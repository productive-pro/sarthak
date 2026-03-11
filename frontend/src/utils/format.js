export function fmt(iso) {
  if (iso === null || iso === undefined || iso === '') return '';
  try {
    // Handle Unix timestamps (seconds or milliseconds)
    const d = typeof iso === 'number'
      ? new Date(iso < 1e12 ? iso * 1000 : iso)
      : new Date(iso);
    if (isNaN(d)) return String(iso);
    const now = new Date();
    const diff = (now - d) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
    return d.toLocaleDateString();
  } catch { return iso; }
}

export function fmtDur(min) {
  if (!min && min !== 0) return '';
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60), m = min % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

export function nowTs() {
  return new Date().toISOString();
}

/** Format a number with locale-aware thousand separators (e.g. 1000 → "1,000"). */
export function fmtNum(n, fallback = '—') {
  if (n === null || n === undefined || isNaN(n)) return fallback;
  return Number(n).toLocaleString();
}
