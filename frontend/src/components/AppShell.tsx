import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/auth/AuthContext';
import { Nav } from './Nav';

export function AppShell({ children }: { children: ReactNode }) {
  const { me, logout } = useAuth();

  return (
    <div className="layout">
      <header className="header">
        <div className="header-inner">
          <Link className="brand" to="/">
            <span className="brand-mark">CG</span>
            <span className="brand-text">CareerGo</span>
          </Link>
          <Nav />
          <div className="header-user">
            {me ? (
              <>
                <span className="user-pill">{me.name}</span>
                <button type="button" className="btn btn-ghost btn-small" onClick={logout}>
                  Sign out
                </button>
              </>
            ) : (
              <>
                <Link className="btn btn-ghost btn-small" to="/login">
                  Sign in
                </Link>
                <Link className="btn btn-primary btn-small" to="/register">
                  Register
                </Link>
              </>
            )}
          </div>
        </div>
      </header>
      <main className="main">{children}</main>
      <footer className="footer">
        <span>CareerGo · crawl → skills → match &amp; rank</span>
      </footer>
    </div>
  );
}
