import { redirect } from 'next/navigation';
import { analysisPath } from '@/lib/routes';

export default async function Page({ params }: { params: Promise<{ analysisId: string }> }) {
  const { analysisId } = await params;
  redirect(analysisPath(analysisId));
}
