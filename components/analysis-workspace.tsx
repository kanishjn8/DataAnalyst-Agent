'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { analysisPath, type AnalysisView } from '@/lib/routes';
import { useSessionDraft } from '@/lib/session-draft';
import type { Capabilities, PreparedView, Project } from '@/shared/workspace';
import type { AnalysisResult } from '@/shared/contracts';
import { analyze, exportFile, previewTable, type Mutation } from '@/lib/api';
import { DataSetup } from './data-setup';
import { DataTable, ResultCard } from './result-card';
import { Icon } from './icons';
import { signOut } from '@/lib/auth';
import { DashboardPanel } from './dashboard-panel';
import { useAccount } from './auth-boundary';
import { GenerationProgress } from './generation-progress';

const views = [
  { id: 'setup', label: 'Data setup', icon: 'database' },
  { id: 'data', label: 'Data preview', icon: 'table' },
  { id: 'analysis', label: 'Analysis', icon: 'message' },
  { id: 'dashboard', label: 'Dashboard', icon: 'grid' },
] as const;
const questions = [
  { icon: 'chart' as const, title: 'Compare performance', text: 'Which category has the highest total?', color: 'purple' },
  { icon: 'trend' as const, title: 'Explore a trend', text: 'Show monthly trends.', color: 'blue' },
  { icon: 'alert' as const, title: 'Find unusual values', text: 'Detect anomalies in the table.', color: 'amber' },
  { icon: 'search' as const, title: 'Get an overview', text: 'Summarize this table and its quality.', color: 'teal' },
];
export function AnalysisWorkspace({ project, view, onAction, onRefresh, onBack, saveState, capabilities }: {
  project: Project; view: AnalysisView; onAction: (action: Mutation) => Promise<Project>; onRefresh: () => Promise<Project>;
  onBack: () => void; saveState: string; capabilities: Capabilities;
}) {
  const router = useRouter(), search = useSearchParams();
  const [title, setTitle] = useSessionDraft(`analysis:${project.id}:title`, project.title);
  const [question, setQuestion] = useSessionDraft(`analysis:${project.id}:${project.dataVersion}:question`, project.question);
  const tableId = search.get('table') ?? '';
  const previewId = tableId;
  const allTables = tableId === 'all';
  const resultFilter = allTables || search.get('findings') === 'all' ? '' : tableId;
  const [preview, setPreview] = useState<{ id: string; version: number; data: PreparedView | null; error: string }>({ id: '', version: -1, data: null, error: '' });
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [steps, setSteps] = useState<string[]>([]), [streamText, setStreamText] = useState('');
  const [liveResults, setLiveResults] = useState<{ id: string; result: AnalysisResult }[]>([]);
  const composer = useRef<HTMLTextAreaElement>(null), abort = useRef<AbortController | null>(null);
  const hasTables = project.tables.length > 0;
  const effectiveView = hasTables ? view : 'setup';
  const selectedPreview = project.tables.some(table => table.id === previewId) ? previewId : project.tables[0]?.id ?? '';
  const selectedTable = project.tables.find(table => table.id === tableId);
  const data = preview.id === selectedPreview && preview.version === project.dataVersion ? preview.data : null;
  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    if (!selectedPreview || view !== 'data') return;
    const controller = new AbortController();
    previewTable(project, selectedPreview, controller.signal).then(result => {
      if (!controller.signal.aborted) setPreview({ id: selectedPreview, version: project.dataVersion, data: result.preview, error: '' });
    }).catch(error => { if (!controller.signal.aborted) setPreview({ id: selectedPreview, version: project.dataVersion, data: null, error: error.message }); });
    return () => controller.abort();
  }, [project, selectedPreview, view]);
  function changeView(next: AnalysisView, selected = tableId) {
    if (!busy) router.push(analysisPath(project.id, next, selected), { scroll: false });
  }
  function setResultFilter(value: string) {
    const path = analysisPath(project.id, view, tableId);
    router.replace(value ? path : `${path}${tableId ? '&' : '?'}findings=all`, { scroll: false });
  }
  async function ask(scope: string) {
    if (busy || !capabilities.analysis || (scope !== 'all' && !selectedTable)) return;
    const text = question.trim() || (scope === 'all' ? 'Summarize this table and its data quality.' : '');
    if (!text) return;
    setBusy(true); setError(''); setStreamText(''); setLiveResults([]); setSteps(['Preparing your question…']); setResultFilter(scope === 'all' ? '' : scope);
    const controller = new AbortController(); abort.current = controller;
    try {
      const current = await onAction({ action: 'patch', question: text });
      await analyze(current, text, crypto.randomUUID(), controller.signal, event => {
        if (event.type === 'status') { setSteps(steps => steps.at(-1) === event.message ? steps : [...steps, event.message]); setStreamText(''); }
        if (event.type === 'text') setStreamText(text => text + event.text);
        if (event.type === 'result') { setLiveResults(results => [...results, { id: event.analysisId, result: event.result }]); setStreamText(''); }
      }, scope);
      if (!controller.signal.aborted) { setQuestion(''); await onAction({ action: 'patch', question: '' }); }
    } catch (error) { if (!controller.signal.aborted) setError((error as Error).message); }
    finally {
      // Reload committed findings after completion or an interrupted request.
      try { await onRefresh(); } catch (error) { setError((error as Error).message); }
      setBusy(false); setSteps([]); setStreamText(''); setLiveResults([]);
    }
  }
  async function exportData(action: 'exportDataset' | 'exportResult' | 'exportReport', id?: string) {
    try { await exportFile(project.id, action, id, action === 'exportDataset' ? selectedPreview : undefined); }
    catch (error) { setError((error as Error).message); }
  }
  async function pin(id: string, pinned: boolean) {
    try { await onAction({ action: 'pin', analysisId: id, pinned }); } catch (error) { setError((error as Error).message); }
  }
  const turns = project.analyses.filter(turn => !resultFilter || turn.result.tableId === resultFilter || turn.result.tableIds?.includes(resultFilter) || (!turn.result.tableId && project.tables.length === 1));
  return <div className="app-shell">
    <aside className="sidebar"><div className="sidebar-brand"><span className="brand-mark"><Icon name="grid" size={21}/></span><div><strong>Workspace</strong><span>Data analysis</span></div></div><button className="new-analysis back-to-analyses" disabled={busy} onClick={onBack}><Icon name="arrow" size={16} style={{ transform: 'rotate(180deg)' }}/>Your analyses</button><p className="nav-label">THIS ANALYSIS</p><div className="sidebar-project-title" title={project.title}>{project.title}</div><nav className="side-nav" aria-label="Analysis steps">{views.map(item => <button key={item.id} disabled={busy || (item.id !== 'setup' && !hasTables)} aria-current={effectiveView === item.id ? 'page' : undefined} onClick={() => changeView(item.id)}><Icon name={item.icon} size={18}/>{item.label}</button>)}</nav><div className="sidebar-rule"/><div className="files-heading"><p className="nav-label">TABLES</p><span>{project.tables.length}</span></div>{hasTables ? <ul className="sidebar-table-list">{project.tables.map(table => <li key={table.id}><button disabled={busy} onClick={() => { changeView('analysis', table.id); }}><Icon name={table.kind === 'source' ? 'table' : 'database'} size={15}/><span title={table.name}>{table.name}</span><small>{table.kind === 'source' ? 'CSV' : table.kind}</small></button></li>)}</ul> : <p className="sidebar-empty">Upload your CSVs<br/>to get started.</p>}<SidebarAccount saveState={saveState} disabled={busy}/></aside>
    <div className="main-shell">
      <main className="main-content"><div className="page-heading project-heading"><div><label className="sr-only" htmlFor="project-title">Analysis title</label><input id="project-title" className="project-title-input" disabled={busy} value={title} maxLength={80} onChange={event => setTitle(event.target.value)} onBlur={() => { const value = title.trim() || project.title; setTitle(value); if (value !== project.title) void onAction({ action: 'patch', title: value }).catch(() => {}); }} onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur(); }}/><p className="page-description">{effectiveView === 'setup' ? 'Arrange your tables and connect related data.' : `${project.tables.length} tables available · select any table to explore it`}</p></div>{effectiveView !== 'setup' && <button className="secondary" disabled={busy} onClick={() => changeView('setup')}><Icon name="database" size={16}/>Open table canvas</button>}</div>
      {error && <div className="alert" role="alert"><Icon name="alert" size={16}/>{error}<button onClick={() => setError('')}>Dismiss</button></div>}
      <section className={`workspace-panel${effectiveView === 'dashboard' ? ' dashboard-workspace' : ''}`}>
      {effectiveView === 'setup' && <div id="view-setup" role="region" aria-label="Data setup"><DataSetup project={project} onAction={onAction} onContinue={() => changeView('data')}/></div>}
      {effectiveView === 'data' && <div id="view-data" role="region" aria-label="Data preview" className="data-view">
        <div className="section-heading"><div><h2>Explore your tables</h2><p>Original and connected tables can each be previewed and analyzed.</p></div><button className="secondary" disabled={!data} onClick={() => void exportData('exportDataset')}><Icon name="download" size={14}/>Export CSV</button></div>
        <label className="table-picker">Preview table<select value={selectedPreview} onChange={event => changeView('data', event.target.value)}>{project.tables.map(table => <option key={table.id} value={table.id}>{table.name} · {table.rowCount.toLocaleString()} rows</option>)}</select></label>
        {preview.error && preview.id === selectedPreview && <p role="alert">{preview.error}</p>}
        {!data ? <p className="muted" role="status">Loading table…</p> : <><DataTable rows={data.rows} totalRows={data.rowCount}/><div className="data-details-grid"><div className="detail-box"><h3><Icon name="database" size={17}/>Column overview</h3><DataTable rows={data.columns.map(column => ({ column: column.name, type: column.type, missing: column.missing }))} limit={40}/></div><div className="detail-box"><h3><Icon name="shield" size={17}/>Preparation and quality notes</h3>{[...data.notes, ...data.warnings].length ? <ul className="quality-notes">{[...data.notes, ...data.warnings].map((note, index) => <li key={index}>{note}</li>)}</ul> : <p className="quality-success"><Icon name="check" size={17}/>No missing values or duplicate rows found.</p>}</div></div></>}
        <div className="data-next"><button className="secondary" onClick={() => changeView('setup')}>Back to table canvas</button><button className="primary" onClick={() => { changeView('analysis', selectedPreview); }}>Ask about this table<Icon name="arrow" size={16}/></button></div>
      </div>}
      {effectiveView === 'analysis' && <div id="view-analysis" role="region" aria-label="Analysis">
        <div className="analysis-scope"><label className="table-picker">Ask about<select value={allTables || selectedTable ? tableId : ''} disabled={busy} onChange={event => { changeView('analysis', event.target.value); }}><option value="">Choose a table</option><option value="all">All tables</option>{project.tables.map(table => <option key={table.id} value={table.id}>{table.name}</option>)}</select></label><div><strong>{allTables ? 'Ask across your workspace' : selectedTable ? `${selectedTable.rowCount.toLocaleString()} rows · ${selectedTable.columns.length} columns` : 'Select a table to ask a question'}</strong><p>{allTables ? 'Uses the relevant tables and their connections to answer your question.' : 'Choose All tables to ask across your workspace.'}</p></div></div>
        <div className="questions-section"><div className="section-heading"><div><h2>What would you like to know?</h2><p>Questions use your selection. All tables gives one answer using the relevant data.</p></div></div><div className="suggestion-grid">{questions.map(item => <button key={item.title} className="suggestion" disabled={busy} onClick={() => { setQuestion(item.text); composer.current?.focus(); }}><span className={`suggestion-icon ${item.color}`}><Icon name={item.icon} size={19}/></span><span><strong>{item.title}</strong><small>{item.text}</small></span><Icon name="arrow" size={16}/></button>)}</div></div>
        <div className="conversation-results">{resultFilter && <div className="findings-filter"><span>Findings for {project.tables.find(table => table.id === resultFilter)?.name}</span><button className="small" onClick={() => setResultFilter('')}>Show all findings</button></div>}{turns.map(turn => <article key={turn.id}><div className="question"><strong>You <span className="finding-table">{turn.result.tableName ?? 'Prepared table'}</span></strong><p>{turn.question}</p></div><ResultCard result={turn.result} onPin={() => void pin(turn.id, !turn.pinned)} onExport={() => void exportData('exportResult', turn.id)}/></article>)}{liveResults.filter(result => !project.analyses.some(turn => turn.id === result.id)).map(result => <ResultCard key={result.id} result={result.result}/>)}{busy && <GenerationProgress steps={steps} text={streamText}/>}{!!project.analyses.length && <button className="secondary" onClick={() => void exportData('exportReport')}>Export report</button>}</div>
        <div className="composer-wrap"><form className="composer" onSubmit={event => { event.preventDefault(); void ask(tableId); }}><div className="composer-input"><Icon name="spark" size={20}/><label htmlFor="question" className="sr-only">Your question</label><textarea ref={composer} id="question" placeholder={allTables ? 'Ask about all tables…' : selectedTable ? `Ask about ${selectedTable.name}…` : 'Choose a table or All tables above…'} value={question} maxLength={1000} rows={2} onChange={event => setQuestion(event.target.value)} disabled={busy} onBlur={() => { if (!busy && question !== project.question) void onAction({ action: 'patch', question }).catch(() => {}); }}/></div><div className="composer-footer"><span>{capabilities.analysis ? allTables ? 'Using workspace context · relevant tables chosen for your question' : selectedTable ? `Using ${selectedTable.name}` : 'Choose a table before sending.' : 'Analysis is currently unavailable.'}</span>{busy ? <button type="button" className="secondary" onClick={() => abort.current?.abort()}>Stop</button> : <button className="send-button" disabled={!capabilities.analysis || !question.trim() || (!selectedTable && !allTables)}>Send<Icon name="arrow" size={17}/></button>}</div></form></div>
      </div>}
      {effectiveView === 'dashboard' && <div id="view-dashboard" role="region" aria-label="Dashboard" className="dashboard-view"><DashboardPanel key={`${project.id}:${project.dataVersion}`} project={project} available={capabilities.analysis}/>{project.analyses.some(turn => turn.pinned) ? project.analyses.filter(turn => turn.pinned).map(turn => <div key={turn.id}><button className="small" onClick={() => void pin(turn.id, false)}>Remove from dashboard</button><ResultCard result={turn.result} onExport={() => void exportData('exportResult', turn.id)}/></div>) : null}</div>}
      </section></main><Footer/>
    </div>
  </div>;
}
export function Footer() { return <footer><span>Data analysis</span></footer>; }

export function SidebarAccount({ saveState, disabled = false }: { saveState?: string; disabled?: boolean }) {
  const user = useAccount();
  const account = user?.email || 'Your account';
  return <div className="sidebar-account">
    {saveState && <span className="save-state" role="status"><span className={`status-dot ${saveState === 'Saved' ? 'saved-dot' : ''}`}/>{saveState}</span>}
    <div className="account-identity" role="group" aria-label="Current account">
      <span className="account-avatar" aria-hidden="true">{account.charAt(0).toUpperCase()}</span>
      <div className="account-details"><span>Signed in as</span><strong title={account}>{account}</strong></div>
    </div>
    <button className="secondary" disabled={disabled} onClick={() => void signOut()}>Sign out</button>
  </div>;
}
