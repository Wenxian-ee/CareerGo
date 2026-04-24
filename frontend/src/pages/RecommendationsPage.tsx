import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, formatUnknownError } from '@/api/client';
import type {
  JobReasoningApiResponse,
  RecommendationItem,
  RecommendationScoreBreakdown,
  RecommendationsDiagnostics,
} from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { JobSkillGraph } from '@/components/JobSkillGraph';
import { StatusBanner } from '@/components/StatusBanner';
import { appendRecommendationsTroubleshooting } from '@/utils/inputGuards';

function pct(x: number | null | undefined, digits = 2): string {
  if (x == null || Number.isNaN(x)) return '—';
  return `${(x * 100).toFixed(digits)}%`;
}

function renderBreakdownBucket(
  title: string,
  bucket: RecommendationScoreBreakdown[keyof RecommendationScoreBreakdown],
) {
  const components = bucket?.components ?? {};
  const entries = Object.entries(components).filter(([, v]) => v && v.value != null);
  if (!entries.length) return null;
  return (
    <div>
      <p className="modal-h3" style={{ fontSize: '1rem', marginTop: '0.75rem' }}>{title}</p>
      <ul>
        {entries.map(([name, v]) => (
          <li key={name}>
            {name}: {pct(v?.value ?? undefined)}{' '}
            {v?.effective_weight != null ? `(w=${(v.effective_weight * 100).toFixed(1)}%)` : ''}
          </li>
        ))}
      </ul>
      {bucket?.missing?.length ? (
        <p className="muted small">Missing: {bucket.missing.join(', ')}</p>
      ) : null}
    </div>
  );
}

function emptyReasonMessage(d: RecommendationsDiagnostics | null | undefined): string {
  const r = d?.empty_reason;
  if (r === 'no_jobs_in_database') {
    return 'No rows in merged_jobs — import or crawl job data first.';
  }
  if (r === 'no_matches_after_constraints') {
    return 'Jobs were loaded, but none passed hard constraints and the match threshold (even after relaxing the score floor). Try widening location or salary in your profile, or check work type.';
  }
  return '';
}

export function RecommendationsPage() {
  const { token } = useAuth();
  const [items, setItems] = useState<RecommendationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [computing, setComputing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [computedAt, setComputedAt] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<RecommendationsDiagnostics | null>(null);
  /** Latest POST returned zero items but GET still had rows from matching_history */
  const [showingHistoryFallback, setShowingHistoryFallback] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [detailItem, setDetailItem] = useState<RecommendationItem | null>(null);
  const [learning, setLearning] = useState<JobReasoningApiResponse | null>(null);
  const [learningLoading, setLearningLoading] = useState(false);
  const [learningErr, setLearningErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await api.getRecommendations();
      setItems(res.items ?? []);
      setComputedAt(null);
      setDiagnostics(null);
      setShowingHistoryFallback(false);
    } catch (e) {
      setErr(formatUnknownError(e));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  useEffect(() => {
    if (!computing) {
      setElapsedSeconds(0);
      return;
    }
    setElapsedSeconds(0);
    const interval = setInterval(() => setElapsedSeconds((s) => s + 1), 1000);
    return () => clearInterval(interval);
  }, [computing]);

  const fetchLearningPath = useCallback(async (jobId: string) => {
    const id = (jobId || '').trim();
    if (!id) {
      setLearningErr('Missing job id — close and reopen this detail.');
      setLearning(null);
      return;
    }
    setLearningLoading(true);
    setLearningErr(null);
    try {
      const res = await api.getLearningInsights(id);
      setLearning(res);
    } catch (e) {
      setLearningErr(formatUnknownError(e));
      setLearning(null);
    } finally {
      setLearningLoading(false);
    }
  }, []);

  useEffect(() => {
    setLearning(null);
    setLearningErr(null);
    if (!detailItem) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setDetailItem(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [detailItem]);

  async function compute() {
    setComputing(true);
    setErr(null);
    setShowingHistoryFallback(false);
    try {
      const res = await api.postRecommendations(10);
      const postItems = res.items ?? [];
      setDiagnostics(res.diagnostics ?? null);
      setComputedAt(res.computed_at ?? null);

      if (postItems.length === 0) {
        try {
          const hist = await api.getRecommendations();
          const histItems = hist.items ?? [];
          if (histItems.length > 0) {
            setItems(histItems);
            setShowingHistoryFallback(true);
            return;
          }
        } catch {
          /* ignore */
        }
        setItems([]);
      } else {
        setItems(postItems);
      }
    } catch (e) {
      setErr(formatUnknownError(e));
    } finally {
      setComputing(false);
    }
  }

  if (!token) {
    return (
      <div className="page page-narrow-centered">
        <p>
          Please <Link to="/login">sign in</Link> and complete your profile first.
        </p>
      </div>
    );
  }

  const diagHint = emptyReasonMessage(diagnostics);
  const relaxedNote = diagnostics?.used_relaxed_match
    ? 'Relaxed match threshold was used so jobs above hard constraints could still rank.'
    : null;

  return (
    <div className="page page-narrow-centered recommendations-page">
      <header className="page-head">
        <h1 className="page-title">Your picks</h1>
        <p className="page-sub">
          We match your profile to open roles, rank them, and add short explanations. Hit refresh anytime after you
          update your profile.
        </p>
      </header>

      <div className="toolbar toolbar-centered">
        <button type="button" className="btn btn-ghost" onClick={() => void load()} disabled={loading || computing}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
        <button type="button" className="btn btn-primary" onClick={() => void compute()} disabled={computing}>
          {computing ? 'Updating…' : 'Update recommendations'}
        </button>
        <Link className="btn btn-ghost" to="/profile">
          Edit Profile
        </Link>
        {computing ? (
          <div style={{ width: '100%', maxWidth: '36rem' }}>
            <div className="progress-bar-wrap">
              <div className="progress-bar-indeterminate" />
            </div>
            <p className="muted small" style={{ textAlign: 'center', marginTop: '0.4rem' }}>
              {elapsedSeconds < 60
                ? `Computing… ${elapsedSeconds}s elapsed`
                : `Computing… ${Math.floor(elapsedSeconds / 60)}m ${elapsedSeconds % 60}s elapsed`}
              {' · '}Ranking jobs (LLM reasoning available per-job)
            </p>
          </div>
        ) : null}
      </div>

      {computedAt ? <StatusBanner kind="success" title={`Computed at ${computedAt}`} /> : null}

      {showingHistoryFallback ? (
        <StatusBanner
          kind="info"
          title="Showing saved history from a previous run"
          detail="The latest recompute returned no new rows. Below are older matches from matching_history if any exist."
        />
      ) : null}

      {diagnostics?.jobs_loaded != null && computedAt && items.length > 0 && !showingHistoryFallback ? (
        <p className="muted small">
          Jobs considered: {diagnostics.jobs_loaded}
          {diagnostics.jobs_query_limit == null ? ' (full merged_jobs table)' : ''}
          {relaxedNote ? ` · ${relaxedNote}` : ''}
        </p>
      ) : null}

      {err ? (
        <StatusBanner kind="error" title="Request failed" detail={appendRecommendationsTroubleshooting(err)} />
      ) : null}

      {!loading && !err && computedAt && items.length === 0 && !showingHistoryFallback ? (
        <StatusBanner
          kind="error"
          title="No recommendations from this run"
          detail={
            diagHint ||
            'Try editing your profile (locations, salary, work type) or confirm the database has jobs in merged_jobs.'
          }
        />
      ) : null}

      <ol className="rec-list">
        {items.map((it, i) => (
          <li key={`${it.job_id}-${i}`} className="rec-card">
            <div className="rec-rank">{it.rank ?? i + 1}</div>
            <div className="rec-card-body">
              <h2 className="rec-title">{it.title || it.job_id}</h2>
              <p className="rec-meta">
                {it.company || '—'} · {it.location || '—'}
                {it.salary ? ` · ${it.salary}` : ''}
                {it.job_type ? ` · ${it.job_type}` : ''}
                {it.source ? ` · ${it.source}` : ''}
              </p>
              {it.description_snippet ? <p className="rec-snippet">{it.description_snippet}</p> : null}
              {(it.department || it.hours || it.closing_date || it.category) ? (
                <p className="muted small rec-extra">
                  {[it.department, it.hours, it.closing_date ? `Closes ${it.closing_date}` : null, it.category]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
              ) : null}
              {it.score != null ? (
                <p className="rec-score">
                  Overall {typeof it.score === 'number' ? `${(it.score * 100).toFixed(2)}%` : it.score}
                  {it.relevance != null ? ` · Relevance ${pct(it.relevance, 2)}` : ''}
                  {it.feasibility != null ? ` · Feasibility ${pct(it.feasibility, 2)}` : ''}
                  {it.growth != null ? ` · Growth ${pct(it.growth, 2)}` : ''}
                </p>
              ) : null}
              {it.matched_at ? <p className="muted small">Recorded {it.matched_at}</p> : null}
              <div className="rec-card-actions">
                {it.job_url ? (
                  <a className="btn btn-primary btn-small" href={it.job_url} target="_blank" rel="noopener noreferrer">
                    Posting link
                  </a>
                ) : null}
                <button type="button" className="btn btn-ghost btn-small" onClick={() => setDetailItem(it)}>
                  Details &amp; AI analysis
                </button>
              </div>
            </div>
          </li>
        ))}
      </ol>

      {detailItem ? (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={() => {
            setDetailItem(null);
          }}
        >
          <div
            className="modal-panel modal-panel--wide"
            role="dialog"
            aria-modal="true"
            aria-labelledby="rec-detail-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-head">
              <h2 id="rec-detail-title" className="modal-title">
                {detailItem.title || detailItem.job_id}
              </h2>
              <button type="button" className="btn btn-ghost btn-small modal-close" onClick={() => setDetailItem(null)}>
                Close
              </button>
            </div>
            <p className="rec-meta">
              {detailItem.company || '—'} · {detailItem.location || '—'}
              {detailItem.salary ? ` · ${detailItem.salary}` : ''}
              {detailItem.job_type ? ` · ${detailItem.job_type}` : ''}
              {detailItem.source ? ` · ${detailItem.source}` : ''}
            </p>
            {(detailItem.department || detailItem.hours || detailItem.closing_date || detailItem.category) ? (
              <p className="muted small">
                {[detailItem.department, detailItem.hours, detailItem.closing_date, detailItem.category]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
            ) : null}
            {detailItem.description_snippet ? (
              <p className="rec-snippet" style={{ marginTop: '0.5rem' }}>
                {detailItem.description_snippet}
              </p>
            ) : null}
            {detailItem.job_url ? (
              <p style={{ marginTop: '0.5rem' }}>
                <a className="btn btn-primary btn-small" href={detailItem.job_url} target="_blank" rel="noopener noreferrer">
                  Open full posting
                </a>
                {' '}
                <Link className="btn btn-ghost btn-small" to={`/jobs/${encodeURIComponent(String(detailItem.job_id))}`}>
                  Open internal job page
                </Link>
              </p>
            ) : (
              <p style={{ marginTop: '0.5rem' }}>
                <Link className="btn btn-ghost btn-small" to={`/jobs/${encodeURIComponent(String(detailItem.job_id))}`}>
                  Open internal job page
                </Link>
              </p>
            )}

            <section className="modal-section">
              <h3 className="modal-h3">Skill map</h3>
              <JobSkillGraph jobId={detailItem.job_id} />
            </section>

            <section className="modal-section">
              <h3 className="modal-h3">Scores</h3>
              <ul className="score-grid">
                <li>
                  <span className="score-label">Final</span> {pct(detailItem.score ?? undefined)}
                </li>
                <li>
                  <span className="score-label">Match</span> {pct(detailItem.match_score ?? undefined)}
                </li>
                <li>
                  <span className="score-label">Relevance</span> {pct(detailItem.relevance ?? undefined)}
                </li>
                <li>
                  <span className="score-label">Feasibility</span> {pct(detailItem.feasibility ?? undefined)}
                </li>
                <li>
                  <span className="score-label">Growth</span> {pct(detailItem.growth ?? undefined)}
                </li>
              </ul>
              {detailItem.score_breakdown ? (
                <div style={{ marginTop: '0.75rem' }}>
                  {renderBreakdownBucket('Relevance breakdown', detailItem.score_breakdown.relevance)}
                  {renderBreakdownBucket('Feasibility breakdown', detailItem.score_breakdown.feasibility)}
                  {renderBreakdownBucket('Growth breakdown', detailItem.score_breakdown.growth)}
                </div>
              ) : null}
            </section>

            {detailItem.explanation ? (
              <section className="modal-section">
                <h3 className="modal-h3">Readiness &amp; fit</h3>
                <p className="rec-expl">{detailItem.explanation}</p>
              </section>
            ) : null}

            <section className="modal-section">
              <h3 className="modal-h3">AI analysis &amp; learning path</h3>
              <p className="muted small" style={{ marginBottom: '0.6rem' }}>
                Get personalised skill gaps, learning suggestions, and strengths for this role based on your current
                profile. Uses LLM — may take 10–30 seconds.
              </p>
              <button
                type="button"
                className="btn btn-primary"
                disabled={learningLoading}
                onClick={() => void fetchLearningPath(detailItem.job_id)}
              >
                {learningLoading ? 'Generating…' : learning ? 'Refresh analysis' : 'Get AI analysis'}
              </button>
              {learningErr ? <p className="muted" style={{ marginTop: '0.5rem' }}>{learningErr}</p> : null}
              {learningLoading ? (
                <div style={{ marginTop: '0.75rem' }}>
                  <div className="progress-bar-wrap">
                    <div className="progress-bar-indeterminate" />
                  </div>
                  <p className="muted small" style={{ marginTop: '0.35rem' }}>Generating analysis…</p>
                </div>
              ) : null}
              {learning ? (
                <div className="learning-block">
                  <p className="muted small">
                    Match {pct(learning.scores?.match_score)} · Final {pct(learning.scores?.final_score)} · Hard
                    constraints:{' '}
                    {learning.constraints_satisfied === undefined
                      ? 'unknown'
                      : learning.constraints_satisfied
                        ? 'satisfied'
                        : 'not fully satisfied'}
                  </p>
                  {!learning.reasoning ? (
                    <p className="muted small">Analysis payload had no reasoning block — try refresh or check API logs.</p>
                  ) : null}
                  {learning.reasoning?.skill_gaps?.length ? (
                    <div>
                      <p className="modal-h3" style={{ fontSize: '1rem', marginTop: '0.75rem' }}>
                        Skill gaps
                      </p>
                      <ul>
                        {learning.reasoning.skill_gaps.map((g, idx) => (
                          <li key={idx}>
                            <strong>{g.skill}</strong>
                            {g.reason ? ` — ${g.reason}` : ''}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {learning.reasoning?.learning_suggestions?.length ? (
                    <div>
                      <p className="modal-h3" style={{ fontSize: '1rem', marginTop: '1rem' }}>
                        Learning &amp; development suggestions
                      </p>
                      <ul>
                        {learning.reasoning.learning_suggestions.map((s, idx) => (
                          <li key={idx}>{s}</li>
                        ))}
                      </ul>
                    </div>
                  ) : learning.reasoning ? (
                    <p className="muted small" style={{ marginTop: '0.75rem' }}>
                      No specific learning suggestions returned — try refreshing or check if LLM is enabled on the server.
                    </p>
                  ) : null}
                  {learning.reasoning?.strengths?.length ? (
                    <div>
                      <p className="modal-h3" style={{ fontSize: '1rem', marginTop: '1rem' }}>
                        Your strengths for this role
                      </p>
                      <ul>
                        {learning.reasoning.strengths.map((s, idx) => (
                          <li key={idx}>{s}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </section>
          </div>
        </div>
      ) : null}

      {!loading && !err && items.length === 0 && !computedAt ? (
        <p className="muted empty-rec-hint">
          No recommendations yet. Complete your profile and click &quot;Update recommendations&quot;.
        </p>
      ) : null}
    </div>
  );
}
