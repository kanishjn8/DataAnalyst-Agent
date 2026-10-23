import { notFound } from 'next/navigation';
import { AnalysisRoute } from '@/components/workspace';
import { isAnalysisView } from '@/lib/routes';

export default async function Page({ params }: { params: Promise<{ analysisId: string; view: string }> }) {
  const { analysisId, view } = await params;
  if (!isAnalysisView(view) || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(analysisId)) notFound();
  return <AnalysisRoute analysisId={analysisId} view={view}/>;
}
