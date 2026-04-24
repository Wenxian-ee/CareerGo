"""
Merge and Deduplicate Jobs from Jobs.ac.uk and Adzuna

Features:
- Read Jobs.ac.uk data from the jobs_ac_uk_jobs table
- Read Adzuna data from the adzuna_jobs table
- Standardise and map fields to a unified schema
- Filter out records with NULL required fields
- Smart deduplication (based on title, company, location)
- Save to the unified merged_jobs table
- Generate a detailed merge report

Incremental mode (default):
- Does not truncate merged_jobs.
- Fetches only source rows whose unified id is not yet in merged_jobs:
  jobs.ac.uk → job_id ``jobs_ac_uk_<jobs_ac_uk_jobs.job_id>``, Adzuna → ``adzuna_<adzuna_jobs.job_id>``
  (same rule as the crawler’s stable ``job_id`` + source prefix).
- After fetch, optional title/company/location dedup_hash still skips cross-source duplicates.
- Inserts use ON CONFLICT (job_id) DO NOTHING so existing rows stay unchanged.
- Pass clear_existing=True for a full rebuild (truncate then re-import all source rows).
- Pass update_existing=True to reload all source rows and upsert; use only_new=False (default then) to scan full tables.
"""
# TODO: review filtering criteria

import psycopg2
from psycopg2.extras import execute_values, RealDictCursor
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable
import hashlib
import json
import re

from config import MERGED_JOBS_TABLE, DATABASE_CONFIG

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('merge_jobs.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class JobMerger:
    """
    Job Data Merger

    Reads job data from Jobs.ac.uk and Adzuna, standardises fields,
    filters invalid records, deduplicates, and saves to a unified table.
    """

    # Unified field mapping configuration
    # Format: target_field -> source column name (None = not available, callable = special handling)
    FIELD_MAPPING = {
        'jobs_ac_uk': {
            'source':             lambda job: 'jobs_ac_uk',
            'source_job_id':      'job_id',
            'title':              'title',
            'company':            'employer',
            'employer':           'employer',
            'department':         'department',
            'location':           'location',
            'area':               None,
            'salary':             'salary',
            'salary_min':         None,
            'salary_max':         None,
            'hours':              'hours',
            'job_type':           'job_type',
            'contract_type':      'contract_type',
            'contract_time':      None,
            'description':        'description',
            'full_description':   'full_description',
            'requirements':       'requirements',
            'responsibilities':   'responsibilities',
            'url':                'url',
            'apply_url':          'apply_url',
            'redirect_url':       None,
            'published_date':     'published_date',
            'closing_date':       'closing_date',
            'expires':            'expires',
            'placed_on':          'placed_on',
            'created':            None,
            'category':           'category',
            'subcategory':        'subcategory',
            'required_education': lambda job: JobMerger._extract_required_education(job),
            'required_experience_years': lambda job: JobMerger._extract_required_experience_years(job),
            'company_size':       lambda job: JobMerger._extract_company_size(job),
            'industry':           lambda job: JobMerger._extract_industry(job),
            'company_type':       lambda job: JobMerger._extract_company_type(job),
            'view_count':         lambda job: JobMerger._extract_int_metric(job, "view_count", "views", "impressions"),
            'application_count':  lambda job: JobMerger._extract_int_metric(job, "application_count", "applications"),
            'competition_level':  lambda job: JobMerger._extract_float_metric(job, "competition_level"),
            'country':            lambda job: 'uk',
            'job_ref':            'job_ref',
            'feed_source':        'feed_source',
            'original_scraped_at': 'scraped_at',
            'raw_data':           'raw_data',
        },
        'adzuna': {
            'source':             lambda job: 'adzuna',
            'source_job_id':      'job_id',
            'title':              'title',
            'company':            'company',
            'employer':           'company',
            'department':         None,
            'location':           'location',
            'area':               'area',
            'salary':             None,  # built from salary_min / salary_max
            'salary_min':         'salary_min',
            'salary_max':         'salary_max',
            'hours':              None,
            'job_type':           'contract_type',
            'contract_type':      'contract_type',
            'contract_time':      'contract_time',
            'description':        'description',
            'full_description':   'description',
            'requirements':       None,
            'responsibilities':   None,
            'url':                'url',
            'apply_url':          'redirect_url',
            'redirect_url':       'redirect_url',
            'published_date':     None,
            'closing_date':       None,
            'expires':            None,
            'placed_on':          None,
            'created':            'created',
            'category':           'category',
            'subcategory':        None,
            'required_education': lambda job: JobMerger._extract_required_education(job),
            'required_experience_years': lambda job: JobMerger._extract_required_experience_years(job),
            'company_size':       lambda job: JobMerger._extract_company_size(job),
            'industry':           lambda job: JobMerger._extract_industry(job),
            'company_type':       lambda job: JobMerger._extract_company_type(job),
            'view_count':         lambda job: JobMerger._extract_int_metric(job, "view_count", "views", "impressions"),
            'application_count':  lambda job: JobMerger._extract_int_metric(job, "application_count", "applications"),
            'competition_level':  lambda job: JobMerger._extract_float_metric(job, "competition_level"),
            'country':            'country',
            'job_ref':            None,
            'feed_source':        lambda job: 'adzuna',
            'original_scraped_at': 'scraped_at',
            'raw_data':           'raw_data',
        }
    }

    REQUIRED_FIELDS = ['title', 'company', 'location']

    def __init__(self, db_config: Dict[str, str], merged_table: Optional[str] = None):
        self.db_config = db_config
        self.merged_table = merged_table or MERGED_JOBS_TABLE
        self.init_merged_table()

        self.stats = {
            'jobs_ac_uk_total': 0,
            'jobs_ac_uk_in_source': 0,
            'jobs_ac_uk_filtered': 0,
            'adzuna_total': 0,
            'adzuna_in_source': 0,
            'adzuna_filtered': 0,
            'merge_fetch_only_new': False,
            'duplicates_removed': 0,
            'skipped_existing_job_id': 0,
            'merged_total': 0,
            'start_time': datetime.now(),
        }

    def get_connection(self):
        """Get a database connection."""
        return psycopg2.connect(
            host=self.db_config.get("host"),
            port=self.db_config.get("port"),
            database=self.db_config.get("database"),
            user=self.db_config.get("user"),
            password=self.db_config.get("password"),
        )

    def init_merged_table(self):
        """Create the merge target table and indexes if they don't exist."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            mt = self.merged_table
            idx = f"idx_{mt}"

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {mt} (
                    id SERIAL PRIMARY KEY,
                    job_id VARCHAR(255) UNIQUE,
                    source VARCHAR(50) NOT NULL,
                    source_job_id VARCHAR(255),

                    -- Basic info
                    title TEXT NOT NULL,
                    company TEXT,
                    employer TEXT,
                    department TEXT,
                    location TEXT,
                    area TEXT,

                    -- Salary and contract
                    salary TEXT,
                    salary_min DECIMAL(10, 2),
                    salary_max DECIMAL(10, 2),
                    hours TEXT,
                    job_type TEXT,
                    contract_type TEXT,
                    contract_time TEXT,

                    -- Job description
                    description TEXT,
                    full_description TEXT,
                    requirements TEXT,
                    responsibilities TEXT,

                    -- URLs
                    url TEXT,
                    apply_url TEXT,
                    redirect_url TEXT,

                    -- Dates
                    published_date TIMESTAMP,
                    closing_date TIMESTAMP,
                    expires TEXT,
                    placed_on TEXT,
                    created TIMESTAMP,

                    -- Classification
                    category TEXT,
                    subcategory TEXT,
                    required_education TEXT,
                    required_experience_years FLOAT,
                    company_size TEXT,
                    industry TEXT,
                    company_type TEXT,
                    view_count INTEGER,
                    application_count INTEGER,
                    competition_level FLOAT,
                    country VARCHAR(10),

                    -- Metadata
                    job_ref VARCHAR(100),
                    feed_source TEXT,

                    -- Deduplication
                    dedup_hash VARCHAR(64),
                    duplicate_of INTEGER REFERENCES {mt}(id),

                    -- Timestamps
                    merged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    original_scraped_at TIMESTAMP,

                    -- Raw payload
                    raw_data JSONB
                )
            """)

            for ddl in (
                f"ALTER TABLE {mt} ADD COLUMN IF NOT EXISTS required_education TEXT",
                f"ALTER TABLE {mt} ADD COLUMN IF NOT EXISTS required_experience_years FLOAT",
                f"ALTER TABLE {mt} ADD COLUMN IF NOT EXISTS company_size TEXT",
                f"ALTER TABLE {mt} ADD COLUMN IF NOT EXISTS industry TEXT",
                f"ALTER TABLE {mt} ADD COLUMN IF NOT EXISTS company_type TEXT",
                f"ALTER TABLE {mt} ADD COLUMN IF NOT EXISTS view_count INTEGER",
                f"ALTER TABLE {mt} ADD COLUMN IF NOT EXISTS application_count INTEGER",
                f"ALTER TABLE {mt} ADD COLUMN IF NOT EXISTS competition_level FLOAT",
            ):
                cursor.execute(ddl)

            index_defs = [
                (f"{idx}_job_id",          f"{mt}(job_id)"),
                (f"{idx}_source",          f"{mt}(source)"),
                (f"{idx}_dedup_hash",      f"{mt}(dedup_hash)"),
                (f"{idx}_company",         f"{mt}(company)"),
                (f"{idx}_location",        f"{mt}(location)"),
                (f"{idx}_created",         f"{mt}(created)"),
                (f"{idx}_published_date",  f"{mt}(published_date)"),
            ]
            for idx_name, idx_expr in index_defs:
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_expr}"
                )

            cursor.execute(f"""
                CREATE INDEX IF NOT EXISTS {idx}_title
                ON {mt} USING gin(to_tsvector('english', title))
            """)

            conn.commit()
            cursor.close()
            conn.close()
            logger.info("Merged table initialised successfully")
        except Exception as e:
            logger.error(f"Failed to initialise merged table: {e}")
            raise

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def is_valid_job(self, job: Dict, source: str) -> bool:
        """Return True if all REQUIRED_FIELDS resolve to non-empty values."""
        mapping = self.FIELD_MAPPING[source]

        for field in self.REQUIRED_FIELDS:
            field_mapping = mapping.get(field)

            if callable(field_mapping):
                value = field_mapping(job)
            elif field_mapping is None:
                value = None
            else:
                value = job.get(field_mapping)

            if value is None or (isinstance(value, str) and value.strip() == ''):
                logger.debug(
                    f"Filtered job ({field} is empty): {job.get('job_id', 'unknown')}"
                )
                return False

        return True

    # ------------------------------------------------------------------
    # Text normalisation & dedup hash
    # ------------------------------------------------------------------

    def normalize_text(self, text: str) -> str:
        """Normalise text for dedup comparison (lowercase, strip punctuation)."""
        if not text:
            return ""
        text = text.lower()
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'[^\w\s]', '', text)
        return text.strip()

    def generate_dedup_hash(self, title: str, company: str, location: str) -> str:
        """Generate a SHA-256 dedup hash from normalised title|company|location."""
        norm_title = self.normalize_text(title or "")
        norm_company = self.normalize_text(company or "")
        norm_location = self.normalize_text(location or "")
        combined = f"{norm_title}|{norm_company}|{norm_location}"
        return hashlib.sha256(combined.encode()).hexdigest()

    @staticmethod
    def build_unified_job_id(
        source: str,
        source_job_id: Optional[str],
        dedup_hash: str,
    ) -> str:
        """
        Stable id for merged_jobs.job_id, aligned with fetch-time NOT EXISTS filter.

        Crawler rows use ``jobs_ac_uk_<job_id>`` / ``adzuna_<job_id>`` when ``job_id`` is present.
        If source_job_id is missing, fall back to md5(dedup_hash) (legacy / edge cases).
        """
        if source_job_id is not None:
            sid = str(source_job_id).strip()
            if sid:
                return f"{source}_{sid}"
        return f"{source}_{hashlib.md5(dedup_hash.encode()).hexdigest()}"

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def fetch_jobs_ac_uk_jobs(self, only_new: bool = True) -> List[Dict]:
        """
        Load rows from jobs_ac_uk_jobs.

        If only_new is True, return only rows not yet present in merged_jobs, matching
        unified id ``jobs_ac_uk_`` || job_id (same as post-merge ``merged_jobs.job_id``).
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            cursor.execute("SELECT COUNT(*) AS cnt FROM jobs_ac_uk_jobs")
            row = cursor.fetchone()
            # RealDictCursor: rows are name-keyed; [0] raises KeyError(0) (logged as "Error ...: 0")
            self.stats['jobs_ac_uk_in_source'] = (
                int(list(row.values())[0]) if row else 0
            )

            if only_new:
                cursor.execute(f"""
                    SELECT j.* FROM jobs_ac_uk_jobs j
                    WHERE j.job_id IS NOT NULL
                      AND TRIM(j.job_id::text) <> ''
                      AND NOT EXISTS (
                        SELECT 1 FROM {self.merged_table} m
                        WHERE m.job_id = ('jobs_ac_uk_' || j.job_id::text)
                      )
                    ORDER BY j.scraped_at DESC NULLS LAST
                """)
            else:
                cursor.execute("""
                    SELECT * FROM jobs_ac_uk_jobs
                    ORDER BY scraped_at DESC NULLS LAST
                """)

            jobs = cursor.fetchall()
            self.stats['jobs_ac_uk_total'] = len(jobs)

            cursor.close()
            conn.close()

            logger.info(
                f"Fetched {len(jobs)} jobs.ac.uk rows from jobs_ac_uk_jobs "
                f"(only_new={only_new}, table has {self.stats['jobs_ac_uk_in_source']} rows)"
            )
            return [dict(job) for job in jobs]
        except Exception as e:
            logger.error(f"Error reading Jobs.ac.uk data: {e}")
            return []

    def fetch_adzuna_jobs(self, only_new: bool = True) -> List[Dict]:
        """Load adzuna_jobs; if only_new, exclude rows already merged as ``adzuna_<job_id>``."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            cursor.execute("SELECT COUNT(*) AS cnt FROM adzuna_jobs")
            row = cursor.fetchone()
            self.stats['adzuna_in_source'] = int(list(row.values())[0]) if row else 0

            if only_new:
                cursor.execute(f"""
                    SELECT j.* FROM adzuna_jobs j
                    WHERE j.job_id IS NOT NULL
                      AND TRIM(j.job_id::text) <> ''
                      AND NOT EXISTS (
                        SELECT 1 FROM {self.merged_table} m
                        WHERE m.job_id = ('adzuna_' || j.job_id::text)
                      )
                    ORDER BY j.scraped_at DESC NULLS LAST
                """)
            else:
                cursor.execute("""
                    SELECT * FROM adzuna_jobs
                    ORDER BY scraped_at DESC NULLS LAST
                """)

            jobs = cursor.fetchall()
            self.stats['adzuna_total'] = len(jobs)

            cursor.close()
            conn.close()

            logger.info(
                f"Fetched {len(jobs)} Adzuna rows from adzuna_jobs "
                f"(only_new={only_new}, table has {self.stats['adzuna_in_source']} rows)"
            )
            return [dict(job) for job in jobs]
        except Exception as e:
            logger.error(f"Error reading Adzuna data: {e}")
            return []

    # ------------------------------------------------------------------
    # Field mapping
    # ------------------------------------------------------------------

    def map_job_to_unified_format(self, job: Dict, source: str) -> Dict:
        """Map a raw job dict to the unified merged_jobs schema."""
        mapping = self.FIELD_MAPPING[source]
        unified_job: Dict[str, Any] = {}

        for target_field, source_field in mapping.items():
            if callable(source_field):
                unified_job[target_field] = source_field(job)
            elif source_field is None:
                unified_job[target_field] = None
            else:
                unified_job[target_field] = job.get(source_field)

        # Build salary text for Adzuna from salary_min / salary_max
        if source == 'adzuna' and not unified_job.get('salary'):
            salary_min = unified_job.get('salary_min')
            salary_max = unified_job.get('salary_max')

            if salary_min or salary_max:
                if salary_min and salary_max:
                    if salary_min == salary_max:
                        salary_text = f"£{salary_min:,.0f}"
                    else:
                        salary_text = f"£{salary_min:,.0f} - £{salary_max:,.0f}"
                elif salary_min:
                    salary_text = f"£{salary_min:,.0f}+"
                else:
                    salary_text = f"Up to £{salary_max:,.0f}"
                unified_job['salary'] = salary_text

        # Fallback: use url when apply_url is missing
        if not unified_job.get('apply_url'):
            unified_job['apply_url'] = unified_job.get('url')

        return unified_job

    @staticmethod
    def _raw_payload(job: Dict) -> Dict[str, Any]:
        raw_data = job.get("raw_data")
        return raw_data if isinstance(raw_data, dict) else {}

    @staticmethod
    def _extract_raw_value(job: Dict, *keys: str) -> Any:
        for key in keys:
            value = job.get(key)
            if value not in (None, ""):
                return value
        raw = JobMerger._raw_payload(job)
        for key in keys:
            value = raw.get(key)
            if value not in (None, ""):
                return value
        return None

    @staticmethod
    def _extract_int_metric(job: Dict, *keys: str) -> Optional[int]:
        value = JobMerger._extract_raw_value(job, *keys)
        if value in (None, ""):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_float_metric(job: Dict, *keys: str) -> Optional[float]:
        value = JobMerger._extract_raw_value(job, *keys)
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_required_education(job: Dict) -> Optional[str]:
        direct = JobMerger._extract_raw_value(
            job,
            "required_education",
            "education_requirement",
            "education_level",
            "qualification",
        )
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        text = " ".join(
            str(job.get(k) or "")
            for k in ("title", "requirements", "description", "full_description")
        ).lower()
        if any(k in text for k in ("phd", "doctorate")):
            return "PhD"
        if any(k in text for k in ("master", "msc", "ms ")):
            return "Master"
        if any(k in text for k in ("bachelor", "undergraduate", "bs ", "bsc")):
            return "Bachelor"
        return None

    @staticmethod
    def _extract_required_experience_years(job: Dict) -> Optional[float]:
        direct = JobMerger._extract_float_metric(
            job,
            "required_experience_years",
            "experience_years",
            "min_experience_years",
        )
        if direct is not None:
            return max(0.0, direct)
        text = " ".join(
            str(job.get(k) or "")
            for k in ("title", "requirements", "description", "full_description")
        ).lower()
        matches = re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", text)
        if matches:
            try:
                return max(0.0, float(matches[0]))
            except ValueError:
                return None
        return None

    @staticmethod
    def _extract_company_size(job: Dict) -> Optional[str]:
        value = JobMerger._extract_raw_value(job, "company_size", "organization_size", "employer_size")
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _extract_industry(job: Dict) -> Optional[str]:
        value = JobMerger._extract_raw_value(job, "industry", "sector", "category", "subcategory")
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _extract_company_type(job: Dict) -> Optional[str]:
        value = JobMerger._extract_raw_value(job, "company_type", "employer_type", "organization_type")
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    # ------------------------------------------------------------------
    # Merge orchestration
    # ------------------------------------------------------------------

    def merge_jobs(
        self,
        clear_existing: bool = False,
        update_existing: bool = False,
        only_new: Optional[bool] = None,
    ):
        """
        Run the full merge pipeline: fetch → map → filter → dedup → save.

        Args:
            clear_existing: If True, truncate merged_jobs before inserting (full rebuild).
            update_existing: If True, ON CONFLICT (job_id) updates the row from source.
                If False (default), conflicts are ignored so existing merged rows stay as-is.
                Ignored when clear_existing=True (table is empty).
            only_new: If True, SQL only loads source rows whose unified ``job_id`` is not
                yet in merged_jobs (matches crawler incremental adds). If False, loads
                every row from jobs_ac_uk_jobs and adzuna_jobs.
                Default: True when not clearing and not updating; False when
                ``clear_existing`` or ``update_existing`` (full table scan for rebuild/sync).
        """
        if only_new is None:
            only_new = (not clear_existing) and (not update_existing)

        self.stats['jobs_ac_uk_filtered'] = 0
        self.stats['adzuna_filtered'] = 0
        self.stats['duplicates_removed'] = 0
        self.stats['skipped_existing_job_id'] = 0
        self.stats['merged_total'] = 0
        self.stats['merge_fetch_only_new'] = bool(only_new)

        logger.info("=" * 80)
        logger.info("Starting job merge")
        if clear_existing:
            logger.info("Mode: full rebuild (truncate merged_jobs)")
        else:
            logger.info(
                "Mode: incremental "
                f"(only_new={only_new}, update_existing={'on' if update_existing else 'off'})"
            )
        logger.info("=" * 80)

        if clear_existing:
            logger.info("Truncating existing merge table %s...", self.merged_table)
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(f"TRUNCATE TABLE {self.merged_table} RESTART IDENTITY CASCADE")
            conn.commit()
            cursor.close()
            conn.close()

        logger.info("Fetching Jobs.ac.uk data...")
        jobs_ac_uk_jobs = self.fetch_jobs_ac_uk_jobs(only_new=only_new)

        logger.info("Fetching Adzuna data...")
        adzuna_jobs = self.fetch_adzuna_jobs(only_new=only_new)

        logger.info("Mapping to unified schema and filtering invalid records...")
        unified_jobs: List[Dict] = []

        for job in jobs_ac_uk_jobs:
            if self.is_valid_job(job, 'jobs_ac_uk'):
                unified_jobs.append(self.map_job_to_unified_format(job, 'jobs_ac_uk'))
            else:
                self.stats['jobs_ac_uk_filtered'] += 1

        for job in adzuna_jobs:
            if self.is_valid_job(job, 'adzuna'):
                unified_jobs.append(self.map_job_to_unified_format(job, 'adzuna'))
            else:
                self.stats['adzuna_filtered'] += 1

        jac_valid = len(jobs_ac_uk_jobs) - self.stats['jobs_ac_uk_filtered']
        adz_valid = len(adzuna_jobs) - self.stats['adzuna_filtered']

        logger.info(f"Total valid jobs to merge: {len(unified_jobs)}")
        logger.info(
            f"  Jobs.ac.uk: {len(jobs_ac_uk_jobs)} fetched, "
            f"{self.stats['jobs_ac_uk_filtered']} filtered, {jac_valid} valid"
        )
        logger.info(
            f"  Adzuna: {len(adzuna_jobs)} fetched, "
            f"{self.stats['adzuna_filtered']} filtered, {adz_valid} valid"
        )

        logger.info("Deduplicating and saving to %s...", self.merged_table)
        self.save_merged_jobs(unified_jobs, update_existing=update_existing)

        self.print_statistics()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    # All columns written during INSERT (order matters – must match VALUES tuple)
    _INSERT_COLUMNS = [
        'job_id', 'source', 'source_job_id', 'title', 'company', 'employer',
        'department', 'location', 'area', 'salary', 'salary_min', 'salary_max',
        'hours', 'job_type', 'contract_type', 'contract_time', 'description',
        'full_description', 'requirements', 'responsibilities', 'url',
        'apply_url', 'redirect_url', 'published_date', 'closing_date',
        'expires', 'placed_on', 'created', 'category', 'subcategory',
        'required_education', 'required_experience_years', 'company_size', 'industry',
        'company_type', 'view_count', 'application_count', 'competition_level',
        'country', 'job_ref', 'feed_source', 'dedup_hash',
        'original_scraped_at', 'raw_data',
    ]

    # Columns updated on conflict (exclude job_id)
    _UPSERT_COLUMNS = [c for c in _INSERT_COLUMNS if c != 'job_id']

    def _build_insert_query(self, update_on_conflict: bool) -> str:
        cols = ', '.join(self._INSERT_COLUMNS)
        mt = self.merged_table
        if not update_on_conflict:
            return (
                f"INSERT INTO {mt} ({cols}) VALUES %s "
                f"ON CONFLICT (job_id) DO NOTHING"
            )
        upsert = ', '.join(
            f"{c} = EXCLUDED.{c}" for c in self._UPSERT_COLUMNS
        )
        return (
            f"INSERT INTO {mt} ({cols}) VALUES %s "
            f"ON CONFLICT (job_id) DO UPDATE SET {upsert}, "
            f"merged_at = CURRENT_TIMESTAMP"
        )

    def save_merged_jobs(
        self,
        jobs: List[Dict],
        batch_size: int = 100,
        update_existing: bool = False,
    ):
        """Save unified jobs to merged_jobs with dedup.

        When update_existing is False, rows with an existing job_id are not modified
        (ON CONFLICT DO NOTHING). When True, conflicting rows are overwritten from source.
        """
        if not jobs:
            logger.warning("No jobs to save")
            return

        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            existing_hashes: set = set()
            cursor.execute(
                f"SELECT dedup_hash FROM {self.merged_table} WHERE dedup_hash IS NOT NULL"
            )
            for row in cursor.fetchall():
                existing_hashes.add(row[0])

            logger.info(f"Existing dedup hashes in DB: {len(existing_hashes)}")

            insert_query = self._build_insert_query(update_on_conflict=update_existing)
            values: list = []
            duplicates = 0
            saved_count = 0
            skipped_job_id = 0

            for job in jobs:
                title = str(job.get('title') or '')
                company = str(job.get('company') or job.get('employer') or '')
                location = str(job.get('location') or '')
                dedup_hash = self.generate_dedup_hash(
                    title,
                    company,
                    location,
                )

                if dedup_hash in existing_hashes:
                    duplicates += 1
                    logger.debug(
                        f"Skipping duplicate: {job.get('title')} @ {job.get('company')}"
                    )
                    continue

                existing_hashes.add(dedup_hash)

                job_id = self.build_unified_job_id(
                    job['source'],
                    job.get('source_job_id'),
                    dedup_hash,
                )

                values.append((
                    job_id,
                    job.get('source'),
                    job.get('source_job_id'),
                    job.get('title'),
                    job.get('company'),
                    job.get('employer'),
                    job.get('department'),
                    job.get('location'),
                    job.get('area'),
                    job.get('salary'),
                    job.get('salary_min'),
                    job.get('salary_max'),
                    job.get('hours'),
                    job.get('job_type'),
                    job.get('contract_type'),
                    job.get('contract_time'),
                    job.get('description'),
                    job.get('full_description'),
                    job.get('requirements'),
                    job.get('responsibilities'),
                    job.get('url'),
                    job.get('apply_url'),
                    job.get('redirect_url'),
                    job.get('published_date'),
                    job.get('closing_date'),
                    job.get('expires'),
                    job.get('placed_on'),
                    job.get('created'),
                    job.get('category'),
                    job.get('subcategory'),
                    job.get('required_education'),
                    job.get('required_experience_years'),
                    job.get('company_size'),
                    job.get('industry'),
                    job.get('company_type'),
                    job.get('view_count'),
                    job.get('application_count'),
                    job.get('competition_level'),
                    job.get('country'),
                    job.get('job_ref'),
                    job.get('feed_source'),
                    dedup_hash,
                    job.get('original_scraped_at'),
                    json.dumps(job.get('raw_data') or {}),
                ))

                if len(values) >= batch_size:
                    execute_values(cursor, insert_query, values)
                    conn.commit()
                    n = cursor.rowcount
                    saved_count += n
                    if not update_existing:
                        skipped_job_id += len(values) - n
                    logger.info(f"Inserted/updated {saved_count} jobs so far")
                    values = []

            if values:
                execute_values(cursor, insert_query, values)
                conn.commit()
                n = cursor.rowcount
                saved_count += n
                if not update_existing:
                    skipped_job_id += len(values) - n
                logger.info(f"Inserted/updated {saved_count} jobs so far")

            self.stats['duplicates_removed'] = duplicates
            self.stats['skipped_existing_job_id'] = skipped_job_id
            self.stats['merged_total'] = saved_count

            cursor.close()
            conn.close()

            logger.info(
                f"Merge complete: {saved_count} rows written to {self.merged_table} "
                f"(after dedup)"
            )
            logger.info(f"Skipped {duplicates} jobs (same dedup_hash as existing row)")
            if not update_existing and skipped_job_id:
                logger.info(
                    f"Skipped {skipped_job_id} rows (job_id already in {self.merged_table})"
                )

        except Exception as e:
            logger.error(f"Error saving merged data: {e}")
            raise

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def print_statistics(self):
        """Print merge statistics."""
        duration = (datetime.now() - self.stats['start_time']).total_seconds()

        logger.info("\n" + "=" * 80)
        logger.info("Merge Statistics")
        logger.info("=" * 80)
        if self.stats.get('merge_fetch_only_new'):
            logger.info(
                f"Jobs.ac.uk: fetched {self.stats['jobs_ac_uk_total']} rows not yet in merged_jobs "
                f"(source table has {self.stats.get('jobs_ac_uk_in_source', 0)} rows)"
            )
            logger.info(
                f"Adzuna: fetched {self.stats['adzuna_total']} rows not yet in merged_jobs "
                f"(source table has {self.stats.get('adzuna_in_source', 0)} rows)"
            )
        else:
            logger.info(f"Jobs.ac.uk rows fetched: {self.stats['jobs_ac_uk_total']}")
            logger.info(f"Adzuna rows fetched: {self.stats['adzuna_total']}")

        logger.info(f"  Jobs.ac.uk filtered (missing required fields): {self.stats['jobs_ac_uk_filtered']}")
        logger.info(f"  Jobs.ac.uk valid: {self.stats['jobs_ac_uk_total'] - self.stats['jobs_ac_uk_filtered']}")
        logger.info(f"  Adzuna filtered (missing required fields): {self.stats['adzuna_filtered']}")
        logger.info(f"  Adzuna valid: {self.stats['adzuna_total'] - self.stats['adzuna_filtered']}")

        total_input = self.stats['jobs_ac_uk_total'] + self.stats['adzuna_total']
        total_filtered = self.stats['jobs_ac_uk_filtered'] + self.stats['adzuna_filtered']
        total_valid = total_input - total_filtered

        logger.info(f"Total input: {total_input}")
        if total_input > 0:
            logger.info(
                f"Total filtered: {total_filtered} "
                f"({total_filtered / total_input * 100:.2f}%)"
            )
        else:
            logger.info("Total filtered: 0")
        logger.info(f"Total valid: {total_valid}")
        logger.info(f"Duplicates removed: {self.stats['duplicates_removed']}")
        if self.stats.get('skipped_existing_job_id', 0):
            logger.info(
                f"Skipped (ON CONFLICT, existing job_id): {self.stats['skipped_existing_job_id']} "
                f"(should be 0 when only_new=True; safety net otherwise)"
            )
        logger.info(f"Rows inserted/updated this run: {self.stats['merged_total']}")

        if total_valid > 0:
            logger.info(
                f"Dedup rate: "
                f"{self.stats['duplicates_removed'] / total_valid * 100:.2f}%"
            )

        logger.info(f"Duration: {duration:.2f}s")
        logger.info("=" * 80)

        self.print_source_distribution()
        self.print_field_coverage()

    def print_source_distribution(self):
        """Print per-source job counts from the merge target table."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            cursor.execute(f"""
                SELECT source, COUNT(*) AS count
                FROM {self.merged_table}
                GROUP BY source
                ORDER BY count DESC
            """)

            logger.info("\nSource distribution:")
            logger.info("-" * 80)
            for row in cursor.fetchall():
                logger.info(f"  {row[0]}: {row[1]} jobs")

            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Error fetching source distribution: {e}")

    def print_field_coverage(self):
        """Print non-null coverage for key fields."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            cursor.execute(f"SELECT COUNT(*) FROM {self.merged_table}")
            total_row = cursor.fetchone()
            total = int(total_row[0]) if total_row else 0

            if total == 0:
                return

            logger.info("\nField coverage:")
            logger.info("-" * 80)

            key_fields = [
                'title', 'company', 'location', 'salary', 'description',
                'url', 'category', 'contract_type', 'apply_url',
            ]

            for field in key_fields:
                cursor.execute(f"""
                    SELECT COUNT(*)
                    FROM {self.merged_table}
                    WHERE {field} IS NOT NULL AND {field} != ''
                """)
                count_row = cursor.fetchone()
                count = int(count_row[0]) if count_row else 0
                pct = (count / total * 100) if total > 0 else 0
                filled = int(pct / 2)
                bar = '\u2588' * filled + '\u2591' * (50 - filled)
                logger.info(f"  {field:15s} {bar} {pct:6.2f}% ({count}/{total})")

            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Error fetching field coverage: {e}")

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_merged_jobs(
        self, output_file: str = 'merged_jobs.csv', limit: Optional[int] = None
    ):
        """Export merged jobs to a CSV file (excluding raw_data)."""
        try:
            import csv

            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            query = f"SELECT * FROM {self.merged_table} ORDER BY merged_at DESC"
            if limit:
                query += f" LIMIT {limit}"

            cursor.execute(query)
            jobs = cursor.fetchall()

            if jobs:
                with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                    fieldnames = [k for k in jobs[0].keys() if k != 'raw_data']
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()

                    for job in jobs:
                        row = {k: v for k, v in dict(job).items() if k != 'raw_data'}
                        writer.writerow(row)

                logger.info(f"Exported {len(jobs)} jobs to {output_file}")

            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Error exporting CSV: {e}")


def main():
    merger = JobMerger(DATABASE_CONFIG)

    # Incremental: SQL only loads rows whose unified job_id is not yet in merged_jobs
    # (jobs_ac_uk_<id> / adzuna_<id>), then dedup_hash; ON CONFLICT DO NOTHING.
    # Full rebuild: merger.merge_jobs(clear_existing=True)  # only_new=False implicit
    # Resync all rows from source: merger.merge_jobs(update_existing=True, only_new=False)
    merger.merge_jobs(clear_existing=False, update_existing=False)

    # Optional: export to CSV
    # merger.export_merged_jobs('merged_jobs.csv', limit=1000)


if __name__ == "__main__":
    main()
