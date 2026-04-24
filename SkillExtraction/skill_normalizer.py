"""
Skill normalization module
Use Sentence-Transformer for embedding similarity matching
Map extracted skills to ESCO/O*NET standard skill library
"""

import logging
from typing import List, Dict, Optional, Tuple
import numpy as np
import psycopg2
from sentence_transformers import SentenceTransformer
from fuzzywuzzy import fuzz
import torch

try:
    # When imported via repo root (e.g. `from SkillExtraction.skill_normalizer import ...`)
    from SkillExtraction.config import (
        DB_CONFIG,
        MODEL_CONFIG,
        NORMALIZATION_CONFIG,
        NORMALIZED_JOB_SKILLS_TABLE,
    )
except ModuleNotFoundError:
    # When running this file directly from `SkillExtraction/` directory
    from config import (
        DB_CONFIG,
        MODEL_CONFIG,
        NORMALIZATION_CONFIG,
        NORMALIZED_JOB_SKILLS_TABLE,
    )

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SkillNormalizer:
    """ 
    Skill normalization module
    Use Sentence-Transformer for embedding similarity matching
    Map extracted skills to ESCO/O*NET standard skill library
    """
    
    def __init__(self, db_config: Dict = None):
        self.db_config = db_config or DB_CONFIG
        self.config = NORMALIZATION_CONFIG
        
        # Sentence-Transformer configuration (cosine gate: NORMALIZATION_CONFIG.embedding_threshold overrides MODEL_CONFIG)
        self.st_config = MODEL_CONFIG['sentence_transformer']
        self.similarity_threshold = float(
            self.config.get("embedding_threshold", self.st_config["similarity_threshold"])
        )
        self.top_k = self.st_config['top_k']
        
        logger.info("=" * 80)
        logger.info("Initialize skill normalization module")
        logger.info("=" * 80)
        
        # Load Sentence-Transformer model
        self._load_embedding_model()
        
        # Load standard skill library from database
        self.standard_skills = self._load_standard_skills()
        
        # Precompute embeddings for standard skills
        self.skill_embeddings = self._precompute_embeddings()
        
        logger.info(f"Skill normalization module initialized, loaded {len(self.standard_skills)} standard skills")
        logger.info("=" * 80)
    
    def _load_embedding_model(self):
        """Load Sentence-Transformer model"""
        try:
            model_path = self.st_config['model_name']
            logger.info(f"Loading Sentence-Transformer model: {model_path}")

            # Force local loading (avoid online)
            self.embedding_model = SentenceTransformer(
                model_path,
                device='cuda' if torch.cuda.is_available() else 'cpu'
            )

            logger.info(
                f"Using device: {'GPU' if torch.cuda.is_available() else 'CPU'}"
            )

            logger.info("Sentence-Transformer model loaded successfully")

        except Exception as e:
            logger.error(f"Failed to load Sentence-Transformer model: {e}")
            raise
    
    def _load_standard_skills(self) -> List[Dict]:
        """Load standard skill library from database (ESCO and O*NET)"""
        skills = []
        
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Load ESCO skills
            if self.config.get('use_esco_only', True):
                logger.info("Loading ESCO skills from database...")
                cursor.execute("""
                    SELECT id, skill_uri, preferred_label, alternative_labels, 
                           description, skill_type
                    FROM esco_skills
                    WHERE preferred_label IS NOT NULL AND preferred_label != ''
                """)
                
                esco_rows = cursor.fetchall()
                logger.info(f"Loaded {len(esco_rows)} ESCO skills")
                
                for row in esco_rows:
                    skill_id, uri, label, alt_labels, desc, skill_type = row
                    
                    # Main label
                    skills.append({
                        'id': skill_id,
                        'name': label,
                        'source': 'ESCO',
                        'uri': uri,
                        'description': desc or '',
                        'skill_type': skill_type or '',
                        'is_alternative': False
                    })
                    
                    # Alternative labels
                    if alt_labels:
                        for alt_label in alt_labels:
                            if alt_label and alt_label.strip():
                                skills.append({
                                    'id': skill_id,
                                    'name': alt_label.strip(),
                                    'source': 'ESCO',
                                    'uri': uri,
                                    'description': desc or '',
                                    'skill_type': skill_type or '',
                                    'is_alternative': True
                                })
            
            # Load O*NET skills (if enabled)
            if not self.config.get('use_esco_only', True):
                logger.info("Loading O*NET skills from database...")
                cursor.execute("""
                    SELECT id, element_id, element_name, description, category
                    FROM onet_skills
                    WHERE element_name IS NOT NULL AND element_name != ''
                """)
                
                onet_rows = cursor.fetchall()
                logger.info(f"Loaded {len(onet_rows)} O*NET skills")
                
                for row in onet_rows:
                    skill_id, element_id, name, desc, category = row
                    skills.append({
                        'id': skill_id,
                        'name': name,
                        'source': 'ONET',
                        'element_id': element_id,
                        'description': desc or '',
                        'category': category or '',
                        'is_alternative': False
                    })
            
            cursor.close()
            conn.close()
            
            logger.info(f"Loaded {len(skills)} standard skills (including alternative labels)")
            
        except Exception as e:
            logger.error(f"Failed to load standard skills from database: {e}")
            logger.warning("Using empty skill library")
            skills = []
        
        return skills
    
    def _precompute_embeddings(self) -> np.ndarray:
        """Precompute embeddings for all standard skills"""
        if not self.standard_skills:
            logger.warning("No standard skills, cannot precompute embeddings")
            return np.array([])
        
        logger.info("Precomputing embeddings for standard skills...")
        
        # Extract all skill names
        skill_names = [skill['name'] for skill in self.standard_skills]
        
        # Batch compute embeddings
        try:
            embeddings = self.embedding_model.encode(
                skill_names,
                batch_size=32,
                show_progress_bar=True,
                convert_to_numpy=True
            )
            
            logger.info(f"Precomputation completed, embeddings shape: {embeddings.shape}")
            return embeddings
            
        except Exception as e:
            logger.error(f"Failed to precompute embeddings: {e}")
            return np.array([])
    
    def normalize_skill(self, skill_text: str, top_k: int = None) -> List[Dict]:
        """
        Normalize a single skill
        
        Args:
            skill_text: The skill text to normalize
            top_k: Return the top k most similar skills
        
        Returns:
            Matching results list, each result contains:
            - skill: Standard skill information
            - similarity: Similarity score
            - method: Matching method (embedding/fuzzy)
        """
        if not skill_text or not skill_text.strip():
            return []
        
        skill_text = skill_text.strip()
        top_k = top_k or self.top_k
        
        results = []
        similarities = None
        embedding_matches: List[Dict] = []

        # Method 1: Embedding similarity (single encode per skill_text)
        if self.config.get('use_embedding', True) and len(self.skill_embeddings) > 0:
            similarities = self._encode_and_similarities(skill_text)
            if similarities is not None:
                embedding_matches = self._matches_from_embedding_similarities(similarities, top_k)
                results.extend(embedding_matches)

        # Method 2: Fuzzy on embedding top-N only (never full 100k scan — too slow)
        if self.config.get('use_fuzzy_matching', True) and len(embedding_matches) < top_k:
            if similarities is not None:
                fuzzy_matches = self._match_by_fuzzy_candidates(skill_text, top_k, similarities)
                results.extend(fuzzy_matches)
            elif self.standard_skills:
                logger.warning(
                    "Fuzzy matching without precomputed embeddings: "
                    "set use_embedding True or disable use_fuzzy_matching"
                )

        # Best-effort: single highest cosine match if nothing passed strict/fuzzy gates
        if (
            not results
            and self.config.get("best_effort_embedding", True)
            and similarities is not None
            and len(self.standard_skills) > 0
        ):
            min_sim = float(self.config.get("best_effort_min_sim", 0.35))
            sims = np.asarray(similarities, dtype=np.float64)
            sims = np.nan_to_num(sims, nan=-1.0, posinf=1.0, neginf=-1.0)
            best_idx = int(np.argmax(sims))
            best_sim = float(sims[best_idx])
            if best_sim >= min_sim:
                results.append({
                    "skill": self.standard_skills[best_idx],
                    "similarity": best_sim,
                    "method": "embedding_best_effort",
                })

        # Merge and deduplicate results
        results = self._merge_results(results, top_k)

        return results

    def _encode_and_similarities(self, skill_text: str) -> Optional[np.ndarray]:
        """Cosine similarity between query embedding and all standard skill embeddings."""
        try:
            query_embedding = self.embedding_model.encode(
                [skill_text],
                show_progress_bar=False,
                convert_to_numpy=True,
            )[0]
            denom = (
                np.linalg.norm(self.skill_embeddings, axis=1) * np.linalg.norm(query_embedding)
            )
            similarities = np.dot(self.skill_embeddings, query_embedding) / denom
            return similarities
        except Exception as e:
            logger.error(f"Embedding encode/similarity failed: {e}")
            return None

    def _matches_from_embedding_similarities(
        self, similarities: np.ndarray, top_k: int
    ) -> List[Dict]:
        """Pick top embedding matches above similarity threshold."""
        try:
            top_indices = np.argsort(similarities)[::-1][: top_k * 2]
            matches = []
            for idx in top_indices:
                similarity = float(similarities[idx])
                if similarity >= self.similarity_threshold:
                    matches.append({
                        'skill': self.standard_skills[idx],
                        'similarity': similarity,
                        'method': 'embedding',
                    })
            return matches[:top_k]
        except Exception as e:
            logger.error(f"Embedding matching failed: {e}")
            return []

    def _match_by_embedding(self, skill_text: str, top_k: int) -> List[Dict]:
        """Use embedding similarity matching (one encode; for callers that need embedding-only)."""
        sims = self._encode_and_similarities(skill_text)
        if sims is None:
            return []
        return self._matches_from_embedding_similarities(sims, top_k)

    def _match_by_fuzzy_candidates(
        self, skill_text: str, top_k: int, similarities: np.ndarray
    ) -> List[Dict]:
        """Fuzzy match only within embedding-nearest candidates (not entire skill library)."""
        try:
            fuzzy_threshold = self.config.get('fuzzy_threshold', 80)
            max_cand = min(
                int(self.config.get('fuzzy_max_candidates', 500)),
                len(self.standard_skills),
            )
            top_indices = np.argsort(similarities)[::-1][:max_cand]
            st_lower = skill_text.lower()
            matches = []
            for idx in top_indices:
                skill = self.standard_skills[idx]
                ratio = fuzz.token_sort_ratio(st_lower, skill['name'].lower())
                if ratio >= fuzzy_threshold:
                    matches.append({
                        'skill': skill,
                        'similarity': ratio / 100.0,
                        'method': 'fuzzy',
                    })
            matches.sort(key=lambda x: x['similarity'], reverse=True)
            return matches[:top_k]
        except Exception as e:
            logger.error(f"Fuzzy matching failed: {e}")
            return []

    def _match_by_fuzzy(self, skill_text: str, top_k: int) -> List[Dict]:
        """Legacy full-library fuzzy scan — avoid; use _match_by_fuzzy_candidates."""
        try:
            fuzzy_threshold = self.config.get('fuzzy_threshold', 80)
            matches = []
            st_lower = skill_text.lower()
            for skill in self.standard_skills:
                ratio = fuzz.token_sort_ratio(st_lower, skill['name'].lower())
                if ratio >= fuzzy_threshold:
                    matches.append({
                        'skill': skill,
                        'similarity': ratio / 100.0,
                        'method': 'fuzzy',
                    })
            matches.sort(key=lambda x: x['similarity'], reverse=True)
            return matches[:top_k]
        except Exception as e:
            logger.error(f"Fuzzy matching failed: {e}")
            return []
    
    def _merge_results(self, results: List[Dict], top_k: int) -> List[Dict]:
        """Merge and deduplicate results"""
        # Deduplicate by skill ID, keep the highest similarity
        seen = {}
        for result in results:
            skill_id = result['skill']['id']
            skill_name = result['skill']['name']
            key = f"{skill_id}_{skill_name}"
            
            if key not in seen or result['similarity'] > seen[key]['similarity']:
                seen[key] = result
        
        # Convert to list and sort
        merged = list(seen.values())
        merged.sort(key=lambda x: x['similarity'], reverse=True)
        
        return merged[:top_k]
    
    def normalize_batch(self, skill_texts: List[str], top_k: int = None) -> List[List[Dict]]:
        """
        Batch normalize skills
        
        Args:
            skill_texts: The list of skill texts to normalize
            top_k: Return the top k most similar skills for each skill
        
        Returns:
            List of matching results for each skill
        """
        results = []
        total = len(skill_texts)
        
        for i, skill_text in enumerate(skill_texts):
            if (i + 1) % 100 == 0:
                logger.info(f"Normalization progress: {i + 1}/{total}")
            
            matches = self.normalize_skill(skill_text, top_k)
            results.append(matches)
        
        return results
    
    def get_best_match(self, skill_text: str) -> Optional[Dict]:
        """Get the best matching standard skill"""
        matches = self.normalize_skill(skill_text, top_k=1)
        return matches[0] if matches else None
    
    def save_normalized_skills(self, normalized_results: List[Dict]):
        """
        Save normalization results to database (job scenario).

        Expected structure for each item in normalized_results:
        {
            "job_id": "xxx",
            "raw_skill": "python",
            "matches": [...]
        }
        """
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()

            # Keep consistent with integrated_pipeline
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {NORMALIZED_JOB_SKILLS_TABLE} (
                    id SERIAL PRIMARY KEY,
                    job_id VARCHAR(255) NOT NULL,
                    raw_skill_text TEXT NOT NULL,
                    normalized_skill_name TEXT NOT NULL,
                    similarity_score DECIMAL(5, 4),
                    normalization_method VARCHAR(50),
                    esco_skill_id INTEGER REFERENCES esco_skills(id),
                    onet_skill_id INTEGER REFERENCES onet_skills(id),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(job_id, raw_skill_text, normalized_skill_name)
                )
            """)

            for result in normalized_results:
                job_id = str(result.get('job_id', '')).strip()
                raw_skill = result['raw_skill']
                matches = result['matches']

                if not job_id or not raw_skill or not matches:
                    continue

                # Get the best match
                best_match = matches[0]
                skill_info = best_match['skill']

                # Insert or update normalized_job_skills table
                if skill_info['source'] == 'ESCO':
                    cursor.execute(f"""
                        INSERT INTO {NORMALIZED_JOB_SKILLS_TABLE}
                        (job_id, raw_skill_text, normalized_skill_name, similarity_score,
                         normalization_method, esco_skill_id, onet_skill_id)
                        VALUES (%s, %s, %s, %s, %s, %s, NULL)
                        ON CONFLICT (job_id, raw_skill_text, normalized_skill_name) DO UPDATE SET
                            similarity_score = EXCLUDED.similarity_score,
                            normalization_method = EXCLUDED.normalization_method,
                            esco_skill_id = EXCLUDED.esco_skill_id,
                            onet_skill_id = EXCLUDED.onet_skill_id
                    """, (
                        job_id,
                        raw_skill,
                        skill_info['name'],
                        float(best_match.get('similarity', 0.0)),
                        best_match.get('method', ''),
                        skill_info['id']
                    ))
                elif skill_info['source'] == 'ONET':
                    cursor.execute(f"""
                        INSERT INTO {NORMALIZED_JOB_SKILLS_TABLE}
                        (job_id, raw_skill_text, normalized_skill_name, similarity_score,
                         normalization_method, esco_skill_id, onet_skill_id)
                        VALUES (%s, %s, %s, %s, %s, NULL, %s)
                        ON CONFLICT (job_id, raw_skill_text, normalized_skill_name) DO UPDATE SET
                            similarity_score = EXCLUDED.similarity_score,
                            normalization_method = EXCLUDED.normalization_method,
                            esco_skill_id = EXCLUDED.esco_skill_id,
                            onet_skill_id = EXCLUDED.onet_skill_id
                    """, (
                        job_id,
                        raw_skill,
                        skill_info['name'],
                        float(best_match.get('similarity', 0.0)),
                        best_match.get('method', ''),
                        skill_info['id']
                    ))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"Successfully saved {len(normalized_results)} job skills to database")
            
        except Exception as e:
            logger.error(f"Failed to save normalized skills: {e}")
            raise


if __name__ == "__main__":
    # Test skill normalizer
    logger.info("Test skill normalizer")
    
    normalizer = SkillNormalizer()
    
    # Test skills
    test_skills = [
        "Python programming",
        "Machine Learning",
        "Data Analytics",
        "Project Management",
        "SQL databases",
        "AWS cloud",
        "Docker containers",
        "JavaScript",
        "React framework",
        "Communication skills"
    ]
    
    print("\n" + "=" * 80)
    print("Skill normalization test")
    print("=" * 80)
    
    for skill in test_skills:
        print(f"\nOriginal skill: {skill}")
        matches = normalizer.normalize_skill(skill, top_k=3)
        
        if matches:
            print("  Matching results:")
            for i, match in enumerate(matches, 1):
                print(f"    {i}. {match['skill']['name']}")
                print(f"       Similarity: {match['similarity']:.3f}")
                print(f"       Method: {match['method']}")
                print(f"       Source: {match['skill']['source']}")
        else:
            print("  No matching found")
