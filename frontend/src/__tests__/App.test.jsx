import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/preact';
import { App } from '../App.jsx';

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('App health banner', () => {
  it('shows "Portale pronto" when the backend is ok', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ status: 'ok', qbittorrent: 'up' })));
    render(<App />);
    expect(await screen.findByText('Portale pronto')).toBeTruthy();
  });

  it('shows the starting message when the backend is degraded', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ status: 'degraded', qbittorrent: 'down' })),
    );
    render(<App />);
    expect(await screen.findByText('Servizio in avvio. Riprova tra poco.')).toBeTruthy();
  });

  it('shows the unreachable message when fetch rejects', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    render(<App />);
    expect(
      await screen.findByText('Server non raggiungibile. Controlla che il computer sia acceso.'),
    ).toBeTruthy();
  });
});
