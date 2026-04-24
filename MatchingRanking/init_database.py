"""
Database initialization script
Create database tables for user profile
"""

import psycopg2
from config import DATABASE_CONFIG
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_tables():
    """Create all necessary database tables"""
    
    conn = psycopg2.connect(**DATABASE_CONFIG)
    cursor = conn.cursor()
    
    try:
        # 1. User basic information table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id VARCHAR(50) PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(100),
                phone VARCHAR(20),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("✓ Created table: users")
        
        # 2. Education background table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_education (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) REFERENCES users(user_id) ON DELETE CASCADE,
                level VARCHAR(20) NOT NULL,
                major VARCHAR(100) NOT NULL,
                school VARCHAR(200) NOT NULL,
                graduation_year INTEGER,
                gpa FLOAT,
                ranking VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("✓ Created table: user_education")
        
        # 3. Skills table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_skills (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) REFERENCES users(user_id) ON DELETE CASCADE,
                name VARCHAR(100) NOT NULL,
                proficiency FLOAT CHECK (proficiency >= 0 AND proficiency <= 1),
                years_of_experience FLOAT,
                category VARCHAR(50),
                verified BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, name)
            )
        """)
        logger.info("✓ Created table: user_skills")

        # 3.1 User normalized skills table (ESCO/O*NET standardization for matching)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_normalized_skills (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) REFERENCES users(user_id) ON DELETE CASCADE,
                raw_skill_text VARCHAR(200) NOT NULL,
                normalized_skill_name VARCHAR(200) NOT NULL,
                esco_skill_id INTEGER,
                similarity_score DECIMAL(5, 4),
                normalization_method VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, raw_skill_text)
            )
        """)
        logger.info("✓ Created table: user_normalized_skills")
        
        # 4. User preferences table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) REFERENCES users(user_id) ON DELETE CASCADE,
                preference_type VARCHAR(50) NOT NULL,
                value VARCHAR(200) NOT NULL,
                weight FLOAT DEFAULT 1.0 CHECK (weight >= 0 AND weight <= 1),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("✓ Created table: user_preferences")
        
        # 5. User constraints table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_constraints (
                user_id VARCHAR(50) PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                locations TEXT[],
                min_salary FLOAT,
                max_salary FLOAT,
                work_type VARCHAR(50),
                start_date DATE,
                industries TEXT[],
                company_types TEXT[],
                exclude_companies TEXT[],
                max_commute_time INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("✓ Created table: user_constraints")
        
        # 6. Work experience table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_work_experience (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) REFERENCES users(user_id) ON DELETE CASCADE,
                company VARCHAR(200) NOT NULL,
                position VARCHAR(100) NOT NULL,
                duration_months INTEGER,
                responsibilities TEXT[],
                achievements TEXT[],
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("✓ Created table: user_work_experience")
        
        # 7. User certifications table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_certifications (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) REFERENCES users(user_id) ON DELETE CASCADE,
                certification_name VARCHAR(200) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("✓ Created table: user_certifications")
        
        # 8. User languages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_languages (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) REFERENCES users(user_id) ON DELETE CASCADE,
                language VARCHAR(50) NOT NULL,
                proficiency VARCHAR(50) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, language)
            )
        """)
        logger.info("✓ Created table: user_languages")
        
        # 9. User projects table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_projects (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) REFERENCES users(user_id) ON DELETE CASCADE,
                name VARCHAR(200) NOT NULL,
                description TEXT,
                tech_stack TEXT[],
                url VARCHAR(500),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("✓ Created table: user_projects")
        
        # 10. Matching history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS matching_history (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) REFERENCES users(user_id) ON DELETE CASCADE,
                job_id VARCHAR(100),
                match_score FLOAT,
                relevance_score FLOAT,
                feasibility_score FLOAT,
                growth_score FLOAT,
                final_score FLOAT,
                explanation TEXT,
                reasoning_json JSONB,
                score_breakdown_json JSONB,
                matched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("✓ Created table: matching_history")
        
        # 11. User actions table (click, apply, etc.)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_actions (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) REFERENCES users(user_id) ON DELETE CASCADE,
                job_id VARCHAR(100),
                action_type VARCHAR(20) NOT NULL,
                action_data JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("✓ Created table: user_actions")
        
        # Create indexes for better query performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_skills_user_id ON user_skills(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_normalized_skills_user_id ON user_normalized_skills(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_normalized_skills_normalized_name
                ON user_normalized_skills(normalized_skill_name);
            CREATE INDEX IF NOT EXISTS idx_user_education_user_id ON user_education(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_work_experience_user_id ON user_work_experience(user_id);
            CREATE INDEX IF NOT EXISTS idx_matching_history_user_id ON matching_history(user_id);
            CREATE INDEX IF NOT EXISTS idx_matching_history_job_id ON matching_history(job_id);
            CREATE INDEX IF NOT EXISTS idx_user_actions_user_id ON user_actions(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_actions_job_id ON user_actions(job_id);
        """)
        logger.info("✓ Created indexes")
        
        conn.commit()
        logger.info("\n✅ All tables created successfully!")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error creating tables: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


def drop_tables():
    """Drop all tables (use with caution)"""
    conn = psycopg2.connect(**DATABASE_CONFIG)
    cursor = conn.cursor()
    
    try:
        tables = [
            'user_actions',
            'matching_history',
            'user_projects',
            'user_languages',
            'user_certifications',
            'user_work_experience',
            'user_constraints',
            'user_preferences',
            'user_skills',
            'user_normalized_skills',
            'user_education',
            'users'
        ]
        
        for table in tables:
            cursor.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
            logger.info(f"✓ Dropped table: {table}")
        
        conn.commit()
        logger.info("\n✓ All tables dropped successfully!")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"✗ Error dropping tables: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--drop':
        confirm = input("Are you sure you want to drop all tables? (yes/no): ")
        if confirm.lower() == 'yes':
            drop_tables()
        else:
            print("✗ Operation cancelled.")
    else:
        create_tables()

