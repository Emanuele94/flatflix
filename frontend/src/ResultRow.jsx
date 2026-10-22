import { MSG } from './messages.js';

// One search result. Names are attacker-controlled text: only ever rendered as text children.
export function ResultRow({ result }) {
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
    </li>
  );
}
