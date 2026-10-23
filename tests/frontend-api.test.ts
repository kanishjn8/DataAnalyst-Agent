import { afterEach, describe, expect, it, vi } from 'vitest';
import { analyze, deleteProject, listProjects, mutateProject, previewTable } from '../lib/api';
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
  it('surfaces backend validation failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ error: 'Column types do not match.' }, { status: 400 })));
    await expect(mutateProject(project, { action: 'removeFile', fileId: 'missing' })).rejects.toThrow(/Column types/);
  });
});
