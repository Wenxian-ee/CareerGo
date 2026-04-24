"""
Configuration for Matching and Ranking System
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load the project-root .env file when present; silently skip otherwise.
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", override=False)

# Keep in sync with SkillExtraction/config.py and Crawler/config.py.
MERGED_JOBS_TABLE = os.environ.get("MERGED_JOBS_TABLE", "merged_jobs_3")
NORMALIZED_JOB_SKILLS_TABLE = os.environ.get("NORMALIZED_JOB_SKILLS_TABLE", "normalized_job_skills_3")

# ========== Database Config ==========
DATABASE_CONFIG = {
    'host': os.environ.get("DB_HOST", "localhost"),
    'port': int(os.environ.get("DB_PORT", "5432")),
    'database': os.environ.get("DB_NAME", "jobs_data"),
    'user': os.environ.get("DB_USER", "fyp"),
    'password': os.environ.get("DB_PASSWORD", "fyp"),
}

# ========== Matching Algorithm Config ==========
MATCHER_CONFIG = {
    'skill_weight': 0.4,           # Skill matching weight
    'education_weight': 0.15,      # Education matching weight
    'experience_weight': 0.15,     # Experience matching weight
    'preference_weight': 0.15,     # Preference matching weight
    'salary_weight': 0.10,         # Salary matching weight
    'location_weight': 0.05,       # Location matching weight
    'min_skill_coverage': 0.5,     # Minimum skill coverage
    'skill_proficiency_factor': 0.3  # Skill proficiency factor
}

# ========== Ranking System Config ==========
RANKER_CONFIG = {
    'relevance_weight': 0.4,       # Relevance weight
    'feasibility_weight': 0.35,    # Feasibility weight
    'growth_weight': 0.25,         # Growth weight
    'relevance_component_weights': {
        "match_alignment": 0.45,
        "skill_alignment": 0.30,
        "preference_alignment": 0.15,
        "industry_alignment": 0.10,
    },
    'feasibility_component_weights': {
        "skill_readiness": 0.30,
        "experience_fit": 0.20,
        "education_fit": 0.15,
        "salary_attainability": 0.15,
        "location_commute_fit": 0.10,
        "market_competition_adjustment": 0.10,
    },
    'growth_component_weights': {
        "skill_growth_potential": 0.35,
        "salary_growth_potential": 0.25,
        "career_ladder_signal": 0.20,
        "market_future_signal": 0.20,
    },
    'diversity_factor': 0.1,       # Diversity factor
    'use_pareto': False,           # Whether to use Pareto sorting
    'calibration_enabled': True    # Whether to enable calibration
}

# ========== LLM Explanation Config ==========
# LLM enrichment is opt-in: sequential API calls can stall for minutes.
# Enable by setting RECOMMEND_USE_LLM=1 and configuring DEEPSEEK_API_KEY in the environment.
_RECOMMEND_USE_LLM = os.environ.get("RECOMMEND_USE_LLM", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
LLM_CONFIG = {
    "enabled": True,
    "use_llm": _RECOMMEND_USE_LLM,
    "model": "deepseek-chat",
    # OpenAI-compatible base URL; llm_reasoner appends /chat/completions automatically.
    "base_url": os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    "api_key": os.environ.get("DEEPSEEK_API_KEY") or None,
    "api_key_env": "DEEPSEEK_API_KEY",
    'env_file': '.env',           # Location of the dotenv file (relative to CWD).
    'http_proxy': None,           # e.g. http://127.0.0.1:7890
    'https_proxy': None,          # e.g. http://127.0.0.1:7890
    'timeout_seconds': 20,
    'max_skill_gaps': 5,
    'max_learning_suggestions': 3,
    'log_errors': True,
}

# ========== Logging Config ==========
LOGGING_CONFIG = {
    'level': 'INFO',
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
}

