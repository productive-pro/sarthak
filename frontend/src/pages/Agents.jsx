import { useState } from 'react';
import { api } from '../api';
import { fmt } from '../utils/format';
import { useStore } from '../store';
import Modal from '../components/Modal';
import { Spinner } from '../components/ui';
import useFetch from '../hooks/useFetch';

export default function Agents() {
  const [showCreate, setShowCreate] = useState(false);
  const [desc, setDesc]     = useState('');
  const [tg, setTg]         = useState(false);
  const [logsModal, setLogsModal] = useState(null);
  const [runModal, setRunModal]   = useState(null);
  const { ok, err } = useStore();

  const { data: agents = [], loading, reload } = useFetch('/agents', [], {
    initialData: [],
  });

  const create = async () => {
    if (!desc.trim()) { err('Describe what the agent should do'); return; }
    try {
      await api('/agents', { method: 'POST', body: JSON.stringify({ description: desc, notify_telegram: tg }) });
      ok('Agent created'); setShowCreate(false); setDesc(''); setTg(false); reload();
    } catch (e) { err(e.message); }
  };

  const toggleAgent = async (id, enabled) => {
    try {
      await api(`/agents/${id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !enabled }) });
      ok(enabled ? 'Agent paused' : 'Agent enabled'); reload();
    } catch (e) { err(e.message); }
  };

  const runAgent = async (id) => {
    setRunModal({ loading: true, output: '' });
    try {
      const r = await api(`/agents/${id}/run`, { method: 'POST' });
      const out = typeof r === 'string' ? r : (r?.output || r?.result || JSON.stringify(r, null, 2));
      setRunModal({ loading: false, output: out });
    } catch (e) { setRunModal({ loading: false, output: e.message }); }
  };

  const viewLogs = async (agent) => {
    const aid = agent.agent_id || agent.id;
    setLogsModal({ title: agent.name || aid, loading: true, logs: [] });
    try {
      const r = await api(`/agents/${aid}/logs`);
      setLogsModal({ title: agent.name || aid, loading: false, logs: Array.isArray(r) ? r : r.logs ?? [] });
    } catch (e) { setLogsModal({ title: agent.name || aid, loading: false, logs: [], error: e.message }); }
  };

  const deleteAgent = async (id) => {
    if (!confirm('Delete this agent?')) return;
    try { await api(`/agents/${id}`, { method: 'DELETE' }); ok('Agent deleted'); reload(); }
    catch (e) { err(e.message); }
  };

  return (
    <div className="page">
      <header className="pg-header">
        <div className="pg-title-group">
          <h1 className="pg-title">Agents</h1>
          <p className="pg-sub">Scheduled automation agents</p>
        </div>
        <div className="pg-actions">
          <button className="btn btn-accent btn-sm" onClick={() => setShowCreate(true)}>+ New Agent</button>
        </div>
      </header>

      <div className="pg-body">
        {loading ? (
          <Spinner />
        ) : agents.length === 0 ? (
          <div className="empty">
            <div className="empty-ttl">No agents yet</div>
            <div className="empty-desc">Create an agent to automate recurring tasks.</div>
            <button className="btn btn-accent btn-sm" style={{ marginTop: 12 }} onClick={() => setShowCreate(true)}>Create First Agent</button>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {agents.map(a => (
              <AgentCard
                key={a.agent_id || a.id}
                agent={a}
                onToggle={() => toggleAgent(a.agent_id || a.id, a.enabled)}
                onRun={() => runAgent(a.agent_id || a.id)}
                onLogs={() => viewLogs(a)}
                onDelete={() => deleteAgent(a.agent_id || a.id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Create modal */}
      {showCreate && (
        <Modal title="Create Agent" onClose={() => setShowCreate(false)} footer={
          <>
            <button className="btn btn-muted btn-sm" onClick={() => { setShowCreate(false); setDesc(''); setTg(false); }}>Cancel</button>
            <button className="btn btn-accent btn-sm" onClick={create}>Create Agent</button>
          </>
        }>
          <div>
            <label className="form-label">Describe what this agent should do *</label>
            <textarea className="s-textarea" rows={4} value={desc} onChange={e => setDesc(e.target.value)}
              placeholder={'e.g. "Every morning at 9am, summarise top AI news and send to Telegram"'} />
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--txt2)', cursor: 'pointer' }}>
            <input type="checkbox" checked={tg} onChange={e => setTg(e.target.checked)} />
            Send results to Telegram
          </label>
        </Modal>
      )}

      {/* Logs modal */}
      {logsModal && (
        <Modal title={`Logs — ${logsModal.title}`} onClose={() => setLogsModal(null)}>
          {logsModal.loading ? (
            <Spinner />
          ) : logsModal.error ? (
            <div style={{ color: 'var(--red)', fontSize: 13 }}>{logsModal.error}</div>
          ) : logsModal.logs.length === 0 ? (
            <div style={{ color: 'var(--txt3)', fontSize: 13 }}>No runs yet.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {logsModal.logs.slice(0, 10).map((l, i) => (
                <div key={i} className="card">
                  <div className="card-hdr">
                    <span style={{ fontSize: 11, color: 'var(--txt3)' }}>{fmt(l.ts || l.ran_at)}</span>
                    <span style={{ fontSize: 11, color: l.success ? 'var(--accent)' : 'var(--red)' }}>
                      {l.success ? '✓ success' : '✗ failed'}
                    </span>
                  </div>
                  {l.output && (
                    <pre style={{ margin: 0, fontSize: 11.5, color: 'var(--txt2)', whiteSpace: 'pre-wrap', padding: '10px 18px', maxHeight: 200, overflow: 'auto' }}>
                      {l.output}
                    </pre>
                  )}
                </div>
              ))}
            </div>
          )}
        </Modal>
      )}

      {/* Run output modal */}
      {runModal && (
        <Modal title="Run Output" onClose={() => setRunModal(null)}>
          {runModal.loading
            ? <Spinner />
            : <pre className="code-block" style={{ maxHeight: 420, overflow: 'auto', margin: 0 }}>{runModal.output}</pre>}
        </Modal>
      )}
    </div>
  );
}

function AgentCard({ agent: a, onToggle, onRun, onLogs, onDelete }) {
  return (
    <div className="agent-card">
      <div className="card-hdr">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1, minWidth: 0 }}>
          <span style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--txt)' }}>
            {a.name || `Agent ${(a.agent_id || a.id || '').slice(0, 8)}`}
          </span>
          {a.schedule && (
            <span style={{ fontFamily: 'var(--mono)', fontSize: 11, background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 4, padding: '1px 7px', display: 'inline-block', color: 'var(--txt3)', width: 'fit-content' }}>
              {a.schedule}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <span className="badge" style={{ fontSize: 11, color: a.enabled ? 'var(--accent)' : 'var(--txt3)', background: a.enabled ? 'var(--accent-dim)' : 'var(--surface2)', border: `1px solid ${a.enabled ? 'var(--accent-border)' : 'var(--brd)'}` }}>
            {a.enabled ? 'active' : 'paused'}
          </span>
          <button className="btn btn-muted btn-xs" onClick={onToggle}>{a.enabled ? 'Pause' : 'Enable'}</button>
          <button className="btn btn-muted btn-xs" onClick={onRun}>Run</button>
          <button className="btn btn-muted btn-xs" onClick={onLogs}>Logs</button>
          <button className="btn btn-del btn-xs" onClick={onDelete}>Delete</button>
        </div>
      </div>
      {(a.description || a.task) && (
        <div style={{ padding: '8px 18px 10px', fontSize: 12.5, color: 'var(--txt2)', lineHeight: 1.5 }}>
          {a.description || a.task}
        </div>
      )}
      {a.tools?.length > 0 && (
        <div style={{ padding: '0 18px 10px', display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {a.tools.map(t => <span key={t} className="badge badge-muted" style={{ fontSize: 10.5 }}>{t}</span>)}
        </div>
      )}
      {(a.last_run_at || a.last_run) && (
        <div style={{ padding: '0 18px 8px', fontSize: 11, color: 'var(--txt3)' }}>Last run: {fmt(a.last_run_at || a.last_run)}</div>
      )}
    </div>
  );
}
