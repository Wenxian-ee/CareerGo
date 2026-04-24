import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '@/api/client';
import type {
  EducationDTO,
  PreferenceDTO,
  ProjectDTO,
  SkillDTO,
  UserProfilePayload,
  WorkExperienceDTO,
} from '@/api/types';
import { EDUCATION_LEVELS, PREFERENCE_TYPES } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { NumericInput } from '@/components/NumericInput';
import { StatusBanner } from '@/components/StatusBanner';
import {
  COMPANY_TYPE_PRESETS,
  INDUSTRY_PRESETS,
  INSTITUTION_TIER_PRESETS,
  PREFERENCE_COMPANY_SIZE_OPTIONS,
  PREFERENCE_INDUSTRY_OPTIONS,
  SKILL_CATEGORIES,
  WORK_TYPE_PRESETS,
} from '@/profile/fieldOptions';
import {
  normalizeCertList,
  normalizeMultilineLines,
  normalizeStringList,
  parseCertLinesLive,
  parseLanguagesForSave,
  parseListInputLive,
  parseMultilineLive,
} from '@/profile/parseProfileFields';
import { emptyProfile } from '@/profile/defaultProfile';
import { formatUnknownError } from '@/api/client';
import { MAX_NAME_LEN, sanitizeProfilePayload, validateProfilePayload } from '@/utils/inputGuards';

const OTHER = 'Other';
/** Separates preset tokens (comma-joined) from free-text "other" in preference value */
const PREF_OTHER_SEP = '\u0001';

function formatListForTextarea(items: string[]): string {
  return (items || []).join('\n');
}

type ProfileTextDrafts = {
  locations: string;
  exclude: string;
  certs: string;
  langs: string;
  industriesCustom: string;
  companyTypesCustom: string;
};

function draftsFromForm(f: UserProfilePayload): ProfileTextDrafts {
  return {
    locations: formatListForTextarea(f.constraints.locations || []),
    exclude: formatListForTextarea(f.constraints.exclude_companies || []),
    certs: Array.isArray(f.certifications) ? f.certifications.join('\n') : '',
    langs: Object.entries(f.languages || {})
      .map(([k, v]) => `${k}: ${v}`)
      .join('\n'),
    industriesCustom: formatListForTextarea(
      (f.constraints.industries || []).filter(
        (x) => !INDUSTRY_PRESETS.includes(x as (typeof INDUSTRY_PRESETS)[number]),
      ),
    ),
    companyTypesCustom: formatListForTextarea(
      (f.constraints.company_types || []).filter(
        (x) => !COMPANY_TYPE_PRESETS.includes(x as (typeof COMPANY_TYPE_PRESETS)[number]),
      ),
    ),
  };
}

function isWorkTypePreset(w: string | undefined | null): boolean {
  return !!w && (WORK_TYPE_PRESETS as readonly string[]).includes(w);
}

function isInstitutionTierPreset(r: string | undefined | null): boolean {
  return !!r && (INSTITUTION_TIER_PRESETS as readonly string[]).includes(r);
}

function isSkillCategoryPreset(c: string | undefined | null): boolean {
  return !!c && (SKILL_CATEGORIES as readonly string[]).includes(c);
}

function togglePresetInList(list: string[], preset: string, on: boolean, allPresets: readonly string[]): string[] {
  const custom = list.filter((x) => !allPresets.includes(x));
  const selected = allPresets.filter((p) => list.includes(p));
  const nextSelected = on ? [...new Set([...selected, preset])] : selected.filter((p) => p !== preset);
  return [...nextSelected, ...custom];
}

function preferenceTokens(value: string): string[] {
  return value
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean);
}

function decodePrefWithOther(
  raw: string,
  presets: string[],
): { checked: string[]; other: string } {
  if (raw.includes(PREF_OTHER_SEP)) {
    const [left, right] = raw.split(PREF_OTHER_SEP, 2);
    const checked = preferenceTokens(left).filter((t) => presets.includes(t));
    return { checked, other: right ?? '' };
  }
  const tokens = preferenceTokens(raw);
  const checked = tokens.filter((t) => presets.includes(t));
  const other = tokens.filter((t) => !presets.includes(t)).join(', ');
  return { checked, other };
}

function encodePrefWithOther(checked: string[], other: string): string {
  const left = checked.join(', ');
  if (!other) return left;
  return left ? `${left}${PREF_OTHER_SEP}${other}` : other;
}

const INDUSTRY_PREFS = PREFERENCE_INDUSTRY_OPTIONS.filter((x) => x !== OTHER) as string[];
const COMPANY_SIZE_PREFS = PREFERENCE_COMPANY_SIZE_OPTIONS.filter((x) => x !== OTHER) as string[];

function IndustryPrefValue({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { checked, other } = decodePrefWithOther(value, INDUSTRY_PREFS);
  const [otherDraft, setOtherDraft] = useState(other);
  useEffect(() => {
    setOtherDraft(decodePrefWithOther(value, INDUSTRY_PREFS).other);
  }, [value]);
  return (
    <div className="pref-value-box">
      <span className="field-label">Value</span>
      <div className="checkbox-grid">
        {INDUSTRY_PREFS.map((p) => (
          <label key={p} className="field inline-check">
            <input
              type="checkbox"
              checked={checked.includes(p)}
              onChange={(e) => {
                const next = e.target.checked ? [...new Set([...checked, p])] : checked.filter((x) => x !== p);
                onChange(encodePrefWithOther(next, otherDraft));
              }}
            />
            <span>{p}</span>
          </label>
        ))}
      </div>
      <label className="field">
        <span className="field-label">Other (free text)</span>
        <textarea
          className="textarea"
          rows={2}
          placeholder="Spaces and line breaks are OK; blur or toggle a box to save."
          value={otherDraft}
          onChange={(e) => setOtherDraft(e.target.value)}
          onBlur={() => onChange(encodePrefWithOther(checked, otherDraft))}
        />
      </label>
      <p className="field-hint">Example: tick Technology and describe niche sectors in Other.</p>
    </div>
  );
}

function CompanySizePrefValue({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { checked, other } = decodePrefWithOther(value, COMPANY_SIZE_PREFS);
  const [otherDraft, setOtherDraft] = useState(other);
  useEffect(() => {
    setOtherDraft(decodePrefWithOther(value, COMPANY_SIZE_PREFS).other);
  }, [value]);
  return (
    <div className="pref-value-box">
      <span className="field-label">Value</span>
      <div className="checkbox-grid">
        {COMPANY_SIZE_PREFS.map((p) => (
          <label key={p} className="field inline-check">
            <input
              type="checkbox"
              checked={checked.includes(p)}
              onChange={(e) => {
                const next = e.target.checked ? [...new Set([...checked, p])] : checked.filter((x) => x !== p);
                onChange(encodePrefWithOther(next, otherDraft));
              }}
            />
            <span>{p}</span>
          </label>
        ))}
      </div>
      <label className="field">
        <span className="field-label">Other (free text)</span>
        <textarea
          className="textarea"
          rows={2}
          placeholder="e.g. Prefer smaller teams"
          value={otherDraft}
          onChange={(e) => setOtherDraft(e.target.value)}
          onBlur={() => onChange(encodePrefWithOther(checked, otherDraft))}
        />
      </label>
    </div>
  );
}

function PreferenceValueField({
  row,
  onChange,
}: {
  row: PreferenceDTO;
  onChange: (value: string) => void;
}) {
  if ((row.preference_type as string) === 'Industry') {
    return <IndustryPrefValue value={row.value} onChange={onChange} />;
  }
  if (row.preference_type === 'Company Size') {
    return <CompanySizePrefValue value={row.value} onChange={onChange} />;
  }

  return (
    <label className="field pref-value">
      <span className="field-label">Value / description</span>
      <textarea
        className="textarea"
        rows={2}
        placeholder="Short note about this preference"
        value={row.value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

export function ProfilePage() {
  const { me, token } = useAuth();
  const [form, setForm] = useState<UserProfilePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null);
  const [loadWarning, setLoadWarning] = useState<string | null>(null);
  const [textDrafts, setTextDrafts] = useState<ProfileTextDrafts>({
    locations: '',
    exclude: '',
    certs: '',
    langs: '',
    industriesCustom: '',
    companyTypesCustom: '',
  });

  const load = useCallback(async () => {
    if (!me) return;
    setLoading(true);
    setMsg(null);
    setLoadWarning(null);
    const base = emptyProfile(me.user_id, me.name);
    try {
      const p = await api.getProfile();
      const c = p.constraints || base.constraints;
      const next: UserProfilePayload = {
        ...base,
        ...p,
        user_id: me.user_id,
        name: p.name || me.name,
        education: p.education?.length ? p.education : base.education,
        skills: p.skills?.length ? p.skills : base.skills,
        preferences: p.preferences?.length ? p.preferences : base.preferences,
        constraints: {
          ...base.constraints,
          ...c,
          locations: c.locations ?? [],
          industries: c.industries ?? [],
          company_types: c.company_types ?? [],
          exclude_companies: c.exclude_companies ?? [],
        },
        work_experience: p.work_experience ?? [],
        certifications: p.certifications ?? [],
        languages: p.languages && Object.keys(p.languages).length ? p.languages : base.languages,
        projects: p.projects ?? [],
      };
      setForm(next);
      setTextDrafts(draftsFromForm(next));
    } catch (e) {
      setForm(base);
      setTextDrafts(draftsFromForm(base));
      setLoadWarning(formatUnknownError(e));
    } finally {
      setLoading(false);
    }
  }, [me]);

  useEffect(() => {
    if (token && me) void load();
  }, [token, me, load]);

  async function save() {
    if (!form || !me) return;
    setSaving(true);
    setMsg(null);
    try {
      const presetInd = INDUSTRY_PRESETS.filter((pr) => (form.constraints.industries || []).includes(pr));
      const customInd = normalizeStringList(parseListInputLive(textDrafts.industriesCustom));
      const industriesMerged = [...new Set([...presetInd, ...customInd])];

      const presetCt = COMPANY_TYPE_PRESETS.filter((pr) => (form.constraints.company_types || []).includes(pr));
      const customCt = normalizeStringList(parseListInputLive(textDrafts.companyTypesCustom));
      const companyTypesMerged = [...new Set([...presetCt, ...customCt])];

      const body: UserProfilePayload = {
        ...form,
        user_id: me.user_id,
        name: form.name.trim() || me.name,
        certifications: normalizeCertList(parseCertLinesLive(textDrafts.certs)),
        languages: parseLanguagesForSave(textDrafts.langs),
        constraints: {
          ...form.constraints,
          locations: normalizeStringList(parseListInputLive(textDrafts.locations)),
          exclude_companies: normalizeStringList(parseListInputLive(textDrafts.exclude)),
          industries: industriesMerged,
          company_types: companyTypesMerged,
        },
        work_experience: form.work_experience.map((wx) => ({
          ...wx,
          responsibilities: normalizeMultilineLines(wx.responsibilities || []),
          achievements: normalizeMultilineLines(wx.achievements || []),
        })),
        projects: form.projects.map((proj) => ({
          ...proj,
          tech_stack: normalizeStringList(parseListInputLive((proj.tech_stack || []).join('\n'))),
        })),
      };
      const sanitized = sanitizeProfilePayload(body);
      const validationErrors = validateProfilePayload(sanitized);
      if (validationErrors.length) {
        setMsg({ kind: 'err', text: validationErrors.join(' ') });
        return;
      }
      const saved = await api.putProfile(sanitized);
      const base = emptyProfile(me.user_id, me.name);
      const c = saved.constraints || base.constraints;
      const merged: UserProfilePayload = {
        ...base,
        ...saved,
        constraints: {
          ...base.constraints,
          ...c,
          locations: c.locations ?? [],
          industries: c.industries ?? [],
          company_types: c.company_types ?? [],
          exclude_companies: c.exclude_companies ?? [],
        },
      };
      setForm(merged);
      setTextDrafts(draftsFromForm(merged));
      setMsg({ kind: 'ok', text: 'Profile saved.' });
    } catch (e) {
      setMsg({ kind: 'err', text: formatUnknownError(e) });
    } finally {
      setSaving(false);
    }
  }

  if (!token) {
    return (
      <div className="page page-narrow-centered">
        <p>
          Please <Link to="/login">sign in</Link> first.
        </p>
      </div>
    );
  }

  if (loading || !form) {
    return (
      <p className="muted page-narrow-centered">
        Loading profile…
      </p>
    );
  }

  const setField = (patch: Partial<UserProfilePayload>) => setForm((f) => (f ? { ...f, ...patch } : f));

  const edu = form.education;
  const setEdu = (i: number, p: Partial<EducationDTO>) => {
    const next = [...edu];
    next[i] = { ...next[i], ...p };
    setField({ education: next });
  };
  const addEdu = () =>
    setField({
      education: [
        ...edu,
        { level: 'Bachelor', major: '', school: '', graduation_year: 2024, gpa: undefined, ranking: '' },
      ],
    });

  const skills = form.skills;
  const setSkill = (i: number, p: Partial<SkillDTO>) => {
    const next = [...skills];
    next[i] = { ...next[i], ...p };
    setField({ skills: next });
  };
  const addSkill = () =>
    setField({
      skills: [...skills, { name: '', proficiency: 0.5, years_of_experience: 0, category: 'General' }],
    });

  const prefs = form.preferences;
  const setPref = (i: number, p: Partial<PreferenceDTO>) => {
    const next = [...prefs];
    next[i] = { ...next[i], ...p };
    setField({ preferences: next });
  };
  const addPref = () =>
    setField({
      preferences: [...prefs, { preference_type: 'Company Size', value: '', weight: 0.8 }],
    });

  const wx = form.work_experience;
  const setWx = (i: number, p: Partial<WorkExperienceDTO>) => {
    const next = [...wx];
    next[i] = { ...next[i], ...p };
    setField({ work_experience: next });
  };
  const addWx = () =>
    setField({
      work_experience: [
        ...wx,
        { company: '', position: '', duration_years: 0, responsibilities: [], achievements: [] },
      ],
    });

  const projs = form.projects;
  const setProj = (i: number, p: Partial<ProjectDTO>) => {
    const next = [...projs];
    next[i] = { ...next[i], ...p };
    setField({ projects: next });
  };
  const addProj = () =>
    setField({
      projects: [...projs, { name: '', description: '', tech_stack: [] }],
    });

  const industries = form.constraints.industries || [];
  const companyTypes = form.constraints.company_types || [];
  const wt = form.constraints.work_type ?? '';

  return (
    <div className="page profile-page page-narrow-centered">
      <header className="page-head">
        <h1 className="page-title">My profile</h1>
        <p className="page-sub">
          Same fields as <code>user_profile.UserProfile</code> and the database, used for matching and ranking.
        </p>
      </header>

      {loadWarning ? (
        <StatusBanner
          kind="warning"
          title="Could not load saved profile from the server"
          detail={`${loadWarning} Showing empty defaults — you can still edit and save.`}
        />
      ) : null}
      {msg?.kind === 'ok' ? <StatusBanner kind="success" title={msg.text} /> : null}
      {msg?.kind === 'err' ? <StatusBanner kind="error" title="Save failed" detail={msg.text} /> : null}

      <section className="form-section">
        <h2 className="section-title">Basic information</h2>
        <label className="field">
          <span className="field-label">Display name</span>
          <p className="field-hint">Example: Alex Chen (shown on your account).</p>
          <input
            className="input"
            placeholder="Alex Chen"
            maxLength={MAX_NAME_LEN}
            value={form.name}
            onChange={(e) => setField({ name: e.target.value })}
          />
        </label>
      </section>

      <section className="form-section">
        <h2 className="section-title">Education</h2>
        <p className="field-hint section-hint">Add one block per degree. Example: Bachelor in CS at Sample University, 2025.</p>
        {edu.map((row, i) => {
          const rankingSelectVal = isInstitutionTierPreset(row.ranking)
            ? (row.ranking as string)
            : row.ranking == null
              ? ''
              : OTHER;
          const showCustomRanking = rankingSelectVal === OTHER;
          return (
            <div key={i} className="repeat-block">
              <div className="row-2">
                <label className="field">
                  <span className="field-label">Level</span>
                  <select
                    className="input"
                    value={row.level}
                    onChange={(e) => setEdu(i, { level: e.target.value as EducationDTO['level'] })}
                  >
                    {EDUCATION_LEVELS.map((l) => (
                      <option key={l} value={l}>
                        {l}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span className="field-label">Graduation year</span>
                  <NumericInput
                    className="input"
                    value={row.graduation_year}
                    onChange={(v) => setEdu(i, { graduation_year: v })}
                    fallback={new Date().getFullYear()}
                  />
                </label>
              </div>
              <label className="field">
                <span className="field-label">Major</span>
                <input
                  className="input"
                  placeholder="e.g. Computer Science"
                  value={row.major}
                  onChange={(e) => setEdu(i, { major: e.target.value })}
                />
              </label>
              <label className="field">
                <span className="field-label">School</span>
                <input
                  className="input"
                  placeholder="e.g. University of Example"
                  value={row.school}
                  onChange={(e) => setEdu(i, { school: e.target.value })}
                />
              </label>
              <div className="row-2">
                <label className="field">
                  <span className="field-label">GPA (optional)</span>
                  <input
                    className="input"
                    type="number"
                    step="0.01"
                    placeholder="3.7"
                    value={row.gpa ?? ''}
                    onChange={(e) => setEdu(i, { gpa: e.target.value ? Number(e.target.value) : undefined })}
                  />
                </label>
                <label className="field">
                  <span className="field-label">Institution tier</span>
                  <select
                    className="input"
                    value={rankingSelectVal}
                    onChange={(e) => {
                      const v = e.target.value;
                      if (v === '') setEdu(i, { ranking: null });
                      else if (v === OTHER) setEdu(i, { ranking: '' });
                      else setEdu(i, { ranking: v });
                    }}
                  >
                    <option value="">— Not specified —</option>
                    {INSTITUTION_TIER_PRESETS.map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                    <option value={OTHER}>Other</option>
                  </select>
                  {showCustomRanking ? (
                    <input
                      className="input"
                      style={{ marginTop: '0.5rem' }}
                      placeholder="e.g. G5 Institutions, Ivy League"
                      value={row.ranking ?? ''}
                      onChange={(e) => setEdu(i, { ranking: e.target.value })}
                    />
                  ) : null}
                </label>
              </div>
            </div>
          );
        })}
        <button type="button" className="btn btn-ghost" onClick={addEdu}>
          + Add education
        </button>
      </section>

      <section className="form-section">
        <h2 className="section-title">Skills</h2>
        <p className="field-hint section-hint">Example: Python · programming language · 0.85 proficiency · 2 years.</p>
        {skills.map((row, i) => {
          const cat = row.category || 'General';
          const catSelect = isSkillCategoryPreset(cat) ? cat : OTHER;
          const catCustom = isSkillCategoryPreset(cat) ? '' : cat;
          return (
            <div key={i} className="repeat-block">
              <div className="row-2">
                <label className="field">
                  <span className="field-label">Skill name</span>
                  <input
                    className="input"
                    placeholder="e.g. Python"
                    value={row.name}
                    onChange={(e) => setSkill(i, { name: e.target.value })}
                  />
                </label>
                <label className="field">
                  <span className="field-label">Category</span>
                  <select
                    className="input"
                    value={catSelect}
                    onChange={(e) => {
                      const v = e.target.value;
                      if (v === OTHER) setSkill(i, { category: catCustom || '' });
                      else setSkill(i, { category: v });
                    }}
                  >
                    {SKILL_CATEGORIES.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                    <option value={OTHER}>{OTHER}</option>
                  </select>
                </label>
              </div>
              {catSelect === OTHER ? (
                <label className="field">
                  <span className="field-label">Custom category</span>
                  <input
                    className="input"
                    placeholder="e.g. Cloud platform"
                    value={catCustom}
                    onChange={(e) => setSkill(i, { category: e.target.value })}
                  />
                </label>
              ) : null}
              <div className="row-2">
                <label className="field">
                  <span className="field-label">Proficiency (0–1)</span>
                  <NumericInput
                    className="input"
                    step="0.05"
                    min={0}
                    max={1}
                    value={row.proficiency}
                    onChange={(v) => setSkill(i, { proficiency: v })}
                  />
                </label>
                <label className="field">
                  <span className="field-label">Years</span>
                  <NumericInput
                    className="input"
                    step="0.5"
                    min={0}
                    value={row.years_of_experience}
                    onChange={(v) => setSkill(i, { years_of_experience: v })}
                  />
                </label>
              </div>
            </div>
          );
        })}
        <button type="button" className="btn btn-ghost" onClick={addSkill}>
          + Add skill
        </button>
      </section>

      <section className="form-section">
        <h2 className="section-title">Preferences</h2>
        <p className="field-hint section-hint">Weight how much each preference matters (0–1). Use Industry or Company Size for structured options.</p>
        {prefs.map((row, i) => (
          <div key={i} className="repeat-block pref-grid">
            <label className="field">
              <span className="field-label">Type</span>
              <select
                className="input"
                value={row.preference_type}
                onChange={(e) =>
                  setPref(i, { preference_type: e.target.value as PreferenceDTO['preference_type'], value: '' })
                }
              >
                {PREFERENCE_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field-label">Weight (0–1)</span>
              <NumericInput
                className="input"
                step="0.05"
                min={0}
                max={1}
                value={row.weight}
                onChange={(v) => setPref(i, { weight: v })}
              />
            </label>
            <PreferenceValueField row={row} onChange={(value) => setPref(i, { value })} />
          </div>
        ))}
        <button type="button" className="btn btn-ghost" onClick={addPref}>
          + Add preference
        </button>
      </section>

      <section className="form-section">
        <h2 className="section-title">Hard constraints</h2>
        <p className="field-hint section-hint">Locations and lists: one item per line, or separate with commas. Internal spaces are kept.</p>
        <label className="field">
          <span className="field-label">Preferred locations</span>
          <textarea
            className="textarea"
            rows={3}
            placeholder={'London\nManchester'}
            value={textDrafts.locations}
            onChange={(e) => setTextDrafts((d) => ({ ...d, locations: e.target.value }))}
          />
          <p className="field-hint">Example cities or regions you would accept.</p>
        </label>
        <div className="salary-range-card">
          <div className="salary-range-head">
            <span className="field-label salary-range-title">Expected salary</span>
            <span className="salary-unit-pill" title="Annual total, same numeric scale as job salary fields">
              Annual
            </span>
          </div>
          <p className="field-hint salary-range-hint">
            Yearly totals only, in the <strong>same numeric unit</strong> as your job table (
            <code className="salary-code">salary_min</code> / <code className="salary-code">salary_max</code>
            ). Many UK feeds use plain GBP/year; other pipelines may differ — match whatever you imported.
          </p>
          <div className="salary-range-row" role="group" aria-label="Expected salary range">
            <label className="field salary-range-field">
              <span className="field-label">Minimum</span>
              <div className="input-with-suffix">
                <input
                  className="input"
                  type="number"
                  inputMode="decimal"
                  min={0}
                  step={1}
                  placeholder="e.g. 28000"
                  value={form.constraints.min_salary ?? ''}
                  onChange={(e) =>
                    setField({
                      constraints: {
                        ...form.constraints,
                        min_salary: e.target.value ? Number(e.target.value) : undefined,
                      },
                    })
                  }
                />
                <span className="input-suffix">/ yr</span>
              </div>
            </label>
            <span className="salary-range-divider" aria-hidden="true">
              —
            </span>
            <label className="field salary-range-field">
              <span className="field-label">Maximum</span>
              <div className="input-with-suffix">
                <input
                  className="input"
                  type="number"
                  inputMode="decimal"
                  min={0}
                  step={1}
                  placeholder="e.g. 55000"
                  value={form.constraints.max_salary ?? ''}
                  onChange={(e) =>
                    setField({
                      constraints: {
                        ...form.constraints,
                        max_salary: e.target.value ? Number(e.target.value) : undefined,
                      },
                    })
                  }
                />
                <span className="input-suffix">/ yr</span>
              </div>
            </label>
          </div>
        </div>
        <label className="field">
          <span className="field-label">Work arrangement</span>
          <div className="row-2">
            <select
              className="input"
              value={isWorkTypePreset(wt) ? wt : OTHER}
              onChange={(e) => {
                const v = e.target.value;
                if (v === OTHER) {
                  setField({ constraints: { ...form.constraints, work_type: '' } });
                } else {
                  setField({ constraints: { ...form.constraints, work_type: v } });
                }
              }}
            >
              {WORK_TYPE_PRESETS.map((w) => (
                <option key={w} value={w}>
                  {w}
                </option>
              ))}
              <option value={OTHER}>{OTHER}</option>
            </select>
          </div>
          {!isWorkTypePreset(wt) ? (
            <input
              className="input"
              style={{ marginTop: '0.5rem' }}
              placeholder="Describe arrangement, e.g. 4 days on-site"
              value={wt}
              onChange={(e) =>
                setField({
                  constraints: { ...form.constraints, work_type: e.target.value || undefined },
                })
              }
            />
          ) : null}
          <p className="field-hint">Pick a preset or Other and describe your situation.</p>
        </label>
        <label className="field">
          <span className="field-label">Earliest start date</span>
          <input
            className="input"
            type="date"
            value={form.constraints.start_date?.slice(0, 10) ?? ''}
            onChange={(e) =>
              setField({
                constraints: { ...form.constraints, start_date: e.target.value || undefined },
              })
            }
          />
        </label>

        <div className="field">
          <span className="field-label">Preferred industries</span>
          <p className="field-hint">Tick common sectors and/or add custom lines below.</p>
          <div className="checkbox-grid">
            {INDUSTRY_PRESETS.map((p) => (
              <label key={p} className="field inline-check">
                <input
                  type="checkbox"
                  checked={industries.includes(p)}
                  onChange={(e) =>
                    setField({
                      constraints: {
                        ...form.constraints,
                        industries: togglePresetInList(industries, p, e.target.checked, INDUSTRY_PRESETS),
                      },
                    })
                  }
                />
                <span>{p}</span>
              </label>
            ))}
          </div>
          <label className="field">
            <span className="field-label">Custom industries</span>
            <textarea
              className="textarea"
              rows={2}
              placeholder="e.g. Aerospace"
              value={textDrafts.industriesCustom}
              onChange={(e) => setTextDrafts((d) => ({ ...d, industriesCustom: e.target.value }))}
            />
          </label>
        </div>

        <div className="field">
          <span className="field-label">Company types</span>
          <div className="checkbox-grid">
            {COMPANY_TYPE_PRESETS.map((p) => (
              <label key={p} className="field inline-check">
                <input
                  type="checkbox"
                  checked={companyTypes.includes(p)}
                  onChange={(e) =>
                    setField({
                      constraints: {
                        ...form.constraints,
                        company_types: togglePresetInList(companyTypes, p, e.target.checked, COMPANY_TYPE_PRESETS),
                      },
                    })
                  }
                />
                <span>{p}</span>
              </label>
            ))}
          </div>
          <label className="field">
            <span className="field-label">Custom company types</span>
            <textarea
              className="textarea"
              rows={2}
              placeholder="e.g. Family business"
              value={textDrafts.companyTypesCustom}
              onChange={(e) => setTextDrafts((d) => ({ ...d, companyTypesCustom: e.target.value }))}
            />
          </label>
        </div>

        <label className="field">
          <span className="field-label">Excluded companies</span>
          <textarea
            className="textarea"
            rows={2}
            placeholder={'Company A\nCompany B'}
            value={textDrafts.exclude}
            onChange={(e) => setTextDrafts((d) => ({ ...d, exclude: e.target.value }))}
          />
          <p className="field-hint">Employers you do not want to be matched with.</p>
        </label>
      </section>

      <section className="form-section">
        <h2 className="section-title">Work experience</h2>
        <p className="field-hint section-hint">Responsibilities: one bullet per line; commas inside a line are OK.</p>
        {wx.map((row, i) => (
          <div key={i} className="repeat-block">
            <div className="row-2">
              <label className="field">
                <span className="field-label">Company</span>
                <input
                  className="input"
                  placeholder="e.g. Acme Ltd"
                  value={row.company}
                  onChange={(e) => setWx(i, { company: e.target.value })}
                />
              </label>
              <label className="field">
                <span className="field-label">Role</span>
                <input
                  className="input"
                  placeholder="e.g. Software engineer intern"
                  value={row.position}
                  onChange={(e) => setWx(i, { position: e.target.value })}
                />
              </label>
            </div>
            <label className="field">
              <span className="field-label">Duration (years)</span>
              <NumericInput
                className="input"
                step="0.25"
                min={0}
                value={row.duration_years}
                onChange={(v) => setWx(i, { duration_years: v })}
              />
            </label>
            <label className="field">
              <span className="field-label">Responsibilities (one per line)</span>
              <textarea
                className="textarea"
                rows={3}
                placeholder={'Shipped feature X\nReviewed pull requests'}
                value={(row.responsibilities || []).join('\n')}
                onChange={(e) => setWx(i, { responsibilities: parseMultilineLive(e.target.value) })}
              />
            </label>
            <label className="field">
              <span className="field-label">Achievements (one per line)</span>
              <textarea
                className="textarea"
                rows={2}
                placeholder={'Reduced latency by 20%'}
                value={(row.achievements || []).join('\n')}
                onChange={(e) => setWx(i, { achievements: parseMultilineLive(e.target.value) })}
              />
            </label>
          </div>
        ))}
        <button type="button" className="btn btn-ghost" onClick={addWx}>
          + Add work experience
        </button>
      </section>

      <section className="form-section">
        <h2 className="section-title">Certifications</h2>
        <p className="field-hint section-hint">One certification per line. Commas inside a name stay on one line.</p>
        <label className="field field--block">
          <span className="field-label">Certifications</span>
          <textarea
            className="textarea"
            rows={3}
            placeholder={'AWS Certified Developer\nIELTS 7.5'}
            value={textDrafts.certs}
            onChange={(e) => setTextDrafts((d) => ({ ...d, certs: e.target.value }))}
          />
        </label>
      </section>

      <section className="form-section">
        <h2 className="section-title">Languages</h2>
        <p className="field-hint section-hint">One line per language. Example: English: Fluent</p>
        <label className="field field--block">
          <span className="field-label">Languages</span>
          <textarea
            className="textarea"
            rows={3}
            placeholder={'English: Fluent\nMandarin: Native'}
            value={textDrafts.langs}
            onChange={(e) => setTextDrafts((d) => ({ ...d, langs: e.target.value }))}
          />
        </label>
      </section>

      <section className="form-section">
        <h2 className="section-title">Projects</h2>
        {projs.map((row, i) => (
          <div key={i} className="repeat-block">
            <label className="field">
              <span className="field-label">Project name</span>
              <input
                className="input"
                placeholder="e.g. Course recommender"
                value={row.name}
                onChange={(e) => setProj(i, { name: e.target.value })}
              />
            </label>
            <label className="field">
              <span className="field-label">Description</span>
              <textarea
                className="textarea"
                rows={2}
                placeholder="What you built and the outcome."
                value={row.description ?? ''}
                onChange={(e) => setProj(i, { description: e.target.value })}
              />
            </label>
            <label className="field">
              <span className="field-label">Tech stack</span>
              <textarea
                className="textarea"
                rows={2}
                placeholder={'Python\nReact'}
                value={formatListForTextarea(row.tech_stack || [])}
                onChange={(e) => setProj(i, { tech_stack: parseMultilineLive(e.target.value) })}
              />
              <p className="field-hint">One technology per line; commas are also OK (applied on save).</p>
            </label>
          </div>
        ))}
        <button type="button" className="btn btn-ghost" onClick={addProj}>
          + Add project
        </button>
      </section>

      <div className="toolbar sticky-actions toolbar-centered">
        {saving ? (
          <div className="progress-bar-wrap" style={{ width: '100%', maxWidth: '36rem' }}>
            <div className="progress-bar-indeterminate" />
          </div>
        ) : null}
        <button type="button" className="btn btn-primary" disabled={saving} onClick={() => void save()}>
          {saving ? 'Saving…' : 'Save profile'}
        </button>
        <Link className="btn btn-ghost" to="/recommendations">
          Go to recommendations →
        </Link>
      </div>
    </div>
  );
}
