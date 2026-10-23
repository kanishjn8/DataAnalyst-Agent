import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
function files(directory: string): string[] { return readdirSync(directory, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? files(path.join(directory, entry.name)) : /\.(ts|tsx)$/.test(entry.name) ? [path.join(directory, entry.name)] : []); }
describe('frontend separation', () => {
  it('does not contain CSV, SQL, database or model execution logic', () => {
    for (const file of [...files('components'), ...files('lib')]) {
      const source = readFileSync(file, 'utf8');
      expect(source, file).not.toMatch(/(?:from|import\s*\()\s*['"][^'"]*(?:backend\/|supabase\/functions|papaparse|@google\/genai|sqlite)/);
      expect(source, file).not.toMatch(/\b(?:indexedDB|parseCsv|prepareData|runAnalysis)\b/);
    }
  });
});
