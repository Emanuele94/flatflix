// Same-origin JSON fetch wrapper. Caddy serves the SPA and proxies /api/*.
export class ApiError extends Error {
  constructor(status, code) {
    super(code);
    this.name = 'ApiError';
    this.status = status; // 0 for a network failure
    this.code = code; // backend `detail` string, or "network"
  }
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
    throw new ApiError(res.status, detail);
  }
  return data;
}
