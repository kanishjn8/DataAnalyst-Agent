'use client';

import { useEffect, useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import type { TableInfo } from '@/shared/workspace';
import type { CanvasPoint, DerivedTable, TableGraph } from '@/shared/preparation';
import { operationInputs } from '@/shared/preparation';
import { Icon } from './icons';
import { useSessionDraft } from '@/lib/session-draft';

export type ColumnPort = { tableId: string; column: string };
const WIDTH = 244, HEIGHT = 310;
export function nodePosition(graph: TableGraph, id: string, index: number): CanvasPoint {
  return graph.positions[id] ?? { x: 40 + (index % 3) * 300, y: 42 + Math.floor(index / 3) * 370 };
}
export function TableCanvas({ analysisId, graph, tables, selectedId, disabled, onChange, onSelect, onJoin, onStack, onRemove, onRename }: {
  analysisId: string; graph: TableGraph; tables: TableInfo[]; selectedId: string; disabled: boolean;
  onChange: (graph: TableGraph) => void; onSelect: (id: string) => void;
  onJoin: (left: ColumnPort, right: ColumnPort) => void;
  onStack: (leftId: string, rightId: string) => void;
  onRemove: (id: string) => void;
  onRename: (id: string) => void;
}) {
  const board = useRef<HTMLDivElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useSessionDraft(`analysis:${analysisId}:canvas-zoom`, 1);
  const scale = Number.isFinite(zoom) ? Math.max(0.25, Math.min(2, zoom)) : 1;
  const move = useRef<{ id: string; start: CanvasPoint; pointer: CanvasPoint; moved: boolean } | null>(null);
  const connect = useRef<{ port: ColumnPort; start: CanvasPoint; moved: boolean } | null>(null);
  const ignoreClick = useRef(false);
  const [link, setLink] = useState<ColumnPort | null>(null);
  const [wire, setWire] = useState<{ start: CanvasPoint; end: CanvasPoint } | null>(null);
  const [moving, setMoving] = useState('');
  const positions = new Map(tables.map((table, i) => [table.id, nodePosition(graph, table.id, i)]));
  const extent = { width: Math.max(1000, ...Array.from(positions.values()).map(p => p.x + WIDTH + 80)), height: Math.max(650, ...Array.from(positions.values()).map(p => p.y + HEIGHT + 80)) };
  function zoomTo(value: number, anchor?: CanvasPoint) {
    const element = viewport.current;
    if (!element || move.current || connect.current) return;
    const next = Math.max(0.25, Math.min(2, Math.round(value * 100) / 100));
    const point = anchor ?? { x: element.clientWidth / 2, y: element.clientHeight / 2 };
    const x = (element.scrollLeft + point.x) / scale, y = (element.scrollTop + point.y) / scale;
    setZoom(next);
    requestAnimationFrame(() => { element.scrollLeft = x * next - point.x; element.scrollTop = y * next - point.y; });
  }
  function fitTables() {
    const element = viewport.current;
    if (!element) return;
    const width = Math.max(...Array.from(positions.values()).map(p => p.x + WIDTH)) + 40;
    const height = Math.max(...Array.from(positions.values()).map(p => p.y + HEIGHT)) + 40;
    zoomTo(Math.min(element.clientWidth / width, element.clientHeight / height, 1));
    requestAnimationFrame(() => { element.scrollLeft = 0; element.scrollTop = 0; });
  }
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    function wheel(event: WheelEvent) {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      const rect = element!.getBoundingClientRect();
      zoomTo(scale * Math.exp(-event.deltaY * 0.002), { x: event.clientX - rect.left, y: event.clientY - rect.top });
    }
    element.addEventListener('wheel', wheel, { passive: false });
    return () => element.removeEventListener('wheel', wheel);
    // The handler uses the current zoom; table layout is not involved in wheel zoom.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scale]);
  function relative(event: PointerEvent): CanvasPoint {
    const rect = board.current!.getBoundingClientRect();
    return { x: (event.clientX - rect.left) / scale, y: (event.clientY - rect.top) / scale };
  }
  function place(id: string, point: CanvasPoint) {
    onChange({ ...graph, positions: { ...graph.positions, [id]: { x: Math.max(0, Math.min(6000, point.x)), y: Math.max(0, Math.min(6000, point.y)) } } });
  }
  function startMove(event: PointerEvent<HTMLButtonElement>, table: TableInfo) {
    if (disabled || event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    move.current = { id: table.id, start: positions.get(table.id)!, pointer: relative(event), moved: false };
    setMoving(table.id);
  }
  function moveNode(event: PointerEvent<HTMLButtonElement>) {
    const drag = move.current;
    if (!drag) return;
    const point = relative(event), dx = point.x - drag.pointer.x, dy = point.y - drag.pointer.y;
    if (Math.abs(dx) + Math.abs(dy) > 5) drag.moved = true;
    if (drag.moved) place(drag.id, { x: drag.start.x + dx, y: drag.start.y + dy });
  }
  function endMove(event: PointerEvent<HTMLButtonElement>) {
    const drag = move.current;
    if (!drag) return;
    move.current = null; setMoving('');
    const point = relative(event);
    const target = tables.find(table => {
      const position = positions.get(table.id)!;
      return table.id !== drag.id && point.x >= position.x && point.x <= position.x + WIDTH && point.y >= position.y && point.y <= position.y + HEIGHT;
    });
    if (drag.moved && target) { place(drag.id, drag.start); onStack(target.id, drag.id); }
  }
  function choosePort(port: ColumnPort) {
    if (ignoreClick.current) { ignoreClick.current = false; return; }
    if (!link || link.tableId === port.tableId) { setLink(port); return; }
    onJoin(link, port); setLink(null);
  }
  function startConnection(event: PointerEvent<HTMLButtonElement>, port: ColumnPort) {
    if (disabled || event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    connect.current = { port, start: relative(event), moved: false };
  }
  function dragConnection(event: PointerEvent<HTMLButtonElement>) {
    const drag = connect.current;
    if (!drag) return;
    const end = relative(event);
    if (Math.abs(end.x - drag.start.x) + Math.abs(end.y - drag.start.y) > 5) drag.moved = true;
    if (drag.moved) setWire({ start: drag.start, end });
  }
  function endConnection(event: PointerEvent<HTMLButtonElement>) {
    const drag = connect.current;
    connect.current = null; setWire(null);
    if (!drag?.moved) return;
    ignoreClick.current = true;
    const port = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>('[data-column]');
    if (port?.dataset.table && port.dataset.column && port.dataset.table !== drag.port.tableId) {
      onJoin(drag.port, { tableId: port.dataset.table, column: port.dataset.column }); setLink(null);
    }
  }
  return <>
    <div className="canvas-help"><span><Icon name="grid" size={15}/>Drag a table header to move it. Connect columns to join. Drop a table on another to stack.</span>{link && <button className="small" onClick={() => setLink(null)}>Cancel connection</button>}</div>
    <div className="canvas-zoom-controls" role="group" aria-label="Canvas zoom"><button className="small" aria-label="Zoom out" disabled={scale <= 0.25 || !!moving} onClick={() => zoomTo(scale - 0.1)}>−</button><button className="small" aria-label="Reset zoom to 100 percent" onClick={() => zoomTo(1)}>{Math.round(scale * 100)}%</button><button className="small" aria-label="Zoom in" disabled={scale >= 2 || !!moving} onClick={() => zoomTo(scale + 0.1)}>+</button><button className="small" onClick={fitTables}>Fit tables</button><span>Ctrl / ⌘ + scroll to zoom</span></div>
    {link && <p className="canvas-connection-hint" role="status">Connecting {tables.find(t => t.id === link.tableId)?.name}.{link.column} — choose a column in another table.</p>}
    <div ref={viewport} className="canvas-scroll" aria-label="Table canvas" tabIndex={0} onKeyDown={event => {
      if (event.target !== event.currentTarget) return;
      if (['+', '=', '-', '0'].includes(event.key)) { event.preventDefault(); zoomTo(event.key === '0' ? 1 : scale + (event.key === '-' ? -0.1 : 0.1)); }
    }}><div className="canvas-size" style={{ width: extent.width * scale, height: extent.height * scale }}><div ref={board} className="table-canvas" style={{ ...extent, transform: `scale(${scale})`, transformOrigin: '0 0' }}>
      <svg className="canvas-wires" width={extent.width} height={extent.height} aria-label="Table connections">
        <defs><marker id="connection-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8" fill="#9b8ac6"/></marker></defs>
        {graph.operations.flatMap(node => operationInputs(node.operation).map((id, index) => {
          const from = positions.get(id), to = positions.get(node.id);
          if (!from || !to) return null;
          const start = { x: from.x + WIDTH, y: from.y + 90 + index * 20 }, end = { x: to.x, y: to.y + 90 + index * 20 };
          const bend = Math.max(70, Math.abs(end.x - start.x) / 2);
          const label = node.operation.kind === 'stack' ? 'Stack' : `${node.operation.joinType === 'left' ? 'Left' : 'Inner'} join · ${index ? node.operation.rightKey : node.operation.leftKey}`;
          return <g key={`${node.id}-${id}`}><path d={`M${start.x},${start.y} C${start.x + bend},${start.y} ${end.x - bend},${end.y} ${end.x},${end.y}`} markerEnd="url(#connection-arrow)"/><title>{label}</title><text x={(start.x + end.x) / 2} y={(start.y + end.y) / 2 - 8} textAnchor="middle">{label.length > 28 ? label.slice(0, 26) + '…' : label}</text></g>;
        }))}
        {wire && <path className="pending-wire" d={`M${wire.start.x},${wire.start.y} L${wire.end.x},${wire.end.y}`}/>}
      </svg>
      {tables.map(table => {
        const position = positions.get(table.id)!;
        const operation: DerivedTable | undefined = graph.operations.find(node => node.id === table.id);
        return <article key={table.id} className={`canvas-table ${selectedId === table.id ? 'selected' : ''} ${moving === table.id ? 'moving' : ''} ${table.kind !== 'source' ? 'derived' : ''}`} style={{ left: position.x, top: position.y }} aria-label={`Table ${table.name}`}>
          <div className="canvas-table-header"><button className="canvas-drag-handle" disabled={disabled} aria-label={`Move ${table.name}`} onPointerDown={event => startMove(event, table)} onPointerMove={moveNode} onPointerUp={endMove} onPointerCancel={() => { move.current = null; setMoving(''); }} onKeyDown={event => {
            const offsets: Record<string, CanvasPoint> = { ArrowLeft: { x: -20, y: 0 }, ArrowRight: { x: 20, y: 0 }, ArrowUp: { x: 0, y: -20 }, ArrowDown: { x: 0, y: 20 } };
            if (offsets[event.key]) { event.preventDefault(); place(table.id, { x: position.x + offsets[event.key].x, y: position.y + offsets[event.key].y }); }
          }}><Icon name={table.kind === 'source' ? 'table' : 'database'} size={17}/><span title={table.name}>{table.name}</span><span className="drag-grip" aria-hidden="true">⠿</span></button><button className="icon-button" disabled={disabled} aria-label={`Rename ${table.name}`} title="Rename table" onClick={() => onRename(table.id)}><Icon name="edit" size={14}/></button><button className="icon-button" disabled={disabled} aria-label={`Remove ${table.name} from canvas`} onClick={() => onRemove(table.id)}><Icon name="close" size={14}/></button></div>
          <div className="canvas-table-meta"><span className={`table-kind ${table.kind}`}>{table.kind === 'source' ? 'CSV table' : table.kind === 'join' ? 'Joined table' : 'Stacked table'}</span><span>{table.rowCount.toLocaleString()} rows</span></div>
          <div className="canvas-columns">{table.columns.map(column => <button key={column.name} className={`canvas-column ${link?.tableId === table.id && link.column === column.name ? 'connecting' : ''}`} disabled={disabled} data-table={table.id} data-column={column.name} aria-label={`Connect ${table.name}.${column.name}`} onPointerDown={event => startConnection(event, { tableId: table.id, column: column.name })} onPointerMove={dragConnection} onPointerUp={endConnection} onPointerCancel={() => { connect.current = null; setWire(null); }} onClick={() => choosePort({ tableId: table.id, column: column.name })}><span className="column-type">{column.type === 'number' ? '#' : column.type === 'date' ? '◷' : 'Aa'}</span><span title={column.name}>{column.name}</span><span className="column-port"/></button>)}</div>
          <div className="canvas-table-footer"><span>{table.columns.length} columns{operation?.operation.kind === 'join' ? ` · ${operation.operation.joinType} join` : ''}</span><button disabled={disabled} onClick={() => onSelect(table.id)}>Preview<Icon name="arrow" size={12}/></button></div>
        </article>;
      })}
    </div></div></div>
  </>;
}
