"""
Database utilities for CareerGo crawlers
Provides helper functions for database operations and queries
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from typing import Any, List, Dict, Optional

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Helper class for database operations"""

    def __init__(self, db_config: Dict[str, Any]):
        """
        Initialize database manager
        
        Args:
            db_config: PostgreSQL connection configuration
        """
        self.db_config = db_config
    
    def get_connection(self):
        """Get database connection"""
        return psycopg2.connect(**self.db_config)
    
    def test_connection(self) -> bool:
        """Test database connection"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False
    
    def get_job_count(self, table_name: str) -> int:
        """
        Get total number of jobs in a table
        
        Args:
            table_name: Name of the table (jobs_ac_uk or indeed_jobs)
            
        Returns:
            Number of jobs
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            return count
        except Exception as e:
            logger.error(f"Error getting job count: {e}")
            return 0
    
    def get_recent_jobs(self, table_name: str, days: int = 7, limit: int = 100) -> List[Dict]:
        """
        Get recently scraped jobs
        
        Args:
            table_name: Name of the table
            days: Number of days to look back
            limit: Maximum number of results
            
        Returns:
            List of job dictionaries
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            query = f"""
                SELECT * FROM {table_name}
                WHERE scraped_at > NOW() - INTERVAL '{days} days'
                ORDER BY scraped_at DESC
                LIMIT {limit}
            """
            
            cursor.execute(query)
            jobs = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return [dict(job) for job in jobs]
        except Exception as e:
            logger.error(f"Error getting recent jobs: {e}")
            return []
    
    def search_jobs(self, table_name: str, keyword: str, limit: int = 100) -> List[Dict]:
        """
        Search jobs by keyword in title or description
        
        Args:
            table_name: Name of the table
            keyword: Search keyword
            limit: Maximum number of results
            
        Returns:
            List of job dictionaries
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            query = f"""
                SELECT * FROM {table_name}
                WHERE title ILIKE %s OR description ILIKE %s
                ORDER BY scraped_at DESC
                LIMIT {limit}
            """
            
            cursor.execute(query, (f'%{keyword}%', f'%{keyword}%'))
            jobs = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return [dict(job) for job in jobs]
        except Exception as e:
            logger.error(f"Error searching jobs: {e}")
            return []
    
    def get_jobs_by_location(self, table_name: str, location: str, limit: int = 100) -> List[Dict]:
        """
        Get jobs by location
        
        Args:
            table_name: Name of the table
            location: Location to filter by
            limit: Maximum number of results
            
        Returns:
            List of job dictionaries
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            query = f"""
                SELECT * FROM {table_name}
                WHERE location ILIKE %s
                ORDER BY scraped_at DESC
                LIMIT {limit}
            """
            
            cursor.execute(query, (f'%{location}%',))
            jobs = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return [dict(job) for job in jobs]
        except Exception as e:
            logger.error(f"Error getting jobs by location: {e}")
            return []
    
    def get_statistics(self, table_name: str) -> Dict:
        """
        Get statistics about scraped jobs
        
        Args:
            table_name: Name of the table
            
        Returns:
            Dictionary with statistics
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            stats = {}
            
            # Total jobs
            cursor.execute(f"SELECT COUNT(*) as total FROM {table_name}")
            stats['total_jobs'] = cursor.fetchone()['total']
            
            # Jobs by location (top 10)
            cursor.execute(f"""
                SELECT location, COUNT(*) as count
                FROM {table_name}
                WHERE location IS NOT NULL
                GROUP BY location
                ORDER BY count DESC
                LIMIT 10
            """)
            stats['top_locations'] = [dict(row) for row in cursor.fetchall()]
            
            # Jobs scraped in last 24 hours
            cursor.execute(f"""
                SELECT COUNT(*) as count
                FROM {table_name}
                WHERE scraped_at > NOW() - INTERVAL '24 hours'
            """)
            stats['jobs_last_24h'] = cursor.fetchone()['count']
            
            # Jobs scraped in last 7 days
            cursor.execute(f"""
                SELECT COUNT(*) as count
                FROM {table_name}
                WHERE scraped_at > NOW() - INTERVAL '7 days'
            """)
            stats['jobs_last_7d'] = cursor.fetchone()['count']
            
            # Most recent scrape
            cursor.execute(f"""
                SELECT MAX(scraped_at) as last_scrape
                FROM {table_name}
            """)
            result = cursor.fetchone()
            stats['last_scrape'] = result['last_scrape'] if result else None
            
            cursor.close()
            conn.close()
            
            return stats
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {}
    
    def delete_old_jobs(self, table_name: str, days: int = 30) -> int:
        """
        Delete jobs older than specified days
        
        Args:
            table_name: Name of the table
            days: Delete jobs older than this many days
            
        Returns:
            Number of deleted jobs
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            query = f"""
                DELETE FROM {table_name}
                WHERE scraped_at < NOW() - INTERVAL '{days} days'
            """
            
            cursor.execute(query)
            deleted_count = cursor.rowcount
            conn.commit()
            
            cursor.close()
            conn.close()
            
            logger.info(f"Deleted {deleted_count} old jobs from {table_name}")
            return deleted_count
        except Exception as e:
            logger.error(f"Error deleting old jobs: {e}")
            return 0
    
    def export_to_csv(self, table_name: str, output_file: str, limit: Optional[int] = None):
        """
        Export jobs to CSV file
        
        Args:
            table_name: Name of the table
            output_file: Path to output CSV file
            limit: Optional limit on number of rows
        """
        try:
            import csv
            
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            query = f"SELECT * FROM {table_name} ORDER BY scraped_at DESC"
            if limit:
                query += f" LIMIT {limit}"
            
            cursor.execute(query)
            jobs = cursor.fetchall()
            
            if jobs:
                with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=jobs[0].keys())
                    writer.writeheader()
                    for job in jobs:
                        writer.writerow(dict(job))
                
                logger.info(f"Exported {len(jobs)} jobs to {output_file}")
            
            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Error exporting to CSV: {e}")


def print_statistics(db_config: Dict[str, Any]):
    """
    Print statistics for both crawler source tables.

    Args:
        db_config: Database configuration
    """
    db_manager = DatabaseManager(db_config)

    print("\n" + "=" * 80)
    print("CareerGo Database Statistics")
    print("=" * 80)

    for table_name in ['jobs_ac_uk_jobs', 'adzuna_jobs']:
        print(f"\n{table_name.upper()}")
        print("-" * 80)
        
        stats = db_manager.get_statistics(table_name)
        
        if stats:
            print(f"Total jobs: {stats.get('total_jobs', 0)}")
            print(f"Jobs in last 24 hours: {stats.get('jobs_last_24h', 0)}")
            print(f"Jobs in last 7 days: {stats.get('jobs_last_7d', 0)}")
            print(f"Last scrape: {stats.get('last_scrape', 'N/A')}")
            
            print("\nTop 10 Locations:")
            for loc in stats.get('top_locations', []):
                print(f"  - {loc['location']}: {loc['count']} jobs")
        else:
            print("No data available")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    from config import DATABASE_CONFIG  # type: ignore[attr-defined]

    print_statistics(DATABASE_CONFIG)

