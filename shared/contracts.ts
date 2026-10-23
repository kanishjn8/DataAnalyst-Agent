// Transport types shared by the UI. All validation and calculations run in Python.
export const LIMITS = { files: 5, bytes: 15_000_000, rows: 20_000, columns: 40 };
export type Cell = string | number | null;
export type Row = Record<string, Cell>;
export type Column = { name: string; type: 'number' | 'date' | 'text'; missing: number; unique: number; mixedNumeric: boolean };
export type Plan = { explanation: string };
export type Chart = { type: 'bar' | 'line' | 'pie' | 'scatter'; x: string; y: string; data: Row[] };
export type AnalysisResult = { tableId?: string | null; tableIds?: string[]; tableName?: string; requestGroupId?: string; workspaceAnalysis?: boolean; sections?: AnalysisResult[]; title: string; answer: string; plan: Plan; rows: Row[]; chart: Chart | null; steps: string[]; warnings: string[]; sql: string | null; matchedRows: number; totalRows: number };
export type StreamEvent = { type: 'status'; message: string } | { type: 'text'; text: string } | { type: 'result'; result: AnalysisResult; requestId: string; analysisId: string; cached: boolean } | { type: 'done'; requestId: string; completed: number; failed: number } | { type: 'error'; message: string; requestId: string };
