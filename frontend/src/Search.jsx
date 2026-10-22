import { useEffect, useRef, useState } from 'preact/hooks';
import { api, ApiError } from './api.js';
import { MSG } from './messages.js';
import { ResultRow } from './ResultRow.jsx';

const POLL_MS = 700;
const JOB_POLL_MS = 2000; // D-11: ask the backend about a preparing job every 2 s
const JOB_GIVE_UP_MS = 330000; // METADATA_TIMEOUT is 5 min; stop asking after 5.5 min

// A row in one of these states can be tapped again; every other state ignores taps.
const RETRYABLE = new Set(['failed', 'notReady', 'network']);
// Backend job statuses that map to a row state. Anything else is a failure, never a success.
const JOB_STATES = new Set(['started', 'preparing', 'rejected', 'unavailable', 'duplicate', 'failed']);

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

  // Maps a backend job answer to a row state and keeps polling while it is preparing.
  function applyJob(id, epoch, res, startedAt) {
    const status = res && JOB_STATES.has(res.status) ? res.status : 'failed';
    if (status !== 'preparing') {
      setJob(id, { state: status });
      return;
    }
    const jobId = res.job_id;
    setJob(id, { state: 'preparing', jobId });
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
        // The job is unknown or the session is gone: asking again will not help.
        if (err instanceof ApiError && (err.status === 404 || err.status === 401)) return;
        // Anything else (network blip, 5xx) keeps the row on "Preparing" and retries.
      }
      if (Date.now() - startedAt < JOB_GIVE_UP_MS) pollJob(id, epoch, jobId, startedAt);
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
    const run = runId.current;
    const searchType = type;
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
        if (snap.done) {
          setSearching(false);
          if (snap.results.length === 0) setOutcome(snap.timed_out ? 'timeout' : 'empty');
        } else {
          poll(run, searchId);
        }
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
