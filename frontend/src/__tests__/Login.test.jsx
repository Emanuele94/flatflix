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
});
