'use client';
import { createContext, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { User } from '@supabase/supabase-js';
import { getAuth, signUp } from '@/lib/auth';
import { Icon } from './icons';

const AccountContext = createContext<User | null>(null);
export function useAccount() { return useContext(AccountContext); }

export function AuthBoundary({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState('');
  useEffect(() => {
    let alive = true, unsubscribe = () => {};
    getAuth().then(async client => {
      if (!alive) return;
      const listener = client.auth.onAuthStateChange((_event, next) => { if (alive) setUser(next?.user.is_anonymous ? null : next?.user ?? null); });
      unsubscribe = () => listener.data.subscription.unsubscribe();
      const { data, error } = await client.auth.getSession();
      if (error) throw error;
      if (alive) { setUser(data.session?.user.is_anonymous ? null : data.session?.user ?? null); setLoading(false); }
    }).catch(error => { if (alive) { setError(error.message); setLoading(false); } });
    return () => { alive = false; unsubscribe(); };
  }, []);
  if (user) return <AccountContext.Provider key={user.id} value={user}>{children}</AccountContext.Provider>;
  return <div className="app-shell overview-shell"><aside className="sidebar"><div className="sidebar-brand"><span className="brand-mark"><Icon name="grid" size={21}/></span><div><strong>Workspace</strong><span>Data analysis</span></div></div></aside><div className="main-shell"><main className="main-content"><div className="page-heading"><div><h1>Data analysis</h1><p className="page-description">Organize your data and explore your analyses.</p></div></div>{loading ? <p role="status">Loading your workspace…</p> : <SignIn initialError={error}/>}</main></div></div>;
}
function SignIn({ initialError }: { initialError: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [email, setEmail] = useState(''), [password, setPassword] = useState('');
  const [creating, setCreating] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(initialError);
  const [notice, setNotice] = useState('');
  useEffect(() => { dialog.current?.showModal(); }, []);
  async function login() {
    setBusy(true); setError(''); setNotice('');
    try {
      const client = await getAuth();
      const result = creating ? await signUp(email, password) : await client.auth.signInWithPassword({ email, password });
      if (result.error) throw result.error;
      if (creating && !result.data.session) { setNotice('Check your email to confirm your account, then sign in.'); setCreating(false); setBusy(false); return; }
      if (!result.data.session) throw new Error('Check your email to finish signing in.');

    } catch (error) { setError((error as Error).message); setBusy(false); }
  }
  return <dialog ref={dialog} className="create-dialog" aria-labelledby="sign-in-title" onCancel={event => event.preventDefault()}><form onSubmit={event => { event.preventDefault(); void login(); }}><div className="dialog-heading"><span className="icon-tile purple"><Icon name="shield" size={20}/></span></div><h2 id="sign-in-title">{creating ? 'Create your account' : 'Sign in to your workspace'}</h2><p>Keep your files and analyses together.</p><label htmlFor="sign-in-email">Email</label><input autoFocus id="sign-in-email" type="email" autoComplete="email" required value={email} disabled={busy} onChange={event => setEmail(event.target.value)}/><label htmlFor="sign-in-password" style={{ marginTop: 16 }}>Password</label><input id="sign-in-password" type="password" autoComplete={creating ? 'new-password' : 'current-password'} required minLength={6} value={password} disabled={busy} onChange={event => setPassword(event.target.value)}/>{notice && <p role="status">{notice}</p>}{error && <p className="dialog-error" role="alert">{error}</p>}<div className="dialog-actions"><button type="button" className="secondary" disabled={busy} onClick={() => { setCreating(!creating); setError(''); }}>{creating ? 'Sign in instead' : 'Create account'}</button><button className="primary" disabled={busy}>{busy ? 'Please wait…' : creating ? 'Create account' : 'Sign in'}</button></div></form></dialog>;
}
