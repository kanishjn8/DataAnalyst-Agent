'use client';
import { useEffect, useRef, useState } from 'react';
import type { ProjectSummary } from '@/shared/workspace';
import { Icon } from './icons';
export function ProjectList({ projects, loading, onOpen, onCreate, onRename, onDelete }: { projects: ProjectSummary[]; loading: boolean; onOpen: (id: string) => void; onCreate: (title: string) => Promise<void>; onRename: (id: string, title: string) => Promise<void>; onDelete: (id: string) => Promise<void> }) {
  const [creating, setCreating] = useState(false), [search, setSearch] = useState('');
  const [deleting, setDeleting] = useState<ProjectSummary | null>(null);
  const [renaming, setRenaming] = useState<ProjectSummary | null>(null);
  const visible = projects.filter(p => p.title.toLowerCase().includes(search.toLowerCase()));
  return <>
    <div className="page-heading"><div><h1>Data analysis</h1><p className="page-description">Organize your data and explore your analyses.</p></div><button className="primary" onClick={() => setCreating(true)}><Icon name="plus" size={17}/>New analysis</button></div>
    <div className="projects-toolbar"><div><h2>Your analyses <span>{projects.length}</span></h2><p>Pick up where you left off, or start with a new set of files.</p></div>{projects.length > 0 && <label className="project-search"><Icon name="search" size={16}/><span className="sr-only">Search analyses</span><input placeholder="Search analyses…" value={search} onChange={e => setSearch(e.target.value)}/></label>}</div>
    {loading ? <div className="project-empty" role="status">Loading your analyses…</div> : projects.length ? <div className="project-grid">{visible.map((project, index) => <article className="project-card" key={project.id}><button className="project-card-main" onClick={() => onOpen(project.id)}><div className="project-card-top"><span className={`icon-tile ${['purple', 'blue', 'teal'][index % 3]}`}><Icon name="table" size={21}/></span><span className={`project-state ${project.ready ? 'is-ready' : ''}`}>{project.ready ? 'Dataset ready' : project.fileCount ? 'Prepare data' : 'New analysis'}</span></div><h3>{project.title}</h3><p>{project.fileCount} CSV {project.fileCount === 1 ? 'file' : 'files'} <span>·</span> {project.ready ? 'Ready to explore' : 'Start with data setup'}</p><span className="project-open">Open analysis <Icon name="arrow" size={14}/></span></button><div className="project-card-bottom"><span>Updated {new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(project.updatedAt))}</span><div className="project-card-actions"><button className="project-rename" aria-label={`Rename ${project.title}`} onClick={() => setRenaming(project)}><Icon name="edit" size={15}/>Rename</button><button className="project-delete" aria-label={`Delete ${project.title}`} onClick={() => setDeleting(project)}><Icon name="trash" size={15}/>Delete</button></div></div></article>)}{!visible.length && <p className="no-project-match">No analyses match “{search}”.</p>}</div> : <section className="project-empty"><span className="empty-icon"><Icon name="grid" size={31}/></span><h2>Start your first analysis</h2><p>Keep related CSVs together. Upload your files, join or stack your data, and build an analysis around it.</p><button className="primary" onClick={() => setCreating(true)}><Icon name="plus" size={16}/>Create an analysis</button><div className="project-flow"><span>Upload files</span><Icon name="chevron" size={13}/><span>Prepare data</span><Icon name="chevron" size={13}/><span>Explore insights</span></div></section>}
    {renaming && <RenameDialog project={renaming} onClose={() => setRenaming(null)} onRename={async title => { await onRename(renaming.id, title); setRenaming(null); }}/>}
    {deleting && <DeleteDialog project={deleting} onClose={() => setDeleting(null)} onDelete={async () => { await onDelete(deleting.id); setDeleting(null); }}/>}
    {creating && <CreateDialog onClose={() => setCreating(false)} onCreate={async title => { await onCreate(title); setCreating(false); }}/>} 
  </>;
}
function RenameDialog({ project, onClose, onRename }: { project: ProjectSummary; onClose: () => void; onRename: (title: string) => Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null), submitting = useRef(false);
  const [title, setTitle] = useState(project.title), [busy, setBusy] = useState(false), [error, setError] = useState('');
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="create-dialog" aria-labelledby="rename-analysis-title" onCancel={event => { if (submitting.current) event.preventDefault(); else onClose(); }}>
    <form onSubmit={async event => {
      event.preventDefault();
      const name = title.trim();
      if (submitting.current || !name || name === project.title) return;
      submitting.current = true; setBusy(true); setError('');
      try { await onRename(name); } catch (error) { setError((error as Error).message); setBusy(false); submitting.current = false; }
    }}>
      <div className="dialog-heading"><span className="icon-tile purple"><Icon name="edit" size={20}/></span><button type="button" className="icon-button" aria-label="Close rename analysis" disabled={busy} onClick={onClose}><Icon name="close" size={18}/></button></div>
      <h2 id="rename-analysis-title">Rename analysis</h2>
      <label htmlFor="rename-analysis-name">Analysis name</label>
      <input id="rename-analysis-name" autoFocus required maxLength={80} disabled={busy} value={title} onChange={event => setTitle(event.target.value)} onFocus={event => event.target.select()}/>
      {error && <p role="alert" className="dialog-error">{error}</p>}
      <div className="dialog-actions"><button type="button" className="secondary" disabled={busy} onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !title.trim() || title.trim() === project.title}>{busy ? 'Saving…' : 'Save name'}</button></div>
    </form>
  </dialog>;
}

function CreateDialog({ onClose, onCreate }: { onClose: () => void; onCreate: (title: string) => Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [title, setTitle] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('');
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="create-dialog" onCancel={onClose}><form onSubmit={async e => { e.preventDefault(); setBusy(true); setError(''); try { await onCreate(title.trim()); } catch (e) { setError((e as Error).message); setBusy(false); } }}><div className="dialog-heading"><span className="icon-tile purple"><Icon name="plus" size={20}/></span><button type="button" className="icon-button" aria-label="Close new analysis" onClick={onClose}><Icon name="close" size={18}/></button></div><h2>New analysis</h2><p>Give this set of data a name. You’ll add its CSV files next.</p><label htmlFor="analysis-name">Analysis name</label><input id="analysis-name" autoFocus required maxLength={80} placeholder="e.g. Retail sales or Customer activity" value={title} onChange={e => setTitle(e.target.value)}/>{error && <p role="alert" className="dialog-error">{error}</p>}<div className="dialog-actions"><button type="button" className="secondary" disabled={busy} onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !title.trim()}>{busy ? 'Creating…' : 'Create analysis'}<Icon name="arrow" size={15}/></button></div></form></dialog>;
}

function DeleteDialog({ project, onClose, onDelete }: { project: ProjectSummary; onClose: () => void; onDelete: () => Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="create-dialog" aria-labelledby="delete-analysis-title" aria-describedby="delete-analysis-description" onCancel={event => { if (busy) event.preventDefault(); else onClose(); }}>
    <form onSubmit={async event => {
      event.preventDefault(); setBusy(true); setError('');
      try { await onDelete(); } catch (error) { setError((error as Error).message); setBusy(false); }
    }}>
      <div className="dialog-heading"><span className="icon-tile delete-tile"><Icon name="trash" size={20}/></span><button type="button" className="icon-button" aria-label="Close delete analysis" disabled={busy} onClick={onClose}><Icon name="close" size={18}/></button></div>
      <h2 id="delete-analysis-title">Delete analysis?</h2>
      <p id="delete-analysis-description">“{project.title}” and all its uploaded files, findings and dashboard cards will be permanently deleted. This cannot be undone.</p>
      {error && <p role="alert" className="dialog-error">{error}</p>}
      <div className="dialog-actions"><button type="button" className="secondary" autoFocus disabled={busy} onClick={onClose}>Cancel</button><button className="danger" disabled={busy}>{busy ? 'Deleting…' : 'Delete analysis'}</button></div>
    </form>
  </dialog>;
}
