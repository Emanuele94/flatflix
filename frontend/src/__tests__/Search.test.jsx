import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/preact';
import { Search } from '../Search.jsx';

function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function row(id, name, seeders) {
  return {
    result_id: id,
    name,
    size_human: '4.2 GB',
    seeders,
    leechers: 3,
    source: 'piratebay',
    quality: '1080p',
  };
}

// Route by path+method so each test scripts the POST answer and the polling snapshots.
function stubSearch({ start = { search_id: 's1' }, snapshots }) {
  const calls = [];
  let i = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path, init = {}) => {
      calls.push({ path, method: init.method, body: init.body });
      if (path === '/api/search') return jsonResponse(start);
      const snap = snapshots[Math.min(i, snapshots.length - 1)];
      i += 1;
      return snap instanceof Error ? Promise.reject(snap) : snap;
    }),
  );
  return calls;
}

function submitSearch(q) {
  fireEvent.input(screen.getByLabelText('Titolo del film o della serie'), { target: { value: q } });
  fireEvent.click(screen.getByRole('button', { name: 'Cerca' }));
}

async function tick(ms) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('Search flow', () => {
  it('posts exactly {q, type: film} by default and offers the Film and Serie TV toggle', async () => {
    const calls = stubSearch({ snapshots: [jsonResponse({ search_id: 's1', done: true, timed_out: false, results: [] })] });
    render(<Search />);
    expect(screen.getByLabelText('Film').checked).toBe(true);
    expect(screen.getByLabelText('Serie TV').checked).toBe(false);
    submitSearch('Sintel');
    await tick(0);
    const post = calls.find((c) => c.method === 'POST');
    expect(post.path).toBe('/api/search');
    expect(JSON.parse(post.body)).toEqual({ q: 'Sintel', type: 'film' });
  });

  it('posts type serie when Serie TV is chosen', async () => {
    const calls = stubSearch({ snapshots: [jsonResponse({ search_id: 's1', done: true, timed_out: false, results: [] })] });
    render(<Search />);
    fireEvent.click(screen.getByLabelText('Serie TV'));
    submitSearch('Pioneer One');
    await tick(0);
    expect(JSON.parse(calls.find((c) => c.method === 'POST').body)).toEqual({
      q: 'Pioneer One',
      type: 'serie',
    });
  });

  it('renders partial then final snapshots in the order received and stops polling after done', async () => {
    const calls = stubSearch({
      snapshots: [
        jsonResponse({
          search_id: 's1',
          done: false,
          timed_out: false,
          results: [row('a', 'Alpha 1080p', 50)],
        }),
        jsonResponse({
          search_id: 's1',
          done: true,
          timed_out: false,
          results: [row('b', 'Beta 1080p', 90), row('a', 'Alpha 1080p', 50)],
        }),
      ],
    });
    const { container } = render(<Search />);
    submitSearch('x1');
    await tick(0); // POST resolves
    await tick(700); // first poll
    expect([...container.querySelectorAll('li.result .result-name')].map((n) => n.textContent)).toEqual([
      'Alpha 1080p',
    ]);
    await tick(700); // second poll, done
    expect([...container.querySelectorAll('li.result .result-name')].map((n) => n.textContent)).toEqual([
      'Beta 1080p',
      'Alpha 1080p',
    ]);
    const gets = () => calls.filter((c) => c.path !== '/api/search').length;
    expect(gets()).toBe(2);
    await tick(5000);
    expect(gets()).toBe(2);
  });

  it('a new search cancels the previous polling', async () => {
    const calls = stubSearch({
      snapshots: [jsonResponse({ search_id: 's1', done: false, timed_out: false, results: [] })],
    });
    render(<Search />);
    submitSearch('first');
    await tick(0);
    await tick(700);
    const before = calls.filter((c) => c.path === '/api/search/s1').length;
    expect(before).toBe(1);
    submitSearch('second'); // same fake search id on purpose: counts must grow once, not twice
    await tick(0);
    await tick(700);
    await tick(700);
    const total = calls.filter((c) => c.path === '/api/search/s1').length;
    // one loop only: exactly one extra poll per 700 ms tick after the restart
    expect(total).toBe(before + 2);
  });

  it('stops polling when the screen unmounts', async () => {
    const calls = stubSearch({
      snapshots: [jsonResponse({ search_id: 's1', done: false, timed_out: false, results: [] })],
    });
    const { unmount } = render(<Search />);
    submitSearch('x1');
    await tick(0);
    await tick(700);
    const before = calls.length;
    unmount();
    await tick(5000);
    expect(calls.length).toBe(before);
  });
});

const FOREIGN = /not_ready|search_unavailable|search_not_found|\b50\d\b|\b422\b|\{|undefined|Error/;

function snapshot(results, { done = true, timed_out = false } = {}) {
  return jsonResponse({ search_id: 's1', done, timed_out, results });
}

async function runSearch(stub, q = 'Sintel') {
  stubSearch(stub);
  const view = render(<Search />);
  submitSearch(q);
  await tick(0);
  await tick(700);
  return view;
}

describe('Search states (D-06, PUI-02)', () => {
  it('shows "Ricerca in corso…" with the rows received while the search runs, and hides it when done', async () => {
    const stub = {
      snapshots: [snapshot([row('a', 'Alpha', 50)], { done: false }), snapshot([row('a', 'Alpha', 50)])],
    };
    stubSearch(stub);
    const { container } = render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    expect(screen.getByText('Ricerca in corso…')).toBeTruthy();
    await tick(700);
    expect(screen.getByText('Ricerca in corso…')).toBeTruthy();
    expect(container.querySelector('.spinner')).toBeTruthy();
    expect(container.querySelectorAll('li.result').length).toBe(1);
    await tick(700);
    expect(screen.queryByText('Ricerca in corso…')).toBeNull();
    expect(container.querySelectorAll('li.result').length).toBe(1);
  });

  it('says there is nothing found when done with zero rows', async () => {
    await runSearch({ snapshots: [snapshot([])] });
    expect(screen.getByText('Nessun risultato. Prova con altre parole.')).toBeTruthy();
    expect(screen.queryByText('La ricerca ha impiegato troppo tempo. Riprova.')).toBeNull();
  });

  it('says the search took too long when it timed out with zero rows', async () => {
    await runSearch({ snapshots: [snapshot([], { timed_out: true })] });
    expect(screen.getByText('La ricerca ha impiegato troppo tempo. Riprova.')).toBeTruthy();
    expect(screen.queryByText('Nessun risultato. Prova con altre parole.')).toBeNull();
  });

  it('shows the rows with no message and no indicator when it timed out with some results', async () => {
    const { container } = await runSearch({
      snapshots: [snapshot([row('a', 'Alpha', 50)], { timed_out: true })],
    });
    expect(container.querySelectorAll('li.result').length).toBe(1);
    expect(screen.queryByText('La ricerca ha impiegato troppo tempo. Riprova.')).toBeNull();
    expect(screen.queryByText('Nessun risultato. Prova con altre parole.')).toBeNull();
    expect(screen.queryByText('Ricerca in corso…')).toBeNull();
  });

  it('shows no empty message before any search', () => {
    stubSearch({ snapshots: [snapshot([])] });
    render(<Search />);
    expect(screen.queryByText('Nessun risultato. Prova con altre parole.')).toBeNull();
  });

  it('shows the starting message on a 503 and nothing technical', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'not_ready' }, 503)));
    const { container } = render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    expect(screen.getByText('Il servizio si sta avviando. Riprova tra poco.')).toBeTruthy();
    expect(screen.queryByText('Ricerca in corso…')).toBeNull();
    expect(container.textContent).not.toMatch(FOREIGN);
  });

  it('asks for at least 2 characters on a 422 and nothing technical', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'validation_error' }, 422)));
    const { container } = render(<Search />);
    submitSearch('a');
    await tick(0);
    expect(screen.getByText('Scrivi almeno 2 caratteri.')).toBeTruthy();
    expect(container.textContent).not.toMatch(FOREIGN);
  });

  it('shows the unreachable message on a network error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))));
    const { container } = render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    expect(
      screen.getByText('Server non raggiungibile. Controlla che il computer sia acceso.'),
    ).toBeTruthy();
    expect(container.textContent).not.toMatch(FOREIGN);
  });

  it('shows a plain Italian message when a poll fails with search_not_found', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path) =>
        path === '/api/search'
          ? jsonResponse({ search_id: 's1' })
          : jsonResponse({ detail: 'search_not_found' }, 404),
      ),
    );
    const { container } = render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    await tick(700);
    expect(container.querySelector('.form-error').textContent).toBe('Qualcosa è andato storto. Riprova.');
    expect(container.textContent).not.toMatch(FOREIGN);
    expect(screen.queryByText('Ricerca in corso…')).toBeNull();
  });

  it('clears the previous message when a new search starts', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'not_ready' }, 503)));
    render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    expect(screen.getByText('Il servizio si sta avviando. Riprova tra poco.')).toBeTruthy();
    stubSearch({ snapshots: [snapshot([], { done: false })] });
    submitSearch('Sintel');
    await tick(0);
    expect(screen.queryByText('Il servizio si sta avviando. Riprova tra poco.')).toBeNull();
  });

  it('keeps each row DOM node when a snapshot re-sorts the rows (key = result_id)', async () => {
    stubSearch({
      snapshots: [
        snapshot([row('a', 'Alpha', 50), row('b', 'Beta', 40)], { done: false }),
        snapshot([row('b', 'Beta', 90), row('a', 'Alpha', 50)]),
      ],
    });
    const { container } = render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    await tick(700);
    const [alphaBefore, betaBefore] = container.querySelectorAll('li.result');
    await tick(700);
    const after = container.querySelectorAll('li.result');
    expect(after[0]).toBe(betaBefore);
    expect(after[1]).toBe(alphaBefore);
  });
});
