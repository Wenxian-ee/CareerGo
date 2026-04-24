"""
Convert API JSON payloads into MatchingRanking user_profile dataclasses.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

import sys
from pathlib import Path

_MR = Path(__file__).resolve().parent.parent / "MatchingRanking"
if str(_MR) not in sys.path:
    sys.path.insert(0, str(_MR))

from user_profile import (  # noqa: E402
    Constraints,
    Education,
    EducationLevel,
    Preference,
    PreferenceType,
    Skill,
    UserProfile,
    WorkExperience,
)


def _education_level(v: str) -> EducationLevel:
    for e in EducationLevel:
        if e.value == v:
            return e
    return EducationLevel.BACHELOR


def _preference_type(v: str) -> PreferenceType:
    for e in PreferenceType:
        if e.value == v:
            return e
    return PreferenceType.INDUSTRY


def dict_to_user_profile(data: Dict[str, Any], user_id: str, name_override: Optional[str] = None) -> UserProfile:
    name = name_override or (data.get("name") or "").strip() or user_id

    education: List[Education] = []
    for e in data.get("education") or []:
        if not isinstance(e, dict):
            continue
        gy = int(e.get("graduation_year") or 2020)
        if gy < 1950 or gy > 2100:
            gy = 2020
        education.append(
            Education(
                level=_education_level(str(e.get("level", "Bachelor"))),
                major=str(e.get("major", "")),
                school=str(e.get("school", "")),
                graduation_year=gy,
                gpa=float(e["gpa"]) if e.get("gpa") is not None else None,
                ranking=str(e["ranking"]) if e.get("ranking") else None,
            )
        )

    skills: List[Skill] = []
    for s in data.get("skills") or []:
        if not isinstance(s, dict):
            continue
        skills.append(
            Skill(
                name=str(s.get("name", "")),
                proficiency=float(s.get("proficiency", 0.5)),
                years_of_experience=float(s.get("years_of_experience", 0)),
                category=str(s.get("category", "General")),
                verified=bool(s.get("verified", False)),
                raw_name=s.get("raw_name"),
                esco_skill_id=int(s["esco_skill_id"]) if s.get("esco_skill_id") is not None else None,
                similarity_score=float(s["similarity_score"]) if s.get("similarity_score") is not None else None,
                normalization_method=s.get("normalization_method"),
            )
        )

    preferences: List[Preference] = []
    for p in data.get("preferences") or []:
        if not isinstance(p, dict):
            continue
        preferences.append(
            Preference(
                preference_type=_preference_type(str(p.get("preference_type", "Industry"))),
                value=str(p.get("value", "")),
                weight=float(p.get("weight", 1.0)),
            )
        )

    c = data.get("constraints") or {}
    exclude = c.get("exclude_companies") or []
    if isinstance(exclude, list):
        excl_set: Set[str] = set(str(x) for x in exclude if x)
    else:
        excl_set = set()

    constraints = Constraints(
        locations=list(c.get("locations") or []),
        min_salary=float(c["min_salary"]) if c.get("min_salary") is not None else None,
        max_salary=float(c["max_salary"]) if c.get("max_salary") is not None else None,
        work_type=str(c["work_type"]) if c.get("work_type") else None,
        start_date=str(c["start_date"]) if c.get("start_date") else None,
        industries=list(c.get("industries") or []),
        company_types=list(c.get("company_types") or []),
        exclude_companies=excl_set,
        max_commute_time=int(c["max_commute_time"]) if c.get("max_commute_time") is not None else None,
    )

    work_experience: List[WorkExperience] = []
    for w in data.get("work_experience") or []:
        if not isinstance(w, dict):
            continue
        work_experience.append(
            WorkExperience(
                company=str(w.get("company", "")),
                position=str(w.get("position", "")),
                duration_years=float(w.get("duration_years", 0)),
                responsibilities=list(w.get("responsibilities") or []),
                achievements=list(w.get("achievements") or []),
            )
        )

    certifications = [str(x) for x in (data.get("certifications") or []) if x]
    languages = dict(data.get("languages") or {})
    projects = [p for p in (data.get("projects") or []) if isinstance(p, dict)]

    return UserProfile(
        user_id=user_id,
        name=name,
        education=education,
        skills=skills,
        preferences=preferences,
        constraints=constraints,
        work_experience=work_experience,
        certifications=certifications,
        languages=languages,
        projects=projects,
    )
