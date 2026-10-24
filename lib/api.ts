import type { TableGraph } from '@/shared/preparation';
import type { Capabilities, PreparedView, Project, ProjectSummary, TableInfo } from '@/shared/workspace';
import type { StreamEvent } from '@/shared/contracts';
import { authHeaders } from './auth';
const root = process.env.NEXT_PUBLIC_API_BASE_URL || (process.env.NODE_ENV === 'development' ? 'http://127.0.0.1:4000' : '/api');
async function post(path: string, body: unknown, signal?: AbortSignal) {
  let response: Response;
  try { response = await fetch(`${root}/${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...await authHeaders() }, body: JSON.stringify(body), signal }); }
  catch (error) { if (signal?.aborted) throw error; throw new Error('The service is unavailable. Please try again.'); }
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    throw new Error(problem.error || 'Could not complete this request. Please try again.');
  }
  return response;
}
export async function listProjects(): Promise<{ projects: ProjectSummary[]; capabilities: Capabilities }> { return (await post('workspace', { action: 'list' })).json(); }
export async function getCapabilities(signal?: AbortSignal): Promise<Capabilities> {
  const response = await fetch(`${root}/health`, { signal, cache: 'no-store' });
  if (!response.ok) throw new Error('The service is unavailable. Please try again.');
  return (await response.json()).capabilities;
}
export async function loadProject(id: string, signal?: AbortSignal): Promise<Project> { return (await (await post('workspace', { action: 'load', workspaceId: id }, signal)).json()).project; }
export async function createProject(title: string): Promise<Project> { return (await (await post('workspace', { action: 'create', title })).json()).project; }
export async function deleteProject(id: string): Promise<void> { await post('workspace', { action: 'delete', workspaceId: id }); }
export type Mutation = { action: 'patch'; title?: string; question?: string } | { action: 'upload'; files: File[] } | { action: 'removeFile'; fileId: string } | { action: 'renameTable'; tableId: string; name: string } | { action: 'canvas'; canvas: TableGraph } | { action: 'pin'; analysisId: string; pinned: boolean };
export async function mutateProject(project: Project, mutation: Mutation): Promise<Project> {
  if (mutation.action === 'upload') {
    let latest = project;
    for (const file of mutation.files) {
      const grant = await (await post(`analyses/${project.id}/uploads`, { name: file.name, bytes: file.size, contentType: file.type || 'text/csv' })).json();
      const uploaded = await fetch(grant.url, { method: grant.method, headers: grant.headers, body: file });
      if (!uploaded.ok) throw new Error('Could not upload this file. Please try again.');
      latest = (await (await post(`uploads/${grant.uploadId}/complete`, {})).json()).project;
    }
    return latest;
  }
  return (await (await post('workspace', { ...mutation, workspaceId: project.id, ...(mutation.action !== 'pin' ? { revision: project.revision } : {}) })).json()).project;
}
export async function previewTable(project: Project, tableId: string, signal: AbortSignal, canvas?: TableGraph): Promise<{ preview: PreparedView; tables: TableInfo[] }> {
  return (await post('workspace', { action: 'tablePreview', workspaceId: project.id, revision: project.revision, tableId, ...(canvas ? { canvas } : {}) }, signal)).json();
}
export async function exportFile(workspaceId: string, action: 'exportDataset' | 'exportResult' | 'exportReport', analysisId?: string, tableId?: string) {
  const response = await post('workspace', { action, workspaceId, ...(analysisId ? { analysisId } : {}), ...(tableId ? { tableId } : {}) });
  const blob = await response.blob(); const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url; link.download = action === 'exportReport' ? 'analysis-report.md' : action === 'exportDataset' ? 'prepared-data.csv' : 'analysis.csv'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export async function analyze(project: Project, question: string, requestId: string, signal: AbortSignal, receive: (event: StreamEvent) => void, tableId?: string) {
  const response = await post('analyze', { workspaceId: project.id, dataVersion: project.dataVersion, question, requestId, ...(tableId ? { tableId } : {}) }, signal);
  await readEvents<StreamEvent>(response, signal, receive, event => event.type === 'done' || (!tableId && event.type === 'result'));
}
async function readEvents<Event extends { type: string }>(response: Response, signal: AbortSignal, receive: (event: Event) => void, complete: (event: Event) => boolean) {
  const reader = response.body?.getReader();
  if (!reader) throw new Error('Could not read the response. Please try again.');
  const decoder = new TextDecoder(); let buffer = '', finished = false;
  const processLine = (line: string) => {
    if (!line.trim()) return;
    const event = JSON.parse(line) as Event;
    if (event.type === 'error') throw new Error('message' in event && typeof event.message === 'string' ? event.message : 'Could not complete this request.');
    if (complete(event)) finished = true;
    receive(event);
  };
  try {
    while (true) { const { done, value } = await reader.read(); if (done) break; buffer += decoder.decode(value, { stream: true }); const lines = buffer.split('\n'); buffer = lines.pop() || ''; lines.forEach(processLine); }
    processLine(buffer + decoder.decode());
    if (!finished && !signal.aborted) throw new Error('The response ended early. Please try again.');
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

export type Dashboard = { id: string; dataVersion: number; tableIds: string[]; cards: import('@/shared/contracts').AnalysisResult[]; summary: string; createdAt: string };
export type DashboardEvent = Extract<StreamEvent, { type: 'status' | 'text' | 'error' }> | { type: 'card'; index: number; card: Dashboard['cards'][number] } | { type: 'dashboard'; dashboard: Dashboard } | { type: 'done'; requestId: string };
export async function getDashboard(projectId: string, signal?: AbortSignal): Promise<Dashboard | null> {
  const response = await fetch(`${root}/analyses/${projectId}/dashboard`, { headers: await authHeaders(), signal });
  if (!response.ok) throw new Error('Could not load the dashboard. Please try again.');
  return (await response.json()).dashboard;
}
export async function generateDashboard(projectId: string, tableIds: string[], signal: AbortSignal, receive: (event: DashboardEvent) => void): Promise<Dashboard> {
  const response = await post(`analyses/${projectId}/dashboard/stream`, { tableIds, requestId: crypto.randomUUID() }, signal);
  let dashboard: Dashboard | null = null;
  await readEvents<DashboardEvent>(response, signal, event => {
    if (event.type === 'dashboard') dashboard = event.dashboard;
    receive(event);
  }, event => event.type === 'dashboard');
  if (!dashboard) throw new Error('The dashboard was not saved. Please try again.');
  return dashboard;
}
