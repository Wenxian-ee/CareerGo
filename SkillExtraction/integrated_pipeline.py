"""
Integrated skill-extraction pipeline.

Glues together `taxonomy_collector`, `entity_extractor_pretrained` and
`skill_normalizer` to extract skills from the job database and standardise
them against ESCO / O*NET vocabularies.

Notes:
- All confidence scores are cast to plain Python ``float`` (not ``numpy.float32``)
  so the psycopg2 drivers can bind them safely.
"""
# TODO: switch to additive imports if table layout changes,
#       so this module does not have to be modified every time.


import logging
from typing import List, Dict, Optional, Tuple
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime
import json
import os
import re
from urllib import error, request
from tqdm import tqdm

from taxonomy_collector import TaxonomyCollector
from entity_extractor_pretrained import PretrainedSkillExtractor
from skill_normalizer import SkillNormalizer
from ontology_graph import SkillOntologyBuilder
from config import (
    DB_CONFIG,
    MODEL_CONFIG,
    NORMALIZATION_CONFIG,
    MERGED_JOBS_TABLE,
    EXTRACTED_JOB_SKILLS_TABLE,
    NORMALIZED_JOB_SKILLS_TABLE,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _requirements_empty_sql(column: str, table_alias: Optional[str] = None) -> str:
    """Predicate: column is unfilled for skill backfill (NULL, '', or JSON empty array)."""
    col = f"{table_alias}.{column}" if table_alias else column
    return (
        f"({col} IS NULL OR TRIM({col}::text) = '' OR TRIM({col}::text) = '[]')"
    )


def _requirements_column_is_nonempty(raw: Optional[str]) -> bool:
    """True if requirements column has user/crawler content (not NULL / '' / '[]')."""
    if raw is None:
        return False
    s = str(raw).strip()
    return bool(s) and s != "[]"


def _split_requirements_phrases(raw: str) -> List[str]:
    """
    Parse requirements field: JSON array of strings, or plain text split on ;/newlines.
    """
    s = (raw or "").strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            arr = json.loads(s)
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except (json.JSONDecodeError, TypeError):
            pass
    parts = re.split(r"[;\n\r]+", s)
    out = [p.strip() for p in parts if p.strip()]
    return out if out else [s]


class IntegratedSkillPipeline:
    """
    Integrated skill extraction pipeline
    Connect job posting database and skill standardization system
    """
    
    def __init__(self, db_config: Dict = None):
        """
        Initialize the pipeline
        
        Args:
            db_config: database configuration
        """
        self.db_config = db_config or DB_CONFIG
        self.llm_fallback_config = self._default_llm_fallback_config()
        
        logger.info("=" * 80)
        logger.info("Initialize the integrated skill extraction pipeline")
        logger.info("=" * 80)
        
        # Initialize the components
        self.taxonomy_collector = TaxonomyCollector(db_config=self.db_config)
        # Keyword enhancement scans the full ~100k ESCO vocabulary per job, which
        # is extremely slow in large batches, so it is disabled by default.
        # Enable with: export SKILL_ENABLE_KEYWORD_ENHANCE=1
        _kw_enhance = os.environ.get(
            "SKILL_ENABLE_KEYWORD_ENHANCE", ""
        ).strip().lower() in ("1", "true", "yes", "on")
        if _kw_enhance:
            logger.warning(
                "SKILL_ENABLE_KEYWORD_ENHANCE is on: keyword pass scans ~100k terms per job — expect much slower runs."
            )
        self.extractor = PretrainedSkillExtractor(
            model_type="pretrained_ner",
            enable_keyword_enhance=_kw_enhance,
        )
        self.normalizer = SkillNormalizer(db_config=self.db_config)
        self.ontology_builder = SkillOntologyBuilder(db_config=self.db_config)
        
        logger.info("Pipeline initialized")
        logger.info("=" * 80)

    def _skill_record_from_entity(self, entity: Dict) -> Optional[Dict]:
        """
        Map one NER entity to a normalized skill row (ESCO/O*NET) or raw fallback.
        """
        if entity.get("type") not in ("SKILL", "TOOL"):
            return None
        raw = (entity.get("text") or "").strip()
        if not raw:
            return None

        matches = self.normalizer.normalize_skill(raw, top_k=1)
        if matches:
            best_match = matches[0]
            sk = best_match["skill"]
            return {
                "raw": raw,
                "type": entity.get("type", ""),
                "confidence": float(entity.get("score", 0.0)),
                "extraction_method": entity.get("method", ""),
                "normalized": sk["name"],
                "similarity": float(best_match["similarity"]),
                "normalization_method": best_match["method"],
                "source": sk["source"],
                "skill_id": sk.get("id"),
                "skill_uri": sk.get("uri", ""),
                "skill_type": sk.get("skill_type", ""),
            }

        cfg = NORMALIZATION_CONFIG
        min_len = int(cfg.get("raw_unmapped_min_len", 4))
        if cfg.get("allow_raw_unmapped", True) and len(raw) >= min_len:
            return {
                "raw": raw,
                "type": entity.get("type", ""),
                "confidence": float(entity.get("score", 0.0)),
                "extraction_method": entity.get("method", ""),
                "normalized": raw,
                "similarity": 0.0,
                "normalization_method": "raw_unmapped",
                "source": "EXTRACTED",
                "skill_id": None,
                "skill_uri": "",
                "skill_type": "",
            }
        return None

    def _skill_record_from_requirements_phrase(self, phrase: str) -> Optional[Dict]:
        """Normalize one phrase from job.requirements (crawler/manual text), no NER."""
        ent = {
            "text": phrase.strip(),
            "type": "SKILL",
            "score": 1.0,
            "method": "requirements_column",
        }
        return self._skill_record_from_entity(ent)

    def _result_normalize_from_requirements_column(
        self, job_id: str, requirements_raw: str
    ) -> Dict:
        """Build pipeline result using only requirements column text → ESCO (no NER)."""
        phrases = _split_requirements_phrases(requirements_raw)
        normalized_skills: List[Dict] = []
        seen_raw = set()
        for phrase in phrases:
            key = phrase.strip().lower()
            if not key or key in seen_raw:
                continue
            seen_raw.add(key)
            rec = self._skill_record_from_requirements_phrase(phrase)
            if rec:
                normalized_skills.append(rec)

        return {
            "job_id": job_id,
            "extracted_entities": [],
            "normalized_skills": normalized_skills,
            "statistics": {
                "total_entities": 0,
                "normalized_skills": len(normalized_skills),
                "by_type": {},
                "mode": "requirements_column_only",
            },
        }

    def _default_llm_fallback_config(self) -> Dict:
        """LLM fallback config for extraction failures."""
        return {
            "enabled": True,
            "model": os.getenv("SKILL_LLM_MODEL", "deepseek-chat"),
            "base_url": os.getenv("SKILL_LLM_BASE_URL", "https://api.deepseek.com"),
            "api_key_env": os.getenv("SKILL_LLM_API_KEY_ENV", "DEEPSEEK_API_KEY"),
            "timeout_seconds": int(os.getenv("SKILL_LLM_TIMEOUT_SECONDS", "20")),
            "max_description_chars": int(os.getenv("SKILL_LLM_MAX_CHARS", "4000")),
            "max_skills": int(os.getenv("SKILL_LLM_MAX_SKILLS", "30")),
            "min_trigger_entities": int(os.getenv("SKILL_LLM_TRIGGER_MIN_ENTITIES", "1")),
        }

    def _extract_entities_with_llm(self, description: str, job_id: str = "") -> List[Dict]:
        """
        Fallback extraction using LLM when rule/NER extraction returns too few entities.
        Returns entities in the same schema as extractor.extract_entities().
        """
        cfg = self.llm_fallback_config
        if not cfg.get("enabled", True):
            return []

        api_key = os.getenv(cfg.get("api_key_env", "DEEPSEEK_API_KEY"))
        if not api_key:
            logger.debug("LLM fallback skipped: API key is not configured")
            return []

        text = (description or "").strip()
        if not text:
            return []

        text = text[: cfg.get("max_description_chars", 4000)]
        max_skills = cfg.get("max_skills", 30)
        prompt = (
            "Extract core job skills/tools from this job description.\n"
            f"Return ONLY a valid JSON array of strings, up to {max_skills} items.\n"
            "No markdown, no explanation.\n\n"
            f"Job description:\n{text}"
        )
        payload = {
            "model": cfg.get("model", "deepseek-chat"),
            "messages": [
                {
                    "role": "system",
                    "content": "You are an information extractor. Output strict JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
        }

        try:
            req = request.Request(
                url=f"{cfg.get('base_url', 'https://api.deepseek.com').rstrip('/')}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            with request.urlopen(req, timeout=cfg.get("timeout_seconds", 20)) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (error.URLError, error.HTTPError, TimeoutError, OSError, json.JSONDecodeError) as e:
            logger.warning(f"LLM fallback extraction failed for job {job_id}: {e}")
            return []

        try:
            content = body["choices"][0]["message"]["content"]
        except Exception:
            logger.warning(f"LLM fallback response format error for job {job_id}")
            return []

        # Robust JSON parsing: accept direct JSON array or array embedded in text.
        skill_items = None
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                skill_items = parsed
        except json.JSONDecodeError:
            m = re.search(r"\[[\s\S]*\]", content)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                    if isinstance(parsed, list):
                        skill_items = parsed
                except json.JSONDecodeError:
                    pass

        if not skill_items:
            return []

        entities: List[Dict] = []
        seen = set()
        for item in skill_items[:max_skills]:
            if isinstance(item, dict):
                raw = item.get("name") or item.get("skill") or ""
            else:
                raw = str(item)
            name = raw.strip()
            key = name.lower()
            if not name or key in seen:
                continue
            seen.add(key)
            entities.append(
                {
                    "text": name,
                    "type": "SKILL",
                    "score": 0.85,
                    "method": "llm_fallback",
                    "focus": "all",
                }
            )

        if entities:
            logger.info(f"LLM fallback extracted {len(entities)} entities for job {job_id}")
        return entities
    
    def setup_taxonomy(self, force_reload: bool = False):
        """
        Setup skill taxonomy system
        
        Args:
            force_reload: whether to force reload ESCO/O*NET data
        """
        logger.info("\n" + "=" * 80)
        logger.info("Step 1: Setup skill taxonomy system")
        logger.info("=" * 80)
        
        # Check if there is data in the database
        if not force_reload and self._check_taxonomy_exists():
            logger.info("Skill taxonomy data already exists, skip loading")
            return
        
        # Collect ESCO and O*NET data
        logger.info("Load skill taxonomy data from local files...")
        self.taxonomy_collector.collect_all()
        
        logger.info("Skill taxonomy system setup completed")
    
    def _check_taxonomy_exists(self) -> bool:
        """Check if there is skill taxonomy data in the database"""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM esco_skills")
            esco_count = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()
            
            logger.info(f"There are {esco_count} ESCO skills in the database")
            return esco_count > 0
            
        except Exception as e:
            logger.warning(f"Failed to check skill taxonomy data: {e}")
            return False
    
    def create_job_skills_table(self):
        """Create job skills association table"""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            ext = EXTRACTED_JOB_SKILLS_TABLE
            norm = NORMALIZED_JOB_SKILLS_TABLE
            idx_e = f"idx_{ext}"
            idx_n = f"idx_{norm}"

            # Extracted raw skills table
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {ext} (
                    id SERIAL PRIMARY KEY,
                    job_id VARCHAR(255) NOT NULL,
                    skill_text TEXT NOT NULL,
                    skill_type VARCHAR(50),
                    confidence_score DECIMAL(5, 4),
                    extraction_method VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(job_id, skill_text)
                )
            """)
            
            # Normalized skills table
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {norm} (
                    id SERIAL PRIMARY KEY,
                    job_id VARCHAR(255) NOT NULL,
                    raw_skill_text TEXT NOT NULL,
                    normalized_skill_name TEXT NOT NULL,
                    similarity_score DECIMAL(5, 4),
                    normalization_method VARCHAR(50),
                    esco_skill_id INTEGER REFERENCES esco_skills(id),
                    onet_skill_id INTEGER REFERENCES onet_skills(id),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(job_id, raw_skill_text, normalized_skill_name)
                )
            """)
            
            # Indexes
            cursor.execute(f"""
                CREATE INDEX IF NOT EXISTS {idx_e}_job_id 
                ON {ext}(job_id)
            """)
            cursor.execute(f"""
                CREATE INDEX IF NOT EXISTS {idx_n}_job_id 
                ON {norm}(job_id)
            """)
            cursor.execute(f"""
                CREATE INDEX IF NOT EXISTS {idx_n}_skill_name 
                ON {norm}(normalized_skill_name)
            """)
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info("Job skills association table created successfully")
            
        except Exception as e:
            logger.error(f"Failed to create job skills association table: {e}")
            raise
    
    def process_job_description(self, job_id: str, description: str) -> Dict:
        """
        Process a single job description
        
        Args:
            job_id: Job ID
            description: Job description text
            
        Returns:
            Result dictionary
        """
        result = {
            'job_id': job_id,
            'extracted_entities': [],
            'normalized_skills': [],
            'statistics': {}
        }
        
        if not description or not description.strip():
            logger.warning(f"Job {job_id} description is empty, skip")
            return result
        
        try:
            # Step 1: Extract entities
            logger.debug(f"Job {job_id}: Extract entities...")
            entities = self.extractor.extract_entities(
                description,
                enhance=True,
                focus="requirements",
            )
            # Fallback: if requirements-focused extraction returns nothing,
            # retry on the full description to improve recall.
            if not entities:
                entities = self.extractor.extract_entities(
                    description,
                    enhance=True,
                    focus="all",
                )
            if len(entities) < self.llm_fallback_config.get("min_trigger_entities", 1):
                llm_entities = self._extract_entities_with_llm(description, job_id=job_id)
                if llm_entities:
                    entities = llm_entities
            result['extracted_entities'] = entities
            
            # Step 2: Normalize skills
            logger.debug(f"Job {job_id}: Normalize skills...")
            for entity in entities:
                rec = self._skill_record_from_entity(entity)
                if rec:
                    result["normalized_skills"].append(rec)
            
            # Statistics    
            result['statistics'] = {
                'total_entities': len(entities),
                'normalized_skills': len(result['normalized_skills']),
                'by_type': {}
            }
            
            for entity in entities:
                entity_type = entity['type']
                result['statistics']['by_type'][entity_type] = \
                    result['statistics']['by_type'].get(entity_type, 0) + 1
            
            logger.debug(f"Job {job_id} processing completed: "
                        f"Extracted {len(entities)} entities, "
                        f"Normalized {len(result['normalized_skills'])} skills")
            
        except Exception as e:
            logger.error(f"Error processing job {job_id}: {e}")
            result['error'] = str(e)
        
        return result

    def _build_requirements_text_from_normalized(self, normalized_skills: List[Dict]) -> str:
        """
        Serialize normalized skills list to requirements text (deduplicated).
        Used to backfill the requirements field in the job table.
        """
        if not normalized_skills:
            return ""

        seen = set()
        ordered = []
        for skill in normalized_skills:
            name = (skill.get('normalized') or "").strip()
            key = name.lower()
            if not name or key in seen:
                continue
            seen.add(key)
            ordered.append(name)

        return "; ".join(ordered)

    def _build_requirements_text(
        self,
        normalized_skills: List[Dict],
        extracted_entities: Optional[List[Dict]] = None,
    ) -> str:
        """
        Build requirements text with fallback:
        1) normalized skills (preferred)
        2) extracted SKILL/TOOL entities (fallback)
        """
        requirements_text = self._build_requirements_text_from_normalized(normalized_skills)
        if requirements_text:
            return requirements_text

        if not extracted_entities:
            return ""

        seen = set()
        ordered = []
        for ent in extracted_entities:
            if ent.get('type') not in ['SKILL', 'TOOL']:
                continue
            name = (ent.get('text') or "").strip()
            key = name.lower()
            if not name or key in seen:
                continue
            seen.add(key)
            ordered.append(name)

        return "; ".join(ordered)

    def _get_existing_columns(self, table_name: str) -> set:
        """Get the existing column names set of the specified table."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = %s
                """,
                (table_name,),
            )
            columns = {row[0] for row in cursor.fetchall()}
            cursor.close()
            conn.close()
            return columns
        except Exception as e:
            logger.error(f"Failed to get the column names set of the table {table_name}: {e}")
            return set()

    def _update_job_requirements(
        self,
        table_name: str,
        job_id_column: str,
        requirements_column: str,
        job_id: str,
        requirements_text: str,
    ):
        """
        Backfill the normalized skills to the job table requirements field.
        Only backfill when the requirements is originally empty, to avoid overwriting the manually/scraped results.
        """
        if not requirements_text:
            return

        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute(
                f"""
                UPDATE {table_name}
                SET {requirements_column} = %s
                WHERE {job_id_column} = %s
                  AND ({_requirements_empty_sql(requirements_column)})
                """,
                (requirements_text, job_id),
            )
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to backfill the requirements of job {job_id}: {e}")
    
    def save_job_skills(self, result: Dict):
        """
        Save job skills to the database
        
        Args:
            result: the result returned by process_job_description
        """
        if 'error' in result:
            return
        
        job_id = result['job_id']
        
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Save extracted raw skills
            if result['extracted_entities']:
                extracted_values = []
                for entity in result['extracted_entities']:
                    extracted_values.append((
                        job_id,
                        entity['text'],
                        entity['type'],
                        float(entity['score']),  # Convert to Python float
                        entity['method']
                    ))
                
                execute_values(cursor, f"""
                    INSERT INTO {EXTRACTED_JOB_SKILLS_TABLE} 
                    (job_id, skill_text, skill_type, confidence_score, extraction_method)
                    VALUES %s
                    ON CONFLICT (job_id, skill_text) DO UPDATE SET
                        skill_type = EXCLUDED.skill_type,
                        confidence_score = EXCLUDED.confidence_score,
                        extraction_method = EXCLUDED.extraction_method
                """, extracted_values)
            
            # Save normalized skills
            if result['normalized_skills']:
                normalized_values = []
                for skill in result['normalized_skills']:
                    # Select the corresponding ID based on the source
                    esco_id = skill.get("skill_id") if skill.get("source") == "ESCO" else None
                    onet_id = skill.get("skill_id") if skill.get("source") == "ONET" else None
                    
                    normalized_values.append((
                        job_id,
                        skill['raw'],
                        skill['normalized'],
                        float(skill['similarity']),  # Convert to Python float
                        skill['normalization_method'],
                        esco_id,
                        onet_id
                    ))
                
                execute_values(cursor, f"""
                    INSERT INTO {NORMALIZED_JOB_SKILLS_TABLE} 
                    (job_id, raw_skill_text, normalized_skill_name, 
                     similarity_score, normalization_method, 
                     esco_skill_id, onet_skill_id)
                    VALUES %s
                    ON CONFLICT (job_id, raw_skill_text, normalized_skill_name) DO UPDATE SET
                        similarity_score = EXCLUDED.similarity_score,
                        normalization_method = EXCLUDED.normalization_method,
                        esco_skill_id = EXCLUDED.esco_skill_id,
                        onet_skill_id = EXCLUDED.onet_skill_id
                """, normalized_values)
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.debug(f"Job {job_id} skills saved successfully")
            
        except Exception as e:
            logger.error(f"Failed to save job {job_id} skills: {e}")

    def save_job_skills_batch(self, results: List[Dict]):
        """
        Persist skills for multiple jobs in a single transaction to avoid the
        per-job connect/commit overhead when writing many rows.
        """
        if not results:
            return
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            ext = EXTRACTED_JOB_SKILLS_TABLE
            norm = NORMALIZED_JOB_SKILLS_TABLE
            for result in results:
                if "error" in result:
                    continue
                job_id = result["job_id"]
                if result.get("extracted_entities"):
                    extracted_values = []
                    for entity in result["extracted_entities"]:
                        extracted_values.append(
                            (
                                job_id,
                                entity["text"],
                                entity["type"],
                                float(entity["score"]),
                                entity["method"],
                            )
                        )
                    execute_values(
                        cursor,
                        f"""
                        INSERT INTO {ext}
                        (job_id, skill_text, skill_type, confidence_score, extraction_method)
                        VALUES %s
                        ON CONFLICT (job_id, skill_text) DO UPDATE SET
                            skill_type = EXCLUDED.skill_type,
                            confidence_score = EXCLUDED.confidence_score,
                            extraction_method = EXCLUDED.extraction_method
                        """,
                        extracted_values,
                    )
                if result.get("normalized_skills"):
                    normalized_values = []
                    for skill in result["normalized_skills"]:
                        esco_id = (
                            skill.get("skill_id") if skill.get("source") == "ESCO" else None
                        )
                        onet_id = (
                            skill.get("skill_id") if skill.get("source") == "ONET" else None
                        )
                        normalized_values.append(
                            (
                                job_id,
                                skill["raw"],
                                skill["normalized"],
                                float(skill["similarity"]),
                                skill["normalization_method"],
                                esco_id,
                                onet_id,
                            )
                        )
                    execute_values(
                        cursor,
                        f"""
                        INSERT INTO {norm}
                        (job_id, raw_skill_text, normalized_skill_name,
                         similarity_score, normalization_method,
                         esco_skill_id, onet_skill_id)
                        VALUES %s
                        ON CONFLICT (job_id, raw_skill_text, normalized_skill_name) DO UPDATE SET
                            similarity_score = EXCLUDED.similarity_score,
                            normalization_method = EXCLUDED.normalization_method,
                            esco_skill_id = EXCLUDED.esco_skill_id,
                            onet_skill_id = EXCLUDED.onet_skill_id
                        """,
                        normalized_values,
                    )
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Batch save job skills failed: {e}")

    def update_job_requirements(
        self,
        job_table: str,
        job_id_column: str,
        requirements_column: str,
        job_id: str,
        normalized_skills: List[Dict],
    ):
        """
        Backfill the normalized skills to the job table requirements field.
        The requirements is written in JSON array string format (TEXT column compatible).
        """
        skill_names = sorted(
            list(
                {
                    s["normalized"].strip()
                    for s in normalized_skills
                    if s.get("normalized") and s["normalized"].strip()
                }
            )
        )
        if not skill_names:
            return

        requirements_json = json.dumps(skill_names, ensure_ascii=False)

        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute(
                f"""
                UPDATE {job_table}
                SET {requirements_column} = %s
                WHERE {job_id_column}::text = %s
                """,
                (requirements_json, str(job_id)),
            )
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to backfill the requirements of job {job_id}: {e}")

    def update_job_requirements_batch(
        self,
        job_table: str,
        job_id_column: str,
        requirements_column: str,
        items: List[Tuple[str, List[Dict]]],
    ):
        """
        Batch backfill the ``requirements`` column with a JSON-array string.
        Multiple UPDATE statements run on a single connection/transaction.
        items: list of (job_id, normalized_skills_list) tuples.
        """
        if not items:
            return
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            for job_id, normalized_skills in items:
                skill_names = sorted(
                    list(
                        {
                            s["normalized"].strip()
                            for s in normalized_skills
                            if s.get("normalized") and s["normalized"].strip()
                        }
                    )
                )
                if not skill_names:
                    continue
                requirements_json = json.dumps(skill_names, ensure_ascii=False)
                cursor.execute(
                    f"""
                    UPDATE {job_table}
                    SET {requirements_column} = %s
                    WHERE {job_id_column}::text = %s
                    """,
                    (requirements_json, str(job_id)),
                )
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Batch backfill requirements failed: {e}")

    def process_and_backfill_requirements(
        self,
        table_name: str = MERGED_JOBS_TABLE,
        job_id_column: str = "job_id",
        description_column: str = "description",
        full_description_column: str = "full_description",
        requirements_column: str = "requirements",
        only_null_requirements: bool = True,
        limit: int = None,
        batch_size: int = 10,
    ) -> List[Dict]:
        """
        Full pipeline:
          1) Read job text from ``description`` / ``full_description`` (and
             ``requirements`` when present).
          2) Extract requirement-oriented skills via NER, unless the row already
             has a non-empty ``requirements`` column and is only missing
             normalization.
          3) Normalize to ESCO / O*NET.
          4) Write to ``extracted_job_skills`` / ``normalized_job_skills``.
          5) Backfill the job-table ``requirements`` column.

        When ``job.requirements`` already contains crawler/manual text but
        ``normalized_job_skills`` has no row, the pipeline splits that column
        and runs normalization only (no NER).
        """
        logger.info("\n" + "=" * 80)
        logger.info("Full pipeline: Extract + Normalize + Backfill requirements")
        logger.info("=" * 80)

        where_clauses = [
            "("
            f"(t.{full_description_column} IS NOT NULL AND TRIM(t.{full_description_column}::text) <> '') "
            f"OR (t.{description_column} IS NOT NULL AND TRIM(t.{description_column}::text) <> '') "
            f"OR (t.{requirements_column} IS NOT NULL AND TRIM(t.{requirements_column}::text) <> '' "
            f"AND TRIM(t.{requirements_column}::text) <> '[]')"
            ")",
        ]
        if only_null_requirements:
            where_clauses.append(
                "("
                f"{_requirements_empty_sql(requirements_column, 't')} "
                f"OR NOT EXISTS (SELECT 1 FROM {NORMALIZED_JOB_SKILLS_TABLE} n "
                f"WHERE n.job_id = t.{job_id_column}::text)"
                ")"
            )

        query = f"""
            SELECT t.{job_id_column},
                   t.{description_column},
                   t.{full_description_column},
                   t.{requirements_column},
                   EXISTS (
                       SELECT 1
                       FROM {NORMALIZED_JOB_SKILLS_TABLE} n
                       WHERE n.job_id = t.{job_id_column}::text
                   ) AS has_normalized
            FROM {table_name} t
            WHERE {' AND '.join(where_clauses)}
        """
        if limit:
            query += f" LIMIT {limit}"

        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute(query)
            jobs = cursor.fetchall()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to load job data: {e}")
            return []

        jobs_needing_extraction = sum(1 for row in jobs if not row[4])
        logger.info(
            f"Number of jobs fetched: {len(jobs)}; needing extraction: {jobs_needing_extraction}"
        )
        if not jobs:
            return []

        results: List[Dict] = []

        # 1) For already normalized jobs: only backfill requirements
        pending_ner: List[Dict] = []
        pending_req_only: List[Dict] = []
        for job_id, description, full_description, requirements_raw, has_normalized in jobs:
            job_id = str(job_id)
            if has_normalized:
                normalized_skills = self.get_normalized_job_skills(job_id)
                self.update_job_requirements(
                    job_table=table_name,
                    job_id_column=job_id_column,
                    requirements_column=requirements_column,
                    job_id=job_id,
                    normalized_skills=normalized_skills,
                )
                continue

            if _requirements_column_is_nonempty(requirements_raw):
                pending_req_only.append({
                    "job_id": job_id,
                    "requirements_raw": requirements_raw,
                })
                continue

            text = full_description if full_description and str(full_description).strip() else description
            pending_ner.append({
                "job_id": job_id,
                "text": text or "",
            })

        # 1b) Normalize-only path: split the requirements column into phrases
        #     and map each phrase to ESCO directly (no NER).
        processed_count = 0
        if pending_req_only:
            logger.info(
                "Jobs with existing requirements text, normalize only (no NER): %s",
                len(pending_req_only),
            )
            with tqdm(
                total=len(pending_req_only),
                desc="Normalize from requirements column",
                unit="job",
                dynamic_ncols=True,
            ) as pbar:
                for item in pending_req_only:
                    job_id = item["job_id"]
                    result = self._result_normalize_from_requirements_column(
                        job_id, str(item["requirements_raw"])
                    )
                    self.save_job_skills(result)
                    self.update_job_requirements(
                        job_table=table_name,
                        job_id_column=job_id_column,
                        requirements_column=requirements_column,
                        job_id=job_id,
                        normalized_skills=result.get("normalized_skills", []),
                    )
                    results.append(result)
                    processed_count += 1
                    pbar.update(1)
                    if processed_count % batch_size == 0 or processed_count == 1:
                        logger.info(
                            "Requirements-only normalization progress: %s/%s",
                            processed_count,
                            len(pending_req_only),
                        )

        # 2) Batch extract + normalize: when the requirements column is empty,
        #    run NER against the description text.
        if pending_ner:
            ner_processed = 0
            with tqdm(
                total=len(pending_ner),
                desc="Processing jobs (NER)",
                unit="job",
                dynamic_ncols=True,
            ) as pbar:
                for i in range(0, len(pending_ner), batch_size):
                    chunk = pending_ner[i:i + batch_size]
                    chunk_texts = [item["text"] for item in chunk]

                    # First pass: requirements-focused extraction. ner_batch_size
                    # is decoupled from chunk size so we can saturate the GPU.
                    ner_bs = max(
                        batch_size,
                        int(MODEL_CONFIG.get("pretrained_ner", {}).get("batch_size", 16)),
                    )
                    entities_batch = self.extractor.extract_entities_batch(
                        chunk_texts,
                        enhance=True,
                        focus="requirements",
                        ner_batch_size=ner_bs,
                    )

                    # Fallback per item: if empty, extract from full text
                    for idx, entities in enumerate(entities_batch):
                        if entities:
                            continue
                        entities_batch[idx] = self.extractor.extract_entities(
                            chunk_texts[idx],
                            enhance=True,
                            focus="all",
                        )
                        if len(entities_batch[idx]) < self.llm_fallback_config.get("min_trigger_entities", 1):
                            llm_entities = self._extract_entities_with_llm(
                                chunk_texts[idx],
                                job_id=chunk[idx]["job_id"],
                            )
                            if llm_entities:
                                entities_batch[idx] = llm_entities

                    chunk_results: List[Dict] = []
                    for item, entities in zip(chunk, entities_batch):
                        job_id = item["job_id"]
                        result = {
                            "job_id": job_id,
                            "extracted_entities": entities,
                            "normalized_skills": [],
                            "statistics": {},
                        }

                        for entity in entities:
                            rec = self._skill_record_from_entity(entity)
                            if rec:
                                result["normalized_skills"].append(rec)

                        result["statistics"] = {
                            "total_entities": len(entities),
                            "normalized_skills": len(result["normalized_skills"]),
                            "by_type": {},
                        }
                        for entity in entities:
                            t = entity.get("type", "UNKNOWN")
                            result["statistics"]["by_type"][t] = result["statistics"]["by_type"].get(t, 0) + 1

                        chunk_results.append(result)
                        results.append(result)
                        ner_processed += 1
                        pbar.update(1)

                    self.save_job_skills_batch(chunk_results)
                    self.update_job_requirements_batch(
                        table_name,
                        job_id_column,
                        requirements_column,
                        [
                            (r["job_id"], r.get("normalized_skills", []))
                            for r in chunk_results
                        ],
                    )

                    if ner_processed % batch_size == 0 or ner_processed == 1:
                        logger.info(
                            "NER pipeline progress: %s/%s",
                            ner_processed,
                            len(pending_ner),
                        )

        self._print_final_statistics(results)
        return results
    
    def process_all_jobs(self, 
                        table_name: str = MERGED_JOBS_TABLE,
                        job_id_column: str = 'job_id',
                        description_column: str = 'description',
                        description_columns: Optional[List[str]] = None,
                        requirements_column: str = 'requirements',
                        fill_requirements: bool = True,
                        limit: int = None,
                        batch_size: int = 10):
        """
        Process all jobs in the database
        
        Args:
            table_name: Job table name
            job_id_column: Job ID column name
            description_column: Job description column name
            description_columns: Candidate description columns (by priority), e.g. ['full_description', 'description']
            requirements_column: Column name to backfill requirements
            fill_requirements: Whether to backfill normalized skills to the job table requirements column
            limit: Limit the number of jobs to process
            batch_size: Batch size (for logging output)
        """
        logger.info("\n" + "=" * 80)
        logger.info("Step 2: Batch process job data")
        logger.info("=" * 80)
        
        try:
            table_columns = self._get_existing_columns(table_name)
            if not table_columns:
                logger.error(f"Failed to read the column information of the table {table_name}, stop processing")
                return []

            candidate_description_columns = description_columns or [description_column]
            if description_columns is None and description_column == 'description':
                candidate_description_columns = ['full_description', 'description']

            available_description_columns = [
                col for col in candidate_description_columns if col in table_columns
            ]
            if not available_description_columns:
                logger.error(
                    f"No available description columns found in the table {table_name}. Candidate columns: {candidate_description_columns}"
                )
                return []

            can_fill_requirements = (
                fill_requirements and
                requirements_column in table_columns
            )
            if fill_requirements and not can_fill_requirements:
                logger.warning(
                    f"The table {table_name} does not have the column {requirements_column}, will skip backfilling requirements"
                )

            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Build query
            select_description_expr = ", ".join([f"t.{col}" for col in available_description_columns])
            where_non_empty_desc = " OR ".join(
                [f"(t.{col} IS NOT NULL AND t.{col} != '')" for col in available_description_columns]
            )
            normalized_exists_sql = (
                f"EXISTS ("
                f"SELECT 1 FROM {NORMALIZED_JOB_SKILLS_TABLE} n "
                f"WHERE n.job_id = t.{job_id_column}::text"
                f")"
            )
            requirements_empty_expr = _requirements_empty_sql(requirements_column, "t")

            # Incremental mode: only extract jobs that are not yet normalized.
            # If requirements-backfill is enabled, already-normalized rows are
            # still visited to top up the requirements column (but extraction
            # / normalization are skipped for them).
            if can_fill_requirements:
                processed_filter_sql = f"({requirements_empty_expr} OR NOT {normalized_exists_sql})"
            else:
                processed_filter_sql = f"NOT {normalized_exists_sql}"

            query = f"""
                SELECT t.{job_id_column}, {select_description_expr},
                       {normalized_exists_sql} AS has_normalized
                FROM {table_name} t
                WHERE ({where_non_empty_desc})
                  AND {processed_filter_sql}
            """
            if limit:
                query += f" LIMIT {limit}"
            
            logger.info(f"Loading job data from table {table_name}...")
            cursor.execute(query)
            jobs = cursor.fetchall()
            
            cursor.close()
            conn.close()
            
            jobs_needing_extraction = sum(1 for row in jobs if not row[-1])
            logger.info(
                f"Number of jobs fetched: {len(jobs)}; needing extraction: {jobs_needing_extraction}"
            )
            
            if not jobs:
                logger.warning("No job data found, please check the table name and column names")
                return []
            
            # Batch process: only extract/normalize jobs that are missing from
            # normalized_job_skills.
            results: List[Dict] = []
            processed_count = 0
            for row in jobs:
                job_id = str(row[0])
                has_normalized = bool(row[-1])
                descriptions = row[1:-1]

                # Already normalized: only backfill the requirements column.
                if has_normalized:
                    if can_fill_requirements:
                        normalized_skills = self.get_normalized_job_skills(job_id)
                        requirements_text = self._build_requirements_text(
                            normalized_skills=normalized_skills,
                            extracted_entities=[],
                        )
                        self._update_job_requirements(
                            table_name=table_name,
                            job_id_column=job_id_column,
                            requirements_column=requirements_column,
                            job_id=job_id,
                            requirements_text=requirements_text,
                        )
                    continue

                # Extraction needed: pick the highest-priority non-empty description.
                description = ""
                for text in descriptions:
                    if text and str(text).strip():
                        description = str(text)
                        break

                result = self.process_job_description(job_id, description)
                results.append(result)
                self.save_job_skills(result)

                if can_fill_requirements:
                    requirements_text = self._build_requirements_text(
                        normalized_skills=result.get('normalized_skills', []),
                        extracted_entities=result.get('extracted_entities', []),
                    )
                    self._update_job_requirements(
                        table_name=table_name,
                        job_id_column=job_id_column,
                        requirements_column=requirements_column,
                        job_id=job_id,
                        requirements_text=requirements_text,
                    )

                processed_count += 1
                if processed_count % batch_size == 0 or processed_count == 1:
                    logger.info(
                        f"Processing progress: {processed_count}/{jobs_needing_extraction}"
                    )
                if processed_count % batch_size == 0:
                    self._print_batch_statistics(
                        results[-batch_size:], processed_count, jobs_needing_extraction
                    )
            
            # Final statistics
            self._print_final_statistics(results)
            
            return results
            
        except Exception as e:
            logger.error(f"Error batch processing: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def _print_batch_statistics(self, results: List[Dict], current: int, total: int):
        """Print batch statistics"""
        total_entities = sum(r['statistics'].get('total_entities', 0) for r in results)
        total_normalized = sum(r['statistics'].get('normalized_skills', 0) for r in results)
        
        logger.info(f"   Batch statistics ({current}/{total}): "
                   f"Extracted {total_entities} entities, "
                   f"Normalized {total_normalized} skills")
    
    def _print_final_statistics(self, results: List[Dict]):
        """Print final statistics"""
        logger.info("\n" + "=" * 80)
        logger.info("Final statistics")
        logger.info("=" * 80)
        
        total_jobs = len(results)
        total_entities = sum(r['statistics'].get('total_entities', 0) for r in results)
        total_normalized = sum(r['statistics'].get('normalized_skills', 0) for r in results)
        
        logger.info(f"Number of jobs to process: {total_jobs}")
        logger.info(f"Total number of entities extracted: {total_entities}")
        logger.info(f"Total number of normalized skills: {total_normalized}")
        
        if total_jobs > 0:
            logger.info(f"Average number of entities extracted per job: {total_entities / total_jobs:.2f}")
            logger.info(f"Average number of normalized skills per job: {total_normalized / total_jobs:.2f}")
        
        # By type statistics
        type_counts = {}
        for result in results:
            for entity_type, count in result['statistics'].get('by_type', {}).items():
                type_counts[entity_type] = type_counts.get(entity_type, 0) + count
        
        if type_counts:
            logger.info("\nBy entity type statistics:")
            for entity_type, count in sorted(type_counts.items(), 
                                            key=lambda x: x[1], reverse=True):
                logger.info(f"  {entity_type}: {count}")
        
        logger.info("=" * 80)
    
    def get_job_skills(self, job_id: str) -> Dict:
        """
        Get all skills of a job
        
        Args:
            job_id: Job ID
            
        Returns:
            Dictionary containing raw skills and normalized skills
        """
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Get extracted raw skills
            cursor.execute(f"""
                SELECT skill_text, skill_type, confidence_score, extraction_method
                FROM {EXTRACTED_JOB_SKILLS_TABLE}
                WHERE job_id = %s
            """, (job_id,))
            
            extracted = []
            for row in cursor.fetchall():
                extracted.append({
                    'text': row[0],
                    'type': row[1],
                    'confidence': float(row[2]) if row[2] else 0,
                    'method': row[3]
                })
            
            # Get normalized skills
            cursor.execute(f"""
                SELECT raw_skill_text, normalized_skill_name, 
                       similarity_score, normalization_method,
                       esco_skill_id, onet_skill_id
                FROM {NORMALIZED_JOB_SKILLS_TABLE}
                WHERE job_id = %s
            """, (job_id,))
            
            normalized = []
            for row in cursor.fetchall():
                normalized.append({
                    'raw': row[0],
                    'normalized': row[1],
                    'similarity': float(row[2]) if row[2] else 0,
                    'method': row[3],
                    'esco_id': row[4],
                    'onet_id': row[5]
                })
            
            cursor.close()
            conn.close()
            
            return {
                'job_id': job_id,
                'extracted_skills': extracted,
                'normalized_skills': normalized
            }
            
        except Exception as e:
            logger.error(f"Failed to get skills of job {job_id}: {e}")
            return {'job_id': job_id, 'extracted_skills': [], 'normalized_skills': []}

    def get_normalized_job_skills(self, job_id: str) -> List[Dict]:
        """
        Only fetch normalized skills of a job.
        Used for incremental/skip logic when extraction is already done.
        """
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()

            cursor.execute(f"""
                SELECT raw_skill_text, normalized_skill_name,
                       similarity_score, normalization_method,
                       esco_skill_id, onet_skill_id
                FROM {NORMALIZED_JOB_SKILLS_TABLE}
                WHERE job_id = %s
            """, (job_id,))

            normalized = []
            for row in cursor.fetchall():
                normalized.append({
                    'raw': row[0],
                    'normalized': row[1],
                    'similarity': float(row[2]) if row[2] else 0,
                    'method': row[3],
                    'esco_id': row[4],
                    'onet_id': row[5]
                })

            cursor.close()
            conn.close()
            return normalized

        except Exception as e:
            logger.error(f"Failed to get normalized skills of job {job_id}: {e}")
            return []
    
    def get_skill_statistics(self) -> Dict:
        """Get overall skill statistics"""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            stats = {}
            
            # Total number of jobs
            cursor.execute(f"SELECT COUNT(DISTINCT job_id) FROM {EXTRACTED_JOB_SKILLS_TABLE}")
            stats['total_jobs'] = cursor.fetchone()[0]
            
            # Total number of extracted skills
            cursor.execute(f"SELECT COUNT(*) FROM {EXTRACTED_JOB_SKILLS_TABLE}")
            stats['total_extracted'] = cursor.fetchone()[0]
            
            # Unique number of skills
            cursor.execute(f"SELECT COUNT(DISTINCT skill_text) FROM {EXTRACTED_JOB_SKILLS_TABLE}")
            stats['unique_extracted'] = cursor.fetchone()[0]
            
            # Total number of normalized skills
            cursor.execute(f"SELECT COUNT(*) FROM {NORMALIZED_JOB_SKILLS_TABLE}")
            stats['total_normalized'] = cursor.fetchone()[0]
            
            # Unique number of normalized skills
            cursor.execute(f"SELECT COUNT(DISTINCT normalized_skill_name) FROM {NORMALIZED_JOB_SKILLS_TABLE}")
            stats['unique_normalized'] = cursor.fetchone()[0]
            
            # Average similarity
            cursor.execute(f"SELECT AVG(similarity_score) FROM {NORMALIZED_JOB_SKILLS_TABLE}")
            avg_sim = cursor.fetchone()[0]
            stats['avg_similarity'] = float(avg_sim) if avg_sim else 0
            
            # Most common skills
            cursor.execute(f"""
                SELECT normalized_skill_name, COUNT(*) as count
                FROM {NORMALIZED_JOB_SKILLS_TABLE}
                GROUP BY normalized_skill_name
                ORDER BY count DESC
                LIMIT 10
            """)
            stats['top_skills'] = [
                {'skill': row[0], 'count': row[1]} 
                for row in cursor.fetchall()
            ]
            
            cursor.close()
            conn.close()
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}

    def construct_skill_ontology_graph(
        self,
        job_table: str = MERGED_JOBS_TABLE,
        job_id_column: str = "job_id",
        title_column: str = "title",
        limit_jobs: int = 200,
        similarity_threshold: float = 0.3,
    ) -> Dict:
        """
        Build a sample skill ontology graph.

        Kept for backward compatibility with older callers; delegates the real
        work to :class:`SkillOntologyBuilder`.
        """
        return self.ontology_builder.construct_skill_ontology_graph(
            job_table=job_table,
            job_id_column=job_id_column,
            title_column=title_column,
            limit_jobs=limit_jobs,
            similarity_threshold=similarity_threshold,
        )


def main():
    """Main function - full pipeline example"""
    
    # Create pipeline
    pipeline = IntegratedSkillPipeline()
    
    # Step 1: Setup skill taxonomy system (first run only)
    pipeline.setup_taxonomy(force_reload=False)
    
    # Create job skills association table
    pipeline.create_job_skills_table()
    
    # Step 2: Full pipeline (extract + normalize + backfill requirements)
    # Note: Please modify the parameters according to your actual table name and column name
    # Number of jobs processed per batch. Larger batches improve NER GPU
    # utilisation; 48/64 is a reasonable starting point when VRAM allows.
    pipeline_bs = int(os.environ.get("SKILL_PIPELINE_BATCH_SIZE", "64"))
    results = pipeline.process_and_backfill_requirements(
        table_name=MERGED_JOBS_TABLE,
        job_id_column='job_id',
        description_column='description',
        full_description_column='full_description',
        requirements_column='requirements',
        only_null_requirements=True,   # Only backfill requirements that are originally empty
        limit=None,                    # Run all jobs
        batch_size=pipeline_bs,
    )
    
    # Step 3: View statistics
    stats = pipeline.get_skill_statistics()
    
    logger.info("\n" + "=" * 80)
    logger.info("Overall statistics")
    logger.info("=" * 80)
    logger.info(f"Total number of jobs: {stats.get('total_jobs', 0)}")
    logger.info(f"Total number of extracted skills: {stats.get('total_extracted', 0)}")
    logger.info(f"Unique number of skills: {stats.get('unique_extracted', 0)}")
    logger.info(f"Total number of normalized skills: {stats.get('total_normalized', 0)}")
    logger.info(f"Unique number of normalized skills: {stats.get('unique_normalized', 0)}")
    logger.info(f"Average similarity: {stats.get('avg_similarity', 0):.3f}")
    
    if stats.get('top_skills'):
        logger.info("\nMost common 10 skills:")
        for i, skill_info in enumerate(stats['top_skills'], 1):
            logger.info(f"  {i}. {skill_info['skill']}: {skill_info['count']} times")
    
    logger.info("=" * 80)

    # Step 4: Build example skill ontology graph
    try:
        ontology_graph = pipeline.construct_skill_ontology_graph(
            job_table=MERGED_JOBS_TABLE,
            job_id_column='job_id',
            title_column='title',
            limit_jobs=200,
            similarity_threshold=0.3,
        )
        logger.info("Example ontology graph node/edge statistics:")
        logger.info(f"  Job nodes: {len(ontology_graph['jobs'])}")
        logger.info(f"  Skill nodes: {len(ontology_graph['skills'])}")
        logger.info(f"  Job-Skill edges: {len(ontology_graph['edges']['job_skill'])}")
        logger.info(f"  Related roles edges: {len(ontology_graph['edges']['related_roles'])}")
    except Exception as e:
        logger.error(f"Failed to build example skill ontology graph: {e}")


if __name__ == "__main__":
    main()
