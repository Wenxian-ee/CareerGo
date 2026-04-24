"""
Matching algorithm
Based on skill overlap and multi-dimensional features
"""

from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np
from user_profile import UserProfile, Constraints
from utils import (
    jaccard_similarity, 
    cosine_similarity,
    calculate_skill_overlap,
    calculate_weighted_skill_match,
    sigmoid,
    exponential_decay
)


class JobMatcher:
    """Job matcher"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize matcher
        config: configuration parameters
        """
        self.config = config or self._default_config()
    
    def _default_config(self) -> Dict:
        """Default configuration"""
        return {
            'skill_weight': 0.4,           # Skill matching weight
            'education_weight': 0.15,      # Education matching weight
            'experience_weight': 0.15,     # Experience matching weight
            'preference_weight': 0.15,     # Preference matching weight
            'salary_weight': 0.10,         # Salary matching weight
            'location_weight': 0.05,       # Location matching weight
            'min_skill_coverage': 0.5,     # Minimum skill coverage
            'skill_proficiency_factor': 0.3  # Skill proficiency factor
        }
    
    def match(self, user_profile: UserProfile, jobs: List[Dict]) -> List[Tuple[Dict, float, Dict]]:
        """
        Match user and job list
        Returns: [(job, score, details), ...]
        """
        results = []
        
        for job in jobs:
            # First check hard constraints
            if not user_profile.constraints.is_satisfied(job):
                continue
            
            # Calculate match score
            score, details = self.calculate_match_score(user_profile, job)
            
            # Filter low score jobs
            if score >= self.config.get('min_match_score', 0.3):
                results.append((job, score, details))
        
        # Sort by score
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results
    
    def calculate_match_score(self, user_profile: UserProfile, job: Dict) -> Tuple[float, Dict]:
        """
        Calculate match score
        return: (total score, specific score dictionary)
        """
        details = {}
        
        # 1. skill matching
        skill_score = self._calculate_skill_match(user_profile, job)
        details['skill_score'] = skill_score
        
        # 2. Education matching
        education_score = self._calculate_education_match(user_profile, job)
        details['education_score'] = education_score
        
        # 3. Work experience matching
        experience_score = self._calculate_experience_match(user_profile, job)
        details['experience_score'] = experience_score
        
        # 4. Preference matching
        preference_score = self._calculate_preference_match(user_profile, job)
        details['preference_score'] = preference_score
        
        # 5. Constraints matching
        salary_score = self._calculate_salary_match(user_profile, job)
        details['salary_score'] = salary_score
        
        # 6. Location matching
        
        location_score = self._calculate_location_match(user_profile, job)
        details['location_score'] = location_score
        
        # Calculate weighted total score
        total_score = (
            skill_score * self.config['skill_weight'] +
            education_score * self.config['education_weight'] +
            experience_score * self.config['experience_weight'] +
            preference_score * self.config['preference_weight'] +
            salary_score * self.config['salary_weight'] +
            location_score * self.config['location_weight']
        )
        
        details['total_score'] = total_score
        
        return total_score, details
    
    def _calculate_skill_match(self, user_profile: UserProfile, job: Dict) -> float:
        """Calculate skill match score"""
        job_skills = job.get('required_skills', [])
        if not job_skills:
            return 0.5  # If the job has no skill requirements, give medium score
        
        # Convert to lowercase set
        job_skill_set = {skill.lower() for skill in job_skills}
        user_skill_set = user_profile.get_skill_set()
        
        # Basic skill overlap
        coverage, match_rate, jaccard = calculate_skill_overlap(user_skill_set, job_skill_set)
        
        # Consider weighted skill match based on skill proficiency
        user_weighted_skills = user_profile.get_weighted_skills()
        job_weighted_skills = {skill.lower(): 1.0 for skill in job_skills}
        
        # If the job has skill weight information
        if 'skill_weights' in job:
            job_weighted_skills = {
                skill.lower(): weight 
                for skill, weight in job['skill_weights'].items()
            }
        
        weighted_match = calculate_weighted_skill_match(user_weighted_skills, job_weighted_skills)
        
        # Overall score: coverage is most important, weighted match is second
        skill_score = (
            coverage * 0.5 +           # Required skill coverage
            weighted_match * 0.3 +     # Weighted skill match
            jaccard * 0.2              # Overall similarity
        )
        
        # If coverage is below threshold, apply penalty
        if coverage < self.config['min_skill_coverage']:
            penalty = (self.config['min_skill_coverage'] - coverage) * 0.5
            skill_score = max(0, skill_score - penalty)
        
        return min(1.0, skill_score)
    
    def _calculate_education_match(self, user_profile: UserProfile, job: Dict) -> float:
        """Calculate education background match score"""
        required_education = job.get('required_education')
        if not required_education:
            return 1.0  # No requirement — full score
        
        highest_edu = user_profile.get_highest_education()
        if not highest_edu:
            return 0.3  # If there is no education information, give low score
        
        # Education level mapping — keys match EducationLevel enum values (English)
        level_map = {
            'High School': 1, 'Associate': 2, 'Bachelor': 3, 'Master': 4, 'PhD': 5
        }

        def _edu_level_int(text: str) -> int:
            """Normalise a raw education string from the DB to an integer level."""
            # First try an exact match against known enum values
            exact = level_map.get(text, None)
            if exact is not None:
                return exact
            t = (text or "").strip().lower()
            if any(k in t for k in ("phd", "doctor")):
                return 5
            if any(k in t for k in ("master", "msc", "m.sc")):
                return 4
            if any(k in t for k in ("bachelor", "undergraduate", "bsc", "b.sc")):
                return 3
            if any(k in t for k in ("associate", "diploma")):
                return 2
            if "high school" in t:
                return 1
            return 0

        user_level = level_map.get(highest_edu.level.value, 0)
        required_level = _edu_level_int(required_education)
        
        # Education match
        if user_level >= required_level:
            education_score = 1.0
        else:
            # Education below requirement — penalise proportionally to the gap
            education_score = max(0.3, user_level / required_level)
        
        # Major match bonus
        if 'preferred_majors' in job:
            if highest_edu.major in job['preferred_majors']:
                education_score = min(1.0, education_score * 1.2)
        
        # GPA bonus
        if highest_edu.gpa and highest_edu.gpa >= 3.5:
            education_score = min(1.0, education_score * 1.1)
        
        # School ranking bonus
        if highest_edu.ranking in ['985', '211', 'QS Top 100']:
            education_score = min(1.0, education_score * 1.15)
        
        return education_score
    
    def _calculate_experience_match(self, user_profile: UserProfile, job: Dict) -> float:
        """Calculate work experience match score"""
        required_years = job.get('required_experience_years', 0)
        user_years = user_profile.get_total_experience_years()
        
        if required_years == 0:
            return 1.0  # No requirement — full score
        
        # Use sigmoid function to smooth match
        # When experience is just right, the score is highest, too much or too little will reduce the score
        if user_years >= required_years:
            # Experience enough
            if user_years <= required_years * 1.5:
                experience_score = 1.0
            else:
                # Experience overqualified, apply penalty
                excess = user_years - required_years * 1.5
                experience_score = 1.0 - sigmoid(excess, k=0.3, x0=2.0) * 0.3
        else:
            # Experience less than required, apply penalty
            ratio = user_years / required_years
            experience_score = sigmoid(ratio, k=5.0, x0=0.7)
        
        # Related industry experience bonus
        if 'preferred_industries' in job:
            for exp in user_profile.work_experience:
                # Here we simplify the processing, in reality, there should be industry mapping
                if any(ind in exp.company for ind in job['preferred_industries']):
                    experience_score = min(1.0, experience_score * 1.2)
                    break
        
        return experience_score
    
    def _calculate_preference_match(self, user_profile: UserProfile, job: Dict) -> float:
        """Calculate preference match score"""
        if not user_profile.preferences:
            return 0.5  # If there is no preference information, give medium score
        
        preference_scores = []
        total_weight = 0.0
        
        for pref in user_profile.preferences:
            weight = pref.weight
            total_weight += weight
            
            # Match based on preference type
            if pref.preference_type.value == "Industry":
                if job.get('industry') == pref.value:
                    preference_scores.append(1.0 * weight)
                else:
                    preference_scores.append(0.3 * weight)
            
            elif pref.preference_type.value == "Company Size":
                if job.get('company_size') == pref.value:
                    preference_scores.append(1.0 * weight)
                else:
                    preference_scores.append(0.5 * weight)
            
            elif pref.preference_type.value == "Work-Life Balance":
                work_life_score = job.get('work_life_balance_score', 0.5)
                preference_scores.append(work_life_score * weight)
            
            elif pref.preference_type.value == "Career Growth":
                growth_score = job.get('career_growth_score', 0.5)
                preference_scores.append(growth_score * weight)
            
            elif pref.preference_type.value == "Innovation":
                innovation_score = job.get('innovation_score', 0.5)
                preference_scores.append(innovation_score * weight)
            
            else:
                preference_scores.append(0.5 * weight)
        
        if total_weight == 0:
            return 0.5
        
        return sum(preference_scores) / total_weight
    
    def _calculate_salary_match(self, user_profile: UserProfile, job: Dict) -> float:
        """Calculate salary match score"""
        job_salary = job.get('salary')
        if not job_salary:
            return 0.5  # If there is no salary information, give medium score
        
        constraints = user_profile.constraints
        
        # In expected range
        if constraints.min_salary and constraints.max_salary:
            if constraints.min_salary <= job_salary <= constraints.max_salary:
                # The closer to the maximum expectation, the better
                ratio = (job_salary - constraints.min_salary) / (constraints.max_salary - constraints.min_salary)
                return 0.7 + 0.3 * ratio
            elif job_salary > constraints.max_salary:
                # Exceeding the expected upper limit, still a good thing
                return 1.0
            else:
                # Below the minimum requirement (should not happen, because hard constraints have been filtered)
                return 0.3
        
        elif constraints.min_salary:
            if job_salary >= constraints.min_salary:
                # The more it exceeds the minimum requirement, the better, but there is a limit
                excess_ratio = (job_salary - constraints.min_salary) / constraints.min_salary
                return min(1.0, 0.7 + 0.3 * sigmoid(excess_ratio, k=2.0))
            else:
                return 0.3
        
        return 0.5
    
    def _calculate_location_match(self, user_profile: UserProfile, job: Dict) -> float:
        """Calculate location match score"""
        job_location = job.get('location')
        if not job_location:
            return 0.5
        
        preferred_locations = user_profile.constraints.locations
        if not preferred_locations:
            return 1.0  # No preference — full score
        
        # Perfect match
        if job_location in preferred_locations:
            return 1.0
        
        # Partial match (e.g. Beijing-Chaoyang vs Beijing)
        for loc in preferred_locations:
            if loc in job_location or job_location in loc:
                return 0.8
        
        # Not matched (should not happen, because hard constraints have been filtered)
        return 0.3
    
    def batch_match_with_explanation(
        self, 
        user_profile: UserProfile, 
        jobs: List[Dict],
        top_k: int = 10
    ) -> List[Dict]:
        """
        Batch match and generate explanation
        Returns detailed matching results
        """
        matches = self.match(user_profile, jobs)
        
        results = []
        for job, score, details in matches[:top_k]:
            result = {
                'job': job,
                'match_score': score,
                'details': details,
                'explanation': self._generate_explanation(user_profile, job, details)
            }
            results.append(result)
        
        return results
    
    def _generate_explanation(self, user_profile: UserProfile, job: Dict, details: Dict) -> str:
        """Generate matching explanation"""
        explanations = []
        
        # Skill matching
        skill_score = details.get('skill_score', 0)
        if skill_score >= 0.8:
            explanations.append(f"Your skills are a strong match for the job requirements ({skill_score:.0%})")
        elif skill_score >= 0.6:
            explanations.append(f"Your skills broadly cover the job requirements ({skill_score:.0%})")
        else:
            explanations.append(f"Your skills partially match the job requirements ({skill_score:.0%}); you may need to learn new skills")
        
        # Education background
        edu_score = details.get('education_score', 0)
        if edu_score >= 0.9:
            explanations.append("Your education background fully meets the requirements")
        
        # Work experience
        exp_score = details.get('experience_score', 0)
        if exp_score >= 0.8:
            explanations.append("Your work experience is very matched")
        elif exp_score < 0.5:
            explanations.append("This job may need more related experience")
        
        # Salary
        salary_score = details.get('salary_score', 0)
        if salary_score >= 0.8:
            explanations.append("Salary meets your expectations")
        
        return ";".join(explanations)

