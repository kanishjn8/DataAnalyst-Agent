import type { Metadata } from 'next';
import './globals.css';
import { Suspense } from 'react';
import { AuthBoundary } from '@/components/auth-boundary';
import { WorkspaceProvider } from '@/components/workspace';
export const metadata: Metadata = { title: 'Data analysis', description: 'Prepare CSV datasets, connect related tables, and explore your data.' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><Suspense fallback={<p role="status">Loading workspace…</p>}><AuthBoundary><WorkspaceProvider>{children}</WorkspaceProvider></AuthBoundary></Suspense></body></html>;
}
