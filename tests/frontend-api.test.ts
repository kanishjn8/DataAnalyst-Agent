import { afterEach, describe, expect, it, vi } from 'vitest';
import { analyze, deleteProject, generateDashboard, listProjects, mutateProject, previewTable } from '../lib/api';
import type { Project } from '../shared/workspace';
const project = { id: 'server-workspace', revision: 4, dataVersion: 2 } as Project;
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules(); });
describe('frontend API boundary', () => {
  it('calls the separate Python port directly during local development', async () => {
    vi.resetModules();
    vi.stubEnv('NODE_ENV', 'development');
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', '');
    const fetch = vi.fn().mockResolvedValue(Response.json({ projects: [] })); vi.stubGlobal('fetch', fetch);
    await (await import('../lib/api')).listProjects();
    expect(fetch.mock.calls[0][0]).toBe('http://127.0.0.1:4000/workspace');
  });
  it('supports an explicitly configured backend URL', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', 'https://api.example.com');
    const fetch = vi.fn().mockResolvedValue(Response.json({ projects: [] })); vi.stubGlobal('fetch', fetch);
    await (await import('../lib/api')).listProjects();
    expect(fetch.mock.calls[0][0]).toBe('https://api.example.com/workspace');
  });
  it('requests deletion on the backend and surfaces failures', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(Response.json({ deletedId: project.id })).mockResolvedValueOnce(Response.json({ error: 'Analysis not found.' }, { status: 404 })); vi.stubGlobal('fetch', fetch);
    await deleteProject(project.id);
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ action: 'delete', workspaceId: project.id });
    await expect(deleteProject(project.id)).rejects.toThrow('Analysis not found.');
  });
  it('loads workspace summaries from the backend', async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ projects: [], capabilities: { analysis: false } })); vi.stubGlobal('fetch', fetch);
    expect(await listProjects()).toMatchObject({ projects: [] });
    expect(fetch.mock.calls[0][0]).toBe('/api/workspace');
  });
  it('renames an analysis using its revision and returns the saved title', async () => {
    const renamed = { ...project, title: 'Quarterly sales', revision: 5 };
    const fetch = vi.fn().mockResolvedValue(Response.json({ project: renamed })); vi.stubGlobal('fetch', fetch);
    expect(await mutateProject(project, { action: 'patch', title: 'Quarterly sales' })).toEqual(renamed);
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ action: 'patch', workspaceId: project.id, revision: 4, title: 'Quarterly sales' });
  });
  it('reports a conflicting rename so the user can retry without losing newer changes', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ error: 'This analysis changed. Please reload.' }, { status: 409 })));
    await expect(mutateProject(project, { action: 'patch', title: 'Quarterly sales' })).rejects.toThrow('This analysis changed. Please reload.');
  });
  it('sends preparation choices and revision without computed rows', async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ project })); vi.stubGlobal('fetch', fetch);
    await mutateProject(project, { action: 'canvas', canvas: { kind: 'graph', operations: [], positions: {} } });
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body).toEqual({ action: 'canvas', workspaceId: project.id, revision: 4, canvas: { kind: 'graph', operations: [], positions: {} } });
    expect(body).not.toHaveProperty('rows');
  });
  it('fetches previews from the server instead of processing CSV locally', async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ preview: { rowCount: 12, rows: [] }, tables: [] })); vi.stubGlobal('fetch', fetch);
    const result = await previewTable(project, 'server-table', new AbortController().signal);
    expect(result.preview.rowCount).toBe(12);
    expect(JSON.parse(fetch.mock.calls[0][1].body).action).toBe('tablePreview');
  });
  it('saves pin state without a dataset revision and returns the server-confirmed state', async () => {
    const pinned = { ...project, analyses: [{ id: 'answer-id', pinned: true }] };
    const fetch = vi.fn().mockResolvedValue(Response.json({ project: pinned })); vi.stubGlobal('fetch', fetch);
    const saved = await mutateProject(project, { action: 'pin', analysisId: 'answer-id', pinned: true });
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ action: 'pin', workspaceId: project.id, analysisId: 'answer-id', pinned: true });
    expect(saved.analyses[0].pinned).toBe(true);
  });
  it('surfaces a failed pin save instead of claiming it was pinned', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ error: 'Result not found.' }, { status: 404 })));
    await expect(mutateProject(project, { action: 'pin', analysisId: 'missing', pinned: true })).rejects.toThrow('Result not found.');
  });
  it('handles streamed events split across network chunks', async () => {
    const encoder = new TextEncoder();
    const text = JSON.stringify({ type: 'status', message: 'Working' }) + '\n' + JSON.stringify({ type: 'result', result: {}, requestId: 'r', analysisId: 'r', cached: false }) + '\n';
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new ReadableStream({ start(output) { output.enqueue(encoder.encode(text.slice(0, 13))); output.enqueue(encoder.encode(text.slice(13))); output.close(); } }))));
    const events: string[] = [];
    await analyze(project, 'Revenue?', 'r', new AbortController().signal, event => events.push(event.type));
    expect(events).toEqual(['status', 'result']);
  });
  it('reports an interrupted stream instead of pretending it completed', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"type":"status","message":"Working"}\n')));
    await expect(analyze(project, 'Revenue?', 'r', new AbortController().signal, () => {})).rejects.toThrow(/ended early/);
  });
  it('streams dashboard cards and text before returning the saved dashboard', async () => {
    const saved = { id: 'saved-dashboard', dataVersion: 2, tableIds: ['sales'], cards: [], summary: '**Total:** 42', createdAt: '2026-10-24' };
    const lines = [
      { type: 'status', message: 'Calculating…' },
      { type: 'card', index: 0, card: { title: 'Revenue' } },
      { type: 'text', text: '**Total:** 42' },
      { type: 'dashboard', dashboard: saved },
      { type: 'done', requestId: 'r' },
    ].map(event => JSON.stringify(event)).join('\n');
    const bytes = new TextEncoder().encode(lines);
    const fetch = vi.fn().mockResolvedValue(new Response(new ReadableStream({ start(output) {
      // Split in the middle of a UTF-8 character as well as an NDJSON event.
      for (let i = 0; i < bytes.length; i += 7) output.enqueue(bytes.slice(i, i + 7));
      output.close();
    } })));
    vi.stubGlobal('fetch', fetch);
    const events: string[] = [];
    expect(await generateDashboard(project.id, ['sales'], new AbortController().signal, event => events.push(event.type))).toEqual(saved);
    expect(fetch.mock.calls[0][0]).toBe('/api/analyses/server-workspace/dashboard/stream');
    expect(events).toEqual(['status', 'card', 'text', 'dashboard', 'done']);
  });
  it.each([
    ['{"type":"card","index":0,"card":{}}\n', 'ended early'],
    ['{"type":"error","message":"The dataset changed.","requestId":"r"}\n', 'dataset changed'],
  ])('does not treat an incomplete dashboard as saved', async (body, message) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body)));
    await expect(generateDashboard(project.id, ['sales'], new AbortController().signal, () => {})).rejects.toThrow(message);
  });
  it('surfaces backend validation failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ error: 'Column types do not match.' }, { status: 400 })));
    await expect(mutateProject(project, { action: 'removeFile', fileId: 'missing' })).rejects.toThrow(/Column types/);
  });
});
