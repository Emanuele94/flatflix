import { useEffect, useRef, useState } from 'preact/hooks';
import { api, ApiError } from './api.js';
import { DownloadRow } from './DownloadRow.jsx';
import { MSG } from './messages.js';

export const POLL_MS = 5000;

// The last list this session saw, so coming back to the tab shows it at once (UI-SPEC: Polling).
let cachedItems = null;

export function clearDownloadsCache() {
  cachedItems = null;
}

// jsdom reports 'prerender', never 'visible': only 'hidden' means "do not poll".
function pageHidden() {
  return document.visibilityState === 'hidden';
}

// The Downloads tab. Mounted only while its tab is active; the effect cleanup stops everything.
export function Downloads({ onGoToSearch }) {
  const [items, setItems] = useState(cachedItems); // null until a list was ever received
  const [problem, setProblem] = useState(null); // null | 'down' | 'refused'
  const [confirmId, setConfirmId] = useState(null); // the one row with an open confirm panel
  const [busy, setBusy] = useState({}); // id -> 'cancel' | 'remove' while a DELETE is in flight
  const busyRef = useRef({}); // synchronous twin of `busy`: a second tap in the same tick sends nothing

  const [failedId, setFailedId] = useState(null); // the row whose last action failed (D-37)
  const epochRef = useRef(0); // counts polls; a poll's number tells if it began before an action
  const removedRef = useRef(new Map()); // id -> poll number current when its row was removed

  function removeRow(id) {
    removedRef.current.set(id, epochRef.current);
    if (cachedItems) cachedItems = cachedItems.filter((i) => i.id !== id);
    setItems((prev) => (prev ? prev.filter((i) => i.id !== id) : prev));
    setConfirmId((cur) => (cur === id ? null : cur));
  }

  // Cancel and Remove are the same request: one DELETE with only the opaque id (D-35). The server
  // decides whether files go (plan 02-07); the browser never says.
  async function act(id, kind) {
    if (busyRef.current[id]) return;
    busyRef.current[id] = kind;
    setBusy({ ...busyRef.current });
    setFailedId((cur) => (cur === id ? null : cur));
    try {
      await api(`/api/downloads/${id}`, { method: 'DELETE' });
      removeRow(id);
    } catch (err) {
      const status = err instanceof ApiError ? err.status : -1;
      if (status === 404) {
        removeRow(id); // already gone: that is what she wanted
      } else if (status === 0 || status === 502) {
        // The download service is out of reach: the outage rule, not a per-row message (D-36).
        setProblem(err.code === 'qbit_refused' ? 'refused' : 'down');
        setConfirmId(null);
      } else if (status !== 401) {
        // A 401 belongs to the global handler. Anything else: restore the row, say it plainly.
        setConfirmId(null);
        setFailedId(id);
      }
    } finally {
      delete busyRef.current[id];
      setBusy({ ...busyRef.current });
    }
  }

  useEffect(() => {
    let alive = true;
    let timer = null;

    function clearTimer() {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
    }

    // 5 s after an answer settles, and only while the page is visible.
    function schedule() {
      clearTimer();
      if (!alive || pageHidden()) return;
      timer = setTimeout(poll, POLL_MS);
    }

    async function poll() {
      clearTimer();
      epochRef.current += 1;
      const run = epochRef.current;
      try {
        const data = await api('/api/downloads');
        if (!alive || run !== epochRef.current) return; // unmounted, or a newer poll owns the answer
        // A row removed after this poll began must not come back from its older answer.
        const removed = removedRef.current;
        for (const [id, at] of removed) if (run > at) removed.delete(id);
        const list = data.items.filter((i) => !removed.has(i.id));
        cachedItems = list;
        setItems(list);
        setProblem(null);
        // An open confirm only survives while its row still asks to be cancelled: she is never
        // asked to cancel a film that just finished.
        setConfirmId((cur) =>
          cur !== null && list.some((i) => i.id === cur && i.action === 'cancel') ? cur : null,
        );
      } catch (err) {
        if (!alive || run !== epochRef.current) return;
        // A 401 belongs to the global handler (login screen): nothing to show here.
        if (!(err instanceof ApiError && err.status === 401)) {
          setProblem(err instanceof ApiError && err.code === 'qbit_refused' ? 'refused' : 'down');
          setConfirmId(null); // a stale list never keeps a confirm open (D-36)
        }
      }
      schedule();
    }

    function onVisibility() {
      clearTimer();
      if (!pageHidden()) poll();
    }

    document.addEventListener('visibilitychange', onVisibility);
    poll();
    return () => {
      alive = false;
      clearTimer();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, []);

  const banner =
    problem === 'refused' ? MSG.downloadServiceProblem : problem ? MSG.downloadServiceDown : null;

  let body = null;
  if (items === null) {
    // Nothing known yet. A failed first load shows only the banner, never "No downloads yet".
    if (!problem) {
      body = (
        <p class="searching" role="status">
          <span class="spinner" aria-hidden="true" />
          {MSG.downloadsLoading}
        </p>
      );
    }
  } else if (items.length === 0) {
    if (!problem) {
      body = (
        <div class="empty">
          <h2>{MSG.downloadsEmptyTitle}</h2>
          <p class="muted">{MSG.downloadsEmptyBody}</p>
          <button class="btn btn-primary" type="button" onClick={onGoToSearch}>
            {MSG.goToSearch}
          </button>
        </div>
      );
    }
  } else {
    body = (
      <ul class={problem ? 'downloads is-stale' : 'downloads'}>
        {items.map((item) => (
          <DownloadRow
            key={item.id}
            item={item}
            stale={Boolean(problem)}
            confirming={confirmId === item.id}
            busy={busy[item.id] || null}
            failed={failedId === item.id}
            onAskCancel={(id) => {
              setFailedId(null);
              setConfirmId(id); // one panel at a time: opening this one closes any other
            }}
            onKeep={() => setConfirmId(null)}
            onCancel={(id) => act(id, 'cancel')}
            onRemove={(id) => act(id, 'remove')}
          />
        ))}
      </ul>
    );
  }

  return (
    <>
      {banner && (
        <p class="banner" role="status">
          {banner}
        </p>
      )}
      {body}
    </>
  );
}
