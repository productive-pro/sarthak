/** api.js — thin fetch wrapper + format re-exports for one-stop imports. */

export async function api(path, opts = {}) {
  const url = path.startsWith('/api') ? path : `/api/${path.replace(/^\//, '')}`;
  // Don't force JSON Content-Type when sending FormData — let browser set multipart boundary
  const isFormData = opts.body instanceof FormData;
  const headers = isFormData
    ? { ...opts.headers }
    : { 'Content-Type': 'application/json', ...opts.headers };
  const res = await fetch(url, { headers, ...opts });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    let msg = `HTTP ${res.status}`;
    try { const j = JSON.parse(text); msg = j.detail || j.message || msg; } catch {}
    throw new Error(msg);
  }
  const ct = res.headers.get('content-type') || '';
  if (!ct.includes('application/json')) return {};
  return res.json().catch(() => ({}));
}

// Re-export format helpers so callers can do: import { api, fmt, fmtDur } from '../api'
export { fmt, fmtDur, nowTs, fmtNum } from './utils/format';
