import { useState, useEffect, useCallback } from 'react';
import { Spinner } from '../components/ui';
import { api } from '../api';
import { useStore } from '../store';

export default function Config() {
  const [content, setContent] = useState('');
  const [path, setPath]       = useState('');
  const [dirty, setDirty]     = useState(false);
  const [loading, setLoading] = useState(true);
  const { ok, err } = useStore();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api('/config');
      setContent(r.content || '');
      setPath(r.path || '');
      setDirty(false);
    } catch (e) { err(e.message); }
    setLoading(false);
  }, [err]); // err is stable from Zustand

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    try {
      await api('/config', { method: 'PUT', body: JSON.stringify({ content }) });
      ok('Config saved'); setDirty(false);
    } catch (e) { err(e.message); }
  };

  const handleChange = (e) => { setContent(e.target.value); setDirty(true); };
  const handleKeyDown = (e) => { if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); save(); } };

  return (
    <div className="page">
      <header className="pg-header">
        <div className="pg-title-group">
          <h1 className="pg-title">Config</h1>
          {path && <p className="pg-sub mono" style={{ fontSize: 11 }}>{path}</p>}
        </div>
        <div className="pg-actions">
          {dirty && <span className="dirty-badge">Unsaved</span>}
          <button className="btn btn-muted btn-sm" onClick={load}>Reload</button>
          <button className="btn btn-accent btn-sm" onClick={save} disabled={!dirty}>Save</button>
        </div>
      </header>

      <div className="pg-body" style={{ display: 'flex', flexDirection: 'column', padding: '16px 24px' }}>
        {loading ? (
          <Spinner />
        ) : (
          <textarea
            className="config-editor"
            value={content}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            spellCheck={false}
          />
        )}
      </div>
    </div>
  );
}
