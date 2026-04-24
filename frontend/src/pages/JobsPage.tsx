import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '@/api/client';
import type { HealthResponse, JobRecord } from '@/api/types';
import {
  CATEGORY_CODE_PRESETS,
  JOB_TYPE_CODE_PRESETS,
  KEYWORD_CODE_PRESETS,
  LOCATION_CODE_PRESETS,
  OTHER,
  SOURCE_CODE_PRESETS,
  mergeFilterOptions,
} from '@/constants/jobFilterPresets';
import { StatusBanner } from '@/components/StatusBanner';
import { formatUnknownError } from '@/api/client';
import { jobFilterEmptyCustomHints, sanitizeSingleLine, MAX_FILTER_TOKEN_LEN } from '@/utils/inputGuards';

type Draft = {
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

const emptyDraft = (): Draft => ({
  locationSel: '',
  locationOther: '',
  categorySel: '',
  categoryOther: '',
  jobTypeSel: '',
  jobTypeOther: '',
  sourceSel: '',
  sourceOther: '',
  keywordSel: '',
  keywordOther: '',
});

function resolveSel(sel: string, other: string): string | undefined {
  if (!sel) return undefined;
  if (sel === OTHER) {
    const t = sanitizeSingleLine(other, MAX_FILTER_TOKEN_LEN);
    return t || undefined;
  }
  return sanitizeSingleLine(sel, MAX_FILTER_TOKEN_LEN) || undefined;
}

export function JobsPage() {
  const [items, setItems] = useState<JobRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [apiOk, setApiOk] = useState<boolean | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [applied, setApplied] = useState<Draft>(emptyDraft);
  const [jobTypes, setJobTypes] = useState<string[]>([]);
  const [sources, setSources] = useState<string[]>([]);
  const [locations, setLocations] = useState<string[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [filterHints, setFilterHints] = useState<string[]>([]);
  const [checkingJobId, setCheckingJobId] = useState<string | null>(null);
  const [deadJobIds, setDeadJobIds] = useState<Set<string>>(new Set());

  const locationOptions = useMemo(() => mergeFilterOptions(LOCATION_CODE_PRESETS, locations), [locations]);
  const categoryOptions = useMemo(() => mergeFilterOptions(CATEGORY_CODE_PRESETS, categories), [categories]);
  const jobTypeOptions = useMemo(() => mergeFilterOptions(JOB_TYPE_CODE_PRESETS, jobTypes), [jobTypes]);
  const sourceOptions = useMemo(() => mergeFilterOptions(SOURCE_CODE_PRESETS, sources), [sources]);
  const keywordOptions = useMemo(() => [...KEYWORD_CODE_PRESETS], []);

  useEffect(() => {
    void api.health().then((h: HealthResponse) => setApiOk(h.status === 'ok' && !!h.database));
    void api
      .jobsFilterMeta()
      .then((m) => {
        setSources(m.sources ?? []);
        setJobTypes(m.job_types ?? []);
        setLocations(m.locations ?? []);
        setCategories(m.categories ?? []);
      })
      .catch(() => {
        setSources([]);
        setJobTypes([]);
        setLocations([]);
        setCategories([]);
      });
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const kw = resolveSel(applied.keywordSel, applied.keywordOther);
      const res = await api.listJobs({
        page,
        page_size: pageSize,
        keywords: kw,
        location: resolveSel(applied.locationSel, applied.locationOther),
        category: resolveSel(applied.categorySel, applied.categoryOther),
        job_type: resolveSel(applied.jobTypeSel, applied.jobTypeOther),
        source: resolveSel(applied.sourceSel, applied.sourceOther),
      });
      setItems(res.items ?? []);
      setTotal(res.total ?? 0);
    } catch (e) {
      setErr(formatUnknownError(e));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, applied]);

  useEffect(() => {
    void load();
  }, [load]);

  function applyFilters() {
    setFilterHints(jobFilterEmptyCustomHints(draft, OTHER));
    setApplied({ ...draft });
    setPage(1);
  }

  function clearFilters() {
    const e = emptyDraft();
    setDraft(e);
    setApplied(e);
    setFilterHints([]);
    setPage(1);
  }

  async function handleViewPosting(jobId: string, jobUrl: string) {
    if (deadJobIds.has(jobId)) return;
    setCheckingJobId(jobId);
    try {
      const result = await api.checkJobUrl(jobId);
      if (result.reachable) {
        window.open(jobUrl, '_blank', 'noreferrer');
      } else {
        setDeadJobIds((prev) => new Set(prev).add(jobId));
      }
    } catch {
      // If the check itself fails, open the URL anyway
      window.open(jobUrl, '_blank', 'noreferrer');
    } finally {
      setCheckingJobId(null);
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  useEffect(() => {
    const tp = Math.max(1, Math.ceil(total / pageSize));
    if (page > tp) setPage(tp);
  }, [total, pageSize, page]);

  return (
    <div className="page page-narrow-centered jobs-page" style={{ maxWidth: '900px' }}>
      <header className="page-head">
        <h1 className="page-title">Job catalog</h1>
        <p className="page-sub">
          Explore what&apos;s in the database — pick filters below or jump to personalized picks in{' '}
          <Link to="/recommendations">Recommendations</Link>.
        </p>
      </header>

      {apiOk === false ? (
        <StatusBanner
          kind="error"
          title="Backend not ready"
          detail="The API or database isn’t reachable from this page. Start the server (e.g. uvicorn app:app --port 8000) and refresh."
        />
      ) : null}

      <div className="jobs-filters">
        <div className="field">
          <label className="field-label" htmlFor="jf-loc">
            Location
          </label>
          <select
            id="jf-loc"
            className="input"
            value={draft.locationSel}
            onChange={(e) => setDraft((d) => ({ ...d, locationSel: e.target.value }))}
          >
            <option value="">No location filter</option>
            {locationOptions.map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
            <option value={OTHER}>Add my own location…</option>
          </select>
          {draft.locationSel === OTHER ? (
            <input
              className="input"
              style={{ marginTop: '0.35rem' }}
              placeholder="Type a city or region"
              value={draft.locationOther}
              onChange={(e) => setDraft((d) => ({ ...d, locationOther: e.target.value }))}
            />
          ) : null}
        </div>

        <div className="field">
          <label className="field-label" htmlFor="jf-cat">
            Category
          </label>
          <select
            id="jf-cat"
            className="input"
            value={draft.categorySel}
            onChange={(e) => setDraft((d) => ({ ...d, categorySel: e.target.value }))}
          >
            <option value="">No category filter</option>
            {categoryOptions.map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
            <option value={OTHER}>Add my own category…</option>
          </select>
          {draft.categorySel === OTHER ? (
            <input
              className="input"
              style={{ marginTop: '0.35rem' }}
              placeholder="Category keywords"
              value={draft.categoryOther}
              onChange={(e) => setDraft((d) => ({ ...d, categoryOther: e.target.value }))}
            />
          ) : null}
        </div>

        <div className="field">
          <label className="field-label" htmlFor="jf-jt">
            Job type
          </label>
          <select
            id="jf-jt"
            className="input"
            value={draft.jobTypeSel}
            onChange={(e) => setDraft((d) => ({ ...d, jobTypeSel: e.target.value }))}
          >
            <option value="">No job-type filter</option>
            {jobTypeOptions.map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
            <option value={OTHER}>Add my own job type…</option>
          </select>
          {draft.jobTypeSel === OTHER ? (
            <input
              className="input"
              style={{ marginTop: '0.35rem' }}
              placeholder="e.g. permanent, hybrid"
              value={draft.jobTypeOther}
              onChange={(e) => setDraft((d) => ({ ...d, jobTypeOther: e.target.value }))}
            />
          ) : null}
        </div>

        <div className="field">
          <label className="field-label" htmlFor="jf-src">
            Source
          </label>
          <select
            id="jf-src"
            className="input"
            value={draft.sourceSel}
            onChange={(e) => setDraft((d) => ({ ...d, sourceSel: e.target.value }))}
          >
            <option value="">All sources</option>
            {sourceOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
            <option value={OTHER}>Add my own source…</option>
          </select>
          {draft.sourceSel === OTHER ? (
            <input
              className="input"
              style={{ marginTop: '0.35rem' }}
              placeholder="Source name"
              value={draft.sourceOther}
              onChange={(e) => setDraft((d) => ({ ...d, sourceOther: e.target.value }))}
            />
          ) : null}
        </div>

        <div className="field">
          <label className="field-label" htmlFor="jf-kw">
            Keywords (title / description)
          </label>
          <select
            id="jf-kw"
            className="input"
            value={draft.keywordSel}
            onChange={(e) => setDraft((d) => ({ ...d, keywordSel: e.target.value }))}
          >
            <option value="">No keyword filter</option>
            {keywordOptions.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
            <option value={OTHER}>Add my own keywords…</option>
          </select>
          {draft.keywordSel === OTHER ? (
            <input
              className="input"
              style={{ marginTop: '0.35rem' }}
              placeholder="e.g. React, part-time"
              value={draft.keywordOther}
              onChange={(e) => setDraft((d) => ({ ...d, keywordOther: e.target.value }))}
            />
          ) : null}
        </div>

        <div className="field" style={{ alignSelf: 'flex-end' }}>
          <button type="button" className="btn btn-primary" onClick={applyFilters} disabled={loading}>
            Apply filters
          </button>
        </div>
        <div className="field" style={{ alignSelf: 'flex-end' }}>
          <button type="button" className="btn btn-ghost" onClick={clearFilters} disabled={loading}>
            Reset
          </button>
        </div>
      </div>

      <p className="muted small">
        {total} job{total === 1 ? '' : 's'} found
        {loading ? ' · Loading…' : ''}
      </p>

      {filterHints.length ? (
        <StatusBanner kind="warning" title="Filter note" detail={filterHints.join(' ')} />
      ) : null}

      {err ? <StatusBanner kind="error" title="Couldn’t load jobs" detail={err} /> : null}

      <ul className="job-list">
        {items.map((j) => {
          const isExpired = j.closing_date ? new Date(j.closing_date) < new Date() : false;
          return (
            <li key={j.job_id} className={`job-card${isExpired ? ' job-card--expired' : ''}`}>
              <div className="job-card-head">
                <h2 className="job-title">
                  <Link to={`/jobs/${encodeURIComponent(String(j.job_id))}`}>{j.title || j.job_id}</Link>
                </h2>
                <div className="job-card-actions">
                  {isExpired ? (
                    <span className="badge badge--expired">Closed</span>
                  ) : deadJobIds.has(j.job_id) ? (
                    <span className="badge badge--expired">Unavailable</span>
                  ) : null}
                  {j.job_url ? (
                    isExpired || deadJobIds.has(j.job_id) ? (
                      <span className="link-external link-external--disabled" title={isExpired ? 'This posting has closed' : 'This posting is no longer available on the recruiter\'s site'}>
                        View posting
                      </span>
                    ) : checkingJobId === j.job_id ? (
                      <span className="link-external link-external--checking">Checking…</span>
                    ) : (
                      <button
                        type="button"
                        className="link-external link-external--btn"
                        onClick={() => void handleViewPosting(j.job_id, String(j.job_url))}
                        disabled={checkingJobId !== null}
                      >
                        View posting
                      </button>
                    )
                  ) : null}
                </div>
              </div>
              <p className="job-meta">
                {j.company || '—'} · {j.location || '—'}
                {j.salary ? ` · ${j.salary}` : ''}
                {j.job_type ? ` · ${j.job_type}` : ''}
                {j.source ? ` · ${j.source}` : ''}
              </p>
              {j.closing_date ? (
                <p className={`job-closing${isExpired ? ' job-closing--expired' : ''}`}>
                  {isExpired ? `Closed ${j.closing_date}` : `Closes ${j.closing_date}`}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>

      {total > pageSize ? (
        <div className="pager">
          <button type="button" className="btn btn-ghost" disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)}>
            Previous
          </button>
          <span className="muted small">
            Page {page} of {totalPages}
          </span>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={page >= totalPages || loading}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      ) : null}

      <p className="muted small" style={{ marginTop: '2rem' }}>
        <Link to="/">← Back home</Link>
      </p>
    </div>
  );
}
