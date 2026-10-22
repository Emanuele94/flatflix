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

// ---- Download rows (01-13): Scarica, row states, polling -------------------------------
const JOB = 'a'.repeat(16);

function stubPortal({ snapshots, download, jobs = () => jsonResponse({ detail: 'job_not_found' }, 404) }) {
  const calls = [];
  let i = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path, init = {}) => {
      calls.push({ path, method: init.method ?? 'GET', body: init.body });
      if (path === '/api/search') return jsonResponse({ search_id: 's1' });
      if (path === '/api/search/s1') return snapshots[Math.min(i++, snapshots.length - 1)];
      if (path === '/api/download') return download(JSON.parse(init.body));
      if (path.startsWith('/api/download/')) return jobs(path.split('/').pop());
      throw new Error(`unexpected ${path}`);
    }),
  );
  return calls;
}

async function openRows(stub, rows = [row('a', 'Alpha', 50), row('b', 'Beta', 40)]) {
  const calls = stubPortal({ snapshots: [snapshot(rows)], ...stub });
  const view = render(<Search />);
  submitSearch('Sintel');
  await tick(0);
  await tick(700);
  return { ...view, calls };
}

const rowOf = (container, name) =>
  [...container.querySelectorAll('li.result')].find((li) => li.textContent.includes(name));

async function tap(container, name) {
  await act(async () => {
    fireEvent.click(rowOf(container, name).querySelector('button'));
  });
  await tick(0);
}

const downloadPosts = (calls) => calls.filter((c) => c.path === '/api/download' && c.method === 'POST');

describe('Download from the result list (DOWN-01, SEC-03, D-10)', () => {
  it('posts exactly {result_id, type} and shows "Avviato ✓" for a started job', async () => {
    const { container, calls } = await openRows({
      download: () => jsonResponse({ status: 'started', job_id: JOB }),
    });
    await tap(container, 'Alpha');
    const posts = downloadPosts(calls);
    expect(posts.length).toBe(1);
    expect(JSON.parse(posts[0].body)).toEqual({ result_id: 'a', type: 'film' });
    expect(rowOf(container, 'Alpha').textContent).toContain('Avviato ✓');
  });

  it('sends the type of the search that produced the row, not the current toggle', async () => {
    const calls = stubPortal({
      snapshots: [snapshot([row('a', 'Alpha', 50)])],
      download: () => jsonResponse({ status: 'started', job_id: JOB }),
    });
    const { container } = render(<Search />);
    fireEvent.click(screen.getByLabelText('Serie TV'));
    submitSearch('Pioneer One');
    await tick(0);
    await tick(700);
    fireEvent.click(screen.getByLabelText('Film')); // toggled after the results arrived
    await tap(container, 'Alpha');
    expect(JSON.parse(downloadPosts(calls)[0].body).type).toBe('serie');
  });

  it('disables the button with a spinner while the POST is pending', async () => {
    let release;
    const { container } = await openRows({
      download: () => new Promise((resolve) => { release = resolve; }),
    });
    await tap(container, 'Alpha');
    const li = rowOf(container, 'Alpha');
    expect(li.querySelector('button').disabled).toBe(true);
    expect(li.querySelector('.spinner')).toBeTruthy();
    await act(async () => {
      release(jsonResponse({ status: 'started', job_id: JOB }));
    });
    await tick(0);
    expect(li.textContent).toContain('Avviato ✓');
    expect(li.querySelector('.spinner')).toBeNull();
  });

  it('stays on the list after a start and keeps the other rows tappable', async () => {
    const { container } = await openRows({
      download: () => jsonResponse({ status: 'started', job_id: JOB }),
    });
    await tap(container, 'Alpha');
    expect(container.querySelectorAll('li.result').length).toBe(2);
    expect(rowOf(container, 'Beta').querySelector('button').disabled).toBe(false);
    expect(rowOf(container, 'Beta').textContent).not.toContain('Avviato');
  });
});

const OUTCOMES = [
  ['rejected', () => jsonResponse({ status: 'rejected', job_id: JOB }), 'Questo file non contiene un video. Prova un altro risultato.'],
  ['unavailable', () => jsonResponse({ status: 'unavailable', job_id: JOB }), 'Non disponibile. Prova un altro risultato.'],
  ['duplicate', () => jsonResponse({ status: 'duplicate', job_id: JOB }), 'Già presente'],
  ['failed', () => jsonResponse({ status: 'failed', job_id: JOB }), 'Download non riuscito. Riprova.'],
  ['preparing', () => jsonResponse({ status: 'preparing', job_id: JOB }), 'In preparazione'],
  ['410', () => jsonResponse({ detail: 'search_expired' }, 410), 'Ricerca scaduta, cerca di nuovo.'],
  ['503', () => jsonResponse({ detail: 'not_ready' }, 503), 'Il servizio si sta avviando. Riprova tra poco.'],
  ['422', () => jsonResponse({ detail: 'type_mismatch' }, 422), 'Download non riuscito. Riprova.'],
  ['network', () => { throw new TypeError('Failed to fetch'); }, 'Server non raggiungibile. Controlla che il computer sia acceso.'],
];

describe('Download outcomes on the row (D-11, D-13)', () => {
  it.each(OUTCOMES)('%s shows its plain Italian message on the row and nothing technical', async (_n, download, text) => {
    const { container } = await openRows({ download });
    await tap(container, 'Alpha');
    const li = rowOf(container, 'Alpha');
    expect(li.textContent).toContain(text);
    expect(li.textContent).not.toMatch(FOREIGN);
    expect(container.querySelectorAll('li.result').length).toBe(2);
  });

  it.each(OUTCOMES)('never_success: %s never renders "Avviato"', async (_n, download) => {
    const { container } = await openRows({ download });
    await tap(container, 'Alpha');
    expect(container.textContent).not.toContain('Avviato');
    expect(container.textContent).not.toContain('✓');
  });

  it('a failed job enables the button again', async () => {
    const { container } = await openRows({
      download: () => jsonResponse({ status: 'failed', job_id: JOB }),
    });
    await tap(container, 'Alpha');
    expect(rowOf(container, 'Alpha').querySelector('button').disabled).toBe(false);
  });
});

describe('Preparing jobs poll the job (D-11)', () => {
  it('polls GET /api/download/{job_id} every 2 s until a final status', async () => {
    const answers = ['preparing', 'preparing', 'started'];
    let n = 0;
    const { container, calls } = await openRows({
      download: () => jsonResponse({ status: 'preparing', job_id: JOB }),
      jobs: () => jsonResponse({ status: answers[n++], job_id: JOB }),
    });
    await tap(container, 'Alpha');
    const gets = () => calls.filter((c) => c.path === `/api/download/${JOB}`).length;
    expect(gets()).toBe(0);
    await tick(1900);
    expect(gets()).toBe(0);
    await tick(100);
    expect(gets()).toBe(1);
    expect(rowOf(container, 'Alpha').textContent).toContain('In preparazione');
    await tick(2000);
    expect(gets()).toBe(2);
    await tick(2000);
    expect(gets()).toBe(3);
    expect(rowOf(container, 'Alpha').textContent).toContain('Avviato ✓');
    await tick(10000);
    expect(gets()).toBe(3);
  });

  it('shows the rejection when the job ends rejected', async () => {
    const { container } = await openRows({
      download: () => jsonResponse({ status: 'preparing', job_id: JOB }),
      jobs: () => jsonResponse({ status: 'rejected', job_id: JOB }),
    });
    await tap(container, 'Alpha');
    await tick(2000);
    expect(rowOf(container, 'Alpha').textContent).toContain(
      'Questo file non contiene un video. Prova un altro risultato.',
    );
    expect(container.textContent).not.toContain('Avviato');
  });

  it('gives up after 330 s and keeps "In preparazione"', async () => {
    const { container, calls } = await openRows({
      download: () => jsonResponse({ status: 'preparing', job_id: JOB }),
      jobs: () => jsonResponse({ status: 'preparing', job_id: JOB }),
    });
    await tap(container, 'Alpha');
    await tick(330000);
    const gets = () => calls.filter((c) => c.path === `/api/download/${JOB}`).length;
    const after = gets();
    expect(after).toBeGreaterThan(100);
    expect(after).toBeLessThanOrEqual(165);
    expect(rowOf(container, 'Alpha').textContent).toContain('In preparazione');
    await tick(20000);
    expect(gets()).toBe(after);
    expect(rowOf(container, 'Alpha').textContent).toContain('In preparazione');
  });

  it('stops polling when the screen unmounts', async () => {
    const { container, calls, unmount } = await openRows({
      download: () => jsonResponse({ status: 'preparing', job_id: JOB }),
      jobs: () => jsonResponse({ status: 'preparing', job_id: JOB }),
    });
    await tap(container, 'Alpha');
    await tick(2000);
    const before = calls.length;
    unmount();
    await tick(20000);
    expect(calls.length).toBe(before);
  });

  it('keeps "In preparazione" and keeps polling through a network blip', async () => {
    let n = 0;
    const { container } = await openRows({
      download: () => jsonResponse({ status: 'preparing', job_id: JOB }),
      jobs: () => {
        n += 1;
        if (n === 1) throw new TypeError('Failed to fetch');
        return jsonResponse({ status: 'started', job_id: JOB });
      },
    });
    await tap(container, 'Alpha');
    await tick(2000);
    expect(rowOf(container, 'Alpha').textContent).toContain('In preparazione');
    await tick(2000);
    expect(rowOf(container, 'Alpha').textContent).toContain('Avviato ✓');
  });
});

describe('Row state keyed by result_id (PUI-02)', () => {
  it.each([
    ['started', 'Avviato ✓'],
    ['preparing', 'In preparazione'],
    ['duplicate', 'Già presente'],
  ])('a second tap on a %s row sends no second request', async (status, text) => {
    const { container, calls } = await openRows({
      download: () => jsonResponse({ status, job_id: JOB }),
      jobs: () => jsonResponse({ status: 'preparing', job_id: JOB }),
    });
    await tap(container, 'Alpha');
    expect(rowOf(container, 'Alpha').textContent).toContain(text);
    await tap(container, 'Alpha');
    await tap(container, 'Alpha');
    expect(downloadPosts(calls).length).toBe(1);
  });

  it('two taps in the same tick send one request', async () => {
    let release;
    const { container, calls } = await openRows({
      download: () => new Promise((resolve) => { release = resolve; }),
    });
    const button = rowOf(container, 'Alpha').querySelector('button');
    await act(async () => {
      fireEvent.click(button);
      fireEvent.click(button);
    });
    expect(downloadPosts(calls).length).toBe(1);
    await act(async () => {
      release(jsonResponse({ status: 'started', job_id: JOB }));
    });
  });

  it('three rows tapped at once each end in their own state', async () => {
    const byId = {
      a: jsonResponse({ status: 'started', job_id: '1'.repeat(16) }),
      b: jsonResponse({ status: 'rejected', job_id: '2'.repeat(16) }),
      c: jsonResponse({ status: 'duplicate', job_id: '3'.repeat(16) }),
    };
    const { container, calls } = await openRows(
      { download: (body) => byId[body.result_id] },
      [row('a', 'Alpha', 50), row('b', 'Beta', 40), row('c', 'Gamma', 30)],
    );
    await act(async () => {
      for (const name of ['Alpha', 'Beta', 'Gamma']) {
        fireEvent.click(rowOf(container, name).querySelector('button'));
      }
    });
    await tick(0);
    expect(downloadPosts(calls).length).toBe(3);
    expect(rowOf(container, 'Alpha').textContent).toContain('Avviato ✓');
    expect(rowOf(container, 'Beta').textContent).toContain('Questo file non contiene un video.');
    expect(rowOf(container, 'Gamma').textContent).toContain('Già presente');
    expect(rowOf(container, 'Beta').textContent).not.toContain('Avviato');
    expect(rowOf(container, 'Gamma').textContent).not.toContain('Avviato');
  });

  it('keeps each row state when a later snapshot re-sorts the rows', async () => {
    const calls = stubPortal({
      snapshots: [
        snapshot([row('a', 'Alpha', 50), row('b', 'Beta', 40)], { done: false }),
        snapshot([row('b', 'Beta', 90), row('a', 'Alpha', 50)]),
      ],
      download: () => jsonResponse({ status: 'started', job_id: JOB }),
    });
    const { container } = render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    await tick(700);
    await tap(container, 'Alpha');
    await tick(700); // re-sorted snapshot, done
    const items = container.querySelectorAll('li.result');
    expect(items[0].textContent).toContain('Beta');
    expect(items[0].textContent).not.toContain('Avviato');
    expect(items[1].textContent).toContain('Alpha');
    expect(items[1].textContent).toContain('Avviato ✓');
    expect(downloadPosts(calls).length).toBe(1);
  });
});
