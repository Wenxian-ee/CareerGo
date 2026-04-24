export const WORK_TYPE_PRESETS = ['Full-time', 'Part-time', 'Remote', 'Internship', 'Hybrid'] as const;

export const INSTITUTION_TIER_PRESETS = [
  'Russell Group',
  'Top 10 UK',
  'Top 20 UK',
  'Top 50 UK',
  'Top 100 UK',
  'Top 10 World',
  'Top 50 World',
  'Top 100 World',
] as const;

export const SKILL_CATEGORIES = [
  'Programming Language',
  'Framework',
  'Tool',
  'Domain',
  'Soft Skill',
  'General',
] as const;

export const INDUSTRY_PRESETS = [
  'Technology',
  'Finance',
  'Healthcare',
  'Education',
  'Manufacturing',
  'Retail',
  'Consulting',
  'Media',
  'Government',
  'Non-profit',
] as const;

export const COMPANY_TYPE_PRESETS = [
  'Startup',
  'Scale-up',
  'Enterprise',
  'Foreign',
  'State-owned',
  'Private',
  'Non-profit',
] as const;

/** For preference row when type is Industry */
export const PREFERENCE_INDUSTRY_OPTIONS = [
  'Technology',
  'Finance',
  'Healthcare',
  'Education',
  'Energy',
  'Retail',
  'Other',
] as const;

/** For preference row when type is Company Size */
export const PREFERENCE_COMPANY_SIZE_OPTIONS = [
  '1–50',
  '51–200',
  '201–1000',
  '1000+',
  'Other',
] as const;
