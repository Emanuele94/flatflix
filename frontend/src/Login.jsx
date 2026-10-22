import { useState } from 'preact/hooks';
import { api } from './api.js';
import { MSG } from './messages.js';

// The password lives only in component state until submit, then is cleared.
// It is never written to browser web storage; the session is the HttpOnly cookie.
export function Login({ onLoggedIn }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    const body = { username, password };
    setPassword('');
    try {
      await api('/api/login', { method: 'POST', body });
      onLoggedIn();
    } catch {
      // Failure messages are added in the next task.
    } finally {
      setBusy(false);
    }
  }

  return (
    <main class="app">
      <h1>{MSG.loginTitle}</h1>
      <form class="login-form" onSubmit={submit}>
        <label class="field">
          <span>{MSG.username}</span>
          <input
            type="text"
            name="username"
            autocomplete="username"
            value={username}
            onInput={(e) => setUsername(e.currentTarget.value)}
            required
          />
        </label>
        <label class="field">
          <span>{MSG.password}</span>
          <input
            type="password"
            name="password"
            autocomplete="current-password"
            value={password}
            onInput={(e) => setPassword(e.currentTarget.value)}
            required
          />
        </label>
        <button class="btn btn-primary" type="submit" disabled={busy}>
          {MSG.loginButton}
        </button>
      </form>
    </main>
  );
}
