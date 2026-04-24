"""
Tool Functions
Provide some auxiliary functions
"""

import logging
import json
from typing import List, Dict, Any
from pathlib import Path
import pandas as pd
import psycopg2
from datetime import datetime

logger = logging.getLogger(__name__)


def export_skills_to_csv(db_config: Dict, output_file: str = "extracted_skills.csv"):
    """
    Export extracted skills to CSV file
    
    Args:
        db_config: db configuration
        output_file: Output file path
    """
    try:
        conn = psycopg2.connect(**db_config)
        
        query = """
            SELECT 
                job_id,
                raw_skill,
                skill_type,
                normalized_skill_name,
                normalized_skill_source,
                similarity_score,
                matching_method,
                created_at
            FROM extracted_skills
            ORDER BY created_at DESC
        """
        
        df = pd.read_sql(query, conn)
        df.to_csv(output_file, index=False)
        
        conn.close()
        
        logger.info(f"Successfully exported {len(df)} records to {output_file}")
        return df
        
    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
        return None


def export_skill_statistics(db_config: Dict, output_file: str = "skill_statistics.json"):
    """
    Export skill statistics to JSON file
    
    Args:
        db_config: db configuration
        output_file: Output file path
    """
    try:
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
        
        statistics = {}
        
        # Overall statistics
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(DISTINCT raw_skill) as unique_raw,
                COUNT(DISTINCT normalized_skill_name) as unique_normalized,
                AVG(similarity_score) as avg_similarity
            FROM extracted_skills
        """)
        row = cursor.fetchone()
        statistics['overall'] = {
            'total_extractions': row[0],
            'unique_raw_skills': row[1],
            'unique_normalized_skills': row[2],
            'average_similarity': float(row[3]) if row[3] else 0.0
        }
        
        # By type statistics
        cursor.execute("""
            SELECT skill_type, COUNT(*), COUNT(DISTINCT raw_skill)
            FROM extracted_skills
            GROUP BY skill_type
            ORDER BY COUNT(*) DESC
        """)
        statistics['by_type'] = [
            {'type': row[0], 'count': row[1], 'unique': row[2]}
            for row in cursor.fetchall()
        ]
        
        # By source statistics
        cursor.execute("""
            SELECT normalized_skill_source, COUNT(*)
            FROM extracted_skills
            WHERE normalized_skill_source IS NOT NULL
            GROUP BY normalized_skill_source
        """)
        statistics['by_source'] = {row[0]: row[1] for row in cursor.fetchall()}
        
        # By matching method statistics
        cursor.execute("""
            SELECT matching_method, COUNT(*)
            FROM extracted_skills
            WHERE matching_method IS NOT NULL
            GROUP BY matching_method
        """)
        statistics['by_method'] = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Most common skills
        cursor.execute("""
            SELECT normalized_skill_name, COUNT(*) as freq
            FROM extracted_skills
            WHERE normalized_skill_name IS NOT NULL
            GROUP BY normalized_skill_name
            ORDER BY freq DESC
            LIMIT 20
        """)
        statistics['top_skills'] = [
            {'skill': row[0], 'frequency': row[1]}
            for row in cursor.fetchall()
        ]
        
        cursor.close()
        conn.close()
        
        # Save to file
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(statistics, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Successfully exported statistics to {output_file}")
        return statistics
        
    except Exception as e:
        logger.error(f"Error exporting statistics: {e}")
        return None


def create_skill_mapping_report(db_config: Dict, output_file: str = "skill_mapping_report.html"):
    """
    Create skill mapping report (HTML format)
    
    Args:
        db_config: db configuration
        output_file: Output file path
    """
    try:
        conn = psycopg2.connect(**db_config)
        
        # Get data
        query = """
            SELECT 
                raw_skill,
                normalized_skill_name,
                similarity_score,
                matching_method,
                COUNT(*) as frequency
            FROM extracted_skills
            WHERE normalized_skill_name IS NOT NULL
            GROUP BY raw_skill, normalized_skill_name, similarity_score, matching_method
            ORDER BY frequency DESC
            LIMIT 100
        """
        
        df = pd.read_sql(query, conn)
        conn.close()
        
        # Create HTML report
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Skill Mapping Report</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    margin: 20px;
                    background-color: #f5f5f5;
                }}
                h1 {{
                    color: #333;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    background-color: white;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                th, td {{
                    padding: 12px;
                    text-align: left;
                    border-bottom: 1px solid #ddd;
                }}
                th {{
                    background-color: #4CAF50;
                    color: white;
                }}
                tr:hover {{
                    background-color: #f5f5f5;
                }}
                .similarity {{
                    font-weight: bold;
                }}
                .high {{ color: #4CAF50; }}
                .medium {{ color: #FF9800; }}
                .low {{ color: #F44336; }}
            </style>
        </head>
        <body>
            <h1>Skill Mapping Report</h1>
            <p>Generated time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>Total mappings: {len(df)}</p>
            
            <table>
                <thead>
                    <tr>
                        <th>Raw skills</th>
                        <th>Normalized skills</th>
                        <th>Similarity</th>
                        <th>Matching method</th>
                        <th>Frequency</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for _, row in df.iterrows():
            similarity = row['similarity_score']
            if similarity >= 0.9:
                sim_class = 'high'
            elif similarity >= 0.7:
                sim_class = 'medium'
            else:
                sim_class = 'low'
            
            html += f"""
                    <tr>
                        <td>{row['raw_skill']}</td>
                        <td>{row['normalized_skill_name']}</td>
                        <td class="similarity {sim_class}">{similarity:.3f}</td>
                        <td>{row['matching_method']}</td>
                        <td>{row['frequency']}</td>
                    </tr>
            """
        
        html += """
                </tbody>
            </table>
        </body>
        </html>
        """
        
        # Save file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html)
        
        logger.info(f"Successfully created report: {output_file}")
        return output_file
        
    except Exception as e:
        logger.error(f"Error creating report: {e}")
        return None


def validate_database_connection(db_config: Dict) -> bool:
    """
    Validate database connection
    
    Args:
        db_config: db configuration
        
    Returns:
        Whether the connection is successful
    """
    try:
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()
        cursor.close()
        conn.close()
        
        logger.info(f"Database connection successful: {version[0]}")
        return True
        
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


def check_required_tables(db_config: Dict) -> Dict[str, bool]:
    """
    Check if the required database tables exist
    
    Args:
        db_config: db configuration
        
    Returns:
        Dictionary of table existence status
    """
    required_tables = [
        'esco_skills',
        'onet_skills',
        'extracted_skills',
        'adzuna_jobs'
    ]
    
    try:
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
        
        status = {}
        for table in required_tables:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = %s
                );
            """, (table,))
            status[table] = cursor.fetchone()[0]
        
        cursor.close()
        conn.close()
        
        return status
        
    except Exception as e:
        logger.error(f"Error checking tables: {e}")
        return {table: False for table in required_tables}


def main():
    """Test tool functions"""
    try:
        from SkillExtraction.config import DB_CONFIG  # type: ignore
    except Exception:
        from config import DB_CONFIG  # type: ignore
    
    print("Validate database connection...")
    if validate_database_connection(DB_CONFIG):
        print("✓ Database connection successful")
    else:
        print("✗ Database connection failed")
        return
    
    print("\nCheck required tables...")
    table_status = check_required_tables(DB_CONFIG)
    for table, exists in table_status.items():
        status = "✓" if exists else "✗"
        print(f"{status} {table}")
    
    print("\nExport data...")
    export_skills_to_csv(DB_CONFIG)
    export_skill_statistics(DB_CONFIG)
    create_skill_mapping_report(DB_CONFIG)
    
    print("\nDone!")


if __name__ == "__main__":
    main()








