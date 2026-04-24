"""
CareerGo HTTP API: auth, full profile (aligned with user_profile.UserProfile), recommendations (main_with_db flow).
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests as http_requests
import jwt
from psycopg2.extras import RealDictCursor
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from jwt.exceptions import InvalidTokenError

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "MatchingRanking") not in sys.path:
    sys.path.insert(0, str(ROOT / "MatchingRanking"))

from config import DATABASE_CONFIG, MERGED_JOBS_TABLE  # noqa: E402
from database import (  # noqa: E402
    DatabaseManager,
    dedupe_filter_labels,
    sanitize_category_dropdown_labels,
)

from profile_bridge import dict_to_user_profile  # noqa: E402
from recommendations_service import (  # noqa: E402
    compute_and_persist_recommendations,
    compute_job_reasoning_for_user,
)
from main_with_db import convert_db_job_to_dict, format_job_salary  # noqa: E402

JWT_SECRET = os.getenv("CAREERGO_JWT_SECRET", "careergo-dev-change-me")
JWT_ALG = "HS256"
JWT_EXPIRE_DAYS = 7

# pbkdf2_sha256 avoids bcrypt/passlib version mismatches on some systems
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def _ensure_schema(db: DatabaseManager) -> None:
    conn = db.get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);
            """
        )
        cur.execute(
            """
            ALTER TABLE user_constraints ADD COLUMN IF NOT EXISTS max_commute_time INTEGER;
            """
        )
        cur.execute(
            """
            ALTER TABLE matching_history ADD COLUMN IF NOT EXISTS explanation TEXT;
            """
        )
        cur.execute(
            """
            ALTER TABLE matching_history ADD COLUMN IF NOT EXISTS reasoning_json JSONB;
            """
        )
        cur.execute(
            """
            ALTER TABLE matching_history ADD COLUMN IF NOT EXISTS score_breakdown_json JSONB;
            """
        )
        cur.execute(
            f"""
            ALTER TABLE {MERGED_JOBS_TABLE} ADD COLUMN IF NOT EXISTS required_education TEXT;
            """
        )
        cur.execute(
            f"""
            ALTER TABLE {MERGED_JOBS_TABLE} ADD COLUMN IF NOT EXISTS required_experience_years FLOAT;
            """
        )
        cur.execute(
            f"""
            ALTER TABLE {MERGED_JOBS_TABLE} ADD COLUMN IF NOT EXISTS company_size TEXT;
            """
        )
        cur.execute(
            f"""
            ALTER TABLE {MERGED_JOBS_TABLE} ADD COLUMN IF NOT EXISTS industry TEXT;
            """
        )
        cur.execute(
            f"""
            ALTER TABLE {MERGED_JOBS_TABLE} ADD COLUMN IF NOT EXISTS company_type TEXT;
            """
        )
        cur.execute(
            f"""
            ALTER TABLE {MERGED_JOBS_TABLE} ADD COLUMN IF NOT EXISTS view_count INTEGER;
            """
        )
        cur.execute(
            f"""
            ALTER TABLE {MERGED_JOBS_TABLE} ADD COLUMN IF NOT EXISTS application_count INTEGER;
            """
        )
        cur.execute(
            f"""
            ALTER TABLE {MERGED_JOBS_TABLE} ADD COLUMN IF NOT EXISTS competition_level FLOAT;
            """
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = DatabaseManager(DATABASE_CONFIG)
    _ensure_schema(db)
    app.state.db = db
    yield


app = FastAPI(title="CareerGo API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CAREERGO_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> DatabaseManager:
    return app.state.db


# ---------- Auth models & helpers ----------


class RegisterBody(BaseModel):
    user_id: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    email: Optional[str] = None
    phone: Optional[str] = None
    password: str = Field(..., min_length=6, max_length=128)


class LoginBody(BaseModel):
    user_id: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    name: str


def hash_password(p: str) -> str:
    return pwd_context.hash(p)


def verify_password(p: str, h: str) -> bool:
    return pwd_context.verify(p, h)


def create_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS)
    return jwt.encode({"sub": user_id, "exp": exp}, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> str:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        sub = payload.get("sub")
        if not sub or not isinstance(sub, str):
            raise HTTPException(status_code=401, detail="Invalid token")
        return sub
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


security = HTTPBearer()


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    return decode_token(credentials.credentials)


# Response shape aligned with UserProfile.to_dict()


class ProfileOut(BaseModel):
    user_id: str
    name: str
    education: List[Dict[str, Any]] = []
    skills: List[Dict[str, Any]] = []
    preferences: List[Dict[str, Any]] = []
    constraints: Dict[str, Any] = {}
    work_experience: List[Dict[str, Any]] = []
    certifications: List[str] = []
    languages: Dict[str, str] = {}
    projects: List[Dict[str, Any]] = []


@app.get("/api/health")
def health(db: DatabaseManager = Depends(get_db)):
    ok = db.test_connection()
    return {"status": "ok" if ok else "degraded", "database": ok}


@app.post("/api/auth/register", response_model=TokenOut)
def register(body: RegisterBody, db: DatabaseManager = Depends(get_db)):
    uid = body.user_id.strip()
    conn = db.get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (uid,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="User ID already exists")
        ph = hash_password(body.password)
        cur.execute(
            """
            INSERT INTO users (user_id, name, email, phone, password_hash)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (uid, body.name.strip(), body.email, body.phone, ph),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    token = create_token(uid)
    return TokenOut(access_token=token, user_id=uid, name=body.name.strip())


@app.post("/api/auth/login", response_model=TokenOut)
def login(body: LoginBody, db: DatabaseManager = Depends(get_db)):
    conn = db.get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT name, password_hash FROM users WHERE user_id = %s",
            (body.user_id.strip(),),
        )
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    if not row or not row[1]:
        raise HTTPException(status_code=401, detail="Invalid user ID or password")
    name, pw_hash = row[0], row[1]
    if not verify_password(body.password, pw_hash):
        raise HTTPException(status_code=401, detail="Invalid user ID or password")

    token = create_token(body.user_id.strip())
    return TokenOut(access_token=token, user_id=body.user_id.strip(), name=name or body.user_id.strip())


@app.get("/api/auth/me")
def auth_me(
    user_id: str = Depends(get_current_user_id),
    db: DatabaseManager = Depends(get_db),
):
    u = db.get_user(user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": user_id, "name": u.get("name"), "email": u.get("email")}


@app.get("/api/users/me/profile", response_model=ProfileOut)
def get_my_profile(
    user_id: str = Depends(get_current_user_id),
    db: DatabaseManager = Depends(get_db),
):
    p = db.get_user_profile(user_id)
    if not p:
        raise HTTPException(status_code=404, detail="Profile not found or user missing")
    d = p.to_dict()
    return ProfileOut(**d)


@app.post("/api/users/me/jobs/{job_id}/reasoning")
def post_job_reasoning(
    job_id: str,
    user_id: str = Depends(get_current_user_id),
    db: DatabaseManager = Depends(get_db),
):
    """Scores + full reasoning payload (learning_suggestions, skill_gaps, strengths, etc.) for one job."""
    p = db.get_user_profile(user_id)
    if not p:
        raise HTTPException(status_code=400, detail="Complete your profile first")
    result = compute_job_reasoning_for_user(db, p, job_id)
    if result.get("error") == "not_found":
        raise HTTPException(status_code=404, detail=result.get("message", "Job not found"))
    if result.get("error") == "rank_failed":
        raise HTTPException(status_code=500, detail=result.get("message", "Ranking failed"))
    return result


@app.put("/api/users/me/profile", response_model=ProfileOut)
def put_my_profile(
    body: Dict[str, Any],
    user_id: str = Depends(get_current_user_id),
    db: DatabaseManager = Depends(get_db),
):
    u = db.get_user(user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    body = dict(body)
    body["user_id"] = user_id
    profile = dict_to_user_profile(body, user_id, name_override=body.get("name") or u.get("name"))
    if not db.save_user_profile(profile):
        raise HTTPException(status_code=500, detail="Failed to save profile")
    p2 = db.get_user_profile(user_id)
    if not p2:
        raise HTTPException(status_code=500, detail="Failed to load profile after save")
    return ProfileOut(**p2.to_dict())


@app.post("/api/users/me/recommendations")
def post_recommendations(
    user_id: str = Depends(get_current_user_id),
    db: DatabaseManager = Depends(get_db),
    top_k: int = 10,
    include_reasoning: bool = True,
):
    # Keep recommendation generation bounded to Top-10.
    top_k = min(max(int(top_k), 1), 10)
    p = db.get_user_profile(user_id)
    if not p:
        raise HTTPException(status_code=400, detail="Complete your profile first")
    result = compute_and_persist_recommendations(db, p, user_id, top_k=top_k, include_reasoning=include_reasoning)
    return {
        "user_id": user_id,
        "items": result["items"],
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "diagnostics": result.get("diagnostics"),
    }


@app.get("/api/users/me/recommendations")
def get_recommendations(
    user_id: str = Depends(get_current_user_id),
    db: DatabaseManager = Depends(get_db),
    limit: int = 10,
):
    """Latest rows from matching_history with merged_jobs titles, links, and stored reasoning."""
    # Keep recommendation feed bounded to Top-10 for stable UX and consistent ranking scope.
    limit = min(max(int(limit), 1), 10)
    conn = db.get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            f"""
            SELECT * FROM (
                SELECT DISTINCT ON (mh.job_id)
                    mh.job_id,
                    mh.final_score,
                    mh.relevance_score,
                    mh.feasibility_score,
                    mh.growth_score,
                    mh.match_score,
                    mh.matched_at,
                    mj.title,
                    mj.location,
                    COALESCE(mj.employer, mj.company) AS company,
                    mj.apply_url,
                    mj.url,
                    mh.explanation,
                    mh.reasoning_json,
                    mh.score_breakdown_json,
                    mj.salary,
                    mj.job_type,
                    LEFT(COALESCE(mj.description, mj.full_description, ''), 320) AS description_snippet,
                    mj.department,
                    mj.hours,
                    mj.closing_date,
                    mj.source,
                    mj.category
                FROM matching_history mh
                LEFT JOIN {MERGED_JOBS_TABLE} mj ON mj.job_id::text = mh.job_id::text
                WHERE mh.user_id = %s
                ORDER BY mh.job_id, mh.matched_at DESC
            ) t
            ORDER BY t.final_score DESC NULLS LAST
            LIMIT %s
            """,
            (user_id, limit),
        )
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    items = []
    for i, row in enumerate(rows, 1):
        r = dict(row)
        apply_u, url_u = r.get("apply_url"), r.get("url")
        job_url = ((apply_u or "") or (url_u or "")).strip() or None
        raw_reason = r.get("reasoning_json")
        reasoning = raw_reason if isinstance(raw_reason, dict) else None
        cd = r.get("closing_date")
        closing_s = cd.isoformat() if cd is not None and hasattr(cd, "isoformat") else (str(cd) if cd else None)
        items.append(
            {
                "rank": i,
                "job_id": str(r.get("job_id", "")),
                "score": float(r["final_score"]) if r.get("final_score") is not None else None,
                "relevance": float(r["relevance_score"]) if r.get("relevance_score") is not None else None,
                "feasibility": float(r["feasibility_score"]) if r.get("feasibility_score") is not None else None,
                "growth": float(r["growth_score"]) if r.get("growth_score") is not None else None,
                "match_score": float(r["match_score"]) if r.get("match_score") is not None else None,
                "matched_at": r["matched_at"].isoformat() if r.get("matched_at") else None,
                "title": r.get("title") or "",
                "location": r.get("location") or "",
                "company": r.get("company") or "",
                "job_url": job_url,
                "salary": r.get("salary") or "",
                "job_type": r.get("job_type") or "",
                "explanation": r.get("explanation") or "",
                "reasoning": reasoning,
                "score_breakdown": r.get("score_breakdown_json") if isinstance(r.get("score_breakdown_json"), dict) else None,
                "description_snippet": (r.get("description_snippet") or "").strip() or None,
                "department": r.get("department"),
                "hours": r.get("hours"),
                "closing_date": closing_s,
                "source": r.get("source"),
                "category": r.get("category"),
            }
        )
    return {"user_id": user_id, "items": items}


@app.get("/api/jobs/types")
def list_job_type_values(db: DatabaseManager = Depends(get_db)):
    """Distinct job_type / contract_type values (for simple dropdowns)."""
    return {"items": db.list_distinct_job_types()}


@app.get("/api/jobs")
def list_jobs_public(
    db: DatabaseManager = Depends(get_db),
    page: int = 1,
    page_size: int = 20,
    keywords: Optional[str] = None,
    q: Optional[str] = None,
    location: Optional[str] = None,
    job_type: Optional[str] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
):
    """Paginated browse of merged_jobs (simple filters)."""
    if page < 1:
        page = 1
    page_size = min(max(page_size, 1), 100)
    offset = (page - 1) * page_size
    filters: Dict[str, Any] = {"offset": offset}
    kw = keywords or q
    if kw:
        filters["keywords"] = kw
    if location:
        filters["location"] = location
    if job_type:
        filters["job_type"] = job_type
    if category:
        filters["category"] = category
    if source:
        filters["source"] = source

    count_filters = {k: v for k, v in filters.items() if k != "offset"}
    total = db.count_merged_jobs(count_filters)
    rows = db.get_jobs_from_merged_table(limit=page_size, filters=filters)
    items = []
    for r in rows:
        job = convert_db_job_to_dict(r)
        closing_raw = job.get("closing_date")
        closing_str: str | None = None
        if closing_raw is not None:
            try:
                closing_str = str(closing_raw)[:10]  # keep YYYY-MM-DD only
            except Exception:
                closing_str = None
        items.append(
            {
                "job_id": str(job["job_id"]),
                "title": job.get("title") or "",
                "company": job.get("company") or "",
                "location": job.get("location") or "",
                "salary": job.get("salary_text") or format_job_salary(job),
                "job_type": job.get("work_type") or "",
                "source": r.get("source") or "",
                "job_url": job.get("job_url"),
                "closing_date": closing_str,
            }
        )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.get("/api/jobs/meta/filters")
def jobs_filter_meta(db: DatabaseManager = Depends(get_db)):
    """Distinct sources, job types, locations, and categories for filter dropdowns."""
    conn = db.get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT DISTINCT source FROM {MERGED_JOBS_TABLE} WHERE source IS NOT NULL AND TRIM(source) <> ''
            ORDER BY source LIMIT 40
            """
        )
        sources = [r[0] for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()
    types = dedupe_filter_labels(db.list_distinct_job_types(limit=80))
    locations = db.list_distinct_locations(limit=120)
    categories = sanitize_category_dropdown_labels(
        db.list_distinct_categories(limit=80),
        types,
    )
    return {"sources": sources, "job_types": types, "locations": locations, "categories": categories}


@app.get("/api/jobs/{job_id}/skill-graph")
def get_job_skill_graph(
    job_id: str,
    fallback_related: bool = False,
    db: DatabaseManager = Depends(get_db),
):
    """Job–skill–related-job subgraph from normalized_job_skills (for UI visualization)."""
    g = db.get_job_skill_graph_d3(job_id, allow_related_fallback=fallback_related)
    if g.get("empty_reason") == "job_not_found":
        raise HTTPException(status_code=404, detail="Job not found")
    return g


@app.get("/api/jobs/{job_id}")
def get_job_public(job_id: str, db: DatabaseManager = Depends(get_db)):
    row = db.get_merged_job_by_job_id(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    job = convert_db_job_to_dict(row)
    desc = job.get("description") or ""
    req = job.get("requirements") or ""
    closing_raw = job.get("closing_date")
    closing_str: str | None = None
    if closing_raw is not None:
        try:
            closing_str = str(closing_raw)[:10]
        except Exception:
            closing_str = None
    return {
        "job_id": str(job["job_id"]),
        "title": job.get("title") or "",
        "company": job.get("company") or "",
        "location": job.get("location") or "",
        "salary": format_job_salary(job),
        "salary_text": job.get("salary_text"),
        "description": desc[:12000],
        "requirements": req[:12000],
        "job_url": job.get("job_url"),
        "job_type": job.get("work_type") or "",
        "source": row.get("source") or "",
        "required_skills": job.get("required_skills") or [],
        "url": row.get("url"),
        "apply_url": row.get("apply_url"),
        "closing_date": closing_str,
    }


_URL_CHECK_TIMEOUT = 8  # seconds
_URL_CHECK_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; CareerGoBot/1.0; +https://careergo.app)"
    )
}


@app.get("/api/jobs/{job_id}/check-url")
def check_job_url(job_id: str, db: DatabaseManager = Depends(get_db)):
    """Probe the external posting URL for a job and report whether it is reachable."""
    row = db.get_merged_job_by_job_id(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    job = convert_db_job_to_dict(row)
    url = job.get("job_url")
    if not url:
        return {"reachable": False, "reason": "no_url", "status_code": None}
    try:
        resp = http_requests.head(
            url,
            allow_redirects=True,
            timeout=_URL_CHECK_TIMEOUT,
            headers=_URL_CHECK_HEADERS,
        )
        # Some servers reject HEAD — fall back to a streaming GET
        if resp.status_code in (405, 403, 400):
            resp = http_requests.get(
                url,
                allow_redirects=True,
                timeout=_URL_CHECK_TIMEOUT,
                headers=_URL_CHECK_HEADERS,
                stream=True,
            )
            resp.close()
        reachable = resp.status_code < 400
        return {
            "reachable": reachable,
            "reason": None if reachable else "http_error",
            "status_code": resp.status_code,
            "url": url,
        }
    except http_requests.exceptions.Timeout:
        return {"reachable": False, "reason": "timeout", "status_code": None, "url": url}
    except http_requests.exceptions.ConnectionError:
        return {"reachable": False, "reason": "connection_error", "status_code": None, "url": url}
    except Exception:
        return {"reachable": False, "reason": "unknown_error", "status_code": None, "url": url}


@app.get("/api/users/me/jobs/{job_id}/learning-insights")
def get_learning_insights(
    job_id: str,
    user_id: str = Depends(get_current_user_id),
    db: DatabaseManager = Depends(get_db),
):
    """Same as POST .../reasoning — scores, learning_suggestions, skill_gaps (on-demand)."""
    p = db.get_user_profile(user_id)
    if not p:
        raise HTTPException(status_code=400, detail="Complete your profile first")
    result = compute_job_reasoning_for_user(db, p, job_id)
    if result.get("error") == "not_found":
        raise HTTPException(status_code=404, detail=result.get("message", "Job not found"))
    if result.get("error") == "rank_failed":
        raise HTTPException(status_code=500, detail=result.get("message", "Ranking failed"))
    return result
