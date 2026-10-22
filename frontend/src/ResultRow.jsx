import { useState } from 'preact/hooks';
import { api } from './api.js';
import { MSG } from './messages.js';

// One search result. Names are attacker-controlled text: only ever rendered as text children.
// Tracer: the row posts only {result_id, type}; the backend owns everything else.
export function ResultRow({ result, type }) {
  const [started, setStarted] = useState(false);

  async function download() {
    try {
      const res = await api('/api/download', {
        method: 'POST',
        body: { result_id: result.result_id, type },
      });
      if (res && res.status === 'started') setStarted(true);
    } catch {
      // Other outcomes are handled by the row states.
    }
  }

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
      {started ? (
        <span class="row-state row-state-ok">{MSG.started}</span>
      ) : (
        <button class="btn btn-primary" type="button" onClick={download}>
          {MSG.download}
        </button>
      )}
    </li>
  );
}
