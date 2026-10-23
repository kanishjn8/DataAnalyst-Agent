'use client';
import { useState } from 'react';
import { BarChart, Bar, LineChart, Line, PieChart, Pie, Cell, ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { AnalysisResult, Chart, Row } from '@/shared/contracts';

export function DataTable({ rows, limit = 20, totalRows = rows.length }: { rows: Row[]; limit?: number; totalRows?: number }) {
  if (!rows.length) return <p className="muted">No result rows.</p>;
  const headers = Object.keys(rows[0]);
  const display = (value: unknown) => value === null ? '—' : typeof value === 'number' ? value.toLocaleString('en-US', { maximumFractionDigits: 4 }) : String(value);
  return <><div className="table-scroll"><table><thead><tr>{headers.map(h => <th key={h}>{h}</th>)}</tr></thead>
    <tbody>{rows.slice(0, limit).map((r, i) => <tr key={i}>{headers.map(h => <td key={h}>{display(r[h])}</td>)}</tr>)}</tbody></table></div>
    {totalRows > limit && <p className="caption">Showing {Math.min(limit, rows.length)} of {totalRows} result rows. Export CSV to view the full result.</p>}</>;
}
const colors = ['#8877cc', '#79b3a4', '#e0ba7b', '#7ca4d3', '#b797c3', '#d99a8e', '#8e9db4'];
function Plot({ chart }: { chart: Chart }) {
  const axes = <><CartesianGrid strokeDasharray="3 3" stroke="#eceaf3" vertical={false}/><XAxis dataKey={chart.x} tick={{ fontSize: 11 }} interval="preserveStartEnd"/><YAxis tick={{ fontSize: 11 }} width={65}/><Tooltip/></>;
  return <div className="chart" role="img" aria-label={`${chart.type} chart; values are in the result table below`}>
    <ResponsiveContainer width="100%" height="100%" minWidth={0}>
      {chart.type === 'bar' ? <BarChart data={chart.data} margin={{ top: 10, right: 20, left: 0, bottom: 10 }}>{axes}<Bar dataKey={chart.y} fill={colors[0]} radius={[5, 5, 0, 0]} maxBarSize={48}/></BarChart> :
        chart.type === 'line' ? <LineChart data={chart.data} margin={{ top: 10, right: 20, left: 0, bottom: 10 }}>{axes}<Line dataKey={chart.y} stroke={colors[0]} strokeWidth={2} dot={false}/>{chart.data.some(d => 'forecast' in d) && <><Line dataKey="forecast" stroke={colors[2]} strokeDasharray="5 5" dot={false}/><Legend/></>}</LineChart> :
        chart.type === 'pie' ? <PieChart><Pie data={chart.data} dataKey={chart.y} nameKey={chart.x} outerRadius={85}>{chart.data.map((_, i) => <Cell key={i} fill={colors[i % colors.length]}/>)}</Pie><Tooltip/><Legend/></PieChart> :
        <ScatterChart margin={{ top: 10, right: 20, left: 0, bottom: 10 }}><CartesianGrid strokeDasharray="3 3"/><XAxis type="number" dataKey={chart.x} name="x"/><YAxis type="number" dataKey={chart.y} name="y"/><Tooltip cursor={{ strokeDasharray: '3 3' }}/><Scatter data={chart.data} fill={colors[0]}/></ScatterChart>}
    </ResponsiveContainer>
  </div>;
}
export function ResultCard({ result, onPin, onExport }: { result: AnalysisResult; onPin?: () => void; onExport?: () => void }) {
  const [copied, setCopied] = useState(false);
  const hasRows = result.rows.length > 0 || result.sections?.some(section => section.rows.length > 0);
  return <section className="result">
    {result.tableName && <p className="result-table-label">{result.tableName}</p>}
    <div className="section-heading"><h3>{result.title}</h3><div className="actions">
      {onPin && <button className="small" onClick={onPin}>Pin to dashboard</button>}
      {hasRows && onExport && <button className="small" onClick={onExport}>Export CSV</button>}
    </div></div>
    {result.answer && <p className="answer">{result.answer}</p>}
    {result.chart && <Plot chart={result.chart}/>}
    {!!result.rows.length && <DataTable rows={result.rows}/>}
    {result.sections?.map((section, index) => <ResultCard key={index} result={section}/>)}
    <details><summary>Method and assumptions</summary>
      <p className="caption">{result.sections ? `${result.sections.length} calculations` : `${result.rows.length.toLocaleString()} result rows · ${result.totalRows.toLocaleString()} input rows`}</p>
      {result.plan.explanation && <p>{result.plan.explanation}</p>}
      <ol>{result.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
    </details>
    {!!result.warnings.length && <details className="quality"><summary>Data quality and limitations ({result.warnings.length})</summary><ul>{result.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></details>}
    {result.sql && <details><summary>Generated SQL</summary><p className="caption">DuckDB SQL executed against the selected table versions.</p>
      <button className="small" onClick={async () => { try { await navigator.clipboard.writeText(result.sql!); setCopied(true); } catch { setCopied(false); } }}>{copied ? 'Copied' : 'Copy SQL'}</button><pre>{result.sql}</pre></details>}
  </section>;
}
