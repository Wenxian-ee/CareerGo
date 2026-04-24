import { NavLink } from 'react-router-dom';
import { useAuth } from '@/auth/AuthContext';

const publicLinks = [
  { to: '/', label: 'Home', end: true },
  { to: '/jobs', label: 'Jobs', end: false },
] as const;

const authedLinks = [
  { to: '/profile', label: 'Profile', end: false },
  { to: '/recommendations', label: 'Recommendations', end: false },
  { to: '/benchmark', label: 'Benchmark', end: false },
] as const;

function LockIcon() {
  return (
    <svg
      aria-hidden="true"
      width="12"
      height="12"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="nav-lock-icon"
    >
      <rect x="3" y="7" width="10" height="7" rx="1.5" />
      <path d="M5.5 7V4.5a2.5 2.5 0 0 1 5 0V7" />
    </svg>
  );
}

export function Nav() {
  const { token } = useAuth();

  return (
    <nav className="nav" aria-label="Main navigation">
      {publicLinks.map(({ to, label, end }) => (
        <NavLink key={to} to={to} end={end} className={({ isActive }) => (isActive ? 'nav-link nav-link-active' : 'nav-link')}>
          {label}
        </NavLink>
      ))}
      {token
        ? authedLinks.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => (isActive ? 'nav-link nav-link-active' : 'nav-link')}
            >
              {label}
            </NavLink>
          ))
        : authedLinks.map(({ to, label }) => (
            <NavLink
              key={to}
              to="/login"
              state={{ from: to }}
              className="nav-link nav-link-locked"
              title="Sign in to access this area"
            >
              <LockIcon />
              <span>{label}</span>
            </NavLink>
          ))}
    </nav>
  );
}
