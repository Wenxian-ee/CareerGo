"""
Jobs.ac.uk 
Scrape jobs.ac.uk job detail pages, extract complete job information
"""

import time
import random
import subprocess
from typing import Dict, Optional
import logging
from html_parser_utils import parse_jobs_ac_uk_page

logger = logging.getLogger(__name__)


class JobsAcUkDetailScraper:
    """Jobs.ac.uk job detail page scraper (uses curl for SSL compatibility)."""

    def __init__(self, delay_range: tuple = (2, 4), curl_timeout: int = 30):
        self.delay_range = delay_range
        self.curl_timeout = curl_timeout
        self.pages_scraped = 0
        self.pages_failed = 0

    def rate_limit(self):
        delay = random.uniform(*self.delay_range)
        time.sleep(delay)

    def _curl_get(self, url: str, max_retries: int = 3) -> Optional[str]:
        for attempt in range(max_retries):
            try:
                result = subprocess.run(
                    ['curl', '-sL', '--insecure',
                     '--retry', '5', '--retry-all-errors', '--retry-delay', '2',
                     '--max-time', str(self.curl_timeout),
                     '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                     '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                     url],
                    capture_output=True, text=True, timeout=self.curl_timeout + 60
                )
                if result.returncode == 0 and result.stdout:
                    return result.stdout
                logger.warning(f"curl attempt {attempt+1}/{max_retries} failed (code={result.returncode}): {url}")
            except subprocess.TimeoutExpired:
                logger.warning(f"curl timeout {attempt+1}/{max_retries}: {url}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
        return None

    def scrape_job_detail(self, job_url: str, max_retries: int = 3) -> Optional[Dict]:
        try:
            self.rate_limit()
            logger.info(f"Scraping: {job_url}")
            html = self._curl_get(job_url, max_retries=max_retries)
            if not html:
                self.pages_failed += 1
                return None

            job_data = parse_jobs_ac_uk_page(html)
            if job_data:
                job_data['url'] = job_url
                self.pages_scraped += 1
                logger.info(f"OK: {job_data.get('title', 'Unknown')}")
                return job_data
            else:
                logger.warning(f"Parse failed: {job_url}")
                self.pages_failed += 1
                return None
        except Exception as e:
            logger.error(f"Error: {job_url} - {e}")
            self.pages_failed += 1
            return None
    
    def scrape_multiple_jobs(self, job_urls: list) -> list:
        """
        Scrape multiple job detail pages
        
        Args:
            job_urls: Job URL list
            
        Returns:
            Job data list
        """
        jobs_data = []
        
        for i, url in enumerate(job_urls, 1):
            logger.info(f"Processing job {i}/{len(job_urls)}")
            job_data = self.scrape_job_detail(url)
            if job_data:
                jobs_data.append(job_data)
        
                logger.info(f"Batch scraping completed: successfully scraped {len(jobs_data)}/{len(job_urls)}")
        return jobs_data
    
    def get_statistics(self) -> Dict:
        """
        Get scraping statistics
        
        Returns:
            Dictionary with statistics
        """
        return {
            'pages_scraped': self.pages_scraped,
            'pages_failed': self.pages_failed,
            'success_rate': (self.pages_scraped / (self.pages_scraped + self.pages_failed) * 100) 
                           if (self.pages_scraped + self.pages_failed) > 0 else 0
        }


def scrape_job_detail(job_url: str, delay_range: tuple = (2, 4)) -> Optional[Dict]:
    scraper = JobsAcUkDetailScraper(delay_range=delay_range)
    return scraper.scrape_job_detail(job_url)

