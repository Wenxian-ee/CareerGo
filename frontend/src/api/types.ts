/** Aligns with MatchingRanking/user_profile and to_dict */

export const EDUCATION_LEVELS = [
  'High School',
  'Associate',
  'Bachelor',
  'Master',
  'PhD',
] as const;

export const PREFERENCE_TYPES = [
  'Industry',
  'Company Size',
  'Work-Life Balance',
  'Career Growth',
  'Innovation',
] as const;

export interface EducationDTO {
  level: (typeof EDUCATION_LEVELS)[number];
  major: string;
  school: string;
  graduation_year: number;
  gpa?: number | null;
  ranking?: string | null;
}

export interface SkillDTO {
  name: string;
  proficiency: number;
  years_of_experience: number;
  category: string;
  raw_name?: string | null;
  esco_skill_id?: number | null;
  similarity_score?: number | null;
  normalization_method?: string | null;
}

export interface PreferenceDTO {
  preference_type: (typeof PREFERENCE_TYPES)[number];
  value: string;
  weight: number;
}

export interface ConstraintsDTO {
  locations: string[];
  min_salary?: number | null;
  max_salary?: number | null;
  work_type?: string | null;
  start_date?: string | null;
  industries: string[];
  company_types: string[];
  exclude_companies: string[];
  max_commute_time?: number | null;
}

export interface WorkExperienceDTO {
  company: string;
  position: string;
  duration_years: number;
  responsibilities: string[];
  achievements: string[];
}

export interface ProjectDTO {
  name: string;
  description?: string;
  tech_stack?: string[];
  url?: string;
}

export interface UserProfilePayload {
  user_id: string;
  name: string;
  education: EducationDTO[];
  skills: SkillDTO[];
  preferences: PreferenceDTO[];
  constraints: ConstraintsDTO;
  work_experience: WorkExperienceDTO[];
  certifications: string[];
  languages: Record<string, string>;
  projects: ProjectDTO[];
}

export interface JobRecord {
  job_id: string;
  title: string;
  employer?: string;
  company?: string;
  location?: string;
  salary?: string | null;
  salary_text?: string | null;
  salary_min?: number | null;
  salary_max?: number | null;
  description?: string;
  description_preview?: string;
  requirements?: string;
  required_skills?: string[];
  preferred_skills?: string[];
  job_url?: string | null;
  job_type?: string | null;
  source?: string | null;
  category?: string | null;
  closing_date?: string | null;
  published_date?: string | null;
  scraped_at?: string | null;
  url?: string | null;
  apply_url?: string | null;
  [key: string]: unknown;
}

export interface JobsListResponse {
  items: JobRecord[];
  total?: number;
  page?: number;
  page_size?: number;
}

/** Aligns with llm_reasoner output / API `reasoning` object */
export interface JobReasoningPayload {
  source?: string;
  recommendation_reasoning?: string;
  strengths?: string[];
  skill_gaps?: Array<{
    skill: string;
    importance?: string;
    status?: string;
    reason?: string;
  }>;
  learning_suggestions?: string[];
  fallback_reason?: string;
  matched_skills?: string[];
}

export interface ScoreBreakdownComponent {
  value?: number | null;
  effective_weight?: number | null;
}

export interface ScoreBreakdownBucket {
  components?: Record<string, ScoreBreakdownComponent>;
  missing?: string[];
  normalization_note?: string;
}

export interface RecommendationScoreBreakdown {
  relevance?: ScoreBreakdownBucket | null;
  feasibility?: ScoreBreakdownBucket | null;
  growth?: ScoreBreakdownBucket | null;
}

export interface JobReasoningApiResponse {
  job_id: string;
  job_url?: string | null;
  title?: string;
  company?: string;
  location?: string;
  salary?: string;
  constraints_satisfied?: boolean;
  scores: {
    match_score: number;
    final_score: number;
    relevance: number;
    feasibility: number;
    growth: number;
  };
  score_breakdown?: RecommendationScoreBreakdown | null;
  reasoning: JobReasoningPayload;
}

export interface RecommendationItem {
  job_id: string;
  title: string;
  company?: string;
  location?: string;
  salary?: string;
  job_url?: string | null;
  job_type?: string | null;
  industry?: string | null;
  department?: string | null;
  hours?: string | null;
  closing_date?: string | null;
  source?: string | null;
  category?: string | null;
  description_snippet?: string | null;
  score?: number | null;
  rank?: number;
  relevance?: number | null;
  feasibility?: number | null;
  growth?: number | null;
  match_score?: number | null;
  explanation?: string;
  matched_at?: string | null;
  reasoning?: JobReasoningPayload | Record<string, unknown>;
  score_breakdown?: RecommendationScoreBreakdown | null;
}

export interface JobsBrowseResponse {
  items: JobRecord[];
  total: number;
  page: number;
  page_size: number;
}

export interface RecommendationsDiagnostics {
  jobs_loaded?: number;
  /** null = no SQL LIMIT (entire merged_jobs) */
  jobs_query_limit?: number | null;
  used_relaxed_match?: boolean;
  empty_reason?: string | null;
  /** Server-side timing in milliseconds */
  latency_matching_ranking_ms?: number | null;
  latency_llm_ms?: number | null;
  latency_total_ms?: number | null;
}

export interface RecommendationsResponse {
  user_id: string;
  items: RecommendationItem[];
  computed_at?: string;
  diagnostics?: RecommendationsDiagnostics;
}

export interface HealthResponse {
  status: string;
  database?: boolean;
  version?: string;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  name: string;
}
