"""
Multi-objective ranking system
Based on relevance, feasibility, and growth
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from user_profile import UserProfile
from utils import (
    weighted_average,
    normalize_scores,
    pareto_dominance,
    calculate_diversity_penalty,
    sigmoid
)


class MultiObjectiveRanker:
    """Multi-objective ranker"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize ranker
        config: configuration parameters
        """
        self.config = config or self._default_config()
    
    def _default_config(self) -> Dict:
        """Default configuration"""
        return {
            'relevance_weight': 0.4,      # Relevance weight
            'feasibility_weight': 0.35,   # Feasibility weight
            'growth_weight': 0.25,        # Growth weight
            'relevance_component_weights': {
                "match_alignment": 0.45,
                "skill_alignment": 0.30,
                "preference_alignment": 0.15,
                "industry_alignment": 0.10,
            },
            'feasibility_component_weights': {
                "skill_readiness": 0.30,
                "experience_fit": 0.20,
                "education_fit": 0.15,
                "salary_attainability": 0.15,
                "location_commute_fit": 0.10,
                "market_competition_adjustment": 0.10,
            },
            'growth_component_weights': {
                "skill_growth_potential": 0.35,
                "salary_growth_potential": 0.25,
                "career_ladder_signal": 0.20,
                "market_future_signal": 0.20,
            },
            'diversity_factor': 0.1,      # Diversity factor
            # Optional: trim pre-ranked pool before diversity (inner work is O(stop_after * pool))
            'diversity_candidate_cap': 2000,
            'use_pareto': False,          # Whether to use Pareto sorting
            'calibration_enabled': True   # Whether to enable calibration
        }
    
    def rank(
        self, 
        user_profile: UserProfile,
        matched_jobs: List[Tuple[Dict, float, Dict]],
        top_k: int = 20
    ) -> List[Dict]:
        """
        Multi-objective ranking for matched jobs
        matched_jobs: [(job, match_score, details), ...]
        Returns: ranked job list
        """
        if not matched_jobs:
            return []
        
        # Calculate three objective scores
        ranked_jobs = []
        for job, match_score, details in matched_jobs:
            relevance, relevance_breakdown = self._calculate_relevance(user_profile, job, match_score, details)
            feasibility, feasibility_breakdown = self._calculate_feasibility(user_profile, job, details)
            growth, growth_breakdown = self._calculate_growth_potential(user_profile, job)
            
            ranked_jobs.append({
                'job': job,
                'match_score': match_score,
                'details': details,
                'relevance': relevance,
                'feasibility': feasibility,
                'growth': growth,
                'relevance_breakdown': relevance_breakdown,
                'feasibility_breakdown': feasibility_breakdown,
                'growth_breakdown': growth_breakdown,
                'objectives': [relevance, feasibility, growth]
            })
        
        # Select ranking method based on configuration
        if self.config['use_pareto']:
            ranked_jobs = self._pareto_ranking(ranked_jobs)
        else:
            ranked_jobs = self._weighted_ranking(ranked_jobs)

        # Diversity greedy is O(n * stop_after); matcher can return thousands of rows — only build top_k.
        if self.config['diversity_factor'] > 0:
            cap = int(self.config.get('diversity_candidate_cap', 2000))
            if cap > 0 and len(ranked_jobs) > cap:
                ranked_jobs = ranked_jobs[:cap]

        if self.config['diversity_factor'] > 0:
            ranked_jobs = self._apply_diversity(ranked_jobs, stop_after=top_k)
        
        # Calibrate
        if self.config['calibration_enabled']:
            ranked_jobs = self._calibrate_rankings(user_profile, ranked_jobs)
        
        return ranked_jobs[:top_k]
    
    @staticmethod
    def _safe_score(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            score = float(value)
        except (TypeError, ValueError):
            return None
        if np.isnan(score):
            return None
        return max(0.0, min(1.0, score))

    @staticmethod
    def _score_weighted_with_missing(
        components: List[Tuple[str, Optional[float], float]]
    ) -> Tuple[float, Dict[str, Any]]:
        valid = []
        missing = []
        for name, value, weight in components:
            if value is None:
                missing.append(name)
            else:
                valid.append((name, value, weight))

        if not valid:
            return 0.5, {
                "components": {name: {"value": None, "effective_weight": 0.0} for name, _, _ in components},
                "missing": missing,
                "normalization_note": "all_components_missing_fallback_0.5",
            }

        total_weight = sum(weight for _, _, weight in valid)
        weighted_sum = sum(value * weight for _, value, weight in valid)
        score = weighted_sum / total_weight if total_weight > 0 else 0.5

        component_payload: Dict[str, Dict[str, Any]] = {}
        for name, value, weight in components:
            if value is None or total_weight <= 0:
                component_payload[name] = {"value": value, "effective_weight": 0.0}
            else:
                component_payload[name] = {
                    "value": value,
                    "effective_weight": weight / total_weight,
                }

        return max(0.0, min(1.0, score)), {
            "components": component_payload,
            "missing": missing,
        }

    def _calculate_relevance(
        self, 
        user_profile: UserProfile, 
        job: Dict,
        match_score: float,
        details: Dict
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calculate relevance score
        Based on skill matching, experience matching, preference matching
        """
        base_relevance = self._safe_score(match_score)
        skill_score = self._safe_score(details.get('skill_score'))

        preference_score: Optional[float] = None
        if user_profile.preferences:
            preference_score = self._safe_score(details.get('preference_score'))

        industry_match: Optional[float] = None
        if user_profile.constraints.industries:
            industry_match = 0.35
            job_industry = str(job.get('industry') or "").strip().lower()
            for wanted in user_profile.constraints.industries:
                wanted_norm = str(wanted or "").strip().lower()
                if wanted_norm and job_industry and (
                    wanted_norm in job_industry or job_industry in wanted_norm
                ):
                    industry_match = 1.0
                    break

        w = self.config.get("relevance_component_weights", {})
        relevance, breakdown = self._score_weighted_with_missing(
            [
                ("match_alignment", base_relevance, float(w.get("match_alignment", 0.45))),
                ("skill_alignment", skill_score, float(w.get("skill_alignment", 0.30))),
                ("preference_alignment", preference_score, float(w.get("preference_alignment", 0.15))),
                ("industry_alignment", industry_match, float(w.get("industry_alignment", 0.10))),
            ]
        )
        return relevance, breakdown
    
    def _calculate_feasibility(
        self,
        user_profile: UserProfile,
        job: Dict,
        details: Dict
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calculate feasibility score
        Consider the possibility of the user obtaining this job
        """
        skill_readiness = self._safe_score(details.get('skill_score'))
        experience_fit = self._safe_score(details.get('experience_score'))
        education_fit = self._safe_score(details.get('education_score'))
        location_fit = self._safe_score(details.get('location_score'))

        salary_attainability: Optional[float] = None
        job_salary = job.get('salary')
        min_salary = user_profile.constraints.min_salary
        max_salary = user_profile.constraints.max_salary
        if job_salary is not None:
            try:
                js = float(job_salary)
                if min_salary is not None and max_salary is not None and max_salary > min_salary:
                    if min_salary <= js <= max_salary:
                        salary_attainability = 1.0
                    elif js < min_salary:
                        salary_attainability = max(0.25, js / min_salary)
                    else:
                        overflow_ratio = (js - max_salary) / max(max_salary, 1e-6)
                        salary_attainability = max(0.35, 1.0 - min(overflow_ratio, 1.0) * 0.65)
                elif min_salary is not None and min_salary > 0:
                    salary_attainability = min(1.0, sigmoid((js / min_salary) - 1.0, k=2.0, x0=0.0))
                elif max_salary is not None and max_salary > 0:
                    salary_attainability = max(0.35, 1.0 - min(js / max_salary, 2.0) * 0.3)
            except (TypeError, ValueError):
                salary_attainability = None

        competition_adjustment: Optional[float] = None
        competition_level = self._safe_score(job.get('competition_level'))
        if competition_level is not None:
            competition_adjustment = max(0.2, 1.0 - 0.7 * competition_level)

        w = self.config.get("feasibility_component_weights", {})
        feasibility, breakdown = self._score_weighted_with_missing(
            [
                ("skill_readiness", skill_readiness, float(w.get("skill_readiness", 0.30))),
                ("experience_fit", experience_fit, float(w.get("experience_fit", 0.20))),
                ("education_fit", education_fit, float(w.get("education_fit", 0.15))),
                ("salary_attainability", salary_attainability, float(w.get("salary_attainability", 0.15))),
                ("location_commute_fit", location_fit, float(w.get("location_commute_fit", 0.10))),
                ("market_competition_adjustment", competition_adjustment, float(w.get("market_competition_adjustment", 0.10))),
            ]
        )
        return feasibility, breakdown
    
    def _calculate_growth_potential(
        self,
        user_profile: UserProfile,
        job: Dict
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calculate growth potential score
        Evaluate the value of this job to the user's career development
        """
        job_skills = set(skill.lower() for skill in job.get('required_skills', []))
        user_skills = user_profile.get_skill_set()
        new_skills = job_skills - user_skills

        skill_growth_potential: Optional[float] = None
        if job_skills:
            novelty_count = min(1.0, len(new_skills) * 0.12)
            novelty_ratio = min(1.0, len(new_skills) / max(1, len(job_skills)))
            skill_growth_potential = 0.7 * novelty_count + 0.3 * novelty_ratio

        salary_growth_potential: Optional[float] = None
        job_salary = job.get('salary')
        if job_salary and user_profile.constraints.min_salary:
            try:
                salary_ratio = float(job_salary) / max(float(user_profile.constraints.min_salary), 1e-6)
                salary_growth_potential = min(1.0, sigmoid(salary_ratio - 1, k=2.2, x0=0.15))
            except (TypeError, ValueError):
                salary_growth_potential = None

        career_ladder_signal = self._safe_score(job.get('title_seniority_level'))
        if career_ladder_signal is None:
            title_text = str(job.get("title") or "").lower()
            if any(k in title_text for k in ("intern", "junior", "graduate", "trainee")):
                career_ladder_signal = 0.85
            elif any(k in title_text for k in ("senior", "lead", "manager", "director", "principal")):
                career_ladder_signal = 0.4
            else:
                career_ladder_signal = 0.65

        market_future_signal: Optional[float] = None
        trend_text = " ".join(
            str(job.get(k) or "").lower()
            for k in ("title", "category", "subcategory", "industry")
        )
        demand_hits = sum(
            1
            for kw in (
                "ai", "machine learning", "data", "cloud", "security", "platform",
                "backend", "software", "analytics", "product",
            )
            if kw in trend_text
        )
        demand_score = min(1.0, 0.45 + demand_hits * 0.08)
        freshness = 0.6
        days_since_posted = job.get("days_since_posted")
        if isinstance(days_since_posted, (int, float)):
            dsp = float(days_since_posted)
            if dsp <= 7:
                freshness = 0.9
            elif dsp <= 21:
                freshness = 0.75
            elif dsp <= 45:
                freshness = 0.6
            else:
                freshness = 0.45
        market_future_signal = 0.6 * demand_score + 0.4 * freshness

        w = self.config.get("growth_component_weights", {})
        growth, breakdown = self._score_weighted_with_missing(
            [
                ("skill_growth_potential", skill_growth_potential, float(w.get("skill_growth_potential", 0.35))),
                ("salary_growth_potential", salary_growth_potential, float(w.get("salary_growth_potential", 0.25))),
                ("career_ladder_signal", career_ladder_signal, float(w.get("career_ladder_signal", 0.20))),
                ("market_future_signal", market_future_signal, float(w.get("market_future_signal", 0.20))),
            ]
        )
        return growth, breakdown
    
    def _weighted_ranking(self, jobs: List[Dict]) -> List[Dict]:
        """Weighted ranking method"""
        for job_info in jobs:
            # Calculate comprehensive score
            final_score = (
                job_info['relevance'] * self.config['relevance_weight'] +
                job_info['feasibility'] * self.config['feasibility_weight'] +
                job_info['growth'] * self.config['growth_weight']
            )
            job_info['final_score'] = final_score
        
        # Sort by comprehensive score
        jobs.sort(key=lambda x: x['final_score'], reverse=True)
        
        return jobs
    
    def _pareto_ranking(self, jobs: List[Dict]) -> List[Dict]:
        """Pareto ranking method"""
        # Implement Pareto frontier sorting
        remaining = jobs.copy()
        ranked = []
        rank = 1
        
        while remaining:
            # Find current Pareto frontier
            pareto_front = []
            dominated = []
            
            for i, job1 in enumerate(remaining):
                is_dominated = False
                for j, job2 in enumerate(remaining):
                    if i != j:
                        if pareto_dominance(job2['objectives'], job1['objectives']) == 1:
                            is_dominated = True
                            break
                
                if not is_dominated:
                    pareto_front.append(job1)
                else:
                    dominated.append(job1)
            
            # Assign ranking to current frontier
            for job in pareto_front:
                job['pareto_rank'] = rank
                job['final_score'] = 1.0 / rank  # Convert to score
            
            ranked.extend(pareto_front)
            remaining = dominated
            rank += 1
        
        return ranked
    
    def _apply_diversity(
        self, jobs: List[Dict], stop_after: Optional[int] = None
    ) -> List[Dict]:
        """Greedy diversity reordering. If ``stop_after`` is set (e.g. ``top_k``), stop once that many are chosen."""
        if len(jobs) <= 1:
            return jobs

        limit = stop_after if stop_after is not None else len(jobs)
        limit = max(1, min(int(limit), len(jobs)))

        selected = [jobs[0]]  # First one directly selected
        remaining = jobs[1:]

        diversity_features = ['company', 'industry', 'position_type']

        while remaining and len(selected) < limit:
            # Calculate diversity penalty for each candidate
            for job_info in remaining:
                penalty = calculate_diversity_penalty(
                    [j['job'] for j in selected],
                    job_info['job'],
                    diversity_features
                )
                # Adjust score
                job_info['diversity_adjusted_score'] = (
                    job_info['final_score'] * (1 - self.config['diversity_factor'] * penalty)
                )
            
            # Select the highest score after adjustment
            remaining.sort(key=lambda x: x['diversity_adjusted_score'], reverse=True)
            selected.append(remaining[0])
            remaining = remaining[1:]
        
        return selected
    
    def _calibrate_rankings(self, user_profile: UserProfile, jobs: List[Dict]) -> List[Dict]:
        """
        Calibrate rankings
        Based on user history, market feedback, etc.
        """
        # Here we implement simple calibration logic
        # In practice, it can be based on user feedback, click rate, etc.
        
        for i, job_info in enumerate(jobs):
            job = job_info['job']
            
            # 1. Position bias calibration (jobs at the front may be over-emphasised).
            position_bias = 1.0 - (i * 0.01)  # Slightly reduce the weight of the front position
            
            # 2. Popular job calibration
            if job.get('view_count', 0) > 1000:
                # Popular jobs may already be competitive
                popularity_penalty = 0.95
            else:
                popularity_penalty = 1.0
            
            # 3. Freshness calibration
            days_posted = job.get('days_since_posted', 0)
            if days_posted > 30:
                freshness_penalty = 0.9  # Jobs posted for too long may not be active
            else:
                freshness_penalty = 1.0
            
            # Apply calibration
            calibrated_score = (
                job_info['final_score'] * 
                position_bias * 
                popularity_penalty * 
                freshness_penalty
            )
            
            job_info['calibrated_score'] = calibrated_score
            job_info['final_score'] = calibrated_score
        
        # Re-sort
        jobs.sort(key=lambda x: x['final_score'], reverse=True)
        
        return jobs
    
    def explain_ranking(self, job_info: Dict) -> str:
        """Generate ranking explanation"""
        explanations = []
        
        relevance = job_info['relevance']
        feasibility = job_info['feasibility']
        growth = job_info['growth']
        
        # Relevance explanation
        if relevance >= 0.8:
            explanations.append(f"Highly relevant ({relevance:.0%})")
        elif relevance >= 0.6:
            explanations.append(f"Moderately relevant ({relevance:.0%})")
        else:
            explanations.append(f"Partially relevant ({relevance:.0%})")

        # Feasibility explanation
        if feasibility >= 0.8:
            explanations.append(f"Strong chance of landing this role ({feasibility:.0%})")
        elif feasibility >= 0.6:
            explanations.append(f"Some chance of landing this role ({feasibility:.0%})")
        else:
            explanations.append(f"Competitive / difficult to land ({feasibility:.0%})")

        # Growth explanation
        if growth >= 0.8:
            explanations.append(f"High growth potential ({growth:.0%})")
        elif growth >= 0.6:
            explanations.append(f"Some growth opportunities ({growth:.0%})")
        else:
            explanations.append(f"Limited growth potential ({growth:.0%})")
        
        return " | ".join(explanations)
    
    def get_ranking_summary(self, ranked_jobs: List[Dict]) -> Dict:
        """Get ranking summary statistics"""
        if not ranked_jobs:
            return {}
        
        relevance_scores = [j['relevance'] for j in ranked_jobs]
        feasibility_scores = [j['feasibility'] for j in ranked_jobs]
        growth_scores = [j['growth'] for j in ranked_jobs]
        
        return {
            'total_jobs': len(ranked_jobs),
            'avg_relevance': np.mean(relevance_scores),
            'avg_feasibility': np.mean(feasibility_scores),
            'avg_growth': np.mean(growth_scores),
            'top_relevance': max(relevance_scores),
            'top_feasibility': max(feasibility_scores),
            'top_growth': max(growth_scores),
            'score_distribution': {
                'high_quality': sum(1 for j in ranked_jobs if j['final_score'] >= 0.8),
                'medium_quality': sum(1 for j in ranked_jobs if 0.6 <= j['final_score'] < 0.8),
                'low_quality': sum(1 for j in ranked_jobs if j['final_score'] < 0.6)
            }
        }

