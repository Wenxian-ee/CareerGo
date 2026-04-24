"""
Matching and Ranking System - Database Version
integrated with PostgreSQL database, support user profile persistence and job data query
"""
import json
import re
from typing import Any, Dict, List, Optional
from datetime import datetime

from config import DATABASE_CONFIG, LLM_CONFIG, MATCHER_CONFIG, RANKER_CONFIG
from database import DatabaseManager
from llm_reasoner import RecommendationReasoner
from user_profile import (
    UserProfile, Education, Skill, Preference, Constraints,
    WorkExperience, EducationLevel, PreferenceType
)
from matching_algorithm import JobMatcher
from ranking_system import MultiObjectiveRanker


def print_separator(title: str = ""):
    """Print separator"""
    if title:
        print(f"\n{'='*80}")
        print(f"  {title}")
        print('='*80 + '\n')
    else:
        print('='*80)


def convert_db_job_to_dict(db_job: Dict) -> Dict:
    """
    Convert database query results to the format needed by the matching algorithm
    """
    def _to_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _to_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _parse_datetime(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                # Handle ISO strings with trailing Z.
                return datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                pass
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d",
            ):
                try:
                    return datetime.strptime(text, fmt)
                except ValueError:
                    continue
        return None

    def _norm_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip().lower()

    def _education_level_score(value: Any) -> Optional[float]:
        text = _norm_text(value)
        if not text:
            return None
        if any(k in text for k in ("phd", "doctor")):
            return 1.0
        if any(k in text for k in ("master", "msc", "ms ")):
            return 0.8
        if any(k in text for k in ("bachelor", "undergraduate", "bsc", "ba ")):
            return 0.6
        if any(k in text for k in ("associate", "diploma")):
            return 0.4
        return 0.5

    def _seniority_level(value: Any) -> float:
        text = _norm_text(value)
        if not text:
            return 0.5
        if any(k in text for k in ("intern", "trainee", "graduate", "entry", "junior", "assistant")):
            return 0.85
        if any(k in text for k in ("lead", "principal", "staff", "architect", "manager", "director", "head")):
            return 0.35
        if any(k in text for k in ("senior", "sr.", "sr ", "mid-level")):
            return 0.45
        return 0.65

    def _company_size_score(value: Any) -> Optional[float]:
        text = _norm_text(value)
        if not text:
            return None
        if any(k in text for k in ("startup", "small", "1-10", "11-50", "51-200")):
            return 0.75
        if any(k in text for k in ("201-500", "501-1000", "medium")):
            return 0.65
        if any(k in text for k in ("enterprise", "1000+", "large", "multinational")):
            return 0.55
        return 0.6

    # First use job_id field with business meaning, then fallback to primary key id
    job_id = db_job.get('job_id') or db_job.get('id', 'unknown')

    # Combine min/max salary into a representative value for salary matching
    salary_min = db_job.get('salary_min')
    salary_max = db_job.get('salary_max')

    # If min/max are empty, but salary text has clear numbers, parse from text
    salary_text = db_job.get('salary') or ""
    if salary_min is None and salary_max is None and salary_text:
        # Extract all numbers (support formats like 30,000 / 45000.50)
        number_strings = re.findall(r"\d[\d,]*\.?\d*", salary_text)
        numbers = []
        for ns in number_strings:
            try:
                numbers.append(float(ns.replace(",", "")))
            except ValueError:
                continue
        if numbers:
            if len(numbers) == 1:
                salary_min = salary_max = numbers[0]
            else:
                salary_min = min(numbers)
                salary_max = max(numbers)

    if salary_min is not None and salary_max is not None:
        salary = float(salary_min + salary_max) / 2.0
    elif salary_min is not None:
        salary = float(salary_min)
    elif salary_max is not None:
        salary = float(salary_max)
    else:
        salary = None

    # Work type: merge possible job_type / position_type from schema
    work_type = db_job.get('job_type') or db_job.get('position_type')

    # Company name: first employer, then company, then default value to avoid None
    company_name = db_job.get('employer') or db_job.get('company') or "Unknown Company"

    # Availability/earliest start:
    # merged_jobs schema typically uses `published_date` / `placed_on` / `created` for timelines.
    # We normalize them into a single `start_date` key for hard-constraint checks.
    start_date = (
        db_job.get('start_date')
        or db_job.get('published_date')
        or db_job.get('placed_on')
        or db_job.get('created')
    )
    posted_at = _parse_datetime(
        db_job.get('published_date') or db_job.get('created') or db_job.get('placed_on')
    )
    if posted_at:
        # Keep timezone awareness consistent to avoid subtracting aware vs naive datetimes.
        if posted_at.tzinfo is not None and posted_at.utcoffset() is not None:
            now_dt = datetime.now(posted_at.tzinfo)
        else:
            now_dt = datetime.now()
        days_since_posted = max(0, (now_dt - posted_at).days)
    else:
        days_since_posted = None

    raw_data_value = db_job.get('raw_data')
    raw_data: Dict[str, Any] = raw_data_value if isinstance(raw_data_value, dict) else {}

    # Backward/forward compatible field mapping for matcher/ranker.
    required_education = (
        db_job.get('required_education')
        or db_job.get('education_requirement')
        or raw_data.get('required_education')
        or raw_data.get('education_requirement')
    )
    required_experience_years = (
        _to_float(db_job.get('required_experience_years'))
        if db_job.get('required_experience_years') is not None
        else _to_float(db_job.get('experience_years'))
    )
    if required_experience_years is None:
        required_experience_years = _to_float(raw_data.get('required_experience_years'))
    if required_experience_years is None:
        required_experience_years = _to_float(raw_data.get('experience_years'))
    if required_experience_years is None:
        merged_text = " ".join(
            str(db_job.get(k) or "")
            for k in ("title", "requirements", "description", "full_description")
        ).lower()
        exp_matches = re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", merged_text)
        if exp_matches:
            try:
                required_experience_years = max(0.0, float(exp_matches[0]))
            except ValueError:
                required_experience_years = None
    if required_experience_years is None:
        required_experience_years = 0.0

    company_size = db_job.get('company_size') or raw_data.get('company_size') or raw_data.get('organization_size')
    industry = db_job.get('industry') or raw_data.get('industry') or raw_data.get('sector') or db_job.get('category')
    company_type = db_job.get('company_type') or raw_data.get('company_type') or raw_data.get('organization_type')
    view_count = (
        _to_int(db_job.get('view_count'))
        or _to_int(raw_data.get('view_count'))
        or _to_int(raw_data.get('views'))
        or _to_int(raw_data.get('impressions'))
        or 0
    )
    application_count = (
        _to_int(db_job.get('application_count'))
        or _to_int(raw_data.get('application_count'))
        or _to_int(raw_data.get('applications'))
        or 0
    )

    explicit_competition = _to_float(db_job.get('competition_level'))
    if explicit_competition is None:
        explicit_competition = _to_float(raw_data.get('competition_level'))

    if explicit_competition is not None:
        competition_level = max(0.0, min(1.0, explicit_competition))
    elif view_count > 0 or application_count > 0:
        # Convert popularity signals into [0, 1] competition proxy.
        view_component = min(1.0, view_count / 5000.0)
        app_component = min(1.0, application_count / 200.0)
        competition_level = min(1.0, view_component * 0.7 + app_component * 0.3)
    elif days_since_posted is not None:
        # New postings tend to attract more applicants in the first days.
        if days_since_posted <= 3:
            competition_level = 0.7
        elif days_since_posted <= 14:
            competition_level = 0.5
        elif days_since_posted <= 30:
            competition_level = 0.35
        else:
            competition_level = 0.25
    else:
        competition_level = 0.5

    close_at = _parse_datetime(db_job.get('closing_date'))
    if close_at:
        if close_at.tzinfo is not None and close_at.utcoffset() is not None:
            now_for_close = datetime.now(close_at.tzinfo)
        else:
            now_for_close = datetime.now()
        days_to_close = (close_at - now_for_close).days
    else:
        days_to_close = None

    required_education_level = _education_level_score(required_education)
    title_seniority_level = _seniority_level(db_job.get('title'))
    company_size_score = _company_size_score(company_size)

    _apply = str(db_job.get('apply_url') or '').strip()
    _url = str(db_job.get('url') or '').strip()
    job_url = (_apply or _url) or None

    desc = db_job.get('description') or db_job.get('full_description') or ''
    if not isinstance(desc, str):
        desc = str(desc) if desc is not None else ''
    if len(desc) > 320:
        desc_snippet = desc[:317].rstrip() + '…'
    else:
        desc_snippet = desc

    return {
        'job_id': job_id,
        'title': db_job.get('title', 'Unknown Title'),
        'company': company_name,
        'location': db_job.get('location', 'Unknown Location'),
        'job_url': job_url,
        'salary_min': salary_min or 0.0,
        'salary_max': salary_max or 0.0,
        'salary': salary,
        # Original salary text, only for display (may contain currency symbols/units)
        'salary_text': db_job.get('salary'),
        'description': db_job.get('description', '') or db_job.get('full_description', ''),
        'description_snippet': desc_snippet,
        'requirements': db_job.get('requirements', ''),
        'required_skills': db_job.get('required_skills', []),
        'preferred_skills': db_job.get('preferred_skills', []),
        'required_education': required_education,
        'required_education_level': required_education_level,
        'education_requirement': db_job.get('education_requirement', 'Bachelor'),
        'required_experience_years': required_experience_years,
        'experience_years': db_job.get('experience_years', 0),
        'industry': industry or 'Unknown',
        # Optional classification fields (may or may not exist depending on upstream processing)
        'company_type': company_type,
        'position_type': work_type or 'Full-time',
        'work_type': work_type or 'Full-time',
        'company_size': company_size or 'Unknown',
        'company_size_score': company_size_score,
        'start_date': start_date,
        # Optional commute time fields (may or may not exist depending on upstream processing)
        'commute_time': db_job.get('commute_time') or db_job.get('commute_minutes'),
        'benefits': db_job.get('benefits', []),
        # Display-only fields from merged_jobs (optional columns)
        'department': db_job.get('department'),
        'hours': db_job.get('hours'),
        'closing_date': db_job.get('closing_date'),
        'days_since_posted': days_since_posted,
        'days_to_close': days_to_close,
        'title_seniority_level': title_seniority_level,
        'view_count': view_count,
        'application_count': application_count,
        'competition_level': competition_level,
        'source': db_job.get('source'),
        'category': db_job.get('category'),
        'subcategory': db_job.get('subcategory'),
    }


def create_sample_user_profile(user_id: str = "user_002") -> UserProfile:
    """
    Create sample user profile (English version)
    """
    education = [
        Education(
            level=EducationLevel.BACHELOR,
            major="Software Engineering",
            school="Shanghai Jiao Tong University",
            graduation_year=2022,
            gpa=3.4,
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
        user_id=user_id,
        name="Li Si",
        education=education,
        skills=skills,
        preferences=preferences,
        constraints=constraints,
        work_experience=work_experience,
        certifications=["AWS Certified", "Deep Learning Specialization"],
        languages={"Chinese": "Fluent", "English": "Basic"},
        projects=[
            {
                "name": "Image Recognition System",
                "description": "CNN-based image classification",
                "tech_stack": ["Python", "PyTorch","Java"],
            }
        ]
    )


def format_job_salary(job: Dict) -> str:
    """
    Format job salary for display.
    Prefer the original text; fall back to a numeric range when available.
    """
    if job.get('salary_text'):
        return job['salary_text']

    salary_min = job.get('salary_min')
    salary_max = job.get('salary_max')

    # If there is no salary information
    if (salary_min is None or salary_min == 0) and (salary_max is None or salary_max == 0):
        return "Salary not provided"

    # If there is only one boundary
    if salary_min and not salary_max:
        return str(salary_min)
    if salary_max and not salary_min:
        return str(salary_max)

    # If both have boundaries
    if salary_min == salary_max:
        return str(salary_min)
    return f"{salary_min}-{salary_max}"


def format_skill_gaps(reasoning: Dict) -> str:
    """Format skill gaps output"""
    skill_gaps = reasoning.get('skill_gaps', [])
    if not skill_gaps:
        return "No obvious skill gaps identified"

    formatted = []
    for gap in skill_gaps[:3]:
        formatted.append(f"{gap['skill']} ({gap.get('importance', 'medium')})")
    return ", ".join(formatted)


def main():
    """Main function"""
    print_separator("Job Matching and Ranking System Demonstration (Database Version)")
    
    # 1. Connect to database
    print_separator("Step 1: Connect to database")
    db_manager = DatabaseManager(DATABASE_CONFIG)
    
    if not db_manager.test_connection():
        print("Database connection failed, please check configuration")
        return
    
    print("Database connection successful")
    
    # 2. Load or create the user profile
    print_separator("Step 2: Load or create user profile")
    
    user_id = "lzf"
    user_profile = db_manager.get_user_profile(user_id)
    
    if not user_profile:
        print(f"User {user_id} does not exist, creating sample user...")
        user_profile = create_sample_user_profile(user_id)
        
        if db_manager.save_user_profile(user_profile):
            print(f"Sample user created successfully")
        else:
            print("User creation failed")
            return
    else:
        print("User profile loaded from database successfully")
    
    # Display user information
    print(f"\nUser: {user_profile.name}")
    if user_profile.education:
        edu = user_profile.get_highest_education()
        if edu is not None:
            print(f"Education: {edu.level.value} - {edu.major}")
    print(f"Skills: {', '.join([s.name for s in user_profile.skills[:5]])}")
    print(f"Expected locations: {', '.join(user_profile.constraints.locations)}")
    print(f"Expected salary: {user_profile.constraints.min_salary}-{user_profile.constraints.max_salary}/yr")
    
    # 3. Load jobs from the database
    print_separator("Step 3: Load jobs from database")
    
    # Load all jobs from merged_jobs (no LIMIT). Location/salary filters apply in the matcher.
    db_jobs = db_manager.get_jobs_from_merged_table(limit=None, filters={})
    
    if not db_jobs:
        print("No jobs found in the database")
        print("Please run the crawler system to import job data into the database")
        print("Please check if the merged_jobs table has data")
        print("\nProgram exiting")
        return
    
    print(f"Loaded {len(db_jobs)} jobs from the database")
    # Convert the data format
    jobs = [convert_db_job_to_dict(job) for job in db_jobs]
    
    # 4. Execute job matching
    print_separator("Step 4: Execute job matching")
    matcher = JobMatcher(config=MATCHER_CONFIG)
    matched_results = matcher.match(user_profile, jobs)
    print(f"Matched {len(matched_results)} jobs meeting conditions\n")
    
    # Display the matching results
    if matched_results:
        print("Matching results preview:")
        for i, (job, score, details) in enumerate(matched_results[:3], 1):
            print(f"\n{i}. {job['title']} - {job['company']}")
            print(f"   Matching score: {score:.2%}")
            print(f"   Skill matching: {details['skill_score']:.2%}")
            print(f"   Education matching: {details['education_score']:.2%}")
            print(f"   Experience matching: {details['experience_score']:.2%}")
    
    # 5. Execute multi-objective ranking
    print_separator("Step 5: Multi-objective ranking")
    ranker = MultiObjectiveRanker(config=RANKER_CONFIG)
    ranked_jobs = ranker.rank(user_profile, matched_results, top_k=10)
    reasoner = RecommendationReasoner(config=LLM_CONFIG)
    ranked_jobs = reasoner.enrich_ranked_jobs(user_profile, ranked_jobs)
    
    print(f"Ranking completed, returning Top {len(ranked_jobs)} jobs\n")
    
    # Display the ranking results
    if ranked_jobs:
        print("="*100)
        print(f"{'Rank':<6} {'Job':<20} {'Company':<15} {'Overall score':<8} {'Relevance':<8} {'Feasibility':<8} {'Growth':<8}")
        print("="*100)
        
        for i, job_info in enumerate(ranked_jobs, 1):
            job = job_info['job']
            print(f"{i:<6} {job['title'][:20]:<20} {job['company'][:15]:<15} "
                  f"{job_info['final_score']:.2%}    "
                  f"{job_info['relevance']:.2%}    "
                  f"{job_info['feasibility']:.2%}    "
                  f"{job_info['growth']:.2%}")
        
        print("="*100)
    
    # 6. Save the matching results to the database
    print_separator("Step 6: Save matching results to database")
    
    saved_count = 0
    for job_info in ranked_jobs:
        job = job_info['job']
        scores = {
            'match_score': job_info.get('match_score', 0),
            'relevance': job_info['relevance'],
            'feasibility': job_info['feasibility'],
            'growth': job_info['growth'],
            'final_score': job_info['final_score']
        }
        
        if db_manager.save_matching_result(user_id, str(job['job_id']), scores):
            saved_count += 1
    
    print(f"{saved_count} matching results saved to database")
    
    # 7. Detailed recommendation results
    print_separator("Step 7: Generate detailed recommendation report")
    
    if ranked_jobs:
        print(f"\nRecommendations for user {user_profile.name}:\n")
        
        for i, job_info in enumerate(ranked_jobs[:5], 1):
            job = job_info['job']
            print(f"\n{'='*80}")
            print(f"Recommendation #{i}: {job['title']}")
            print(f"{'='*80}")
            print(f"Company: {job['company']}")
            print(f"Location: {job['location']}")
            print(f"Salary: {format_job_salary(job)}")
            print(f"\nScores:")
            print(f"   Overall score: {job_info['final_score']:.2%}")
            print(f"   Relevance: {job_info['relevance']:.2%} (Skill matching)")
            print(f"   Feasibility: {job_info['feasibility']:.2%} (Education, experience requirements)")
            print(f"   Growth: {job_info['growth']:.2%} (Career development potential)")
            print(f"   Score explanation: {ranker.explain_ranking(job_info)}")
            
            if job.get('required_skills'):
                print(f"\nRequired skills: {', '.join(job['required_skills'][:5])}")

            reasoning = job_info.get('reasoning', {})
            if reasoning:
                print(f"\nRecommendation reasoning ({reasoning.get('source', 'fallback')}): {reasoning.get('recommendation_reasoning', '')}")
                if reasoning.get('fallback_reason'):
                    print(f"LLM fallback reason: {reasoning['fallback_reason']}")
                print(f"Skill gaps: {format_skill_gaps(reasoning)}")
                learning_suggestions = reasoning.get('learning_suggestions', [])
                if learning_suggestions:
                    print(f"Learning suggestions: {'; '.join(learning_suggestions[:3])}")
    
    # 8. Export results to JSON
    print_separator("Step 8: Export results to JSON")
    
    highest_education = user_profile.get_highest_education()
    output_data = {
        'user': {
            'user_id': user_profile.user_id,
            'name': user_profile.name,
            'skills': [s.name for s in user_profile.skills],
            'education': highest_education.level.value if highest_education else 'N/A',
        },
        'recommendations': [
            {
                'rank': i,
                'job_id': job_info['job']['job_id'],
                'title': job_info['job']['title'],
                'company': job_info['job']['company'],
                'location': job_info['job']['location'],
                # Unified display format to avoid ambiguous currency units.
                'salary': format_job_salary(job_info['job']),
                'scores': {
                    'final_score': round(job_info['final_score'], 4),
                    'relevance': round(job_info['relevance'], 4),
                    'feasibility': round(job_info['feasibility'], 4),
                    'growth': round(job_info['growth'], 4),
                },
                'score_explanation': ranker.explain_ranking(job_info),
                'reasoning': job_info.get('reasoning', {}),
            }
            for i, job_info in enumerate(ranked_jobs, 1)
        ],
        'timestamp': datetime.now().isoformat()
    }
    
    output_file = 'results_db.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"Results exported to {output_file}")
    
    # 9. Display the statistics
    print_separator("Step 9: Statistics")
    
    print(f"Total users: {len(db_manager.list_users())}")
    print(f"Number of jobs matched: {len(jobs)}")
    print(f"Number of jobs meeting conditions: {len(matched_results)}")
    print(f"Number of recommended jobs: {len(ranked_jobs)}")
    
    history = db_manager.get_matching_history(user_id, limit=100)
    print(f"User matching history: {len(history)} records")
    
    print_separator("Completed")
    print(f"\nAll steps completed!")
    print(f"- Matched {len(matched_results)} jobs")
    print(f"- Recommended Top {len(ranked_jobs)} jobs")
    print(f"- Results saved to database and {output_file}\n")


if __name__ == "__main__":
    main()
