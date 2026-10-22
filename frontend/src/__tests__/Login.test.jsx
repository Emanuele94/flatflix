import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/preact';
import { Login } from '../Login.jsx';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('Login form', () => {
  it('posts exactly {username, password} and calls onLoggedIn on success', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 204, json: async () => null }));
    vi.stubGlobal('fetch', fetchMock);
    const onLoggedIn = vi.fn();
    render(<Login onLoggedIn={onLoggedIn} />);

    fireEvent.input(screen.getByLabelText('Nome utente'), { target: { value: 'casa' } });
    fireEvent.input(screen.getByLabelText('Password'), { target: { value: 'segreta' } });
    fireEvent.click(screen.getByRole('button', { name: 'Entra' }));

    await waitFor(() => expect(onLoggedIn).toHaveBeenCalledTimes(1));
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe('/api/login');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ username: 'casa', password: 'segreta' });
  });

  async function submitWith(fetchImpl) {
    vi.stubGlobal('fetch', vi.fn(fetchImpl));
    const onLoggedIn = vi.fn();
    const { container } = render(<Login onLoggedIn={onLoggedIn} />);
    fireEvent.input(screen.getByLabelText('Nome utente'), { target: { value: 'casa' } });
    fireEvent.input(screen.getByLabelText('Password'), { target: { value: 'sbagliata' } });
    fireEvent.click(screen.getByRole('button', { name: 'Entra' }));
    return { onLoggedIn, container };
  }

  it('shows the Italian wrong-credentials message on 401 and nothing technical', async () => {
    const { onLoggedIn, container } = await submitWith(async () => ({
      ok: false,
      status: 401,
      json: async () => ({ detail: 'bad_credentials' }),
    }));
    expect(await screen.findByText('Nome utente o password errati.')).toBeTruthy();
    expect(onLoggedIn).not.toHaveBeenCalled();
    expect(container.textContent).not.toMatch(/401|bad_credentials|detail|\{/);
  });

  it('shows the throttled message on 429', async () => {
    const { container } = await submitWith(async () => ({
      ok: false,
      status: 429,
      json: async () => ({ detail: 'too_many_attempts' }),
    }));
    expect(await screen.findByText('Troppi tentativi. Riprova tra qualche minuto.')).toBeTruthy();
    expect(container.textContent).not.toMatch(/429|too_many_attempts/);
  });

  it('shows the unreachable message on a network failure', async () => {
    await submitWith(async () => {
      throw new TypeError('Failed to fetch');
    });
    expect(
      await screen.findByText('Server non raggiungibile. Controlla che il computer sia acceso.'),
    ).toBeTruthy();
  });

  it('clears the password field after submit', async () => {
    await submitWith(async () => ({
      ok: false,
      status: 401,
      json: async () => ({ detail: 'bad_credentials' }),
    }));
    await screen.findByText('Nome utente o password errati.');
    expect(screen.getByLabelText('Password').value).toBe('');
  });
});
