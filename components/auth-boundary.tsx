'use client';
import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { getAuth } from '@/lib/auth';
import { Icon } from './icons';

export function AuthBoundary({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<string | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState('');
  useEffect(() => {
    let alive = true, unsubscribe = () => {};
    getAuth().then(async client => {
      const { data } = await client.auth.getSession();
      if (alive) { setSession(data.session?.user.id ?? null); setLoading(false); }
      const listener = client.auth.onAuthStateChange((_event, next) => { if (alive) setSession(next?.user.id ?? null); });
      unsubscribe = () => listener.data.subscription.unsubscribe();
    }).catch(error => { if (alive) { setError(error.message); setLoading(false); } });
    return () => { alive = false; unsubscribe(); };
  }, []);
  if (session) return <div key={session}>{children}</div>;
  return <div className="app-shell overview-shell"><aside className="sidebar"><div className="sidebar-brand"><span className="brand-mark"><Icon name="grid" size={21}/></span><div><strong>Workspace</strong><span>Data analysis</span></div></div></aside><div className="main-shell"><main className="main-content"><div className="page-heading"><div><h1>Data analysis</h1><p className="page-description">Organize your data and explore your analyses.</p></div></div>{loading ? <p role="status">Loading your workspace…</p> : <SignIn initialError={error}/>}</main></div></div>;
}
function SignIn({ initialError }: { initialError: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [email, setEmail] = useState(''), [password, setPassword] = useState('');
  const [creating, setCreating] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(initialError);
  useEffect(() => { dialog.current?.showModal(); }, []);
  async function login(guest = false) {
    setBusy(true); setError('');
    try {
      const client = await getAuth();
      const result = guest ? await client.auth.signInAnonymously() : creating ? await client.auth.signUp({ email, password }) : await client.auth.signInWithPassword({ email, password });
      if (result.error) throw result.error;
      if (!result.data.session) throw new Error('Check your email to finish signing in.');

    } catch (error) { setError((error as Error).message); setBusy(false); }
  }
  return <dialog ref={dialog} className="create-dialog" aria-labelledby="sign-in-title" onCancel={event => event.preventDefault()}><form onSubmit={event => { event.preventDefault(); void login(); }}><div className="dialog-heading"><span className="icon-tile purple"><Icon name="shield" size={20}/></span></div><h2 id="sign-in-title">{creating ? 'Create your account' : 'Sign in to your workspace'}</h2><p>Keep your files and analyses together.</p><label htmlFor="sign-in-email">Email</label><input autoFocus id="sign-in-email" type="email" autoComplete="email" required value={email} disabled={busy} onChange={event => setEmail(event.target.value)}/><label htmlFor="sign-in-password" style={{ marginTop: 16 }}>Password</label><input id="sign-in-password" type="password" autoComplete={creating ? 'new-password' : 'current-password'} required minLength={6} value={password} disabled={busy} onChange={event => setPassword(event.target.value)}/>{error && <p className="dialog-error" role="alert">{error}</p>}<div className="dialog-actions"><button type="button" className="secondary" disabled={busy} onClick={() => { setCreating(!creating); setError(''); }}>{creating ? 'Sign in instead' : 'Create account'}</button><button className="primary" disabled={busy}>{busy ? 'Please wait…' : creating ? 'Create account' : 'Sign in'}</button></div><div className="dialog-actions"><button type="button" className="text-button" disabled={busy} onClick={() => void login(true)}>Continue as guest<Icon name="arrow" size={14}/></button></div></form></dialog>;
}
