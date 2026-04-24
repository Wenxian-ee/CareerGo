import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api, formatUnknownError } from '@/api/client';
import { useAuth } from '@/auth/AuthContext';
import { NumericInput } from '@/components/NumericInput';

interface RunRecord {
  run: number;
  /** client-side round-trip ms */
  clientTotalMs: number;
  /** server-side: match + rank only */
  serverMatchRankMs: number | null;
  /** server-side: LLM enrichment */
  serverLlmMs: number | null;
  /** server-side: total pipeline */
  serverTotalMs: number | null;
  jobsProcessed: number | null;
  error?: string;
}

function avg(nums: number[]): number {
  if (!nums.length) return 0;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

function fmt(ms: number | null | undefined, decimals = 1): string {
  if (ms == null || Number.isNaN(ms)) return '—';
  if (ms >= 60000) return `${(ms / 60000).toFixed(1)} min`;
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${ms.toFixed(decimals)} ms`;
}

function MetricCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bench-metric-card">
      <p className="bench-metric-label">{label}</p>
      <p className="bench-metric-value">{value}</p>
      {sub ? <p className="bench-metric-sub">{sub}</p> : null}
    </div>
  );
}

export function BenchmarkPage() {
  const { token } = useAuth();
  const [iterations, setIterations] = useState(3);
  const [includeReasoning, setIncludeReasoning] = useState(false);
  const [topK, setTopK] = useState(10);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [records, setRecords] = useState<RunRecord[]>([]);
  const [statusMsg, setStatusMsg] = useState('');

  async function runBenchmark() {
    setRunning(true);
    setProgress(0);
    setRecords([]);
    setStatusMsg('');

    const newRecords: RunRecord[] = [];

    for (let i = 1; i <= iterations; i++) {
      setStatusMsg(`Running iteration ${i} / ${iterations}…`);
      const t0 = performance.now();
      try {
        const res = await api.postRecommendations(topK, includeReasoning);
        const clientTotalMs = performance.now() - t0;
        const d = res.diagnostics ?? {};
        newRecords.push({
          run: i,
          clientTotalMs,
          serverMatchRankMs: d.latency_matching_ranking_ms ?? null,
          serverLlmMs: d.latency_llm_ms ?? null,
          serverTotalMs: d.latency_total_ms ?? null,
          jobsProcessed: d.jobs_loaded ?? null,
        });
      } catch (e) {
        const clientTotalMs = performance.now() - t0;
        newRecords.push({
          run: i,
          clientTotalMs,
          serverMatchRankMs: null,
          serverLlmMs: null,
          serverTotalMs: null,
          jobsProcessed: null,
          error: formatUnknownError(e),
        });
      }
      setProgress(i);
      setRecords([...newRecords]);
    }

    setStatusMsg('Done.');
    setRunning(false);
  }

  const successRecords = records.filter((r) => !r.error);

  const avgClientTotal = avg(successRecords.map((r) => r.clientTotalMs));
  const avgMatchRank = avg(
    successRecords.filter((r) => r.serverMatchRankMs != null).map((r) => r.serverMatchRankMs as number),
  );
  const avgWithLlm = avg(
    successRecords.filter((r) => r.serverTotalMs != null).map((r) => r.serverTotalMs as number),
  );
  const allClientMs = successRecords.map((r) => r.clientTotalMs);
  const minLatency = allClientMs.length ? Math.min(...allClientMs) : null;
  const maxLatency = allClientMs.length ? Math.max(...allClientMs) : null;
  const avgJobs = avg(
    successRecords.filter((r) => r.jobsProcessed != null).map((r) => r.jobsProcessed as number),
  );

  if (!token) {
    return (
      <div className="page page-narrow-centered">
        <p>
          Please <Link to="/login">sign in</Link> first to run the benchmark.
        </p>
      </div>
    );
  }

  return (
    <div className="page page-narrow-centered">
      <header className="page-head">
        <h1 className="page-title">Performance Benchmark</h1>
        <p className="page-sub">
          Measures end-to-end latency of the matching &amp; ranking pipeline by calling{' '}
          <code>POST /api/users/me/recommendations</code> repeatedly and collecting server-side timing
          from the response diagnostics.
        </p>
      </header>

      {/* Controls */}
      <div className="bench-controls">
        <label className="bench-label" htmlFor="iter-input">
          Iterations
        </label>
        <NumericInput
          id="iter-input"
          min={1}
          max={20}
          value={iterations}
          onChange={(v) => setIterations(v)}
          fallback={1}
          disabled={running}
          className="bench-iter-input"
        />
        <label className="bench-label" htmlFor="topk-input">
          Top-K
        </label>
        <NumericInput
          id="topk-input"
          min={1}
          max={10}
          value={topK}
          onChange={(v) => setTopK(v)}
          fallback={1}
          disabled={running}
          className="bench-iter-input"
        />
        <label className="bench-label" htmlFor="llm-toggle" style={{ display: 'inline-flex', gap: '0.4rem', alignItems: 'center' }}>
          <input
            id="llm-toggle"
            type="checkbox"
            checked={includeReasoning}
            onChange={(e) => setIncludeReasoning(e.target.checked)}
            disabled={running}
          />
          Enable LLM reasoning
        </label>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => void runBenchmark()}
          disabled={running}
        >
          {running ? `Running… (${progress}/${iterations})` : 'Run Benchmark'}
        </button>
        {statusMsg ? <span className="muted small">{statusMsg}</span> : null}
        {!running ? (
          <span className="muted small">
            Mode: {includeReasoning ? 'LLM enabled' : 'LLM disabled (LLM latency should be ~0 ms)'}
          </span>
        ) : null}
        {!running && includeReasoning ? (
          <span className="muted small">
            Tip: if timeout happens, reduce Iterations and Top-K (e.g. 1-3) in LLM mode.
          </span>
        ) : null}
      </div>

      {/* Progress bar */}
      {running && (
        <div className="bench-progress-bar-wrap">
          <div
            className="bench-progress-bar-fill"
            style={{ width: `${(progress / iterations) * 100}%` }}
          />
        </div>
      )}

      {/* Summary metrics */}
      {successRecords.length > 0 && (
        <>
          <h2 className="bench-section-title">Summary ({successRecords.length} successful runs)</h2>
          <div className="bench-metrics-grid">
            <MetricCard
              label="Avg latency — Matching &amp; Ranking only"
              value={avgMatchRank > 0 ? fmt(avgMatchRank) : fmt(avgClientTotal)}
              sub={avgMatchRank > 0 ? 'server-side (match + rank)' : 'client round-trip (server timing unavailable)'}
            />
            <MetricCard
              label="Avg latency — With LLM explanation"
              value={avgWithLlm > 0 ? fmt(avgWithLlm) : fmt(avgClientTotal)}
              sub={avgWithLlm > 0 ? 'server-side (full pipeline)' : 'client round-trip fallback'}
            />
            <MetricCard
              label="Min observed latency"
              value={fmt(minLatency)}
              sub="client round-trip"
            />
            <MetricCard
              label="Max observed latency"
              value={fmt(maxLatency)}
              sub="client round-trip"
            />
            <MetricCard
              label="Avg jobs processed / request"
              value={avgJobs > 0 ? avgJobs.toFixed(0) : '—'}
              sub="rows loaded from merged_jobs"
            />
          </div>
        </>
      )}

      {/* Per-run table */}
      {records.length > 0 && (
        <>
          <h2 className="bench-section-title">Per-run detail</h2>
          <div className="bench-table-wrap">
            <table className="bench-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Client total</th>
                  <th>Server: Match+Rank</th>
                  <th>Server: LLM</th>
                  <th>Server: Total</th>
                  <th>Jobs loaded</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {records.map((r) => (
                  <tr key={r.run} className={r.error ? 'bench-row-error' : ''}>
                    <td>{r.run}</td>
                    <td>{fmt(r.clientTotalMs)}</td>
                    <td>{fmt(r.serverMatchRankMs)}</td>
                    <td>{fmt(r.serverLlmMs)}</td>
                    <td>{fmt(r.serverTotalMs)}</td>
                    <td>{r.jobsProcessed ?? '—'}</td>
                    <td>{r.error ? <span className="bench-error-text">{r.error}</span> : '✓'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Notes */}
      <div className="bench-notes">
        <p className="muted small">
          <strong>Metric definitions:</strong>
        </p>
        <ul className="muted small">
          <li>
            <strong>Match + Rank only</strong> — server-measured time from the start of{' '}
            <code>JobMatcher.match()</code> to the end of <code>MultiObjectiveRanker.rank()</code>,
            excluding DB load and LLM calls.
          </li>
          <li>
            <strong>With LLM explanation</strong> — server-measured total pipeline time including DB
            load, matching, ranking, and LLM enrichment.
          </li>
          <li>
            <strong>Min / Max latency</strong> — client-side round-trip (includes network + server).
          </li>
          <li>
            <strong>Jobs processed / request</strong> — number of rows loaded from{' '}
            <code>merged_jobs</code> before filtering.
          </li>
        </ul>
      </div>
    </div>
  );
}
