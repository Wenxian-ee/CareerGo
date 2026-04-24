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
          {token ? (
            <>
              <Link className="btn btn-primary" to="/recommendations">
                Get my recommendations
              </Link>
              <Link className="btn btn-ghost" to="/profile">
                Edit my profile
              </Link>
              <Link className="btn btn-ghost" to="/jobs">
                Browse all jobs
              </Link>
            </>
          ) : (
            <>
              <Link className="btn btn-primary" to="/register">
                Create an account
              </Link>
              <Link className="btn btn-ghost" to="/login">
                Sign in
              </Link>
              <Link className="btn btn-ghost" to="/jobs">
                Browse all jobs
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

      <section className="steps-section">
        <h2 className="steps-heading">How CareerGo works</h2>
        <p className="steps-sub">Three steps from sign-up to ranked, explained job matches.</p>
        <ol className="step-list">
          <li className="step-card">
            <span className="step-number">1</span>
            <div className="step-body">
              <h3 className="step-title">Create a free account</h3>
              <p className="step-text">
                Takes under a minute. Your profile and match history are saved so you can come back anytime.
              </p>
              {token ? (
                <span className="step-status">You&apos;re signed in as {me?.name}.</span>
              ) : (
                <Link className="step-link" to="/register">
                  Register <span aria-hidden="true">→</span>
                </Link>
              )}
            </div>
          </li>
          <li className="step-card">
            <span className="step-number">2</span>
            <div className="step-body">
              <h3 className="step-title">Tell us about you</h3>
              <p className="step-text">
                Education, skills, preferred salary and locations, work arrangement, experience and projects.
                The more you fill, the more accurate your matches.
              </p>
              {token ? (
                <Link className="step-link" to="/profile">
                  Edit my profile <span aria-hidden="true">→</span>
                </Link>
              ) : (
                <span className="step-status step-status-muted">Available after you sign in.</span>
              )}
            </div>
          </li>
          <li className="step-card">
            <span className="step-number">3</span>
            <div className="step-body">
              <h3 className="step-title">Get ranked recommendations</h3>
              <p className="step-text">
                We score every open role on relevance, feasibility and growth, show a skill map, and suggest
                what to learn next — with short, plain-English explanations.
              </p>
              {token ? (
                <Link className="step-link" to="/recommendations">
                  View recommendations <span aria-hidden="true">→</span>
                </Link>
              ) : (
                <span className="step-status step-status-muted">Available after you sign in.</span>
              )}
            </div>
          </li>
        </ol>
      </section>

      <section className="card home-browse-card">
        <div className="home-browse-copy">
          <h2 className="card-title">Just want to look around?</h2>
          <p className="card-body">
            Browse the full job catalog without signing in. Filter by location, category, job type, source or
            keywords.
          </p>
        </div>
        <Link className="btn btn-primary" to="/jobs">
          Open job catalog <span aria-hidden="true">→</span>
        </Link>
      </section>
    </div>
  );
}
