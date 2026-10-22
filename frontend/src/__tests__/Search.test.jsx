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
