"""
Matching and ranking pipeline aligned with main_with_db.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "MatchingRanking") not in sys.path:
    sys.path.insert(0, str(ROOT / "MatchingRanking"))

from config import (  # noqa: E402
    DATABASE_CONFIG,
    LLM_CONFIG,
    MATCHER_CONFIG,
    MERGED_JOBS_TABLE,
    RANKER_CONFIG,
)
from database import DatabaseManager  # noqa: E402
from llm_reasoner import RecommendationReasoner  # noqa: E402
from main_with_db import convert_db_job_to_dict, format_job_salary  # noqa: E402
from matching_algorithm import JobMatcher  # noqa: E402
from ranking_system import MultiObjectiveRanker  # noqa: E402
from user_profile import UserProfile  # noqa: E402

logger = logging.getLogger(__name__)


def compute_and_persist_recommendations(
    db: DatabaseManager,
    user_profile: UserProfile,
    user_id: str,
    top_k: int = 10,
    include_reasoning: bool = True,
) -> Dict[str, Any]:
    """Same core steps as main_with_db.main: load jobs -> match -> rank -> (optional) LLM enrich -> persist matching_history.

    Loads **all** rows from the configured merged jobs table (``MERGED_JOBS_TABLE``, default
    ``merged_jobs_3``) with no SQL LIMIT. Location / salary / etc. are enforced inside
    ``JobMatcher`` and ``Constraints.is_satisfied``, not by truncating the candidate list.

    If the strict matcher yields no rows (e.g. all scores below default min_match_score), retry with
    min_match_score=0.0 so jobs that still pass hard constraints can be ranked.

    When ``include_reasoning=False`` the LLM enrichment step is skipped entirely; each job gets a
    rule-based fallback explanation from the ranker instead.  Per-job on-demand reasoning is still
    available via ``compute_job_reasoning_for_user``.
    """
    t0 = time.perf_counter()
    db_jobs = db.get_jobs_from_merged_table(limit=None, filters={})
    t_db_done = time.perf_counter()
    logger.info(
        "recommendations: loaded %s jobs from merged+skills join in %.2fs",
        len(db_jobs),
        t_db_done - t0,
    )

    if not db_jobs:
        return {
            "items": [],
            "diagnostics": {
                "jobs_loaded": 0,
                "jobs_query_limit": None,
                "used_relaxed_match": False,
                "empty_reason": "no_jobs_in_database",
                "latency_matching_ranking_ms": 0.0,
                "latency_llm_ms": 0.0,
                "latency_total_ms": 0.0,
            },
        }

    jobs = [convert_db_job_to_dict(j) for j in db_jobs]
    matcher = JobMatcher(config=MATCHER_CONFIG)
    t1 = time.perf_counter()
    matched_results = matcher.match(user_profile, jobs)
    logger.info(
        "recommendations: matcher -> %s candidates in %.2fs",
        len(matched_results),
        time.perf_counter() - t1,
    )
    used_relaxed = False
    if not matched_results:
        relaxed_cfg = dict(MATCHER_CONFIG)
        relaxed_cfg["min_match_score"] = 0.0
        matcher_relaxed = JobMatcher(config=relaxed_cfg)
        matched_results = matcher_relaxed.match(user_profile, jobs)
        if matched_results:
            used_relaxed = True
            logger.info(
                "Recommendations: strict match empty; used relaxed min_match_score=0.0 (%s jobs)",
                len(matched_results),
            )

    ranker = MultiObjectiveRanker(config=RANKER_CONFIG)
    t2 = time.perf_counter()
    ranked_jobs = ranker.rank(user_profile, matched_results, top_k=top_k)
    t_rank_done = time.perf_counter()
    logger.info(
        "recommendations: ranker -> %s top rows in %.2fs",
        len(ranked_jobs),
        t_rank_done - t2,
    )

    t3 = time.perf_counter()
    if include_reasoning:
        reasoner = RecommendationReasoner(config=LLM_CONFIG)
        try:
            ranked_jobs = reasoner.enrich_ranked_jobs(user_profile, ranked_jobs)
        except Exception as e:
            logger.warning("LLM enrich skipped: %s", e)
        logger.info(
            "recommendations: reasoning enrich in %.2fs (use_llm=%s)",
            time.perf_counter() - t3,
            bool(LLM_CONFIG.get("use_llm")),
        )
    else:
        logger.info("recommendations: LLM enrich skipped (include_reasoning=False); using rule-based fallback")
    t4 = time.perf_counter()

    out: List[Dict[str, Any]] = []
    for i, job_info in enumerate(ranked_jobs, 1):
        job = job_info["job"]
        reasoning = job_info.get("reasoning") or {}
        expl = reasoning.get("recommendation_reasoning") or reasoning.get("fallback_reason") or ""
        if not expl:
            expl = ranker.explain_ranking(job_info)
        scores = {
            "match_score": job_info.get("match_score", 0),
            "relevance": job_info["relevance"],
            "feasibility": job_info["feasibility"],
            "growth": job_info["growth"],
            "final_score": job_info["final_score"],
        }
        db.save_matching_result(
            user_id,
            str(job["job_id"]),
            scores,
            explanation=expl,
            reasoning_json=reasoning if reasoning else None,
            score_breakdown_json={
                "relevance": job_info.get("relevance_breakdown"),
                "feasibility": job_info.get("feasibility_breakdown"),
                "growth": job_info.get("growth_breakdown"),
            },
        )
        out.append(
            {
                "rank": i,
                "job_id": str(job.get("job_id", "")),
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "salary": format_job_salary(job),
                "job_url": job.get("job_url"),
                "job_type": job.get("work_type") or job.get("position_type"),
                "industry": job.get("industry"),
                "department": job.get("department"),
                "hours": job.get("hours"),
                "closing_date": (
                    job.get("closing_date").isoformat()
                    if job.get("closing_date") is not None and hasattr(job.get("closing_date"), "isoformat")
                    else (str(job.get("closing_date")) if job.get("closing_date") else None)
                ),
                "source": job.get("source"),
                "category": job.get("category"),
                "description_snippet": job.get("description_snippet") or (job.get("description") or "")[:320],
                "score": float(job_info["final_score"]),
                "relevance": float(job_info["relevance"]),
                "feasibility": float(job_info["feasibility"]),
                "growth": float(job_info["growth"]),
                "score_breakdown": {
                    "relevance": job_info.get("relevance_breakdown"),
                    "feasibility": job_info.get("feasibility_breakdown"),
                    "growth": job_info.get("growth_breakdown"),
                },
                "explanation": expl,
                "reasoning": reasoning,
            }
        )
    diagnostics: Dict[str, Any] = {
        "jobs_loaded": len(db_jobs),
        "jobs_query_limit": None,
        "used_relaxed_match": used_relaxed,
        "empty_reason": None if out else "no_matches_after_constraints",
        # Server-side latency breakdown (milliseconds)
        "latency_matching_ranking_ms": round((t_rank_done - t1) * 1000, 2),
        "latency_llm_ms": round((t4 - t3) * 1000, 2),
        "latency_total_ms": round((t4 - t0) * 1000, 2),
    }
    return {"items": out, "diagnostics": diagnostics}


def compute_job_reasoning_for_user(
    db: DatabaseManager,
    user_profile: UserProfile,
    job_id: str,
) -> Dict[str, Any]:
    """Run matcher + ranker on one job and attach LLM/fallback reasoning (learning_suggestions, skill_gaps, etc.)."""
    row = db.get_merged_job_by_job_id(job_id)
    if not row:
        return {
            "error": "not_found",
            "message": f"Job not found in {MERGED_JOBS_TABLE}",
        }

    job = convert_db_job_to_dict(row)
    satisfied = user_profile.constraints.is_satisfied(job)

    matcher = JobMatcher(config=MATCHER_CONFIG)
    ranker = MultiObjectiveRanker(config=RANKER_CONFIG)
    match_score, details = matcher.calculate_match_score(user_profile, job)
    ranked = ranker.rank(user_profile, [(job, match_score, details)], top_k=1)
    if not ranked:
        return {"error": "rank_failed", "message": "Could not rank this job"}

    job_info = ranked[0]
    reasoner = RecommendationReasoner(config=LLM_CONFIG)
    reasoning = reasoner.generate_reasoning(user_profile, job_info)

    return {
        "job_id": str(job_id),
        "job_url": job.get("job_url"),
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "location": job.get("location", ""),
        "salary": format_job_salary(job),
        "constraints_satisfied": satisfied,
        "scores": {
            "match_score": float(job_info.get("match_score", 0)),
            "final_score": float(job_info["final_score"]),
            "relevance": float(job_info["relevance"]),
            "feasibility": float(job_info["feasibility"]),
            "growth": float(job_info["growth"]),
        },
        "score_breakdown": {
            "relevance": job_info.get("relevance_breakdown"),
            "feasibility": job_info.get("feasibility_breakdown"),
            "growth": job_info.get("growth_breakdown"),
        },
        "reasoning": reasoning,
    }
