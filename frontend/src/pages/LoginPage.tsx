import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { formatUnknownError } from '@/api/client';
import { useAuth } from '@/auth/AuthContext';
import { StatusBanner } from '@/components/StatusBanner';
import { MAX_USER_ID_LEN, validateLoginInput } from '@/utils/inputGuards';

export function LoginPage() {
  const nav = useNavigate();
  const { login } = useAuth();
  const [user_id, setUserId] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    const v = validateLoginInput(user_id, password);
    if (v) {
      setErr(v);
      return;
    }
    try {
      await login(user_id.trim(), password);
      nav('/profile', { replace: true });
    } catch (e2) {
      setErr(formatUnknownError(e2));
    }
  }

  return (
    <div className="page narrow-page page-auth">
      <header className="page-head">
        <h1 className="page-title">Sign in</h1>
      </header>
      {err ? <StatusBanner kind="error" title="Sign-in failed" detail={err} /> : null}
      <form className="form-stack" onSubmit={(e) => void submit(e)}>
        <label className="field">
          <span className="field-label">User ID</span>
          <input
            className="input"
            required
            maxLength={MAX_USER_ID_LEN}
            autoComplete="username"
            value={user_id}
            onChange={(e) => setUserId(e.target.value)}
          />
        </label>
        <label className="field">
          <span className="field-label">Password</span>
          <input className="input" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <button type="submit" className="btn btn-primary">
          Sign in
        </button>
        <p className="muted">
          No account? <Link to="/register">Register</Link>
        </p>
      </form>
    </div>
  );
}
