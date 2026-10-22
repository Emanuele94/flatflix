import { useEffect, useState } from 'preact/hooks';
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

  useEffect(() => {
    let alive = true;
    let epoch = 0;
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
      epoch += 1;
      const run = epoch;
      try {
        const data = await api('/api/downloads');
        if (!alive || run !== epoch) return; // unmounted, or a newer poll owns the answer
        cachedItems = data.items;
        setItems(data.items);
        setProblem(null);
      } catch (err) {
        if (!alive || run !== epoch) return;
        // A 401 belongs to the global handler (login screen): nothing to show here.
        if (!(err instanceof ApiError && err.status === 401)) {
          setProblem(err instanceof ApiError && err.code === 'qbit_refused' ? 'refused' : 'down');
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
          <DownloadRow key={item.id} item={item} stale={Boolean(problem)} />
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
