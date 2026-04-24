"""
Adzuna API Crawler
Fetches UK job listings via the official Adzuna API.

Docs: https://developer.adzuna.com/docs/search

Features:
- Official API, stable and compliant
- Search params: keywords, location, salary, etc.
- PostgreSQL integration
- Deduplication and error handling
- Rate limiting
"""

import itertools
import time
import random
import requests
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import psycopg2
from psycopg2.extras import execute_values
import json
from tqdm import tqdm
from config import ADZUNA_CONFIG, DATABASE_CONFIG  # type: ignore[attr-defined]

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('adzuna_crawler.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class AdzunaCrawler:
    """
    Adzuna API crawler.

    - Fetches jobs via official API
    - Multiple search dimensions
    - PostgreSQL storage
    - Deduplication by job_id
    """

    # API config
    API_BASE_URL = "https://api.adzuna.com/v1/api/jobs"
    COUNTRY = "gb"  # United Kingdom

    # Default keywords (graduate / early career)
    DEFAULT_KEYWORDS = [
        'graduate',
        'graduate scheme',
        'internship',
        'placement',
        'entry level',
        'junior',
    ]

    # Fallback category tags if fetch_categories() fails
    CATEGORIES = [
        'it-jobs',
        'engineering-jobs',
        'accounting-finance-jobs',
        'graduate-jobs',
        'healthcare-nursing-jobs',
        'legal-jobs',
        'marketing-advertising-pr-jobs',
        'scientific-qa-jobs',
        'admin-jobs',
        'creative-design-jobs',
        'customer-services-jobs',
        'energy-oil-gas-jobs',
        'hr-jobs',
        'logistics-warehouse-jobs',
        'manufacturing-jobs',
        'property-jobs',
        'retail-jobs',
        'sales-jobs',
        'social-work-jobs',
        'teaching-jobs',
        'trade-construction-jobs',
        'travel-jobs',
    ]

    def __init__(self, app_id: str, app_key: str, db_config: Dict[str, Any],
                 delay_range: Tuple[float, float] = (1.0, 2.0)):
        """
        Args:
            app_id: Adzuna API app id
            app_key: Adzuna API app key
            db_config: PostgreSQL connection kwargs
            delay_range: Random delay between requests (seconds), (min, max)
        """
        self.app_id = app_id
        self.app_key = app_key
        self.delay_range = delay_range

        self.db_config = db_config
        self.init_database()

        self.request_count = 0
        self.jobs_found = 0
        self.jobs_saved = 0
        self.error_count = 0
        self.start_time = datetime.now()

        logger.info("Adzuna crawler initialized")

    def init_database(self):
        """Create PostgreSQL table and indexes if missing."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS adzuna_jobs (
                    id SERIAL PRIMARY KEY,
                    job_id VARCHAR(255) UNIQUE,
                    title TEXT NOT NULL,
                    company TEXT,
                    location TEXT,
                    area TEXT,
                    salary_min DECIMAL(10, 2),
                    salary_max DECIMAL(10, 2),
                    contract_type TEXT,
                    contract_time TEXT,
                    description TEXT,
                    category TEXT,
                    url TEXT,
                    redirect_url TEXT,
                    created TIMESTAMP,
                    country VARCHAR(10) DEFAULT 'gb',
                    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    raw_data JSONB
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_adzuna_job_id 
                ON adzuna_jobs(job_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_adzuna_company 
                ON adzuna_jobs(company)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_adzuna_location 
                ON adzuna_jobs(location)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_adzuna_category 
                ON adzuna_jobs(category)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_adzuna_created 
                ON adzuna_jobs(created)
            """)

            conn.commit()
            cursor.close()
            conn.close()
            logger.info("Database tables ready")
        except Exception as e:
            logger.error(f"Database init failed: {e}")
            raise

    def fetch_categories(self) -> List[str]:
        """Fetch all category tags from the API."""
        try:
            self.rate_limit()
            url = f"{self.API_BASE_URL}/{self.COUNTRY}/categories"
            params = {'app_id': self.app_id, 'app_key': self.app_key}
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            tags = [item['tag'] for item in data.get('results', []) if item.get('tag')]
            logger.info(f"Loaded {len(tags)} categories from API: {tags}")
            return tags
        except Exception as e:
            logger.warning(f"fetch_categories failed, using CATEGORIES fallback: {e}")
            return self.CATEGORIES

    def rate_limit(self):
        """Sleep for a random delay within delay_range."""
        delay = random.uniform(*self.delay_range)
        logger.debug(f"Sleep {delay:.2f}s")
        time.sleep(delay)

    def search_jobs(self, what: str = "", where: str = "",
                    category: str = "", max_days_old: int = 30,
                    results_per_page: int = 50, page: int = 1,
                    sort_by: str = "date") -> Optional[Dict]:
        """
        Single search request.

        Args:
            what: Query text (title, description, etc.)
            where: Location string
            category: Adzuna category tag
            max_days_old: Max listing age in days
            results_per_page: Page size (max 50)
            page: 1-based page index
            sort_by: date | relevance | salary

        Returns:
            Parsed JSON dict or None on failure
        """
        try:
            self.rate_limit()

            url = f"{self.API_BASE_URL}/{self.COUNTRY}/search/{page}"

            params = {
                'app_id': self.app_id,
                'app_key': self.app_key,
                'results_per_page': min(results_per_page, 50),
                'what': what,
                'where': where,
                'max_days_old': max_days_old,
                'sort_by': sort_by,
            }

            if category:
                params['category'] = category

            params = {k: v for k, v in params.items() if v}

            logger.info(
                f"Search what='{what}' where='{where}' category='{category}' page={page}"
            )

            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            self.request_count += 1
            data = response.json()

            logger.info(
                f"Got {len(data.get('results', []))} results (total count={data.get('count', 0)})"
            )

            return data

        except requests.exceptions.RequestException as e:
            self.error_count += 1
            logger.error(f"API request error: {e}")
            return None
        except json.JSONDecodeError as e:
            self.error_count += 1
            logger.error(f"JSON decode error: {e}")
            return None

    def parse_job(self, job_data: Dict) -> Optional[Dict]:
        """
        Normalize one job record from API JSON.

        Returns:
            Dict for DB insert or None if parsing fails
        """
        try:
            salary_min = job_data.get('salary_min')
            salary_max = job_data.get('salary_max')

            location_data = job_data.get('location', {})
            location_display = location_data.get('display_name', '')
            area = ', '.join(location_data.get('area', []))

            company_data = job_data.get('company', {})
            company_name = company_data.get('display_name', '')

            category_data = job_data.get('category', {})
            category = (
                category_data.get('label', '')
                if isinstance(category_data, dict)
                else str(category_data)
            )

            created = job_data.get('created')
            if created:
                try:
                    created = datetime.fromisoformat(created.replace('Z', '+00:00'))
                except Exception:
                    created = None

            parsed_job = {
                'job_id': str(job_data.get('id')),
                'title': job_data.get('title'),
                'company': company_name,
                'location': location_display,
                'area': area,
                'salary_min': salary_min,
                'salary_max': salary_max,
                'contract_type': job_data.get('contract_type'),
                'contract_time': job_data.get('contract_time'),
                'description': job_data.get('description'),
                'category': category,
                'url': job_data.get('redirect_url'),
                'redirect_url': job_data.get('redirect_url'),
                'created': created,
                'country': 'gb',
                'raw_data': job_data
            }

            return parsed_job

        except Exception as e:
            logger.error(f"parse_job error: {e}")
            return None

    def crawl_search(self, what: str = "", where: str = "",
                     category: str = "", max_pages: int = 5,
                     max_days_old: int = 30) -> List[Dict]:
        """
        Paginate search_jobs for one (what, where, category) combo.

        Returns:
            List of parsed job dicts
        """
        jobs = []

        for page in range(1, max_pages + 1):
            data = self.search_jobs(
                what=what,
                where=where,
                category=category,
                max_days_old=max_days_old,
                page=page
            )

            if not data or 'results' not in data:
                break

            results = data['results']
            if not results:
                break

            for job_data in results:
                parsed_job = self.parse_job(job_data)
                if parsed_job:
                    jobs.append(parsed_job)

            total_count = data.get('count', 0)
            current_count = page * 50
            if current_count >= total_count:
                logger.info(f"All pages fetched for this query ({total_count} total)")
                break

        self.jobs_found += len(jobs)
        return jobs

    def save_to_database(self, jobs_data: List[Dict]):
        """Upsert jobs into adzuna_jobs."""
        if not jobs_data:
            logger.warning("No jobs to save")
            return

        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()

            insert_query = """
                INSERT INTO adzuna_jobs 
                (job_id, title, company, location, area, salary_min, salary_max, 
                 contract_type, contract_time, description, 
                 category, url, redirect_url, created,
                 country, raw_data)
                VALUES %s
                ON CONFLICT (job_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    company = EXCLUDED.company,
                    location = EXCLUDED.location,
                    area = EXCLUDED.area,
                    salary_min = EXCLUDED.salary_min,
                    salary_max = EXCLUDED.salary_max,
                    contract_type = EXCLUDED.contract_type,
                    contract_time = EXCLUDED.contract_time,
                    description = EXCLUDED.description,
                    category = EXCLUDED.category,
                    url = EXCLUDED.url,
                    redirect_url = EXCLUDED.redirect_url,
                    created = EXCLUDED.created,
                    country = EXCLUDED.country,
                    raw_data = EXCLUDED.raw_data,
                    scraped_at = CURRENT_TIMESTAMP
            """

            values = [
                (
                    job.get('job_id'),
                    job.get('title'),
                    job.get('company'),
                    job.get('location'),
                    job.get('area'),
                    job.get('salary_min'),
                    job.get('salary_max'),
                    job.get('contract_type'),
                    job.get('contract_time'),
                    job.get('description'),
                    job.get('category'),
                    job.get('url'),
                    job.get('redirect_url'),
                    job.get('created'),
                    job.get('country'),
                    json.dumps(job.get('raw_data', {}))
                )
                for job in jobs_data if job.get('job_id')
            ]

            if values:
                execute_values(cursor, insert_query, values)
                conn.commit()
                self.jobs_saved += len(values)
                logger.info(f"Saved {len(values)} rows to database")

            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Database save error: {e}")
            raise

    def crawl(self, keywords: Optional[List[str]] = None, locations: Optional[List[str]] = None,
              categories: Optional[List[str]] = None, max_pages: int = 5,
              max_days_old: int = 30, batch_size: int = 50,
              fetch_all_categories: bool = True):
        """
        Run all keyword x location x category combinations.

        Args:
            keywords: Search terms (defaults to DEFAULT_KEYWORDS)
            locations: where= values; use [""] for nationwide
            categories: Adzuna tags; if None and fetch_all_categories, from API
            max_pages: Max pages per combination
            max_days_old: Listing age filter
            batch_size: Flush to DB when buffer reaches this size
            fetch_all_categories: If categories is None, call fetch_categories()
        """
        logger.info("=" * 80)
        logger.info("Starting Adzuna crawl")
        logger.info("=" * 80)

        if keywords is None:
            keywords = self.DEFAULT_KEYWORDS
        if locations is None:
            locations = [""]
        if categories is None:
            categories = self.fetch_categories() if fetch_all_categories else [""]

        logger.info(f"keywords={keywords}")
        logger.info(f"locations={locations if locations != [''] else ['(nationwide)']}")
        logger.info(f"categories={categories if categories != [''] else ['(all)']}")
        logger.info(f"max_pages={max_pages} max_days_old={max_days_old}")

        all_jobs = []

        combos = list(itertools.product(keywords, locations, categories))
        total_combos = len(combos)

        with tqdm(total=total_combos, desc="Crawl", unit="combo", ncols=100) as pbar:
            for keyword, location, category in combos:
                try:
                    jobs = self.crawl_search(
                        what=keyword,
                        where=location,
                        category=category,
                        max_pages=max_pages,
                        max_days_old=max_days_old
                    )
                    all_jobs.extend(jobs)

                    if len(all_jobs) >= batch_size:
                        self.save_to_database(all_jobs)
                        all_jobs = []

                except Exception as e:
                    logger.error(
                        f"Crawl error keyword={keyword!r} location={location!r} "
                        f"category={category!r}: {e}"
                    )
                finally:
                    pbar.update(1)

        if all_jobs:
            self.save_to_database(all_jobs)

        self.print_statistics()

    def print_statistics(self):
        """Log run summary."""
        duration = (datetime.now() - self.start_time).total_seconds()
        logger.info("=" * 80)
        logger.info("Crawl statistics")
        logger.info(f"requests={self.request_count}")
        logger.info(f"jobs_found={self.jobs_found}")
        logger.info(f"jobs_saved={self.jobs_saved}")
        logger.info(f"errors={self.error_count}")
        logger.info(f"duration_sec={duration:.2f}")
        if duration > 0:
            logger.info(f"req_per_sec={self.request_count / duration:.2f}")
        logger.info("=" * 80)


def main():
    """CLI entry: configure credentials and run crawl."""
    crawler = AdzunaCrawler(
        app_id=ADZUNA_CONFIG['app_id'],
        app_key=ADZUNA_CONFIG['app_key'],
        db_config=DATABASE_CONFIG,
        delay_range=ADZUNA_CONFIG.get('delay_range', (1, 2)),
    )

    crawler.crawl(
        keywords=[
            'graduate',
            'graduate scheme',
            'entry level',
            'junior',
        ],
        locations=[""],
        categories=None,
        max_pages=10,
        max_days_old=60,
        batch_size=100,
        fetch_all_categories=True,
    )


if __name__ == "__main__":
    main()
