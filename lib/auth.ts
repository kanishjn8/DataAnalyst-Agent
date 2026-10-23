import { createClient, type SupabaseClient } from '@supabase/supabase-js';
export const apiRoot = process.env.NEXT_PUBLIC_API_BASE_URL || (process.env.NODE_ENV === 'development' ? 'http://127.0.0.1:4000' : '/api');
let client: Promise<SupabaseClient> | undefined;
export function getAuth() {
  if (!client) client = fetch(`${apiRoot}/config`).then(async response => {
    if (!response.ok) throw new Error('The service is unavailable. Please try again.');
    const config = await response.json();
    return createClient(config.url, config.anonKey, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } });
  }).catch(error => { client = undefined; throw error; });
  return client;
}
export async function authHeaders(): Promise<Record<string, string>> {
  if (typeof window === 'undefined') return {};
  const { data, error } = await (await getAuth()).auth.getSession();
  if (error || !data.session) throw new Error('Sign in to continue.');
  return { Authorization: `Bearer ${data.session.access_token}` };
}
export async function signOut() { await (await getAuth()).auth.signOut(); }
export async function signUp(email: string, password: string) {
  return (await getAuth()).auth.signUp({ email, password, options: { emailRedirectTo: `${window.location.origin}/` } });
}
