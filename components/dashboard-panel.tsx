'use client';
import { useEffect, useState } from 'react';
import { generateDashboard, getDashboard, type Dashboard } from '@/lib/api';
import type { Project } from '@/shared/workspace';
import { operationInputs } from '@/shared/preparation';
import { ResultCard } from './result-card';
import { Icon } from './icons';

export function DashboardPanel({ project, available }: { project: Project; available: boolean }) {
  const consumed = new Set(project.canvas.operations.flatMap(node => operationInputs(node.operation)));
  const [selected, setSelected] = useState(project.tables.filter(table => !consumed.has(table.id)).map(table => table.id));
  const [dashboard, setDashboard] = useState<Dashboard | null>(null), [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    getDashboard(project.id, controller.signal).then(value => { if (!controller.signal.aborted) { setDashboard(value); setLoading(false); } }).catch(error => { if (!controller.signal.aborted) { setError(error.message); setLoading(false); } });
    return () => controller.abort();
  }, [project.id, project.dataVersion]);
  async function generate() {
    setBusy(true); setError('');
    try { setDashboard(await generateDashboard(project.id, selected)); }
    catch (error) { setError((error as Error).message); } finally { setBusy(false); }
  }
  const current = dashboard?.dataVersion === project.dataVersion ? dashboard : null;
  return <section><div className="section-heading"><div><h2>Your dashboard</h2><p>Choose the tables to include. Each finding stays linked to its source.</p></div><button className="secondary" disabled={busy || !available || !selected.length} onClick={() => void generate()}><Icon name="chart" size={16}/>{busy ? 'Generating…' : current ? 'Regenerate dashboard' : 'Generate dashboard'}</button></div>
    <div className="stack-options" role="group" aria-label="Dashboard tables">{project.tables.map(table => <label key={table.id}><input type="checkbox" disabled={busy} checked={selected.includes(table.id)} onChange={event => setSelected(ids => event.target.checked ? [...ids, table.id] : ids.filter(id => id !== table.id))}/>{table.name}</label>)}</div>
    {error && <div className="alert" role="alert">{error}</div>}
    {(loading || busy) && <p className="muted" role="status">{busy ? 'Calculating your dashboard…' : 'Loading dashboard…'}</p>}
    {!available && !current && <p className="muted">Analysis is currently unavailable.</p>}
    {current && <><p className="answer">{current.summary}</p>{current.cards.map((card, index) => <ResultCard key={`${current.id}-${index}`} result={card}/>)}</>}
  </section>;
}
