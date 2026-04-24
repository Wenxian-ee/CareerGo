import type { SkillDTO, UserProfilePayload } from '@/api/types';

/** Single-line text: strip control chars and cap length (prevents oversized query strings). */
export const MAX_FILTER_TOKEN_LEN = 120;
export const MAX_NAME_LEN = 200;
export const MAX_USER_ID_LEN = 64;
export const MAX_LIST_ITEMS = 200;
export const MAX_TEXT_FIELD = 8000;

export function stripControlChars(s: string): string {
  return s.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '');
}

export function sanitizeSingleLine(s: string, maxLen: number): string {
  const t = stripControlChars(s).trim();
  if (t.length <= maxLen) return t;
  return t.slice(0, maxLen);
}

export function clamp(n: number, min: number, max: number): number {
  if (!Number.isFinite(n)) return min;
  return Math.min(max, Math.max(min, n));
}

export function clamp01(n: number): number {
  return clamp(n, 0, 1);
}

/** HTTP / API errors → short, actionable copy (English UI). */
export function formatHttpError(status: number, detail: string): string {
  const d = (detail || '').trim();
  const short = d.length > 280 ? `${d.slice(0, 277)}…` : d;

  if (status === 401) {
    return 'Session expired or invalid. Please sign in again.';
  }
  if (status === 403) {
    return short || 'You do not have permission for this action.';
  }
  if (status === 404) {
    return short || 'The requested resource was not found.';
  }
  if (status === 422 || status === 400) {
    return short || 'Some fields were rejected by the server. Check values and try again.';
  }
  if (status === 429) {
    return 'Too many requests. Wait a moment and try again.';
  }
  if (status >= 500) {
    return short || 'Server error. Try again later or contact support if it persists.';
  }
  return short || `Request failed (${status}).`;
}

export function validateLoginInput(user_id: string, password: string): string | null {
  const u = user_id.trim();
  if (!u) return 'Please enter your user ID.';
  if (u.length > MAX_USER_ID_LEN) return `User ID must be at most ${MAX_USER_ID_LEN} characters.`;
  if (!password) return 'Please enter your password.';
  if (password.length > 512) return 'Password is too long.';
  return null;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function validateRegisterInput(p: {
  user_id: string;
  name: string;
  email: string;
  password: string;
}): string | null {
  const uid = p.user_id.trim();
  if (!uid) return 'Please choose a user ID.';
  if (uid.length > MAX_USER_ID_LEN) return `User ID must be at most ${MAX_USER_ID_LEN} characters.`;
  if (!/^[a-zA-Z0-9._-]+$/.test(uid)) {
    return 'User ID may only use letters, digits, dot, underscore, and hyphen.';
  }
  const name = p.name.trim();
  if (!name) return 'Please enter your display name.';
  if (name.length > MAX_NAME_LEN) return `Display name must be at most ${MAX_NAME_LEN} characters.`;
  const em = p.email.trim();
  if (em && !EMAIL_RE.test(em)) return 'Email doesn’t look valid. Leave it blank or fix the format.';
  if (p.password.length < 6) return 'Password must be at least 6 characters.';
  if (p.password.length > 512) return 'Password is too long.';
  return null;
}

export function capStringList(items: string[], maxItems: number, maxItemLen: number): string[] {
  const out: string[] = [];
  for (const x of items) {
    if (out.length >= maxItems) break;
    const t = sanitizeSingleLine(x, maxItemLen);
    if (t) out.push(t);
  }
  return out;
}

const YEAR_MIN = 1950;
const YEAR_MAX = 2100;

/**
 * Clamp and clean profile numbers / lists before sending to API.
 * Does not remove education/skills blocks entirely — use validateProfilePayload for hard errors.
 */
export function sanitizeProfilePayload(input: UserProfilePayload): UserProfilePayload {
  const name = sanitizeSingleLine(input.name, MAX_NAME_LEN) || input.name;

  const defaultYear = new Date().getFullYear();
  const education = (input.education || []).map((e) => ({
    ...e,
    major: sanitizeSingleLine(e.major, 500),
    school: sanitizeSingleLine(e.school, 500),
    ranking: e.ranking != null ? sanitizeSingleLine(String(e.ranking), 200) : e.ranking,
    graduation_year: (() => {
      const y = Math.round(Number(e.graduation_year));
      if (!Number.isFinite(y) || y === 0) return defaultYear;
      return clamp(y, YEAR_MIN, YEAR_MAX);
    })(),
    gpa:
      e.gpa != null && Number.isFinite(Number(e.gpa))
        ? clamp(Number(e.gpa), 0, 5)
        : undefined,
  }));

  const skills = (input.skills || [])
    .filter((s) => sanitizeSingleLine(s.name || '', 200).length > 0)
    .map((s) => {
      const { verified: _omit, ...rest } = s as SkillDTO & { verified?: boolean };
      return {
        ...rest,
        name: sanitizeSingleLine(s.name, 200),
        category: sanitizeSingleLine(s.category || 'General', 120),
        proficiency: clamp01(Number(s.proficiency)),
        years_of_experience: clamp(Number(s.years_of_experience), 0, 60),
      };
    });

  const preferences = (input.preferences || []).map((p) => ({
    ...p,
    value: stripControlChars(p.value || '').slice(0, MAX_TEXT_FIELD),
    weight: clamp01(Number(p.weight)),
  }));

  const c = input.constraints || {
    locations: [],
    industries: [],
    company_types: [],
    exclude_companies: [],
  };

  const constraints = {
    ...c,
    locations: capStringList(c.locations || [], MAX_LIST_ITEMS, 200),
    industries: capStringList(c.industries || [], MAX_LIST_ITEMS, 200),
    company_types: capStringList(c.company_types || [], MAX_LIST_ITEMS, 120),
    exclude_companies: capStringList(c.exclude_companies || [], MAX_LIST_ITEMS, 200),
    work_type: c.work_type != null ? sanitizeSingleLine(String(c.work_type), 120) : c.work_type,
    start_date: c.start_date != null ? sanitizeSingleLine(String(c.start_date), 80) : c.start_date,
    min_salary:
      c.min_salary != null && Number.isFinite(Number(c.min_salary))
        ? Math.max(0, Number(c.min_salary))
        : c.min_salary ?? undefined,
    max_salary:
      c.max_salary != null && Number.isFinite(Number(c.max_salary))
        ? Math.max(0, Number(c.max_salary))
        : c.max_salary ?? undefined,
    max_commute_time:
      c.max_commute_time != null && Number.isFinite(Number(c.max_commute_time))
        ? clamp(Number(c.max_commute_time), 0, 24 * 60)
        : c.max_commute_time ?? undefined,
  };

  const work_experience = (input.work_experience || []).map((w) => ({
    ...w,
    company: sanitizeSingleLine(w.company, 300),
    position: sanitizeSingleLine(w.position, 300),
    duration_years: clamp(Number(w.duration_years), 0, 60),
    responsibilities: capStringList(w.responsibilities || [], 200, 2000),
    achievements: capStringList(w.achievements || [], 200, 2000),
  }));

  const certifications = capStringList(input.certifications || [], MAX_LIST_ITEMS, 500);

  const langs: Record<string, string> = {};
  const entries = Object.entries(input.languages || {});
  let n = 0;
  for (const [k, v] of entries) {
    if (n >= 80) break;
    const kk = sanitizeSingleLine(k, 80);
    const vv = sanitizeSingleLine(v, 200);
    if (kk && vv) {
      langs[kk] = vv;
      n += 1;
    }
  }

  const projects = (input.projects || []).map((proj) => ({
    ...proj,
    name: sanitizeSingleLine(proj.name, 300),
    description: proj.description != null ? stripControlChars(proj.description).slice(0, MAX_TEXT_FIELD) : proj.description,
    url: proj.url != null ? sanitizeSingleLine(String(proj.url), 2000) : proj.url,
    tech_stack: capStringList(proj.tech_stack || [], 100, 120),
  }));

  return {
    ...input,
    user_id: sanitizeSingleLine(input.user_id, MAX_USER_ID_LEN),
    name,
    education,
    skills,
    preferences,
    constraints,
    work_experience,
    certifications,
    languages: langs,
    projects,
  };
}

export function validateProfilePayload(p: UserProfilePayload): string[] {
  const errs: string[] = [];
  if (!p.name?.trim()) errs.push('Display name cannot be empty.');

  p.education?.forEach((e, i) => {
    const y = Number(e.graduation_year);
    if (!Number.isFinite(y) || y < YEAR_MIN || y > YEAR_MAX) {
      errs.push(`Education #${i + 1}: graduation year must be between ${YEAR_MIN} and ${YEAR_MAX}.`);
    }
    if (e.gpa != null && (Number(e.gpa) < 0 || Number(e.gpa) > 5)) {
      errs.push(`Education #${i + 1}: GPA should be between 0 and 5 (or leave blank).`);
    }
  });

  p.skills?.forEach((s, i) => {
    if (Number(s.proficiency) < 0 || Number(s.proficiency) > 1) {
      errs.push(`Skill #${i + 1}: proficiency must be between 0 and 1.`);
    }
    if (Number(s.years_of_experience) < 0 || Number(s.years_of_experience) > 60) {
      errs.push(`Skill #${i + 1}: years of experience must be between 0 and 60.`);
    }
  });

  p.preferences?.forEach((pref, i) => {
    if (Number(pref.weight) < 0 || Number(pref.weight) > 1) {
      errs.push(`Preference #${i + 1}: weight must be between 0 and 1.`);
    }
  });

  const c = p.constraints;
  if (c) {
    const min = c.min_salary;
    const max = c.max_salary;
    if (min != null && max != null && Number(min) > Number(max)) {
      errs.push('Minimum expected salary cannot be greater than maximum salary.');
    }
  }

  p.work_experience?.forEach((w, i) => {
    if (Number(w.duration_years) < 0 || Number(w.duration_years) > 60) {
      errs.push(`Work experience #${i + 1}: duration (years) must be between 0 and 60.`);
    }
  });

  return errs;
}

export type JobFilterDraft = {
  locationSel: string;
  locationOther: string;
  categorySel: string;
  categoryOther: string;
  jobTypeSel: string;
  jobTypeOther: string;
  sourceSel: string;
  sourceOther: string;
  keywordSel: string;
  keywordOther: string;
};

/** Check draft for "Add my own" selected but empty — returns user-facing hints. */
export function jobFilterEmptyCustomHints(d: JobFilterDraft, otherToken: string): string[] {
  const hints: string[] = [];
  const check = (label: string, sel: string, other: string) => {
    if (sel === otherToken && !sanitizeSingleLine(other, MAX_FILTER_TOKEN_LEN)) {
      hints.push(`${label}: custom text is empty — that filter was not applied.`);
    }
  };
  check('Location', d.locationSel, d.locationOther);
  check('Category', d.categorySel, d.categoryOther);
  check('Job type', d.jobTypeSel, d.jobTypeOther);
  check('Source', d.sourceSel, d.sourceOther);
  check('Keywords', d.keywordSel, d.keywordOther);
  return hints;
}

/** Extra hint only when the failure is likely server-side / data, not network or auth. */
export function appendRecommendationsTroubleshooting(message: string): string {
  const m = (message || '').trim();
  if (!m) return message;
  if (m.includes('Cannot reach the API')) return m;
  if (m.includes('Session expired') || m.includes('sign in again')) return m;
  if (m.includes('Too many requests')) return m;
  return `${m} If the API is running, confirm PostgreSQL is up and merged_jobs has job rows.`;
}
