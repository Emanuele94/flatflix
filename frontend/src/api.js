// Same-origin JSON fetch wrapper. Caddy serves the SPA and proxies /api/*.
export class ApiError extends Error {
  constructor(status, code) {
    super(code);
    this.name = 'ApiError';
    this.status = status; // 0 for a network failure
    this.code = code; // backend `detail` string, or "network"
  }
}

let unauthorizedHandler = null;

// App registers a callback that runs on any 401 except the login call itself.
export function setUnauthorizedHandler(fn) {
  unauthorizedHandler = typeof fn === 'function' ? fn : null;
}

export async function api(path, { method = 'GET', body } = {}) {
  const init = { method, credentials: 'same-origin', headers: {} };
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, 'network');
  }

  if (res.status === 204) return null;

  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }

  if (!res.ok) {
    const detail = data && typeof data.detail === 'string' ? data.detail : 'error';
    if (res.status === 401 && path !== '/api/login' && unauthorizedHandler) unauthorizedHandler();
    throw new ApiError(res.status, detail);
  }
  return data;
}
