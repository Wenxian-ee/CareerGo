/**
 * Default filter chips merged with `/api/jobs/meta/filters` (DB distinct values).
 * Code presets are listed first; then API-only values, sorted A–Z.
 */
import { INDUSTRY_PRESETS, WORK_TYPE_PRESETS } from '@/profile/fieldOptions';

export const OTHER = '__OTHER__';

/** UK + CN anchors + remote; full list still merges with DB frequency order from API */
export const LOCATION_CODE_PRESETS = [
  'London',
  'Manchester',
  'Birmingham',
  'Bristol',
  'Leeds',
  'Liverpool',
  'Edinburgh',
  'Glasgow',
  'Cambridge',
  'Oxford',
  'Belfast',
  'Cardiff',
  'Newcastle',
  'Sheffield',
  'Nottingham',
  'Southampton',
  'Remote',
  'UK-wide',
  'Beijing',
  'Shanghai',
  'Shenzhen',
  'Guangzhou',
  'Hangzhou',
  'Chengdu',
  'Nanjing',
  'Wuhan',
  "Xi'an",
  'Hong Kong',
  'China',
] as const;

/** Broad categories — combined with DB categories */
export const CATEGORY_CODE_PRESETS = [
  ...INDUSTRY_PRESETS,
  'Academic or Research',
  'Professional / Managerial / Support Services',
  'STEM',
  'Arts & Humanities',
  'Public sector',
] as const;

/** Job type / contract — combined with DB job_types (mergeFilterOptions dedupes Full-time vs Full Time) */
export const JOB_TYPE_CODE_PRESETS = [
  ...WORK_TYPE_PRESETS,
  'Permanent',
  'Contract',
  'Fixed-term',
  'Temporary',
] as const;

/** Crawler / merge sources often seen in this project */
export const SOURCE_CODE_PRESETS = ['adzuna', 'jobs_ac_uk'] as const;

/** Quick keyword searches — user can still pick “Add my own…” */
export const KEYWORD_CODE_PRESETS = [
  'Python',
  'data',
  'research',
  'lecturer',
  'PhD',
  'software',
  'engineer',
  'finance',
  'remote',
  'graduate',
  'postdoc',
  'teaching',
] as const;

/** Same label with different spacing/hyphen (Full-time vs Full time) → one entry. */
function normDedupeKey(s: string): string {
  return s
    .trim()
    .toLowerCase()
    .replace(/[\s\-_]+/g, '');
}

/** Code presets first (stable order), then API values not already listed, A–Z. */
export function mergeFilterOptions(codePresets: readonly string[], fromApi: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const p of codePresets) {
    const k = normDedupeKey(p);
    if (!k || seen.has(k)) continue;
    seen.add(k);
    out.push(p);
  }
  const rest = fromApi
    .filter((a) => a && !seen.has(normDedupeKey(a)))
    .sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
  for (const r of rest) {
    seen.add(normDedupeKey(r));
    out.push(r);
  }
  return out;
}
