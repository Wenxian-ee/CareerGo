"""
One-off script to seed nine demo accounts (test_02 ... test_10) with
differentiated profiles, so the frontend can log in immediately.

For every user:
- user_id  == name == password == "test_NN"
- password is hashed with pbkdf2_sha256 (same scheme as `api/app.py`).
- a full UserProfile is persisted through DatabaseManager.save_user_profile,
  which populates users / user_education / user_skills / user_preferences /
  user_constraints / user_work_experience / user_certifications /
  user_languages / user_projects and ESCO-normalized skills (best effort).

Usage:
    python MatchingRanking/seed_test_users.py            # create / refresh all
    python MatchingRanking/seed_test_users.py --drop     # delete them first
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List

from passlib.context import CryptContext

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from config import DATABASE_CONFIG  # noqa: E402
from database import DatabaseManager  # noqa: E402
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("seed_test_users")

# Must match api/app.py so tokens issued at login validate successfully.
_pwd_ctx = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


# ---------------------------------------------------------------------------
# Persona catalogue
# ---------------------------------------------------------------------------

def _make_profiles() -> List[UserProfile]:
    """Return 9 differentiated UK-oriented personas (test_02 ... test_10)."""
    profiles: List[UserProfile] = []

    # test_02 — CS new graduate, machine learning
    profiles.append(UserProfile(
        user_id="test_02",
        name="test_02",
        education=[
            Education(
                level=EducationLevel.BACHELOR,
                major="Computer Science",
                school="University College London",
                graduation_year=2024,
                gpa=3.6,
                ranking="QS Top 100",
            )
        ],
        skills=[
            Skill(name="Python", proficiency=0.85, years_of_experience=3, category="Programming Language", verified=True),
            Skill(name="Machine Learning", proficiency=0.75, years_of_experience=1.5, category="Technical Field"),
            Skill(name="PyTorch", proficiency=0.7, years_of_experience=1, category="Framework"),
            Skill(name="SQL", proficiency=0.65, years_of_experience=1, category="Database"),
            Skill(name="Git", proficiency=0.8, years_of_experience=2, category="Tool"),
        ],
        preferences=[
            Preference(PreferenceType.INDUSTRY, "Artificial Intelligence", weight=0.9),
            Preference(PreferenceType.CAREER_GROWTH, "Fast Growth", weight=0.85),
            Preference(PreferenceType.INNOVATION, "Technical Innovation", weight=0.7),
        ],
        constraints=Constraints(
            locations=["London", "Cambridge"],
            min_salary=28000.0,
            max_salary=45000.0,
            work_type="Full-time",
            industries=["Technology", "Artificial Intelligence", "FinTech"],
        ),
        work_experience=[
            WorkExperience(
                company="UCL ML Research Group",
                position="Research Intern",
                duration_years=0.5,
                responsibilities=["Train NLP classifiers", "Maintain data-labelling pipeline"],
                achievements=["Improved F1 by 4 points on project baseline"],
            )
        ],
        certifications=["Deep Learning Specialization"],
        languages={"English": "Native", "Mandarin": "Conversational"},
        projects=[{
            "name": "Resume-to-Job Matcher",
            "description": "SBERT-based semantic match prototype",
            "tech_stack": ["Python", "PyTorch", "FastAPI"],
        }],
    ))

    # test_03 — Data analyst, Manchester
    profiles.append(UserProfile(
        user_id="test_03",
        name="test_03",
        education=[
            Education(
                level=EducationLevel.BACHELOR,
                major="Statistics",
                school="University of Manchester",
                graduation_year=2023,
                gpa=3.4,
            )
        ],
        skills=[
            Skill(name="SQL", proficiency=0.85, years_of_experience=2.5, category="Database", verified=True),
            Skill(name="Python", proficiency=0.7, years_of_experience=2, category="Programming Language"),
            Skill(name="Power BI", proficiency=0.8, years_of_experience=1.5, category="Tool"),
            Skill(name="Tableau", proficiency=0.6, years_of_experience=1, category="Tool"),
            Skill(name="Excel", proficiency=0.9, years_of_experience=3, category="Tool"),
            Skill(name="Statistics", proficiency=0.75, years_of_experience=3, category="Technical Field"),
        ],
        preferences=[
            Preference(PreferenceType.INDUSTRY, "Retail", weight=0.6),
            Preference(PreferenceType.WORK_LIFE_BALANCE, "Good Balance", weight=0.85),
            Preference(PreferenceType.COMPANY_SIZE, "Enterprise", weight=0.5),
        ],
        constraints=Constraints(
            locations=["Manchester", "Leeds", "Liverpool"],
            min_salary=26000.0,
            max_salary=38000.0,
            work_type="Full-time",
            industries=["Retail", "Consulting", "Healthcare"],
        ),
        work_experience=[
            WorkExperience(
                company="Boots UK",
                position="Junior Data Analyst",
                duration_years=1.0,
                responsibilities=["Build weekly sales dashboards", "Write SQL extraction jobs"],
                achievements=["Automated five recurring reports, saving ~10 hours per week"],
            )
        ],
        certifications=["Microsoft Certified: Data Analyst Associate"],
        languages={"English": "Native"},
        projects=[{
            "name": "Retail Cohort Churn Study",
            "description": "Segmented loyalty customers and modelled churn drivers",
            "tech_stack": ["Python", "pandas", "Power BI"],
        }],
    ))

    # test_04 — Backend engineer with industry experience
    profiles.append(UserProfile(
        user_id="test_04",
        name="test_04",
        education=[
            Education(
                level=EducationLevel.MASTER,
                major="Software Engineering",
                school="University of Birmingham",
                graduation_year=2021,
                gpa=3.5,
            )
        ],
        skills=[
            Skill(name="Java", proficiency=0.9, years_of_experience=4, category="Programming Language", verified=True),
            Skill(name="Spring Boot", proficiency=0.85, years_of_experience=3, category="Framework"),
            Skill(name="Kubernetes", proficiency=0.7, years_of_experience=2, category="Tool"),
            Skill(name="AWS", proficiency=0.75, years_of_experience=2.5, category="Tool"),
            Skill(name="PostgreSQL", proficiency=0.8, years_of_experience=3, category="Database"),
            Skill(name="Microservices", proficiency=0.8, years_of_experience=2.5, category="Technical Field"),
        ],
        preferences=[
            Preference(PreferenceType.INDUSTRY, "FinTech", weight=0.8),
            Preference(PreferenceType.CAREER_GROWTH, "Staff / Senior Track", weight=0.75),
            Preference(PreferenceType.COMPANY_SIZE, "Medium", weight=0.6),
        ],
        constraints=Constraints(
            locations=["Birmingham", "London", "Remote"],
            min_salary=55000.0,
            max_salary=85000.0,
            work_type="Full-time",
            industries=["FinTech", "Technology", "Banking"],
        ),
        work_experience=[
            WorkExperience(
                company="Capital One UK",
                position="Software Engineer",
                duration_years=3.0,
                responsibilities=[
                    "Own microservice for credit card onboarding",
                    "Run on-call rotations for payment pipeline",
                ],
                achievements=["Reduced p95 latency from 480ms to 210ms on card-issuance service"],
            )
        ],
        certifications=["AWS Certified Solutions Architect – Associate"],
        languages={"English": "Native"},
        projects=[{
            "name": "Event-driven order service",
            "description": "Kafka + Spring Boot reference implementation",
            "tech_stack": ["Java", "Spring Boot", "Kafka", "PostgreSQL"],
        }],
    ))

    # test_05 — Finance graduate, Edinburgh
    profiles.append(UserProfile(
        user_id="test_05",
        name="test_05",
        education=[
            Education(
                level=EducationLevel.BACHELOR,
                major="Accounting and Finance",
                school="University of Edinburgh",
                graduation_year=2024,
                gpa=3.7,
            )
        ],
        skills=[
            Skill(name="Financial Modelling", proficiency=0.7, years_of_experience=1.5, category="Technical Field"),
            Skill(name="Excel", proficiency=0.9, years_of_experience=4, category="Tool", verified=True),
            Skill(name="VBA", proficiency=0.6, years_of_experience=1, category="Programming Language"),
            Skill(name="SQL", proficiency=0.55, years_of_experience=1, category="Database"),
            Skill(name="Bloomberg Terminal", proficiency=0.5, years_of_experience=0.5, category="Tool"),
        ],
        preferences=[
            Preference(PreferenceType.INDUSTRY, "Banking", weight=0.9),
            Preference(PreferenceType.COMPANY_SIZE, "Enterprise", weight=0.7),
            Preference(PreferenceType.CAREER_GROWTH, "Rotational Scheme", weight=0.8),
        ],
        constraints=Constraints(
            locations=["Edinburgh", "London", "Glasgow"],
            min_salary=30000.0,
            max_salary=45000.0,
            work_type="Full-time",
            industries=["Banking", "Finance", "Accounting"],
        ),
        work_experience=[
            WorkExperience(
                company="KPMG",
                position="Summer Intern – Audit",
                duration_years=0.25,
                responsibilities=["Assist FS audit team with working papers"],
                achievements=["Received return offer for graduate programme"],
            )
        ],
        certifications=["CFA Level I Candidate"],
        languages={"English": "Native"},
        projects=[{
            "name": "DCF Valuation – FTSE retailer",
            "description": "University capstone DCF model",
            "tech_stack": ["Excel", "VBA"],
        }],
    ))

    # test_06 — Mechanical engineer, Bristol
    profiles.append(UserProfile(
        user_id="test_06",
        name="test_06",
        education=[
            Education(
                level=EducationLevel.BACHELOR,
                major="Mechanical Engineering",
                school="University of Bristol",
                graduation_year=2023,
                gpa=3.5,
            )
        ],
        skills=[
            Skill(name="SolidWorks", proficiency=0.85, years_of_experience=3, category="Tool", verified=True),
            Skill(name="AutoCAD", proficiency=0.75, years_of_experience=2, category="Tool"),
            Skill(name="MATLAB", proficiency=0.7, years_of_experience=2.5, category="Programming Language"),
            Skill(name="FEA", proficiency=0.65, years_of_experience=1.5, category="Technical Field"),
            Skill(name="Python", proficiency=0.55, years_of_experience=1, category="Programming Language"),
        ],
        preferences=[
            Preference(PreferenceType.INDUSTRY, "Aerospace", weight=0.9),
            Preference(PreferenceType.INNOVATION, "Applied R&D", weight=0.7),
        ],
        constraints=Constraints(
            locations=["Bristol", "Coventry", "Derby"],
            min_salary=28000.0,
            max_salary=42000.0,
            work_type="Full-time",
            industries=["Aerospace", "Manufacturing", "Automotive"],
        ),
        work_experience=[
            WorkExperience(
                company="Airbus",
                position="Engineering Placement",
                duration_years=1.0,
                responsibilities=["Wing fuel-system components stress analysis"],
                achievements=["Delivered FEA report cited in internal review"],
            )
        ],
        certifications=["IMechE Student Member"],
        languages={"English": "Native", "French": "Conversational"},
        projects=[{
            "name": "UAV airframe optimisation",
            "description": "Topology optimisation of composite airframe",
            "tech_stack": ["SolidWorks", "ANSYS", "MATLAB"],
        }],
    ))

    # test_07 — UX/UI designer, London
    profiles.append(UserProfile(
        user_id="test_07",
        name="test_07",
        education=[
            Education(
                level=EducationLevel.BACHELOR,
                major="Digital Media Design",
                school="Goldsmiths, University of London",
                graduation_year=2022,
                gpa=3.6,
            )
        ],
        skills=[
            Skill(name="Figma", proficiency=0.9, years_of_experience=3, category="Tool", verified=True),
            Skill(name="User Research", proficiency=0.75, years_of_experience=2, category="Technical Field"),
            Skill(name="Prototyping", proficiency=0.8, years_of_experience=2.5, category="Technical Field"),
            Skill(name="HTML", proficiency=0.6, years_of_experience=2, category="Programming Language"),
            Skill(name="CSS", proficiency=0.6, years_of_experience=2, category="Programming Language"),
            Skill(name="React", proficiency=0.4, years_of_experience=1, category="Framework"),
        ],
        preferences=[
            Preference(PreferenceType.INDUSTRY, "Creative", weight=0.8),
            Preference(PreferenceType.WORK_LIFE_BALANCE, "Hybrid / 3 days office", weight=0.85),
            Preference(PreferenceType.INNOVATION, "Design-led", weight=0.7),
        ],
        constraints=Constraints(
            locations=["London", "Brighton"],
            min_salary=32000.0,
            max_salary=48000.0,
            work_type="Full-time",
            industries=["Creative", "Media", "Technology"],
        ),
        work_experience=[
            WorkExperience(
                company="Monzo Bank",
                position="Product Design Intern",
                duration_years=0.5,
                responsibilities=["Design onboarding flows", "Run moderated usability tests"],
                achievements=["Shipped savings-pot redesign improving activation by 12%"],
            )
        ],
        certifications=["NN/g UX Master Certificate (in progress)"],
        languages={"English": "Native"},
        projects=[{
            "name": "Accessible banking onboarding",
            "description": "WCAG 2.2 compliant mobile banking flow",
            "tech_stack": ["Figma", "Maze", "ProtoPie"],
        }],
    ))

    # test_08 — Marketing graduate, London
    profiles.append(UserProfile(
        user_id="test_08",
        name="test_08",
        education=[
            Education(
                level=EducationLevel.BACHELOR,
                major="Marketing",
                school="King's College London",
                graduation_year=2024,
                gpa=3.3,
            )
        ],
        skills=[
            Skill(name="SEO", proficiency=0.75, years_of_experience=1.5, category="Technical Field"),
            Skill(name="Content Strategy", proficiency=0.7, years_of_experience=1.5, category="Technical Field"),
            Skill(name="Google Analytics", proficiency=0.7, years_of_experience=1.5, category="Tool"),
            Skill(name="Social Media Marketing", proficiency=0.8, years_of_experience=2, category="Technical Field"),
            Skill(name="Copywriting", proficiency=0.75, years_of_experience=2, category="Technical Field"),
        ],
        preferences=[
            Preference(PreferenceType.INDUSTRY, "Consumer Goods", weight=0.75),
            Preference(PreferenceType.CAREER_GROWTH, "Graduate Scheme", weight=0.85),
        ],
        constraints=Constraints(
            locations=["London", "Reading"],
            min_salary=26000.0,
            max_salary=35000.0,
            work_type="Full-time",
            industries=["Consumer Goods", "Retail", "Media"],
        ),
        work_experience=[
            WorkExperience(
                company="Unilever",
                position="Digital Marketing Intern",
                duration_years=0.5,
                responsibilities=["Plan TikTok campaigns for hair-care line"],
                achievements=["Campaign reached 2M organic views and +18% sign-ups"],
            )
        ],
        certifications=["Google Analytics Individual Qualification"],
        languages={"English": "Native", "Spanish": "Fluent"},
        projects=[{
            "name": "Student podcast brand",
            "description": "Grew Spotify podcast from 0 to 5k monthly listeners",
            "tech_stack": ["Canva", "Meta Ads", "Spotify for Podcasters"],
        }],
    ))

    # test_09 — Cybersecurity, mostly remote
    profiles.append(UserProfile(
        user_id="test_09",
        name="test_09",
        education=[
            Education(
                level=EducationLevel.MASTER,
                major="Cyber Security",
                school="Royal Holloway, University of London",
                graduation_year=2023,
                gpa=3.8,
                ranking="QS Top 200",
            )
        ],
        skills=[
            Skill(name="Linux", proficiency=0.85, years_of_experience=4, category="Tool", verified=True),
            Skill(name="Penetration Testing", proficiency=0.75, years_of_experience=2, category="Technical Field"),
            Skill(name="Network Security", proficiency=0.8, years_of_experience=2.5, category="Technical Field"),
            Skill(name="Python", proficiency=0.75, years_of_experience=3, category="Programming Language"),
            Skill(name="Burp Suite", proficiency=0.7, years_of_experience=2, category="Tool"),
            Skill(name="Splunk", proficiency=0.6, years_of_experience=1.5, category="Tool"),
        ],
        preferences=[
            Preference(PreferenceType.INDUSTRY, "Cybersecurity", weight=0.95),
            Preference(PreferenceType.WORK_LIFE_BALANCE, "Remote", weight=0.9),
            Preference(PreferenceType.INNOVATION, "Offensive Research", weight=0.6),
        ],
        constraints=Constraints(
            locations=["London", "Remote"],
            min_salary=45000.0,
            max_salary=70000.0,
            work_type="Remote",
            industries=["Cybersecurity", "Technology", "Government"],
        ),
        work_experience=[
            WorkExperience(
                company="PwC UK",
                position="Cyber Consultant",
                duration_years=1.5,
                responsibilities=["Lead external pentests", "Write executive risk reports"],
                achievements=["Identified RCE in client's auth service, CVSS 9.1"],
            )
        ],
        certifications=["CompTIA Security+", "OSCP (in progress)"],
        languages={"English": "Native"},
        projects=[{
            "name": "Home SOC lab",
            "description": "ELK + Suricata IDS home lab with automated detections",
            "tech_stack": ["Elastic", "Suricata", "Python"],
        }],
    ))

    # test_10 — Biomedical engineer, Manchester
    profiles.append(UserProfile(
        user_id="test_10",
        name="test_10",
        education=[
            Education(
                level=EducationLevel.MASTER,
                major="Biomedical Engineering",
                school="University of Manchester",
                graduation_year=2024,
                gpa=3.6,
            )
        ],
        skills=[
            Skill(name="MATLAB", proficiency=0.85, years_of_experience=4, category="Programming Language", verified=True),
            Skill(name="Signal Processing", proficiency=0.75, years_of_experience=2, category="Technical Field"),
            Skill(name="Python", proficiency=0.7, years_of_experience=2, category="Programming Language"),
            Skill(name="LabVIEW", proficiency=0.65, years_of_experience=1.5, category="Tool"),
            Skill(name="Medical Imaging", proficiency=0.7, years_of_experience=1.5, category="Technical Field"),
        ],
        preferences=[
            Preference(PreferenceType.INDUSTRY, "Healthcare", weight=0.95),
            Preference(PreferenceType.CAREER_GROWTH, "R&D Track", weight=0.8),
        ],
        constraints=Constraints(
            locations=["Manchester", "Cambridge", "Oxford"],
            min_salary=30000.0,
            max_salary=45000.0,
            work_type="Full-time",
            industries=["Healthcare", "Medical Devices", "Pharmaceuticals"],
        ),
        work_experience=[
            WorkExperience(
                company="Manchester NHS Foundation Trust",
                position="Research Assistant",
                duration_years=0.75,
                responsibilities=["MRI signal-processing pipeline for stroke study"],
                achievements=["Co-authored poster at BioMedEng 2023"],
            )
        ],
        certifications=["Good Clinical Practice (GCP)"],
        languages={"English": "Fluent", "Mandarin": "Native"},
        projects=[{
            "name": "Wearable ECG classifier",
            "description": "CNN classifier for arrhythmia detection on wearable ECG",
            "tech_stack": ["Python", "PyTorch", "MATLAB"],
        }],
    ))

    return profiles


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _set_password_hash(db: DatabaseManager, user_id: str, password: str) -> None:
    """Store the pbkdf2_sha256 hash on `users.password_hash`."""
    hashed = _pwd_ctx.hash(password)
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        # The `password_hash` column is added lazily by api.app._ensure_schema,
        # but we also add it here so the script can run before the API starts.
        cur.execute(
            """
            ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);
            """
        )
        cur.execute(
            "UPDATE users SET password_hash = %s WHERE user_id = %s",
            (hashed, user_id),
        )
        if cur.rowcount == 0:
            logger.warning("User %s not found when setting password_hash", user_id)
        conn.commit()
        cur.close()
    finally:
        conn.close()


def _delete_users(db: DatabaseManager, user_ids: List[str]) -> None:
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        # ON DELETE CASCADE on the child tables wipes profile rows automatically.
        cur.execute("DELETE FROM users WHERE user_id = ANY(%s)", (user_ids,))
        conn.commit()
        logger.info("Deleted %s rows from users.", cur.rowcount)
        cur.close()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Seed test_02 ... test_10 accounts.")
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Delete the nine accounts before re-creating them.",
    )
    args = parser.parse_args()

    db = DatabaseManager(DATABASE_CONFIG)
    if not db.test_connection():
        logger.error("Database connection failed; check .env / DATABASE_CONFIG.")
        return 2

    profiles = _make_profiles()
    user_ids = [p.user_id for p in profiles]

    if args.drop:
        _delete_users(db, user_ids)

    ok = 0
    for profile in profiles:
        if not db.save_user_profile(profile):
            logger.error("Failed to save profile for %s", profile.user_id)
            continue
        _set_password_hash(db, profile.user_id, password=profile.user_id)
        logger.info(
            "Seeded %s  (password = %s,  %d skills, %d prefs)",
            profile.user_id,
            profile.user_id,
            len(profile.skills),
            len(profile.preferences),
        )
        ok += 1

    logger.info("Done. %s / %s users seeded.", ok, len(profiles))
    return 0 if ok == len(profiles) else 1


if __name__ == "__main__":
    sys.exit(main())
