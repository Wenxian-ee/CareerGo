"""
Database operation class
Provide CRUD operations and job data query for user profile
"""

import psycopg2
from psycopg2.extras import Json, RealDictCursor, execute_values
from typing import Any, List, Dict, Optional, Tuple
import logging
import re
from datetime import datetime
import json
import hashlib
import sys
from pathlib import Path

from config import DATABASE_CONFIG, MERGED_JOBS_TABLE, NORMALIZED_JOB_SKILLS_TABLE
from user_profile import (
    UserProfile, Education, Skill, Preference, Constraints, 
    WorkExperience, EducationLevel, PreferenceType
)

logger = logging.getLogger(__name__)

# --- Job catalog filter helpers (dropdown dedupe / avoid work-type as "category") ---

_WORK_TYPE_AS_CATEGORY = re.compile(
    r"^\s*(full|part)\s*[-]?\s*time\s*$|"
    r"^\s*(permanent|temporary|contract|fixed[- ]?term|internship|hybrid|seasonal|freelance)\s*$|"
    r"^\s*remote\s*$",
    re.I,
)


def _norm_filter_dedupe_key(s: str) -> str:
    """Collapse spaces/hyphens so 'Full Time' and 'Full-time' dedupe together."""
    return re.sub(r"[\s\-_]+", "", (s or "").strip().lower())


def dedupe_filter_labels(values: List[str]) -> List[str]:
    """Drop duplicate labels that only differ by spacing or hyphenation."""
    seen = set()
    out: List[str] = []
    for v in values:
        if not v or not str(v).strip():
            continue
        k = _norm_filter_dedupe_key(str(v))
        if k in seen:
            continue
        seen.add(k)
        out.append(str(v).strip())
    return out


def should_exclude_category_dropdown_label(label: str, job_type_keys: set) -> bool:
    """True if this value belongs in job-type filter, not category/subcategory."""
    s = (label or "").strip()
    if not s:
        return True
    if _WORK_TYPE_AS_CATEGORY.search(s):
        return True
    if _norm_filter_dedupe_key(s) in job_type_keys:
        return True
    return False


def sanitize_category_dropdown_labels(
    categories: List[str], job_types: List[str]
) -> List[str]:
    """Remove work-type strings mistakenly stored in category/subcategory (or duplicated as job types)."""
    jk = {_norm_filter_dedupe_key(x) for x in job_types if x}
    return [
        c
        for c in categories
        if c and not should_exclude_category_dropdown_label(c, jk)
    ]


class DatabaseManager:
    """Database manager"""
    
    def __init__(self, db_config: Optional[Dict[str, Any]] = None):
        """Initialize database manager"""
        self.db_config = db_config or DATABASE_CONFIG
        # Lazy-load and cache SkillNormalizer (heavy model load)
        self._skill_normalizer = None
    
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
    
    def create_user(
        self,
        user_id: str,
        name: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> bool:
        """Create user"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO users (user_id, name, email, phone)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE
                SET name = EXCLUDED.name,
                    email = EXCLUDED.email,
                    phone = EXCLUDED.phone,
                    updated_at = CURRENT_TIMESTAMP
            """, (user_id, name, email, phone))
            
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"✓ User {user_id} created/updated successfully")
            return True
        except Exception as e:
            logger.error(f"Create user failed: {e}")
            return False
    
    def get_user(self, user_id: str) -> Optional[Dict]:
        """Get user basic information"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            user = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            return dict(user) if user else None
        except Exception as e:
            logger.error(f"Get user failed: {e}")
            return None
    
    def delete_user(self, user_id: str) -> bool:
        """Delete user"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
            
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"✓ User {user_id} deleted successfully")
            return True
        except Exception as e:
            logger.error(f"Delete user failed: {e}")
            return False
    
    def save_education(self, user_id: str, education_list: List[Education]) -> bool:
        """Save user education background"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM user_education WHERE user_id = %s", (user_id,))
            
            for edu in education_list:
                cursor.execute("""
                    INSERT INTO user_education 
                    (user_id, level, major, school, graduation_year, gpa, ranking)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (user_id, edu.level.value, edu.major, edu.school, 
                      edu.graduation_year, edu.gpa, edu.ranking))
            
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"✓ User {user_id} education background saved successfully")
            return True
        except Exception as e:
            logger.error(f"Save education background failed: {e}")
            return False
    
    def get_education(self, user_id: str) -> List[Education]:
        """Get user education background"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT * FROM user_education WHERE user_id = %s
                ORDER BY graduation_year DESC
            """, (user_id,))
            
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            
            education_list = []
            for row in rows:
                edu = Education(
                    level=EducationLevel(row['level']),
                    major=row['major'],
                    school=row['school'],
                    graduation_year=row['graduation_year'],
                    gpa=row['gpa'],
                    ranking=row['ranking']
                )
                education_list.append(edu)
            
            return education_list
        except Exception as e:
            logger.error(f"Get education background failed: {e}")
            return []
    
    def save_skills(self, user_id: str, skills: List[Skill]) -> bool:
        """Save user skills"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM user_skills WHERE user_id = %s", (user_id,))
            
            for skill in skills:
                cursor.execute("""
                    INSERT INTO user_skills 
                    (user_id, name, proficiency, years_of_experience, category, verified)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (user_id, skill.name, skill.proficiency, 
                      skill.years_of_experience, skill.category, skill.verified))

            # Also persist ESCO-normalized mapping for matching.
            # If ESCO tables are missing / model fails to load, we will fallback to raw skills only.
            try:
                self._save_normalized_skills(cursor, user_id, skills)
            except Exception as e:
                logger.warning(f"Skip skill normalization for user {user_id}: {e}")
            
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"✓ User {user_id} skills saved successfully")
            return True
        except Exception as e:
            logger.error(f"Save skills failed: {e}")
            return False

    def _get_skill_normalizer(self):
        """Lazy-load SkillNormalizer from SkillExtraction module."""
        if self._skill_normalizer is not None:
            return self._skill_normalizer
        
        # Ensure repo root is on sys.path so `import SkillExtraction...` works
        repo_root = Path(__file__).resolve().parents[1]
        if str(repo_root) not in sys.path:
            sys.path.append(str(repo_root))

        try:
            from SkillExtraction.skill_normalizer import SkillNormalizer
            self._skill_normalizer = SkillNormalizer(db_config=self.db_config)
        except Exception as e:
            logger.warning(f"Failed to initialize SkillNormalizer: {e}")
            self._skill_normalizer = None
        
        return self._skill_normalizer

    def _save_normalized_skills(self, cursor, user_id: str, skills: List[Skill]) -> None:
        """Save user -> normalized skill mapping into `user_normalized_skills`."""
        normalizer = self._get_skill_normalizer()
        if not normalizer:
            # Can't normalize; keep only raw skills.
            return

        cursor.execute("DELETE FROM user_normalized_skills WHERE user_id = %s", (user_id,))

        rows_to_insert = []
        for skill in skills:
            raw_skill_text = (skill.name or "").strip()
            if not raw_skill_text:
                continue

            matches = normalizer.normalize_skill(raw_skill_text, top_k=1)
            if matches:
                best = matches[0]
                skill_info = best.get("skill") or {}
                normalized_name = (skill_info.get("name") or raw_skill_text).strip()
                rows_to_insert.append(
                    (
                        user_id,
                        raw_skill_text,
                        normalized_name,
                        int(skill_info["id"]) if skill_info.get("id") is not None else None,
                        float(best.get("similarity", 0.0)) if best.get("similarity") is not None else None,
                        str(best.get("method") or ""),
                    )
                )
            else:
                # Keep raw skill as normalized fallback so matching can still work for exact matches.
                rows_to_insert.append(
                    (
                        user_id,
                        raw_skill_text,
                        raw_skill_text,
                        None,
                        None,
                        "no_match",
                    )
                )

        if not rows_to_insert:
            return

        execute_values(
            cursor,
            """
            INSERT INTO user_normalized_skills
                (user_id, raw_skill_text, normalized_skill_name, esco_skill_id, similarity_score, normalization_method)
            VALUES %s
            ON CONFLICT (user_id, raw_skill_text) DO UPDATE SET
                normalized_skill_name = EXCLUDED.normalized_skill_name,
                esco_skill_id = EXCLUDED.esco_skill_id,
                similarity_score = EXCLUDED.similarity_score,
                normalization_method = EXCLUDED.normalization_method
            """,
            rows_to_insert,
        )
    
    def get_skills(self, user_id: str) -> List[Skill]:
        """Get user skills"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Backward compatibility:
            # If `user_normalized_skills` table doesn't exist yet, fallback to `user_skills` only.
            cursor.execute("SELECT to_regclass('user_normalized_skills') AS t")
            row = cursor.fetchone()
            has_normalized_table = bool(row and row.get("t"))
            
            if has_normalized_table:
                cursor.execute("""
                    SELECT
                        us.name AS raw_skill_text,
                        us.proficiency,
                        us.years_of_experience,
                        us.category,
                        us.verified,
                        COALESCE(uns.normalized_skill_name, us.name) AS skill_name,
                        uns.esco_skill_id,
                        uns.similarity_score,
                        uns.normalization_method
                    FROM user_skills us
                    LEFT JOIN user_normalized_skills uns
                        ON us.user_id = uns.user_id
                       AND us.name = uns.raw_skill_text
                    WHERE us.user_id = %s
                    ORDER BY us.proficiency DESC, us.years_of_experience DESC
                """, (user_id,))
            else:
                cursor.execute("""
                    SELECT
                        us.name AS raw_skill_text,
                        us.proficiency,
                        us.years_of_experience,
                        us.category,
                        us.verified
                    FROM user_skills us
                    WHERE us.user_id = %s
                    ORDER BY us.proficiency DESC, us.years_of_experience DESC
                """, (user_id,))
            
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            
            skills = []
            for row in rows:
                skill = Skill(
                    name=row.get('skill_name') or row['raw_skill_text'],
                    raw_name=row['raw_skill_text'],
                    esco_skill_id=row.get('esco_skill_id'),
                    similarity_score=float(row['similarity_score']) if row.get('similarity_score') is not None else None,
                    normalization_method=row.get('normalization_method'),
                    proficiency=row['proficiency'],
                    years_of_experience=float(row['years_of_experience'] or 0),
                    category=row.get('category') or '',
                    verified=bool(row.get('verified')),
                )
                skills.append(skill)
            
            return skills
        except Exception as e:
            logger.error(f"Get skills failed: {e}")
            return []
    
    def save_preferences(self, user_id: str, preferences: List[Preference]) -> bool:
        """Save user preferences"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM user_preferences WHERE user_id = %s", (user_id,))
            
            for pref in preferences:
                cursor.execute("""
                    INSERT INTO user_preferences 
                    (user_id, preference_type, value, weight)
                    VALUES (%s, %s, %s, %s)
                """, (user_id, pref.preference_type.value, pref.value, pref.weight))
            
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"✓ User {user_id} preferences saved successfully")
            return True
        except Exception as e:
            logger.error(f"Save preferences failed: {e}")
            return False
    
    def get_preferences(self, user_id: str) -> List[Preference]:
        """Get user preferences"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT * FROM user_preferences WHERE user_id = %s
                ORDER BY weight DESC
            """, (user_id,))
            
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            
            preferences = []
            for row in rows:
                pref = Preference(
                    preference_type=PreferenceType(row['preference_type']),
                    value=row['value'],
                    weight=row['weight']
                )
                preferences.append(pref)
            
            return preferences
        except Exception as e:
            logger.error(f"Get preferences failed: {e}")
            return []
    
    def save_constraints(self, user_id: str, constraints: Constraints) -> bool:
        """Save user constraints"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO user_constraints 
                (user_id, locations, min_salary, max_salary, work_type, 
                 start_date, industries, company_types, exclude_companies, max_commute_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE
                SET locations = EXCLUDED.locations,
                    min_salary = EXCLUDED.min_salary,
                    max_salary = EXCLUDED.max_salary,
                    work_type = EXCLUDED.work_type,
                    start_date = EXCLUDED.start_date,
                    industries = EXCLUDED.industries,
                    company_types = EXCLUDED.company_types,
                    exclude_companies = EXCLUDED.exclude_companies,
                    max_commute_time = EXCLUDED.max_commute_time,
                    updated_at = CURRENT_TIMESTAMP
            """, (user_id, constraints.locations, constraints.min_salary,
                  constraints.max_salary, constraints.work_type, constraints.start_date,
                  constraints.industries, constraints.company_types,
                  list(constraints.exclude_companies), constraints.max_commute_time))
            
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"✓ User {user_id} constraints saved successfully")
            return True
        except Exception as e:
            logger.error(f"Save constraints failed: {e}")
            return False
    
    def get_constraints(self, user_id: str) -> Optional[Constraints]:
        """Get user constraints"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT * FROM user_constraints WHERE user_id = %s
            """, (user_id,))
            
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if row:
                sd = row.get('start_date')
                if sd is not None and not isinstance(sd, str):
                    sd = str(sd)
                constraints = Constraints(
                    locations=row['locations'] or [],
                    min_salary=row['min_salary'],
                    max_salary=row['max_salary'],
                    work_type=row['work_type'],
                    start_date=sd,
                    industries=row['industries'] or [],
                    company_types=row['company_types'] or [],
                    exclude_companies=set(row['exclude_companies'] or []),
                    max_commute_time=row.get('max_commute_time'),
                )
                return constraints
            return None
        except Exception as e:
            logger.error(f"Get constraints failed: {e}")
            return None
    
    def save_work_experience(self, user_id: str, experiences: List[WorkExperience]) -> bool:
        """Save work experience"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM user_work_experience WHERE user_id = %s", (user_id,))
            
            for exp in experiences:
                cursor.execute("""
                    INSERT INTO user_work_experience 
                    (user_id, company, position, duration_months, responsibilities, achievements)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (user_id, exp.company, exp.position, exp.duration_months,
                      exp.responsibilities, exp.achievements))
            
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"✓ User {user_id} work experience saved successfully")
            return True
        except Exception as e:
            logger.error(f"Save work experience failed: {e}")
            return False
    
    def get_work_experience(self, user_id: str) -> List[WorkExperience]:
        """Get work experience"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT * FROM user_work_experience WHERE user_id = %s
                ORDER BY duration_months DESC
            """, (user_id,))
            
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            
            experiences = []
            for row in rows:
                exp = WorkExperience(
                    company=row['company'],
                    position=row['position'],
                    duration_years=(row['duration_months'] or 0) / 12.0,
                    responsibilities=row['responsibilities'] or [],
                    achievements=row['achievements'] or []
                )
                experiences.append(exp)
            
            return experiences
        except Exception as e:
            logger.error(f"Get work experience failed: {e}")
            return []
    
    def save_certifications(self, user_id: str, certifications: List[str]) -> bool:
        """Save certifications"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM user_certifications WHERE user_id = %s", (user_id,))
            
            for cert in certifications:
                cursor.execute("""
                    INSERT INTO user_certifications (user_id, certification_name)
                    VALUES (%s, %s)
                """, (user_id, cert))
            
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Save certifications failed: {e}")
            return False
    
    def get_certifications(self, user_id: str) -> List[str]:
        """Get certifications"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT certification_name FROM user_certifications WHERE user_id = %s
            """, (user_id,))
            
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"Get certifications failed: {e}")
            return []
    
    def save_languages(self, user_id: str, languages: Dict[str, str]) -> bool:
        """Save languages"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM user_languages WHERE user_id = %s", (user_id,))
            
            for lang, prof in languages.items():
                cursor.execute("""
                    INSERT INTO user_languages (user_id, language, proficiency)
                    VALUES (%s, %s, %s)
                """, (user_id, lang, prof))
            
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Save languages failed: {e}")
            return False
    
    def get_languages(self, user_id: str) -> Dict[str, str]:
        """Get languages"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT language, proficiency FROM user_languages WHERE user_id = %s
            """, (user_id,))
            
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return {row[0]: row[1] for row in rows}
        except Exception as e:
            logger.error(f"Get languages failed: {e}")
            return {}
    
    def save_projects(self, user_id: str, projects: List[Dict]) -> bool:
        """Save projects"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM user_projects WHERE user_id = %s", (user_id,))
            
            for proj in projects:
                cursor.execute("""
                    INSERT INTO user_projects 
                    (user_id, name, description, tech_stack, url)
                    VALUES (%s, %s, %s, %s, %s)
                """, (user_id, proj.get('name'), proj.get('description'),
                      proj.get('tech_stack', []), proj.get('url')))
            
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Save projects failed: {e}")
            return False
    
    def get_projects(self, user_id: str) -> List[Dict]:
        """Get projects"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT name, description, tech_stack, url 
                FROM user_projects WHERE user_id = %s
            """, (user_id,))
            
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Get projects failed: {e}")
            return []
    
    def save_user_profile(self, profile: UserProfile) -> bool:
        """Save complete user profile. Any sub-step returning False fails the whole save (API should 500)."""
        try:
            steps = [
                ("create_user", lambda: self.create_user(profile.user_id, profile.name)),
                ("save_education", lambda: self.save_education(profile.user_id, profile.education)),
                ("save_skills", lambda: self.save_skills(profile.user_id, profile.skills)),
                ("save_preferences", lambda: self.save_preferences(profile.user_id, profile.preferences)),
                ("save_constraints", lambda: self.save_constraints(profile.user_id, profile.constraints)),
                ("save_work_experience", lambda: self.save_work_experience(profile.user_id, profile.work_experience)),
                ("save_certifications", lambda: self.save_certifications(profile.user_id, profile.certifications)),
                ("save_languages", lambda: self.save_languages(profile.user_id, profile.languages)),
                ("save_projects", lambda: self.save_projects(profile.user_id, profile.projects)),
            ]
            for name, fn in steps:
                if not fn():
                    logger.error("save_user_profile: step %s returned False for user %s", name, profile.user_id)
                    return False
            logger.info(f"✓ User profile {profile.user_id} saved successfully")
            return True
        except Exception as e:
            logger.error(f"Save user profile failed: {e}")
            return False
    
    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        """Get complete user profile"""
        try:
            user = self.get_user(user_id)
            if not user:
                logger.warning(f"User {user_id} does not exist")
                return None
            
            education = self.get_education(user_id)
            skills = self.get_skills(user_id)
            preferences = self.get_preferences(user_id)
            constraints = self.get_constraints(user_id)
            work_experience = self.get_work_experience(user_id)
            certifications = self.get_certifications(user_id)
            languages = self.get_languages(user_id)
            projects = self.get_projects(user_id)
            
            profile = UserProfile(
                user_id,
                user['name'],
                education,
                skills,
                preferences,
                constraints or Constraints(),
                work_experience,
                certifications,
                languages,
                projects,
            )
            
            logger.info(f"✓ User profile {user_id} loaded successfully")
            return profile
        except Exception as e:
            logger.error(f"Get user profile failed: {e}")
            return None
    
    def list_users(self, limit: int = 100) -> List[Dict]:
        """List all users"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT user_id, name, email, created_at, updated_at 
                FROM users 
                ORDER BY created_at DESC 
                LIMIT %s
            """, (limit,))
            
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"List users failed: {e}")
            return []
    
    def _append_merged_jobs_filters(self, query: str, params: List, filters: Optional[Dict]) -> str:
        """Shared WHERE fragments for merged_jobs listings (same keys as get_jobs_from_merged_table)."""
        if not filters:
            return query
        if filters.get('location'):
            query += " AND mj.location ILIKE %s"
            params.append(f"%{filters['location']}%")

        if filters.get('job_type'):
            query += (
                " AND (COALESCE(mj.job_type::text, '') ILIKE %s "
                "OR COALESCE(mj.contract_type::text, '') ILIKE %s)"
            )
            jt = f"%{filters['job_type']}%"
            params.extend([jt, jt])

        if filters.get('category'):
            query += (
                " AND (COALESCE(mj.category::text, '') ILIKE %s "
                "OR COALESCE(mj.subcategory::text, '') ILIKE %s)"
            )
            c = f"%{filters['category']}%"
            params.extend([c, c])

        if 'min_salary' in filters and filters['min_salary'] is not None:
            query += " AND mj.salary_min >= %s"
            params.append(filters['min_salary'])

        if 'max_salary' in filters and filters['max_salary'] is not None:
            query += " AND mj.salary_max <= %s"
            params.append(filters['max_salary'])

        if filters.get('keywords'):
            query += " AND (mj.title ILIKE %s OR mj.description ILIKE %s)"
            keyword = f"%{filters['keywords']}%"
            params.extend([keyword, keyword])

        if filters.get('source'):
            query += " AND mj.source ILIKE %s"
            params.append(f"%{filters['source']}%")

        return query

    def count_merged_jobs(self, filters: Optional[Dict] = None) -> int:
        """Count distinct jobs in merged_jobs with optional filters (aligned with list endpoint)."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            query = f"""
                SELECT COUNT(DISTINCT mj.id)
                FROM {MERGED_JOBS_TABLE} mj
                LEFT JOIN {NORMALIZED_JOB_SKILLS_TABLE} njs
                    ON mj.job_id = njs.job_id
                WHERE 1=1
            """
            params: List = []
            query = self._append_merged_jobs_filters(query, params, filters)
            cursor.execute(query, params)
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            return int(row[0]) if row and row[0] is not None else 0
        except Exception as e:
            logger.error(f"count_merged_jobs failed: {e}")
            return 0

    def get_merged_job_by_job_id(self, job_id: str) -> Optional[Dict]:
        """Single merged job row with aggregated normalized skills (for API detail / reasoning)."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                f"""
                SELECT
                    mj.*,
                    COALESCE(
                        ARRAY_AGG(DISTINCT njs.normalized_skill_name)
                            FILTER (WHERE njs.normalized_skill_name IS NOT NULL),
                        ARRAY[]::TEXT[]
                    ) AS required_skills
                FROM {MERGED_JOBS_TABLE} mj
                LEFT JOIN {NORMALIZED_JOB_SKILLS_TABLE} njs
                    ON mj.job_id = njs.job_id
                WHERE mj.job_id::text = %s
                GROUP BY mj.id
                LIMIT 1
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_merged_job_by_job_id failed: {e}")
            return None

    def list_distinct_job_types(self, limit: int = 80) -> List[str]:
        """Distinct non-empty job_type / contract_type values for filter UI."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT DISTINCT q.v FROM (
                    SELECT NULLIF(TRIM(job_type), '') AS v FROM {MERGED_JOBS_TABLE} WHERE job_type IS NOT NULL
                    UNION
                    SELECT NULLIF(TRIM(contract_type), '') FROM {MERGED_JOBS_TABLE} WHERE contract_type IS NOT NULL
                ) q
                WHERE q.v IS NOT NULL
                ORDER BY q.v
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            return [r[0] for r in rows if r and r[0]]
        except Exception as e:
            logger.error(f"list_distinct_job_types failed: {e}")
            return []

    def list_distinct_locations(self, limit: int = 120) -> List[str]:
        """
        Locations for filter dropdowns: order by frequency so mixed locales (e.g. UK + CN)
        are not pushed out by alphabetical ASCII-only ORDER BY + small LIMIT.
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT TRIM(location) AS loc
                FROM {MERGED_JOBS_TABLE}
                WHERE location IS NOT NULL AND TRIM(location) <> ''
                GROUP BY TRIM(location)
                ORDER BY COUNT(*) DESC, loc ASC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            return [r[0] for r in rows if r and r[0]]
        except Exception as e:
            logger.error(f"list_distinct_locations failed: {e}")
            return []

    def list_distinct_categories(self, limit: int = 80) -> List[str]:
        """Distinct category / subcategory values for filter dropdowns (raw from DB)."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT DISTINCT q.c FROM (
                    SELECT NULLIF(TRIM(category), '') AS c FROM {MERGED_JOBS_TABLE} WHERE category IS NOT NULL
                    UNION
                    SELECT NULLIF(TRIM(subcategory), '') FROM {MERGED_JOBS_TABLE} WHERE subcategory IS NOT NULL
                ) q
                WHERE q.c IS NOT NULL
                ORDER BY q.c
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            return [r[0] for r in rows if r and r[0]]
        except Exception as e:
            logger.error(f"list_distinct_categories failed: {e}")
            return []

    def get_job_skill_graph_d3(
        self,
        job_id: str,
        max_skills: int = 28,
        max_related: int = 6,
        allow_related_fallback: bool = False,
    ) -> Dict:
        """Small job–skill–related-job graph for visualization (D3-style nodes + links).

        Skills are extracted on-demand from the current job row (title/requirements/raw skill fields),
        then normalized at request time. This does not require prelinked rows for this job in
        normalized_job_skills.
        """

        def nid(prefix: str, key: str) -> str:
            h = hashlib.md5(key.encode("utf-8")).hexdigest()[:16]
            return f"{prefix}_{h}"

        row = self.get_merged_job_by_job_id(job_id)
        if not row:
            return {"nodes": [], "links": [], "empty_reason": "job_not_found"}

        jid = str(row.get("job_id") or job_id)
        jtitle = (row.get("title") or jid)[:120]
        center_id = nid("job", jid)
        center_job_url = (
            (str(row.get("apply_url") or "").strip())
            or (str(row.get("url") or "").strip())
            or None
        )
        nodes: List[Dict] = [
            {
                "id": center_id,
                "label": jtitle,
                "group": "job",
                "job_id": jid,
                "job_url": center_job_url,
            }
        ]
        links: List[Dict] = []
        skills: List[str] = []

        def _parse_skill_values(v: Any) -> List[str]:
            if v is None:
                return []
            if isinstance(v, list):
                out = []
                for x in v:
                    s = str(x or "").strip()
                    if s:
                        out.append(s)
                return out
            if isinstance(v, str):
                s = v.strip()
                if not s:
                    return []
                # Try JSON list first; fall back to common separators.
                if s.startswith("[") and s.endswith("]"):
                    try:
                        j = json.loads(s)
                        if isinstance(j, list):
                            return [str(x).strip() for x in j if str(x).strip()]
                    except Exception:
                        pass
                parts = re.split(r"[,\n;/|]+", s)
                return [p.strip() for p in parts if p and p.strip()]
            return []

        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            # 1) Build candidate phrases directly from the current job row.
            candidates: List[str] = []
            candidates.extend(_parse_skill_values(row.get("required_skills")))
            candidates.extend(_parse_skill_values(row.get("preferred_skills")))
            candidates.extend(_parse_skill_values(row.get("requirements")))
            candidates.extend(_parse_skill_values(row.get("description")))
            title = str(row.get("title") or "").strip()
            if title:
                candidates.extend([p.strip() for p in re.split(r"[/|,+()\-]", title) if p and p.strip()])

            # Keep only short phrase-like candidates; avoid long sentence chunks.
            cleaned_candidates: List[str] = []
            seen_raw = set()
            for c in candidates:
                s = str(c or "").strip()
                if not s:
                    continue
                if len(s) > 64:
                    continue
                key = s.lower()
                if key in seen_raw:
                    continue
                seen_raw.add(key)
                cleaned_candidates.append(s)
                if len(cleaned_candidates) >= 120:
                    break

            # 2) Normalize candidates on-demand (runtime extraction), fallback to raw if unmatched.
            normalizer = self._get_skill_normalizer()
            normalized: List[str] = []
            seen_norm = set()
            for phrase in cleaned_candidates:
                norm_name = phrase
                if normalizer:
                    try:
                        matches = normalizer.normalize_skill(phrase, top_k=1)
                        if matches:
                            skill_info = (matches[0] or {}).get("skill") or {}
                            norm_name = str(skill_info.get("name") or phrase).strip()
                    except Exception:
                        norm_name = phrase
                key = norm_name.lower()
                if not norm_name or key in seen_norm:
                    continue
                seen_norm.add(key)
                normalized.append(norm_name)
                if len(normalized) >= max_skills:
                    break
            skills = normalized

            # Query related jobs first (via shared normalized skills), then keep
            # only skills that actually connect to at least one related job.
            related: List[Any] = []
            if skills:
                cursor.execute(
                    f"""
                    SELECT n2.job_id::text, COUNT(*) AS cnt
                    FROM {NORMALIZED_JOB_SKILLS_TABLE} n2
                    WHERE n2.normalized_skill_name = ANY(%s)
                      AND n2.job_id::text <> %s
                    GROUP BY n2.job_id
                    ORDER BY cnt DESC
                    LIMIT %s
                    """,
                    (skills, jid, max_related),
                )
                related = cursor.fetchall()

            # skill_name -> set(related_job_id) for every (skill, related_job) pair
            # that actually shares that skill in normalized_job_skills.
            skill_to_related: Dict[str, set] = {}
            related_job_ids_text = [str(r[0]) for r in related]
            if skills and related_job_ids_text:
                cursor.execute(
                    f"""
                    SELECT job_id::text, normalized_skill_name
                    FROM {NORMALIZED_JOB_SKILLS_TABLE}
                    WHERE job_id::text = ANY(%s)
                      AND normalized_skill_name = ANY(%s)
                    """,
                    (related_job_ids_text, skills),
                )
                for rjid_row, skill_row in cursor.fetchall():
                    skill_to_related.setdefault(str(skill_row), set()).add(str(rjid_row))

            # Keep only skills that connect to at least one related job.
            connected_skill_set = set(skill_to_related.keys())
            skills_kept = [s for s in skills if s in connected_skill_set]

            # Skill nodes + center-to-skill edges (only kept skills).
            for s in skills_kept:
                sid = nid("skill", s)
                nodes.append(
                    {
                        "id": sid,
                        "label": s[:100],
                        "group": "skill",
                        "normalized_skill_name": s,
                    }
                )
                links.append({"source": center_id, "target": sid})

            # Related-job nodes + center-to-related edges; also skill->related edges.
            for rjid, cnt in related:
                rjid_text = str(rjid)
                cursor.execute(
                    f"""
                    SELECT
                        title,
                        NULLIF(TRIM(COALESCE(apply_url, url, '')), '') AS job_url
                    FROM {MERGED_JOBS_TABLE}
                    WHERE job_id::text = %s
                    LIMIT 1
                    """,
                    (rjid_text,),
                )
                tr = cursor.fetchone()
                rtitle = (tr[0] if tr and tr[0] else rjid_text)[:100]
                rjob_url = str(tr[1]).strip() if tr and len(tr) > 1 and tr[1] else None
                rid = nid("job", rjid_text)
                if rid == center_id:
                    continue
                nodes.append(
                    {
                        "id": rid,
                        "label": rtitle,
                        "group": "related_job",
                        "job_id": rjid_text,
                        "job_url": rjob_url,
                    }
                )
                links.append({"source": center_id, "target": rid, "weight": int(cnt)})

            # Bridge edges: skill -> related_job (so the UI can show which skill
            # connects the center to which related role).
            for skill_name, rjid_set in skill_to_related.items():
                if skill_name not in connected_skill_set:
                    continue
                sid = nid("skill", skill_name)
                for rjid_text in rjid_set:
                    rid = nid("job", rjid_text)
                    if rid == center_id:
                        continue
                    links.append({"source": sid, "target": rid, "weight": 1})

            # Title-based fallback: skills column has values but no normalized_job_skills
            # row references them yet. The fallback cannot compute true skill overlap, so
            # we intentionally drop all skill nodes in this branch and show related jobs
            # only (matches the product spec: "hide skills that aren't tied to related jobs").
            if skills and not related:
                # Remove any skill nodes/edges that slipped in earlier (defensive).
                nodes = [n for n in nodes if n.get("group") != "skill"]
                links = [
                    lk
                    for lk in links
                    if not (
                        isinstance(lk.get("source"), str)
                        and str(lk["source"]).startswith("skill_")
                    )
                    and not (
                        isinstance(lk.get("target"), str)
                        and str(lk["target"]).startswith("skill_")
                    )
                ]

                like_terms = [f"%{s}%" for s in skills[:8]]
                cursor.execute(
                    f"""
                    SELECT
                        job_id::text,
                        COALESCE(NULLIF(TRIM(title), ''), job_id::text) AS title,
                        NULLIF(TRIM(COALESCE(apply_url, url, '')), '') AS job_url
                    FROM {MERGED_JOBS_TABLE}
                    WHERE job_id::text <> %s
                      AND (
                        title ILIKE ANY(%s) OR
                        COALESCE(description, '') ILIKE ANY(%s) OR
                        COALESCE(requirements::text, '') ILIKE ANY(%s)
                      )
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (jid, like_terms, like_terms, like_terms, max_related),
                )
                rel_rows = cursor.fetchall()
                for rjid, rtitle, rjob_url in rel_rows:
                    rid = nid("job", str(rjid))
                    if rid == center_id:
                        continue
                    if any(n.get("id") == rid for n in nodes):
                        continue
                    nodes.append(
                        {
                            "id": rid,
                            "label": str(rtitle)[:100],
                            "group": "related_job",
                            "job_id": str(rjid),
                            "job_url": str(rjob_url).strip() if rjob_url else None,
                        }
                    )
                    links.append({"source": center_id, "target": rid, "weight": 1})

            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"get_job_skill_graph_d3 failed: {e}")
            return {
                "nodes": nodes,
                "links": links,
                "center_job_id": jid,
                "empty_reason": "partial",
                "error": str(e),
            }

        if len(nodes) <= 1 and allow_related_fallback:
            try:
                conn = self.get_connection()
                cursor = conn.cursor()
                cat = str(row.get("category") or "").strip()
                src = str(row.get("source") or "").strip()
                cursor.execute(
                    f"""
                    SELECT
                        job_id::text,
                        COALESCE(NULLIF(TRIM(title), ''), job_id::text) AS title,
                        NULLIF(TRIM(COALESCE(apply_url, url, '')), '') AS job_url
                    FROM {MERGED_JOBS_TABLE}
                    WHERE job_id::text <> %s
                      AND (
                        (%s <> '' AND category = %s)
                        OR (%s <> '' AND source = %s)
                      )
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (jid, cat, cat, src, src, max_related),
                )
                rel_rows = cursor.fetchall()
                cursor.close()
                conn.close()
                for rjid, rtitle, rjob_url in rel_rows:
                    rid = nid("job", str(rjid))
                    if rid == center_id:
                        continue
                    nodes.append(
                        {
                            "id": rid,
                            "label": str(rtitle)[:100],
                            "group": "related_job",
                            "job_id": str(rjid),
                            "job_url": str(rjob_url).strip() if rjob_url else None,
                        }
                    )
                    links.append({"source": center_id, "target": rid, "weight": 1})
            except Exception as e:
                logger.warning(f"related fallback graph failed: {e}")

        if len(nodes) <= 1:
            return {
                "nodes": nodes,
                "links": links,
                "center_job_id": jid,
                "empty_reason": "no_skills_for_job",
            }
        if not skills:
            return {
                "nodes": nodes,
                "links": links,
                "center_job_id": jid,
                "empty_reason": "fallback_related_only",
            }
        return {"nodes": nodes, "links": links, "center_job_id": jid}

    def get_jobs_from_merged_table(
        self, limit: Optional[int] = 1000, filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict]:
        """Get jobs from merged_jobs table.

        If ``limit`` is ``None``, no SQL LIMIT is applied (full table scan for matching).
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Use standardized skills from normalized_job_skills table
            # Aggregate standardized skills of the same job into required_skills array, for matching algorithm
            query = f"""
                SELECT 
                    mj.*,
                    COALESCE(
                        ARRAY_AGG(DISTINCT njs.normalized_skill_name)
                            FILTER (WHERE njs.normalized_skill_name IS NOT NULL),
                        ARRAY[]::TEXT[]
                    ) AS required_skills
                FROM {MERGED_JOBS_TABLE} mj
                LEFT JOIN {NORMALIZED_JOB_SKILLS_TABLE} njs
                    ON mj.job_id = njs.job_id
                WHERE 1=1
            """
            params = []
            query = self._append_merged_jobs_filters(query, params, filters)

            query += """
                GROUP BY mj.id
                ORDER BY mj.id DESC
            """
            if limit is not None:
                query += " LIMIT %s"
                params.append(limit)
            if filters and filters.get('offset') is not None:
                query += " OFFSET %s"
                params.append(int(filters['offset']))
            
            cursor.execute(query, params)
            jobs = cursor.fetchall()
            
            cursor.close()
            conn.close()
            
            return [dict(job) for job in jobs]
        except Exception as e:
            logger.error(f"Get jobs from merged_table failed: {e}")
            return []
    
    def search_jobs(self, keyword: str, limit: int = 100) -> List[Dict]:
        """Search jobs"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute(f"""
                SELECT * FROM {MERGED_JOBS_TABLE}
                WHERE title ILIKE %s OR description ILIKE %s
                LIMIT %s
            """, (f'%{keyword}%', f'%{keyword}%', limit))
            
            jobs = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return [dict(job) for job in jobs]
        except Exception as e:
            logger.error(f"Search jobs failed: {e}")
            return []
    
    def save_matching_result(
        self,
        user_id: str,
        job_id: str,
        scores: Dict,
        explanation: Optional[str] = None,
        reasoning_json: Optional[Dict] = None,
        score_breakdown_json: Optional[Dict] = None,
    ) -> bool:
        """Save matching result; optional explanation + reasoning payload for API list/detail."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                ALTER TABLE matching_history ADD COLUMN IF NOT EXISTS explanation TEXT;
                """
            )
            cursor.execute(
                """
                ALTER TABLE matching_history ADD COLUMN IF NOT EXISTS reasoning_json JSONB;
                """
            )
            cursor.execute(
                """
                ALTER TABLE matching_history ADD COLUMN IF NOT EXISTS score_breakdown_json JSONB;
                """
            )
            rj = Json(reasoning_json) if reasoning_json is not None else None
            sb = Json(score_breakdown_json) if score_breakdown_json is not None else None
            cursor.execute(
                """
                INSERT INTO matching_history
                (user_id, job_id, match_score, relevance_score,
                 feasibility_score, growth_score, final_score, explanation, reasoning_json, score_breakdown_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    job_id,
                    scores.get("match_score"),
                    scores.get("relevance"),
                    scores.get("feasibility"),
                    scores.get("growth"),
                    scores.get("final_score"),
                    explanation,
                    rj,
                    sb,
                ),
            )

            conn.commit()
            cursor.close()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Save matching result failed: {e}")
            return False
    
    def get_matching_history(self, user_id: str, limit: int = 50) -> List[Dict]:
        """Get matching history"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT * FROM matching_history 
                WHERE user_id = %s 
                ORDER BY matched_at DESC 
                LIMIT %s
            """, (user_id, limit))
            
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Get matching history failed: {e}")
            return []
    
    def log_user_action(
        self,
        user_id: str,
        job_id: str,
        action_type: str,
        action_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Log user action"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO user_actions (user_id, job_id, action_type, action_data)
                VALUES (%s, %s, %s, %s)
            """, (user_id, job_id, action_type, json.dumps(action_data) if action_data else None))
            
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Log user action failed: {e}")
            return False
