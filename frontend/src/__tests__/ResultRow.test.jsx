import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/preact';
import { ResultRow } from '../ResultRow.jsx';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

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
      <ResultRow result={{ ...base, ...overrides }} type="film" />
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

function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

describe('ResultRow tracer: Scarica (DOWN-01, SEC-03)', () => {
  it('posts exactly {result_id, type} and shows "Avviato ✓" for a started job', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ status: 'started', job_id: 'a'.repeat(16) }));
    vi.stubGlobal('fetch', fetchMock);
    const { container } = renderRow();
    fireEvent.click(screen.getByRole('button', { name: 'Scarica' }));
    await screen.findByText('Avviato ✓');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe('/api/download');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ result_id: 'r1', type: 'film' });
    expect(container.textContent).toContain('Avviato ✓');
  });
});
