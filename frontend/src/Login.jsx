import { useState } from 'preact/hooks';
import { api, ApiError } from './api.js';
import { MSG } from './messages.js';

// Only MSG strings ever reach the screen: no status code, JSON or English text.
function loginErrorMessage(err) {
  if (err instanceof ApiError) {
    if (err.status === 401) return MSG.loginFailed;
    if (err.status === 429) return MSG.loginThrottled;
  }
  return MSG.serverUnreachable;
}

// The password lives only in component state until submit, then is cleared.
// It is never written to browser web storage; the session is the HttpOnly cookie.
export function Login({ onLoggedIn }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    const body = { username, password };
    setPassword('');
    try {
      await api('/api/login', { method: 'POST', body });
      onLoggedIn();
    } catch (err) {
      setError(loginErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main class="app">
      <h1>{MSG.loginTitle}</h1>
      {error && (
        <p class="form-error" role="alert">
          {error}
        </p>
      )}
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
