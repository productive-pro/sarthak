/**
 * useChatSessions — fetches and manages the sessions list
 * separately from the runtime so the runtime stays pure.
 */
import { useState, useCallback, useEffect } from 'react';
import { api } from '../api';
import { useStore } from '../store';

export function useChatSessions() {
  const [sessions, setSessions] = useState([]);
  const { err } = useStore();

  const refresh = useCallback(async () => {
    try {
      const r = await api('/chat/sessions');
      setSessions(r.sessions || (Array.isArray(r) ? r : []));
    } catch { /* silent */ }
  }, []);

  // Initial load: use promise chain so setState is in a callback, not inline
  useEffect(() => {
    let cancelled = false;
    api('/chat/sessions')
      .then(r => { if (!cancelled) setSessions(r.sessions || (Array.isArray(r) ? r : [])); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const deleteSession = useCallback(async (sid) => {
    try {
      await api(`/chat/sessions/${sid}`, { method: 'DELETE' });
      refresh();
    } catch (e) { err(e.message); }
  }, [refresh, err]);

  return { sessions, refresh, deleteSession };
}
