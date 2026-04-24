# CareerGo

**Design and Implementation of an LLM-Assisted Career Guidance and Job Pathway Recommender.**

CareerGo is an end-to-end research/engineering project that crawls UK graduate-focused job postings, normalises their skill requirements against the ESCO taxonomy, matches candidates against jobs with a multi-dimensional scoring model, and serves everything through a FastAPI backend and a React / Vite frontend.

---

## 1. Architecture at a glance

```
          +-----------------+      +-------------------+      +---------------------+
          |   Jobs.ac.uk    |      |   Adzuna API      |      |  (optional)         |
          |   RSS + detail  |      |  (UK, gb)         |      |  ESCO / O*NET dumps |
          +--------+--------+      +---------+---------+      +----------+----------+
                   |                         |                           |
                   v                         v                           v
            +--------------------------------------------------+  +-----------------+
            |          Crawler/  (PostgreSQL source tables)    |  | taxonomy_       |
            |     jobs_ac_uk_jobs   |   adzuna_jobs            |  | collector.py    |
            +------------------+---+--+-------------------------+  +--------+--------+
                               |    |                                       |
                               v    v                                       |
                       +-------------------------+      +------------------+ |
                       | merge_jobs.py (JobMerger)|     | esco_skills      |<+
                       |   -> merged_jobs_N       |     | onet_skills      |
                       +------------+-------------+     +---------+--------+
                                    |                             |
                                    v                             v
                       +------------------------------------------------+
                       |   SkillExtraction/  (BERT-NER + MiniLM + fuzzy) |
                       |     -> extracted_job_skills_N                   |
                       |     -> normalized_job_skills_N                  |
                       |     -> (ontology_graph.py -> JSON for D3)       |
                       +------------------------+------------------------+
                                                |
                                                v
                       +------------------------------------------------+
                       |   MatchingRanking/ (JobMatcher, Ranker, LLM)    |
                       |     -> matching_history                         |
                       +------------------------+------------------------+
                                                |
                                                v
                       +-------------------+    |    +---------------------+
                       |  api/  FastAPI    |<---+----+ frontend/ React+Vite|
                       |  JWT / profiles /  |        | (dev: vite proxy)  |
                       |  recommendations  |         |                    |
                       +-------------------+         +--------------------+
```

Main pipeline stages:

1. **Collection** — `Crawler/jobs_ac_uk_rss_crawler.py` and `Crawler/adzuna_crawler.py`
   write raw rows into PostgreSQL.
2. **Merge & dedupe** — `Crawler/merge_jobs.py` normalises fields, computes a
   SHA-256 `dedup_hash` over `title|company|location`, and writes the unified
   `merged_jobs_N` table.
3. **Enrichment (optional)** — `Crawler/enrich_merged_jobs_from_url.py` fetches
   the posting page again and fills `full_description`.
4. **Skill extraction** — `SkillExtraction/integrated_pipeline.py` runs BERT-NER,
   normalises each entity via MiniLM embeddings + fuzzy matching, and writes
   `extracted_job_skills_N` / `normalized_job_skills_N`.
5. **Matching & ranking** — `MatchingRanking/matching_algorithm.py` scores
   `(user, job)` across 6 dimensions; `ranking_system.py` produces a
   multi-objective (relevance / feasibility / growth) ranking with optional
   Pareto-layered sorting and greedy diversity.
6. **Recommendation & explanation** — `MatchingRanking/llm_reasoner.py` and
   `api/recommendations_service.py` generate reasoning (LLM or deterministic
   fallback) and persist to `matching_history`.
7. **Application layer** — `api/app.py` exposes REST endpoints (JWT auth,
   profile, jobs browsing, recommendations); the `frontend/` SPA consumes them.

---

## 2. Repository layout

| Path                  | Responsibility                                                          |
| --------------------- | ----------------------------------------------------------------------- |
| `Crawler/`            | RSS/API crawlers, field normalisation, `JobMerger`, URL enrichment.     |
| `SkillExtraction/`    | ESCO/O\*NET import, NER skill extraction, vector+fuzzy normalisation.   |
| `MatchingRanking/`    | `UserProfile`, `JobMatcher`, `MultiObjectiveRanker`, LLM reasoner, DB.  |
| `api/`                | FastAPI app (auth, profile, jobs, recommendations).                     |
| `frontend/`           | React 18 + Vite 5 SPA.                                                  |
| `requirements.txt`    | Aggregated Python dependencies for the whole backend.                   |
| `.env.example`        | Environment-variable template (copy to `.env`).                         |

---

## 3. Prerequisites

- **Python** 3.9+ (3.10 / 3.11 tested).
- **PostgreSQL** 13+.
- **Node.js** 18+ for the frontend.
- **CUDA GPU** is optional but strongly recommended for the skill pipeline
  (BERT-NER + MiniLM embeddings). CPU-only works too, just slower.
- **Model weights** (downloaded on first run if missing):
  - [`dslim/bert-base-NER`](https://huggingface.co/dslim/bert-base-NER)
    — expected under `SkillExtraction/models/bert-base-NER/`.
  - [`sentence-transformers/all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
    — expected under `SkillExtraction/models/all-MiniLM-L6-v2/`, or set
    `SENTENCE_TRANSFORMER_MODEL` to a HuggingFace Hub identifier.

> The `SkillExtraction/models/` and `SkillExtraction/data/` directories are
> ignored by git — put your local weights / CSV dumps there without worrying
> about accidentally committing them.

---

## 4. Quick start

### 4.1 Clone & configure

```bash
git clone https://github.com/<your-account>/CareerGo.git
cd CareerGo

cp .env.example .env
# Edit .env and set DB_*, ADZUNA_*, DEEPSEEK_* and CAREERGO_JWT_SECRET.
```

### 4.2 Database

```bash
createdb jobs_data                                   # or equivalent GUI step
psql -U $DB_USER -d jobs_data -c "SELECT version();" # sanity-check

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Create the user / matching schema used by MatchingRanking and the API.
python MatchingRanking/init_database.py
```

### 4.3 Crawl + merge + extract

```bash
# 1. Crawl sources (tables are auto-created on first run).
python Crawler/adzuna_crawler.py
python Crawler/jobs_ac_uk_rss_crawler.py

# 2. Merge + dedupe into merged_jobs_3 (default).
python Crawler/merge_jobs.py

# 3. (Optional) re-fetch detail pages to fill full_description.
python Crawler/enrich_merged_jobs_from_url.py

# 4. Extract and normalise skills.
python SkillExtraction/integrated_pipeline.py
```

### 4.4 API + frontend (dev mode)

```bash
# Terminal 1 — FastAPI backend on :8000
uvicorn api.app:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — Vite frontend on :5173 (proxies /api to :8000)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

### 4.5 CLI smoke test (no frontend)

```bash
python MatchingRanking/main_with_db.py
```

This loads user `lzf` (creates a sample if missing), scores every row from
`merged_jobs_3`, ranks the top 10, runs LLM (or deterministic fallback)
reasoning, and writes results to `results_db.json`.

---

## 5. Key configuration

All modules read a shared `.env` at the repo root via `python-dotenv`.

| Variable                        | Default                             | Consumer                                   |
| ------------------------------- | ----------------------------------- | ------------------------------------------ |
| `DB_HOST` / `DB_PORT` / ...     | `localhost` / `5432` / ...          | every module                               |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | *(required to crawl Adzuna)*     | `Crawler/adzuna_crawler.py`                |
| `DEEPSEEK_API_KEY`              | *(unset -> falls back to template)* | `MatchingRanking/llm_reasoner.py`          |
| `DEEPSEEK_BASE_URL`             | `https://api.deepseek.com/v1`       | same                                       |
| `RECOMMEND_USE_LLM`             | `1`                                 | `api/` recommendations                     |
| `CAREERGO_JWT_SECRET`           | `careergo-dev-change-me`            | `api/app.py`                               |
| `CAREERGO_CORS_ORIGINS`         | `http://127.0.0.1:5173,...`         | `api/app.py`                               |
| `MERGED_JOBS_TABLE`             | `merged_jobs_3`                     | Crawler / SkillExtraction / MatchingRanking|
| `EXTRACTED_JOB_SKILLS_TABLE`    | `extracted_job_skills_3`            | SkillExtraction                            |
| `NORMALIZED_JOB_SKILLS_TABLE`   | `normalized_job_skills_3`           | SkillExtraction / MatchingRanking          |
| `SENTENCE_TRANSFORMER_MODEL`    | `SkillExtraction/models/all-MiniLM-L6-v2` | SkillExtraction                      |
| `SKILL_ENABLE_KEYWORD_ENHANCE`  | off                                 | SkillExtraction (slow; full-vocab scan)    |
| `SKILL_PIPELINE_BATCH_SIZE`     | `64`                                | SkillExtraction entrypoint                 |

Tune matcher / ranker weights in `MatchingRanking/config.py` (`MATCHER_CONFIG`,
`RANKER_CONFIG`); defaults match the dissertation:

| Matcher dimension | Default weight |
| ----------------- | -------------- |
| skills            | 0.40           |
| education         | 0.15           |
| experience        | 0.15           |
| preferences       | 0.15           |
| salary            | 0.10           |
| location          | 0.05           |

| Ranker objective | Default weight |
| ---------------- | -------------- |
| relevance        | 0.40           |
| feasibility      | 0.35           |
| growth           | 0.25           |

---

## 6. HTTP API summary

All endpoints live under `/api` and follow OAuth-style `Authorization: Bearer <JWT>` for protected routes. See FastAPI's auto-generated docs at `http://localhost:8000/docs` for request/response schemas.

| Method | Path                                         | Purpose                                         |
| ------ | -------------------------------------------- | ----------------------------------------------- |
| GET    | `/api/health`                                | DB health probe                                 |
| POST   | `/api/auth/register`                         | Create account (JWT returned)                   |
| POST   | `/api/auth/login`                            | Login                                           |
| GET    | `/api/auth/me`                               | Current user                                    |
| GET    | `/api/users/me/profile`                      | Current profile                                 |
| PUT    | `/api/users/me/profile`                      | Upsert profile                                  |
| POST   | `/api/users/me/recommendations`              | Recompute top-K recommendations                 |
| GET    | `/api/users/me/recommendations`              | Latest persisted recommendations                |
| POST   | `/api/users/me/jobs/{job_id}/reasoning`      | On-demand reasoning for one job                 |
| GET    | `/api/users/me/jobs/{job_id}/learning-insights` | Same as above, GET flavour                   |
| GET    | `/api/jobs`                                  | Paginated browsing (filters: keywords, location, ...) |
| GET    | `/api/jobs/{job_id}`                         | Job detail                                      |
| GET    | `/api/jobs/{job_id}/check-url`               | External URL liveness probe                     |
| GET    | `/api/jobs/{job_id}/skill-graph`             | Job ↔ skill ↔ related-role subgraph for D3.js   |
| GET    | `/api/jobs/meta/filters`                     | Distinct sources / job types / locations / categories |
| GET    | `/api/jobs/types`                            | Distinct job-type values                        |

---

## 7. Performance / resource notes

- The full skill pipeline loads **BERT-NER** *and* **MiniLM** in memory; budget
  3–4 GB RAM minimum (4–6 GB more comfortable).
- Inside cgroup-limited containers (≈2 GB) the process can be OOM-killed with
  no Python traceback. Either raise the limit or run `integrated_pipeline.py`
  with smaller `SKILL_PIPELINE_BATCH_SIZE`.
- `recommendations_service` loads **all** rows from the merged table per
  request; this is intentional (constraints are enforced in Python), but the
  LLM step is network-bound — set `RECOMMEND_USE_LLM=0` to skip it during
  local UI testing.

---

## 8. Development

- `python -m py_compile $(git ls-files '*.py')` — quick syntax check.
- Logs are written next to each module (`Crawler/*.log`, `SkillExtraction/logs/`);
  they are gitignored.
- Follow the existing docstring/typing conventions; keep all code and comments
  in English.

---

## 9. Security & secrets

- `.env` is gitignored by default. Do **not** commit real credentials.
- If you previously committed API keys, rotate them before making the repo
  public (Adzuna app key, DeepSeek key, JWT secret).
- Replace `CAREERGO_JWT_SECRET` in production; `openssl rand -hex 32` is a
  reasonable one-liner.

---

## 10. License

Released under the [MIT License](./LICENSE).
