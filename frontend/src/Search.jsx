import { useEffect, useRef, useState } from 'preact/hooks';
import { api } from './api.js';
import { MSG } from './messages.js';
import { ResultRow } from './ResultRow.jsx';

const POLL_MS = 700;

// One search at a time. Polling runs only while the latest snapshot is not done;
// a new search or an unmount bumps `runId`, which stops the previous loop.
export function Search() {
  const [type, setType] = useState('film');
  const [q, setQ] = useState('');
  const [rows, setRows] = useState([]);
  const [searching, setSearching] = useState(false);
  const runId = useRef(0);
  const timer = useRef(null);

  function stopPolling() {
    runId.current += 1;
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }

  useEffect(() => stopPolling, []);

  async function submit(event) {
    event.preventDefault();
    stopPolling();
    const run = runId.current;
    const searchType = type;
    setRows([]);
    setSearching(true);
    try {
      const { search_id: searchId } = await api('/api/search', {
        method: 'POST',
        body: { q, type: searchType },
      });
      if (run !== runId.current) return;
      poll(run, searchId);
    } catch {
      if (run === runId.current) setSearching(false);
    }
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
        } else {
          poll(run, searchId);
        }
      } catch {
        if (run === runId.current) setSearching(false);
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
      <ul class="results">
        {rows.map((r) => (
          <ResultRow key={r.result_id} result={r} type={type} />
        ))}
      </ul>
    </section>
  );
}
