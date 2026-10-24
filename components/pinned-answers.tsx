import type { AnalysisTurn } from '@/shared/workspace';
import { ResultCard } from './result-card';

export function PinnedAnswers({ findings, pendingId, disabled, onRemove, onExport }: {
  findings: AnalysisTurn[]; pendingId: string | null; disabled: boolean;
  onRemove: (id: string) => void; onExport: (id: string) => void;
}) {
  const pinned = findings.filter(finding => finding.pinned);
  return <section className="pinned-answers" aria-labelledby="pinned-answers-title">
    <div className="section-heading"><div><h2 id="pinned-answers-title">Pinned answers <span className="pinned-count">{pinned.length}</span></h2>
      <p>Answers you saved from Analysis. No dashboard generation is needed.</p></div></div>
    {pinned.length ? <div className="dashboard-cards">{pinned.map(finding => <article key={finding.id} className="pinned-answer">
      <div className="pinned-answer-heading"><p>{finding.question}</p><button className="small" disabled={disabled || pendingId === finding.id}
        aria-busy={pendingId === finding.id} onClick={() => onRemove(finding.id)}>{pendingId === finding.id ? 'Removing…' : 'Remove from dashboard'}</button></div>
      <ResultCard result={finding.result} pinned onExport={() => onExport(finding.id)}/>
    </article>)}</div> : <div className="pinned-empty workspace-panel">Use “Pin to dashboard” on an answer in Analysis to save it here.</div>}
  </section>;
}
