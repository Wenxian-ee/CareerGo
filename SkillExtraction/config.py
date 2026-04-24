"""
Configuration file for SkillExtraction module
Contains configuration parameters for all modules
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root (silently skip if not found)
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", override=False)

# Base paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
MODELS_DIR = BASE_DIR / "models"
LOGS_DIR = BASE_DIR / "logs"

# Local model paths
LOCAL_BERT_NER_PATH = str(MODELS_DIR / "bert-base-NER")

# Create necessary directories
for dir_path in [DATA_DIR, MODELS_DIR, LOGS_DIR]:
    dir_path.mkdir(exist_ok=True)

# Database configuration
DB_CONFIG = {
    'host': os.environ.get("DB_HOST", "localhost"),
    'port': int(os.environ.get("DB_PORT", "5432")),
    'database': os.environ.get("DB_NAME", "jobs_data"),
    'user': os.environ.get("DB_USER", "fyp"),
    'password': os.environ.get("DB_PASSWORD", "fyp"),
}

# Table names used by the skill-extraction pipeline. The `_3` suffix isolates
# this run from legacy tables; override via environment variables to run other
# versions side-by-side.
MERGED_JOBS_TABLE = os.environ.get("MERGED_JOBS_TABLE", "merged_jobs_3")
EXTRACTED_JOB_SKILLS_TABLE = os.environ.get("EXTRACTED_JOB_SKILLS_TABLE", "extracted_job_skills_3")
NORMALIZED_JOB_SKILLS_TABLE = os.environ.get("NORMALIZED_JOB_SKILLS_TABLE", "normalized_job_skills_3")

# ESCO API configuration
ESCO_API_BASE = "https://ec.europa.eu/esco/api"
ESCO_VERSION = "v1.1.0"
ESCO_LANGUAGE = "en"

# O*NET configuration (kept but not used in main pipeline)
ONET_DATA_URL = "https://www.onetcenter.org/dl_files/database/db_28_0_text/"
ONET_FILES = {
    'skills': 'Skills.txt',
    'knowledge': 'Knowledge.txt',
    'abilities': 'Abilities.txt',
    'work_activities': 'Work Activities.txt',
    'technology_skills': 'Technology Skills.txt'
}

# Model configuration
MODEL_CONFIG = {
    # Pretrained NER model (recommended, no training needed) 
    'pretrained_ner': {
        'model_name': LOCAL_BERT_NER_PATH,  # Load NER model from local
        'max_length': 512,
        'batch_size': 16,
        'use_pretrained': True,  # Mark as using pretrained model
        'description': 'BERT model specifically trained for NER tasks, F1 score reaches 91%, no training needed'
    },
    
    # Alternative: Multilingual NER model
    'multilingual_ner': {
        'model_name': 'Davlan/bert-base-multilingual-cased-ner-hrl',
        'max_length': 512,
        'batch_size': 16,
        'use_pretrained': True,
        'description': 'NER model supporting multiple languages, suitable for mixed English and Chinese scenarios'
    },
    
    # BERT model (if training is needed)
    'bert': {
        'model_name': 'bert-base-uncased',
        'max_length': 512,
        'batch_size': 16,
        'learning_rate': 2e-5,
        'num_epochs': 3,
        'warmup_steps': 500,
        'use_pretrained': False,
    },
    
    # Qwen3 model (if training is needed)
    'qwen3': {
        'model_name': 'Qwen/Qwen2.5-7B-Instruct',
        'max_length': 2048,
        'batch_size': 8,
        'learning_rate': 1e-5,
        'num_epochs': 3,
        'use_lora': True,  # Use LoRA fine-tuning
        'lora_r': 8,
        'lora_alpha': 16,
        'use_pretrained': False,
    },
    
    # SentenceTransformer configuration.
    # The model path can either be a local directory (default: ./models/all-MiniLM-L6-v2)
    # or a HuggingFace Hub identifier (e.g. "sentence-transformers/all-MiniLM-L6-v2").
    'sentence_transformer': {
        'model_name': os.environ.get(
            "SENTENCE_TRANSFORMER_MODEL",
            str(MODELS_DIR / "all-MiniLM-L6-v2"),
        ),
        # Default fallback; real threshold comes from NORMALIZATION_CONFIG.embedding_threshold
        # (consumed by skill_normalizer).
        'similarity_threshold': 0.52,
        'top_k': 5,
    }
}

# Pretrained NER model label mapping
# Map pretrained model labels to our skill types
PRETRAINED_NER_LABEL_MAPPING = {
    'MISC': 'SKILL',  # Miscellaneous entities are usually skills
    'ORG': 'TOOL',    # Organization names are probably tools/platforms
    'PER': 'O',       # Person names are not our concern
    'LOC': 'O',       # Locations are not our concern
    'O': 'O',         # Non-entity
}

# NER label configuration (for custom training)
NER_LABELS = [
    'O',           # Outside
    'B-SKILL',     # Begin-Skill
    'I-SKILL',     # Inside-Skill
    'B-TOOL',      # Begin-Tool
    'I-TOOL',      # Inside-Tool
    'B-CERT',      # Begin-Certification
    'I-CERT',      # Inside-Certification
    'B-QUAL',      # Begin-Qualification
    'I-QUAL',      # Inside-Qualification
]

# Logging configuration
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        },
    },
    'handlers': {
        'file': {
            'class': 'logging.FileHandler',
            'filename': str(LOGS_DIR / 'skill_extraction.log'),
            'formatter': 'standard',
        },
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'root': {
        'handlers': ['file', 'console'],
        'level': 'INFO',
    },
}

# Skill normalization configuration
NORMALIZATION_CONFIG = {
    'use_esco_only': True,  # Only use ESCO, not O*NET
    'use_fuzzy_matching': True,
    # Fuzzy only runs on embedding top-N candidates (full 100k scan is unusably slow)
    'fuzzy_max_candidates': 500,
    'fuzzy_threshold': 78,
    'use_embedding': True,
    'embedding_threshold': 0.68,
    'use_llm': False,  # Whether to use LLM for matching (optional)
    'llm_model': 'gpt-3.5-turbo',  # LLM model name
    'best_effort_embedding': False,
    'best_effort_min_sim': 0.5,
    # Disable: When no ESCO hit, do not write the original text into the normalized result (cleaner, recall will decrease)
    'allow_raw_unmapped': False,
    'raw_unmapped_min_len': 5,
}

# Data processing configuration
PROCESSING_CONFIG = {
    'min_skill_length': 2,  # Minimum skill length
    'max_skill_length': 50,  # Maximum skill length
    'remove_stopwords': True,
    'lowercase': True,
}
