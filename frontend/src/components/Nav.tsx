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
        : null}
    </nav>
  );
}
