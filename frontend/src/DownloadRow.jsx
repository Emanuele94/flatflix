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
// `stale` is accepted now; the row actions of plan 02-10 use it to disable their buttons.
export function DownloadRow({ item }) {
  const state = STATES[item.state];
  const badge = BADGE[item.type];
  const eta = item.state === 'downloading' ? formatEta(item.eta_seconds) : null;
  const value = item.state === 'ready' ? 100 : Math.round(item.progress);
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
    </li>
  );
}
