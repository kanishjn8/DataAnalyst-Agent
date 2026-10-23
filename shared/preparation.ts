export type TableOperation =
  | { kind: 'stack'; fileIds: string[] }
  | { kind: 'join'; leftId: string; rightId: string; leftKey: string; rightKey: string; joinType: 'inner' | 'left' };

export type CanvasPoint = { x: number; y: number };
export type DerivedTable = { id: string; name: string; operation: TableOperation };
export type TableGraph = { kind: 'graph'; operations: DerivedTable[]; positions: Record<string, CanvasPoint> };
export function operationInputs(operation: TableOperation): string[] {
  return operation.kind === 'stack' ? operation.fileIds : [operation.leftId, operation.rightId];
}
