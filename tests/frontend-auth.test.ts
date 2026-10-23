import { afterEach, describe, expect, it, vi } from 'vitest';
const { createClient, register } = vi.hoisted(() => ({ createClient: vi.fn(), register: vi.fn() }));
vi.mock('@supabase/supabase-js', () => ({ createClient }));
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules(); vi.clearAllMocks(); });

describe('hosted authentication', () => {
  it('enables verification-link sessions and shares the initialized client', async () => {
    const client = { auth: { signUp: register } };
    createClient.mockReturnValue(client);
    const fetch = vi.fn().mockResolvedValue(Response.json({ url: 'https://project.supabase.co', anonKey: 'test-publishable-key' }));
    vi.stubGlobal('fetch', fetch);
    const { getAuth } = await import('../lib/auth');
    const clients = await Promise.all([getAuth(), getAuth()]);
    expect(clients).toEqual([client, client]);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(createClient).toHaveBeenCalledWith('https://project.supabase.co', 'test-publishable-key', {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    });
  });

  it.each(['https://frontend.vercel.app', 'http://localhost:3000'])(
    'returns signup confirmation to the current frontend: %s', async origin => {
      vi.stubGlobal('window', { location: { origin } });
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ url: 'https://project.supabase.co', anonKey: 'test-publishable-key' })));
      createClient.mockReturnValue({ auth: { signUp: register } });
      const result = { data: { session: null }, error: null };
      register.mockResolvedValue(result);
      const { signUp } = await import('../lib/auth');
      expect(await signUp('test@example.com', 'test-only-password')).toBe(result);
      expect(register).toHaveBeenCalledWith({ email: 'test@example.com', password: 'test-only-password', options: { emailRedirectTo: `${origin}/` } });
    },
  );

  it('allows authentication initialization to be retried after a configuration request fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response('', { status: 503 }))
      .mockResolvedValueOnce(Response.json({ url: 'https://project.supabase.co', anonKey: 'test-publishable-key' })));
    const client = { auth: { signUp: register } };
    createClient.mockReturnValue(client);
    const { getAuth } = await import('../lib/auth');
    await expect(getAuth()).rejects.toThrow('unavailable');
    expect(await getAuth()).toBe(client);
  });
});
