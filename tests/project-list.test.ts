import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { ProjectList } from '../components/project-list';

describe('analysis list actions', () => {
  it('offers a clearly labelled rename action for each analysis alongside delete', () => {
    const html = renderToStaticMarkup(createElement(ProjectList, {
      projects: ['Sales', 'Customers'].map((title, index) => ({
        id: `analysis-${index}`, title, createdAt: '2026-10-25', updatedAt: '2026-10-25', fileCount: 1, ready: true,
      })),
      loading: false, onOpen: vi.fn(), onCreate: vi.fn(), onRename: vi.fn(), onDelete: vi.fn(),
    }));
    for (const title of ['Sales', 'Customers']) {
      expect(html).toContain(`aria-label="Rename ${title}"`);
      expect(html).toContain(`aria-label="Delete ${title}"`);
    }
    // Card actions must be separate from the button that opens the analysis.
    expect(html.match(/<\/button><div class="project-card-bottom">/g)).toHaveLength(2);
  });
});
