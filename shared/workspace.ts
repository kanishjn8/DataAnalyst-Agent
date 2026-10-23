import type { AnalysisResult, Column, Row } from './contracts';
import type { TableGraph } from './preparation';
export type FileInfo = { id: string; name: string; rowCount: number; bytes: number; columns: Column[] };
export type TableInfo = { id: string; name: string; kind: 'source' | 'join' | 'stack'; rowCount: number; columns: Column[] };
export type PreparedView = { description: string; rowCount: number; columns: Column[]; rows: Row[]; warnings: string[]; notes: string[]; sql: string | null };
export type AnalysisTurn = { id: string; question: string; result: AnalysisResult; pinned: boolean; createdAt: string; cached?: boolean };
export type ProjectSummary = { id: string; title: string; createdAt: string; updatedAt: string; fileCount: number; ready: boolean };
export type Project = ProjectSummary & { revision: number; dataVersion: number; files: FileInfo[]; canvas: TableGraph; tables: TableInfo[]; question: string; analyses: AnalysisTurn[] };
export type Capabilities = { analysis: boolean };
