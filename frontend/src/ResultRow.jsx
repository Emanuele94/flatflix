import { MSG } from './messages.js';

// Row states (kept by Search, keyed by result_id):
//   undefined | pending | started | preparing | duplicate
//   | rejected | unsupported | unavailable | failed | expired | notReady | network | lost
//   | throttled (429 on the tap, D-39) | cancelled (job cancelled from the Downloads tab)
// "Started" is rendered for `started` only: the backend returns it after the allowlist ran,
// priorities were verified and torrents/start succeeded. Nothing else ever looks like success.

// States shown as a disabled button carrying the text itself.
const LOCKED_LABEL = {
  started: { text: MSG.started, tone: 'ok' },
  preparing: { text: MSG.preparing, tone: 'warn', spinner: true },
  duplicate: { text: MSG.duplicate, tone: 'warn' },
};

// States shown as a message under the button.
const MESSAGE = {
  rejected: { text: MSG.rejected, tone: 'warn', retry: false },
  unsupported: { text: MSG.unsupportedFormat, tone: 'warn', retry: false },
  unavailable: { text: MSG.unavailable, tone: 'warn', retry: false },
  expired: { text: MSG.searchExpired, tone: 'warn', retry: false },
  failed: { text: MSG.downloadFailed, tone: 'error', retry: true },
  notReady: { text: MSG.notReady, tone: 'warn', retry: true },
  network: { text: MSG.serverUnreachable, tone: 'error', retry: true },
  lost: { text: MSG.downloadLost, tone: 'warn', retry: true },
  throttled: { text: MSG.throttled, tone: 'warn', retry: true },
  cancelled: { text: MSG.downloadCancelled, tone: 'warn', retry: true },
};

// One search result. Names are attacker-controlled text: only ever rendered as text children.
export function ResultRow({ result, state, onDownload }) {
  const locked = LOCKED_LABEL[state];
  const message = MESSAGE[state];
  const pending = state === 'pending';
  const disabled = pending || Boolean(message && !message.retry);

  return (
    <li class="result">
      <div class="result-name">{result.name}</div>
      <div class="result-main">
        <span class="result-size">{result.size_human}</span>
        <span class="result-seeders">
          {result.seeders} {MSG.seedUnit}
        </span>
        {result.quality && <span class="badge">{result.quality}</span>}
      </div>
      <div class="result-meta muted">
        {result.leechers} {MSG.leechUnit} · {result.source}
      </div>
      <div class="result-action">
        {locked ? (
          <button class={`btn row-state row-state-${locked.tone}`} type="button" disabled>
            {locked.spinner && <span class="spinner" aria-hidden="true" />}
            {locked.text}
          </button>
        ) : (
          <>
            <button
              class="btn btn-primary"
              type="button"
              disabled={disabled}
              onClick={() => {
                if (!disabled) onDownload(result);
              }}
            >
              {pending && <span class="spinner" aria-hidden="true" />}
              {MSG.download}
            </button>
            {message && (
              <p class={`row-state row-state-${message.tone}`} role="status">
                {message.text}
              </p>
            )}
          </>
        )}
      </div>
    </li>
  );
}
