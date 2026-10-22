import { useEffect, useRef } from 'preact/hooks';
import { formatEta } from './eta.js';
import { MSG } from './messages.js';

// state code (from the backend) -> text and tone. The backend decides the state; this only maps
// a code to words. bar: 'indeterminate' | 'value' | null; barClass colours the native element.
const STATES = {
  preparing: { text: MSG.preparing, tone: 'warn', bar: 'indeterminate', spinner: true },
  downloading: { text: MSG.stateDownloading, tone: 'normal', bar: 'value', barClass: 'is-downloading' },
  stalled: {
    text: MSG.stateStalled,
    tone: 'warn',
    bar: 'value',
    barClass: 'is-stalled',
    hint: MSG.stalledHint,
  },
  ready: { text: MSG.stateReady, tone: 'ok', bar: 'value', barClass: 'is-ready' },
  problem: { text: MSG.stateProblem, tone: 'error', bar: null, hint: MSG.problemBody },
  rejected: { text: MSG.rejected, tone: 'warn', bar: null },
  unsupported: { text: MSG.unsupportedFormat, tone: 'warn', bar: null },
  unavailable: { text: MSG.unavailable, tone: 'warn', bar: null },
  failed: { text: MSG.downloadFailed, tone: 'error', bar: null },
};

const BADGE = { film: MSG.typeFilm, serie: MSG.typeSerie };

// One download. Names are attacker-controlled text: only ever rendered as text children.
// The action area follows the backend's `action` field: 'cancel' (asks once, in the row, D-32),
// 'remove' (one tap, the files stay, D-33) or null (no control, D-29). `stale` disables it (D-36).
export function DownloadRow({
  item,
  stale = false,
  confirming = false,
  busy = null,
  onAskCancel,
  onCancel,
  onKeep,
  onRemove,
}) {
  const state = STATES[item.state];
  const badge = BADGE[item.type];
  const eta = item.state === 'downloading' ? formatEta(item.eta_seconds) : null;
  const value = item.state === 'ready' ? 100 : Math.round(item.progress);

  const cancelRef = useRef(null);
  const keepRef = useRef(null);
  const panelWasOpen = useRef(false);
  const showPanel = item.action === 'cancel' && (confirming || busy === 'cancel');

  // Focus: the safe choice when the panel opens; back on "Cancel download" when it closes.
  useEffect(() => {
    if (showPanel && !panelWasOpen.current && keepRef.current) keepRef.current.focus();
    if (!showPanel && panelWasOpen.current && cancelRef.current) cancelRef.current.focus();
    panelWasOpen.current = showPanel;
  }, [showPanel]);

  const locked = stale || busy !== null;
  return (
    <li class="download">
      <div class="download-name">{item.name || MSG.unnamedDownload}</div>
      <div class="download-main">
        {badge && <span class="badge">{badge}</span>}
        {state && (
          <span class={`download-state row-state-${state.tone}`}>
            {state.spinner && <span class="spinner" aria-hidden="true" />}
            {state.text}
          </span>
        )}
        {eta && <span class="download-eta muted">{eta}</span>}
      </div>
      {state && state.hint && (
        <p class={`download-hint ${state.tone === 'error' ? 'row-state-error' : 'muted'}`}>
          {state.hint}
        </p>
      )}
      {state && state.bar && (
        <div class="download-progress">
          {state.bar === 'indeterminate' ? (
            <progress max="100" aria-label={MSG.progressLabel} />
          ) : (
            <progress
              class={state.barClass}
              max="100"
              value={value}
              aria-label={MSG.progressLabel}
            />
          )}
          {state.bar === 'value' && (
            <span class="download-percent muted" aria-hidden="true">
              {value}%
            </span>
          )}
        </div>
      )}
      {item.action === 'cancel' && (
        <div class="download-action">
          {showPanel ? (
            <div
              class="confirm"
              onKeyDown={(e) => {
                if (e.key === 'Escape' && !locked) onKeep(item.id);
              }}
            >
              <p class="confirm-title">{MSG.cancelConfirmTitle}</p>
              <p class="muted">{MSG.cancelConfirmBody}</p>
              <div class="confirm-actions">
                <button
                  class="btn btn-destructive"
                  type="button"
                  disabled={locked}
                  onClick={() => onCancel(item.id)}
                >
                  {busy === 'cancel' && <span class="spinner" aria-hidden="true" />}
                  {busy === 'cancel' ? MSG.cancelling : MSG.cancelConfirmYes}
                </button>
                <button
                  class="btn"
                  type="button"
                  ref={keepRef}
                  disabled={locked}
                  onClick={() => onKeep(item.id)}
                >
                  {MSG.cancelConfirmNo}
                </button>
              </div>
            </div>
          ) : (
            <button
              class="btn"
              type="button"
              ref={cancelRef}
              disabled={locked}
              onClick={() => onAskCancel(item.id)}
            >
              {MSG.cancelDownload}
            </button>
          )}
        </div>
      )}
    </li>
  );
}
