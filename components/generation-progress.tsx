import { Icon } from './icons';
import { Markdown } from './markdown';

export function GenerationProgress({ steps, text }: { steps: string[]; text: string }) {
  return <section className="generation-progress" aria-label="Generation progress">
    <h3>Progress</h3>
    <ol>{steps.map((step, index) => <li key={index} className={index === steps.length - 1 ? 'active' : ''}>
      {index === steps.length - 1 ? <span className="progress-dot" aria-hidden="true"/> : <Icon name="check" size={14}/>}
      <span>{step}</span>
    </li>)}</ol>
    <span className="sr-only" role="status">{steps.at(-1)}</span>
    {text && <div className="progress-answer"><Markdown>{text}</Markdown></div>}
  </section>;
}
