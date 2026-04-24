import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, formatUnknownError } from '@/api/client';
import type { JobRecord } from '@/api/types';
import { JobSkillGraph } from '@/components/JobSkillGraph';
import { StatusBanner } from '@/components/StatusBanner';

export function JobDetailPage() {
  const { jobId = '' } = useParams();
  const [job, setJob] = useState<JobRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [urlChecking, setUrlChecking] = useState(false);
  const [urlDead, setUrlDead] = useState(false);

  async function handleOpenPosting(jobUrl: string) {
    if (!jobId || urlDead) return;
    setUrlChecking(true);
    try {
      const result = await api.checkJobUrl(jobId);
      if (result.reachable) {
        window.open(jobUrl, '_blank', 'noreferrer');
      } else {
        setUrlDead(true);
      }
    } catch {
      window.open(jobUrl, '_blank', 'noreferrer');
    } finally {
      setUrlChecking(false);
    }
  }

  useEffect(() => {
    const id = (jobId || '').trim();
    if (!id) return;
    setLoading(true);
    setErr(null);
    api
      .getJob(id)
      .then((res) => setJob(res))
      .catch((e: unknown) => {
        setErr(formatUnknownError(e));
        setJob(null);
      })
      .finally(() => setLoading(false));
  }, [jobId]);

  return (
    <div className="page page-narrow-centered">
      <div className="back-bar">
        <Link className="back-chip" to="/jobs">
          <span className="back-chip-arrow" aria-hidden="true">←</span>
          <span>Back to jobs</span>
        </Link>
      </div>
      {loading ? <p className="muted small">Loading job…</p> : null}
      {err ? <StatusBanner kind="error" title="Could not load this job" detail={err} /> : null}
      {job ? (
        <>
          <header className="page-head">
            <h1 className="page-title">{job.title || job.job_id}</h1>
            <p className="page-sub">
              {job.company || '—'} · {job.location || '—'}
              {job.salary ? ` · ${job.salary}` : ''}
              {job.job_type ? ` · ${job.job_type}` : ''}
              {job.source ? ` · ${job.source}` : ''}
            </p>
          </header>
          {(() => {
            const isExpired = job.closing_date ? new Date(job.closing_date as string) < new Date() : false;
            return (
              <>
                {job.closing_date ? (
                  <p className={`job-closing${isExpired ? ' job-closing--expired' : ''}`} style={{ marginBottom: '0.75rem' }}>
                    {isExpired
                      ? `This posting closed on ${job.closing_date as string}`
                      : `Closes ${job.closing_date as string}`}
                  </p>
                ) : null}
                {isExpired ? (
                  <StatusBanner
                    kind="warning"
                    title="Posting closed"
                    detail="The application deadline for this job has passed. The external link may no longer be available."
                  />
                ) : null}
                {urlDead && !isExpired ? (
                  <StatusBanner
                    kind="warning"
                    title="Posting unavailable"
                    detail="This job posting is no longer available on the recruiter's site, even though it has not passed its closing date."
                  />
                ) : null}
                {job.job_url ? (
                  <p>
                    {isExpired || urlDead ? (
                      <span className="btn btn-primary btn-small btn--disabled" style={{ opacity: 0.45, cursor: 'not-allowed' }}>
                        Open posting
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="btn btn-primary btn-small"
                        disabled={urlChecking}
                        onClick={() => void handleOpenPosting(String(job.job_url))}
                      >
                        {urlChecking ? 'Checking…' : 'Open posting'}
                      </button>
                    )}
                  </p>
                ) : null}
              </>
            );
          })()}
          <section className="modal-section">
            <h3 className="modal-h3">Skill map</h3>
            <JobSkillGraph jobId={String(job.job_id)} />
          </section>
          {job.description ? (
            <section className="modal-section">
              <h3 className="modal-h3">Description</h3>
              <p className="rec-snippet">{job.description}</p>
            </section>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
