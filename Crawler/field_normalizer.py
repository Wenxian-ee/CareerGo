"""
Field Normalizer Module
Converts heterogeneous job adverts into a unified schema with structured attributes

Solves:
- Different websites use different field names for the same concept (e.g. salary vs funding vs compensation)
- Salary information may be in different locations (direct fields, sections, description text)
- Need to extract and merge information from multiple sources
"""     

import re
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)


class FieldNormalizer:
    """
    Field Normalizer
    
    Features:
    - Map different field names from different sources to a unified schema
    - Handle synonyms (e.g. salary, funding, remuneration)
    - Extract salary information from multiple locations (direct fields, sections, description)
    - Extract and normalize field values
    - Support custom mapping rules
    """
    
    # Standard field definitions for the unified schema
    STANDARD_FIELDS = {
        'title': 'title',
        'company': 'company',
        'employer': 'employer',
        'location': 'location',
        'salary': 'salary',  # Unified salary/funding field
        'job_type': 'job_type',
        'contract_type': 'contract_type',
        'description': 'description',
        'requirements': 'requirements',
        'skills': 'skills',
        'posted_date': 'posted_date',
        'closing_date': 'closing_date',
        'url': 'url',
    }
    
    # Field mapping rules: map different variants to standard fields
    FIELD_MAPPINGS = {
        # All possible field names for salary-related fields (this is crucial!)
        'salary': [
            'salary',
            'funding',
            'funding_amount',
            'funding amount',  # Version with spaces
            'fundingamount',
            'remuneration',
            'pay',
            'compensation',
            'stipend',
            'wage',
            'earnings',
            'package',
            'salary_range',
            'salary range',
            'annual_salary',
            'annual salary',
            'hourly_rate',
            'hourly rate',
            'funding_available',
            'funding available',
            'bursary',
            'scholarship',
            'award',
            'grant',
            'financial_support',
            'financial support',
        ],
        
        # Company/employer related
        'employer': [
            'employer',
            'company',
            'organization',
            'organisation',
            'institution',
            'university',
            'college',
            'employer_name',
            'employer name',
            'company_name',
            'company name',
            'institution_name',
            'institution name',
        ],
        
        # Location related
        'location': [
            'location',
            'place',
            'city',
            'region',
            'country',
            'address',
            'workplace',
            'site',
        ],
        
        # Job type
        'job_type': [
            'job_type',
            'job type',
            'employment_type',
            'employment type',
            'position_type',
            'position type',
            'role_type',
            'role type',
            'contract',
            'hours',
            'working_hours',
            'working hours',
            'full_time',
            'full time',
            'part_time',
            'part time',
        ],
        
        # Contract type
        'contract_type': [
            'contract_type',
            'contract type',
            'contract',
            'duration',
            'term',
            'tenure',
            'fixed_term',
            'fixed term',
            'permanent',
            'temporary',
        ],
        
        # Closing date
        'closing_date': [
            'closing_date',
            'closing date',
            'deadline',
            'application_deadline',
            'application deadline',
            'expires',
            'expiry_date',
            'expiry date',
            'close_date',
            'close date',
            'end_date',
            'end date',
        ],
        
        # Posted date
        'posted_date': [
            'posted_date',
            'posted date',
            'published_date',
            'published date',
            'placed_on',
            'placed on',
            'date_posted',
            'date posted',
            'publication_date',
            'publication date',
            'start_date',
            'start date',
        ],
        
        # Job description
        'description': [
            'description',
            'job_description',
            'job description',
            'full_description',
            'full description',
            'details',
            'about',
            'overview',
            'summary',
        ],
        
        # Requirements
        'requirements': [
            'requirements',
            'qualifications',
            'essential_qualifications',
            'essential qualifications',
            'essential_requirements',
            'essential requirements',
            'required_qualifications',
            'required qualifications',
            'required_skills',
            'required skills',
            'prerequisites',
            'criteria',
        ],
        
        # Skills
        'skills': [
            'skills',
            'required_skills',
            'required skills',
            'desired_skills',
            'desired skills',
            'competencies',
            'abilities',
            'expertise',
        ],
    }
    
    # Regular expression patterns for field values (used to extract specific information from text)
    VALUE_PATTERNS = {
        'salary': [
            # GBP format
            r'£[\d,]+(?:\s*-\s*£[\d,]+)?(?:\s*(?:per|p\.a\.|pa|annually|per annum|year))?',
            # USD format
            r'\$[\d,]+(?:\s*-\s*\$[\d,]+)?(?:\s*(?:per|p\.a\.|pa|annually|per annum|year))?',
            # EUR format
            r'€[\d,]+(?:\s*-\s*€[\d,]+)?(?:\s*(?:per|p\.a\.|pa|annually|per annum|year))?',
            # Currency code format
            r'[\d,]+\s*(?:GBP|USD|EUR)(?:\s*-\s*[\d,]+\s*(?:GBP|USD|EUR))?',
            # Specific phrases
            r'funding\s+(?:of|amount:?)\s+£[\d,]+',
            r'stipend\s+(?:of|amount:?)\s+£[\d,]+',
            r'salary\s+(?:of|range:?)\s+£[\d,]+',
            # Number range (no currency symbol but with context)
            r'(?:salary|funding|stipend|pay)[\s:]+[\d,]+\s*-\s*[\d,]+',
        ],
    }
    
    def __init__(self, custom_mappings: Dict[str, List[str]] = None):
        """
            Initialize field normalizer
        Args:
            custom_mappings: Custom field mapping rules
        """
        self.field_mappings = self.FIELD_MAPPINGS.copy()
        
        # Merge custom mappings
        if custom_mappings:
            for standard_field, variants in custom_mappings.items():
                if standard_field in self.field_mappings:
                    self.field_mappings[standard_field].extend(variants)
                else:
                    self.field_mappings[standard_field] = variants
        
        # Create reverse mapping: variant -> standard field
        self.reverse_mapping = {}
        for standard_field, variants in self.field_mappings.items():
            for variant in variants:
                # Normalize variant name (lowercase, underscore)
                normalized_variant = self._normalize_key(variant)
                self.reverse_mapping[normalized_variant] = standard_field
    
    def _normalize_key(self, key: str) -> str:
        """
        Normalize key name: lowercase, space and hyphen to underscore, remove special characters
        
        Args:
            key: Original key name
            
        Returns:
            Normalized key name
        """
        if not key:
            return ""
        
        # Convert to lowercase
        key = key.lower()
        # Convert spaces and hyphens to underscore
        key = key.replace(' ', '_').replace('-', '_')
        # Remove special characters like colon and slash
        key = key.replace(':', '').replace('/', '_')
        # Remove extra underscores
        key = re.sub(r'_+', '_', key)
        # Remove leading and trailing underscores
        key = key.strip('_')
        
        return key
    
    def normalize_field_name(self, field_name: str) -> Optional[str]:
        """
        Normalize field name to standard field name in the unified schema
        
        Args:
            field_name: Original field name
            
        Returns:
            Normalized field name, None if not mapped
        """
        if not field_name:
            return None
        
        # Normalize input field name
        normalized = self._normalize_key(field_name)
        
        # Find mapping
        return self.reverse_mapping.get(normalized)
    
    def extract_salary_from_text(self, text: str) -> Optional[str]:
        """
        Extract salary/funding information from text
        
        Args:
            text: Text containing salary information
            
        Returns:
            Extracted salary information
        """
        if not text:
            return None
        
        for pattern in self.VALUE_PATTERNS['salary']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0).strip()
        
        return None
    
    def normalize_job_data(self, raw_data: Dict[str, Any], 
                          search_in_description: bool = True) -> Dict[str, Any]:
        """
        Normalize raw job data to the unified schema
        
        Args:
            raw_data: Original job data dictionary
            search_in_description: Whether to search for missing fields in the description text
            
        Returns:
            Normalized job data dictionary
        """
        normalized_data = {}
        
        # Step 1: Map existing fields
        for raw_field, raw_value in raw_data.items():
            if not raw_value or raw_field in ['raw_data', 'sections', 'meta', 'lists', '_raw_data']:
                continue
            
            # Get standard field name
            standard_field = self.normalize_field_name(raw_field)
            
            if standard_field:
                # If standard field already exists, keep the more complete value
                if standard_field in normalized_data:
                    existing_value = normalized_data[standard_field]
                    # Keep the longer value (usually more complete)
                    if isinstance(raw_value, str) and isinstance(existing_value, str):
                        if len(raw_value) > len(existing_value):
                            normalized_data[standard_field] = raw_value
                            logger.debug(f"Update field {standard_field}: {raw_field} -> {raw_value[:50]}...")
                else:
                    normalized_data[standard_field] = raw_value
                    logger.debug(f"Map field {standard_field}: {raw_field} -> {raw_value[:50] if isinstance(raw_value, str) else raw_value}")
            else:
                # Keep fields that cannot be mapped (use original field name)
                normalized_data[raw_field] = raw_value
        
        # Step 2: Intelligent extraction of salary information (multi-level search)
        if 'salary' not in normalized_data or not normalized_data['salary']:
            salary = self._extract_salary_comprehensive(raw_data)
            if salary:
                normalized_data['salary'] = salary
                logger.info(f"Intelligent extraction of salary information: {salary}")
        
        # Step 3: Ensure required fields exist
        for field in ['title', 'employer', 'location', 'description', 'url']:
            if field not in normalized_data:
                normalized_data[field] = None
        
        # Keep raw data for debugging
        normalized_data['_raw_data'] = raw_data
        
        return normalized_data
    
    def _extract_salary_comprehensive(self, raw_data: Dict[str, Any]) -> Optional[str]:
        """
        Comprehensive extraction of salary information (multi-level, multi-strategy)
        
        Priority:
        1. Direct fields (all salary-related field name variants)
        2. Salary-related sections
        3. Salary pattern matching in description text
        
        Args:
            raw_data: Original data
            
        Returns:
            Extracted salary information
        """
        # Strategy 1: Check all possible salary field names
        salary = self._extract_from_direct_fields(raw_data)
        if salary:
            logger.debug(f"Extract salary from direct fields: {salary}")
            return salary
        
        # Strategy 2: Extract from sections
        salary = self._extract_from_sections(raw_data)
        if salary:
            logger.debug(f"Extract salary from sections: {salary}")
            return salary
        
        # Strategy 3: Search in description text
        salary = self._extract_from_text_fields(raw_data)
        if salary:
            logger.debug(f"Extract salary from text fields: {salary}")
            return salary
        
        logger.debug("Unable to extract salary information")
        return None
    
    def _extract_from_direct_fields(self, raw_data: Dict[str, Any]) -> Optional[str]:
        """
        Extract salary information from direct fields
        Iterate through all possible salary field name variants
        
        Args:
            raw_data: Original data
            
        Returns:
            Extracted salary information
        """
        # Iterate through all possible salary field variants
        for field_variant in self.FIELD_MAPPINGS['salary']:
            # Try multiple formats
            possible_keys = [
                field_variant,  # Original format
                self._normalize_key(field_variant),  # Normalized format
            ]
            
            for key in possible_keys:
                # Search in original data (case-insensitive)
                for raw_key, raw_value in raw_data.items():
                    if self._normalize_key(raw_key) == self._normalize_key(key):
                        if raw_value and isinstance(raw_value, str) and raw_value.strip():
                            logger.debug(f"Found salary in field '{raw_key}': {raw_value}")
                            return raw_value.strip()
        
        return None
    
    def _extract_from_sections(self, raw_data: Dict[str, Any]) -> Optional[str]:
        """
        Extract salary information from sections field
        
        Args:
            raw_data: Original data
            
        Returns:
            Extracted salary information
        """
        sections = raw_data.get('sections', {})
        if not sections or not isinstance(sections, dict):
            return None
        
        # Salary-related keywords
        salary_keywords = [
            'salary', 'funding', 'remuneration', 'stipend', 
            'pay', 'compensation', 'award', 'grant', 'bursary'
        ]
        
        for section_title, section_content in sections.items():
            if not section_content:
                continue
            
            section_title_lower = section_title.lower()
            
            # Check if section title contains salary keywords
            if any(keyword in section_title_lower for keyword in salary_keywords):
                # Try to extract salary amount from content
                salary = self.extract_salary_from_text(section_content)
                if salary:
                    return salary
                # If unable to extract specific amount, return entire section content (may contain descriptive information)
                if isinstance(section_content, str) and len(section_content) < 500:
                    return section_content.strip()
        
        return None
    
    def _extract_from_text_fields(self, raw_data: Dict[str, Any]) -> Optional[str]:
        """
        Search for salary information in all text fields
        
        Args:
            raw_data: Original data
            
        Returns:
            Extracted salary information
        """
        # Search order: full_description > description > other long text fields
        search_fields = ['full_description', 'description', 'summary', 'overview']
        
        for field in search_fields:
            if field in raw_data and raw_data[field]:
                salary = self.extract_salary_from_text(raw_data[field])
                if salary:
                    return salary
        
        # Search all string fields (as last resort)
        for key, value in raw_data.items():
            if isinstance(value, str) and len(value) > 50:  # Only search longer text
                salary = self.extract_salary_from_text(value)
                if salary:
                    return salary
        
        return None
    
    def batch_normalize(self, jobs_data: List[Dict[str, Any]], 
                       search_in_description: bool = True) -> List[Dict[str, Any]]:
        """
        Batch normalize job data
        
        Args:
            jobs_data: Original job data list
            search_in_description: Whether to search for missing fields in the description text
            
        Returns:
            Normalized job data list
        """
        normalized_jobs = []
        
        for i, job_data in enumerate(jobs_data, 1):
            try:
                normalized = self.normalize_job_data(job_data, search_in_description)
                normalized_jobs.append(normalized)
                logger.debug(f"Successfully normalized job {i}/{len(jobs_data)}")
            except Exception as e:
                logger.error(f"Error normalizing job {i}: {e}")
                # Keep original data
                normalized_jobs.append(job_data)
        
        return normalized_jobs
    
    def get_field_coverage_report(self, jobs_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate field coverage report
        
        Args:
            jobs_data: Job data list
            
        Returns:
            Dictionary containing field coverage statistics
        """
        if not jobs_data:
            return {}
        
        total_jobs = len(jobs_data)
        field_counts = {}
        
        # Count occurrences of each standard field
        for standard_field in self.STANDARD_FIELDS.keys():
            count = sum(1 for job in jobs_data 
                       if job.get(standard_field) and str(job.get(standard_field)).strip())
            field_counts[standard_field] = {
                'count': count,
                'percentage': (count / total_jobs * 100) if total_jobs > 0 else 0
            }
        
        return {
            'total_jobs': total_jobs,
            'field_coverage': field_counts,
            'missing_salary_count': total_jobs - field_counts.get('salary', {}).get('count', 0),
        }
    
    def print_coverage_report(self, jobs_data: List[Dict[str, Any]]):
        """
        Print field coverage report
        
        Args:
            jobs_data: Job data list
        """
        report = self.get_field_coverage_report(jobs_data)
        
        print("\n" + "=" * 80)
        print("Field Coverage Report")
        print("=" * 80)
        print(f"Total jobs: {report['total_jobs']}")
        print("\nStandard field coverage:")
        print("-" * 80)
        
        for field, stats in sorted(report['field_coverage'].items(), 
                                   key=lambda x: x[1]['percentage'], 
                                   reverse=True):
            bar_length = int(stats['percentage'] / 2)
            bar = '█' * bar_length + '░' * (50 - bar_length)
            print(f"{field:20s} {bar} {stats['percentage']:6.2f}% ({stats['count']}/{report['total_jobs']})")
        
        print("=" * 80)
        
        if report.get('missing_salary_count', 0) > 0:
            print(f"\nWarning: {report['missing_salary_count']} jobs missing salary information")


# Convenience function
def normalize_job_data(raw_data: Dict[str, Any], 
                      custom_mappings: Dict[str, List[str]] = None) -> Dict[str, Any]:
    """
    Convenience function: normalize single job data
    
    Args:
        raw_data: Original job data
        custom_mappings: Custom field mapping rules
        
    Returns:
        Normalized job data
    """
    normalizer = FieldNormalizer(custom_mappings)
    return normalizer.normalize_job_data(raw_data)


def batch_normalize_jobs(jobs_data: List[Dict[str, Any]], 
                        custom_mappings: Dict[str, List[str]] = None) -> List[Dict[str, Any]]:
    """
    Convenience function: batch normalize job data
    
    Args:
        jobs_data: Original job data list
        custom_mappings: Custom field mapping rules
        
    Returns:
        Normalized job data list
    """
    normalizer = FieldNormalizer(custom_mappings)
    return normalizer.batch_normalize(jobs_data)


if __name__ == "__main__":
    # Test example
    logging.basicConfig(level=logging.INFO)
    
    # Example 1: Job data with different field names
    test_jobs = [
        {
            'title': 'PhD Studentship in Digital Chemistry',
            'employer': 'University of Example',
            'funding_amount': '£18,622 per annum',  # Note: This is funding_amount
            'location': 'London, UK',
            'full_description': 'A fully funded PhD position...',
        },
        {
            'title': 'Research Assistant',
            'institution_name': 'Example College',
            'salary': '£35,000 - £40,000',
            'place': 'Manchester, UK',
            'description': 'An exciting research position...',
        },
        {
            'title': 'Postdoc Position',
            'organization': 'Research Institute',
            'remuneration': '€45,000 per year',
            'city': 'Berlin, Germany',
            'job_description': 'Postdoctoral research opportunity...',
        },
        {
            'title': '10 Fully Funded PhD Studentships',
            'employer': 'University of Southampton',
            'location': 'Southampton, UK',
            'sections': {
                'FUNDING AMOUNT': '£18,622 per annum plus tuition fees',  # In sections
                'REQUIREMENTS': 'Strong background in chemistry...',
            },
            'description': 'Exciting PhD opportunities in automated materials chemistry.',
        }
    ]
    
    # Create normalizer
    normalizer = FieldNormalizer()
    
    # Normalize data
    print("\nOriginal data -> Normalized data:")
    print("=" * 80)
    
    normalized_jobs = []
    for i, job in enumerate(test_jobs, 1):
        print(f"\nJob {i}: {job.get('title', 'Unknown')}")
        print(f"Original fields: {[k for k in job.keys() if k != 'sections']}")
        
        normalized = normalizer.normalize_job_data(job)
        normalized_jobs.append(normalized)
        
        print(f"Normalized fields: {[k for k in normalized.keys() if not k.startswith('_') and k != 'sections']}")
        print(f"✓ Salary field: {normalized.get('salary', 'N/A')}")
    
    # Print coverage report
    normalizer.print_coverage_report(normalized_jobs)
