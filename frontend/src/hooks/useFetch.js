import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useStore } from '../store';

export default function useFetch(path, deps = [], opts = {}) {
  const errFn = useStore(s => s.err);
  const {
    enabled = true,
    initialData = null,
    // Default to true only if there's a path to fetch; avoids spurious loading spinners
    initialLoading = !!(path && enabled),
    transform,
  } = opts;

  // Stable refs so callbacks are never recreated due to prop/fn identity changes
  const transformRef = useRef(transform);
  transformRef.current = transform;
  const errRef = useRef(errFn);
  errRef.current = errFn;

  const [data, setData] = useState(initialData);
  const [loading, setLoading] = useState(initialLoading);
  const [error, setError] = useState(null);

  // Stringify deps so useCallback dependency array is stable
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const depsKey = deps.map(d => (d === null || d === undefined ? '' : String(d))).join('|');

  const abortRef = useRef(null);

  const load = useCallback(async () => {
    if (!enabled || !path) return;
    // Cancel any in-flight request before starting a new one
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    try {
      const res = await api(path, { signal: controller.signal });
      const out = transformRef.current ? transformRef.current(res) : res;
      setData(out);
      setError(null);
    } catch (e) {
      if (e.name === 'AbortError') return; // cancelled — ignore
      setError(e);
      errRef.current(e.message);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, enabled, depsKey]);

  useEffect(() => {
    load();
  }, [load]);

  return { data, loading, error, reload: load, setData };
}
