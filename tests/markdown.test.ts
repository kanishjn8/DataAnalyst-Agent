import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { Markdown } from '../components/markdown';

describe('model response formatting', () => {
  it('renders Markdown headings, emphasis, lists, code, and tables', () => {
    const html = renderToStaticMarkup(createElement(Markdown, { children: '## Overview\n\n**Revenue** rose.\n\n- First\n- Second\n\n`SUM(revenue)`\n\n| Region | Total |\n| --- | --- |\n| West | 42 |' }));
    expect(html).toContain('<h2>Overview</h2>');
    expect(html).toContain('<strong>Revenue</strong>');
    expect(html).toContain('<li>First</li>');
    expect(html).toContain('<code>SUM(revenue)</code>');
    expect(html).toContain('<table>');
  });
  it('does not execute model HTML, embed remote images, or allow script links', () => {
    const html = renderToStaticMarkup(createElement(Markdown, { children: '<script>alert(1)</script>\n\n<img src="https://tracking.example/pixel">\n\n![pixel](https://tracking.example/pixel)\n\n[unsafe](javascript:alert%281%29)\n\n[source](https://example.com)' }));
    expect(html).not.toContain('<script');
    expect(html).not.toContain('<img');
    expect(html).not.toContain('tracking.example');
    expect(html).not.toContain('javascript:');
    expect(html).toContain('rel="noopener noreferrer"');
  });
});
