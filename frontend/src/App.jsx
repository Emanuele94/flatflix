import { useEffect, useState } from 'preact/hooks';
import { api, ApiError } from './api.js';
import { MSG } from './messages.js';

export function App() {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    let alive = true;
    api('/api/health')
      .then((data) => {
        if (alive) setStatus(data && data.status === 'ok' ? 'ok' : 'degraded');
      })
      .catch((err) => {
        if (!alive) return;
        setStatus(err instanceof ApiError ? 'unreachable' : 'degraded');
      });
    return () => {
      alive = false;
    };
  }, []);

  let text = '';
  if (status === 'ok') text = MSG.healthOk;
  else if (status === 'degraded') text = MSG.healthDegraded;
  else if (status === 'unreachable') text = MSG.serverUnreachable;

  return (
    <main class="app">
      <h1>{MSG.appTitle}</h1>
      <p class="status">{text}</p>
    </main>
  );
}
