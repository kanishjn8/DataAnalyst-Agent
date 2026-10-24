import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { ResultCard } from '../components/result-card';
import { PinnedAnswers } from '../components/pinned-answers';
import type { AnalysisResult } from '../shared/contracts';
import type { AnalysisTurn } from '../shared/workspace';

const result: AnalysisResult = {
  title: 'Vehicle count', answer: 'There are **250** vehicles.', tableName: 'Vehicles',
  plan: { explanation: 'Count the selected rows.' }, rows: [{ count: 250 }], chart: null,
  steps: ['Count the selected rows.'], warnings: [], sql: 'SELECT COUNT(*) FROM vehicles',
  matchedRows: 250, totalRows: 250,
};
const finding: AnalysisTurn = { id: 'saved-answer', question: 'How many vehicles?', result, pinned: true, createdAt: '2026-10-24' };
const controls = { pendingId: null, disabled: false, onRemove: vi.fn(), onExport: vi.fn() };

describe('pinning answers', () => {
  it('exposes the saved toggle state and a distinct label', () => {
    const html = renderToStaticMarkup(createElement(ResultCard, { result, pinned: true, onPin: vi.fn() }));
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain('Pinned to dashboard');
    expect(html).toContain('Click to remove this answer');
    expect(html).not.toContain('>Pin to dashboard<');
  });
  it('disables the toggle and displays progress while a pin is being saved', () => {
    const html = renderToStaticMarkup(createElement(ResultCard, { result, pinPending: true, onPin: vi.fn() }));
    expect(html).toMatch(/<button[^>]*aria-busy="true"[^>]*disabled=""/);
    expect(html).toContain('Pinning…');
    expect(html).toContain('aria-pressed="false"');
  });
  it('shows saved answers with their source question independently of generated cards', () => {
    const html = renderToStaticMarkup(createElement(PinnedAnswers, {
      ...controls, findings: [finding, { ...finding, id: 'not-pinned', question: 'Unpinned question', pinned: false }],
    }));
    expect(html).toContain('Pinned answers');
    expect(html).toContain('How many vehicles?');
    expect(html).toContain('Vehicle count');
    expect(html).toContain('<strong>250</strong>');
    expect(html).toContain('Remove from dashboard');
    expect(html).not.toContain('Unpinned question');
  });
  it('shows an empty state after the last answer is unpinned', () => {
    const html = renderToStaticMarkup(createElement(PinnedAnswers, { ...controls, findings: [{ ...finding, pinned: false }] }));
    expect(html).toContain('Use “Pin to dashboard”');
    expect(html).not.toContain('How many vehicles?');
  });
});
