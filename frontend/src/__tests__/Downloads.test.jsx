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

const READY = (id, name) => item(id, name, { state: 'ready', progress: 100, eta_seconds: null, action: 'remove' });
const ID_A = 'a'.repeat(16);

function click(name) {
  fireEvent.click(screen.getByRole('button', { name }));
}

describe('remove from list (D-33)', () => {
  it('one tap sends one DELETE with the id and no body and the row goes on 204', async () => {
    const net = stubApi({
      list: [jsonResponse({ items: [READY('a', 'Sintel.2010'), item('b', 'Tears.of.Steel')] })],
      del: [NO_CONTENT],
    });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    click(MSG.removeFromList);
    await tick(0);
    expect(net.deletes()).toEqual([{ path: `/api/downloads/${ID_A}`, method: 'DELETE', body: undefined }]);
    expect(screen.queryByText('Sintel.2010')).toBeNull();
    expect(screen.getByText('Tears.of.Steel')).toBeTruthy();
  });

  it('a 404 removes the row too', async () => {
    stubApi({
      list: [jsonResponse({ items: [READY('a', 'Sintel.2010')] })],
      del: [jsonResponse({ detail: 'download_not_found' }, 404)],
    });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    click(MSG.removeFromList);
    await tick(0);
    expect(screen.queryByText('Sintel.2010')).toBeNull();
    expect(screen.queryByText(MSG.actionFailed)).toBeNull();
  });

  it('shows "Removing…" with a disabled button while the DELETE is pending and sends nothing twice', async () => {
    const pending = deferred();
    const net = stubApi({ list: [jsonResponse({ items: [READY('a', 'Sintel.2010')] })], del: [pending.promise] });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    click(MSG.removeFromList);
    await tick(0);
    const busyButton = screen.getByRole('button', { name: MSG.removing });
    expect(busyButton.disabled).toBe(true);
    fireEvent.click(busyButton);
    await tick(0);
    expect(net.deletes()).toHaveLength(1);
    pending.resolve(NO_CONTENT);
    await tick(0);
    expect(screen.queryByText('Sintel.2010')).toBeNull();
  });

  it('a failed-job row has no button and no dismiss control (D-29)', async () => {
    stubApi({ list: [jsonResponse({ items: [item('f', 'Gone.Wrong', { state: 'failed', action: null })] })] });
    const { container } = render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    expect(screen.getByText('Gone.Wrong')).toBeTruthy();
    expect(container.querySelector('button')).toBeNull();
  });
});

describe('action failures (D-36, D-37)', () => {
  it('a 500 closes the panel, keeps the row, says it plainly and the next tap works', async () => {
    const net = stubApi({ del: [jsonResponse({ detail: 'boom' }, 500), NO_CONTENT] });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    click(MSG.cancelDownload);
    click(MSG.cancelConfirmYes);
    await tick(0);
    expect(screen.queryByText(MSG.cancelConfirmTitle)).toBeNull();
    expect(screen.getByText('Sintel.2010')).toBeTruthy();
    const note = screen.getByText(MSG.actionFailed);
    expect(note.getAttribute('role')).toBe('status');
    expect(note.classList.contains('row-state-warn')).toBe(true);
    expect(document.body.textContent).not.toMatch(/500|boom/);
    expect(screen.getByRole('button', { name: MSG.cancelDownload }).disabled).toBe(false);
    click(MSG.cancelDownload);
    expect(screen.queryByText(MSG.actionFailed)).toBeNull();
    click(MSG.cancelConfirmYes);
    await tick(0);
    expect(net.deletes()).toHaveLength(2);
    expect(screen.queryByText('Sintel.2010')).toBeNull();
  });

  it('a failed Remove says the same sentence and keeps the row', async () => {
    stubApi({
      list: [jsonResponse({ items: [READY('a', 'Sintel.2010')] })],
      del: [jsonResponse({ detail: 'boom' }, 500)],
    });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    click(MSG.removeFromList);
    await tick(0);
    expect(screen.getByText('Sintel.2010')).toBeTruthy();
    expect(screen.getByText(MSG.actionFailed)).toBeTruthy();
    expect(screen.getByRole('button', { name: MSG.removeFromList }).disabled).toBe(false);
  });

  it.each([
    ['502 qbit_unreachable', jsonResponse({ detail: 'qbit_unreachable' }, 502), MSG.downloadServiceDown],
    ['502 qbit_refused', jsonResponse({ detail: 'qbit_refused' }, 502), MSG.downloadServiceProblem],
    ['a network failure', new TypeError('Failed to fetch'), MSG.downloadServiceDown],
  ])('%s follows the outage rule: banner, greyed list, buttons off, no action sentence', async (_n, answer, banner) => {
    const { container } = (() => {
      stubApi({ del: [answer] });
      return render(<Downloads onGoToSearch={() => {}} />);
    })();
    await tick(0);
    click(MSG.cancelDownload);
    click(MSG.cancelConfirmYes);
    await tick(0);
    expect(screen.getByText(banner)).toBeTruthy();
    expect(container.querySelector('ul.downloads.is-stale')).not.toBeNull();
    expect(screen.queryByText(MSG.cancelConfirmTitle)).toBeNull();
    expect(screen.queryByText(MSG.actionFailed)).toBeNull();
    expect(screen.getByRole('button', { name: MSG.cancelDownload }).disabled).toBe(true);
    expect(screen.getByText('Sintel.2010')).toBeTruthy();
  });

  it('the next successful poll after an outage re-enables the buttons', async () => {
    stubApi({ list: [LIST_A, LIST_A], del: [jsonResponse({ detail: 'qbit_unreachable' }, 502)] });
    const { container } = render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    click(MSG.cancelDownload);
    click(MSG.cancelConfirmYes);
    await tick(0);
    expect(screen.getByRole('button', { name: MSG.cancelDownload }).disabled).toBe(true);
    await tick(5000);
    expect(container.querySelector('.is-stale')).toBeNull();
    expect(screen.getByRole('button', { name: MSG.cancelDownload }).disabled).toBe(false);
  });

  it('a failed poll (stale) closes an open confirm panel and disables every button', async () => {
    stubApi({ list: [LIST_A, UNREACHABLE] });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    click(MSG.cancelDownload);
    expect(screen.getByText(MSG.cancelConfirmTitle)).toBeTruthy();
    await tick(5000);
    expect(screen.queryByText(MSG.cancelConfirmTitle)).toBeNull();
    expect(screen.getByRole('button', { name: MSG.cancelDownload }).disabled).toBe(true);
  });

  it('never puts a status code or a detail code on screen after a failed action', async () => {
    for (const answer of [
      jsonResponse({ detail: 'boom' }, 500),
      jsonResponse({ detail: 'qbit_unreachable' }, 502),
      jsonResponse({ detail: 'qbit_refused' }, 502),
      jsonResponse({ detail: 'download_not_found' }, 404),
    ]) {
      stubApi({ del: [answer] });
      const view = render(<Downloads onGoToSearch={() => {}} />);
      await tick(0);
      click(MSG.cancelDownload);
      click(MSG.cancelConfirmYes);
      await tick(0);
      expect(document.body.textContent).not.toMatch(/502|500|404|qbit_|boom|download_not_found/);
      view.unmount();
      clearDownloadsCache();
    }
  });
});

describe('one confirm panel at a time, and only while it is true', () => {
  const TWO = jsonResponse({ items: [item('a', 'Sintel.2010'), item('b', 'Tears.of.Steel')] });

  it('opening the confirm of row B closes the one of row A', async () => {
    stubApi({ list: [TWO] });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    fireEvent.click(screen.getAllByRole('button', { name: MSG.cancelDownload })[0]);
    expect(screen.getAllByText(MSG.cancelConfirmTitle)).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: MSG.cancelDownload }));
    expect(screen.getAllByText(MSG.cancelConfirmTitle)).toHaveLength(1);
    expect(screen.getByText('Sintel.2010').closest('li').querySelector('.confirm')).toBeNull();
    expect(screen.getByText('Tears.of.Steel').closest('li').querySelector('.confirm')).not.toBeNull();
  });

  it('an open panel survives a refresh that returns the same row', async () => {
    stubApi({ list: [LIST_A, jsonResponse({ items: [item('a', 'Sintel.2010', { progress: 55 })] })] });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    click(MSG.cancelDownload);
    await tick(5000);
    expect(screen.getByText(MSG.cancelConfirmTitle)).toBeTruthy();
    expect(screen.getByText('55%')).toBeTruthy();
  });

  it('a refresh that makes the row ready closes the panel and offers Remove from list instead', async () => {
    stubApi({ list: [LIST_A, jsonResponse({ items: [READY('a', 'Sintel.2010')] })] });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    click(MSG.cancelDownload);
    await tick(5000);
    expect(screen.queryByText(MSG.cancelConfirmTitle)).toBeNull();
    expect(screen.queryByRole('button', { name: MSG.cancelConfirmYes })).toBeNull();
    expect(screen.getByRole('button', { name: MSG.removeFromList })).toBeTruthy();
  });

  it('a refresh that no longer has the row closes the panel', async () => {
    stubApi({ list: [LIST_A, LIST_B] });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    click(MSG.cancelDownload);
    await tick(5000);
    expect(screen.queryByText(MSG.cancelConfirmTitle)).toBeNull();
    expect(screen.getByText('Tears.of.Steel')).toBeTruthy();
  });

  it('a slow poll that started before the cancel does not bring the row back', async () => {
    const slow = deferred();
    stubApi({ list: [LIST_A, slow.promise] });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    await tick(5000);
    click(MSG.cancelDownload);
    click(MSG.cancelConfirmYes);
    await tick(0);
    expect(screen.queryByText('Sintel.2010')).toBeNull();
    slow.resolve(LIST_A);
    await tick(0);
    expect(screen.queryByText('Sintel.2010')).toBeNull();
  });
});

const CHECKING = (id, name, extra = {}) =>
  item(id, name, {
    state: 'checking',
    action: 'cancel',
    progress: 99,
    eta_seconds: null,
    skipped: 0,
    ...extra,
  });

describe('safety check tracer (D-53)', () => {
  it('a checking row shows Checking… with its hint, no bar, and cancels with the finished-download confirm', async () => {
    const net = stubApi({
      list: [jsonResponse({ items: [CHECKING('a', 'Sintel.2010')] })],
      del: [NO_CONTENT],
    });
    const { container } = render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    const row = screen.getByText('Sintel.2010').closest('li');
    expect(row.querySelector('.download-state').textContent).toBe(MSG.stateChecking);
    expect(row.querySelector('.spinner')).not.toBeNull();
    expect(screen.getByText(MSG.checkingHint)).toBeTruthy();
    expect(container.querySelector('progress')).toBeNull();
    expect(container.textContent).not.toContain('%');
    click(MSG.cancelDownload);
    expect(screen.getByText(MSG.cancelConfirmTitle)).toBeTruthy();
    expect(screen.getByText(MSG.cancelConfirmBodyDone)).toBeTruthy();
    expect(screen.queryByText(MSG.cancelConfirmBody)).toBeNull();
    click(MSG.cancelConfirmYes);
    await tick(0);
    expect(net.deletes()).toEqual([{ path: `/api/downloads/${ID_A}`, method: 'DELETE', body: undefined }]);
    expect(screen.queryByText('Sintel.2010')).toBeNull();
  });
});

describe('safety check rows in the list (D-53, D-56, D-61)', () => {
  const FAILED = (id, name) =>
    item(id, name, { state: 'check_failed', action: null, progress: 99, eta_seconds: null, skipped: 0 });

  it('an outage greys the list and disables the checking row\'s Cancel button', async () => {
    stubApi({ list: [jsonResponse({ items: [CHECKING('a', 'Sintel.2010')] }), UNREACHABLE] });
    const { container } = render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    click(MSG.cancelDownload);
    expect(screen.getByText(MSG.cancelConfirmTitle)).toBeTruthy();
    await tick(5000);
    expect(container.querySelector('ul.downloads.is-stale')).not.toBeNull();
    expect(screen.queryByText(MSG.cancelConfirmTitle)).toBeNull();
    expect(screen.getByRole('button', { name: MSG.cancelDownload }).disabled).toBe(true);
  });

  it('a list that only held a check_failed row returns to the empty state', async () => {
    stubApi({ list: [jsonResponse({ items: [FAILED('f', 'Fake.Movie')] }), EMPTY] });
    const { container } = render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    expect(screen.getByText(MSG.checkFailed)).toBeTruthy();
    expect(container.querySelector('button')).toBeNull();
    await tick(5000);
    expect(screen.getByText(MSG.downloadsEmptyTitle)).toBeTruthy();
    expect(screen.getByText(MSG.downloadsEmptyBody)).toBeTruthy();
  });

  it('rows render in the order the backend sends them', async () => {
    stubApi({
      list: [
        jsonResponse({
          items: [
            CHECKING('a', 'First.Row'),
            FAILED('f', 'Second.Row'),
            item('r', 'Third.Row', { state: 'ready', action: 'remove', progress: 100, skipped: 2 }),
          ],
        }),
      ],
    });
    const { container } = render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    const names = [...container.querySelectorAll('.download-name')].map((n) => n.textContent);
    expect(names).toEqual(['First.Row', 'Second.Row', 'Third.Row']);
    expect(screen.getByText(MSG.skippedMany.replace('{n}', '2'))).toBeTruthy();
  });

  it('a failing DELETE on a checking row says so plainly and keeps the row', async () => {
    stubApi({
      list: [jsonResponse({ items: [CHECKING('a', 'Sintel.2010')] })],
      del: [jsonResponse({ detail: 'boom' }, 500)],
    });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    click(MSG.cancelDownload);
    click(MSG.cancelConfirmYes);
    await tick(0);
    expect(screen.getByText(MSG.actionFailed)).toBeTruthy();
    expect(screen.getByText('Sintel.2010')).toBeTruthy();
    expect(screen.queryByText(MSG.cancelConfirmTitle)).toBeNull();
  });

  it('a 404 on a checking row removes it like a 204, and Cancelling… shows while in flight', async () => {
    const pending = deferred();
    stubApi({
      list: [jsonResponse({ items: [CHECKING('a', 'Sintel.2010')] })],
      del: [pending.promise],
    });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    click(MSG.cancelDownload);
    click(MSG.cancelConfirmYes);
    await tick(0);
    expect(screen.getByRole('button', { name: MSG.cancelling }).disabled).toBe(true);
    pending.resolve(jsonResponse({ detail: 'download_not_found' }, 404));
    await tick(0);
    expect(screen.queryByText('Sintel.2010')).toBeNull();
    expect(screen.queryByText(MSG.actionFailed)).toBeNull();
  });

  it('a downloading row that moves to checking with its panel open switches the body and stays open', async () => {
    stubApi({
      list: [LIST_A, jsonResponse({ items: [CHECKING('a', 'Sintel.2010')] })],
    });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    click(MSG.cancelDownload);
    expect(screen.getByText(MSG.cancelConfirmBody)).toBeTruthy();
    await tick(5000);
    expect(screen.getByText(MSG.cancelConfirmTitle)).toBeTruthy();
    expect(screen.getByText(MSG.cancelConfirmBodyDone)).toBeTruthy();
  });

  it('a checking row that becomes check_failed closes its panel', async () => {
    stubApi({
      list: [jsonResponse({ items: [CHECKING('a', 'Sintel.2010')] }), jsonResponse({ items: [FAILED('a', 'Sintel.2010')] })],
    });
    render(<Downloads onGoToSearch={() => {}} />);
    await tick(0);
    click(MSG.cancelDownload);
    await tick(5000);
    expect(screen.queryByText(MSG.cancelConfirmTitle)).toBeNull();
    expect(screen.getByText(MSG.checkFailed)).toBeTruthy();
  });
});
