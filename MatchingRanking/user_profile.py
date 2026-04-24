"""
User Profile Schema Definition
Defines user's education background, grades, skills, preferences and constraints
"""

from dataclasses import dataclass, field
from datetime import date, datetime
import re
from typing import List, Dict, Optional, Set
from enum import Enum


class EducationLevel(Enum):
    """Education level enumeration"""
    HIGH_SCHOOL = "High School"
    ASSOCIATE = "Associate"
    BACHELOR = "Bachelor"
    MASTER = "Master"
    PHD = "PhD"


class PreferenceType(Enum):
    """Preference type enumeration"""
    INDUSTRY = "Industry"
    COMPANY_SIZE = "Company Size"
    WORK_LIFE_BALANCE = "Work-Life Balance"
    CAREER_GROWTH = "Career Growth"
    INNOVATION = "Innovation"


@dataclass
class Education:
    """Education background"""
    level: EducationLevel
    major: str
    school: str
    graduation_year: int
    gpa: Optional[float] = None  # 0-4.0 scale
    ranking: Optional[str] = None  # School ranking (985/211/Regular, etc.)
    
    def to_dict(self) -> Dict:
        return {
            'level': self.level.value,
            'major': self.major,
            'school': self.school,
            'graduation_year': self.graduation_year,
            'gpa': self.gpa,
            'ranking': self.ranking
        }


@dataclass
class Skill:
    """Skill definition"""
    name: str
    proficiency: float  # 0-1, proficiency level
    years_of_experience: float  # Years of experience
    category: str  # Skill category (Programming Language/Framework/Tool, etc.)
    verified: bool = False  # Whether verified

    # ---- ESCO normalization metadata (optional) ----
    # When you normalize a user-entered skill to ESCO, we keep:
    # - `raw_name`: user input text (free-form)
    # - `name`: normalized skill label used for matching (default behavior)
    raw_name: Optional[str] = None
    esco_skill_id: Optional[int] = None
    similarity_score: Optional[float] = None
    normalization_method: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'raw_name': self.raw_name,
            'proficiency': self.proficiency,
            'years_of_experience': self.years_of_experience,
            'category': self.category,
            'verified': self.verified,
            'esco_skill_id': self.esco_skill_id,
            'similarity_score': self.similarity_score,
            'normalization_method': self.normalization_method,
        }


@dataclass
class Preference:
    """User preference"""
    preference_type: PreferenceType
    value: str
    weight: float = 1.0  # Weight 0-1
    
    def to_dict(self) -> Dict:
        return {
            'preference_type': self.preference_type.value,
            'value': self.value,
            'weight': self.weight
        }


@dataclass
class Constraints:
    """Hard constraints"""
    locations: List[str] = field(default_factory=list)  # Preferred work locations
    min_salary: Optional[float] = None  # Minimum salary requirement (10k/year)
    max_salary: Optional[float] = None  # Maximum salary expectation
    work_type: Optional[str] = None  # Work type (Full-time/Internship/Remote)
    start_date: Optional[str] = None  # Earliest start date
    industries: List[str] = field(default_factory=list)  # Preferred industries
    company_types: List[str] = field(default_factory=list)  # Company types (State-owned/Foreign/Private/Startup)
    exclude_companies: Set[str] = field(default_factory=set)  # Excluded companies
    max_commute_time: Optional[int] = None  # Maximum commute time in minutes

    @staticmethod
    def _norm_str(value: Optional[object]) -> str:
        """Normalize text for comparisons (case-insensitive, trim)."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip().lower()
        return str(value).strip().lower()
    
    def to_dict(self) -> Dict:
        return {
            'locations': self.locations,
            'min_salary': self.min_salary,
            'max_salary': self.max_salary,
            'work_type': self.work_type,
            'start_date': self.start_date,
            'industries': self.industries,
            'company_types': self.company_types,
            'exclude_companies': list(self.exclude_companies),
            'max_commute_time': self.max_commute_time
        }
    
    @staticmethod
    def _safe_float(value) -> Optional[float]:
        """Convert loosely-typed numeric input into float."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return None
            # Extract the first number in case value is like "£36,636" or "36k"
            m = re.search(r"[-+]?\d[\d,]*\.?\d*", s)
            if not m:
                return None
            return float(m.group(0).replace(",", ""))
        return None

    @staticmethod
    def _parse_date(value) -> Optional[date]:
        """Parse common date string formats into `date`."""
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return None
            # Try common formats: 2024-01-31 / 2024/01/31 / with time suffix
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
                try:
                    return datetime.strptime(s, fmt).date()
                except ValueError:
                    continue
        return None

    def is_satisfied(self, job: Dict) -> bool:
        """Check if job satisfies hard constraints"""
        # Location constraint. Loosened to partial match rather than exact match.
        if self.locations:
            job_location = job.get('location') or ""
            # Skip jobs whose location has no overlap with any preferred location.
            if job_location:
                if not any(
                    loc in job_location or job_location in loc
                    for loc in self.locations
                ):
                    return False
            # When the job has no location information, do not hard-filter.
        
        # Salary constraint
        # Job salary currently comes from crawlers and may have unit/currency mismatch with user input.
        # Here we enable it safely by trying common scaling factors and only filtering when we are confident.
        if self.min_salary is not None or self.max_salary is not None:
            job_salary = self._safe_float(job.get('salary'))
            if job_salary is None:
                # Missing salary info -> do not hard-filter.
                pass
            else:
                # Try multiple scales to mitigate unit mismatch (e.g. 36,000 vs 36).
                candidate_scales = [1.0, 1000.0, 10000.0]
                plausible_any_scale = False

                for scale in candidate_scales:
                    scaled_salary = job_salary / scale

                    # Plausibility gate: only consider scales that roughly align with user's magnitude.
                    plausible = True
                    if self.min_salary is not None and self.max_salary is not None:
                        plausible = (scaled_salary >= self.min_salary / 2.0) and (scaled_salary <= self.max_salary * 2.0)
                    elif self.min_salary is not None:
                        plausible = (scaled_salary >= self.min_salary / 2.0) and (scaled_salary <= self.min_salary * 2.0)
                    elif self.max_salary is not None:
                        plausible = (scaled_salary >= self.max_salary / 2.0) and (scaled_salary <= self.max_salary * 2.0)

                    if plausible:
                        plausible_any_scale = True

                    # Hard checks on (scaled) salary
                    if self.min_salary is not None and scaled_salary < self.min_salary:
                        continue
                    # `max_salary` is treated more cautiously (hard-filter only if it's *far* above)
                    if self.max_salary is not None and scaled_salary > self.max_salary * 3.0:
                        continue

                    # Satisfied under this scale.
                    return True

                # If we had at least one plausible scale and couldn't satisfy any, filter out.
                if plausible_any_scale:
                    return False
                # Otherwise, unit mismatch is likely -> do not hard-filter.
                pass

        # Work type constraint (best-effort hard filter; only active when job data exists)
        if self.work_type:
            expected = (self.work_type or "").strip().lower()
            actual = (job.get('work_type') or job.get('position_type') or job.get('job_type') or job.get('contract_type') or "").strip().lower()

            if actual:
                # Basic keyword matching with common variants.
                expected_is_remote = "remote" in expected
                expected_is_intern = "intern" in expected
                expected_is_full = "full" in expected
                expected_is_part = "part" in expected

                if expected_is_remote:
                    if "remote" not in actual:
                        return False
                elif expected_is_intern:
                    if "intern" not in actual:
                        return False
                elif expected_is_full:
                    if "full" not in actual:
                        return False
                elif expected_is_part:
                    if "part" not in actual:
                        return False
                else:
                    # Generic fallback: substring match or exact (case-insensitive) match.
                    if expected not in actual and actual not in expected:
                        return False
            # Missing field -> do not hard-filter.
        
        # Industry constraint (ignore missing or "Unknown" industry values).
        job_industry = job.get('industry')
        if self.industries and job_industry and self._norm_str(job_industry) != "unknown":
            allowed = {self._norm_str(x) for x in self.industries if x}

            job_industry_values: List[str]
            if isinstance(job_industry, list):
                job_industry_values = [self._norm_str(x) for x in job_industry if x]
            else:
                job_industry_values = [self._norm_str(job_industry)]

            matched = False
            for jv in job_industry_values:
                if not jv:
                    continue
                for a in allowed:
                    # Support partial matches (e.g. "Artificial Intelligence" vs "AI / Artificial Intelligence")
                    if a and (a in jv or jv in a):
                        matched = True
                        break
                if matched:
                    break
            if not matched:
                return False
        
        # Company type constraint. Only effective when the job exposes a company type.
        job_company_type = job.get('company_type')
        if self.company_types and job_company_type:
            allowed = {self._norm_str(x) for x in self.company_types if x}
            actual_values: List[str]
            if isinstance(job_company_type, list):
                actual_values = [self._norm_str(x) for x in job_company_type if x]
            else:
                actual_values = [self._norm_str(job_company_type)]

            matched = False
            for av in actual_values:
                if not av:
                    continue
                for a in allowed:
                    if a and (a in av or av in a):
                        matched = True
                        break
                if matched:
                    break
            if not matched:
                return False

        # Start date / commute constraints (optional; only active when job has compatible fields)
        if self.start_date:
            constraint_start = self._parse_date(self.start_date)
            job_start = self._parse_date(job.get('start_date') or job.get('posted_date') or job.get('published_date'))
            if constraint_start and job_start and job_start < constraint_start:
                return False

        if self.max_commute_time is not None:
            commute = self._safe_float(job.get('commute_time') or job.get('commute_minutes'))
            if commute is not None and commute > float(self.max_commute_time):
                return False
        
        # Excluded companies
        job_company_norm = self._norm_str(job.get('company'))
        if job_company_norm:
            exclude_norm = {self._norm_str(x) for x in self.exclude_companies if x}
            if job_company_norm in exclude_norm:
                return False
            # Partial match fallback (e.g. naming variations)
            if any(excl and (excl in job_company_norm or job_company_norm in excl) for excl in exclude_norm):
                return False
        # If job has no company info, don't hard-filter.
        
        return True


@dataclass
class WorkExperience:
    """Work experience"""
    company: str
    position: str
    duration_years: float
    responsibilities: List[str] = field(default_factory=list)
    achievements: List[str] = field(default_factory=list)
    
    @property
    def duration_months(self) -> int:
        """Convert years to months for backward compatibility"""
        return int(self.duration_years * 12)
    
    def to_dict(self) -> Dict:
        return {
            'company': self.company,
            'position': self.position,
            'duration_years': self.duration_years,
            'duration_months': self.duration_months,
            'responsibilities': self.responsibilities,
            'achievements': self.achievements
        }


@dataclass
class UserProfile:
    """Complete user profile"""
    user_id: str
    name: str
    education: List[Education]
    skills: List[Skill]
    preferences: List[Preference]
    constraints: Constraints
    work_experience: List[WorkExperience] = field(default_factory=list)
    certifications: List[str] = field(default_factory=list)
    languages: Dict[str, str] = field(default_factory=dict)  # Language: Proficiency level
    projects: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary format"""
        return {
            'user_id': self.user_id,
            'name': self.name,
            'education': [edu.to_dict() for edu in self.education],
            'skills': [skill.to_dict() for skill in self.skills],
            'preferences': [pref.to_dict() for pref in self.preferences],
            'constraints': self.constraints.to_dict(),
            'work_experience': [exp.to_dict() for exp in self.work_experience],
            'certifications': self.certifications,
            'languages': self.languages,
            'projects': self.projects
        }
    
    def get_skill_set(self) -> Set[str]:
        """Get skill set"""
        return {skill.name.lower() for skill in self.skills}
    
    def get_weighted_skills(self) -> Dict[str, float]:
        """Get weighted skills dictionary"""
        return {
            skill.name.lower(): skill.proficiency * (1 + skill.years_of_experience * 0.1)
            for skill in self.skills
        }
    
    def get_highest_education(self) -> Optional[Education]:
        """Get highest education level"""
        if not self.education:
            return None
        
        level_order = {
            EducationLevel.HIGH_SCHOOL: 1,
            EducationLevel.ASSOCIATE: 2,
            EducationLevel.BACHELOR: 3,
            EducationLevel.MASTER: 4,
            EducationLevel.PHD: 5
        }
        
        return max(self.education, key=lambda e: level_order.get(e.level, 0))
    
    def get_total_experience_years(self) -> float:
        """Get total years of work experience"""
        return sum(exp.duration_years for exp in self.work_experience)


def create_sample_user_profile() -> UserProfile:
    """Create sample user profile"""
    education = [
        Education(
            level=EducationLevel.BACHELOR,
            major="Computer Science",
            school="Tsinghua University",
            graduation_year=2023,
            gpa=3.8,
            ranking="985"
        )
    ]
    
    skills = [
        Skill(name="Python", proficiency=0.9, years_of_experience=3, category="Programming Language", verified=True),
        Skill(name="Java", proficiency=0.7, years_of_experience=2, category="Programming Language"),
        Skill(name="Machine Learning", proficiency=0.8, years_of_experience=2, category="Technical Field"),
        Skill(name="Deep Learning", proficiency=0.75, years_of_experience=1.5, category="Technical Field"),
        Skill(name="PyTorch", proficiency=0.85, years_of_experience=2, category="Framework"),
    ]
    
    preferences = [
        Preference(PreferenceType.INDUSTRY, "Artificial Intelligence", weight=0.9),
        Preference(PreferenceType.CAREER_GROWTH, "Fast Growth", weight=0.8),
        Preference(PreferenceType.INNOVATION, "Technical Innovation", weight=0.7),
    ]
    
    constraints = Constraints(
        locations=["Beijing", "Shanghai", "Shenzhen"],
        min_salary=20.0,
        max_salary=50.0,
        work_type="Full-time",
        industries=["Internet", "Artificial Intelligence", "FinTech"],
        company_types=["Foreign", "Private"],
        exclude_companies={"Some Disliked Company"}
    )
    
    work_experience = [
        WorkExperience(
            company="ByteDance",
            position="Algorithm Intern",
            duration_years=0.5,
            responsibilities=["Develop recommendation algorithms", "Optimize model performance"],
            achievements=["Improved CTR by 15%"]
        )
    ]
    
    return UserProfile(
        user_id="user_002",
        name="Li Si",
        education=education,
        skills=skills,
        preferences=preferences,
        constraints=constraints,
        work_experience=work_experience,
        certifications=["AWS Certified", "Deep Learning Specialization"],
        languages={"Chinese": "Fluent", "English": "Basic"},
        projects=[
            {"name": "Image Recognition System", "description": "CNN-based image classification", "tech_stack": ["Python", "PyTorch","Java"]}
        ]
    )
