'use client';
import { useEffect, useRef, useState } from 'react';
import { generateDashboard, getDashboard, type Dashboard } from '@/lib/api';
import type { Project } from '@/shared/workspace';
import { operationInputs } from '@/shared/preparation';
import { ResultCard } from './result-card';
import { Icon } from './icons';
import { Markdown } from './markdown';
import { GenerationProgress } from './generation-progress';

export function DashboardPanel({ project, available }: { project: Project; available: boolean }) {
  const consumed = new Set(project.canvas.operations.flatMap(node => operationInputs(node.operation)));
  const [selected, setSelected] = useState(project.tables.filter(table => !consumed.has(table.id)).map(table => table.id));
  const [dashboard, setDashboard] = useState<Dashboard | null>(null), [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [error, setError] = useState('');
  const [steps, setSteps] = useState<string[]>([]), [text, setText] = useState(''), [cards, setCards] = useState<Dashboard['cards']>([]);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    getDashboard(project.id, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      setDashboard(value);
      if (value?.dataVersion === project.dataVersion) setSelected(value.tableIds);
      setLoading(false);
    }).catch(error => { if (!controller.signal.aborted) { setError(error.message); setLoading(false); } });
    return () => controller.abort();
  }, [project.id, project.dataVersion]);
  async function generate() {
    const controller = new AbortController(); abort.current = controller;
    setBusy(true); setError(''); setSteps(['Preparing your dashboard…']); setText(''); setCards([]);
    try {
      const value = await generateDashboard(project.id, selected, controller.signal, event => {
        if (controller.signal.aborted) return;
        if (event.type === 'status') setSteps(steps => [...steps, event.message]);
        if (event.type === 'text') setText(text => text + event.text);
        if (event.type === 'card') setCards(cards => [...cards, event.card]);
      });
      if (!controller.signal.aborted) setDashboard(value);
    } catch (error) {
      if (!controller.signal.aborted) setError((error as Error).message);
    } finally {
      if (!controller.signal.aborted) { setBusy(false); setSteps([]); setText(''); setCards([]); }
    }
  }
  const current = dashboard?.dataVersion === project.dataVersion ? dashboard : null;
  const visibleCards = busy ? cards : current?.cards ?? [];
  const shownTables = current?.tableIds.map(id => project.tables.find(table => table.id === id)?.name).filter(Boolean).join(', ');
  return <div className="dashboard-layout">
    <section className="dashboard-selection workspace-panel" aria-labelledby="dashboard-tables-title">
      <div className="section-heading"><div><h2 id="dashboard-tables-title">Tables to include</h2><p>Choose the data for your dashboard.</p></div>
        <button className="secondary" disabled={loading || busy || !available || !selected.length} onClick={() => void generate()}><Icon name="chart" size={16}/>{busy ? 'Generating…' : current ? 'Regenerate dashboard' : 'Generate dashboard'}</button>
      </div>
      <div className="dashboard-table-options" role="group" aria-label="Dashboard tables">{project.tables.map(table => <label key={table.id} className={selected.includes(table.id) ? 'selected' : ''}>
        <input type="checkbox" disabled={loading || busy} checked={selected.includes(table.id)} onChange={event => setSelected(ids => event.target.checked ? [...ids, table.id] : ids.filter(id => id !== table.id))}/>
        <span><strong>{table.name}</strong><small>{table.rowCount.toLocaleString()} rows · {table.kind === 'source' ? 'CSV' : table.kind === 'join' ? 'Joined table' : 'Stacked table'}</small></span>
      </label>)}</div>
      {!selected.length && <p className="caption">Select at least one table to generate a dashboard.</p>}
    </section>
    <section className="dashboard-results" aria-labelledby="dashboard-results-title" aria-busy={loading || busy}>
      <div className="section-heading"><div><h2 id="dashboard-results-title">Your dashboard</h2><p>{busy ? 'Cards appear as they are calculated.' : current ? `Based on: ${shownTables}` : 'Your summary and charts will appear here.'}</p></div></div>
      {error && <div className="alert" role="alert">{error}</div>}
      {loading && <p className="muted" role="status">Loading dashboard…</p>}
      {busy && <GenerationProgress steps={steps} text={text}/>}
      {!busy && current?.summary && <section className="dashboard-summary workspace-panel" aria-label="Dashboard summary"><Markdown>{current.summary}</Markdown></section>}
      <div className="dashboard-cards">{visibleCards.map((card, index) => <ResultCard key={`${busy ? 'generating' : current?.id}-${index}`} result={card}/>)}</div>
      {!loading && !busy && !current && <div className="dashboard-empty workspace-panel"><span className="icon-tile purple"><Icon name="chart" size={22}/></span><h3>{available ? 'Ready when you are' : 'Analysis is currently unavailable'}</h3><p>{available ? 'Choose your tables above, then generate a dashboard to explore the key figures and trends.' : 'Please try again later.'}</p></div>}
    </section>
  </div>;
}
