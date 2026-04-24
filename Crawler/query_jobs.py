"""
Database Query and Statistics Tool
"""

import os
import sys

_CRAWLER_DIR = os.path.dirname(os.path.abspath(__file__))
if _CRAWLER_DIR not in sys.path:
    sys.path.insert(0, _CRAWLER_DIR)

from config import MERGED_JOBS_TABLE, DATABASE_CONFIG

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import json


class JobsDatabase:
    """Job database query tool"""
    
    def __init__(self, db_config):
        self.db_config = db_config
    
    def get_connection(self):
        """Get database connection"""
        return psycopg2.connect(
            host=self.db_config.get("host"),
            port=self.db_config.get("port"),
            database=self.db_config.get("database"),
            user=self.db_config.get("user"),
            password=self.db_config.get("password"),
        )
    
    def test_connection(self):
        """Test database connection"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT version()")
            version_row = cursor.fetchone()
            version = str(version_row[0]) if version_row else "Unknown"
            cursor.close()
            conn.close()
            print("✓ Database connection successful")
            print(f"  PostgreSQL version: {version.split(',')[0]}")
            return True
        except Exception as e:
            print(f"✗ Database connection failed: {e}")
            return False
    
    def get_table_stats(self):
        """Get statistics of all tables"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            tables = ['adzuna_jobs', 'jobs_ac_uk_jobs', MERGED_JOBS_TABLE]
            
            print("\n" + "=" * 80)
            print("Database Table Statistics")
            print("=" * 80)
            
            for table in tables:
                try:
                    # Check if table exists
                    cursor.execute(f"""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_name = '{table}'
                        )
                    """)
                    exists_row = cursor.fetchone()
                    exists = bool(exists_row[0]) if exists_row else False
                    
                    if not exists:
                        print(f"\n{table}: table does not exist")
                        continue
                    
                    # Get total count
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    total_row = cursor.fetchone()
                    total = int(total_row[0]) if total_row else 0
                    
                    print(f"\n{table}:")
                    print(f"  Total records: {total}")
                    
                    if total > 0:
                        # Latest record time
                        cursor.execute(f"""
                            SELECT MAX(scraped_at) FROM {table}
                            WHERE scraped_at IS NOT NULL
                        """)
                        result = cursor.fetchone()
                        if result and result[0]:
                            print(f"  Latest record: {result[0]}")
                        
                        # Last 24 hours
                        cursor.execute(f"""
                            SELECT COUNT(*) FROM {table}
                            WHERE scraped_at > NOW() - INTERVAL '24 hours'
                        """)
                        recent_row = cursor.fetchone()
                        recent = int(recent_row[0]) if recent_row else 0
                        print(f"  Last 24 hours: {recent}")
                        
                        # Records with salary info
                        cursor.execute(f"""
                            SELECT COUNT(*) FROM {table}
                            WHERE salary IS NOT NULL AND salary != ''
                        """)
                        with_salary_row = cursor.fetchone()
                        with_salary = int(with_salary_row[0]) if with_salary_row else 0
                        percentage = (with_salary / total * 100) if total > 0 else 0
                        print(f"  With salary info: {with_salary} ({percentage:.1f}%)")
                
                except Exception as e:
                    print(f"\n{table}: query failed - {e}")
            
            cursor.close()
            conn.close()
            print("\n" + "=" * 80)
            
        except Exception as e:
            print(f"Failed to get statistics: {e}")
    
    def search_jobs(self, keyword, table=None, limit=10):
        """Search jobs"""
        if table is None:
            table = MERGED_JOBS_TABLE
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            query = f"""
                SELECT title, company, employer, location, salary, url
                FROM {table}
                WHERE title ILIKE %s OR description ILIKE %s
                ORDER BY 
                    CASE 
                        WHEN '{table}' = '{MERGED_JOBS_TABLE}' THEN merged_at
                        ELSE scraped_at
                    END DESC
                LIMIT %s
            """
            
            cursor.execute(query, (f'%{keyword}%', f'%{keyword}%', limit))
            jobs = cursor.fetchall()
            
            print(f"\nSearch results: '{keyword}' (total {len(jobs)} records)")
            print("=" * 80)
            
            for i, job in enumerate(jobs, 1):
                company = job.get('company') or job.get('employer') or 'N/A'
                print(f"\n{i}. {job['title']}")
                print(f"   Company: {company}")
                print(f"   Location: {job.get('location') or 'N/A'}")
                print(f"   Salary: {job.get('salary') or 'N/A'}")
                print(f"   Link: {job.get('url') or 'N/A'}")
            
            cursor.close()
            conn.close()
            
        except Exception as e:
            print(f"Search failed: {e}")
    
    def get_top_locations(self, table=None, limit=10):
        """Get most common locations"""
        if table is None:
            table = MERGED_JOBS_TABLE
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute(f"""
                SELECT location, COUNT(*) as count
                FROM {table}
                WHERE location IS NOT NULL AND location != ''
                GROUP BY location
                ORDER BY count DESC
                LIMIT %s
            """, (limit,))
            
            results = cursor.fetchall()
            
            print(f"\nMost common job locations (Top {limit}):")
            print("=" * 80)
            
            for i, (location, count) in enumerate(results, 1):
                max_count = results[0][1] if results and results[0][1] else 1
                bar_length = int(count / max_count * 50)
                bar = '█' * bar_length
                print(f"{i:2d}. {location:30s} {bar} {count}")
            
            cursor.close()
            conn.close()
            
        except Exception as e:
            print(f"Failed to get location statistics: {e}")
    
    def get_top_companies(self, table=None, limit=10):
        """Get most common companies"""
        if table is None:
            table = MERGED_JOBS_TABLE
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Merge company and employer fields
            cursor.execute(f"""
                SELECT 
                    COALESCE(company, employer) as company_name,
                    COUNT(*) as count
                FROM {table}
                WHERE COALESCE(company, employer) IS NOT NULL 
                    AND COALESCE(company, employer) != ''
                GROUP BY company_name
                ORDER BY count DESC
                LIMIT %s
            """, (limit,))
            
            results = cursor.fetchall()
            
            print(f"\nMost common employers (Top {limit}):")
            print("=" * 80)
            
            for i, (company, count) in enumerate(results, 1):
                max_count = results[0][1] if results and results[0][1] else 1
                bar_length = int(count / max_count * 50)
                bar = '█' * bar_length
                print(f"{i:2d}. {company:30s} {bar} {count}")
            
            cursor.close()
            conn.close()
            
        except Exception as e:
            print(f"Failed to get company statistics: {e}")
    
    def get_source_distribution(self):
        """Get data source distribution (only for merged_jobs table)"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute(f"""
                SELECT source, COUNT(*) as count
                FROM {MERGED_JOBS_TABLE}
                GROUP BY source
                ORDER BY count DESC
            """)
            
            results = cursor.fetchall()
            
            if results:
                total = sum(count for _, count in results)
                
                print("\nData source distribution:")
                print("=" * 80)
                
                for source, count in results:
                    percentage = (count / total * 100) if total > 0 else 0
                    bar_length = int(percentage / 2)
                    bar = '█' * bar_length + '░' * (50 - bar_length)
                    print(f"{source:15s} {bar} {percentage:5.1f}% ({count}/{total})")
            
            cursor.close()
            conn.close()
            
        except Exception as e:
            print(f"Failed to get source distribution: {e}")
    
    def export_sample(self, table=None, limit=100, output_file='sample_jobs.json'):
        """Export sample data to JSON"""
        if table is None:
            table = MERGED_JOBS_TABLE
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute(f"""
                SELECT 
                    title, company, employer, location, salary, 
                    job_type, description, url
                FROM {table}
                ORDER BY 
                    CASE 
                        WHEN '{table}' = '{MERGED_JOBS_TABLE}' THEN merged_at
                        ELSE scraped_at
                    END DESC
                LIMIT %s
            """, (limit,))
            
            jobs = cursor.fetchall()
            
            # Convert to serializable format
            jobs_list = []
            for job in jobs:
                job_dict = dict(job)
                # Handle datetime fields
                for key, value in job_dict.items():
                    if isinstance(value, datetime):
                        job_dict[key] = value.isoformat()
                jobs_list.append(job_dict)
            
            # Write to JSON file
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(jobs_list, f, ensure_ascii=False, indent=2)
            
            print(f"\n✓ Exported {len(jobs)} records to {output_file}")
            
            cursor.close()
            conn.close()
            
        except Exception as e:
            print(f"Export failed: {e}")

def main():
    db = JobsDatabase(DATABASE_CONFIG)
    
    print("\n" + "=" * 80)
    print("CareerGo Tool")
    print("=" * 80)
    
    # Test connection
    if not db.test_connection():
        return
    
    db.get_table_stats()
    
    # Data source distribution
    try:
        db.get_source_distribution()
    except:
        pass
    
    try:
        db.get_top_locations(limit=10)
    except:
        pass
    
    try:
        db.get_top_companies(limit=10)
    except:
        pass
    
    # Example search
    print("\n" + "=" * 80)
    print("Example search")
    print("=" * 80)
    
    keywords = ['python', 'data scientist', 'software engineer']
    for keyword in keywords:
        try:
            db.search_jobs(keyword, limit=3)
        except:
            pass
    
    # Export sample
    try:
        db.export_sample(limit=50)
    except:
        pass
    
    print("\n" + "=" * 80)
    print("Query completed")
    print("=" * 80)


if __name__ == "__main__":
    main()

