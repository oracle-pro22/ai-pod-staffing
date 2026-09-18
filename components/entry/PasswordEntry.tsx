'use client';

import { useState, type FormEvent } from 'react';
import { announcePersonaChange } from '@/lib/staffing-fetch';
import '@/styles/password-entry.css';

export function PasswordEntry({ initialError = '' }: { initialError?: string }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(initialError);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError('');
    try {
      const response = await fetch('/api/auth/login', { method: 'POST', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: email.trim(), password }) });
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof result?.error === 'string' ? result.error : 'Unable to sign in. Please try again.');
      setPassword(''); announcePersonaChange(); window.location.assign('/');
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to sign in.'); setBusy(false); }
  }
  return <main className="password-entry">
    <header className="password-brand"><span aria-hidden="true">AI</span><div><strong>AI Pod Staffing</strong><small>Customer Success Services</small></div></header>
    <section className="password-card" aria-labelledby="sign-in-title">
      <p className="password-eyebrow">YOUR WORKSPACE</p><h1 id="sign-in-title">Welcome back</h1>
      <p className="password-description">Sign in to manage your work and connect the right people to every project.</p>
      <form onSubmit={submit}>
        <label htmlFor="staffing-email">Oracle email</label>
        <input id="staffing-email" name="email" type="email" autoComplete="username" required maxLength={320}
          placeholder="firstname.lastname@oracle.com" value={email} onChange={e => setEmail(e.target.value)} disabled={busy} />
        <label htmlFor="staffing-password">Password</label>
        <input id="staffing-password" name="password" type="password" autoComplete="current-password" required maxLength={1024}
          value={password} onChange={e => setPassword(e.target.value)} disabled={busy} />
        {error && <p className="password-error" role="alert">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
      <p className="password-note">Your account opens the workspace assigned to your role.</p>
    </section>
  </main>;
}
