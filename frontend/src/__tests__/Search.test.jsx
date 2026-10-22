import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/preact';
import { Search, SAVED_SEARCH_KEY, clearSavedSearch } from '../Search.jsx';
import { MSG } from '../messages.js';

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
  fireEvent.input(screen.getByLabelText('Movie or series title'), { target: { value: q } });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
}

async function tick(ms) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  sessionStorage.clear(); // every search now writes its state: tests must not leak into each other
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('Search flow', () => {
  it('posts exactly {q, type: film} by default and offers the Film and TV Series toggle', async () => {
    const calls = stubSearch({ snapshots: [jsonResponse({ search_id: 's1', done: true, timed_out: false, results: [] })] });
    render(<Search />);
    expect(screen.getByLabelText('Movie').checked).toBe(true);
    expect(screen.getByLabelText('TV Series').checked).toBe(false);
    submitSearch('Sintel');
    await tick(0);
    const post = calls.find((c) => c.method === 'POST');
    expect(post.path).toBe('/api/search');
    expect(JSON.parse(post.body)).toEqual({ q: 'Sintel', type: 'film' });
  });

  it('posts type serie when TV Series is chosen', async () => {
    const calls = stubSearch({ snapshots: [jsonResponse({ search_id: 's1', done: true, timed_out: false, results: [] })] });
    render(<Search />);
    fireEvent.click(screen.getByLabelText('TV Series'));
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
  it('shows "Searching…" with the rows received while the search runs, and hides it when done', async () => {
    const stub = {
      snapshots: [snapshot([row('a', 'Alpha', 50)], { done: false }), snapshot([row('a', 'Alpha', 50)])],
    };
    stubSearch(stub);
    const { container } = render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    expect(screen.getByText('Searching…')).toBeTruthy();
    await tick(700);
    expect(screen.getByText('Searching…')).toBeTruthy();
    expect(container.querySelector('.spinner')).toBeTruthy();
    expect(container.querySelectorAll('li.result').length).toBe(1);
    await tick(700);
    expect(screen.queryByText('Searching…')).toBeNull();
    expect(container.querySelectorAll('li.result').length).toBe(1);
  });

  it('says there is nothing found when done with zero rows', async () => {
    await runSearch({ snapshots: [snapshot([])] });
    expect(screen.getByText('No results. Try different words.')).toBeTruthy();
    expect(screen.queryByText('The search took too long. Try again.')).toBeNull();
  });

  it('says the search took too long when it timed out with zero rows', async () => {
    await runSearch({ snapshots: [snapshot([], { timed_out: true })] });
    expect(screen.getByText('The search took too long. Try again.')).toBeTruthy();
    expect(screen.queryByText('No results. Try different words.')).toBeNull();
  });

  it('shows the rows with no message and no indicator when it timed out with some results', async () => {
    const { container } = await runSearch({
      snapshots: [snapshot([row('a', 'Alpha', 50)], { timed_out: true })],
    });
    expect(container.querySelectorAll('li.result').length).toBe(1);
    expect(screen.queryByText('The search took too long. Try again.')).toBeNull();
    expect(screen.queryByText('No results. Try different words.')).toBeNull();
    expect(screen.queryByText('Searching…')).toBeNull();
  });

  it('shows no empty message before any search', () => {
    stubSearch({ snapshots: [snapshot([])] });
    render(<Search />);
    expect(screen.queryByText('No results. Try different words.')).toBeNull();
  });

  it('shows the starting message on a 503 and nothing technical', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'not_ready' }, 503)));
    const { container } = render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    expect(screen.getByText('The service is starting up. Try again in a moment.')).toBeTruthy();
    expect(screen.queryByText('Searching…')).toBeNull();
    expect(container.textContent).not.toMatch(FOREIGN);
  });

  it('asks for at least 2 characters on a 422 and nothing technical', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'validation_error' }, 422)));
    const { container } = render(<Search />);
    submitSearch('a');
    await tick(0);
    expect(screen.getByText('Type at least 2 characters.')).toBeTruthy();
    expect(container.textContent).not.toMatch(FOREIGN);
  });

  it('shows the throttle message on a 429 and nothing technical (D-39)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'too_many_requests' }, 429)));
    const { container } = render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    expect(screen.getByRole('alert').textContent).toBe(MSG.throttled);
    expect(container.textContent).not.toContain('429');
    expect(container.textContent).not.toContain('too_many_requests');
    expect(container.textContent).not.toMatch(/retry-after|\b\d+\s*s\b/i);
    expect(screen.queryByText('Searching…')).toBeNull();
    // The form stays editable and a later search works.
    expect(screen.getByLabelText('Movie or series title').disabled).toBe(false);
    stubSearch({ snapshots: [snapshot([], { done: false })] });
    submitSearch('Sintel');
    await tick(0);
    expect(screen.queryByText(MSG.throttled)).toBeNull();
    expect(screen.getByText('Searching…')).toBeTruthy();
  });

  it('shows the unreachable message on a network error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))));
    const { container } = render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    expect(
      screen.getByText('Can’t reach the server. Check that the computer is turned on.'),
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
    expect(container.querySelector('.form-error').textContent).toBe('Something went wrong. Try again.');
    expect(container.textContent).not.toMatch(FOREIGN);
    expect(screen.queryByText('Searching…')).toBeNull();
  });

  it('clears the previous message when a new search starts', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'not_ready' }, 503)));
    render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    expect(screen.getByText('The service is starting up. Try again in a moment.')).toBeTruthy();
    stubSearch({ snapshots: [snapshot([], { done: false })] });
    submitSearch('Sintel');
    await tick(0);
    expect(screen.queryByText('The service is starting up. Try again in a moment.')).toBeNull();
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

// ---- Download rows (01-13): Download, row states, polling -------------------------------
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
  it('posts exactly {result_id, type} and shows "Started ✓" for a started job', async () => {
    const { container, calls } = await openRows({
      download: () => jsonResponse({ status: 'started', job_id: JOB }),
    });
    await tap(container, 'Alpha');
    const posts = downloadPosts(calls);
    expect(posts.length).toBe(1);
    expect(JSON.parse(posts[0].body)).toEqual({ result_id: 'a', type: 'film' });
    expect(rowOf(container, 'Alpha').textContent).toContain('Started ✓');
  });

  it('sends the type of the search that produced the row, not the current toggle', async () => {
    const calls = stubPortal({
      snapshots: [snapshot([row('a', 'Alpha', 50)])],
      download: () => jsonResponse({ status: 'started', job_id: JOB }),
    });
    const { container } = render(<Search />);
    fireEvent.click(screen.getByLabelText('TV Series'));
    submitSearch('Pioneer One');
    await tick(0);
    await tick(700);
    fireEvent.click(screen.getByLabelText('Movie')); // toggled after the results arrived
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
    expect(li.textContent).toContain('Started ✓');
    expect(li.querySelector('.spinner')).toBeNull();
  });

  it('stays on the list after a start and keeps the other rows tappable', async () => {
    const { container } = await openRows({
      download: () => jsonResponse({ status: 'started', job_id: JOB }),
    });
    await tap(container, 'Alpha');
    expect(container.querySelectorAll('li.result').length).toBe(2);
    expect(rowOf(container, 'Beta').querySelector('button').disabled).toBe(false);
    expect(rowOf(container, 'Beta').textContent).not.toContain('Started');
  });
});

const OUTCOMES = [
  ['rejected', () => jsonResponse({ status: 'rejected', job_id: JOB }), 'This file doesn’t contain a video. Try another result.'],
  ['unsupported', () => jsonResponse({ status: 'unsupported', job_id: JOB }), 'This video format isn’t supported. Try another result.'],
  ['unavailable', () => jsonResponse({ status: 'unavailable', job_id: JOB }), 'Not available. Try another result.'],
  ['duplicate', () => jsonResponse({ status: 'duplicate', job_id: JOB }), 'Already added'],
  ['failed', () => jsonResponse({ status: 'failed', job_id: JOB }), 'Download failed. Try again.'],
  ['preparing', () => jsonResponse({ status: 'preparing', job_id: JOB }), 'Preparing'],
  ['410', () => jsonResponse({ detail: 'search_expired' }, 410), 'Search expired. Search again.'],
  ['503', () => jsonResponse({ detail: 'not_ready' }, 503), 'The service is starting up. Try again in a moment.'],
  ['422', () => jsonResponse({ detail: 'type_mismatch' }, 422), 'Download failed. Try again.'],
  ['network', () => { throw new TypeError('Failed to fetch'); }, 'Can’t reach the server. Check that the computer is turned on.'],
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

  it.each(OUTCOMES)('never_success: %s never renders "Started"', async (_n, download) => {
    const { container } = await openRows({ download });
    await tap(container, 'Alpha');
    expect(container.textContent).not.toContain('Started');
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
    expect(rowOf(container, 'Alpha').textContent).toContain('Preparing');
    await tick(2000);
    expect(gets()).toBe(2);
    await tick(2000);
    expect(gets()).toBe(3);
    expect(rowOf(container, 'Alpha').textContent).toContain('Started ✓');
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
      'This file doesn’t contain a video. Try another result.',
    );
    expect(container.textContent).not.toContain('Started');
  });

  it('shows the format message when the job ends unsupported', async () => {
    const { container } = await openRows({
      download: () => jsonResponse({ status: 'preparing', job_id: JOB }),
      jobs: () => jsonResponse({ status: 'unsupported', job_id: JOB }),
    });
    await tap(container, 'Alpha');
    await tick(2000);
    const li = rowOf(container, 'Alpha');
    expect(li.textContent).toContain('This video format isn’t supported. Try another result.');
    expect(li.textContent).not.toContain('This file doesn’t contain a video.');
    expect(container.textContent).not.toContain('Started');
  });

  it('gives up after 330 s, stops asking, and lets the row be tapped again', async () => {
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
    const li = rowOf(container, 'Alpha');
    expect(li.textContent).not.toContain('Preparing');
    expect(li.textContent).toContain('We lost track of this download. Tap Download to check it again.');
    expect(li.querySelector('button').disabled).toBe(false);
    await tick(20000);
    expect(gets()).toBe(after);
  });

  it('a job the backend no longer knows (404) leaves a retryable row, not a spinner (WR-05)', async () => {
    let posts = 0;
    const { container, calls } = await openRows({
      download: () => {
        posts += 1;
        return posts === 1
          ? jsonResponse({ status: 'preparing', job_id: JOB })
          : jsonResponse({ status: 'started', job_id: JOB });
      },
      jobs: () => jsonResponse({ detail: 'job_not_found' }, 404),
    });
    await tap(container, 'Alpha');
    await tick(2000);

    const li = rowOf(container, 'Alpha');
    expect(li.textContent).not.toContain('Preparing');
    expect(li.textContent).toContain('We lost track of this download');
    expect(li.textContent).not.toMatch(FOREIGN);
    expect(li.querySelector('button').disabled).toBe(false);
    const gets = calls.filter((c) => c.path === `/api/download/${JOB}`).length;
    await tick(10000);
    expect(calls.filter((c) => c.path === `/api/download/${JOB}`).length).toBe(gets);

    await tap(container, 'Alpha');
    expect(downloadPosts(calls).length).toBe(2);
    expect(rowOf(container, 'Alpha').textContent).toContain('Started ✓');
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

  it('keeps "Preparing" and keeps polling through a network blip', async () => {
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
    expect(rowOf(container, 'Alpha').textContent).toContain('Preparing');
    await tick(2000);
    expect(rowOf(container, 'Alpha').textContent).toContain('Started ✓');
  });
});

describe('Row state keyed by result_id (PUI-02)', () => {
  it.each([
    ['started', 'Started ✓'],
    ['preparing', 'Preparing'],
    ['duplicate', 'Already added'],
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
    expect(rowOf(container, 'Alpha').textContent).toContain('Started ✓');
    expect(rowOf(container, 'Beta').textContent).toContain('This file doesn’t contain a video.');
    expect(rowOf(container, 'Gamma').textContent).toContain('Already added');
    expect(rowOf(container, 'Beta').textContent).not.toContain('Started');
    expect(rowOf(container, 'Gamma').textContent).not.toContain('Started');
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
    expect(items[0].textContent).not.toContain('Started');
    expect(items[1].textContent).toContain('Alpha');
    expect(items[1].textContent).toContain('Started ✓');
    expect(downloadPosts(calls).length).toBe(1);
  });
});

// ---- Page reload (01-15, G-01-3 c): the search survives an unmount + new mount -----------
const SID = 'b'.repeat(16);
const SID2 = '9'.repeat(16);
const RA = 'c'.repeat(16);
const RB = 'd'.repeat(16);
const RE = 'e'.repeat(16);

function reloadSnapshot(sid, results, { done = true, timed_out = false } = {}) {
  return jsonResponse({ search_id: sid, done, timed_out, results });
}

// Like stubPortal, but with 16-hex search ids and one answer list per search id.
function stubReload({
  starts = [SID],
  searches,
  download = () => jsonResponse({ status: 'preparing', job_id: JOB }),
  jobs = () => jsonResponse({ status: 'preparing', job_id: JOB }),
}) {
  const calls = [];
  const served = {};
  let started = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path, init = {}) => {
      calls.push({ path, method: init.method ?? 'GET', body: init.body });
      if (path === '/api/search') return jsonResponse({ search_id: starts[Math.min(started++, starts.length - 1)] });
      const hit = path.match(/^\/api\/search\/(.+)$/);
      if (hit) {
        const list = searches[hit[1]];
        if (!list) return jsonResponse({ detail: 'search_not_found' }, 404);
        const i = served[hit[1]] ?? 0;
        served[hit[1]] = i + 1;
        return list[Math.min(i, list.length - 1)];
      }
      if (path === '/api/download') return download(JSON.parse(init.body));
      if (path.startsWith('/api/download/')) return jobs(path.split('/').pop());
      throw new Error(`unexpected ${path}`);
    }),
  );
  return calls;
}

// A reload is an unmount followed by a fresh mount of the same screen.
async function reload() {
  cleanup();
  const view = render(<Search />);
  await tick(0);
  return view;
}

const jobGets = (calls) => calls.filter((c) => c.path === `/api/download/${JOB}`).length;

describe('Survives a page reload (G-01-3)', () => {
  async function preparingRow() {
    const calls = stubReload({
      searches: { [SID]: [reloadSnapshot(SID, [row(RA, 'Alpha', 50), row(RB, 'Beta', 40)])] },
    });
    const view = render(<Search />);
    fireEvent.click(screen.getByLabelText('Movie'));
    submitSearch('Sintel');
    await tick(0);
    await tick(700);
    await tap(view.container, 'Alpha');
    expect(rowOf(view.container, 'Alpha').textContent).toContain('Preparing');
    return calls;
  }

  it('brings back the rows, the query, the Movie choice and the Preparing row', async () => {
    await preparingRow();
    const { container } = await reload();
    expect(screen.getByLabelText('Movie or series title').value).toBe('Sintel');
    expect(screen.getByLabelText('Movie').checked).toBe(true);
    expect(container.querySelectorAll('li.result').length).toBe(2);
    expect(rowOf(container, 'Alpha').textContent).toContain('Preparing');
    expect(rowOf(container, 'Beta').textContent).not.toContain('Preparing');
  });

  it('brings back an unsupported row with the format message and a disabled button', async () => {
    const calls = stubReload({
      searches: { [SID]: [reloadSnapshot(SID, [row(RA, 'Alpha', 50)])] },
      download: () => jsonResponse({ status: 'unsupported', job_id: JOB }),
    });
    const first = render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    await tick(700);
    await tap(first.container, 'Alpha');
    expect(rowOf(first.container, 'Alpha').textContent).toContain('This video format isn’t supported. Try another result.');
    const { container } = await reload();
    const li = rowOf(container, 'Alpha');
    expect(li.textContent).toContain('This video format isn’t supported. Try another result.');
    expect(li.querySelector('button').disabled).toBe(true);
    expect(container.textContent).not.toContain('Started');
    await tick(5000);
    expect(downloadPosts(calls).length).toBe(1);
    expect(jobGets(calls)).toBe(0);
  });

  it('restores a TV Series search as TV Series and keeps posting that type', async () => {
    const calls = stubReload({
      searches: { [SID]: [reloadSnapshot(SID, [row(RA, 'Alpha', 50)])] },
      download: () => jsonResponse({ status: 'started', job_id: JOB }),
    });
    render(<Search />);
    fireEvent.click(screen.getByLabelText('TV Series'));
    submitSearch('Pioneer One');
    await tick(0);
    await tick(700);
    const { container } = await reload();
    expect(screen.getByLabelText('TV Series').checked).toBe(true);
    await tap(container, 'Alpha');
    expect(JSON.parse(downloadPosts(calls)[0].body).type).toBe('serie');
  });

  it('resumes polling the job 2 s after the new mount and ends on Started, with no second POST', async () => {
    const calls = await preparingRow();
    const { container } = await reload();
    const before = jobGets(calls);
    await tick(1900);
    expect(jobGets(calls)).toBe(before);
    await tick(100);
    expect(jobGets(calls)).toBe(before + 1);
    expect(downloadPosts(calls).length).toBe(1);
    expect(rowOf(container, 'Alpha').textContent).toContain('Preparing');
  });

  it('the resumed row ends on the final state of the job', async () => {
    const calls = stubReload({
      searches: { [SID]: [reloadSnapshot(SID, [row(RA, 'Alpha', 50)])] },
      jobs: () => jsonResponse({ status: 'started', job_id: JOB }),
    });
    const first = render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    await tick(700);
    await tap(first.container, 'Alpha');
    expect(rowOf(first.container, 'Alpha').textContent).toContain('Preparing');
    const { container } = await reload();
    await tick(2000);
    expect(rowOf(container, 'Alpha').textContent).toContain('Started ✓');
    expect(downloadPosts(calls).length).toBe(1);
  });

  it('a new search after a restore replaces the saved search', async () => {
    const calls = stubReload({
      starts: [SID, SID2],
      searches: {
        [SID]: [reloadSnapshot(SID, [row(RA, 'Alpha', 50)])],
        [SID2]: [reloadSnapshot(SID2, [row(RE, 'Epsilon', 70)])],
      },
    });
    const first = render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    await tick(700);
    await tap(first.container, 'Alpha');
    const second = await reload();
    fireEvent.input(screen.getByLabelText('Movie or series title'), { target: { value: 'Tears' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await tick(0);
    await tick(700);
    expect(second.container.textContent).toContain('Epsilon');
    const third = await reload();
    expect(screen.getByLabelText('Movie or series title').value).toBe('Tears');
    expect(third.container.textContent).toContain('Epsilon');
    expect(third.container.textContent).not.toContain('Alpha');
    await tick(10000);
    expect(jobGets(calls)).toBe(0);
  });

  it('writes nothing to web storage before the first search', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    stubReload({ searches: {} });
    render(<Search />);
    await tick(5000);
    expect(setItem).not.toHaveBeenCalled();
    setItem.mockRestore();
  });

  // ---- Restore edge cases (Task 2): what a saved record may and may not bring back ----------
  const LOST = 'We lost track of this download. Tap Download to check it again.';

  function seed(over = {}) {
    sessionStorage.setItem(
      SAVED_SEARCH_KEY,
      JSON.stringify({
        v: 1,
        type: 'film',
        q: 'Sintel',
        search_id: SID,
        done: true,
        outcome: null,
        rows: [row(RA, 'Alpha', 50), row(RB, 'Beta', 40)],
        jobs: {},
        ...over,
      }),
    );
  }

  async function mountSeeded(stub = {}) {
    const calls = stubReload({ searches: { [SID]: [reloadSnapshot(SID, [row(RA, 'Alpha', 50)])] }, ...stub });
    const view = render(<Search />);
    await tick(0);
    return { ...view, calls };
  }

  it('a pending row (POST in flight at reload) comes back as lost and retryable, with no request', async () => {
    seed({ jobs: { [RA]: { state: 'pending' } } });
    const { container, calls } = await mountSeeded();
    const li = rowOf(container, 'Alpha');
    expect(li.textContent).toContain(LOST);
    expect(li.querySelector('button').disabled).toBe(false);
    await tick(10000);
    expect(calls.length).toBe(0);
  });

  it('a preparing row whose job is 331 s old comes back as lost and is never polled', async () => {
    seed({ jobs: { [RA]: { state: 'preparing', jobId: JOB, startedAt: Date.now() - 331000 } } });
    const { container, calls } = await mountSeeded();
    expect(rowOf(container, 'Alpha').textContent).toContain(LOST);
    expect(rowOf(container, 'Alpha').textContent).not.toContain('Preparing');
    await tick(20000);
    expect(calls.length).toBe(0);
  });

  it('a 10 s old preparing job is polled and gives up at the original 330 s mark', async () => {
    seed({ jobs: { [RA]: { state: 'preparing', jobId: JOB, startedAt: Date.now() - 10000 } } });
    const { container, calls } = await mountSeeded();
    expect(rowOf(container, 'Alpha').textContent).toContain('Preparing');
    await tick(310000);
    expect(rowOf(container, 'Alpha').textContent).toContain('Preparing');
    await tick(10000);
    expect(rowOf(container, 'Alpha').textContent).toContain(LOST);
    const after = jobGets(calls);
    await tick(20000);
    expect(jobGets(calls)).toBe(after);
  });

  it('a search saved while running resumes polling every 700 ms, shows Searching, and stops at done', async () => {
    seed({ done: false, rows: [row(RA, 'Alpha', 50)] });
    const { container, calls } = await mountSeeded({
      searches: {
        [SID]: [
          reloadSnapshot(SID, [row(RA, 'Alpha', 50), row(RB, 'Beta', 40)], { done: false }),
          reloadSnapshot(SID, [row(RB, 'Beta', 90), row(RA, 'Alpha', 50)]),
        ],
      },
    });
    expect(screen.getByText('Searching…')).toBeTruthy();
    await tick(700);
    expect(container.querySelectorAll('li.result').length).toBe(2);
    expect(screen.getByText('Searching…')).toBeTruthy();
    await tick(700);
    expect(screen.queryByText('Searching…')).toBeNull();
    const gets = () => calls.filter((c) => c.path === `/api/search/${SID}`).length;
    expect(gets()).toBe(2);
    await tick(5000);
    expect(gets()).toBe(2);
  });

  it('a search saved done with zero rows brings back the no-results message', async () => {
    seed({ rows: [], outcome: 'empty' });
    await mountSeeded();
    expect(screen.getByText('No results. Try different words.')).toBeTruthy();
  });

  it('a search saved done with zero rows brings back the timeout message', async () => {
    seed({ rows: [], outcome: 'timeout' });
    await mountSeeded();
    expect(screen.getByText('The search took too long. Try again.')).toBeTruthy();
  });

  it.each([
    ['invalid JSON', () => sessionStorage.setItem(SAVED_SEARCH_KEY, '{not json')],
    ['version 2', () => seed({ v: 2 })],
    ['type music', () => seed({ type: 'music' })],
    ['search_id ../logout', () => seed({ search_id: '../logout' })],
    ['rows not an array', () => seed({ rows: { length: 2 } })],
  ])('tampered data (%s) shows the empty start screen, sends no request and removes the key', async (_n, plant) => {
    plant();
    const { container, calls } = await mountSeeded();
    expect(container.querySelectorAll('li.result').length).toBe(0);
    expect(screen.getByLabelText('Movie or series title').value).toBe('');
    expect(container.querySelector('.form-error')).toBeNull();
    expect(container.textContent).not.toMatch(FOREIGN);
    await tick(5000);
    expect(calls.length).toBe(0);
    expect(sessionStorage.getItem(SAVED_SEARCH_KEY)).toBeNull();
  });

  it('tampered rows: a bad row is dropped, the valid rows stay', async () => {
    seed({ rows: [row('x', 'Bad id', 1), { ...row(RB, 'x', 1), name: 42 }, row(RA, 'Alpha', 50)] });
    const { container } = await mountSeeded();
    const names = [...container.querySelectorAll('li.result .result-name')].map((n) => n.textContent);
    expect(names).toEqual(['Alpha']);
  });

  it('tampered jobs: an unknown state or a path-like job id is dropped and never requested', async () => {
    seed({
      jobs: {
        [RA]: { state: 'hacked' },
        [RB]: { state: 'preparing', jobId: '../../api/logout', startedAt: Date.now() },
      },
    });
    const { container, calls } = await mountSeeded();
    for (const name of ['Alpha', 'Beta']) {
      const li = rowOf(container, name);
      expect(li.textContent).not.toContain('Preparing');
      expect(li.textContent).not.toContain(LOST);
      expect(li.querySelector('button').disabled).toBe(false);
    }
    await tick(10000);
    expect(calls.length).toBe(0);
    expect(calls.some((c) => c.path.includes('..'))).toBe(false);
  });

  it('saves exactly v, type, q, search_id, done, outcome, rows, jobs and only the seven API row fields', async () => {
    const leaky = { ...row(RA, 'Alpha', 50), url: 'http://x', hash: 'h', save_path: '/media/Film', category: 'Film' };
    stubReload({ searches: { [SID]: [reloadSnapshot(SID, [leaky])] } });
    const { container } = render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    await tick(700);
    await tap(container, 'Alpha');
    const rec = JSON.parse(sessionStorage.getItem(SAVED_SEARCH_KEY));
    expect(Object.keys(rec).sort()).toEqual(['done', 'jobs', 'outcome', 'q', 'rows', 'search_id', 'type', 'v']);
    expect(Object.keys(rec.rows[0]).sort()).toEqual(
      ['leechers', 'name', 'quality', 'result_id', 'seeders', 'size_human', 'source'],
    );
    expect(JSON.stringify(rec)).not.toMatch(/http|hash|\/media|Film"/);
  });

  it('restored rows are copied with only the seven API fields', async () => {
    seed({ rows: [{ ...row(RA, 'Alpha', 50), url: 'http://x', save_path: '/media/Film' }] });
    await mountSeeded();
    const rec = JSON.parse(sessionStorage.getItem(SAVED_SEARCH_KEY));
    expect(Object.keys(rec.rows[0]).sort()).toEqual(
      ['leechers', 'name', 'quality', 'result_id', 'seeders', 'size_human', 'source'],
    );
  });

  it('a browser whose sessionStorage throws still searches and downloads', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied');
    });
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('denied');
    });
    stubReload({
      searches: { [SID]: [reloadSnapshot(SID, [row(RA, 'Alpha', 50)])] },
      download: () => jsonResponse({ status: 'started', job_id: JOB }),
    });
    const { container } = render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    await tick(700);
    await tap(container, 'Alpha');
    expect(rowOf(container, 'Alpha').textContent).toContain('Started ✓');
    expect(container.querySelector('.form-error')).toBeNull();
    expect(container.textContent).not.toMatch(/denied|storage/i);
  });

  it('a job answer that arrives after clearSavedSearch (logout) cannot write the search back', async () => {
    stubReload({
      searches: { [SID]: [reloadSnapshot(SID, [row(RA, 'Alpha', 50)])] },
      jobs: () => jsonResponse({ status: 'started', job_id: JOB }),
    });
    const { container } = render(<Search />);
    submitSearch('Sintel');
    await tick(0);
    await tick(700);
    await tap(container, 'Alpha');
    expect(rowOf(container, 'Alpha').textContent).toContain('Preparing');
    expect(sessionStorage.getItem(SAVED_SEARCH_KEY)).not.toBeNull();
    clearSavedSearch(); // what logout calls
    expect(sessionStorage.getItem(SAVED_SEARCH_KEY)).toBeNull();
    await tick(2000); // the late answer: started
    expect(rowOf(container, 'Alpha').textContent).toContain('Started ✓');
    expect(sessionStorage.getItem(SAVED_SEARCH_KEY)).toBeNull();
  });
});
