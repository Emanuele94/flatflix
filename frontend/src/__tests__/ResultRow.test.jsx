import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/preact';
import { ResultRow } from '../ResultRow.jsx';

afterEach(cleanup);

const base = {
  result_id: 'r1',
  name: 'Sintel.2010.1080p.BluRay.x264',
  size_human: '4.2 GB',
  seeders: 120,
  leechers: 35,
  source: 'piratebay',
  quality: '1080p',
};

function renderRow(overrides = {}) {
  return render(
    <ul>
      <ResultRow result={{ ...base, ...overrides }} />
    </ul>,
  );
}

describe('ResultRow layout (D-09)', () => {
  it('shows the full name, size and seeders in the prominent line', () => {
    const { container } = renderRow();
    expect(container.querySelector('.result-name').textContent).toBe(base.name);
    const main = container.querySelector('.result-main');
    expect(main.textContent).toContain('4.2 GB');
    expect(main.textContent).toContain('120 seed');
  });

  it('shows leechers and source small and grey', () => {
    const { container } = renderRow();
    const meta = container.querySelector('.result-meta.muted');
    expect(meta.textContent).toBe('35 in download · piratebay');
    expect(screen.getByText('35 in download · piratebay')).toBeTruthy();
  });

  it('shows a quality badge when the quality is known', () => {
    const { container } = renderRow({ quality: '1080p' });
    expect(container.querySelector('.badge').textContent).toBe('1080p');
  });

  it('shows no badge when the quality is null', () => {
    const { container } = renderRow({ quality: null });
    expect(container.querySelector('.badge')).toBeNull();
  });
});

describe('ResultRow encoding (T-01-28)', () => {
  it('renders an HTML-looking name literally and creates no img element', () => {
    const name = '<img src=x onerror=alert(1)>';
    const { container } = renderRow({ name });
    expect(container.querySelector('.result-name').textContent).toBe(name);
    expect(container.querySelector('img')).toBeNull();
  });
});
