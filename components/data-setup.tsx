'use client';

import { useEffect, useRef, useState } from 'react';
import { LIMITS } from '@/shared/contracts';
import { useSessionDraft } from '@/lib/session-draft';
import type { PreparedView, Project, TableInfo } from '@/shared/workspace';
import { previewTable, type Mutation } from '@/lib/api';
import type { DerivedTable, TableGraph } from '@/shared/preparation';
import { operationInputs } from '@/shared/preparation';
import { DataTable } from './result-card';
import { Icon } from './icons';
import { nodePosition, TableCanvas, type ColumnPort } from './table-canvas';

type Connection = { kind: 'join'; left: ColumnPort; right: ColumnPort } | { kind: 'stack'; leftId: string; rightId: string };
type Props = { project: Project; onAction: (action: Mutation) => Promise<Project>; onContinue: () => void };
export function DataSetup({ project, onAction, onContinue }: Props) {
  const [draft, setDraft] = useSessionDraft(`analysis:${project.id}:canvas`, { dataVersion: project.dataVersion, graph: project.canvas });
  const graph = draft.dataVersion === project.dataVersion ? draft.graph : project.canvas;
  function setGraph(value: TableGraph) { setDraft({ dataVersion: project.dataVersion, graph: value }); }
  const tables = project.tables;
  const [selection, setSelectedId] = useSessionDraft(`analysis:${project.id}:canvas-selection`, project.tables[0]?.id ?? '');
  const selectedId = tables.some(table => table.id === selection) ? selection : tables[0]?.id ?? '';
  const [preview, setPreview] = useState<{ id: string; revision: number; data: PreparedView } | null>(null);
  const [previewError, setPreviewError] = useState('');
  const [connection, setConnection] = useState<Connection | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false), [dragging, setDragging] = useState(false), [error, setError] = useState('');
  const input = useRef<HTMLInputElement>(null), previewPanel = useRef<HTMLDivElement>(null);
  const dirty = JSON.stringify(graph) !== JSON.stringify(project.canvas);
  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    // Saved source and derived previews read only eight rows from their stored table.
    previewTable(project, selectedId, controller.signal, JSON.stringify(graph.operations) === JSON.stringify(project.canvas.operations) ? undefined : graph).then(result => {
      if (!controller.signal.aborted) { setPreview({ id: selectedId, revision: project.revision, data: result.preview }); setPreviewError(''); }
    }).catch(error => { if (!controller.signal.aborted) { setPreview(null); setPreviewError(error.message); } });
    return () => controller.abort();
    // Positions are presentation only. Fetch when the selected table or graph operations change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, graph.operations, project.revision]);
  function accept(next: Project) {
    setDraft({ dataVersion: next.dataVersion, graph: next.canvas });
    setSelectedId(id => next.tables.some(table => table.id === id) ? id : next.tables[0]?.id ?? '');
  }
  async function save(continueToData = false) {
    setBusy(true); setError('');
    try { if (dirty) accept(await onAction({ action: 'canvas', canvas: graph })); if (continueToData) onContinue(); }
    catch (error) { setError((error as Error).message); } finally { setBusy(false); }
  }
  async function addFiles(incoming: File[]) {
    if (!incoming.length || busy) return;
    setBusy(true); setError('');
    try {
      if (project.files.length + incoming.length > LIMITS.files) throw new Error('Each analysis can contain up to five files.');
      if (incoming.reduce((n, file) => n + file.size, 0) + project.files.reduce((n, file) => n + file.bytes, 0) > LIMITS.bytes) throw new Error('Source files must total 15 MB or less.');
      if (dirty) await onAction({ action: 'canvas', canvas: graph });
      accept(await onAction({ action: 'upload', files: incoming }));
    } catch (error) { setError((error as Error).message); } finally { setBusy(false); }
  }
  async function connect(node: DerivedTable) {
    if (graph.operations.length >= 8) throw new Error('Use at most eight join or stack operations.');
    const leftId = operationInputs(node.operation)[0];
    const leftPosition = nodePosition(graph, leftId, tables.findIndex(table => table.id === leftId));
    const next: TableGraph = { ...graph, operations: [...graph.operations, node], positions: { ...graph.positions, [node.id]: { x: Math.min(6000, leftPosition.x + 600), y: Math.min(6000, leftPosition.y + 190) } } };
    // Saving validates and materializes the output once. Its preview then reads eight rows.
    const saved = await onAction({ action: 'canvas', canvas: next });
    accept(saved); setSelectedId(node.id); setConnection(null);
  }
  async function remove() {
    if (!removing) return;
    setBusy(true); setError('');
    try {
      if (project.files.some(file => file.id === removing)) {
        if (dirty) await onAction({ action: 'canvas', canvas: graph });
        accept(await onAction({ action: 'removeFile', fileId: removing }));
      } else {
        const removed = new Set([removing]);
        let changed = true;
        while (changed) { changed = false; graph.operations.forEach(node => { if (!removed.has(node.id) && operationInputs(node.operation).some(id => removed.has(id))) { removed.add(node.id); changed = true; } }); }
        const next = { ...graph, operations: graph.operations.filter(node => !removed.has(node.id)), positions: Object.fromEntries(Object.entries(graph.positions).filter(([id]) => !removed.has(id))) };
        accept(await onAction({ action: 'canvas', canvas: next }));
      }
      setRemoving(null);
    } catch (error) { setError((error as Error).message); } finally { setBusy(false); }
  }
  async function rename(name: string) {
    if (!renaming) return;
    if (dirty) accept(await onAction({ action: 'canvas', canvas: graph }));
    accept(await onAction({ action: 'renameTable', tableId: renaming, name }));
    setRenaming(null);
  }
  function selectPreview(id: string) {
    setSelectedId(id);
    previewPanel.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  const currentPreview = preview?.id === selectedId && preview.revision === project.revision ? preview.data : null;
  return <div className="data-setup canvas-setup">
    <div className="setup-intro"><span className="step-number"><Icon name="upload" size={18}/></span><div><h2>Your tables</h2><p>Upload CSVs, then arrange and connect your tables.</p></div><span className="source-count">{project.files.length} / 5 files</span></div>
    {error && <div className="alert" role="alert"><Icon name="alert" size={17}/>{error}</div>}
    <div className={`upload-zone preparation-upload ${project.files.length ? 'compact-upload' : ''} ${dragging ? 'dragging' : ''}`} onDragOver={event => { event.preventDefault(); if (!busy) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); void addFiles(Array.from(event.dataTransfer.files)); }}>
      <span className="upload-symbol"><Icon name="upload" size={26}/></span><div><h2>{project.files.length ? 'Add CSV tables' : 'Drop your CSV files here'}</h2><p>Choose files from your computer or drag them into this area.</p><span className="upload-limits">Up to 5 files · 15 MB total · 20,000 rows</span></div><button className="primary" disabled={busy || project.files.length >= 5} onClick={() => input.current?.click()}><Icon name="plus" size={16}/>{busy ? 'Loading…' : 'Choose files'}</button>
    </div>
    <input ref={input} className="sr-only" type="file" accept=".csv,text/csv" multiple aria-label="Upload CSV files" onChange={event => { if (event.target.files) void addFiles(Array.from(event.target.files)); event.target.value = ''; }}/>
    {!!tables.length && <>
      <div className="canvas-toolbar"><div><h2>Table canvas <span>{tables.length}</span></h2><p>Unconnected tables stay independent. Join and stack results appear as new tables.</p></div><button className="secondary" disabled={busy || !dirty} onClick={() => void save()}>{dirty ? 'Save layout' : 'Layout saved'}<Icon name="check" size={14}/></button></div>
      <TableCanvas analysisId={project.id} graph={graph} tables={tables} selectedId={selectedId} disabled={busy || !!connection || !!removing || !!renaming} onChange={setGraph} onSelect={selectPreview} onJoin={(left, right) => setConnection({ kind: 'join', left, right })} onStack={(leftId, rightId) => setConnection({ kind: 'stack', leftId, rightId })} onRemove={setRemoving} onRename={setRenaming}/>
      <div ref={previewPanel} className="canvas-preview" aria-label="Selected table preview"><div className="section-heading"><div><h3>{tables.find(table => table.id === selectedId)?.name ?? 'Table preview'}</h3><p>{currentPreview ? `${currentPreview.rowCount.toLocaleString()} rows · ${currentPreview.columns.length} columns · First 8 rows` : 'Choose a table to see its data.'}</p></div><label><span className="sr-only">Preview table</span><select value={selectedId} onChange={event => selectPreview(event.target.value)}>{tables.map(table => <option key={table.id} value={table.id}>{table.name}</option>)}</select></label></div>
        {previewError && <p className="dialog-error" role="alert">{previewError}</p>}
        {!currentPreview && !previewError && <p className="muted" role="status">Loading table preview…</p>}
        {currentPreview && <><DataTable rows={currentPreview.rows} limit={8} totalRows={currentPreview.rowCount}/>{!!currentPreview.notes.length && <ul className="preparation-notes">{currentPreview.notes.map(note => <li key={note}>{note}</li>)}</ul>}</>}
      </div>
      <div className="prepare-footer"><span>{dirty ? 'Save your layout to keep these table positions.' : 'Every table is available for its own questions and findings.'}</span><button className="primary" disabled={busy} onClick={() => void save(true)}>Continue to data preview<Icon name="arrow" size={16}/></button></div>
    </>}
    {renaming && <RenameDialog name={tables.find(table => table.id === renaming)?.name ?? ''} onClose={() => setRenaming(null)} onRename={rename}/>}
    {connection && <ConnectionDialog connection={connection} tables={tables} onClose={() => setConnection(null)} onCreate={connect}/>}
    {removing && <RemoveDialog name={tables.find(table => table.id === removing)?.name ?? 'this table'} busy={busy} onClose={() => setRemoving(null)} onRemove={remove}/>}
  </div>;
}
function ConnectionDialog({ connection, tables, onClose, onCreate }: { connection: Connection; tables: TableInfo[]; onClose: () => void; onCreate: (node: DerivedTable) => Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState(connection.kind === 'join' ? 'Joined table' : 'Stacked table');
  const [joinType, setJoinType] = useState<'inner' | 'left'>('inner');
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  useEffect(() => { dialog.current?.showModal(); }, []);
  const left = tables.find(table => table.id === (connection.kind === 'join' ? connection.left.tableId : connection.leftId))!;
  const right = tables.find(table => table.id === (connection.kind === 'join' ? connection.right.tableId : connection.rightId))!;
  return <dialog ref={dialog} className="create-dialog connection-dialog" aria-labelledby="connection-title" onCancel={event => { if (busy) event.preventDefault(); else onClose(); }}><form onSubmit={async event => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await onCreate({ id: crypto.randomUUID(), name: name.trim(), operation: connection.kind === 'stack' ? { kind: 'stack', fileIds: [connection.leftId, connection.rightId] } : { kind: 'join', leftId: connection.left.tableId, rightId: connection.right.tableId, leftKey: connection.left.column, rightKey: connection.right.column, joinType } });
    } catch (error) { setError((error as Error).message); setBusy(false); }
  }}><div className="dialog-heading"><span className="icon-tile purple"><Icon name="database" size={20}/></span><button className="icon-button" type="button" disabled={busy} aria-label="Close connection" onClick={onClose}><Icon name="close" size={18}/></button></div><h2 id="connection-title">{connection.kind === 'join' ? 'Join tables' : 'Stack tables'}</h2>
    {connection.kind === 'join' ? <><p className="connection-equation"><strong>{left.name}</strong><span>{connection.left.column}</span><b>=</b><strong>{right.name}</strong><span>{connection.right.column}</span></p><label htmlFor="join-type">Rows to include</label><select id="join-type" value={joinType} disabled={busy} onChange={event => setJoinType(event.target.value as 'inner' | 'left')}><option value="inner">Inner join — matching rows</option><option value="left">Left join — all rows from {left.name}</option></select></> : <p>Append rows from <strong>{right.name}</strong> below <strong>{left.name}</strong>. Column names and types must match. Both original tables remain available.</p>}
    <label htmlFor="result-table-name">Result table name</label><input autoFocus id="result-table-name" required maxLength={80} value={name} disabled={busy} onChange={event => setName(event.target.value)}/>
    {error && <p className="dialog-error" role="alert">{error}</p>}<div className="dialog-actions"><button type="button" className="secondary" disabled={busy} onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !name.trim()}>{busy ? 'Checking tables…' : connection.kind === 'join' ? 'Create join' : 'Create stack'}</button></div>
  </form></dialog>;
}
function RemoveDialog({ name, busy, onClose, onRemove }: { name: string; busy: boolean; onClose: () => void; onRemove: () => Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="create-dialog" aria-labelledby="remove-table-title" onCancel={event => { if (busy) event.preventDefault(); else onClose(); }}><h2 id="remove-table-title">Remove {name}?</h2><p>This also removes tables built from it. Existing findings will be cleared because the available data changes.</p><div className="dialog-actions"><button className="secondary" autoFocus disabled={busy} onClick={onClose}>Cancel</button><button className="danger" disabled={busy} onClick={() => void onRemove()}>{busy ? 'Removing…' : 'Remove table'}</button></div></dialog>;
}

function RenameDialog({ name, onClose, onRename }: { name: string; onClose: () => void; onRename: (name: string) => Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [value, setValue] = useState(name), [busy, setBusy] = useState(false), [error, setError] = useState('');
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="create-dialog" aria-labelledby="rename-table-title" onCancel={event => { if (busy) event.preventDefault(); else onClose(); }}><form onSubmit={async event => {
    event.preventDefault(); setBusy(true); setError('');
    try { await onRename(value.trim()); } catch (error) { setError((error as Error).message); setBusy(false); }
  }}><h2 id="rename-table-title">Rename table</h2><p>Choose a name to recognize this table throughout your analysis.</p><label htmlFor="table-name">Table name</label><input autoFocus id="table-name" maxLength={80} required value={value} disabled={busy} onChange={event => setValue(event.target.value)}/>{error && <p className="dialog-error" role="alert">{error}</p>}<div className="dialog-actions"><button type="button" className="secondary" disabled={busy} onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !value.trim()}>{busy ? 'Saving…' : 'Save name'}</button></div></form></dialog>;
}
