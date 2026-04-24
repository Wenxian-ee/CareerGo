"""
Entity Extractor Pretrained
Uses pretrained models like dslim/bert-base-NER, no training required
Default only does "extraction", not ESCO/O*NET alignment (alignment should be done in the normalization stage)

Fixes:
- No hardcoded skill classification (e.g. programming languages, frameworks, etc.)
- Load all ESCO/O*NET skills from database, no manual classification
- Suitable for all industries, not limited to STEM subjects 
"""

import torch
from transformers import AutoTokenizer, AutoModelForTokenClassification, pipeline
import logging
from typing import List, Dict, Optional, Tuple
import re
import psycopg2

from config import MODEL_CONFIG, PRETRAINED_NER_LABEL_MAPPING, DB_CONFIG, LOCAL_BERT_NER_PATH

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PretrainedSkillExtractor:
    """
    Entity Extractor Pretrained
    Uses pretrained models like dslim/bert-base-NER, no training required
    Default only does "extraction", not ESCO/O*NET alignment (alignment should be done in the normalization stage)
    """
    
    def __init__(self, model_type: str = 'pretrained_ner', enable_keyword_enhance: bool = False):
        self.model_type = model_type
        self.config = MODEL_CONFIG.get(model_type, MODEL_CONFIG['pretrained_ner'])
        self.model_name = self.config['model_name']
        self.enable_keyword_enhance = enable_keyword_enhance
        
        logger.info("=" * 80)
        logger.info(f"Initializing pretrained NER model: {self.model_name}")
        logger.info("=" * 80)
        
        self.device = 0 if torch.cuda.is_available() else -1
        logger.info(f"Using device: {'GPU' if self.device == 0 else 'CPU'}")
        
        self._load_model()
        
        # Optional: keyword enhancement (default off, to avoid "standardization" in the extraction stage)
        if self.enable_keyword_enhance:
            self.skill_keywords = self._load_skill_keywords()
        else:
            self.skill_keywords = []
    
    def _load_model(self):
        """Load pretrained model from local (offline, not using HuggingFace)"""
        try:
            model_path = LOCAL_BERT_NER_PATH
            logger.info(f"Loading model from local: {model_path}")

            tokenizer = AutoTokenizer.from_pretrained(
                model_path,
                local_files_only=True
            )
            model = AutoModelForTokenClassification.from_pretrained(
                model_path,
                local_files_only=True
            )

            self.ner_pipeline = pipeline(
                "ner",
                model=model,
                tokenizer=tokenizer,
                aggregation_strategy="simple",
                device=self.device
            )

            logger.info("Local model loaded successfully!")

        except Exception as e:
            logger.error(f"Model loading failed: {e}")
            raise
    
    def _load_skill_keywords(self) -> List[str]:
        """
        Load the skill keyword vocabulary from the database (ESCO and O*NET).
        No manual classification, directly use all skills from database
        Suitable for all industries, not limited to STEM subjects
        """
        all_skills = []
        
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()
            
            # Load all skills from ESCO (no limit, no classification)
            logger.info("Loading ESCO skills keywords from database...")
            cursor.execute("""
                SELECT preferred_label, alternative_labels
                FROM esco_skills
                WHERE preferred_label IS NOT NULL AND preferred_label != ''
            """)
            
            esco_rows = cursor.fetchall()
            logger.info(f"Loaded {len(esco_rows)} ESCO skills")
            
            for row in esco_rows:
                label, alt_labels = row
                
                # Add main label
                if label and label.strip():
                    all_skills.append(label.strip())
                
                # Add alternative labels
                if alt_labels:
                    for alt in alt_labels:
                        if alt and alt.strip():
                            all_skills.append(alt.strip())
            
            # Load all skills from O*NET (if exists)
            try:
                cursor.execute("""
                    SELECT element_name
                    FROM onet_skills
                    WHERE element_name IS NOT NULL AND element_name != ''
                """)
                
                onet_rows = cursor.fetchall()
                logger.info(f"Loaded {len(onet_rows)} O*NET skills")
                
                for row in onet_rows:
                    name = row[0]
                    if name and name.strip():
                        all_skills.append(name.strip())
            except Exception as e:
                logger.debug(f"O*NET skills loading skipped: {e}")
            
            cursor.close()
            conn.close()
            
            # Deduplicate
            all_skills = list(set(all_skills))
            
            logger.info(f"Skill keywords loaded successfully:")
            logger.info(f"  - Total skills: {len(all_skills)}")
            logger.info(f"  - Covers all industries, not limited to STEM subjects")
            logger.info(f"  - No hardcoded classification")
            
            return all_skills
            
        except Exception as e:
            logger.error(f"Failed to load skill keywords from database: {e}")
            logger.warning("Database connection failed, will only rely on NER model extraction")
            
            # Return empty list, completely rely on NER model
            return []
    
    REQUIREMENT_HEADERS = [
        r"requirements?", r"qualifications?", r"essential", r"what you(?:'|’)ll need",
        r"what we(?:'|’)re looking for", r"skills?", r"experience", r"education",
        r"must have", r"required", r"you will need"
    ]
    EXCLUDE_HEADERS = [
        r"responsibilities?", r"duties", r"about (?:us|the role|the company)",
        r"benefits?", r"equal opportunity", r"how to apply", r"privacy", r"gdpr"
    ]

    REQUIREMENT_CUE_PATTERNS = [
        r"\bmust\b", r"\brequired\b", r"\bshould\b", r"\bneed to\b",
        r"\bexperience (?:in|with)\b", r"\bproficient in\b", r"\bfamiliar with\b",
        r"\bknowledge of\b", r"\bability to\b"
    ]

    BULLET_LINE = re.compile(r"^\s*(?:[-*•]|(\d+[\.\)]))\s+.+$")

    def extract_entities(self, text: str, enhance: bool = False, focus: str = "requirements") -> List[Dict]:
        """
        focus:
          - "requirements": Try to extract only from the "requirements" section (recommended default)
          - "all": Extract from the full text (legacy behaviour).
        """
        if not text or not text.strip():
            return []

        target_text = text
        if focus == "requirements":
            target_text = self._select_requirement_text(text) or text  # Fallback: if not selected, use all

        return self._extract_entities_from_target_text(target_text, enhance=enhance, focus=focus)

    def extract_entities_batch(
        self,
        texts: List[str],
        enhance: bool = False,
        focus: str = "requirements",
        ner_batch_size: int = 32,
    ) -> List[List[Dict]]:
        """
        Batch extraction for better GPU utilization.
        Returns one entity list per input text in the same order.
        """
        if not texts:
            return []

        prepared_texts: List[str] = []
        valid_flags: List[bool] = []
        for text in texts:
            if not text or not str(text).strip():
                prepared_texts.append("")
                valid_flags.append(False)
                continue
            target_text = str(text)
            if focus == "requirements":
                target_text = self._select_requirement_text(target_text) or target_text
            prepared_texts.append(target_text)
            valid_flags.append(True)

        try:
            ner_outputs = self.ner_pipeline(
                prepared_texts,
                batch_size=ner_batch_size,
            )
        except Exception as e:
            logger.error(f"Batch NER extraction error, fallback to single mode: {e}")
            return [
                self._extract_entities_from_target_text(t, enhance=enhance, focus=focus) if ok else []
                for t, ok in zip(prepared_texts, valid_flags)
            ]

        all_entities: List[List[Dict]] = []
        for target_text, ok, ner_results in zip(prepared_texts, valid_flags, ner_outputs):
            if not ok:
                all_entities.append([])
                continue
            entities = self._convert_ner_results(ner_results, focus=focus)
            if enhance and self.enable_keyword_enhance and self.skill_keywords:
                keyword_entities = self._extract_by_keywords(target_text)
                for ent in keyword_entities:
                    ent['focus'] = focus
                entities.extend(keyword_entities)
            all_entities.append(self._deduplicate_entities(entities))

        return all_entities

    def _extract_entities_from_target_text(self, target_text: str, enhance: bool, focus: str) -> List[Dict]:
        entities = []
        try:
            ner_results = self.ner_pipeline(target_text)
            entities.extend(self._convert_ner_results(ner_results, focus=focus))
        except Exception as e:
            logger.error(f"NER extraction error: {e}")

        if enhance and self.enable_keyword_enhance and self.skill_keywords:
            keyword_entities = self._extract_by_keywords(target_text)
            for ent in keyword_entities:
                ent['focus'] = focus
            entities.extend(keyword_entities)

        return self._deduplicate_entities(entities)

    def _convert_ner_results(self, ner_results: List[Dict], focus: str) -> List[Dict]:
        entities = []
        for entity in ner_results:
            original_label = entity['entity_group']
            mapped_type = PRETRAINED_NER_LABEL_MAPPING.get(original_label, 'SKILL')
            if mapped_type != 'O':
                entities.append({
                    'text': entity['word'].strip(),
                    'type': mapped_type,
                    'score': entity['score'],
                    'method': 'pretrained_ner',
                    'focus': focus
                })
        return entities

    def _select_requirement_text(self, text: str) -> str:
        """
        Try to extract "requirements" related sections from the "description":
        1) Extract by section titles first
        2) Otherwise filter sentences by cue/bullet
        """
        # Uniform newline, for line by line processing
        lines = [ln.rstrip() for ln in text.splitlines()]
        raw = "\n".join(lines)

        # --- A) Section splitting ---
        sections = self._split_into_sections(raw)
        # First find requirements-related sections
        picked = []
        for title, body in sections:
            t = (title or "").lower()
            if self._match_any(t, self.REQUIREMENT_HEADERS) and not self._match_any(t, self.EXCLUDE_HEADERS):
                if body.strip():
                    picked.append(body.strip())

        if picked:
            return "\n".join(picked)

        # --- B) No title: filter by "requirements cue + bullet" ---
        filtered_lines = []
        for ln in lines:
            ln_low = ln.lower()
            if self.BULLET_LINE.match(ln) or self._match_any(ln_low, self.REQUIREMENT_CUE_PATTERNS):
                if not re.search(r"\b(equal opportunity|gdpr|privacy|benefits?)\b", ln_low):
                    filtered_lines.append(ln)

        if not filtered_lines:
            sentences = re.split(r"(?<=[\.\?!])\s+", raw)
            for s in sentences:
                s_low = s.lower()
                if self._match_any(s_low, self.REQUIREMENT_CUE_PATTERNS):
                    filtered_lines.append(s.strip())

        return "\n".join(filtered_lines).strip()

    def _split_into_sections(self, text: str) -> List[Tuple[str, str]]:
        """
        Coarse-grained section splitter:
        Identify 'Requirements:' / 'Qualifications' as topic.
        """
        lines = text.splitlines()
        sections: List[Tuple[str, List[str]]] = []
        current_title = ""
        current_body: List[str] = []

        header_re = re.compile(r"^\s*([A-Za-z][A-Za-z\s/&\-]{2,40})\s*:?\s*$")

        def flush():
            nonlocal current_title, current_body
            if current_title or current_body:
                sections.append((current_title.strip(), "\n".join(current_body).strip()))
            current_title = ""
            current_body = []

        for ln in lines:
            m = header_re.match(ln)
            if m:
                # Encounter new title, flush old section
                flush()
                current_title = m.group(1)
            else:
                current_body.append(ln)

        flush()
        return sections

    def _match_any(self, text: str, patterns: List[str]) -> bool:
        for p in patterns:
            if re.search(p, text, flags=re.IGNORECASE):
                return True
        return False
    
    def _extract_by_keywords(self, text: str) -> List[Dict]:
        """
        Use skill keywords from database to match and extract entities
        No manual classification, all skills are treated uniformly
        """
        entities = []
        text_lower = text.lower()
        padded_text = f" {text_lower} "
        
        # Iterate through all skill keywords
        for skill in self.skill_keywords:
            skill_lower = skill.lower()
            # Fast pre-filter to avoid expensive regex on most keywords.
            if skill_lower not in text_lower:
                continue
            
            # Multi-word skills: substring is usually enough and much faster.
            if len(skill.split()) > 1:
                entities.append({
                    'text': skill,
                    'type': 'SKILL',
                    'score': 0.90,
                    'method': 'keyword_match_substring'
                })
                continue

            # Single-word skills: keep boundary-aware matching to reduce false positives.
            pattern = r'\b' + re.escape(skill_lower) + r'\b'
            if re.search(pattern, padded_text):
                entities.append({
                    'text': skill,
                    'type': 'SKILL',
                    'score': 0.95,
                    'method': 'keyword_match_exact'
                })
        
        return entities
    
    def _deduplicate_entities(self, entities: List[Dict]) -> List[Dict]:
        """Deduplicate entities"""
        seen = {}
        for entity in entities:
            text_lower = entity['text'].lower()
            if text_lower not in seen:
                seen[text_lower] = entity
            else:
                # Keep the higher score
                if entity['score'] > seen[text_lower]['score']:
                    seen[text_lower] = entity
        return list(seen.values())
    
    def extract_batch(self, texts: List[str], enhance: bool = False) -> List[List[Dict]]:
        """Batch extract entities"""
        results = []
        for i, text in enumerate(texts):
            if (i + 1) % 10 == 0:
                logger.info(f"Processing progress: {i + 1}/{len(texts)}")
            entities = self.extract_entities(text, enhance=enhance)
            results.append(entities)
        return results


if __name__ == "__main__":
    extractor = PretrainedSkillExtractor(model_type='pretrained_ner', enable_keyword_enhance=False)
    
    # Test multiple domain job descriptions
    test_texts = [
        # STEM
        """
        We are seeking a Python Developer with machine learning experience.
        The candidate should be proficient in SQL, AWS, and Docker.
        """,
        # Business
        """
        Looking for a Marketing Manager with strong communication skills.
        Experience in brand management, market research, and strategic planning required.
        """,
        # Healthcare
        """
        Seeking a Registered Nurse with patient care experience.
        Must have clinical assessment skills and knowledge of medical procedures.
        """,
        # Education
        """
        Elementary School Teacher needed with curriculum development experience.
        Strong classroom management and student engagement skills required.
        """
    ]
    
    print("\n" + "=" * 80)
    print("Test multi-domain skill extraction (no hardcoded classification)")
    print("=" * 80)
    
    for i, test_text in enumerate(test_texts, 1):
        print(f"\nTest {i}:")
        print(test_text.strip())
        print("-" * 80)
        
        entities = extractor.extract_entities(test_text, enhance=False)
        
        print(f"Extracted {len(entities)} entities:")
        for entity in entities:
            print(f"  - {entity['text']} ({entity['type']}) - score: {entity['score']:.3f} - method: {entity['method']}")
