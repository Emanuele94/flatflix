import { useEffect, useRef, useState } from 'preact/hooks';
import { api, ApiError, setUnauthorizedHandler } from './api.js';
import { Downloads, clearDownloadsCache } from './Downloads.jsx';
import { Login } from './Login.jsx';
import { MSG } from './messages.js';
import { Search, clearSavedSearch } from './Search.jsx';

export function App() {
  // checking | login | in
  const [view, setView] = useState('checking');
  const [health, setHealth] = useState(null);
  // search | downloads. In memory only: after a reload Search is shown (D-26).
  const [tab, setTab] = useState('search');
  const tabRefs = { search: useRef(null), downloads: useRef(null) };

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setTab('search');
      setView('login');
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  async function logout() {
    // First, so the saved search is gone even if /api/logout hangs (G-01-3). A session that merely
    // expires (401) does not clear it: the same person logs in again and finds her search.
    clearSavedSearch();
    clearDownloadsCache();
    try {
      await api('/api/logout', { method: 'POST' });
    } catch {
      // Whatever happened, the user asked to leave: show the login screen.
    }
    setTab('search');
    setView('login');
  }

  function selectTab(name) {
    setTab(name);
    tabRefs[name].current?.focus();
  }

  function onTabKeyDown(e) {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      selectTab(tab === 'search' ? 'downloads' : 'search');
    } else if (e.key === 'Home') {
      e.preventDefault();
      selectTab('search');
    } else if (e.key === 'End') {
      e.preventDefault();
      selectTab('downloads');
    }
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
    content = (
      <Login
        onLoggedIn={() => {
          setTab('search');
          setView('in');
        }}
      />
    );
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
          <div class="tabs" role="tablist">
            <button
              ref={tabRefs.search}
              class="tab"
              type="button"
              role="tab"
              id="tab-search"
              aria-controls="panel-search"
              aria-selected={tab === 'search' ? 'true' : 'false'}
              tabIndex={tab === 'search' ? 0 : -1}
              onClick={() => setTab('search')}
              onKeyDown={onTabKeyDown}
            >
              {MSG.tabSearch}
            </button>
            <button
              ref={tabRefs.downloads}
              class="tab"
              type="button"
              role="tab"
              id="tab-downloads"
              aria-controls="panel-downloads"
              aria-selected={tab === 'downloads' ? 'true' : 'false'}
              tabIndex={tab === 'downloads' ? 0 : -1}
              onClick={() => setTab('downloads')}
              onKeyDown={onTabKeyDown}
            >
              {MSG.tabDownloads}
            </button>
          </div>
          <section
            id="panel-search"
            role="tabpanel"
            aria-labelledby="tab-search"
            hidden={tab !== 'search'}
          >
            <Search />
          </section>
          <section
            id="panel-downloads"
            role="tabpanel"
            aria-labelledby="tab-downloads"
            hidden={tab !== 'downloads'}
          >
            {tab === 'downloads' && <Downloads onGoToSearch={() => setTab('search')} />}
          </section>
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
