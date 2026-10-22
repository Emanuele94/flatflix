import { useEffect, useRef, useState } from 'preact/hooks';
import { api, ApiError } from './api.js';
import { MSG } from './messages.js';
import { ResultRow } from './ResultRow.jsx';

const POLL_MS = 700;
const JOB_POLL_MS = 2000; // D-11: ask the backend about a preparing job every 2 s
const JOB_GIVE_UP_MS = 330000; // METADATA_TIMEOUT is 5 min; stop asking after 5.5 min

// A row in one of these states can be tapped again; every other state ignores taps.
const RETRYABLE = new Set(['failed', 'notReady', 'network', 'lost']);
// Backend job statuses that map to a row state. Anything else is a failure, never a success.
const JOB_STATES = new Set([
  'started',
  'preparing',
  'rejected',
  'unsupported',
  'unavailable',
  'duplicate',
  'failed',
]);

// The current search survives a page reload (G-01-3 c, D-11): sessionStorage, this tab only.
// It holds only the query, the type, opaque ids, the rows the API already showed and row states.
// No credentials, URLs, hashes, paths or categories ever reach it (PUI-02, T-01-43, T-01-54).
export const SAVED_SEARCH_KEY = 'flatflix.search';
const SAVED_SEARCH_VERSION = 1;
const ID = /^[0-9a-f]{16}$/; // the backend's result, job and search id shape
// Row states a saved job may hold: the backend statuses plus the client-side ones.
const ROW_STATES = new Set([...JOB_STATES, 'expired', 'notReady', 'network', 'lost']);

// Bumped by every clear. A write that carries an older generation is dropped, so a late answer
// from a screen that is going away cannot bring a cleared search back (T-01-57).
let generation = 0;

export function clearSavedSearch() {
  generation += 1;
  try {
    sessionStorage.removeItem(SAVED_SEARCH_KEY);
  } catch {
    // Storage unusable: nothing was saved, nothing to clear.
  }
}

function writeSaved(gen, record) {
  if (gen !== generation) return;
  try {
    sessionStorage.setItem(SAVED_SEARCH_KEY, JSON.stringify(record));
  } catch {
    // Storage unusable or full: the portal works the same, it only stops surviving a reload.
  }
}

// The seven fields the search API returns for a row; nothing else is ever saved or restored.
const ROW_FIELDS = ['result_id', 'name', 'size_human', 'seeders', 'leechers', 'source', 'quality'];
const MAX_QUERY = 1000; // the backend's raw cap on q
const MAX_ROWS = 500;

const isPlainObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isPrimitive = (v) => v === null || ['string', 'number', 'boolean'].includes(typeof v);

function pickRow(r) {
  const out = {};
  for (const f of ROW_FIELDS) if (r[f] !== undefined && isPrimitive(r[f])) out[f] = r[f];
  return out;
}

// A row needs an id-shaped result_id and a string name; a bad row is dropped on its own.
const validRow = (r) => isPlainObject(r) && ID.test(r.result_id) && typeof r.name === 'string';

// Turns saved jobs into row states. A mid-tap row (pending) and a job past the give-up time come
// back as lost and retryable, never as a spinner (WR-05). Only a young preparing job resumes
// polling, with its original start time so the 330 s limit survives the reload (T-01-56).
function restoreJobs(saved, now) {
  const jobs = {};
  const resume = [];
  if (!isPlainObject(saved)) return { jobs, resume };
  for (const [id, entry] of Object.entries(saved)) {
    if (!ID.test(id) || !isPlainObject(entry)) continue;
    if (entry.state !== 'pending' && !ROW_STATES.has(entry.state)) continue;
    if (entry.jobId !== undefined && !(typeof entry.jobId === 'string' && ID.test(entry.jobId))) continue;
    if (entry.startedAt !== undefined && !Number.isFinite(entry.startedAt)) continue;
    if (entry.state === 'pending') {
      jobs[id] = { state: 'lost' };
    } else if (entry.state !== 'preparing') {
      jobs[id] = { state: entry.state };
    } else if (
      entry.jobId !== undefined &&
      entry.startedAt !== undefined &&
      entry.startedAt <= now &&
      now - entry.startedAt < JOB_GIVE_UP_MS
    ) {
      jobs[id] = { state: 'preparing', jobId: entry.jobId, startedAt: entry.startedAt };
      resume.push([id, entry.jobId, entry.startedAt]);
    } else {
      jobs[id] = { state: 'lost' };
    }
  }
  return { jobs, resume };
}

// Saved data is untrusted input. Any whole-record failure discards it (and the key); a bad row
// or job only drops that item. Returns null when there is nothing usable.
function readSaved() {
  try {
    const raw = sessionStorage.getItem(SAVED_SEARCH_KEY);
    if (raw === null) return null;
    const rec = JSON.parse(raw);
    const ok =
      isPlainObject(rec) &&
      rec.v === SAVED_SEARCH_VERSION &&
      (rec.type === 'film' || rec.type === 'serie') &&
      typeof rec.q === 'string' &&
      rec.q.length <= MAX_QUERY &&
      typeof rec.search_id === 'string' &&
      ID.test(rec.search_id) &&
      typeof rec.done === 'boolean' &&
      (rec.outcome === null || rec.outcome === 'empty' || rec.outcome === 'timeout') &&
      Array.isArray(rec.rows) &&
      rec.rows.length <= MAX_ROWS &&
      isPlainObject(rec.jobs);
    if (!ok) {
      clearSavedSearch();
      return null;
    }
    const { jobs, resume } = restoreJobs(rec.jobs, Date.now());
    return {
      type: rec.type,
      q: rec.q,
      search_id: rec.search_id,
      done: rec.done,
      outcome: rec.outcome,
      rows: rec.rows.filter(validRow).map(pickRow),
      jobs,
      resume,
    };
  } catch {
    clearSavedSearch(); // unreadable JSON, or storage that throws (the removal is then a no-op)
    return null;
  }
}

function downloadErrorState(err) {
  if (err instanceof ApiError) {
    if (err.status === 410) return 'expired';
    if (err.status === 503) return 'notReady';
    if (err.status === 0) return 'network';
  }
  return 'failed';
}

// Only MSG strings ever reach the screen: no status code, JSON or raw backend text.
function searchErrorMessage(err) {
  if (err instanceof ApiError) {
    if (err.status === 401) return ''; // the App shows the login screen
    if (err.status === 503) return MSG.notReady;
    if (err.status === 422) return MSG.queryTooShort;
    if (err.status === 0) return MSG.serverUnreachable;
    // D-39: one calm sentence; no countdown, no Retry-After value, no status code.
    if (err.status === 429) return MSG.throttled;
  }
  return MSG.searchFailed;
}

// One search at a time. Polling runs only while the latest snapshot is not done;
// a new search or an unmount bumps `runId`, which stops the previous loop.
export function Search() {
  const [type, setType] = useState('film');
  const [q, setQ] = useState('');
  const [rows, setRows] = useState([]);
  const [searching, setSearching] = useState(false);
  const [outcome, setOutcome] = useState(null); // null | 'empty' | 'timeout'
  const [error, setError] = useState('');
  const runId = useRef(0);
  const timer = useRef(null);
  // Row state map keyed by result_id: survives re-sorted snapshots. The ref is the
  // synchronous source of truth for the double-tap guard; the state only triggers renders.
  const [jobs, setJobs] = useState({});
  const jobsRef = useRef({});
  const jobTimers = useRef(new Map());
  const jobEpoch = useRef(0);
  const rowsType = useRef('film'); // type of the search that produced the rows on screen
  // The search on screen as it is saved: {type, q, search_id, done, outcome, rows}, null before one.
  const saved = useRef(null);
  const savedGen = useRef(generation);

  function persist() {
    if (saved.current === null) return;
    writeSaved(savedGen.current, { v: SAVED_SEARCH_VERSION, ...saved.current, jobs: jobsRef.current });
  }

  function stopPolling() {
    runId.current += 1;
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }

  function setJob(id, entry) {
    jobsRef.current = { ...jobsRef.current, [id]: entry };
    setJobs(jobsRef.current);
    persist();
  }

  function stopJobs() {
    jobEpoch.current += 1;
    for (const t of jobTimers.current.values()) clearTimeout(t);
    jobTimers.current.clear();
    jobsRef.current = {};
    setJobs({});
  }

  useEffect(
    () => () => {
      stopPolling();
      jobEpoch.current += 1;
      for (const t of jobTimers.current.values()) clearTimeout(t);
      jobTimers.current.clear();
    },
    [],
  );

  // Restore after a reload. In an effect, not in render, so no timer starts during render.
  // The unmount cleanup above never clears storage: a reload is an unmount.
  useEffect(() => {
    const rec = readSaved();
    if (rec === null) return;
    savedGen.current = generation;
    rowsType.current = rec.type;
    saved.current = {
      type: rec.type,
      q: rec.q,
      search_id: rec.search_id,
      done: rec.done,
      outcome: rec.done && rec.rows.length === 0 ? rec.outcome : null,
      rows: rec.rows,
    };
    setType(rec.type);
    setQ(rec.q);
    setRows(rec.rows);
    setOutcome(saved.current.outcome);
    jobsRef.current = rec.jobs;
    setJobs(jobsRef.current);
    for (const [id, jobId, startedAt] of rec.resume) pollJob(id, jobEpoch.current, jobId, startedAt);
    if (!rec.done) {
      setSearching(true);
      poll(runId.current, rec.search_id);
    }
    persist(); // mapped states (lost) stick
  }, []);

  // Maps a backend job answer to a row state and keeps polling while it is preparing.
  function applyJob(id, epoch, res, startedAt) {
    const status = res && JOB_STATES.has(res.status) ? res.status : 'failed';
    if (status !== 'preparing') {
      setJob(id, { state: status });
      return;
    }
    const jobId = res.job_id;
    setJob(id, { state: 'preparing', jobId, startedAt });
    if (typeof jobId === 'string') pollJob(id, epoch, jobId, startedAt);
  }

  function pollJob(id, epoch, jobId, startedAt) {
    const t = setTimeout(async () => {
      jobTimers.current.delete(id);
      if (epoch !== jobEpoch.current) return;
      try {
        const res = await api(`/api/download/${jobId}`);
        if (epoch !== jobEpoch.current) return;
        if (res && res.status !== 'preparing') {
          applyJob(id, epoch, res, startedAt);
          return;
        }
      } catch (err) {
        if (epoch !== jobEpoch.current) return;
        if (err instanceof ApiError && err.status === 401) return; // the login screen takes over
        if (err instanceof ApiError && err.status === 404) {
          // The backend forgot the job (it restarted). Asking again will not help, but a new tap
          // will: the server finds the torrent again and finishes or reports it (WR-05).
          setJob(id, { state: 'lost' });
          return;
        }
        // Anything else (network blip, 5xx) keeps the row on "Preparing" and retries.
      }
      if (Date.now() - startedAt < JOB_GIVE_UP_MS) pollJob(id, epoch, jobId, startedAt);
      else setJob(id, { state: 'lost' }); // never leave a row on "Preparing" for good (WR-05)
    }, JOB_POLL_MS);
    jobTimers.current.set(id, t);
  }

  async function download(result) {
    const id = result.result_id;
    const current = jobsRef.current[id];
    if (current && !RETRYABLE.has(current.state)) return;
    const epoch = jobEpoch.current;
    setJob(id, { state: 'pending' });
    try {
      // Exactly {result_id, type}: the backend owns every other decision (SEC-03).
      const res = await api('/api/download', {
        method: 'POST',
        body: { result_id: id, type: rowsType.current },
      });
      if (epoch !== jobEpoch.current) return;
      applyJob(id, epoch, res, Date.now());
    } catch (err) {
      if (epoch !== jobEpoch.current) return;
      setJob(id, { state: downloadErrorState(err) });
    }
  }

  async function submit(event) {
    event.preventDefault();
    stopPolling();
    stopJobs();
    clearSavedSearch(); // a new search always starts from an empty record
    savedGen.current = generation;
    saved.current = null;
    const run = runId.current;
    const searchType = type;
    const query = q;
    rowsType.current = searchType;
    setRows([]);
    setOutcome(null);
    setError('');
    setSearching(true);
    try {
      const { search_id: searchId } = await api('/api/search', {
        method: 'POST',
        body: { q, type: searchType },
      });
      if (run !== runId.current) return;
      saved.current = {
        type: searchType,
        q: query,
        search_id: searchId,
        done: false,
        outcome: null,
        rows: [],
      };
      persist();
      poll(run, searchId);
    } catch (err) {
      fail(run, err);
    }
  }

  function fail(run, err) {
    if (run !== runId.current) return;
    setSearching(false);
    setError(searchErrorMessage(err));
  }

  function poll(run, searchId) {
    timer.current = setTimeout(async () => {
      timer.current = null;
      if (run !== runId.current) return;
      try {
        const snap = await api(`/api/search/${searchId}`);
        if (run !== runId.current) return;
        setRows(snap.results);
        let result = null;
        if (snap.done) {
          setSearching(false);
          if (snap.results.length === 0) {
            result = snap.timed_out ? 'timeout' : 'empty';
            setOutcome(result);
          }
        }
        if (saved.current !== null) {
          saved.current = { ...saved.current, rows: snap.results.map(pickRow), done: !!snap.done, outcome: result };
          persist();
        }
        if (!snap.done) poll(run, searchId);
      } catch (err) {
        fail(run, err);
      }
    }, POLL_MS);
  }

  return (
    <section class="search">
      <form class="search-form" onSubmit={submit}>
        <div class="type-toggle" role="radiogroup">
          <label class="type-option">
            <input
              type="radio"
              name="type"
              value="film"
              checked={type === 'film'}
              onChange={() => setType('film')}
            />
            <span>{MSG.typeFilm}</span>
          </label>
          <label class="type-option">
            <input
              type="radio"
              name="type"
              value="serie"
              checked={type === 'serie'}
              onChange={() => setType('serie')}
            />
            <span>{MSG.typeSerie}</span>
          </label>
        </div>
        <input
          class="query"
          type="search"
          value={q}
          placeholder={MSG.queryPlaceholder}
          aria-label={MSG.queryPlaceholder}
          onInput={(e) => setQ(e.currentTarget.value)}
        />
        <button class="btn btn-primary" type="submit">
          {MSG.searchButton}
        </button>
      </form>
      {error && (
        <p class="form-error" role="alert">
          {error}
        </p>
      )}
      {searching && (
        <p class="searching" role="status">
          <span class="spinner" aria-hidden="true" /> {MSG.searching}
        </p>
      )}
      {outcome === 'empty' && <p class="status">{MSG.noResults}</p>}
      {outcome === 'timeout' && <p class="status">{MSG.searchTimedOut}</p>}
      <ul class="results">
        {rows.map((r) => (
          <ResultRow
            key={r.result_id}
            result={r}
            state={jobs[r.result_id]?.state}
            onDownload={download}
          />
        ))}
      </ul>
    </section>
  );
}
