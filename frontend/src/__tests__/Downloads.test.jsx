import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/preact';
import { Downloads, clearDownloadsCache } from '../Downloads.jsx';
import { MSG } from '../messages.js';

function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function item(id, name, extra = {}) {
  return {
    id: id.repeat(16).slice(0, 16),
    name,
    type: 'film',
    state: 'downloading',
    progress: 10,
    eta_seconds: 600,
    action: 'cancel',
    ...extra,
  };
}

const LIST_A = jsonResponse({ items: [item('a', 'Sintel.2010')] });
const LIST_B = jsonResponse({ items: [item('b', 'Tears.of.Steel')] });
const EMPTY = jsonResponse({ items: [] });
const UNREACHABLE = jsonResponse({ detail: 'qbit_unreachable' }, 502);
const REFUSED = jsonResponse({ detail: 'qbit_refused' }, 502);

function deferred() {
  let resolve;
  const promise = new Promise((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

// Each fetch takes the next scripted answer; the last one repeats. An answer is a response,
// an Error (network failure) or a promise (resolved later by the test).
function stubFetch(...answers) {
  const calls = [];
  vi.stubGlobal(
    'fetch',
    vi.fn((path) => {
      calls.push(path);
      const a = answers[Math.min(calls.length - 1, answers.length - 1)];
      return a instanceof Error ? Promise.reject(a) : Promise.resolve(a);
    }),
  );
  return calls;
}

function setVisibility(state) {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
}

function changeVisibility(state) {
  setVisibility(state);
  document.dispatchEvent(new Event('visibilitychange'));
}

async function tick(ms) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  setVisibility('visible');
});

afterEach(() => {
  cleanup();
  clearDownloadsCache();
  delete document.visibilityState;
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('polling (D-31)', () => {
  it('asks once at mount and again exactly 5000 ms after the answer settles', async () => {
    const calls = stubFetch(LIST_A);
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    expect(calls).toEqual(['/api/downloads']);
    await tick(4999);
    expect(calls).toHaveLength(1);
    await tick(1);
    expect(calls).toHaveLength(2);
    await tick(5000);
    expect(calls).toHaveLength(3);
  });

  it('waits for a slow answer before counting 5 s (no overlapping requests)', async () => {
    const slow = deferred();
    const calls = stubFetch(slow.promise, LIST_A);
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(20000);
    expect(calls).toHaveLength(1);
    slow.resolve(LIST_A);
    await tick(0);
    await tick(4999);
    expect(calls).toHaveLength(1);
    await tick(1);
    expect(calls).toHaveLength(2);
  });

  it('schedules nothing while the page is hidden and fetches at once when it is back', async () => {
    const calls = stubFetch(LIST_A);
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    changeVisibility('hidden');
    await tick(60000);
    expect(calls).toHaveLength(1);
    changeVisibility('visible');
    await tick(0);
    expect(calls).toHaveLength(2);
    await tick(5000);
    expect(calls).toHaveLength(3);
  });

  it('does not chain after an answer that settles while the page is hidden', async () => {
    const slow = deferred();
    const calls = stubFetch(slow.promise);
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    setVisibility('hidden');
    slow.resolve(LIST_A);
    await tick(0);
    await tick(60000);
    expect(calls).toHaveLength(1);
  });

  it('stops everything on unmount and ignores an answer that arrives later', async () => {
    const slow = deferred();
    const calls = stubFetch(slow.promise);
    const view = render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    view.unmount();
    slow.resolve(LIST_A);
    await tick(0);
    await tick(30000);
    expect(calls).toHaveLength(1);
    expect(document.body.textContent).toBe('');
  });

  it('ignores an older answer that resolves after a newer poll started', async () => {
    const old = deferred();
    const calls = stubFetch(old.promise, LIST_B);
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    changeVisibility('hidden');
    changeVisibility('visible');
    await tick(0);
    expect(calls).toHaveLength(2);
    expect(await screen.findByText('Tears.of.Steel')).toBeTruthy();
    old.resolve(LIST_A);
    await tick(0);
    expect(screen.queryByText('Sintel.2010')).toBeNull();
    expect(screen.getByText('Tears.of.Steel')).toBeTruthy();
  });
});

describe('first load, empty list and session cache', () => {
  it('shows the loading line while the first answer is in flight', async () => {
    stubFetch(deferred().promise);
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    const line = screen.getByRole('status');
    expect(line.textContent).toContain(MSG.downloadsLoading);
  });

  it('shows the empty state with a Go to Search button after a successful empty answer', async () => {
    stubFetch(EMPTY);
    const go = vi.fn();
    render(<Downloads onGoToSearch={go} />);
    await tick(0);
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe(MSG.downloadsEmptyTitle);
    expect(screen.getByText(MSG.downloadsEmptyBody)).toBeTruthy();
    expect(screen.queryByText(MSG.downloadsLoading)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: MSG.goToSearch }));
    expect(go).toHaveBeenCalledTimes(1);
  });

  it('shows the cached list at once on a remount, with no loading line, then refreshes in place', async () => {
    stubFetch(LIST_A);
    const first = render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    expect(screen.getByText('Sintel.2010')).toBeTruthy();
    first.unmount();
    stubFetch(deferred().promise);
    render(<Downloads onGoToSearch={() => {}} />);
    expect(screen.getByText('Sintel.2010')).toBeTruthy();
    expect(screen.queryByText(MSG.downloadsLoading)).toBeNull();
    expect(document.querySelector('.is-stale')).toBeNull();
  });

  it('clearDownloadsCache makes the next mount show the loading line again', async () => {
    stubFetch(LIST_A);
    const first = render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    first.unmount();
    clearDownloadsCache();
    stubFetch(deferred().promise);
    render(<Downloads onGoToSearch={() => {}} />);
    expect(screen.queryByText('Sintel.2010')).toBeNull();
    expect(screen.getByText(MSG.downloadsLoading)).toBeTruthy();
  });
});

describe('outage (D-36, DOWN-06)', () => {
  it('a failed first load shows only the banner, never the empty state, and keeps polling', async () => {
    const calls = stubFetch(new TypeError('Failed to fetch'), LIST_A);
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    expect(screen.getByText(MSG.downloadServiceDown)).toBeTruthy();
    expect(screen.queryByText(MSG.downloadsEmptyTitle)).toBeNull();
    expect(screen.queryByText(MSG.downloadsLoading)).toBeNull();
    await tick(5000);
    expect(calls).toHaveLength(2);
    expect(screen.getByText('Sintel.2010')).toBeTruthy();
    expect(screen.queryByText(MSG.downloadServiceDown)).toBeNull();
  });

  it('keeps the rows greyed under the banner on 502 qbit_unreachable and recovers by itself', async () => {
    stubFetch(LIST_A, UNREACHABLE, LIST_A);
    const { container } = render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    expect(container.querySelector('ul.downloads.is-stale')).toBeNull();
    await tick(5000);
    expect(screen.getByText('Sintel.2010')).toBeTruthy();
    expect(container.querySelector('ul.downloads.is-stale')).not.toBeNull();
    expect(screen.getByText(MSG.downloadServiceDown).getAttribute('role')).toBe('status');
    await tick(5000);
    expect(container.querySelector('.is-stale')).toBeNull();
    expect(screen.queryByText(MSG.downloadServiceDown)).toBeNull();
    expect(container.querySelector('.banner')).toBeNull();
  });

  it('shows the "ask the admin" banner on 502 qbit_refused and keeps polling', async () => {
    const calls = stubFetch(LIST_A, REFUSED, LIST_A);
    const { container } = render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    await tick(5000);
    expect(screen.getByText(MSG.downloadServiceProblem)).toBeTruthy();
    expect(screen.queryByText(MSG.downloadServiceDown)).toBeNull();
    expect(container.querySelector('ul.downloads.is-stale')).not.toBeNull();
    await tick(5000);
    expect(calls).toHaveLength(3);
    expect(screen.queryByText(MSG.downloadServiceProblem)).toBeNull();
  });

  it('treats any other failure like an unreachable service', async () => {
    stubFetch(LIST_A, jsonResponse({ detail: 'boom' }, 500));
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    await tick(5000);
    expect(screen.getByText(MSG.downloadServiceDown)).toBeTruthy();
  });

  it('shows nothing extra on a 401 (the global handler owns it)', async () => {
    stubFetch(LIST_A, jsonResponse({ detail: 'not_authenticated' }, 401));
    const { container } = render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    await tick(5000);
    expect(container.querySelector('.banner')).toBeNull();
    expect(container.querySelector('.is-stale')).toBeNull();
  });

  it('never puts a status code, a detail code or the word error on screen', async () => {
    for (const failure of [
      new TypeError('Failed to fetch'),
      UNREACHABLE,
      REFUSED,
      jsonResponse({ detail: 'boom' }, 500),
      jsonResponse({ detail: 'not_authenticated' }, 401),
    ]) {
      stubFetch(LIST_A, failure);
      const view = render(<Downloads onGoToSearch={() => {}} />);
      await tick(0);
      await tick(5000);
      expect(document.body.textContent).not.toMatch(/502|500|401|qbit_|boom|not_authenticated|error/i);
      view.unmount();
      clearDownloadsCache();
    }
  });
});

// A route-aware stub: the list answers come from `list`, every DELETE takes the next `del`
// answer. Each call is recorded with its path, method and body.
function stubApi({ list = [LIST_A], del = [jsonResponse(null, 204)] } = {}) {
  const calls = [];
  let lists = 0;
  let dels = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn((path, init = {}) => {
      calls.push({ path, method: init.method, body: init.body });
      const isDelete = init.method === 'DELETE';
      const answers = isDelete ? del : list;
      const n = isDelete ? dels++ : lists++;
      const a = answers[Math.min(n, answers.length - 1)];
      return a instanceof Error ? Promise.reject(a) : Promise.resolve(a);
    }),
  );
  return {
    calls,
    deletes: () => calls.filter((c) => c.method === 'DELETE'),
  };
}

const NO_CONTENT = { ok: true, status: 204, json: async () => null };

describe('cancel from the list (D-32, D-35)', () => {
  it('Cancel, then "Yes, cancel" sends exactly one DELETE with the id and no body, and the row goes at once', async () => {
    const net = stubApi({ del: [NO_CONTENT] });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    fireEvent.click(screen.getByRole('button', { name: MSG.cancelDownload }));
    expect(screen.getByText(MSG.cancelConfirmTitle)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: MSG.cancelConfirmYes }));
    await tick(0);
    expect(net.deletes()).toEqual([
      { path: `/api/downloads/${'a'.repeat(16)}`, method: 'DELETE', body: undefined },
    ]);
    expect(screen.queryByText('Sintel.2010')).toBeNull();
    expect(screen.queryByText(MSG.cancelConfirmTitle)).toBeNull();
  });

  it('a 404 (already gone) removes the row like a 204, with no message', async () => {
    stubApi({ del: [jsonResponse({ detail: 'download_not_found' }, 404)] });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    fireEvent.click(screen.getByRole('button', { name: MSG.cancelDownload }));
    fireEvent.click(screen.getByRole('button', { name: MSG.cancelConfirmYes }));
    await tick(0);
    expect(screen.queryByText('Sintel.2010')).toBeNull();
    expect(document.body.textContent).not.toMatch(/404|download_not_found/);
    expect(screen.queryByText(MSG.actionFailed)).toBeNull();
  });

  it('"No, keep it" closes the panel, sends nothing and returns focus to Cancel', async () => {
    const net = stubApi();
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    fireEvent.click(screen.getByRole('button', { name: MSG.cancelDownload }));
    expect(document.activeElement).toBe(screen.getByRole('button', { name: MSG.cancelConfirmNo }));
    fireEvent.click(screen.getByRole('button', { name: MSG.cancelConfirmNo }));
    await tick(0);
    expect(screen.queryByText(MSG.cancelConfirmTitle)).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: MSG.cancelDownload }));
    expect(net.deletes()).toHaveLength(0);
  });

  it('while the DELETE is pending both buttons are disabled, "Cancelling…" shows and a second tap sends nothing', async () => {
    const pending = deferred();
    const net = stubApi({ del: [pending.promise] });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    fireEvent.click(screen.getByRole('button', { name: MSG.cancelDownload }));
    fireEvent.click(screen.getByRole('button', { name: MSG.cancelConfirmYes }));
    await tick(0);
    const busyButton = screen.getByRole('button', { name: MSG.cancelling });
    expect(busyButton.disabled).toBe(true);
    expect(screen.getByRole('button', { name: MSG.cancelConfirmNo }).disabled).toBe(true);
    fireEvent.click(busyButton);
    await tick(0);
    expect(net.deletes()).toHaveLength(1);
    pending.resolve(NO_CONTENT);
    await tick(0);
    expect(screen.queryByText('Sintel.2010')).toBeNull();
  });
});
