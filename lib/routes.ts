export const analysisViews = ['setup', 'data', 'analysis', 'dashboard'] as const;
export type AnalysisView = typeof analysisViews[number];
export function isAnalysisView(value: string): value is AnalysisView {
  return analysisViews.some(view => view === value);
}
export function analysisPath(id: string, view: AnalysisView = 'setup', tableId?: string) {
  const path = `/analyses/${encodeURIComponent(id)}/${view}`;
  return tableId ? `${path}?table=${encodeURIComponent(tableId)}` : path;
}
