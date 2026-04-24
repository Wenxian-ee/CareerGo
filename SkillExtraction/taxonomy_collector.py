"""
Skill taxonomy data collector
Collect ESCO and O*NET standard skill taxonomy data and build mapping database

ESCO data download: https://esco.ec.europa.eu/en/use-esco/download
Required files:
- skills_en.csv (required) - all skill information

O*NET data download: https://www.onetcenter.org/database.html
Required files (from O*NET Database compressed package):
- Skills.txt (required) - skill definition (note: many tables in O*NET database are "by occupation score")
- Knowledge.txt (required) - knowledge domain
- Abilities.txt (required) - ability definition
- Technology Skills.txt (recommended) - technical skills
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from config import DB_CONFIG, DATA_DIR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TaxonomyCollector:
    """
    Skill taxonomy data collector
    Support ESCO and O*NET two standard classification systems
    """

    def __init__(self, db_config: Dict = None):
        self.db_config = db_config or DB_CONFIG
        self.data_dir = Path(DATA_DIR)
        self.init_database()

    def init_database(self):
        """Initialize database tables"""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()

            # ESCO skills table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS esco_skills (
                    id SERIAL PRIMARY KEY,
                    skill_uri VARCHAR(500) UNIQUE,
                    skill_code VARCHAR(100),
                    preferred_label TEXT NOT NULL,
                    alternative_labels TEXT[],
                    description TEXT,
                    skill_type VARCHAR(50),
                    skill_reuse_level VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    raw_data JSONB
                )
                """
            )

            # O*NET skills table (current design: store "element table taxonomy", not by occupation score)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS onet_skills (
                    id SERIAL PRIMARY KEY,
                    element_id VARCHAR(100) UNIQUE,
                    element_name TEXT NOT NULL,
                    description TEXT,
                    category VARCHAR(100),
                    scale_id VARCHAR(50),
                    data_value DECIMAL(10, 2),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    raw_data JSONB
                )
                """
            )

            # Skill mapping table (ESCO <-> O*NET)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_mappings (
                    id SERIAL PRIMARY KEY,
                    esco_skill_id INTEGER REFERENCES esco_skills(id),
                    onet_skill_id INTEGER REFERENCES onet_skills(id),
                    similarity_score DECIMAL(5, 4),
                    mapping_method VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(esco_skill_id, onet_skill_id)
                )
                """
            )

            # Standardized skills table (unified skill library)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS normalized_skills (
                    id SERIAL PRIMARY KEY,
                    skill_name TEXT NOT NULL,
                    skill_category VARCHAR(100),
                    skill_level VARCHAR(50),
                    synonyms TEXT[],
                    esco_skill_id INTEGER REFERENCES esco_skills(id),
                    onet_skill_id INTEGER REFERENCES onet_skills(id),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(skill_name)
                )
                """
            )

            # Index
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_esco_preferred_label
                ON esco_skills(preferred_label)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_onet_element_name
                ON onet_skills(element_name)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_normalized_skill_name
                ON normalized_skills(skill_name)
                """
            )

            conn.commit()
            cursor.close()
            conn.close()
            logger.info("Database tables initialized successfully")
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
            raise

    # -----------------------------
    # ESCO
    # -----------------------------
    def collect_esco_skills(self, limit: int = None) -> List[Dict]:
        logger.info("Start collecting ESCO skills data...")
        skills = self._load_esco_from_csv()
        if skills and limit:
            skills = skills[:limit]
        logger.info(f"Successfully collected {len(skills)} ESCO skills")
        return skills

    def _load_esco_from_csv(self) -> List[Dict]:
        """
        Load ESCO skills_en.csv from local CSV file
        """
        skills_file = self.data_dir / "skills_en.csv"

        if not skills_file.exists():
            logger.warning(f"ESCO skills file not found: {skills_file}")
            logger.info("=" * 80)
            logger.info("Please follow the steps to get ESCO data:")
            logger.info("1. Visit: https://esco.ec.europa.eu/en/use-esco/download")
            logger.info("2. Download 'ESCO dataset - classification - en - csv.zip'")
            logger.info("3. Unzip and put 'skills_en.csv' file into data/ directory")
            logger.info("=" * 80)
            return self._get_sample_esco_skills()

        try:
            logger.info(f"Load ESCO skills from file: {skills_file}")

            # ✅ Key: read all as strings, and don't convert empty values to NaN
            df = pd.read_csv(skills_file, dtype=str, keep_default_na=False)

            logger.info(f"CSV file contains {len(df)} rows")
            logger.info(f"CSV columns: {list(df.columns)}")

            skills: List[Dict] = []
            skipped_no_uri = 0

            for idx, row in df.iterrows():
                # Common columns in ESCO skills_en.csv:
                # conceptUri, conceptType, preferredLabel, altLabels, description, skillType, reuseLevel, code(may not have)

                uri = (row.get("conceptUri") or "").strip()
                if not uri:
                    skipped_no_uri += 1
                    continue

                # altLabels may be separated by newline
                alt_labels: List[str] = []
                alt_raw = (row.get("altLabels") or "").strip()
                if alt_raw:
                    alt_labels = [x.strip() for x in alt_raw.split("\n") if x.strip()]

                preferred = (row.get("preferredLabel") or "").strip()
                desc = (row.get("description") or "").strip()

                skill = {
                    "uri": uri,
                    "code": (row.get("code") or "").strip(),
                    "preferredLabel": {"en": preferred},
                    "altLabels": {"en": alt_labels},
                    "description": {"en": desc},
                    "skillType": (row.get("skillType") or "").strip(),
                    "reuseLevel": (row.get("reuseLevel") or "").strip(),
                }
                skills.append(skill)

                if (idx + 1) % 1000 == 0:
                    logger.info(f"Processed {idx + 1} records...")

            logger.info(f"Successfully loaded {len(skills)} ESCO skills from CSV file; skipped without uri: {skipped_no_uri}")
            return skills

        except Exception as e:
            logger.error(f"Error loading ESCO CSV file: {e}")
            logger.info("Use sample data instead")
            return self._get_sample_esco_skills()

    def _get_sample_esco_skills(self) -> List[Dict]:
        sample_skills = [
            {
                "uri": "http://data.europa.eu/esco/skill/S1.1.1",
                "code": "S1.1.1",
                "preferredLabel": {"en": "Python programming"},
                "altLabels": {"en": ["Python", "Python coding", "Python development"]},
                "description": {"en": "Programming in Python language"},
                "skillType": "skill/competence",
                "reuseLevel": "cross-sectoral",
            },
            {
                "uri": "http://data.europa.eu/esco/skill/S1.1.2",
                "code": "S1.1.2",
                "preferredLabel": {"en": "Java programming"},
                "altLabels": {"en": ["Java", "Java coding", "Java development"]},
                "description": {"en": "Programming in Java language"},
                "skillType": "skill/competence",
                "reuseLevel": "cross-sectoral",
            },
        ]
        logger.info(f"Use sample data: {len(sample_skills)} ESCO skills")
        return sample_skills

    def save_esco_skills(self, skills: List[Dict]):
        """Save ESCO skills to database (fixed: duplicate skill_uri in the same batch)"""
        if not skills:
            logger.warning("No ESCO skills to save")
            return

        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()

            insert_query = """
                INSERT INTO esco_skills
                (skill_uri, skill_code, preferred_label, alternative_labels,
                 description, skill_type, skill_reuse_level, raw_data)
                VALUES %s
                ON CONFLICT (skill_uri) DO UPDATE SET
                    skill_code = EXCLUDED.skill_code,
                    preferred_label = EXCLUDED.preferred_label,
                    alternative_labels = EXCLUDED.alternative_labels,
                    description = EXCLUDED.description,
                    skill_type = EXCLUDED.skill_type,
                    skill_reuse_level = EXCLUDED.skill_reuse_level,
                    raw_data = EXCLUDED.raw_data
            """

            # ✅ Key: deduplicate before inserting, avoid ON CONFLICT "update the same row twice"
            dedup: Dict[str, tuple] = {}
            skipped = 0

            for skill in skills:
                uri = skill.get("uri")
                uri = "" if uri is None else str(uri).strip()
                if not uri or uri.lower() == "nan":
                    skipped += 1
                    continue

                preferred_label = skill.get("preferredLabel", {})
                if isinstance(preferred_label, dict):
                    preferred_label = preferred_label.get("en", "")
                preferred_label = "" if preferred_label is None else str(preferred_label).strip()

                alt_labels = skill.get("altLabels", {})
                if isinstance(alt_labels, dict):
                    alt_labels = alt_labels.get("en", [])
                if alt_labels is None:
                    alt_labels = []
                alt_labels = [str(x).strip() for x in alt_labels if str(x).strip()]

                description = skill.get("description", {})
                if isinstance(description, dict):
                    description = description.get("en", "")
                description = "" if description is None else str(description).strip()

                row_tuple = (
                    uri,
                    ("" if skill.get("code") is None else str(skill.get("code")).strip()),
                    preferred_label,
                    alt_labels,
                    description,
                    ("" if skill.get("skillType") is None else str(skill.get("skillType")).strip()),
                    ("" if skill.get("reuseLevel") is None else str(skill.get("reuseLevel")).strip()),
                    json.dumps(skill, ensure_ascii=False),
                )

                # Last-write-wins within the same batch. Swap in a "richest
                # record wins" rule here if you prefer.
                dedup[uri] = row_tuple

            values = list(dedup.values())
            logger.info(f"ESCO before insertion: {len(skills)} skills; after deduplication: {len(values)} skills; skipped without uri: {skipped} skills")

            if values:
                execute_values(cursor, insert_query, values, page_size=1000)
                conn.commit()
                logger.info(f"Successfully saved {len(values)} ESCO skills to database")

            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Error saving ESCO skills: {e}")
            raise

    # -----------------------------
    # O*NET
    # -----------------------------
    def collect_onet_skills(self) -> List[Dict]:
        logger.info("Start collecting O*NET skills data...")

        all_skills: List[Dict] = []

        onet_files = {
            "Skills": "Skills.txt",
            "Knowledge": "Knowledge.txt",
            "Abilities": "Abilities.txt",
            "Technology Skills": "Technology Skills.txt",
        }

        for category, filename in onet_files.items():
            skills = self._load_onet_from_file(filename, category)
            all_skills.extend(skills)

        if not all_skills:
            logger.info("No O*NET file found, use sample data")
            all_skills = self._get_sample_onet_skills()

        logger.info(f"Successfully collected {len(all_skills)} O*NET skills")
        return all_skills

    def _load_onet_from_file(self, filename: str, category: str) -> List[Dict]:
        file_path = self.data_dir / filename
        if not file_path.exists():
            logger.debug(f"O*NET file not found: {file_path}")
            return []

        try:
            logger.info(f"Load O*NET {category} from file: {file_path}")

            # Read every column as a string to avoid NaN / type coercion noise.
            df = pd.read_csv(file_path, sep="\t", dtype=str, keep_default_na=False, encoding="utf-8")

            logger.info(f"File contains {len(df)} rows")
            logger.info(f"Columns: {list(df.columns)}")

            skills: List[Dict] = []
            for _, row in df.iterrows():
                element_id = (row.get("Element ID") or "").strip()
                element_name = (row.get("Element Name") or "").strip()
                description = (row.get("Description") or "").strip()

                scale_id = (row.get("Scale ID") or "").strip()
                data_value_raw = (row.get("Data Value") or "").strip()
                try:
                    data_value = float(data_value_raw) if data_value_raw else 0.0
                except ValueError:
                    data_value = 0.0

                skill = {
                    "element_id": element_id,
                    "element_name": element_name,
                    "description": description,
                    "category": category,
                    "scale_id": scale_id,
                    "data_value": data_value,
                }
                skills.append(skill)

            logger.info(f"Successfully loaded {len(skills)} {category} O*NET skills")
            return skills

        except Exception as e:
            logger.error(f"Error loading O*NET file ({filename}): {e}")
            return []

    def _get_sample_onet_skills(self) -> List[Dict]:
        logger.warning("=" * 80)
        logger.warning("Please follow the steps to get O*NET data:")
        logger.warning("1. Visit: https://www.onetcenter.org/database.html")
        logger.warning("2. Download 'O*NET Database' (db_XX_X_text.zip)")
        logger.warning("3. Unzip and put the following files into data/ directory:")
        logger.warning("   - Skills.txt")
        logger.warning("   - Knowledge.txt")
        logger.warning("   - Abilities.txt (optional)")
        logger.warning("   - Technology Skills.txt (optional)")
        logger.warning("=" * 80)

        sample_skills = [
            {
                "element_id": "2.B.1.a",
                "element_name": "Programming",
                "description": "Writing computer programs for various purposes",
                "category": "Skills",
                "scale_id": "IM",
                "data_value": 4.5,
            },
            {
                "element_id": "1.A.1.a.1",
                "element_name": "Deductive Reasoning",
                "description": "The ability to apply general rules to specific problems",
                "category": "Abilities",
                "scale_id": "IM",
                "data_value": 4.3,
            },
        ]

        logger.info(f"Use sample data: {len(sample_skills)} O*NET skills")
        return sample_skills

    def save_onet_skills(self, skills: List[Dict]):
        """Save O*NET skills to database (deduplicate before inserting by element_id)"""
        if not skills:
            logger.warning("No O*NET skills to save")
            return

        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()

            insert_query = """
                INSERT INTO onet_skills
                (element_id, element_name, description, category,
                 scale_id, data_value, raw_data)
                VALUES %s
                ON CONFLICT (element_id) DO UPDATE SET
                    element_name = EXCLUDED.element_name,
                    description = EXCLUDED.description,
                    category = EXCLUDED.category,
                    scale_id = EXCLUDED.scale_id,
                    data_value = EXCLUDED.data_value,
                    raw_data = EXCLUDED.raw_data
            """

            # Key: current table structure only allows element_id to be unique
            # So must deduplicate before inserting, otherwise the same batch of execute_values will trigger "second time"
            dedup: Dict[str, Dict] = {}
            skipped = 0
            for s in skills:
                eid = (s.get("element_id") or "").strip()
                if not eid or eid.lower() == "nan":
                    skipped += 1
                    continue
                # Either first- or last-write-wins is fine; we pick the row
                # with the longer description so we preserve more information.
                if eid not in dedup:
                    dedup[eid] = s
                else:
                    if len((s.get("description") or "")) > len((dedup[eid].get("description") or "")):
                        dedup[eid] = s
            uniq = list(dedup.values())
            logger.info(f"O*NET before insertion: {len(skills)} skills; after deduplication: {len(uniq)} skills; skipped without element_id: {skipped} skills")

            values = []
            for skill in uniq:
                values.append(
                    (
                        (skill.get("element_id") or "").strip(),
                        (skill.get("element_name") or "").strip(),
                        (skill.get("description") or "").strip(),
                        (skill.get("category") or "").strip(),
                        (skill.get("scale_id") or "").strip(),
                        float(skill.get("data_value") or 0.0),
                        json.dumps(skill, ensure_ascii=False),
                    )
                )

            if values:
                execute_values(cursor, insert_query, values, page_size=1000)
                conn.commit()
                logger.info(f"Successfully saved {len(values)} O*NET skills to database")

            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Error saving O*NET skills: {e}")
            raise

    # -----------------------------
    # Pipeline
    # ----------------------------- Integration
    def collect_all(self):
        logger.info("=" * 80)
        logger.info("Start collecting skill taxonomy data...")
        logger.info("=" * 80)

        # ESCO
        esco_skills = self.collect_esco_skills()
        if esco_skills:
            self.save_esco_skills(esco_skills)

        # O*NET
        onet_skills = self.collect_onet_skills()
        if onet_skills:
            self.save_onet_skills(onet_skills)

        logger.info("=" * 80)
        logger.info("Skill taxonomy data collection completed")
        logger.info(f"ESCO skills: {len(esco_skills)}")
        logger.info(f"O*NET skills: {len(onet_skills)}")
        logger.info("=" * 80)


def main():
    collector = TaxonomyCollector()
    collector.collect_all()


if __name__ == "__main__":
    main()
