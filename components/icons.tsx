import type { CSSProperties } from 'react';
type IconName = 'grid' | 'chart' | 'table' | 'upload' | 'file' | 'spark' | 'arrow' | 'plus' | 'check' | 'shield' | 'close' | 'download' | 'chevron' | 'database' | 'search' | 'trend' | 'alert' | 'message' | 'trash' | 'edit';
const paths: Record<IconName, React.ReactNode> = {
  edit: <><path d="m15 4 5 5M4 20l5-1L21 7a2 2 0 0 0-5-5L4 14Z"/></>,
  trash: <><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/></>,
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
  chart: <><path d="M4 3v17h17M8 15v-4m5 4V7m5 8V4"/></>,
  table: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 10v10M15 10v10"/></>,
  upload: <><path d="M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5"/></>,
  file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h5"/></>,
  spark: <><path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4ZM20 2v4m-2-2h4"/></>,
  arrow: <path d="M5 12h14m-6-6 6 6-6 6"/>, plus: <path d="M12 5v14M5 12h14"/>,
  check: <path d="m5 12 4 4L19 6"/>, shield: <><path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6Z"/><path d="m8 12 3 3 5-6"/></>,
  close: <path d="m6 6 12 12M6 18 18 6"/>, download: <path d="M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4"/>,
  chevron: <path d="m9 5 7 7-7 7"/>, database: <><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/></>,
  search: <><circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/></>, trend: <><path d="m3 17 6-6 4 4 8-10M15 5h6v6"/></>,
  alert: <><path d="m12 3 10 18H2Z M12 9v5m0 3v.1"/></>, message: <><path d="M4 4h16v12H8l-4 4Z M8 8h8m-8 4h5"/></>,
};
export function Icon({ name, size = 20, style }: { name: IconName; size?: number; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}>{paths[name]}</svg>;
}
