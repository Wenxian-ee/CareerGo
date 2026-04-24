"""
General utility functions
"""

import numpy as np
from typing import Dict, List, Optional, Set, Tuple
import math


def jaccard_similarity(set1: Set, set2: Set) -> float:
    """
    Calculate Jaccard similarity
    """
    if not set1 or not set2:
        return 0.0
    
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    
    return intersection / union if union > 0 else 0.0


def cosine_similarity(vec1: Dict[str, float], vec2: Dict[str, float]) -> float:
    """
    Calculate cosine similarity (based on dictionary representation of vectors)
    """
    if not vec1 or not vec2:
        return 0.0
    
    # Get all keys
    all_keys = set(vec1.keys()) | set(vec2.keys())
    
    # Build vectors
    v1 = np.array([vec1.get(k, 0.0) for k in all_keys])
    v2 = np.array([vec2.get(k, 0.0) for k in all_keys])
    
    # Calculate cosine similarity
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
    
    return np.dot(v1, v2) / (norm1 * norm2)


def weighted_average(scores: List[float], weights: List[float]) -> float:
    """
    Calculate weighted average
    """
    if not scores or not weights or len(scores) != len(weights):
        return 0.0
    
    total_weight = sum(weights)
    if total_weight == 0:
        return 0.0
    
    return sum(s * w for s, w in zip(scores, weights)) / total_weight


def normalize_scores(scores: List[float], min_val: float = 0.0, max_val: float = 1.0) -> List[float]:
    """
    Normalize scores to specified range
    """
    if not scores:
        return []
    
    min_score = min(scores)
    max_score = max(scores)
    
    if min_score == max_score:
        return [min_val] * len(scores)
    
    return [
        min_val + (score - min_score) * (max_val - min_val) / (max_score - min_score)
        for score in scores
    ]


def sigmoid(x: float, k: float = 1.0, x0: float = 0.0) -> float:
    """
    Sigmoid function, for smooth transition
    k: steepness parameter
    x0: center point
    """
    return 1.0 / (1.0 + math.exp(-k * (x - x0)))


def calculate_skill_overlap(user_skills: Set[str], job_skills: Set[str]) -> Tuple[float, float, float]:
    """
    Calculate skill overlap
    Returns: (coverage, match rate, Jaccard similarity)
    - Coverage: the proportion of user skills covering the job requirements
    - Match rate: the proportion of user skills in the job requirements
    - Jaccard similarity: overall similarity
    """
    if not job_skills:
        return 1.0, 1.0, 1.0
    
    if not user_skills:
        return 0.0, 0.0, 0.0
    
    intersection = user_skills & job_skills
    
    coverage = len(intersection) / len(job_skills)  # user skills cover the job requirements
    match_rate = len(intersection) / len(user_skills) if user_skills else 0.0  # match rate of user skills
    jaccard = jaccard_similarity(user_skills, job_skills)
    
    return coverage, match_rate, jaccard


def calculate_weighted_skill_match(
    user_skills: Dict[str, float],
    job_skills: Dict[str, float]
) -> float:
    """
    Calculate weighted skill match
    Consider the importance of skills
    """
    if not job_skills:
        return 1.0
    
    if not user_skills:
        return 0.0
    
    total_weight = sum(job_skills.values())
    if total_weight == 0:
        return 0.0
    
    matched_weight = 0.0
    for skill, job_weight in job_skills.items():
        if skill in user_skills:
            # user skills level * job requirements weight
            matched_weight += min(user_skills[skill], 1.0) * job_weight
    
    return matched_weight / total_weight


def pareto_dominance(scores1: List[float], scores2: List[float]) -> int:
    """
    Pareto dominance relationship judgment
    Returns: 1 if scores1 dominates scores2, -1 if scores2 dominates scores1, 0 if not comparable
    """
    if len(scores1) != len(scores2):
        raise ValueError("Score list length must be the same")
    
    better = False
    worse = False
    
    for s1, s2 in zip(scores1, scores2):
        if s1 > s2:
            better = True
        elif s1 < s2:
            worse = True
    
    if better and not worse:
        return 1
    elif worse and not better:
        return -1
    else:
        return 0


def calculate_diversity_penalty(
    selected_jobs: List[Dict],
    candidate_job: Dict,
    diversity_features: Optional[List[str]] = None,
) -> float:
    """
    Calculate diversity penalty
    Avoid recommending too similar jobs
    """
    if not selected_jobs:
        return 0.0
    
    if diversity_features is None:
        diversity_features = ['company', 'industry', 'position_type']
    
    similarity_scores = []
    for job in selected_jobs:
        same_features = sum(
            1 for feature in diversity_features
            if job.get(feature) == candidate_job.get(feature)
        )
        similarity_scores.append(same_features / len(diversity_features))
    
    # Return maximum similarity as penalty
    return max(similarity_scores) if similarity_scores else 0.0


def exponential_decay(value: float, decay_rate: float = 0.1, threshold: float = 0.0) -> float:
    """
    Exponential decay function
    Used for decay of distance, time, etc.
    """
    return math.exp(-decay_rate * max(0, value - threshold))


def linear_interpolation(x: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """
    Linear interpolation
    """
    if x2 == x1:
        return y1
    
    return y1 + (x - x1) * (y2 - y1) / (x2 - x1)


def calculate_percentile_rank(value: float, values: List[float]) -> float:
    """
    Calculate percentile rank
    """
    if not values:
        return 0.5
    
    count_below = sum(1 for v in values if v < value)
    count_equal = sum(1 for v in values if v == value)
    
    return (count_below + 0.5 * count_equal) / len(values)

