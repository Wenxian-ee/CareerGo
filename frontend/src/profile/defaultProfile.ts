import type { UserProfilePayload } from '@/api/types';

export function emptyProfile(userId: string, name: string): UserProfilePayload {
  return {
    user_id: userId,
    name,
    education: [
      {
        level: 'Bachelor',
        major: '',
        school: '',
        graduation_year: new Date().getFullYear(),
        gpa: undefined,
        ranking: '',
      },
    ],
    skills: [{ name: '', proficiency: 0.7, years_of_experience: 1, category: 'Programming Language' }],
    preferences: [
      { preference_type: 'Company Size', value: '', weight: 0.8 },
    ],
    constraints: {
      locations: [],
      min_salary: undefined,
      max_salary: undefined,
      work_type: 'Full-time',
      start_date: undefined,
      industries: [],
      company_types: [],
      exclude_companies: [],
      max_commute_time: undefined,
    },
    work_experience: [],
    certifications: [],
    languages: { English: 'Fluent', Mandarin: 'Conversational' },
    projects: [],
  };
}
