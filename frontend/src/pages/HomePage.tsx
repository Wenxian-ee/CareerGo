import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '@/api/client';
import type { HealthResponse } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { StatusBanner } from '@/components/StatusBanner';

export function HomePage() {
  const { me, token } = useAuth();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .health()
      .then((h) => {
        if (!cancelled) setHealth(h);
      })
      .catch((e: Error) => {
        if (!cancelled) setErr(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="page page-home">
      <section className="hero">
        <p className="eyebrow">CareerGo</p>
        <h1 className="hero-title">Find roles that actually fit you</h1>
        <p className="hero-lead">
          Tell us about your skills and preferences — we&apos;ll surface jobs from your database, explain why they
          match, and suggest what to learn next. Browse the full catalog anytime (no login needed).
        </p>
        <div className="hero-actions">
          <Link className="btn btn-ghost" to="/jobs">
            Job catalog
          </Link>
          {token ? (
            <>
              <Link className="btn btn-primary" to="/profile">
                My profile
              </Link>
              <Link className="btn btn-ghost" to="/recommendations">
                Recommendations
              </Link>
            </>
          ) : (
            <>
              <Link className="btn btn-primary" to="/register">
                Register
              </Link>
              <Link className="btn btn-ghost" to="/login">
                Sign in
              </Link>
            </>
          )}
        </div>
        {me ? (
          <p className="muted" style={{ marginTop: '1rem' }}>
            Signed in as <strong>{me.name}</strong> ({me.user_id})
          </p>
        ) : null}
      </section>

      {err ? (
        <StatusBanner
          kind="error"
          title="Cannot reach the API"
          detail={`${err} — start the backend: cd api && uvicorn app:app --host 0.0.0.0 --port 8000`}
        />
      ) : health ? (
        <StatusBanner
          kind="success"
          title="Backend connected"
          detail={`Status: ${health.status}${health.database != null ? ` · Database: ${health.database ? 'OK' : 'error'}` : ''}`}
        />
      ) : (
        <StatusBanner kind="info" title="Checking backend…" />
      )}

      <section className="card home-cta-card">
        <h2 className="card-title">Browse all jobs</h2>
        <p className="card-body">
          Filter by location, category, source, and more — no account needed. For ranked, personalized suggestions, head
          to <Link to="/recommendations">Recommendations</Link> after you sign in.
        </p>
        <div className="home-cta-actions">
          <Link className="btn btn-primary" to="/jobs">
            Open job catalog →
          </Link>
        </div>
      </section>

      <section className="grid-3">
        <article className="card">
          <h2 className="card-title">1. Register / sign in</h2>
          <p className="card-body">
            Accounts are stored in PostgreSQL <code>users</code> (password hash).
          </p>
        </article>
        <article className="card">
          <h2 className="card-title">2. Full profile</h2>
          <p className="card-body">
            Education, skills, preferences, constraints, experience, certifications, languages, and projects match your
            existing ORM layer.
          </p>
        </article>
        <article className="card">
          <h2 className="card-title">3. Recommendations</h2>
          <p className="card-body">
            Jobs load from <code>merged_jobs</code>; scores are saved to <code>matching_history</code>.
          </p>
        </article>
      </section>
    </div>
  );
}
