import { useEffect, useState } from 'preact/hooks';
import { api, ApiError, setUnauthorizedHandler } from './api.js';
import { Login } from './Login.jsx';
import { MSG } from './messages.js';
import { Search } from './Search.jsx';

export function App() {
  // checking | login | in
  const [view, setView] = useState('checking');
  const [health, setHealth] = useState(null);

  useEffect(() => {
    setUnauthorizedHandler(() => setView('login'));
    return () => setUnauthorizedHandler(null);
  }, []);

  async function logout() {
    try {
      await api('/api/logout', { method: 'POST' });
    } catch {
      // Whatever happened, the user asked to leave: show the login screen.
    }
    setView('login');
  }

  useEffect(() => {
    let alive = true;
    api('/api/session')
      .then(() => {
        if (alive) setView('in');
      })
      .catch((err) => {
        if (!alive) return;
        if (err instanceof ApiError && err.status === 0) setHealth('unreachable');
        setView('login');
      });
    api('/api/health')
      .then((data) => {
        if (alive && !(data && data.status === 'ok')) setHealth('degraded');
      })
      .catch((err) => {
        if (!alive) return;
        setHealth(err instanceof ApiError && err.status === 0 ? 'unreachable' : 'degraded');
      });
    return () => {
      alive = false;
    };
  }, []);

  let banner = null;
  if (health === 'degraded') banner = MSG.healthDegraded;
  else if (health === 'unreachable') banner = MSG.serverUnreachable;

  let content = null;
  if (view === 'login') {
    content = <Login onLoggedIn={() => setView('in')} />;
  } else if (view === 'in') {
    content = (
      <>
        <header class="app-header">
          <h1>{MSG.appTitle}</h1>
          <button class="btn" type="button" onClick={logout}>
            {MSG.logout}
          </button>
        </header>
        <main class="app">
          <Search />
        </main>
      </>
    );
  }

  return (
    <>
      {banner && (
        <p class="banner" role="status">
          {banner}
        </p>
      )}
      {content}
    </>
  );
}
