'use client';
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import { createProject, deleteProject, getCapabilities, loadProject, listProjects, mutateProject, type Mutation } from '@/lib/api';
import { analysisPath, type AnalysisView } from '@/lib/routes';
import type { Capabilities, Project, ProjectSummary } from '@/shared/workspace';
import { AnalysisWorkspace, Footer, SidebarAccount } from './analysis-workspace';
import { ProjectList } from './project-list';
import { Icon } from './icons';

type WorkspaceState = {
  projects: ProjectSummary[]; active: Project | null; capabilities: Capabilities; saveState: string; error: string;
  clearError: () => void; reloadList: () => Promise<void>; open: (id: string, signal: AbortSignal) => Promise<void>;
  action: (mutation: Mutation) => Promise<Project>; refresh: () => Promise<Project>;
  create: (title: string) => Promise<void>; rename: (id: string, title: string) => Promise<void>; remove: (id: string) => Promise<void>; back: () => Promise<void>;
};
const Context = createContext<WorkspaceState | null>(null);
function useWorkspace() {
  const value = useContext(Context);
  if (!value) throw new Error('Workspace provider is missing.');
  return value;
}

// The shared layout keeps writes and loaded data alive during route transitions.
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectSummary[]>([]), [active, setActive] = useState<Project | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities>({ analysis: false });
  const [error, setError] = useState(''), [saveState, setSaveState] = useState('Saved');
  const current = useRef<Project | null>(null), writes = useRef<Promise<unknown>>(Promise.resolve());
  const accept = useCallback((project: Project) => {
    current.current = project; setActive(project);
    setProjects(list => [project, ...list.filter(p => p.id !== project.id)].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)));
  }, []);
  const reloadList = useCallback(async () => {
    await writes.current.catch(() => {});
    const result = await listProjects(); setProjects(result.projects); setCapabilities(result.capabilities);
  }, []);
  const open = useCallback(async (id: string, signal: AbortSignal) => {
    await writes.current.catch(() => {});
    if (signal.aborted) return;
    const [project, available] = await Promise.all([loadProject(id, signal), getCapabilities(signal)]);
    if (!signal.aborted) { accept(project); setCapabilities(available); setSaveState('Saved'); setError(''); }
  }, [accept]);
  function action(mutation: Mutation): Promise<Project> {
    const projectId = current.current?.id;
    setSaveState('Saving…'); setError('');
    const next = writes.current.catch(() => {}).then(async () => {
      const project = current.current;
      if (!project || project.id !== projectId) throw new Error('Open this analysis again before saving.');
      const saved = await mutateProject(project, mutation); accept(saved); setSaveState('Saved'); return saved;
    });
    writes.current = next;
    void next.catch(error => { setSaveState('Save failed'); setError(error.message); });
    return next;
  }
  async function back() {
    try { await writes.current; setError(''); router.push('/'); }
    catch { setError('Your latest changes were not saved. Please try again before leaving.'); }
  }
  async function refresh(): Promise<Project> {
    await writes.current;
    if (!current.current) throw new Error('Analysis not found.');
    const project = await loadProject(current.current.id); accept(project); return project;
  }
  async function create(title: string) {
    const project = await createProject(title); accept(project); setSaveState('Saved'); router.push(analysisPath(project.id));
  }
  async function rename(id: string, title: string) {
    const next = writes.current.catch(() => {}).then(async () => {
      // Load the latest revision so a name change cannot overwrite newer edits.
      const project = await loadProject(id);
      const saved = await mutateProject(project, { action: 'patch', title });
      // An earlier title draft must not restore the old name on the next visit.
      try { sessionStorage.removeItem(`analysis:${id}:title`); } catch { /* Storage may be disabled. */ }
      if (current.current?.id === id) { accept(saved); setSaveState('Saved'); }
      else setProjects(list => [saved, ...list.filter(project => project.id !== id)].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)));
    });
    writes.current = next;
    await next;
  }
  async function remove(id: string) {
    await writes.current; await deleteProject(id);
    setProjects(list => list.filter(project => project.id !== id));
    if (current.current?.id === id) { current.current = null; setActive(null); }
  }
  return <Context.Provider value={{ projects, active, capabilities, saveState, error, clearError: () => setError(''), reloadList, open, action, refresh, create, rename, remove, back }}>{children}</Context.Provider>;
}

export function Workspace() {
  const router = useRouter();
  const { projects, reloadList, create, rename, remove } = useWorkspace();
  const [loading, setLoading] = useState(true), [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    reloadList().catch(error => { if (alive) setError(error.message); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [reloadList]);
  return <div className="app-shell overview-shell"><aside className="sidebar"><div className="sidebar-brand"><span className="brand-mark"><Icon name="grid" size={21}/></span><div><strong>Workspace</strong><span>Data analysis</span></div></div><p className="nav-label">YOUR WORKSPACE</p><nav className="side-nav" aria-label="Main navigation"><button aria-current="page"><Icon name="grid" size={18}/>Your analyses<span className="nav-count">{projects.length}</span></button></nav><div className="sidebar-rule"/><SidebarAccount/></aside><div className="main-shell"><main className="main-content">{error && <div className="alert" role="alert"><Icon name="alert" size={16}/>{error}<button onClick={() => { setLoading(true); reloadList().then(() => setError('')).catch(error => setError(error.message)).finally(() => setLoading(false)); }}>Retry</button></div>}<ProjectList projects={projects} loading={loading} onOpen={id => router.push(analysisPath(id))} onCreate={create} onRename={rename} onDelete={remove}/></main><Footer/></div></div>;
}

export function AnalysisRoute({ analysisId, view }: { analysisId: string; view: AnalysisView }) {
  const router = useRouter();
  const { active, capabilities, saveState, error, clearError, open, action, refresh, back } = useWorkspace();
  const [loadingError, setLoadingError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    open(analysisId, controller.signal).catch(error => { if (!controller.signal.aborted) setLoadingError(error.message); });
    return () => controller.abort();
  }, [analysisId, open, attempt]);
  useEffect(() => {
    if (active?.id === analysisId && !active.tables.length && view !== 'setup') router.replace(analysisPath(analysisId));
  }, [active, analysisId, view, router]);
  if (loadingError || active?.id !== analysisId) return <div className="app-shell overview-shell"><div className="main-shell"><main className="main-content">{loadingError ? <div className="alert" role="alert">{loadingError}<button onClick={() => { setLoadingError(''); setAttempt(value => value + 1); }}>Retry</button></div> : <p role="status">Loading analysis…</p>}<button className="secondary" onClick={() => void back()}>Your analyses</button></main></div></div>;
  return <>{error && <div className="global-save-error" role="alert">{error}<button onClick={clearError}>Dismiss</button></div>}<AnalysisWorkspace key={active.id} project={active} view={view} onAction={action} onRefresh={refresh} onBack={() => void back()} saveState={saveState} capabilities={capabilities}/></>;
}
