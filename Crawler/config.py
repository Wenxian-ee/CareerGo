"""
Configuration for CareerGo Crawler System
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load the project-root .env file when present; silently skip otherwise.
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", override=False)

# Keep the same as SkillExtraction/config.py (can be overridden by environment variable MERGED_JOBS_TABLE)
MERGED_JOBS_TABLE = os.environ.get("MERGED_JOBS_TABLE", "merged_jobs_3")

# ========== Database Config ==========
DATABASE_CONFIG = {
    'host': os.environ.get("DB_HOST", "localhost"),
    'port': int(os.environ.get("DB_PORT", "5432")),
    'database': os.environ.get("DB_NAME", "jobs_data"),
    'user': os.environ.get("DB_USER", "fyp"),
    'password': os.environ.get("DB_PASSWORD", "fyp"),
}

# ========== Adzuna API ==========
# Register at https://developer.adzuna.com/ for API keys
ADZUNA_CONFIG = {
    'app_id': os.environ.get("ADZUNA_APP_ID", ""),
    'app_key': os.environ.get("ADZUNA_APP_KEY", ""),
    'delay_range': (1, 2),             # Request delay range (seconds)
    'max_pages': 5,                    # Max pages per search
    'max_days_old': 30,                # Max age of job postings (days)
    'batch_size': 50,                  # Batch insert size
}

# ========== Adzuna search params ==========
# Keywords (graduates and internships)
ADZUNA_KEYWORDS = [
    'graduate',
    'graduate scheme',
    'internship',
    'placement',
    'entry level',
]

# Locations (empty string = UK-wide)
ADZUNA_LOCATIONS = [
    'London',
    'Manchester',
    'Birmingham',
    'Edinburgh',
    'Bristol',
    '',  # UK-wide
]

# Job categories / sectors
ADZUNA_CATEGORIES = [
    'it-jobs',
    'engineering-jobs',
    'accounting-finance-jobs',
    'graduate',
    'healthcare-nursing-jobs',
    'legal-jobs',
    'marketing-advertising-pr-jobs',
    'scientific-qa-jobs',
    '',  # All categories
]

# ========== Merge config ==========
MERGE_CONFIG = {
    'clear_existing': False,           # Clear existing merge table
    'batch_size': 100,                 # Batch size
    'export_csv': True,                # Export CSV
    'csv_filename': 'merged_jobs_export.csv',
    'csv_limit': 1000,                 # Max rows in CSV export
}

# ========== Logging ==========
LOGGING_CONFIG = {
    'level': 'INFO',                   # DEBUG, INFO, WARNING, ERROR
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
}
