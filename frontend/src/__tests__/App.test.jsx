import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/preact';
import { api, setUnauthorizedHandler } from '../api.js';
import { App } from '../App.jsx';
import { clearDownloadsCache } from '../Downloads.jsx';
import { MSG } from '../messages.js';
import { SAVED_SEARCH_KEY } from '../Search.jsx';

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

// Route fetch by path so session and health can be controlled independently.
function stubApi({
  session = jsonResponse({ logged_in: true }),
  health,
  downloads = jsonResponse({ items: [] }),
} = {}) {
  const okHealth = jsonResponse({ status: 'ok', qbittorrent: 'up' });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path) => {
      let r;
      if (path === '/api/session') r = session;
      else if (path === '/api/downloads') r = downloads;
      else r = health ?? okHealth;
      if (r instanceof Error) throw r;
      return r;
    }),
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStorage.clear();
  clearDownloadsCache();
});

describe('App session gate', () => {
  it('shows the login form when the session is 401', async () => {
    stubApi({ session: jsonResponse({ detail: 'not_authenticated' }, 401) });
    render(<App />);
    expect(await screen.findByRole('button', { name: 'Log in' })).toBeTruthy();
    expect(screen.getByLabelText('Username')).toBeTruthy();
    expect(screen.getByLabelText('Password')).toBeTruthy();
  });

  it('shows the logged-in shell when the session is 200', async () => {
    stubApi();
    render(<App />);
    expect(await screen.findByRole('button', { name: 'Search' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Log out' })).toBeTruthy();
  });
});

describe('App tabs (D-26)', () => {
  const ITEMS = {
    items: [
      {
        id: 'a'.repeat(16),
        name: 'Sintel.2010.1080p',
        type: 'film',
        state: 'downloading',
        progress: 42,
        eta_seconds: 600,
        action: 'cancel',
      },
    ],
  };

  it('shows Search and Downloads tabs with Search selected', async () => {
    stubApi();
    render(<App />);
    await screen.findByRole('button', { name: 'Search' });
    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((t) => t.textContent)).toEqual([MSG.tabSearch, MSG.tabDownloads]);
    expect(screen.getByRole('tab', { name: MSG.tabSearch }).getAttribute('aria-selected')).toBe(
      'true',
    );
    expect(screen.getByRole('tab', { name: MSG.tabDownloads }).getAttribute('aria-selected')).toBe(
      'false',
    );
    expect(screen.getAllByRole('button', { name: 'Search' })).toHaveLength(1);
  });

  it('lists the downloads when the Downloads tab is opened', async () => {
    stubApi({ downloads: jsonResponse(ITEMS) });
    render(<App />);
    await screen.findByRole('button', { name: 'Search' });
    fireEvent.click(screen.getByRole('tab', { name: MSG.tabDownloads }));
    expect(await screen.findByText('Sintel.2010.1080p')).toBeTruthy();
    expect(screen.getByRole('tab', { name: MSG.tabDownloads }).getAttribute('aria-selected')).toBe(
      'true',
    );
  });

  it('keeps what was typed in Search when switching to Downloads and back', async () => {
    stubApi({ downloads: jsonResponse(ITEMS) });
    render(<App />);
    await screen.findByRole('button', { name: 'Search' });
    fireEvent.input(screen.getByLabelText('Movie or series title'), { target: { value: 'Sintel' } });
    fireEvent.click(screen.getByRole('tab', { name: MSG.tabDownloads }));
    await screen.findByText('Sintel.2010.1080p');
    fireEvent.click(screen.getByRole('tab', { name: MSG.tabSearch }));
    expect(screen.getByLabelText('Movie or series title').value).toBe('Sintel');
  });

  it('ArrowRight on the Search tab selects Downloads', async () => {
    stubApi({ downloads: jsonResponse(ITEMS) });
    render(<App />);
    await screen.findByRole('button', { name: 'Search' });
    fireEvent.keyDown(screen.getByRole('tab', { name: MSG.tabSearch }), { key: 'ArrowRight' });
    expect(screen.getByRole('tab', { name: MSG.tabDownloads }).getAttribute('aria-selected')).toBe(
      'true',
    );
    expect(await screen.findByText('Sintel.2010.1080p')).toBeTruthy();
  });
});

describe('App health banner', () => {
  it('shows the starting message when the backend is degraded', async () => {
    stubApi({ health: jsonResponse({ status: 'degraded', qbittorrent: 'down' }) });
    render(<App />);
    expect(await screen.findByText('Service is starting up. Try again in a moment.')).toBeTruthy();
  });

  it('shows no banner when the backend is ok', async () => {
    stubApi();
    render(<App />);
    await screen.findByRole('button', { name: 'Search' });
    expect(screen.queryByText('Service is starting up. Try again in a moment.')).toBeNull();
  });

  it('shows the unreachable message when fetch rejects', async () => {
    const down = new TypeError('Failed to fetch');
    stubApi({ session: down, health: down });
    render(<App />);
    expect(
      await screen.findByText('Can’t reach the server. Check that the computer is turned on.'),
    ).toBeTruthy();
  });
});

describe('unauthorized handler in api()', () => {
  afterEach(() => setUnauthorizedHandler(null));

  it('is called on a 401 from a path other than /api/login', async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'not_authenticated' }, 401)));
    await expect(api('/api/search')).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('is not called on a 401 from /api/login', async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'bad_credentials' }, 401)));
    await expect(api('/api/login', { method: 'POST', body: {} })).rejects.toMatchObject({
      status: 401,
    });
    expect(handler).not.toHaveBeenCalled();
  });
});

describe('App session lifecycle', () => {
  async function loginFlow(extra = () => null) {
    let loggedIn = false;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path) => {
        const custom = extra(path, loggedIn);
        if (custom) return custom;
        if (path === '/api/health') return jsonResponse({ status: 'ok', qbittorrent: 'up' });
        if (path === '/api/login') {
          loggedIn = true;
          return { ok: true, status: 204, json: async () => null };
        }
        if (path === '/api/logout') {
          loggedIn = false;
          return { ok: true, status: 204, json: async () => null };
        }
        if (path === '/api/session') {
          return loggedIn
            ? jsonResponse({ logged_in: true })
            : jsonResponse({ detail: 'not_authenticated' }, 401);
        }
        return jsonResponse({ detail: 'not_found' }, 404);
      }),
    );
    render(<App />);
    await screen.findByRole('button', { name: 'Log in' });
    fireEvent.input(screen.getByLabelText('Username'), { target: { value: 'casa' } });
    fireEvent.input(screen.getByLabelText('Password'), { target: { value: 'giusta' } });
    fireEvent.click(screen.getByRole('button', { name: 'Log in' }));
    await screen.findByRole('button', { name: 'Search' });
  }

  it('Log out posts /api/logout and returns to the login screen', async () => {
    await loginFlow();
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }));
    expect(await screen.findByRole('button', { name: 'Log in' })).toBeTruthy();
    const calls = fetch.mock.calls.filter(([p]) => p === '/api/logout');
    expect(calls).toHaveLength(1);
    expect(calls[0][1].method).toBe('POST');
  });

  it('a later 401 from any call returns to login with no error text', async () => {
    await loginFlow();
    // Simulate a later API call (e.g. a search) failing with 401.
    fetch.mockImplementationOnce(async () => jsonResponse({ detail: 'not_authenticated' }, 401));
    await expect(api('/api/search?q=x')).rejects.toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Log in' })).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/Wrong|Too many|reach the server|401/);
  });

  it('never writes to web storage during login and logout', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    await loginFlow();
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }));
    await screen.findByRole('button', { name: 'Log in' });
    await waitFor(() => expect(setItem).not.toHaveBeenCalled());
    setItem.mockRestore();
  });

  describe('saved search (G-01-3)', () => {
    const SID = 'b'.repeat(16);
    const RID = 'c'.repeat(16);

    function seedSearch() {
      sessionStorage.setItem(
        SAVED_SEARCH_KEY,
        JSON.stringify({
          v: 1,
          type: 'film',
          q: 'Sintel',
          search_id: SID,
          done: true,
          outcome: null,
          rows: [
            {
              result_id: RID,
              name: 'Sintel 1080p',
              size_human: '4.2 GB',
              seeders: 50,
              leechers: 3,
              source: 'piratebay',
              quality: '1080p',
            },
          ],
          jobs: {},
        }),
      );
    }

    async function logIn() {
      fireEvent.input(screen.getByLabelText('Username'), { target: { value: 'casa' } });
      fireEvent.input(screen.getByLabelText('Password'), { target: { value: 'giusta' } });
      fireEvent.click(screen.getByRole('button', { name: 'Log in' }));
      await screen.findByRole('button', { name: 'Search' });
    }

    it('logging in shows the restored rows; Log out removes the saved search and the next login starts empty', async () => {
      seedSearch();
      await loginFlow();
      expect(await screen.findByText('Sintel 1080p')).toBeTruthy();
      expect(screen.getByLabelText('Movie or series title').value).toBe('Sintel');
      fireEvent.click(screen.getByRole('button', { name: 'Log out' }));
      await screen.findByRole('button', { name: 'Log in' });
      expect(sessionStorage.getItem(SAVED_SEARCH_KEY) === null).toBe(true);
      await logIn();
      expect(screen.queryByText('Sintel 1080p')).toBeNull();
      expect(screen.getByLabelText('Movie or series title').value).toBe('');
    });
  });
});
