"""
HTML Parser Utils Module
Provides generic HTML parsing functionality for extracting structured data from web pages
"""

from bs4 import BeautifulSoup
from typing import Dict, List, Optional, Any
import re
import json
import logging

logger = logging.getLogger(__name__)


class HTMLParserUtils:
    """HTML Parser Utils Class"""
    
    @staticmethod
    def extract_text_from_element(element, strip: bool = True) -> Optional[str]:
        """
        Extract text from BeautifulSoup element
        
        Args:
            element: BeautifulSoup element
            strip: Whether to remove leading and trailing whitespace
            
        Returns:
            Extracted text, None if element is None
        """
        if element is None:
            return None
        text = element.get_text(strip=strip)
        return text if text else None
    
    @staticmethod
    def extract_table_data(soup: BeautifulSoup, table_selector: str = None) -> Dict[str, str]:
        """
        Extract key-value pairs from HTML table
        
        Args:
            soup: BeautifulSoup object
            table_selector: Table selector (optional)
            
        Returns:
            Dictionary containing table data
        """
        data = {}
        
        # Find tables
        if table_selector:
            tables = soup.select(table_selector)
        else:
            tables = soup.find_all('table')
        
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                # Find table headers and table cells
                th = row.find('th')
                td = row.find('td')
                
                if th and td:
                    # Extract key and value
                    key = HTMLParserUtils.extract_text_from_element(th)
                    value = HTMLParserUtils.extract_text_from_element(td)
                    
                    if key and value:
                        # Normalize key name: remove colon, convert to lowercase, replace spaces with underscores
                        key_normalized = key.replace(':', '').strip().lower().replace(' ', '_')
                        data[key_normalized] = value

        # Normalize common jobs.ac.uk "details table" labels to our schema keys.
        # Example: header text "Closes:" -> key_normalized "closes" -> map to "closing_date"
        if 'closes' in data and 'closing_date' not in data:
            data['closing_date'] = data.pop('closes')
        # Some pages expose an advert/reference id in the details table.
        if 'advert_id' in data and 'job_ref' not in data:
            data['job_ref'] = data.pop('advert_id')
        
        return data
    
    @staticmethod
    def extract_meta_tags(soup: BeautifulSoup) -> Dict[str, str]:
        """
        Extract HTML meta tag information
        
        Args:
            soup: BeautifulSoup object
            
        Returns:
            Dictionary containing meta tag data
        """
        meta_data = {}
        
        # Extract title
        title = soup.find('title')
        if title:
            meta_data['title'] = HTMLParserUtils.extract_text_from_element(title)
        
        # Extract meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            meta_data['description'] = meta_desc.get('content')
        
        # Extract Open Graph tags
        og_tags = soup.find_all('meta', property=re.compile(r'^og:'))
        for tag in og_tags:
            prop = tag.get('property', '').replace('og:', '')
            content = tag.get('content')
            if prop and content:
                meta_data[f'og_{prop}'] = content
        
        return meta_data
    
    @staticmethod
    def extract_structured_sections(soup: BeautifulSoup, 
                                    section_marker: str = 'strong',
                                    uppercase_only: bool = True,
                                    min_length: int = 5) -> Dict[str, str]:
        """
        Extract structured text paragraphs (identified by title markers)
        
        Args:
            soup: BeautifulSoup object
            section_marker: HTML tag for paragraph titles (e.g. 'strong', 'h2')
            uppercase_only: Whether to only recognize uppercase titles
            min_length: Minimum length of title
            
        Returns:
            Dictionary containing content of each paragraph
        """
        sections = {}
        
        # Find all possible paragraph titles
        markers = soup.find_all(section_marker)
        
        for marker in markers:
            section_title = HTMLParserUtils.extract_text_from_element(marker)
            
            if not section_title or len(section_title) < min_length:
                continue
            
            # If uppercase only, check if title is uppercase
            if uppercase_only and not section_title.isupper():
                continue
            
            # Collect content of this paragraph
            section_content = []
            current = marker.parent
            
            if current:
                # Get siblings after current element
                for sibling in current.find_next_siblings():
                    # If next paragraph title is encountered, stop
                    if sibling.find(section_marker):
                        next_marker = sibling.find(section_marker)
                        next_title = HTMLParserUtils.extract_text_from_element(next_marker)
                        if next_title and (not uppercase_only or next_title.isupper()):
                            break
                    
                    # Extract text content
                    text = HTMLParserUtils.extract_text_from_element(sibling)
                    if text and len(text) > 10:
                        section_content.append(text)
            
            if section_content:
                sections[section_title] = '\n'.join(section_content)
        
        return sections
    
    @staticmethod
    def extract_all_paragraphs(soup: BeautifulSoup, 
                               min_length: int = 20,
                               exclude_tags: List[str] = None) -> List[str]:
        """
        Extract all paragraph text
        
        Args:
            soup: BeautifulSoup object
            min_length: Minimum length of paragraph
            exclude_tags: List of parent tags to exclude
            
        Returns:
            List of paragraph text
        """
        if exclude_tags is None:
            exclude_tags = ['script', 'style', 'nav', 'footer', 'header']
        
        paragraphs = []
        
        for p in soup.find_all('p'):
            # Check if in excluded tags
            if any(p.find_parent(tag) for tag in exclude_tags):
                continue
            
            text = HTMLParserUtils.extract_text_from_element(p)
            if text and len(text) >= min_length:
                paragraphs.append(text)
        
        return paragraphs
    
    @staticmethod
    def extract_lists(soup: BeautifulSoup, list_type: str = 'ul') -> List[List[str]]:
        """
        Extract list content
        
        Args:
            soup: BeautifulSoup object
            list_type: List type ('ul' or 'ol')
            
        Returns:
            List of lists, each inner list containing all li items of a ul/ol
        """
        all_lists = []
        
        for list_elem in soup.find_all(list_type):
            items = []
            for li in list_elem.find_all('li', recursive=False):
                text = HTMLParserUtils.extract_text_from_element(li)
                if text:
                    items.append(text)
            
            if items:
                all_lists.append(items)
        
        return all_lists
    
    @staticmethod
    def extract_links(soup: BeautifulSoup, 
                     filter_pattern: str = None,
                     base_url: str = None) -> List[Dict[str, str]]:
        """
        Extract all links
        
        Args:
            soup: BeautifulSoup object
            filter_pattern: Regular expression filter pattern
            base_url: Base URL (for converting relative links)
            
        Returns:
            List of dictionaries containing link information
        """
        links = []
        
        for a in soup.find_all('a', href=True):
            href = a.get('href')
            text = HTMLParserUtils.extract_text_from_element(a)
            
            # If filter pattern is provided, check if it matches
            if filter_pattern and not re.search(filter_pattern, href):
                continue
            
            # If base URL is provided, convert relative links
            if base_url and not href.startswith(('http://', 'https://')):
                from urllib.parse import urljoin
                href = urljoin(base_url, href)
            
            links.append({
                'url': href,
                'text': text or '',
                'title': a.get('title', '')
            })
        
        return links
    
    @staticmethod
    def clean_text(text: str) -> str:
        """
        Clean text: remove extra whitespace, special characters, etc.
        
        Args:
            text: Original text
            
        Returns:
            Cleaned text
        """
        if not text:
            return ""
        
        # Remove extra whitespace characters
        text = re.sub(r'\s+', ' ', text)
        
        # Remove leading and trailing whitespace
        text = text.strip()
        
        # Remove HTML entities
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        text = text.replace('&#039;', "'")
        
        return text
    
    @staticmethod
    def extract_script_variables(soup: BeautifulSoup, 
                                 variable_names: List[str]) -> Dict[str, Any]:
        """
        Extract variable values from JavaScript code
        
        Args:
            soup: BeautifulSoup object
            variable_names: List of variable names to extract
            
        Returns:
            Dictionary containing variable values
        """
        variables = {}
        
        # Find all script tags
        for script in soup.find_all('script'):
            script_text = script.string
            if not script_text:
                continue
            
            # Try to extract each variable
            for var_name in variable_names:
                # Match pattern: var variable_name = "value";
                pattern = rf'var\s+{var_name}\s*=\s*["\']([^"\']*)["\']'
                match = re.search(pattern, script_text)
                if match:
                    variables[var_name] = match.group(1)
        
        return variables


class JobsAcUkHTMLParser:
    """Parser for jobs.ac.uk job detail pages"""

    @staticmethod
    def _extract_var_job_json(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """Extract the rich `var job = {...};` JSON object embedded in <script> tags."""
        for sc in soup.find_all('script'):
            text = sc.string or ''
            m = re.search(r'var\s+job\s*=\s*(\{.*?\})\s*;', text, re.DOTALL)
            if m:
                try:
                    obj = json.loads(m.group(1))
                    return obj.get('job', obj)
                except (json.JSONDecodeError, ValueError):
                    pass
        return None

    @staticmethod
    def _extract_jsonld(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """Extract schema.org/JobPosting JSON-LD data."""
        for sc in soup.find_all('script', type='application/ld+json'):
            text = sc.string or ''
            if not text.strip():
                continue
            try:
                obj = json.loads(text)
                if obj.get('@type') == 'JobPosting':
                    return obj
            except (json.JSONDecodeError, ValueError):
                pass
        return None

    @staticmethod
    def _build_salary_string(js: Dict[str, Any]) -> Optional[str]:
        """Build a human-readable salary string from the var-job JSON fields."""
        sym = js.get('salary_currency_symbol', '£')
        s_min = js.get('salary_min')
        s_max = js.get('salary_max')
        comment = js.get('salary_comment', '')
        if not s_min:
            return comment.strip() if comment else None
        parts = [f"{sym}{s_min}"]
        if s_max and s_max != s_min:
            parts.append(f"to {sym}{s_max}")
        if comment:
            parts.append(comment)
        return ' '.join(parts)
    
    @staticmethod
    def parse_job_detail_page(html_content: str) -> Dict[str, Any]:
        """
        Parse jobs.ac.uk job detail page.

        Extraction priority:
        1. `var job = {...}` embedded JSON (richest structured source)
        2. JSON-LD (schema.org/JobPosting)
        3. HTML elements (h1, lead paragraph, tables, sections, etc.)
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        job_data: Dict[str, Any] = {}

        # ── Source 1: var job JSON (highest priority) ──
        js = JobsAcUkHTMLParser._extract_var_job_json(soup)
        if js:
            if js.get('employer_name'):
                job_data['employer'] = js['employer_name']
            if js.get('department'):
                job_data['department'] = js['department']
            if js.get('title'):
                job_data['title'] = js['title']
            if js.get('reference'):
                job_data['job_ref'] = js['reference']
            if js.get('location'):
                job_data['location'] = js['location']
            if js.get('apply_url'):
                job_data['apply_url'] = js['apply_url']
            if js.get('closing_date'):
                job_data['closing_date'] = js['closing_date']
            if js.get('go_live_date'):
                job_data['placed_on'] = js['go_live_date']
            if js.get('hours'):
                job_data['hours'] = js['hours']
            if js.get('contract'):
                job_data['contract_type'] = js['contract']

            salary_str = JobsAcUkHTMLParser._build_salary_string(js)
            if salary_str:
                job_data['salary'] = salary_str

            jt_list = js.get('job_types')
            if jt_list and isinstance(jt_list, list):
                job_data['job_type'] = ', '.join(
                    jt.get('category_name', '') for jt in jt_list if jt.get('category_name')
                )

            sa_list = js.get('subject_areas')
            if sa_list and isinstance(sa_list, dict):
                job_data['subcategory'] = ', '.join(
                    sa.get('category_name', '') for sa in sa_list.values() if sa.get('category_name')
                )

            job_data['_var_job'] = js

        # ── Source 2: JSON-LD ──
        ld = JobsAcUkHTMLParser._extract_jsonld(soup)
        if ld:
            if not job_data.get('title') and ld.get('title'):
                job_data['title'] = ld['title']
            org = ld.get('hiringOrganization') or {}
            if not job_data.get('employer') and org.get('name'):
                job_data['employer'] = org['name']
            loc = ld.get('jobLocation', {})
            addr = loc.get('address', {}) if isinstance(loc, dict) else {}
            if not job_data.get('location') and addr.get('addressLocality'):
                job_data['location'] = addr['addressLocality']

            # JSON-LD often carries dates and employment type even when JS vars fail.
            if not job_data.get('placed_on') and ld.get('datePosted'):
                job_data['placed_on'] = ld.get('datePosted')
            if not job_data.get('closing_date') and ld.get('validThrough'):
                job_data['closing_date'] = ld.get('validThrough')

            # jobs.ac.uk typically uses "Full Time,Fixed-Term/Contract"
            employment_type = ld.get('employmentType')
            if isinstance(employment_type, str) and employment_type:
                parts = [p.strip() for p in employment_type.split(',') if p.strip()]
                if parts and not job_data.get('hours'):
                    job_data['hours'] = parts[0]
                if len(parts) >= 2 and not job_data.get('contract_type'):
                    job_data['contract_type'] = parts[1]

            # Build a fallback salary string from JSON-LD baseSalary.
            if not job_data.get('salary'):
                base_salary = ld.get('baseSalary')
                if isinstance(base_salary, dict):
                    currency = base_salary.get('currency', '')  # e.g. "GBP"
                    sym = '£' if str(currency).upper() == 'GBP' else '$'
                    value = base_salary.get('value', {}) if isinstance(base_salary.get('value'), dict) else {}
                    minv = value.get('minValue')
                    maxv = value.get('maxValue')
                    try:
                        if minv is not None:
                            minf = float(minv)
                            maxf = float(maxv) if maxv is not None else None
                            if maxf is not None and maxf != minf:
                                job_data['salary'] = f"{sym}{int(minf):,} to {sym}{int(maxf):,}"
                            else:
                                job_data['salary'] = f"{sym}{int(minf):,}"
                    except Exception:
                        pass

            job_data['_jsonld'] = ld

        # ── Source 3: HTML fallbacks ──
        if not job_data.get('title'):
            h1 = soup.find('h1')
            if h1:
                job_data['title'] = HTMLParserUtils.extract_text_from_element(h1)

        # Lead paragraph (employer – department)
        if not job_data.get('employer'):
            lead_p = soup.find('p', class_='lead')
            if lead_p:
                lead_text = HTMLParserUtils.extract_text_from_element(lead_p)
                sep = '–' if lead_text and '–' in lead_text else '-'
                if lead_text and sep in lead_text:
                    parts = lead_text.split(sep, 1)
                    job_data.setdefault('employer', parts[0].strip())
                    if len(parts) >= 2:
                        job_data.setdefault('department', parts[1].strip())

        # jobs.ac.uk often renders employer/department as a grid item:
        #   <... class="j-advert__employer">Employer - Department</...>
        # This is the main missing fallback when JS var extraction fails.
        # institution_name script variable as last-resort employer
        if not job_data.get('employer'):
            emp_el = (
                soup.select_one('.j-advert__employer')
                or soup.select_one('.j-advert_employer')
            )
            if emp_el:
                emp_text = HTMLParserUtils.extract_text_from_element(emp_el)
                if emp_text:
                    parts = re.split(r'\s*[–-]\s*', emp_text, maxsplit=1)
                    if parts and parts[0]:
                        job_data.setdefault('employer', parts[0].strip())
                    if len(parts) >= 2 and parts[1]:
                        job_data.setdefault('department', parts[1].strip())

        # institution_name script variable as last-resort employer
        if not job_data.get('employer'):
            script_vars = HTMLParserUtils.extract_script_variables(soup, ['institution_name'])
            if script_vars.get('institution_name'):
                job_data['employer'] = script_vars['institution_name']

        # job_ref is commonly present as a hidden input even if JS var extraction fails.
        if not job_data.get('job_ref'):
            job_ref_input = soup.find('input', attrs={'type': 'hidden', 'name': 'job_ref'})
            if job_ref_input and job_ref_input.get('value'):
                job_data['job_ref'] = job_ref_input.get('value').strip()

        # Table data (dt/dd or th/td)
        table_data = HTMLParserUtils.extract_table_data(soup)
        for k, v in table_data.items():
            job_data.setdefault(k, v)

        # Type / Role and Subject Area(s) are sometimes rendered as disabled category chips,
        # e.g. <input class="j-form-input__disabled-cat" type="button" value="...">
        # when JS var extraction fails.
        if not job_data.get('job_type') or not job_data.get('subcategory'):
            job_type_vals = []
            subcategory_vals = []
            cat_inputs = soup.select('input.j-form-input__disabled-cat[type="button"][value]')
            for inp in cat_inputs:
                val = (inp.get('value') or '').strip()
                if not val:
                    continue
                # find nearest relevant label <p>...Type / Role...</p> / <p>...Subject Area(s)...</p>
                for prev_p in inp.find_all_previous('p'):
                    prev_text = prev_p.get_text(' ', strip=True)
                    if not prev_text:
                        continue
                    if re.search(r'Type\s*/\s*Role', prev_text, flags=re.IGNORECASE):
                        job_type_vals.append(val)
                        break
                    if re.search(r'Subject\s*Area\(s\)', prev_text, flags=re.IGNORECASE):
                        subcategory_vals.append(val)
                        break
            if job_type_vals and not job_data.get('job_type'):
                job_data['job_type'] = ', '.join(dict.fromkeys(job_type_vals))
            if subcategory_vals and not job_data.get('subcategory'):
                job_data['subcategory'] = ', '.join(dict.fromkeys(subcategory_vals))

        # Full description from paragraphs
        paragraphs = HTMLParserUtils.extract_all_paragraphs(soup, min_length=20)
        if paragraphs:
            job_data['full_description'] = '\n\n'.join(paragraphs)

        # Structured sections
        sections = HTMLParserUtils.extract_structured_sections(
            soup, section_marker='strong', uppercase_only=True, min_length=5
        )
        job_data['sections'] = sections

        if 'RESPONSIBILITIES' in sections:
            job_data.setdefault('responsibilities', sections['RESPONSIBILITIES'])
        if 'ESSENTIAL QUALIFICATIONS/EXPERIENCES' in sections:
            job_data.setdefault('requirements', sections['ESSENTIAL QUALIFICATIONS/EXPERIENCES'])
        elif 'REQUIREMENTS' in sections:
            job_data.setdefault('requirements', sections['REQUIREMENTS'])

        qualifications_sections = []
        for key in sections:
            if 'QUALIFICATION' in key or 'EXPERIENCE' in key or 'REQUIREMENT' in key:
                qualifications_sections.append(sections[key])
        if qualifications_sections and not job_data.get('requirements'):
            job_data['requirements'] = '\n\n'.join(qualifications_sections)

        # List content
        ul_lists = HTMLParserUtils.extract_lists(soup, 'ul')
        if ul_lists:
            job_data['lists'] = ul_lists

        # Apply link HTML fallback
        if not job_data.get('apply_url'):
            apply_link = soup.find('a', id='apply-link')
            if apply_link and apply_link.get('href'):
                job_data['apply_url'] = apply_link['href']
            else:
                # Many jobs.ac.uk pages link out to LSE jobs via a direct Vacancies URL
                vacancy_link = soup.find('a', href=re.compile(r'https?://jobs\\.lse\\.ac\\.uk/Vacancies/', re.IGNORECASE))
                if vacancy_link and vacancy_link.get('href'):
                    job_data['apply_url'] = vacancy_link.get('href').strip()

        # Meta tags
        meta_data = HTMLParserUtils.extract_meta_tags(soup)
        job_data['meta'] = meta_data

        # Clean text fields
        for key, value in list(job_data.items()):
            if isinstance(value, str):
                job_data[key] = HTMLParserUtils.clean_text(value)

        return job_data


# Convenience function
def parse_jobs_ac_uk_page(html_content: str) -> Dict[str, Any]:
    """
    Convenience function: parse jobs.ac.uk job page
    
    Args:
        html_content: HTML content string
        
    Returns:
        Dictionary containing job detail information
    """
    return JobsAcUkHTMLParser.parse_job_detail_page(html_content)

