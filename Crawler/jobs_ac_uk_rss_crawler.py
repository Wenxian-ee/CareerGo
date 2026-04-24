"""
Jobs.ac.uk RSS Feed Crawler 
Uses official RSS Job Feeds provided by jobs.ac.uk
Correct URL format: http://www.jobs.ac.uk/jobs/{category}/?format=rss

RSS Feeds Index: http://www.jobs.ac.uk/feeds/
Terms and Conditions: http://www.jobs.ac.uk/legal/terms-and-conditions

New Features:
- Fetch job list from RSS feed
- Scrape detailed job information from individual pages
- Extract complete job information (title, employer, department, location, salary, description, requirements, etc.)
- Field normalization: unify field names and formats
- Intelligent salary extraction: extract salary information from multiple sources
- Modular design, code reusable
"""
#TODO: No filtering on requirements field yet

import re
import argparse
import signal
import sys
from dateutil import parser as dateparser
import subprocess
import time
import random
import ssl
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib3.util.ssl_ import create_urllib3_context
import feedparser
from datetime import datetime
from typing import List, Dict, Optional, Set
import psycopg2
from psycopg2.extras import execute_values
import json
import logging
from urllib.parse import urljoin, urlparse, parse_qs
import hashlib
from tqdm import tqdm
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Import custom modules
from jobs_ac_uk_detail_scraper import JobsAcUkDetailScraper
from field_normalizer import FieldNormalizer
from config import DATABASE_CONFIG

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('jobs_ac_uk_rss_crawler.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class _TLSAdapter(HTTPAdapter):
    """Use a safer TLS configuration to reduce SSL EOF errors."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)


class JobsAcUkRSSCrawler:
    """
    RSS-based crawler for jobs.ac.uk (enhanced version with field normalization)
    Uses official RSS feeds - the recommended and compliant approach
    
    Features:
    - Uses official RSS Job Feeds
    - Scrapes detailed job information from individual pages
    - Field normalization: unifies field names and formats
    - Intelligent salary extraction from multiple sources
    - Respects rate limits (2-3 seconds between feeds)
    - PostgreSQL integration
    - Comprehensive logging
    - Duplicate detection
    """
    
    # Official RSS feeds - Academic Disciplines (from http://www.jobs.ac.uk/feeds/subject-areas)
    RSS_FEEDS = {
        'agriculture_food_and_veterinary': 'http://www.jobs.ac.uk/jobs/agriculture-food-and-veterinary/?format=rss',
        'architecture_building_and_planning': 'http://www.jobs.ac.uk/jobs/architecture-building-and-planning/?format=rss',
        'biological_sciences': 'http://www.jobs.ac.uk/jobs/biological-sciences/?format=rss',
        'business_and_management_studies': 'http://www.jobs.ac.uk/jobs/business-and-management-studies/?format=rss',
        'computer_sciences': 'http://www.jobs.ac.uk/jobs/computer-sciences/?format=rss',
        'creative_arts_and_design': 'http://www.jobs.ac.uk/jobs/creative-arts-and-design/?format=rss',
        'economics': 'http://www.jobs.ac.uk/jobs/economics/?format=rss',
        'education_studies_inc_tefl': 'http://www.jobs.ac.uk/jobs/education-studies-inc-tefl/?format=rss',
        'engineering_and_technology': 'http://www.jobs.ac.uk/jobs/engineering-and-technology/?format=rss',
        'health_and_medical': 'http://www.jobs.ac.uk/jobs/health-and-medical/?format=rss',
        'historical_and_philosophical_studies': 'http://www.jobs.ac.uk/jobs/historical-and-philosophical-studies/?format=rss',
        'information_management_and_librarianship': 'http://www.jobs.ac.uk/jobs/information-management-and-librarianship/?format=rss',
        'languages_literature_and_culture': 'http://www.jobs.ac.uk/jobs/languages-literature-and-culture/?format=rss',
        'law': 'http://www.jobs.ac.uk/jobs/law/?format=rss',
        'mathematics_and_statistics': 'http://www.jobs.ac.uk/jobs/mathematics-and-statistics/?format=rss',
        'media_and_communications': 'http://www.jobs.ac.uk/jobs/media-and-communications/?format=rss',
        'physical_and_environmental_sciences': 'http://www.jobs.ac.uk/jobs/physical-and-environmental-sciences/?format=rss',
        'politics_and_government': 'http://www.jobs.ac.uk/jobs/politics-and-government/?format=rss',
        'psychology': 'http://www.jobs.ac.uk/jobs/psychology/?format=rss',
        'social_sciences_and_social_care': 'http://www.jobs.ac.uk/jobs/social-sciences-and-social-care/?format=rss',
        'sport_and_leisure': 'http://www.jobs.ac.uk/jobs/sport-and-leisure/?format=rss',
        # Professional / Managerial / Support Services
        'administrative': 'http://www.jobs.ac.uk/jobs/administrative/?format=rss',
        'estates_and_facilities_management': 'http://www.jobs.ac.uk/jobs/estates-and-facilities-management/?format=rss',
        'finance_and_procurement': 'http://www.jobs.ac.uk/jobs/finance-and-procurement/?format=rss',
        'fundraising_alumni_bids_and_grants': 'http://www.jobs.ac.uk/jobs/fundraising-alumni-bids-and-grants/?format=rss',
        'health_wellbeing_and_care': 'http://www.jobs.ac.uk/jobs/health-wellbeing-and-care/?format=rss',
        'hospitality_retail_conferences_and_events': 'http://www.jobs.ac.uk/jobs/hospitality-retail-conferences-and-events/?format=rss',
        'human_resources': 'http://www.jobs.ac.uk/jobs/human-resources/?format=rss',
        'international_activities': 'http://www.jobs.ac.uk/jobs/international-activities/?format=rss',
        'it_services': 'http://www.jobs.ac.uk/jobs/it-services/?format=rss',
        'laboratory_clinical_and_technician': 'http://www.jobs.ac.uk/jobs/laboratory-clinical-and-technician/?format=rss',
        'legal_compliance_and_policy': 'http://www.jobs.ac.uk/jobs/legal-compliance-and-policy/?format=rss',
        'library_services_data_and_information_management': 'http://www.jobs.ac.uk/jobs/library-services-data-and-information-management/?format=rss',
        'other': 'http://www.jobs.ac.uk/jobs/other/?format=rss',
        'pr_marketing_sales_and_communication': 'http://www.jobs.ac.uk/jobs/pr-marketing-sales-and-communication/?format=rss',
        'project_management_and_consulting': 'http://www.jobs.ac.uk/jobs/project-management-and-consulting/?format=rss',
        'senior_management': 'http://www.jobs.ac.uk/jobs/senior-management/?format=rss',
        'sports_and_leisure': 'http://www.jobs.ac.uk/jobs/sports-and-leisure/?format=rss',
        'student_services': 'http://www.jobs.ac.uk/jobs/student-services/?format=rss',
        'sustainability': 'http://www.jobs.ac.uk/jobs/sustainability/?format=rss',
        'web_design_and_development': 'http://www.jobs.ac.uk/jobs/web-design-and-development/?format=rss',
    }

    # Location-based RSS feeds (from http://www.jobs.ac.uk/feeds/locations)
    # China is not listed separately; Asia & Middle East feed covers China-based jobs
    LOCATION_FEEDS = {
        'london': 'http://www.jobs.ac.uk/jobs/london/?format=rss',
        'midlands_of_england': 'http://www.jobs.ac.uk/jobs/midlands-of-england/?format=rss',
        'northern_england': 'http://www.jobs.ac.uk/jobs/northern-england/?format=rss',
        'northern_ireland': 'http://www.jobs.ac.uk/jobs/northern-ireland/?format=rss',
        'republic_of_ireland': 'http://www.jobs.ac.uk/jobs/republic-of-ireland/?format=rss',
        'scotland': 'http://www.jobs.ac.uk/jobs/scotland/?format=rss',
        'south_east_england': 'http://www.jobs.ac.uk/jobs/south-east-england/?format=rss',
        'south_west_england': 'http://www.jobs.ac.uk/jobs/south-west-england/?format=rss',
        'wales': 'http://www.jobs.ac.uk/jobs/wales/?format=rss',
        # China is under Asia & Middle East
        'asia_and_middle_east': 'http://www.jobs.ac.uk/jobs/asia-and-middle-east/?format=rss',
    }
    
    def __init__(self, db_config: Dict[str, str], delay_range: tuple = (3, 6), 
                 scrape_details: bool = True, enable_normalization: bool = True):
        """
        Initialize the RSS crawler
        
        Args:
            db_config: PostgreSQL connection configuration
            delay_range: Tuple of (min_delay, max_delay) in seconds between feeds
            scrape_details: Whether to scrape detail pages (True = full information, False = RSS only)
            enable_normalization: Whether to enable field normalization (True = unified field format)
        """
        self.delay_range = delay_range
        self.scrape_details = scrape_details
        self.enable_normalization = enable_normalization
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8',
            'Accept-Language': 'en-GB,en;q=0.9',
            'Connection': 'close',
            'Cache-Control': 'no-cache',
        })

        retry_strategy = Retry(
            total=6,
            connect=6,
            read=6,
            status=6,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["HEAD", "GET", "OPTIONS"]),
            raise_on_status=False,
        )
        adapter = _TLSAdapter(max_retries=retry_strategy)
        self.session.mount('http://', adapter)
        
        # Database configuration
        self.db_config = db_config
        self.init_database()
        
        # Initialize detail page scraper
        if self.scrape_details:
            self.detail_scraper = JobsAcUkDetailScraper(delay_range=delay_range)
        
        # Initialize field normalizer
        if self.enable_normalization:
            self.field_normalizer = FieldNormalizer()
            logger.info("Field normalizer enabled")
        
        # Statistics
        self.feeds_processed = 0
        self.jobs_found = 0
        self.jobs_detailed = 0
        self.jobs_normalized = 0
        self.jobs_saved = 0
        self.feed_failures = 0
        self.all_jobs_data = []  # Store all job data for final reporting
        self.start_time = datetime.now()
    
    def init_database(self):
        """Initialize PostgreSQL database tables"""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Create enhanced jobs table with more fields
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jobs_ac_uk_jobs (
                    id SERIAL PRIMARY KEY,
                    job_id VARCHAR(255) UNIQUE,
                    job_ref VARCHAR(100),
                    title TEXT NOT NULL,
                    employer TEXT,
                    department TEXT,
                    location TEXT,
                    salary TEXT,
                    hours TEXT,
                    job_type TEXT,
                    contract_type TEXT,
                    description TEXT,
                    full_description TEXT,
                    requirements TEXT,
                    responsibilities TEXT,
                    url TEXT,
                    apply_url TEXT,
                    published_date TIMESTAMP,
                    placed_on VARCHAR(100),
                    closing_date TIMESTAMP,
                    expires VARCHAR(100),
                    category TEXT,
                    subcategory TEXT,
                    feed_source TEXT,
                    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    raw_data JSONB
                )
            """)
            
            # Create indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_ac_uk_job_id 
                ON jobs_ac_uk_jobs(job_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_ac_uk_category 
                ON jobs_ac_uk_jobs(category)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_ac_uk_published_date 
                ON jobs_ac_uk_jobs(published_date)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_ac_uk_employer 
                ON jobs_ac_uk_jobs(employer)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_ac_uk_location 
                ON jobs_ac_uk_jobs(location)
            """)
            
            conn.commit()
            cursor.close()
            conn.close()
            logger.info("Database table initialized successfully")
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
            raise
    
    def generate_job_id(self, url: str) -> str:
        """Generate unique job ID from URL"""
        return hashlib.md5(url.encode()).hexdigest()
    
    def rate_limit(self):
        """Implement polite rate limiting between feed requests"""
        delay = random.uniform(*self.delay_range)
        logger.debug(f"Rate limit: sleeping for {delay:.2f} seconds")
        time.sleep(delay)

    def fallback_feedparser_fetch(self, feed_url: str) -> Optional[feedparser.FeedParserDict]:
        """Fallback parser if requests session fetch fails."""
        try:
            self.rate_limit()
            feed = feedparser.parse(feed_url)
            if getattr(feed, 'entries', None):
                logger.info(f"Fallback feedparser succeeded ({len(feed.entries)} entries): {feed_url}")
                return feed
            logger.warning(f"Fallback feedparser returned no entries: {feed_url}")
            return None
        except Exception as e:
            logger.error(f"Fallback feedparser failed for {feed_url}: {e}")
            return None
    
    def fetch_rss_feed(self, feed_url: str):
        """Fetch RSS using curl instead of requests (more stable for TLS)."""
        try:
            self.rate_limit()

            cmd = [
                'curl',
                '-sL',
                '--compressed',
                '--retry', '5',
                '--retry-all-errors',
                '--retry-delay', '2',
                '--connect-timeout', '15',
                '--max-time', '60',
                '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                '-H', 'Accept: application/rss+xml,application/xml;q=0.9,*/*;q=0.8',
                '-H', 'Accept-Language: en-GB,en;q=0.9',
                '-H', 'Connection: close',
                feed_url
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=90
            )

            if result.returncode == 0 and result.stdout:
                import feedparser
                feed = feedparser.parse(result.stdout)
                logger.info(f"Fetched RSS via curl: {len(feed.entries)} entries")
                return feed

            logger.warning(f"curl RSS failed: {feed_url}")
            return None

        except Exception as e:
            logger.error(f"RSS fetch error: {feed_url} - {e}")
            return None
    
    def parse_rss_entry(self, entry, feed_source: str) -> Optional[Dict]:
        """
        Parse individual RSS entry and optionally fetch detailed information
        
        Args:
            entry: RSS feed entry
            feed_source: Name of the feed source
            
        Returns:
            Dictionary containing job data
        """
        try:
            job_data = {
                'title': None,
                'employer': None,
                'department': None,
                'location': None,
                'salary': None,
                'hours': None,
                'job_type': None,
                'contract_type': None,
                'description': None,
                'full_description': None,
                'requirements': None,
                'responsibilities': None,
                'url': None,
                'apply_url': None,
                'published_date': None,
                'placed_on': None,
                'closing_date': None,
                'expires': None,
                'job_ref': None,
                'category': feed_source,
                'feed_source': feed_source,
                'raw_data': {}
            }
            
            # Extract title
            job_data['title'] = entry.get('title', '').strip()
            
            # Extract URL
            job_data['url'] = entry.get('link', '').strip()
            
            # Extract description/summary
            if 'summary' in entry:
                job_data['description'] = entry.get('summary', '').strip()
            elif 'description' in entry:
                job_data['description'] = entry.get('description', '').strip()
            
            # Extract published date
            if 'published_parsed' in entry and entry.published_parsed:
                try:
                    job_data['published_date'] = datetime(*entry.published_parsed[:6])
                except:
                    pass
            elif 'published' in entry:
                job_data['raw_data']['published_string'] = entry.get('published')
            
            # Extract categories/tags
            if 'tags' in entry:
                categories = [tag.get('term', '') for tag in entry.tags]
                if categories:
                    job_data['subcategory'] = ', '.join(categories)
            
            # Generate unique job ID
            if job_data['url']:
                job_data['job_id'] = self.generate_job_id(job_data['url'])
            
            # Store RSS entry in raw_data
            job_data['raw_data']['rss_entry'] = {
                'title': entry.get('title'),
                'link': entry.get('link'),
                'published': entry.get('published'),
                'summary': entry.get('summary', '')[:500],
            }
            
            # Scrape detailed information from job page if enabled
            if self.scrape_details and job_data['url']:
                logger.info(f"Fetching details: {job_data['title']}")
                detail_data = self.detail_scraper.scrape_job_detail(job_data['url'])
                
                if detail_data:
                    _STASH_KEYS = {'sections', 'meta', 'lists', '_var_job', '_jsonld'}
                    _OVERWRITE_KEYS = {
                        'full_description', 'requirements', 'responsibilities',
                        'employer', 'department', 'salary', 'location',
                        'hours', 'contract_type', 'job_type', 'apply_url',
                        'closing_date', 'placed_on', 'job_ref', 'subcategory',
                    }
                    for key, value in detail_data.items():
                        if key in _STASH_KEYS:
                            job_data['raw_data'][key] = value
                        elif value and (not job_data.get(key) or key in _OVERWRITE_KEYS):
                            job_data[key] = value
                    
                    self.jobs_detailed += 1
            
            # Apply field normalization
            if self.enable_normalization and job_data:
                logger.info(f"Normalizing fields: {job_data['title']}")
                
                # Prepare complete data for normalization (including sections, etc.)
                data_for_normalization = job_data.copy()
                if 'sections' in job_data.get('raw_data', {}):
                    data_for_normalization['sections'] = job_data['raw_data']['sections']
                
                # Execute normalization
                normalized_data = self.field_normalizer.normalize_job_data(data_for_normalization)
                
                # Update job_data while preserving original raw_data and other metadata
                for key, value in normalized_data.items():
                    if key not in ['_raw_data', 'raw_data'] and value is not None:
                        job_data[key] = value
                
                self.jobs_normalized += 1
                
                # Log salary extraction result
                if job_data.get('salary'):
                    logger.info(f"✓ Salary info: {job_data['salary']}")
                else:
                    logger.debug("✗ Salary info not found")
            
            return job_data if job_data['title'] and job_data['url'] else None
            
        except Exception as e:
            logger.error(f"Error parsing RSS entry: {e}")
            return None

    def parse_to_datetime(self, value):
        """
        Parse various date formats to Python datetime for PostgreSQL TIMESTAMP.
        Accepts datetime / date-string like '9th March 2026', '10th January 2026', ISO, etc.
        Returns datetime or None.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            return value

        # Sometimes value could be date object; keep safe:
        try:
            import datetime as _dt
            if isinstance(value, _dt.date) and not isinstance(value, _dt.datetime):
                return datetime(value.year, value.month, value.day)
        except Exception:
            pass

        if isinstance(value, str):
            s = value.strip()
            if not s:
                return None

            # remove ordinal suffix: 9th -> 9, 1st -> 1, 2nd -> 2, 3rd -> 3
            s = re.sub(r'(\d+)(st|nd|rd|th)\b', r'\1', s, flags=re.IGNORECASE)

            # normalize common separators
            s = s.replace("Sept", "Sep")

            try:
                # dateutil can parse lots of human strings
                dt = dateparser.parse(s, fuzzy=True, dayfirst=True)
                return dt
            except Exception:
                return None

        # Unknown type -> give up
        return None

    def save_to_database(self, jobs_data: List[Dict]):
        """
        Save job data to PostgreSQL database
        
        Args:
            jobs_data: List of job dictionaries
        """
        if not jobs_data:
            logger.warning("No job data to save")
            return
        
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Prepare data for insertion
            insert_query = """
                INSERT INTO jobs_ac_uk_jobs 
                (job_id, job_ref, title, employer, department, location, salary, hours,
                 job_type, contract_type, description, full_description, requirements, 
                 responsibilities, url, apply_url, published_date, placed_on, closing_date, 
                 expires, category, subcategory, feed_source, raw_data)
                VALUES %s
                ON CONFLICT (job_id) DO UPDATE SET
                    job_ref = EXCLUDED.job_ref,
                    title = EXCLUDED.title,
                    employer = EXCLUDED.employer,
                    department = EXCLUDED.department,
                    location = EXCLUDED.location,
                    salary = EXCLUDED.salary,
                    hours = EXCLUDED.hours,
                    job_type = EXCLUDED.job_type,
                    contract_type = EXCLUDED.contract_type,
                    description = EXCLUDED.description,
                    full_description = EXCLUDED.full_description,
                    requirements = EXCLUDED.requirements,
                    responsibilities = EXCLUDED.responsibilities,
                    url = EXCLUDED.url,
                    apply_url = EXCLUDED.apply_url,
                    published_date = EXCLUDED.published_date,
                    placed_on = EXCLUDED.placed_on,
                    closing_date = EXCLUDED.closing_date,
                    expires = EXCLUDED.expires,
                    category = EXCLUDED.category,
                    subcategory = EXCLUDED.subcategory,
                    feed_source = EXCLUDED.feed_source,
                    raw_data = EXCLUDED.raw_data,
                    scraped_at = CURRENT_TIMESTAMP
            """
            
            values = [
                (
                    job.get('job_id'),
                    job.get('job_ref'),
                    job.get('title'),
                    job.get('employer'),
                    job.get('department'),
                    job.get('location'),
                    job.get('salary'),
                    job.get('hours'),
                    job.get('job_type'),
                    job.get('contract_type'),
                    job.get('description'),
                    job.get('full_description'),
                    job.get('requirements'),
                    job.get('responsibilities'),
                    job.get('url'),
                    job.get('apply_url'),
                    self.parse_to_datetime(job.get('published_date')),
                    job.get('placed_on'), 
                    self.parse_to_datetime(job.get('closing_date')),
                    job.get('expires'),
                    job.get('category'),
                    job.get('subcategory'),
                    job.get('feed_source'),
                    json.dumps(job.get('raw_data', {}))
                )
                for job in jobs_data if job.get('job_id')
            ]
            
            if values:
                execute_values(cursor, insert_query, values)
                conn.commit()
                self.jobs_saved += len(values)
                logger.info(f"Successfully saved {len(values)} jobs to database")
            
            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Database save error: {e}")
            raise
    
    def get_existing_job_ids(self) -> Set[str]:
        """Return all job_id values already in the database."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("SELECT job_id FROM jobs_ac_uk_jobs")
            ids = {row[0] for row in cursor.fetchall()}
            cursor.close()
            conn.close()
            return ids
        except Exception as e:
            logger.error(f"Error fetching existing job IDs: {e}")
            return set()

    def crawl_feed(self, feed_name: str, feed_url: str, max_jobs: int = None,
                   known_ids: Set[str] = None) -> List[Dict]:
        """
        Crawl a single RSS feed.

        Args:
            feed_name: Name/identifier of the feed
            feed_url: URL of the RSS feed
            max_jobs: Maximum number of jobs to process (None for all)
            known_ids: Set of job_id already in DB; if provided, entries whose
                       URL hashes to a known id are skipped (saves detail-scrape time).

        Returns:
            List of job dictionaries
        """
        logger.info(f"Processing feed: {feed_name}")
        logger.info(f"Feed URL: {feed_url}")

        feed = self.fetch_rss_feed(feed_url)
        if not feed:
            self.feed_failures += 1
            logger.warning(f"Skipping feed due to fetch failure: {feed_name}")
            return []

        jobs_data = []
        skipped = 0
        entries_to_process = feed.entries[:max_jobs] if max_jobs else feed.entries

        for entry in tqdm(entries_to_process, desc=f"  Jobs [{feed_name}]", unit="job", leave=False):
            url = entry.get('link', '').strip()
            if known_ids and url:
                jid = self.generate_job_id(url)
                if jid in known_ids:
                    skipped += 1
                    continue

            job_data = self.parse_rss_entry(entry, feed_source=feed_name)
            if job_data:
                jobs_data.append(job_data)
                self.jobs_found += 1

        self.feeds_processed += 1
        logger.info(f"Feed {feed_name}: {len(jobs_data)} new, {skipped} skipped (already in DB)")

        return jobs_data
    
    def crawl_feeds(self, feed_names: List[str] = None, batch_size: int = 10,
                   max_jobs_per_feed: int = None, extra_feeds: Dict[str, str] = None,
                   use_location_feeds: bool = False, skip_existing: bool = False):
        """
        Crawl multiple RSS feeds.

        Args:
            feed_names: List of feed names to crawl. If None + use_location_feeds=False, 
                       crawls all subject-area feeds.
            batch_size: Number of jobs to save in each batch
            max_jobs_per_feed: Maximum jobs to process per feed (None for all)
            extra_feeds: Additional {name: url} feeds to crawl
            use_location_feeds: If True, use LOCATION_FEEDS instead of RSS_FEEDS
            skip_existing: If True, skip entries whose job_id already exists in DB
                           (avoids re-scraping detail pages on incremental runs)
        """
        logger.info("=" * 80)
        logger.info("Starting Jobs.ac.uk RSS Feed Crawler")
        logger.info("=" * 80)

        source = self.LOCATION_FEEDS if use_location_feeds else self.RSS_FEEDS
        if feed_names is None:
            feeds_to_crawl = dict(source)
        else:
            feeds_to_crawl = {name: source[name] for name in feed_names if name in source}
        if extra_feeds:
            feeds_to_crawl.update(extra_feeds)

        known_ids: Set[str] = set()
        if skip_existing:
            known_ids = self.get_existing_job_ids()
            logger.info(f"Incremental mode: {len(known_ids)} jobs already in DB will be skipped")

        logger.info(f"Will process {len(feeds_to_crawl)} RSS feeds")
        if max_jobs_per_feed:
            logger.info(f"Maximum jobs per feed: {max_jobs_per_feed}")
        if self.scrape_details:
            logger.info("Detail page scraping: enabled")
        else:
            logger.info("Detail page scraping: disabled (RSS only)")
        if self.enable_normalization:
            logger.info("Field normalization: enabled")
        else:
            logger.info("Field normalization: disabled")
        
        all_jobs = []
        feeds_list = list(feeds_to_crawl.items())

        for feed_name, feed_url in tqdm(feeds_list, desc="Feeds", unit="feed"):
            try:
                jobs = self.crawl_feed(
                    feed_name, feed_url,
                    max_jobs=max_jobs_per_feed,
                    known_ids=known_ids if skip_existing else None,
                )
                all_jobs.extend(jobs)
                
                # Remember new ids so cross-feed duplicates are also skipped
                if skip_existing:
                    for j in jobs:
                        jid = j.get('job_id')
                        if jid:
                            known_ids.add(jid)
                
                self.all_jobs_data.extend(jobs)
                
                if len(all_jobs) >= batch_size:
                    self.save_to_database(all_jobs)
                    all_jobs = []
                
            except Exception as e:
                logger.error(f"Error processing feed {feed_name}: {e}")
                self.feed_failures += 1
                continue
        
        if all_jobs:
            self.save_to_database(all_jobs)
        
        self.print_statistics()
        
        if self.enable_normalization and self.all_jobs_data:
            self.print_field_coverage_report()

    # ── Scheduled / incremental crawling ──

    def _reset_counters(self):
        """Reset per-round statistics (called at the start of each scheduled round)."""
        self.feeds_processed = 0
        self.jobs_found = 0
        self.jobs_detailed = 0
        self.jobs_normalized = 0
        self.jobs_saved = 0
        self.feed_failures = 0
        self.all_jobs_data = []
        self.start_time = datetime.now()

    def run_scheduled(self, interval_hours: float = 4.0,
                      use_location_feeds: bool = True,
                      use_subject_feeds: bool = False,
                      feed_names: List[str] = None,
                      extra_feeds: Dict[str, str] = None,
                      batch_size: int = 10):
        """
        Run the crawler in an infinite loop, polling all feeds every *interval_hours*.

        Because each RSS feed only exposes the latest ~20 items, frequent polling
        is the only way to build a comprehensive dataset over time.  Existing
        entries are skipped (by job_id) so detail pages are not re-scraped.

        Press Ctrl-C to stop gracefully.
        """
        stop = {'flag': False}

        def _handle_signal(sig, frame):
            logger.info("Received stop signal, finishing current round ...")
            stop['flag'] = True

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        round_num = 0
        interval_sec = interval_hours * 3600

        # Combine both location and subject feeds if requested
        combined_source: Dict[str, str] = {}
        if use_location_feeds:
            combined_source.update(self.LOCATION_FEEDS)
        if use_subject_feeds:
            combined_source.update(self.RSS_FEEDS)

        while not stop['flag']:
            round_num += 1
            self._reset_counters()
            logger.info("=" * 80)
            logger.info(f"Scheduled round #{round_num} starting at {datetime.now():%Y-%m-%d %H:%M:%S}")
            logger.info("=" * 80)

            try:
                feeds = dict(combined_source)
                if feed_names:
                    feeds = {k: v for k, v in feeds.items() if k in feed_names}
                if extra_feeds:
                    feeds.update(extra_feeds)

                known_ids = self.get_existing_job_ids()
                logger.info(f"DB contains {len(known_ids)} jobs; only new entries will be scraped")

                all_jobs: List[Dict] = []
                for feed_name, feed_url in tqdm(list(feeds.items()), desc="Feeds", unit="feed"):
                    if stop['flag']:
                        break
                    try:
                        jobs = self.crawl_feed(
                            feed_name, feed_url, known_ids=known_ids
                        )
                        all_jobs.extend(jobs)
                        for j in jobs:
                            jid = j.get('job_id')
                            if jid:
                                known_ids.add(jid)
                        self.all_jobs_data.extend(jobs)

                        if len(all_jobs) >= batch_size:
                            self.save_to_database(all_jobs)
                            all_jobs = []
                    except Exception as e:
                        logger.error(f"Error processing feed {feed_name}: {e}")
                        self.feed_failures += 1

                if all_jobs:
                    self.save_to_database(all_jobs)

                self.print_statistics()

            except Exception as e:
                logger.error(f"Round #{round_num} failed: {e}")

            if stop['flag']:
                break

            logger.info(f"Round #{round_num} done. Sleeping {interval_hours}h until next round ...")
            sleep_end = time.time() + interval_sec
            while time.time() < sleep_end and not stop['flag']:
                time.sleep(min(30, sleep_end - time.time()))

        logger.info("Scheduled crawler stopped.")
    
    def crawl_custom_feed(self, feed_url: str, feed_name: str = "custom", 
                         max_jobs: int = None):
        """
        Crawl a custom RSS feed URL
        
        Args:
            feed_url: Custom RSS feed URL (format: http://www.jobs.ac.uk/jobs/{category}/?format=rss)
            feed_name: Name for this feed
            max_jobs: Maximum jobs to process
        """
        logger.info(f"Crawling custom feed: {feed_name}")
        jobs = self.crawl_feed(feed_name, feed_url, max_jobs=max_jobs)
        if jobs:
            self.all_jobs_data.extend(jobs)
            self.save_to_database(jobs)
        self.print_statistics()
        
        # Print field coverage report if normalization is enabled
        if self.enable_normalization and self.all_jobs_data:
            self.print_field_coverage_report()
    
    def print_statistics(self):
        """Print crawling statistics"""
        duration = (datetime.now() - self.start_time).total_seconds()
        logger.info("=" * 80)
        logger.info("Crawling statistics")
        logger.info(f"Feeds processed successfully: {self.feeds_processed}")
        logger.info(f"Feed failures: {self.feed_failures}")
        logger.info(f"Jobs found: {self.jobs_found}")
        if self.scrape_details:
            logger.info(f"Detail pages scraped successfully: {self.jobs_detailed}")
        if self.enable_normalization:
            logger.info(f"Field normalization successful: {self.jobs_normalized}")
        logger.info(f"Jobs saved to database: {self.jobs_saved}")
        logger.info(f"Elapsed time: {duration:.2f} seconds")
        if duration > 0:
            logger.info(f"Average rate: {self.jobs_found / duration:.2f} jobs/second")
        logger.info("=" * 80)
    
    def print_field_coverage_report(self):
        """Print field coverage report using FieldNormalizer"""
        if not self.enable_normalization or not self.all_jobs_data:
            return
        
        logger.info("\n" + "=" * 80)
        logger.info("Generating field coverage report...")
        logger.info("=" * 80)
        
        try:
            self.field_normalizer.print_coverage_report(self.all_jobs_data)
        except Exception as e:
            logger.error(f"Error generating field coverage report: {e}")
    
    @classmethod
    def list_available_feeds(cls):
        """Print all available RSS feeds"""
        print("\n" + "=" * 80)
        print("Subject Area Feeds:")
        for k, v in cls.RSS_FEEDS.items():
            print(f"  {k}: {v}")
        print(f"\nLocation Feeds:")
        for k, v in cls.LOCATION_FEEDS.items():
            print(f"  {k}: {v}")
        print(f"\nTotal: {len(cls.RSS_FEEDS)} subject + {len(cls.LOCATION_FEEDS)} location feeds")
        print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Jobs.ac.uk RSS Feed Crawler (incremental + scheduled)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        '--mode', choices=['once', 'scheduled'], default='once',
        help='once  = single crawl run (default)\nscheduled = infinite loop, polls every --interval hours',
    )
    parser.add_argument(
        '--interval', type=float, default=4.0,
        help='Hours between scheduled rounds (default: 4)',
    )
    parser.add_argument(
        '--feeds', choices=['location', 'subject', 'both'], default='location',
        help='Which feed set to use (default: both)',
    )
    parser.add_argument(
        '--skip-existing', action='store_true', default=True,
        help='Skip entries already in DB (saves detail-scrape time, default: True)',
    )
    parser.add_argument(
        '--no-skip-existing', dest='skip_existing', action='store_false',
        help='Re-scrape all entries even if already in DB',
    )
    parser.add_argument('--list-feeds', action='store_true', help='Print available feeds and exit')
    parser.add_argument('--delay-min', type=float, default=3.0)
    parser.add_argument('--delay-max', type=float, default=6.0)
    args = parser.parse_args()

    if args.list_feeds:
        JobsAcUkRSSCrawler.list_available_feeds()
        return

    crawler = JobsAcUkRSSCrawler(
        db_config=DATABASE_CONFIG,
        delay_range=(args.delay_min, args.delay_max),
        scrape_details=True,
        enable_normalization=True,
    )

    use_loc = args.feeds in ('location', 'both')
    use_sub = args.feeds in ('subject', 'both')

    if args.mode == 'scheduled':
        logger.info(f"Starting SCHEDULED mode: interval={args.interval}h, feeds={args.feeds}")
        crawler.run_scheduled(
            interval_hours=args.interval,
            use_location_feeds=use_loc,
            use_subject_feeds=use_sub,
        )
    else:
        JobsAcUkRSSCrawler.list_available_feeds()
        if use_loc and use_sub:
            combined = {}
            combined.update(crawler.LOCATION_FEEDS)
            combined.update(crawler.RSS_FEEDS)
            # Pass everything via extra_feeds; empty feed_names avoids
            # loading the default source set a second time.
            crawler.crawl_feeds(
                extra_feeds=combined,
                feed_names=[],
                use_location_feeds=False,
                skip_existing=args.skip_existing,
                batch_size=10,
            )
        else:
            crawler.crawl_feeds(
                feed_names=None,
                use_location_feeds=use_loc,
                skip_existing=args.skip_existing,
                batch_size=10,
            )


if __name__ == "__main__":
    main()