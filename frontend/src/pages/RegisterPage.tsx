import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { formatUnknownError } from '@/api/client';
import { useAuth } from '@/auth/AuthContext';
import { StatusBanner } from '@/components/StatusBanner';
import { MAX_NAME_LEN, MAX_USER_ID_LEN, validateRegisterInput } from '@/utils/inputGuards';

export function RegisterPage() {
  const nav = useNavigate();
  const { register } = useAuth();
  const [user_id, setUserId] = useState('');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    const v = validateRegisterInput({
      user_id,
      name,
      email,
      password,
    });
    if (v) {
      setErr(v);
      return;
    }
    try {
      await register({ user_id: user_id.trim(), name: name.trim(), email: email.trim() || undefined, password });
      nav('/profile', { replace: true });
    } catch (e2) {
      setErr(formatUnknownError(e2));
    }
  }

  return (
    <div className="page narrow-page page-auth">
      <header className="page-head">
        <h1 className="page-title">Create your account</h1>
        <p className="page-sub">
          Takes under a minute. After sign-up you can fill in a profile and get personalised job
          recommendations with match scores and AI-powered analysis.
        </p>
      </header>

      {err ? <StatusBanner kind="error" title="Registration failed" detail={err} /> : null}

      <form className="form-stack" onSubmit={(e) => void submit(e)}>
        <label className="field">
          <span className="field-label">User ID (login name)</span>
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
          <span className="field-label">Display name</span>
          <input
            className="input"
            required
            maxLength={MAX_NAME_LEN}
            autoComplete="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="field">
          <span className="field-label">Email (optional)</span>
          <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">Password (min. 6 characters)</span>
          <input className="input" type="password" required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <button type="submit" className="btn btn-primary">
          Register and sign in
        </button>
        <p className="muted">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </form>
    </div>
  );
}
