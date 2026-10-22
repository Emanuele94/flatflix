// One search result. Names are attacker-controlled text: only ever rendered as text children.
export function ResultRow({ result }) {
  return (
    <li class="result">
      <div class="result-name">{result.name}</div>
      <div class="result-main">
        <span>{result.size_human}</span> <span>{result.seeders}</span>
      </div>
    </li>
  );
}
