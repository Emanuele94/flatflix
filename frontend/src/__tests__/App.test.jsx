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

// Route fetch by path so session and health can be controlled independently.
function stubApi({ session = jsonResponse({ logged_in: true }), health } = {}) {
  const okHealth = jsonResponse({ status: 'ok', qbittorrent: 'up' });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path) => {
      const r = path === '/api/session' ? session : (health ?? okHealth);
      if (r instanceof Error) throw r;
      return r;
    }),
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('App session gate', () => {
  it('shows the login form when the session is 401', async () => {
    stubApi({ session: jsonResponse({ detail: 'not_authenticated' }, 401) });
    render(<App />);
    expect(await screen.findByRole('button', { name: 'Entra' })).toBeTruthy();
    expect(screen.getByLabelText('Nome utente')).toBeTruthy();
    expect(screen.getByLabelText('Password')).toBeTruthy();
  });

  it('shows the logged-in shell when the session is 200', async () => {
    stubApi();
    render(<App />);
    expect(await screen.findByText('Accesso effettuato.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Esci' })).toBeTruthy();
  });
});

describe('App health banner', () => {
  it('shows the starting message when the backend is degraded', async () => {
    stubApi({ health: jsonResponse({ status: 'degraded', qbittorrent: 'down' }) });
    render(<App />);
    expect(await screen.findByText('Servizio in avvio. Riprova tra poco.')).toBeTruthy();
  });

  it('shows no banner when the backend is ok', async () => {
    stubApi();
    render(<App />);
    await screen.findByText('Accesso effettuato.');
    expect(screen.queryByText('Servizio in avvio. Riprova tra poco.')).toBeNull();
  });

  it('shows the unreachable message when fetch rejects', async () => {
    const down = new TypeError('Failed to fetch');
    stubApi({ session: down, health: down });
    render(<App />);
    expect(
      await screen.findByText('Server non raggiungibile. Controlla che il computer sia acceso.'),
    ).toBeTruthy();
  });
});
