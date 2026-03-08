import { useEffect, useMemo, useRef, useState } from 'react';
import Overlay from '../components/Overlay';
import MarkdownEditor from '../components/MarkdownEditor';
import ForceGraph from '../components/ForceGraph';
import Modal from '../components/Modal';
import { api, fmt } from '../api';
import { useStore } from '../store';
import { useResizable } from '../hooks/useResizable';



export default function PanelHost({ panel, onClose, space, spaceId, spaceRoadmap, refreshHero }) {
  if (!panel) return null;
  const { name } = panel;
  if (name === 'notes') return (
    <SpaceNotesPanel space={space} spaceId={spaceId} onClose={onClose} />
  );
  if (name === 'tasks') return (
    <TaskManagerPanel space={space} onClose={onClose} />
  );
  if (name === 'files') return (
    <FilesPanel space={space} spaceId={spaceId} spaceRoadmap={spaceRoadmap} onClose={onClose} />
  );
  if (name === 'rag') return (
    <RagPanel space={space} spaceId={spaceId} onClose={onClose} />
  );
  if (name === 'srs') return (
    <SRSPanel spaceId={spaceId} onClose={onClose} />
  );
  if (name === 'graph') return (
    <GraphPanel spaceId={spaceId} spaceRoadmap={spaceRoadmap} onClose={onClose} />
  );
  if (name === 'digest') return (
    <DigestPanel space={space} spaceId={spaceId} onClose={onClose} />
  );
  if (name === 'practice') return (
    <PracticeTestPanel space={space} spaceId={spaceId} onClose={onClose} refreshHero={refreshHero} />
  );
  if (name === 'optimizer') return (
    <OptimizerPanel spaceId={spaceId} onClose={onClose} />
  );
  if (name === 'agents') return (
    <SpaceAgentsPanel space={space} spaceId={spaceId} onClose={onClose} />
  );
  return null;
}

function SpaceNotesPanel({ space, spaceId, onClose }) {
  const [notes, setNotes] = useState([]);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(null);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [mode, setMode] = useState('empty'); // empty | view | new
  const [listWidth, onListDrag] = useResizable('notes-panel-list-width', 240, 140, 460);

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      try {
        const r = await api(`/spaces/${spaceId}/notes?type=note`);
        if (!mounted) return;
        const list = Array.isArray(r) ? r : r.notes || [];
        setNotes(list);
      } catch {}
      setLoading(false);
    })();
    return () => { mounted = false; };
  }, [spaceId]);

  const filtered = useMemo(() => {
    if (!query.trim()) return notes;
    const q = query.toLowerCase();
    return notes.filter(n =>
      (n.title || '').toLowerCase().includes(q) ||
      (n.body_md || '').toLowerCase().includes(q)
    );
  }, [notes, query]);

  const openNote = (n) => {
    setSelected(n);
    setTitle(n.title || '');
    setBody(n.body_md || '');
    setMode('view');
  };

  const openNew = () => {
    setSelected(null);
    setTitle('');
    setBody('');
    setMode('new');
  };

  const save = async () => {
    setSaving(true);
    try {
      if (mode === 'new') {
        const saved = await api(`/spaces/${spaceId}/notes`, {
          method: 'POST',
          body: JSON.stringify({ title: title || 'Untitled', body_md: body || '', type: 'general' }),
        });
        setNotes(n => [saved, ...n]);
        openNote(saved);
      } else if (selected) {
        await api(`/spaces/${spaceId}/notes/${selected.id}`, {
          method: 'PUT',
          body: JSON.stringify({ title: title || 'Untitled', body_md: body || '' }),
        });
        setNotes(n => n.map(x => x.id === selected.id ? { ...x, title: title || 'Untitled', body_md: body || '' } : x));
      }
    } catch {}
    setSaving(false);
  };

  const del = async () => {
    if (!selected) return;
    if (!confirm('Delete this note?')) return;
    try {
      await api(`/spaces/${spaceId}/notes/${selected.id}`, { method: 'DELETE' });
      setNotes(n => n.filter(x => x.id !== selected.id));
      setSelected(null);
      setMode('empty');
    } catch {}
  };

  return (
    <Overlay title={`Notes — ${space?.name || ''}`} width="76%" height="88%" onClose={onClose} bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div className="pane-header" style={{ padding: '10px 16px', borderBottom: '1px solid var(--brd)', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--txt)' }}>Space Notes</span>
            <span style={{ fontSize: 10, color: 'var(--txt3)' }}>{notes.length} notes</span>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input className="s-input" placeholder="Search notes…" style={{ width: 180, fontSize: 12, padding: '4px 10px' }}
              value={query} onChange={e => setQuery(e.target.value)} />
            <button className="btn btn-accent btn-sm" onClick={openNew}>+ New Note</button>
          </div>
        </div>
      </div>
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
        <div style={{ width: listWidth, flexShrink: 0, borderRight: '1px solid var(--brd)', overflow: 'hidden', position: 'relative', display: 'flex', flexDirection: 'column' }}>
          {/* Drag handle on right edge */}
          <div
            onMouseDown={onListDrag}
            style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: 5, cursor: 'col-resize', zIndex: 10, background: 'transparent', transition: 'background 150ms' }}
            onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent-border)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
          />
          <div style={{ flex: 1, overflowY: 'auto', padding: '8px 6px', display: 'flex', flexDirection: 'column', gap: 4 }}>
            {loading ? (
              <div className="loading-center"><span className="spin" /></div>
            ) : filtered.length === 0 ? (
              <div style={{ padding: '24px 12px', textAlign: 'center', color: 'var(--txt3)', fontSize: 12 }}>No notes yet.</div>
            ) : filtered.map(n => (
              <button key={n.id} onClick={() => openNote(n)} className={`sn-row${selected?.id === n.id ? ' active' : ''}`}>
                <div className="sn-title">{n.title || '(untitled)'}</div>
                <div className="sn-meta">{fmt(n.created_at)}</div>
                {(n.body_md || '').slice(0, 60) && <div className="sn-body">{(n.body_md || '').slice(0, 60)}</div>}
              </button>
            ))}
          </div>
        </div>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0 }}>
          {mode === 'empty' ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--txt3)', fontSize: 13 }}>Select a note or create a new one</div>
          ) : (
            <>
              <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--brd)', display: 'flex', alignItems: 'center', gap: 10 }}>
                <input className="s-input" value={title} onChange={e => setTitle(e.target.value)}
                  placeholder="Note title…" style={{ flex: 1, fontSize: 13.5, fontWeight: 600, borderColor: 'transparent', background: 'none', padding: '4px 6px' }}
                  onFocus={e => { e.target.style.borderColor = 'var(--brd2)'; e.target.style.background = 'var(--surface2)'; }}
                  onBlur={e => { e.target.style.borderColor = 'transparent'; e.target.style.background = 'none'; }} />
                <span style={{ fontSize: 10.5, color: 'var(--txt3)' }}>{selected?.created_at ? fmt(selected.created_at) : ''}</span>
                <button className="btn btn-accent btn-sm" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
                {selected && <button className="btn btn-muted btn-sm" style={{ color: '#f87171', borderColor: '#f8717133' }} onClick={del}>Delete</button>}
              </div>
              <div style={{ flex: 1, overflow: 'hidden', minHeight: 0 }}>
                <MarkdownEditor value={body} onChange={setBody} onSave={save} placeholder="Write markdown notes…"
                  historyKey={`space-notes:${spaceId}:${selected?.id || 'new'}`} />
              </div>
            </>
          )}
        </div>
      </div>
    </Overlay>
  );
}


function SpaceAgentsPanel({ space, spaceId, onClose }) {
  const [agents, setAgents]       = useState([]);
  const [loading, setLoading]     = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [desc, setDesc]           = useState('');
  const [tg, setTg]               = useState(false);
  const [runModal, setRunModal]   = useState(null);
  const [logsModal, setLogsModal] = useState(null);
  const { ok, err } = useStore();

  useEffect(() => { load(); }, [spaceId]);

  const load = async () => {
    setLoading(true);
    const r = await api(`/spaces/${spaceId}/agents`).catch(() => []);
    setAgents(Array.isArray(r) ? r : []);
    setLoading(false);
  };

  const create = async () => {
    if (!desc.trim()) { err('Describe what the agent should do'); return; }
    await api(`/spaces/${spaceId}/agents`, { method: 'POST', body: JSON.stringify({ description: desc, notify_telegram: tg }) })
      .then(() => { ok('Agent created'); setShowCreate(false); setDesc(''); setTg(false); load(); })
      .catch(e => err(e.message));
  };

  const toggle = async (id, enabled) => {
    await api(`/agents/${id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !enabled }) })
      .then(() => { ok(enabled ? 'Paused' : 'Enabled'); load(); })
      .catch(e => err(e.message));
  };

  const runAgent = async (id) => {
    setRunModal({ loading: true, output: '' });
    const r = await api(`/agents/${id}/run`, { method: 'POST' })
      .catch(e => ({ output: e.message }));
    setRunModal({ loading: false, output: r.output || r.result || JSON.stringify(r, null, 2) });
  };

  const viewLogs = async (agent) => {
    setLogsModal({ title: agent.name || agent.agent_id, loading: true, logs: [] });
    const r = await api(`/agents/${agent.agent_id}/logs`).catch(() => []);
    setLogsModal({ title: agent.name || agent.agent_id, loading: false, logs: Array.isArray(r) ? r : r?.logs ?? [] });
  };

  const del = async (id) => {
    if (!confirm('Delete this agent?')) return;
    await api(`/agents/${id}`, { method: 'DELETE' })
      .then(() => { ok('Agent deleted'); load(); })
      .catch(e => err(e.message));
  };

  return (
    <>
      <Overlay title={`Space Agents — ${space?.name || ''}`} width="68%" height="80%" onClose={onClose}
        bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--brd)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
          <span style={{ fontSize: 12, color: 'var(--txt3)' }}>Agents scoped to this space</span>
          <button className="btn btn-accent btn-sm" onClick={() => setShowCreate(true)}>+ New Agent</button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          {loading ? (
            <div className="loading-center"><span className="spin" /></div>
          ) : agents.length === 0 ? (
            <div className="empty">
              <div className="empty-ttl">No space agents yet</div>
              <div className="empty-desc">Create agents that run in the context of this space.</div>
              <button className="btn btn-accent btn-sm" style={{ marginTop: 12 }} onClick={() => setShowCreate(true)}>Create Agent</button>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {agents.map(a => (
                <div key={a.agent_id} className="agent-card">
                  <div className="card-hdr">
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--txt)' }}>{a.name || `Agent ${(a.agent_id || '').slice(0, 8)}`}</span>
                      {a.schedule && <code style={{ fontSize: 11, background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 4, padding: '1px 7px', marginLeft: 8, color: 'var(--txt3)' }}>{a.schedule}</code>}
                    </div>
                    <div style={{ display: 'flex', gap: 5, flexShrink: 0 }}>
                      <span className="badge" style={{ fontSize: 11, color: a.enabled ? 'var(--accent)' : 'var(--txt3)' }}>{a.enabled ? 'active' : 'paused'}</span>
                      <button className="btn btn-muted btn-xs" onClick={() => toggle(a.agent_id, a.enabled)}>{a.enabled ? 'Pause' : 'Enable'}</button>
                      <button className="btn btn-muted btn-xs" onClick={() => runAgent(a.agent_id)}>Run</button>
                      <button className="btn btn-muted btn-xs" onClick={() => viewLogs(a)}>Logs</button>
                      <button className="btn btn-del btn-xs" onClick={() => del(a.agent_id)}>Delete</button>
                    </div>
                  </div>
                  {a.description && <div style={{ padding: '6px 18px 10px', fontSize: 12.5, color: 'var(--txt2)' }}>{a.description}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      </Overlay>

      {showCreate && (
        <Modal title="Create Space Agent" onClose={() => setShowCreate(false)} footer={
          <>
            <button className="btn btn-muted btn-sm" onClick={() => setShowCreate(false)}>Cancel</button>
            <button className="btn btn-accent btn-sm" onClick={create}>Create</button>
          </>
        }>
          <div>
            <label className="form-label">Describe what this agent should do *</label>
            <textarea className="s-textarea" rows={4} value={desc} onChange={e => setDesc(e.target.value)}
              placeholder={`e.g. "Every week, summarise my progress in ${space?.name || 'this space'} and list what to study next"`} />
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--txt2)', cursor: 'pointer' }}>
            <input type="checkbox" checked={tg} onChange={e => setTg(e.target.checked)} />
            Send results to Telegram
          </label>
        </Modal>
      )}

      {runModal && (
        <Modal title="Run Output" onClose={() => setRunModal(null)}>
          {runModal.loading
            ? <div className="loading-center"><span className="spin" /></div>
            : <pre className="code-block" style={{ maxHeight: 420, overflow: 'auto', margin: 0 }}>{runModal.output}</pre>}
        </Modal>
      )}

      {logsModal && (
        <Modal title={`Logs — ${logsModal.title}`} onClose={() => setLogsModal(null)}>
          {logsModal.loading ? (
            <div className="loading-center"><span className="spin" /></div>
          ) : logsModal.logs.length === 0 ? (
            <div style={{ color: 'var(--txt3)', fontSize: 13 }}>No runs yet.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {logsModal.logs.slice(0, 10).map((l, i) => (
                <div key={i} className="card">
                  <div className="card-hdr">
                    <span style={{ fontSize: 11, color: 'var(--txt3)' }}>{fmt(l.ts || l.ran_at || l.started_at)}</span>
                    <span style={{ fontSize: 11, color: l.success ? 'var(--accent)' : 'var(--red)' }}>{l.success ? 'success' : 'failed'}</span>
                  </div>
                  {l.output && <pre style={{ margin: 0, fontSize: 11.5, color: 'var(--txt2)', whiteSpace: 'pre-wrap', padding: '8px 18px', maxHeight: 180, overflow: 'auto' }}>{l.output}</pre>}
                </div>
              ))}
            </div>
          )}
        </Modal>
      )}
    </>
  );
}

function TaskManagerPanel({ space, onClose }) {
  const key = `tasks:${space?.name || ''}`;
  const load = () => { try { return JSON.parse(localStorage.getItem(key) || '[]'); } catch { return []; } };
  const [tasks, setTasks] = useState(load());
  const [title, setTitle] = useState('');
  const [priority, setPriority] = useState('medium');

  const save = (next) => { localStorage.setItem(key, JSON.stringify(next)); setTasks(next); };

  const add = () => {
    if (!title.trim()) return;
    const next = [{ id: Date.now().toString(36), title: title.trim(), done: false, priority, created_at: new Date().toISOString().slice(0, 10) }, ...tasks];
    setTitle('');
    save(next);
  };

  const toggle = (id, done) => save(tasks.map(t => t.id === id ? { ...t, done } : t));
  const del = (id) => save(tasks.filter(t => t.id !== id));

  const active = tasks.filter(t => !t.done).length;
  const doneCount = tasks.filter(t => t.done).length;

  return (
    <Overlay title="Task Manager" width="50%" height="72%" onClose={onClose} bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--brd)' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input className="s-input" placeholder="New task…" value={title} onChange={e => setTitle(e.target.value)} onKeyDown={e => e.key === 'Enter' && add()} />
          <select className="s-select" style={{ width: 100 }} value={priority} onChange={e => setPriority(e.target.value)}>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="low">Low</option>
          </select>
          <button className="btn btn-accent btn-sm" onClick={add}>Add</button>
        </div>
        <div style={{ fontSize: 11, color: 'var(--txt3)', marginTop: 8 }}>{active} active · {doneCount} done</div>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
        {tasks.length === 0 ? (
          <div style={{ padding: '24px 0', textAlign: 'center', color: 'var(--txt3)', fontSize: 12 }}>No tasks yet. Add one above.</div>
        ) : tasks.map(t => (
          <div key={t.id} className={`task-row${t.done ? ' task-done' : ''}`}>
            <input type="checkbox" checked={t.done} onChange={e => toggle(t.id, e.target.checked)} />
            <div className="task-title" data-priority={t.priority}>{t.title}</div>
            <span className="task-date">{t.created_at}</span>
            <button className="tb-btn task-del" onClick={() => del(t.id)}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/></svg>
            </button>
          </div>
        ))}
      </div>
    </Overlay>
  );
}

function DigestPanel({ space, spaceId, onClose }) {
  const [subscribed, setSubscribed] = useState(false);
  const [digest, setDigest]         = useState('');
  const [loading, setLoading]       = useState(false);
  const [sending, setSending]       = useState(false);
  const { ok, err } = useStore();

  useEffect(() => {
    if (!spaceId) return;
    let mounted = true;
    (async () => {
      setLoading(true);
      try {
        // Load subscribe state and digest in parallel
        const [sub, r] = await Promise.all([
          api(`/spaces/${spaceId}/digest/subscribe`),
          api(`/spaces/${spaceId}/digest`),
        ]);
        if (!mounted) return;
        setSubscribed(!!sub.subscribed);
        setDigest(r.digest || 'No digest available.');
      } catch {}
      setLoading(false);
    })();
    return () => { mounted = false; };
  }, [spaceId]);

  const toggle = async (val) => {
    setSubscribed(val);
    try {
      await api(`/spaces/${spaceId}/digest/subscribe`, {
        method: 'POST',
        body: JSON.stringify({ subscribed: val }),
      });
      ok(val ? 'Subscribed to daily digest' : 'Unsubscribed from digest');
    } catch (e) { err(e.message); setSubscribed(!val); }
  };

  const sendNow = async () => {
    setSending(true);
    try {
      await api(`/spaces/${spaceId}/digest?send_telegram=true&refresh=false`);
      ok('Digest sent to Telegram');
    } catch (e) { err(e.message); }
    setSending(false);
  };

  return (
    <Overlay title="Daily Digest" width="58%" height="72%" onClose={onClose} bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}>
      {/* Telegram subscribe toggle */}
      <div className="digest-toggle-wrap" style={{ flexShrink: 0 }}>
        <label className="toggle-switch">
          <input type="checkbox" checked={subscribed} onChange={e => toggle(e.target.checked)} />
          <span className="toggle-slider" />
        </label>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--txt)' }}>Daily Digest via Telegram</div>
          <div style={{ fontSize: 11.5, color: 'var(--txt3)' }}>{subscribed ? 'Subscribed — digest will be sent today' : 'Off — no digest will be sent today'}</div>
        </div>
      </div>

      {/* Scrollable digest body */}
      <div style={{ flex: 1, overflow: 'hidden', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        {loading ? (
          <div className="loading-center" style={{ padding: 40 }}><span className="spin" /> Loading digest…</div>
        ) : (
          <MarkdownEditor value={digest} readOnly defaultMode="read" />
        )}
      </div>

      {/* Footer actions */}
      <div style={{ padding: '10px 14px', borderTop: '1px solid var(--brd)', display: 'flex', gap: 6, flexShrink: 0, background: 'var(--surface)' }}>
        <button className="btn btn-muted btn-sm" onClick={() => navigator.clipboard.writeText(digest || '')}>Copy</button>
        <button className="btn btn-muted btn-sm" onClick={sendNow} disabled={sending}>{sending ? 'Sending…' : 'Send to Telegram'}</button>
      </div>
    </Overlay>
  );
}

function SRSPanel({ spaceId, onClose }) {
  const [cards, setCards] = useState([]);
  const [loading, setLoading] = useState(false);
  const [idx, setIdx] = useState(0);
  const [showAnswer, setShowAnswer] = useState(false);

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      try {
        // Use concept-based SRS endpoint (returns due concepts from roadmap)
        const r = await api(`/spaces/${spaceId}/srs`);
        if (mounted) setCards(r.due || []);
      } catch {}
      setLoading(false);
    })();
    return () => { mounted = false; };
  }, [spaceId]);

  const grade = async (conceptId, rating) => {
    try {
      await api(`/spaces/${spaceId}/srs/rate`, { method: 'POST', body: JSON.stringify({ concept_id: conceptId, rating }) });
      setIdx(i => i + 1);
      setShowAnswer(false);
    } catch {}
  };

  const card = cards[idx];

  return (
    <Overlay title="SRS — Due for Review" width="55%" height="65%" onClose={onClose}>
      {loading ? (
        <div className="loading-center"><span className="spin" /></div>
      ) : cards.length === 0 ? (
        <div className="empty">
          <div className="empty-ttl">All caught up!</div>
          <div className="empty-desc">No cards due today.</div>
        </div>
      ) : idx >= cards.length ? (
        <div className="empty">
          <div className="empty-ttl">Review done!</div>
          <div className="empty-desc">{cards.length} card(s) reviewed.</div>
        </div>
      ) : (
        <>
          <div style={{ fontSize: 11.5, color: 'var(--txt3)', marginBottom: 8 }}>Card {idx + 1}/{cards.length} · interval {card.interval}d · due {card.due_date || 'today'}</div>
          <div className="s-card">
            <div className="s-card-hdr" style={{ fontSize: 11, color: 'var(--txt3)' }}>{card.chapter_title} / {card.topic_title}</div>
            <div className="s-card-body" style={{ fontSize: 14, fontWeight: 600, color: 'var(--txt)' }}>{card.title}</div>
          </div>
          {showAnswer && (
            <div style={{ marginTop: 12 }}>
              {card.description && (
                <div className="s-card" style={{ marginBottom: 12 }}>
                  <div className="s-card-hdr">Description</div>
                  <div className="s-card-body">
                    <div style={{ fontSize: 13, color: 'var(--txt2)', lineHeight: 1.6 }}>{card.description}</div>
                  </div>
                </div>
              )}
              <div style={{ marginTop: 8 }}>
                <div style={{ fontSize: 12, color: 'var(--txt3)', marginBottom: 8 }}>How well did you recall? (1=forgot · 5=perfect)</div>
                <div style={{ display: 'flex', gap: 8 }}>
                  {[1,2,3,4,5].map(g => (
                    <button key={g} className="btn btn-muted btn-sm" style={{ flex: 1, fontWeight: 700 }} onClick={() => grade(card.id, g)}>{g}</button>
                  ))}
                </div>
              </div>
            </div>
          )}
          {!showAnswer && (
            <button className="btn btn-accent btn-sm" style={{ marginTop: 12 }} onClick={() => setShowAnswer(true)}>Show Answer</button>
          )}
        </>
      )}
    </Overlay>
  );
}

function FilesPanel({ space, spaceId, spaceRoadmap, onClose }) {
  // ── right-pane tab ───────────────────────────────────────────────
  const [rightTab, setRightTab]         = useState('index'); // 'index' | 'search' | 'chat'

  // ── file walk state ──────────────────────────────────────────────
  const [allFiles, setAllFiles]         = useState([]);   // [{path, size, indexed}]
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [stats, setStats]               = useState({ total: 0, indexed: 0, chunks: 0 });

  // ── selection state ──────────────────────────────────────────────
  const [selected, setSelected]         = useState(new Set()); // Set<rel_path>

  // ── indexing state ───────────────────────────────────────────────
  const [indexing, setIndexing]         = useState(false);
  const [indexStatus, setIndexStatus]   = useState(null); // null | {file, file_index, total_files, chunks_so_far, done, ...}
  const sseRef                          = useRef(null);

  // ── drag-to-index state ──────────────────────────────────────────
  const [dragOver, setDragOver]         = useState(false);
  const [uploading, setUploading]       = useState(false);
  const [uploadStatus, setUploadStatus] = useState(null); // null | {name, done, error}

  // ── UI state ────────────────────────────────────────────────────
  const [pipeline, setPipeline]         = useState('text'); // 'text' | 'vision'
  const [showIndexed, setShowIndexed]   = useState(false);
  const [treeFilter, setTreeFilter]     = useState('');
  const [ragQuery, setRagQuery]         = useState('');
  const [ragResults, setRagResults]     = useState([]);
  const [ragLoading, setRagLoading]     = useState(false);
  const [fileViewer, setFileViewer]     = useState(null);
  const [noteSeed, setNoteSeed]         = useState(null);

  // ── chat state ───────────────────────────────────────────────────
  const [chatHistory, setChatHistory]   = useState([]);
  const [chatInput, setChatInput]       = useState('');
  const [chatLoading, setChatLoading]   = useState(false);
  const chatEndRef                      = useRef(null);

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [chatHistory]);

  const doChat = async () => {
    const q = chatInput.trim();
    if (!q || chatLoading) return;
    setChatInput('');
    setChatHistory(h => [...h, { role: 'user', content: q }]);
    setChatLoading(true);
    try {
      const r = await api(`/spaces/${spaceId}/rag/chat`, {
        method: 'POST',
        body: JSON.stringify({ question: q, history: chatHistory.slice(-8), top_k: 5 }),
      });
      setChatHistory(h => [...h, { role: 'assistant', content: r.answer, sources: r.sources || [] }]);
    } catch (e) {
      setChatHistory(h => [...h, { role: 'assistant', content: `Error: ${e.message}`, sources: [] }]);
    }
    setChatLoading(false);
  };

  // cleanup SSE on unmount
  useEffect(() => () => { sseRef.current?.abort?.(); }, []);

  // ── load workspace files ─────────────────────────────────────────
  useEffect(() => { loadWalk(); }, [spaceId]);

  const loadWalk = async () => {
    setLoadingFiles(true);
    try {
      const r = await api(`/spaces/${spaceId}/rag/walk`);
      setAllFiles(r.files || []);
      setStats({ total: r.total_files || 0, indexed: r.indexed_files || 0, chunks: r.indexed_chunks || 0 });
    } catch {
      try {
        const r = await api(`/spaces/${spaceId}/rag/files`);
        const files = (r.files || []).map(f => ({ path: f.path, size: 0, indexed: true }));
        setAllFiles(files);
        setStats({ total: files.length, indexed: r.indexed_files || files.length, chunks: r.indexed_chunks || 0 });
      } catch {}
    }
    setLoadingFiles(false);
  };

  // ── selection helpers ────────────────────────────────────────────
  const visibleFiles = showIndexed ? allFiles.filter(f => f.indexed) : allFiles;
  const allPaths     = visibleFiles.map(f => f.path);

  const toggleFile = (path) => setSelected(prev => {
    const next = new Set(prev);
    next.has(path) ? next.delete(path) : next.add(path);
    return next;
  });

  const toggleFolder = (prefix, files) => {
    const inFolder = files.filter(f => f.path.startsWith(prefix)).map(f => f.path);
    const allIn    = inFolder.every(p => selected.has(p));
    setSelected(prev => {
      const next = new Set(prev);
      inFolder.forEach(p => allIn ? next.delete(p) : next.add(p));
      return next;
    });
  };

  const selectAll  = () => setSelected(new Set(allPaths));
  const selectNone = () => setSelected(new Set());
  const selCount   = selected.size;

  // ── SSE streaming indexer ────────────────────────────────────────
  const doIndex = async () => {
    if (indexing) return;
    const paths = selCount > 0 ? [...selected] : allPaths;
    if (paths.length === 0) return;

    setIndexing(true);
    setIndexStatus({ file: '', file_index: 0, total_files: paths.length, chunks_so_far: 0, done: false });

    const ctrl = new AbortController();
    sseRef.current = ctrl;

    try {
      const res = await fetch(`/api/spaces/${spaceId}/rag/index-paths/stream`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ paths, pipeline }),
        signal:  ctrl.signal,
      });

      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let   buf     = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        // SSE lines: "data: {...}\n\n"
        const parts = buf.split('\n\n');
        buf = parts.pop() ?? '';
        for (const part of parts) {
          const line = part.replace(/^data:\s*/, '').trim();
          if (!line) continue;
          try {
            const evt = JSON.parse(line);
            setIndexStatus(evt);
            if (evt.done) {
              setStats({ total: allFiles.length, indexed: evt.indexed_files || 0, chunks: evt.indexed_chunks || 0 });
              await loadWalk();
            }
          } catch {}
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setIndexStatus(s => ({ ...s, done: true, error: err?.message || 'Failed' }));
      }
    }
    setIndexing(false);
  };

  const cancelIndex = () => {
    sseRef.current?.abort?.();
    setIndexing(false);
    setIndexStatus(s => s ? { ...s, done: true, error: 'Cancelled' } : null);
  };

  // ── activity export then index ───────────────────────────────────
  const doExportAndIndex = async () => {
    try {
      const r = await api(`/spaces/${spaceId}/rag/export-activities`, { method: 'POST' });
      if (r.paths?.length) {
        // Index exported paths immediately
        setIndexing(true);
        setIndexStatus({ file: '', file_index: 0, total_files: r.paths.length, chunks_so_far: 0, done: false });
        const res = await fetch(`/api/spaces/${spaceId}/rag/index-paths/stream`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ paths: r.paths, pipeline }),
        });
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const parts = buf.split('\n\n');
          buf = parts.pop() ?? '';
          for (const part of parts) {
            const line = part.replace(/^data:\s*/, '').trim();
            if (!line) continue;
            try { const evt = JSON.parse(line); setIndexStatus(evt); if (evt.done) await loadWalk(); } catch {}
          }
        }
        setIndexing(false);
      }
    } catch {}
  };

  // ── drag-to-index ────────────────────────────────────────────────
  const onDragEnter = (e) => { e.preventDefault(); setDragOver(true); };
  const onDragLeave = (e) => { if (!e.currentTarget.contains(e.relatedTarget)) setDragOver(false); };
  const onDragOver  = (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; };

  const onDrop = async (e) => {
    e.preventDefault();
    setDragOver(false);
    const files = [...e.dataTransfer.files];
    if (!files.length) return;
    setUploading(true);
    for (const file of files) {
      setUploadStatus({ name: file.name, done: false });
      try {
        const form = new FormData();
        form.append('file', file);
        const res = await fetch(`/api/spaces/${spaceId}/rag/upload?pipeline=${pipeline}`, {
          method: 'POST',
          body: form,
        });
        if (!res.ok) throw new Error(await res.text());
        const r = await res.json();
        setUploadStatus({ name: file.name, done: true, chunks: r.chunks_indexed });
        setStats(s => ({ ...s, indexed: r.indexed_files || s.indexed, chunks: r.indexed_chunks || s.chunks }));
        await loadWalk();
      } catch (err) {
        setUploadStatus({ name: file.name, done: true, error: err?.message || 'Upload failed' });
      }
    }
    setUploading(false);
    setTimeout(() => setUploadStatus(null), 3000);
  };

  // ── search (RAG + activity blend) ────────────────────────────────
  const doSearch = async () => {
    if (!ragQuery.trim()) return;
    setRagLoading(true);
    try {
      const [ragR, actR] = await Promise.allSettled([
        api(`/spaces/${spaceId}/rag/search`, { method: 'POST', body: JSON.stringify({ query: ragQuery, top_k: 6 }) }),
        api(`/activity?space_dir=${encodeURIComponent(space?.directory || '')}&days=90&limit=50`),
      ]);
      const ragRes  = ragR.status === 'fulfilled' ? (ragR.value.results || []) : [];
      const actItems = actR.status === 'fulfilled' ? (Array.isArray(actR.value) ? actR.value : []) : [];
      const q        = ragQuery.toLowerCase();
      const actHits  = actItems
        .filter(a => (a.content_text || '').toLowerCase().includes(q))
        .slice(0, 4)
        .map(a => ({
          source:      `[${a.activity_type}] ${a.concept_title || ''}`,
          line:        0,
          score:       0.7,
          text:        (a.content_text || '').slice(0, 300),
          is_activity: true,
        }));
      setRagResults([...ragRes, ...actHits]);
    } catch {}
    setRagLoading(false);
  };

  // ── derived display values ────────────────────────────────────────
  const indexedSet    = useMemo(() => new Set(allFiles.filter(f => f.indexed).map(f => f.path)), [allFiles]);
  const filteredFiles = useMemo(() => {
    const base = showIndexed ? allFiles.filter(f => f.indexed) : allFiles;
    if (!treeFilter.trim()) return base;
    const q = treeFilter.toLowerCase();
    return base.filter(f => f.path.toLowerCase().includes(q));
  }, [allFiles, showIndexed, treeFilter]);

  const indexPct = indexStatus
    ? indexStatus.done ? 100 : Math.min(Math.round(((indexStatus.file_index || 0) / Math.max(indexStatus.total_files || 1, 1)) * 85), 85)
    : null;
  const currentFile = indexStatus?.file ? indexStatus.file.split('/').pop() : '';

  return (
    <>
      <Overlay
        title="Workspace"
        width="82%"
        height="88%"
        onClose={onClose}
        bodyStyle={{ display: 'flex', flexDirection: 'column', padding: 0, overflow: 'hidden' }}
      >
        <div style={{ display: 'flex', flex: 1, overflow: 'hidden', minHeight: 0 }}>

          {/* ── LEFT: folder file browser ─────────────────────────── */}
          <div
            style={{ flex: '0 0 62%', display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--brd)', overflow: 'hidden', position: 'relative' }}
            onDragEnter={onDragEnter}
            onDragLeave={onDragLeave}
            onDragOver={onDragOver}
            onDrop={onDrop}
          >
            {/* drop overlay */}
            {dragOver && (
              <div style={{ position: 'absolute', inset: 0, zIndex: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,.55)', border: '2px dashed var(--accent)', borderRadius: 6, pointerEvents: 'none' }}>
                <span style={{ fontSize: 14, color: 'var(--accent)', fontWeight: 600 }}>Drop to upload &amp; index</span>
              </div>
            )}

            {/* filter bar */}
            <div style={{ padding: '10px 12px 8px', borderBottom: '1px solid var(--brd)', display: 'flex', gap: 6, alignItems: 'center' }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0, opacity: 0.4 }}><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              <input
                className="s-input"
                placeholder="Filter files…"
                value={treeFilter}
                onChange={e => setTreeFilter(e.target.value)}
                style={{ flex: 1, border: 'none', background: 'transparent', padding: '2px 0', fontSize: 12.5 }}
              />
              {treeFilter && (
                <button className="btn-ghost btn btn-xs" onClick={() => setTreeFilter('')} style={{ padding: '2px 6px', fontSize: 11 }}>✕</button>
              )}
            </div>

            {/* browser body */}
            {loadingFiles ? (
              <div className="loading-center" style={{ flex: 1 }}><span className="spin" /></div>
            ) : filteredFiles.length === 0 ? (
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8, color: 'var(--txt3)', padding: 24 }}>
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ opacity: 0.3 }}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
                <div style={{ fontSize: 12.5, textAlign: 'center' }}>
                  {treeFilter ? 'No files match filter.' : 'No indexable files found.\nDrop files here to upload and index.'}
                </div>
              </div>
            ) : (
              <div style={{ flex: 1, overflowY: 'auto' }}>
                <FolderBrowser
                  files={filteredFiles}
                  selected={selected}
                  indexedSet={indexedSet}
                  onToggleFile={toggleFile}
                  onToggleFolder={toggleFolder}
                  onOpen={(path) => setFileViewer({ path })}
                />
              </div>
            )}

            {/* upload status bar */}
            {uploadStatus && (
              <div style={{ padding: '6px 12px', fontSize: 11.5, borderTop: '1px solid var(--brd)', color: uploadStatus.error ? '#f87171' : 'var(--txt3)', flexShrink: 0 }}>
                {uploadStatus.error
                  ? `Failed: ${uploadStatus.name} — ${uploadStatus.error}`
                  : uploadStatus.done
                    ? `Indexed: ${uploadStatus.name} · ${uploadStatus.chunks || 0} chunks`
                    : `Uploading ${uploadStatus.name}…`}
              </div>
            )}

            {/* hint */}
            <div style={{ padding: '5px 12px', fontSize: 10.5, color: 'var(--txt4, var(--txt3))', borderTop: '1px solid var(--brd)', flexShrink: 0 }}>
              Drop files anywhere here to upload &amp; index them immediately
            </div>
          </div>

          {/* ── RIGHT: tabbed panel ────────────────────────────────── */}
          <div style={{ flex: '0 0 38%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

            {/* tab bar */}
            <div style={{ display: 'flex', borderBottom: '1px solid var(--brd)', flexShrink: 0 }}>
              {[['index', 'Index'], ['search', 'Search'], ['chat', 'Chat']].map(([id, label]) => (
                <button
                  key={id}
                  onClick={() => setRightTab(id)}
                  style={{
                    flex: 1, padding: '9px 0', fontSize: 12, fontWeight: rightTab === id ? 600 : 400,
                    background: 'transparent', border: 'none', borderBottom: rightTab === id ? '2px solid var(--accent)' : '2px solid transparent',
                    color: rightTab === id ? 'var(--accent)' : 'var(--txt3)', cursor: 'pointer', transition: 'color 120ms',
                  }}
                >
                  {label}
                </button>
              ))}
            </div>

            {/* ── Tab: Index ── */}
            {rightTab === 'index' && (
              <div style={{ flex: 1, overflowY: 'auto', padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 14 }}>
                {/* stats */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
                  <div style={{ background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 6, padding: '8px 10px', textAlign: 'center' }}>
                    <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--txt)' }}>{stats.total}</div>
                    <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginTop: 1 }}>files</div>
                  </div>
                  <div style={{ background: 'var(--surface2)', border: '1px solid var(--accent-border)', borderRadius: 6, padding: '8px 10px', textAlign: 'center' }}>
                    <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--accent)' }}>{stats.indexed}</div>
                    <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginTop: 1 }}>indexed</div>
                  </div>
                  <div style={{ background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 6, padding: '8px 10px', textAlign: 'center' }}>
                    <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--txt)' }}>{stats.chunks}</div>
                    <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginTop: 1 }}>chunks</div>
                  </div>
                </div>

                {/* selection row */}
                <div style={{ display: 'flex', gap: 5 }}>
                  <button className="btn btn-muted btn-sm" style={{ flex: 1 }} onClick={selectAll} disabled={loadingFiles}>All</button>
                  <button className="btn btn-muted btn-sm" style={{ flex: 1 }} onClick={selectNone} disabled={!selCount}>None</button>
                  <button
                    className={`btn btn-sm${showIndexed ? ' btn-accent' : ' btn-muted'}`}
                    style={{ flex: 1 }}
                    onClick={() => setShowIndexed(v => !v)}
                    title="Toggle between all files and indexed-only"
                  >
                    {showIndexed ? 'Indexed' : 'All files'}
                  </button>
                </div>
                {selCount > 0 && (
                  <div style={{ fontSize: 11.5, color: 'var(--accent)', marginTop: -8 }}>{selCount} file{selCount !== 1 ? 's' : ''} selected</div>
                )}

                {/* pipeline */}
                <div>
                  <div style={{ fontSize: 11, color: 'var(--txt3)', marginBottom: 5, fontWeight: 600, letterSpacing: '.04em', textTransform: 'uppercase' }}>Extraction pipeline</div>
                  <select className="s-select" style={{ width: '100%' }} value={pipeline} onChange={e => setPipeline(e.target.value)}>
                    <option value="text">Text — MarkItDown (PDF, DOCX, code…)</option>
                    <option value="vision">Vision LLM — images &amp; scanned PDFs</option>
                  </select>
                </div>

                {/* index / cancel */}
                {indexing ? (
                  <button className="btn btn-muted" style={{ width: '100%' }} onClick={cancelIndex}>Cancel indexing</button>
                ) : (
                  <button className="btn btn-accent" style={{ width: '100%' }} onClick={doIndex} disabled={loadingFiles || allPaths.length === 0}>
                    {selCount > 0 ? `Index ${selCount} selected file${selCount !== 1 ? 's' : ''}` : 'Index all files'}
                  </button>
                )}

                {/* progress */}
                {indexStatus && (
                  <div>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 5 }}>
                      <div style={{ flex: 1, height: 4, background: 'var(--surface2)', borderRadius: 4, overflow: 'hidden', border: '1px solid var(--brd)' }}>
                        <div style={{ height: '100%', width: `${indexPct ?? 0}%`, background: indexStatus.error ? '#f87171' : 'var(--accent)', borderRadius: 4, transition: 'width 100ms' }} />
                      </div>
                      <span style={{ fontSize: 10.5, color: 'var(--txt3)', minWidth: 30, textAlign: 'right' }}>{indexPct ?? 0}%</span>
                    </div>
                    <div style={{ fontSize: 11, color: indexStatus.error ? '#f87171' : 'var(--txt3)' }}>
                      {indexStatus.error
                        ? indexStatus.error
                        : indexStatus.done
                          ? `Done · ${indexStatus.indexed_files} files · ${indexStatus.indexed_chunks} chunks`
                          : currentFile
                            ? `${indexStatus.file_index}/${indexStatus.total_files} · ${currentFile}`
                            : `${indexStatus.file_index}/${indexStatus.total_files} files…`}
                    </div>
                  </div>
                )}

                {/* sync activity */}
                <button className="btn btn-muted btn-sm" style={{ width: '100%' }} onClick={doExportAndIndex} disabled={indexing}
                  title="Export your notes and transcripts from the activity store and index them">
                  Sync notes &amp; transcripts
                </button>
              </div>
            )}

            {/* ── Tab: Search ── */}
            {rightTab === 'search' && (
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--brd)', display: 'flex', gap: 6, flexShrink: 0 }}>
                  <input
                    className="s-input"
                    placeholder="Search across indexed files…"
                    value={ragQuery}
                    onChange={e => setRagQuery(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && doSearch()}
                    style={{ flex: 1, fontSize: 12 }}
                    autoFocus
                  />
                  <button className="btn btn-accent btn-sm" onClick={doSearch} disabled={ragLoading} style={{ flexShrink: 0 }}>
                    {ragLoading ? '…' : 'Search'}
                  </button>
                </div>
                <div style={{ flex: 1, overflowY: 'auto', padding: '10px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {ragResults.length === 0 && ragQuery && !ragLoading && (
                    <div style={{ color: 'var(--txt3)', fontSize: 12.5, textAlign: 'center', padding: '32px 0' }}>No results for "{ragQuery}"</div>
                  )}
                  {ragResults.length === 0 && !ragQuery && (
                    <div style={{ color: 'var(--txt3)', fontSize: 12.5, textAlign: 'center', padding: '32px 0' }}>
                      Index your workspace files first, then search here.
                    </div>
                  )}
                  {ragResults.map((res, i) => (
                    <div key={i} className="rag-result-card" style={{ borderLeft: `2px solid ${res.is_activity ? 'var(--accent)' : 'var(--brd2)'}` }}>
                      <div className="rag-result-source">
                        {res.is_activity
                          ? <span style={{ fontSize: 10.5, color: 'var(--accent)' }}>{res.source}</span>
                          : <button className="tb-btn" style={{ fontSize: 11 }} onClick={() => setFileViewer({ path: res.source })}>{res.source}</button>}
                        {res.score != null && <span style={{ fontSize: 10, color: 'var(--txt3)', marginLeft: 6 }}>{Math.round(res.score * 100)}%</span>}
                      </div>
                      <div className="rag-result-text">{(res.text || '').slice(0, 220)}{(res.text || '').length > 220 ? '…' : ''}</div>
                      <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                        <button className="tb-btn" style={{ fontSize: 10.5 }} onClick={() => setNoteSeed(`> ${res.text}\n\n`)}>Add to note</button>
                        <button className="tb-btn" style={{ fontSize: 10.5 }} onClick={() => { setChatInput(`Based on ${res.source}: ${(res.text || '').slice(0, 80)}… `); setRightTab('chat'); }}>Ask AI</button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ── Tab: Chat ── */}
            {rightTab === 'chat' && (
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {chatHistory.length === 0 && (
                    <div style={{ color: 'var(--txt3)', fontSize: 12.5, textAlign: 'center', padding: '32px 0' }}>
                      <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--txt2)' }}>Ask about your workspace</div>
                      <div style={{ fontSize: 11.5 }}>Answers are grounded in your indexed files.</div>
                      <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 6 }}>
                        {['Summarize the main topics covered', 'What are the key concepts I should know?'].map(s => (
                          <button key={s} className="btn btn-muted btn-sm" style={{ fontSize: 11.5 }} onClick={() => setChatInput(s)}>{s}</button>
                        ))}
                      </div>
                    </div>
                  )}
                  {chatHistory.map((msg, i) => (
                    <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start', gap: 4 }}>
                      <div style={{
                        maxWidth: '88%', padding: '8px 11px', borderRadius: 10, fontSize: 12.5, lineHeight: 1.5,
                        background: msg.role === 'user' ? 'var(--accent)' : 'var(--surface2)',
                        color: msg.role === 'user' ? '#fff' : 'var(--txt)',
                        border: msg.role === 'assistant' ? '1px solid var(--brd)' : 'none',
                      }}>
                        {msg.content}
                      </div>
                      {msg.sources?.length > 0 && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, maxWidth: '88%' }}>
                          {msg.sources.slice(0, 4).map((s, j) => (
                            <button key={j} className="tb-btn" style={{ fontSize: 10, padding: '1px 6px' }} onClick={() => setFileViewer({ path: s.source })}>
                              {s.source.split('/').pop()}:{s.line}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                  {chatLoading && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--txt3)', fontSize: 12 }}>
                      <span className="spin" style={{ width: 12, height: 12 }} /> Thinking…
                    </div>
                  )}
                  <div ref={chatEndRef} />
                </div>
                <div style={{ padding: '10px 14px', borderTop: '1px solid var(--brd)', display: 'flex', gap: 6, flexShrink: 0 }}>
                  <textarea
                    style={{
                      flex: 1, fontSize: 12.5, padding: '7px 10px', borderRadius: 7, border: '1px solid var(--brd)',
                      background: 'var(--surface2)', color: 'var(--txt)', fontFamily: 'var(--font)', resize: 'none', outline: 'none',
                    }}
                    rows={2}
                    value={chatInput}
                    onChange={e => setChatInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doChat(); } }}
                    placeholder="Ask about your workspace… (Enter to send)"
                  />
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                    <button className="btn btn-accent btn-sm" onClick={doChat} disabled={chatLoading || !chatInput.trim()}>Send</button>
                    {chatHistory.length > 0 && (
                      <button className="btn btn-muted btn-sm" onClick={() => setChatHistory([])}>Clear</button>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </Overlay>

      {fileViewer && (
        <FileViewer
          spaceId={spaceId}
          filePath={fileViewer.path}
          spaceRoadmap={spaceRoadmap}
          onClose={() => setFileViewer(null)}
          onTakeNote={(seed) => setNoteSeed(seed)}
        />
      )}
      {noteSeed !== null && (
        <NoteFromSeed spaceId={spaceId} seed={noteSeed} onClose={() => setNoteSeed(null)} />
      )}
    </>
  );
}

/**
 * Folder-based file browser.
 * - Groups files by first path segment (root files + named folders)
 * - Clicking a folder row expands/collapses its files inline
 * - Checkbox on the right of each row; green dot for indexed files
 */
function FolderBrowser({ files, selected, indexedSet, onToggleFile, onToggleFolder, onOpen }) {
  const [openFolders, setOpenFolders] = useState(() => new Set());

  const { rootFiles, folders } = useMemo(() => {
    const roots = [];
    const fMap = {};
    files.forEach(f => {
      const slash = f.path.indexOf('/');
      if (slash === -1) {
        roots.push(f);
      } else {
        const key = f.path.slice(0, slash);
        if (!fMap[key]) fMap[key] = [];
        fMap[key].push(f);
      }
    });
    // Sort folders alphabetically, roots last
    return { rootFiles: roots, folders: fMap };
  }, [files]);

  const toggleFolder = (name) => setOpenFolders(prev => {
    const next = new Set(prev);
    next.has(name) ? next.delete(name) : next.add(name);
    return next;
  });

  const fmtSize = (bytes) => {
    if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)}MB`;
    if (bytes >= 1024) return `${Math.round(bytes / 1024)}KB`;
    return `${bytes}B`;
  };

  return (
    <div style={{ fontSize: 12.5 }}>
      {/* ── folder groups ── */}
      {Object.entries(folders).sort(([a], [b]) => a.localeCompare(b)).map(([name, folderFiles]) => {
        const isOpen     = openFolders.has(name);
        const selCount   = folderFiles.filter(f => selected.has(f.path)).length;
        const allSel     = folderFiles.length > 0 && selCount === folderFiles.length;
        const someSel    = selCount > 0 && selCount < folderFiles.length;
        const idxCount   = folderFiles.filter(f => indexedSet.has(f.path)).length;

        return (
          <div key={name}>
            {/* folder row */}
            <div
              style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '7px 12px', cursor: 'pointer', borderBottom: '1px solid var(--brd)', background: isOpen ? 'var(--surface2)' : 'transparent', userSelect: 'none' }}
              onClick={() => toggleFolder(name)}
            >
              {/* chevron */}
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
                style={{ flexShrink: 0, opacity: 0.55, transform: isOpen ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 150ms' }}>
                <polyline points="9 18 15 12 9 6"/>
              </svg>
              {/* folder icon */}
              <svg width="14" height="14" viewBox="0 0 24 24" fill={isOpen ? 'var(--accent-dim)' : 'none'} stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0, color: 'var(--accent)', opacity: 0.8 }}>
                <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
              </svg>
              {/* folder name */}
              <span style={{ flex: 1, fontWeight: 600, color: 'var(--txt)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {name}/
              </span>
              {/* meta */}
              <span style={{ fontSize: 10.5, color: 'var(--txt3)', flexShrink: 0 }}>
                {idxCount > 0 && <span style={{ color: 'var(--accent)', marginRight: 6 }}>{idxCount} indexed</span>}
                {folderFiles.length} file{folderFiles.length !== 1 ? 's' : ''}
              </span>
              {/* folder checkbox */}
              <input
                type="checkbox"
                ref={el => { if (el) el.indeterminate = someSel; }}
                checked={allSel}
                onChange={() => onToggleFolder(name + '/', files)}
                onClick={e => e.stopPropagation()}
                style={{ cursor: 'pointer', accentColor: 'var(--accent)', flexShrink: 0, width: 14, height: 14 }}
              />
            </div>

            {/* expanded files */}
            {isOpen && folderFiles.map(f => {
              const fname    = f.path.slice(name.length + 1); // relative within folder
              const isChecked = selected.has(f.path);
              const isIndexed = indexedSet.has(f.path);
              return (
                <div
                  key={f.path}
                  style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '5px 12px 5px 32px', borderBottom: '1px solid var(--brd)', background: isChecked ? 'var(--accent-dim)' : 'transparent', transition: 'background 100ms' }}
                >
                  {/* indexed dot */}
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: isIndexed ? 'var(--accent)' : 'var(--brd2)', flexShrink: 0, display: 'inline-block' }} title={isIndexed ? 'Indexed' : 'Not indexed'} />
                  {/* file icon */}
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0, opacity: 0.45 }}>
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                    <polyline points="14 2 14 8 20 8"/>
                  </svg>
                  {/* filename */}
                  <span
                    style={{ flex: 1, color: 'var(--txt2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', cursor: 'pointer', fontSize: 12 }}
                    title={f.path}
                    onClick={() => onOpen(f.path)}
                  >
                    {fname}
                  </span>
                  {/* size */}
                  {f.size > 0 && (
                    <span style={{ fontSize: 10.5, color: 'var(--txt3)', flexShrink: 0 }}>{fmtSize(f.size)}</span>
                  )}
                  {/* checkbox */}
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => onToggleFile(f.path)}
                    style={{ cursor: 'pointer', accentColor: 'var(--accent)', flexShrink: 0, width: 14, height: 14 }}
                  />
                </div>
              );
            })}
          </div>
        );
      })}

      {/* ── root files (no folder) ── */}
      {rootFiles.length > 0 && (
        <div>
          {rootFiles.length > 0 && Object.keys(folders).length > 0 && (
            <div style={{ padding: '6px 12px 4px', fontSize: 10.5, color: 'var(--txt3)', fontWeight: 600, letterSpacing: '.06em', textTransform: 'uppercase', borderBottom: '1px solid var(--brd)' }}>Root files</div>
          )}
          {rootFiles.map(f => {
            const isChecked = selected.has(f.path);
            const isIndexed = indexedSet.has(f.path);
            return (
              <div
                key={f.path}
                style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '5px 12px', borderBottom: '1px solid var(--brd)', background: isChecked ? 'var(--accent-dim)' : 'transparent', transition: 'background 100ms' }}
              >
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: isIndexed ? 'var(--accent)' : 'var(--brd2)', flexShrink: 0, display: 'inline-block' }} title={isIndexed ? 'Indexed' : 'Not indexed'} />
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0, opacity: 0.45 }}>
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                  <polyline points="14 2 14 8 20 8"/>
                </svg>
                <span
                  style={{ flex: 1, color: 'var(--txt2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', cursor: 'pointer', fontSize: 12 }}
                  title={f.path}
                  onClick={() => onOpen(f.path)}
                >
                  {f.path}
                </span>
                {f.size > 0 && (
                  <span style={{ fontSize: 10.5, color: 'var(--txt3)', flexShrink: 0 }}>
                    {f.size >= 1048576 ? `${(f.size / 1048576).toFixed(1)}MB` : f.size >= 1024 ? `${Math.round(f.size / 1024)}KB` : `${f.size}B`}
                  </span>
                )}
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => onToggleFile(f.path)}
                  style={{ cursor: 'pointer', accentColor: 'var(--accent)', flexShrink: 0, width: 14, height: 14 }}
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function FileTree({ node, onOpen }) {
  return Object.entries(node).map(([k, v]) => {
    if (v._f) {
      return (
        <div key={v._f.path} className="file-tree-item" onClick={() => onOpen(v._f.path)}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/></svg>
          {k}
        </div>
      );
    }
    return (
      <details key={k} className="file-tree-dir">
        <summary className="file-tree-dir-name">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
          {k}
        </summary>
        <div style={{ marginLeft: 14 }}>
          <FileTree node={v} onOpen={onOpen} />
        </div>
      </details>
    );
  });
}

function buildFileTree(files) {
  const tree = {};
  (files || []).forEach(f => {
    const parts = f.path.split('/');
    let node = tree;
    parts.forEach((p, i) => {
      if (!node[p]) node[p] = i === parts.length - 1 ? { _f: f } : {};
      node = node[p];
    });
  });
  return tree;
}

const _BINARY_EXTS = new Set([
  'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico',
  'docx', 'doc', 'pptx', 'ppt', 'xlsx', 'xls', 'epub', 'zip',
  'mp4', 'webm', 'mp3', 'wav', 'ogg',
]);

function FileViewer({ spaceId, filePath, spaceRoadmap, onClose, onTakeNote }) {
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [linkTo, setLinkTo] = useState('');

  const ext = filePath.split('.').pop()?.toLowerCase() || '';
  const isBinary = _BINARY_EXTS.has(ext);
  const rawUrl = `/api/spaces/${spaceId}/files/raw?path=${encodeURIComponent(filePath)}`;

  useEffect(() => {
    if (isBinary) return;
    let mounted = true;
    (async () => {
      setLoading(true);
      try {
        const r = await api(`/spaces/${spaceId}/files/content?path=${encodeURIComponent(filePath)}`);
        if (mounted) setContent(r.content || '');
      } catch {}
      setLoading(false);
    })();
    return () => { mounted = false; };
  }, [spaceId, filePath, isBinary]);

  const linkFile = async () => {
    const chapters = spaceRoadmap?.chapters || [];
    const ch = chapters.find(c => c.id === linkTo);
    if (!ch) return;
    await api(`/spaces/${spaceId}/files/link`, {
      method: 'POST',
      body: JSON.stringify({ path: filePath, linked_to: [{ type: 'chapter', id: ch.id }] }),
    });
  };

  const isImage = ['png','jpg','jpeg','gif','webp','svg','bmp','ico'].includes(ext);
  const isPdf   = ext === 'pdf';

  return (
    <Overlay title={filePath} width="65%" height="78%" onClose={onClose}>
      <div style={{ marginBottom: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
        <button className="btn btn-muted btn-sm" onClick={() => onTakeNote?.(`From: ${filePath}\n\n`)}>Take Note</button>
        {isBinary && (
          <a className="btn btn-muted btn-sm" href={rawUrl} target="_blank" rel="noreferrer">Open in browser</a>
        )}
        <select className="s-select" style={{ width: 200 }} value={linkTo} onChange={e => setLinkTo(e.target.value)}>
          <option value="">Link to chapter…</option>
          {(spaceRoadmap?.chapters || []).map(ch => <option key={ch.id} value={ch.id}>{ch.title}</option>)}
        </select>
        <button className="btn btn-muted btn-sm" onClick={linkFile} disabled={!linkTo}>Link</button>
      </div>
      {isPdf ? (
        <iframe
          src={rawUrl}
          style={{ width: '100%', height: 'calc(100% - 50px)', border: 'none', borderRadius: 6 }}
          title={filePath}
        />
      ) : isImage ? (
        <div style={{ textAlign: 'center', overflowY: 'auto' }}>
          <img src={rawUrl} alt={filePath} style={{ maxWidth: '100%', borderRadius: 6 }} />
        </div>
      ) : loading ? (
        <div className="loading-center"><span className="spin" /></div>
      ) : ['md','markdown','rst'].includes(ext) ? (
        <MarkdownEditor value={content} readOnly defaultMode="read" />
      ) : (
        <pre className="code-block" style={{ maxHeight: 'none', overflowX: 'auto' }}>{content}</pre>
      )}
    </Overlay>
  );
}

function NoteFromSeed({ spaceId, seed, onClose }) {
  const [title, setTitle] = useState('Note from search');
  const [body, setBody] = useState(seed || '');
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      await api(`/spaces/${spaceId}/notes`, {
        method: 'POST',
        body: JSON.stringify({ title: title || 'Untitled', body_md: body || '', type: 'general' }),
      });
      onClose();
    } catch {}
    setSaving(false);
  };
  return (
    <Overlay title="Note from search" width="48%" height="55%" onClose={onClose}>
      <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
        <input className="s-input" value={title} onChange={e => setTitle(e.target.value)} placeholder="Title…" />
        <button className="btn btn-accent btn-sm" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
      </div>
      <MarkdownEditor value={body} onChange={setBody} onSave={save} />
    </Overlay>
  );
}

function GraphPanel({ spaceId, spaceRoadmap, onClose }) {
  const [graphData, setGraphData] = useState(null);
  const wrapRef = useRef(null);
  const [dims, setDims] = useState({ w: 800, h: 540 });
  const { setCurrentChapter, setCurrentTopic, setSpacesView } = useStore();

  useEffect(() => {
    let mounted = true;
    api(`/spaces/${spaceId}/graph`).then(r => { if (mounted) setGraphData(r); }).catch(() => {});
    return () => { mounted = false; };
  }, [spaceId]);

  useEffect(() => {
    if (!wrapRef.current) return;
    const obs = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      setDims({ w: Math.floor(width) || 800, h: Math.floor(height) || 540 });
    });
    obs.observe(wrapRef.current);
    return () => obs.disconnect();
  }, []);

  // Build nodes + links from roadmap + graph API
  const { nodes, links } = useMemo(() => {
    const chapters    = spaceRoadmap?.chapters || [];
    const backendNodes = graphData?.nodes || [];
    const backendLinks = graphData?.links || [];
    const nodes = [];
    const links = [];

    // Chapter nodes
    chapters.forEach(ch => {
      nodes.push({ id: ch.id, label: ch.title, type: 'chapter', status: ch.status || 'not_started', chapterId: ch.id, _ch: ch });
      // Topic + concept nodes
      (ch.topics || []).forEach(tp => {
        nodes.push({ id: tp.id, label: tp.title, type: 'topic', status: 'not_started', chapterId: ch.id, _tp: tp, _ch: ch });
        links.push({ source: ch.id, target: tp.id, type: 'hierarchy' });
        (tp.concepts || []).forEach(cn => {
          nodes.push({ id: cn.id, label: cn.title, type: 'concept', status: cn.status || 'not_started', chapterId: ch.id, _cn: cn, _tp: tp, _ch: ch });
          links.push({ source: tp.id, target: cn.id, type: 'hierarchy' });
        });
      });
    });

    // Cross-links from backend /graph endpoint
    backendLinks.forEach(l => links.push({ source: l.source, target: l.target, type: 'related' }));

    return { nodes, links };
  }, [spaceRoadmap, graphData]);

  const handleNodeClick = (node) => {
    if (node.type === 'chapter' && node._ch) {
      setCurrentChapter({ id: node._ch.id, title: node._ch.title, data: node._ch });
      setSpacesView('chapter');
      onClose();
    } else if (node.type === 'topic' && node._tp) {
      setCurrentChapter({ id: node._ch.id, title: node._ch.title, data: node._ch });
      setCurrentTopic({ ...node._tp, chapterId: node._ch.id });
      setSpacesView('topic');
      onClose();
    } else if (node.type === 'concept' && node._cn) {
      setCurrentChapter({ id: node._ch.id, title: node._ch.title, data: node._ch });
      setCurrentTopic({ ...node._tp, chapterId: node._ch.id, _openConceptId: node._cn.id });
      setSpacesView('topic');
      onClose();
    }
  };

  const chCount  = (spaceRoadmap?.chapters || []).length;
  const cnCount  = countConcepts(spaceRoadmap);

  return (
    <Overlay title="Concept Graph" width="88%" height="90%" onClose={onClose} bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      {chCount === 0 ? (
        <div className="empty" style={{ padding: 40 }}><div className="empty-desc">No chapters yet — build a roadmap first.</div></div>
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 14px', borderBottom: '1px solid var(--brd)', flexShrink: 0 }}>
            <div style={{ display: 'flex', gap: 14, fontSize: 11.5, color: 'var(--txt3)' }}>
              <span><strong style={{ color: 'var(--txt2)' }}>{chCount}</strong> chapters</span>
              <span><strong style={{ color: 'var(--txt2)' }}>{nodes.filter(n => n.type === 'topic').length}</strong> topics</span>
              <span><strong style={{ color: 'var(--txt2)' }}>{cnCount}</strong> concepts</span>
            </div>
            <div style={{ display: 'flex', gap: 14, fontSize: 11, color: 'var(--txt3)', alignItems: 'center' }}>
              <LegendDot color="#6366f1" label="chapter" />
              <LegendDot color="#38bdf8" label="topic" />
              <LegendDot color="#4ade80" label="concept" />
              <LegendDot color="#fbbf24" label="in progress" />
              <span style={{ opacity: 0.5, marginLeft: 4 }}>scroll=zoom · drag=pan · click=navigate</span>
            </div>
          </div>
          <div ref={wrapRef} style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
            <ForceGraph
              nodes={nodes}
              links={links}
              onNodeClick={handleNodeClick}
              width={dims.w}
              height={dims.h}
            />
          </div>
        </>
      )}
    </Overlay>
  );
}

function LegendDot({ color, label }) {
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, display: 'inline-block', border: `1.5px solid ${color}` }} />
      {label}
    </span>
  );
}

function countConcepts(roadmap) {
  let count = 0;
  (roadmap?.chapters || []).forEach(ch => {
    (ch.topics || []).forEach(tp => { count += (tp.concepts || []).length; });
  });
  return count;
}

function PracticeTestPanel({ space, spaceId, onClose, refreshHero }) {
  const [phase, setPhase] = useState('setup');
  const [test, setTest] = useState(null);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [answers, setAnswers] = useState({});
  const [timeTaken, setTimeTaken] = useState({});
  const [remaining, setRemaining] = useState(0);
  const timerRef = useRef(null);
  const startRef = useRef(Date.now());

  const [testType, setTestType] = useState('concept');
  const [source, setSource] = useState('llm');
  const [scope, setScope] = useState('');
  const [prompt, setPrompt] = useState('');
  const [secPerQ, setSecPerQ] = useState(120);
  const [nq, setNq] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  const currentQ = test?.questions?.[currentIdx];

  const startTimer = (seconds) => {
    clearInterval(timerRef.current);
    startRef.current = Date.now();
    setRemaining(seconds);
    timerRef.current = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startRef.current) / 1000);
      const rem = seconds - elapsed;
      if (rem <= 0) {
        clearInterval(timerRef.current);
        setRemaining(0);
        nextQuestion(true);
      } else {
        setRemaining(rem);
      }
    }, 250);
  };

  const { err } = useStore();

  const generate = async () => {
    setLoading(true);
    try {
      const t = await api(`/spaces/${spaceId}/practice/generate`, {
        method: 'POST',
        body: JSON.stringify({
          test_type: testType,
          scope,
          source,
          source_prompt: prompt,
          seconds_per_question: secPerQ,
          n_questions: nq ? parseInt(nq) : null,
          directory: space?.directory || '',
        }),
      });
      setTest(t);
      setPhase('test');
      setCurrentIdx(0);
      setAnswers({});
      setTimeTaken({});
      setResult(null);
      startTimer(t.questions?.[0]?.time_limit_seconds || secPerQ);
    } catch (e) { err(e.message); }
    setLoading(false);
  };

  const recordTime = (q) => {
    const elapsed = Math.floor((Date.now() - startRef.current) / 1000);
    setTimeTaken(tt => ({ ...tt, [q.question_id]: Math.min(elapsed, q.time_limit_seconds || secPerQ) }));
  };

  const nextQuestion = async (timedOut = false) => {
    if (!currentQ) return;
    if (timedOut) {
      setTimeTaken(tt => ({ ...tt, [currentQ.question_id]: currentQ.time_limit_seconds || secPerQ }));
    } else {
      recordTime(currentQ);
    }
    if (currentIdx + 1 < test.questions.length) {
      const nextIdx = currentIdx + 1;
      setCurrentIdx(nextIdx);
      startTimer(test.questions[nextIdx]?.time_limit_seconds || secPerQ);
    } else {
      clearInterval(timerRef.current);
      await submitAnswers();
    }
  };

  const submitAnswers = async () => {
    setPhase('results');
    try {
      const r = await api(`/spaces/${spaceId}/practice/grade`, {
        method: 'POST',
        body: JSON.stringify({
          test_id: test.test_id,
          answers,
          time_taken: timeTaken,
          directory: space?.directory || '',
        }),
      });
      setResult(r);
      refreshHero?.();
    } catch (e) { err(e.message); }
  };

  const selectOption = (qId, val) => setAnswers(a => ({ ...a, [qId]: val }));

  useEffect(() => () => clearInterval(timerRef.current), []);

  return (
    <Overlay title="Practice Test" width="62%" height="88%" onClose={onClose} bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      {phase === 'setup' && (
        <div className="pt-setup">
          <div className="pt-setup-header">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0, color: 'var(--accent)' }}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
            <div>
              <div className="pt-setup-title">Configure Practice Test</div>
              <div className="pt-setup-sub">AI-generated or from your own notes</div>
            </div>
          </div>
          <div className="pt-setup-grid">
            <div className="pt-field">
              <label className="pt-label">Test scope</label>
              <div className="pt-seg">
                {['concept','topic','full_space'].map(v => (
                  <button key={v} className={`seg-btn${testType === v ? ' active' : ''}`} onClick={() => setTestType(v)}>
                    {v.replace('_', ' ')}
                  </button>
                ))}
              </div>
            </div>
            <div className="pt-field">
              <label className="pt-label">Concept / topic name</label>
              <input className="s-input" placeholder="e.g. gradient descent (leave blank for auto)" value={scope} onChange={e => setScope(e.target.value)} />
            </div>
            <div className="pt-field">
              <label className="pt-label">Question source</label>
              <div className="pt-seg">
                {['llm','rag','prompt'].map(v => (
                  <button key={v} className={`seg-btn${source === v ? ' active' : ''}`} onClick={() => setSource(v)}>
                    {v === 'llm' ? 'AI-generated' : v === 'rag' ? 'From your notes' : 'Custom prompt'}
                  </button>
                ))}
              </div>
            </div>
            <div className="pt-field">
              <label className="pt-label">Prompt / instructions</label>
              <textarea className="s-input" rows={3} value={prompt} onChange={e => setPrompt(e.target.value)}
                placeholder="Instructions for the AI — e.g. focus on edge cases, use code examples, make questions harder than textbook…" style={{ resize: 'vertical', fontSize: 12.5, lineHeight: 1.55 }} />
            </div>
            <div className="pt-field">
              <label className="pt-label">Time per question (seconds)</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <input type="number" className="s-input" min="15" max="600" value={secPerQ} onChange={e => setSecPerQ(parseInt(e.target.value) || 120)}
                  style={{ width: 100, fontFamily: 'var(--mono)', fontSize: 14, textAlign: 'center' }} />
                <span style={{ fontSize: 11.5, color: 'var(--txt3)' }}>seconds per question</span>
              </div>
            </div>
            <div className="pt-field">
              <label className="pt-label">Number of questions</label>
              <div className="pt-seg">
                {['','5','10','20'].map(v => (
                  <button key={v || 'auto'} className={`seg-btn${nq === v ? ' active' : ''}`} onClick={() => setNq(v)}>
                    {v || 'Auto'}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <button className="btn btn-accent pt-gen-btn" onClick={generate} disabled={loading}>
            {loading ? 'Generating…' : 'Generate Test'}
          </button>
        </div>
      )}
      {phase === 'test' && currentQ && (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div className="pt-test-header">
            <div className="pt-test-meta">
              <span>{`Q${currentIdx + 1}/${test.questions.length}`}</span>
              <span className="pt-sep">·</span>
              <span style={{ color: 'var(--txt3)' }}>{currentQ.concept || ''}</span>
            </div>
            <div className="pt-test-timer-wrap">
              <div className="pt-timer-ring">
                <svg viewBox="0 0 36 36" width="44" height="44">
                  <circle cx="18" cy="18" r="15" fill="none" stroke="var(--brd2)" strokeWidth="2.5" />
                  <circle
                    cx="18" cy="18" r="15" fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round"
                    strokeDasharray="94.25" strokeDashoffset={94.25 * (1 - remaining / (currentQ.time_limit_seconds || secPerQ))}
                    style={{ transform: 'rotate(-90deg)', transformOrigin: 'center', transition: 'stroke .3s' }}
                  />
                </svg>
                <div className="pt-timer-val">{`${String(Math.floor(remaining / 60)).padStart(2, '0')}:${String(remaining % 60).padStart(2, '0')}`}</div>
              </div>
            </div>
          </div>
          <div className="pt-q-body">
            <div className="pt-q-type-row">
              <span className="pt-q-type-pill">{currentQ.question_type}</span>
              {currentQ.difficulty && <span className={`pt-q-diff-pill ${currentQ.difficulty}`}>{currentQ.difficulty}</span>}
              <span className="pt-q-pts">{currentQ.points || 10}pts</span>
            </div>
            <div className="pt-question-text-wrap">
              <MarkdownEditor value={currentQ.question || ''} readOnly defaultMode="read" />
            </div>
            {(currentQ.question_type === 'mcq' || currentQ.question_type === 'true_false') ? (
              <div className="pt-options">
                {(currentQ.options?.length ? currentQ.options : currentQ.question_type === 'true_false' ? ['True', 'False'] : []).map((o, i) => (
                  <button key={o} className={`pt-option${answers[currentQ.question_id] === o ? ' selected' : ''}`} onClick={() => selectOption(currentQ.question_id, o)}>
                    <span className="pt-opt-key">{String.fromCharCode(65 + i)}</span>
                    <span>{o}</span>
                  </button>
                ))}
              </div>
            ) : (
              <textarea className="pt-open-answer s-input" rows={5} value={answers[currentQ.question_id] || ''}
                onChange={e => selectOption(currentQ.question_id, e.target.value)}
                placeholder={currentQ.question_type === 'code' ? 'Write your code here…' : 'Your answer…'} />
            )}
          </div>
          <div className="pt-q-footer">
            <div id="pt-q-hint" style={{ fontSize: 11.5, color: 'var(--txt3)', flex: 1 }}>{currentIdx === test.questions.length - 1 ? '(Last question)' : ''}</div>
            <button className="btn btn-muted btn-sm" onClick={() => nextQuestion(false)}>Skip</button>
            <button className="btn btn-accent btn-sm" onClick={() => nextQuestion(false)}>{currentIdx === test.questions.length - 1 ? 'Finish ✓' : 'Next →'}</button>
          </div>
        </div>
      )}
      {phase === 'results' && result && (
        <div id="pt-results" style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
          <div className="pt-result-header">
            <div className="pt-result-icon">{result.passed ? '✓' : '✗'}</div>
            <div>
              <div className="pt-result-score" style={{ color: result.percent >= 80 ? '#4ade80' : result.percent >= 60 ? '#fbbf24' : '#f87171' }}>{result.percent || 0}%</div>
              <div className="pt-result-status">{result.passed ? 'Passed' : 'Needs more work'}</div>
            </div>
            <div className="pt-result-xp">+{result.xp_earned || 0} XP</div>
          </div>
          <div className="pt-result-concepts">
            {result.strong_concepts?.length ? <div className="pt-concept-group strong"><strong>Strong:</strong> {result.strong_concepts.join(', ')}</div> : null}
            {result.weak_concepts?.length ? <div className="pt-concept-group weak"><strong>Review:</strong> {result.weak_concepts.join(', ')}</div> : null}
          </div>
          <div className="pt-breakdown-title">Question breakdown</div>
          <div className="pt-breakdown">
            {test.questions.map((q, i) => {
              const r = result.question_results?.[i] || {};
              const statusColor = r.timed_out ? '#fbbf24' : r.correct ? '#4ade80' : '#f87171';
              return (
                <div key={q.question_id} className="pt-res-row">
                  <span className="pt-res-status" style={{ color: statusColor }}>{r.timed_out ? '⏱' : r.correct ? '✓' : '✗'}</span>
                  <div className="pt-res-info">
                    <div className="pt-res-q">{(q.question || '').slice(0, 80)}{(q.question || '').length > 80 ? '…' : ''}</div>
                    {!r.correct && r.llm_feedback && <div className="pt-res-fb">{r.llm_feedback.slice(0, 120)}</div>}
                  </div>
                  <span className="pt-res-pts">{r.score || 0}/{q.points}pts</span>
                </div>
              );
            })}
          </div>
          <button className="btn btn-accent" style={{ marginTop: 14 }} onClick={() => { setPhase('setup'); setResult(null); }}>Take Another Test</button>
        </div>
      )}
    </Overlay>
  );
}

function OptimizerPanel({ spaceId, onClose }) {
  const [opts, setOpts] = useState([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      try { const r = await api(`/spaces/${spaceId}/optimize?recent_n=10`); if (mounted) setOpts(r || []); } catch {}
      setLoading(false);
    })();
    return () => { mounted = false; };
  }, [spaceId]);

  return (
    <Overlay title="Session Insights" width="52%" height="74%" onClose={onClose} bodyStyle={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
      {loading ? (
        <div className="loading-center"><span className="spin" /> Analyzing sessions…</div>
      ) : opts.length === 0 ? (
        <div className="empty" style={{ padding: '40px 0' }}>
          <div className="empty-ttl">Not enough data yet</div>
          <div className="empty-desc">Complete a few tracked sessions to see personalized optimizations.</div>
        </div>
      ) : (
        <>
          <div className="opt-header">
            <div className="opt-header-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>
              Session Optimizations
            </div>
            <div className="opt-header-sub">{opts.length} recommendation{opts.length !== 1 ? 's' : ''} based on your recent sessions</div>
          </div>
          {opts.map((o, i) => (
            <div key={i} className="opt-card" data-priority={o.priority || 'medium'}>
              <div className="opt-card-hdr">
                <span className="opt-priority-dot">{o.priority?.slice(0, 1) || '!'}</span>
                <span className="opt-source">{(o.signal_source || '').replace(/_/g, ' ')}</span>
                {o.xp_bonus ? <span className="opt-xp-bonus">+{o.xp_bonus} XP if you act on this</span> : null}
              </div>
              <div className="opt-observation">{o.observation}</div>
              <div className="opt-recommendation">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
                {o.recommendation}
              </div>
            </div>
          ))}
        </>
      )}
    </Overlay>
  );
}

// ── RAG Panel ─────────────────────────────────────────────────────────────────

const RAG_TABS = ['search', 'chat', 'files'];

function RagPanel({ space, spaceId, onClose }) {
  const [tab, setTab]           = useState('search');
  const [status, setStatus]     = useState(null);
  const [indexing, setIndexing] = useState(false);
  const [indexPct, setIndexPct] = useState(null);
  const indexTimer              = useRef(null);
  const fileInputRef            = useRef(null);
  const { ok, err }             = useStore();

  // ── Search state
  const [query, setQuery]         = useState('');
  const [results, setResults]     = useState([]);
  const [searching, setSearching] = useState(false);
  const [expanded, setExpanded]   = useState(null);
  const [fileViewer, setFileViewer] = useState(null);
  const [noteSeed, setNoteSeed]   = useState(null);

  // ── Chat state
  const [chatHistory, setChatHistory] = useState([]);
  const [chatInput, setChatInput]     = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const chatEndRef = useRef(null);

  // ── Files state
  const [files, setFiles]       = useState([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [uploading, setUploading] = useState(false);

  useEffect(() => { loadStatus(); loadFiles(); }, [spaceId]);
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [chatHistory]);

  const loadStatus = async () => {
    try {
      const s = await api(`/spaces/${spaceId}/rag/status`);
      setStatus(s);
    } catch {}
  };

  const loadFiles = async () => {
    setFilesLoading(true);
    try {
      const r = await api(`/spaces/${spaceId}/rag/files`);
      setFiles(r.files || []);
    } catch {}
    setFilesLoading(false);
  };

  const doIndex = async () => {
    if (indexing) return;
    setIndexing(true); setIndexPct(0);
    clearInterval(indexTimer.current);
    indexTimer.current = setInterval(() => setIndexPct(p => Math.min(88, (p ?? 0) + 4)), 200);
    try {
      await api(`/spaces/${spaceId}/rag/index`, { method: 'POST' });
      setIndexPct(100);
      ok('Index complete');
      await Promise.all([loadStatus(), loadFiles()]);
    } catch (e) { err(e.message); }
    clearInterval(indexTimer.current);
    setTimeout(() => { setIndexing(false); setIndexPct(null); }, 900);
  };

  const doSearch = async (q = query) => {
    if (!q.trim()) return;
    setSearching(true); setResults([]); setExpanded(null);
    try {
      const r = await api(`/spaces/${spaceId}/rag/search`, {
        method: 'POST',
        body: JSON.stringify({ query: q.trim(), top_k: 6 }),
      });
      setResults(r.results || []);
    } catch (e) { err(e.message); }
    setSearching(false);
  };

  const doChat = async () => {
    const q = chatInput.trim();
    if (!q || chatLoading) return;
    setChatInput('');
    const userMsg = { role: 'user', content: q };
    setChatHistory(h => [...h, userMsg]);
    setChatLoading(true);
    try {
      const r = await api(`/spaces/${spaceId}/rag/chat`, {
        method: 'POST',
        body: JSON.stringify({
          question: q,
          history: chatHistory.slice(-8),  // last 8 turns for context
          top_k: 5,
        }),
      });
      setChatHistory(h => [...h, { role: 'assistant', content: r.answer, sources: r.sources || [] }]);
    } catch (e) {
      setChatHistory(h => [...h, { role: 'assistant', content: `Error: ${e.message}`, sources: [] }]);
    }
    setChatLoading(false);
  };

  const doUpload = async (file) => {
    if (!file) return;
    setUploading(true);
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await fetch(`/api/spaces/${spaceId}/rag/upload`, { method: 'POST', body: fd });
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      ok(`Uploaded and indexed: ${data.saved_as}`);
      await Promise.all([loadStatus(), loadFiles()]);
    } catch (e) { err(e.message); }
    setUploading(false);
  };

  const fileTree = useMemo(() => buildFileTree(files), [files]);

  const statusBar = status ? (
    <div className="rag-status-bar">
      <span className={`rag-status-dot${status.enabled ? ' active' : ''}`} />
      <span>{status.enabled ? `${status.indexed_files} files · ${status.indexed_chunks} chunks` : 'Not indexed'}</span>
      <span style={{ marginLeft: 'auto', color: 'var(--txt3)' }}>{status.db_size_kb ? `${status.db_size_kb} KB` : ''}</span>
    </div>
  ) : null;

  return (
    <>
      <Overlay
        title={`Knowledge Base — ${space?.name || ''}`}
        width="80%" height="88%"
        onClose={onClose}
        bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column', minHeight: 0 }}
      >
        {/* Toolbar */}
        <div className="rag-toolbar">
          <div className="rag-tab-bar">
            {RAG_TABS.map(t => (
              <button key={t} className={`rag-tab${tab === t ? ' active' : ''}`} onClick={() => setTab(t)}>
                {t === 'search' && <SearchIcon />}
                {t === 'chat'   && <ChatIcon />}
                {t === 'files'  && <FilesIcon />}
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>
          <div className="rag-toolbar-right">
            {statusBar}
            <button className="btn btn-muted btn-sm" onClick={doIndex} disabled={indexing}>
              {indexing ? 'Indexing…' : 'Re-index'}
            </button>
            <button className="btn btn-muted btn-sm" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
              {uploading ? 'Uploading…' : 'Upload file'}
            </button>
            <input ref={fileInputRef} type="file" style={{ display: 'none' }}
              onChange={e => { doUpload(e.target.files?.[0]); e.target.value = ''; }} />
          </div>
        </div>

        {/* Index progress */}
        {indexPct !== null && (
          <div className="rag-progress-wrap">
            <div className="rag-progress-track">
              <div className="rag-progress-fill" style={{ width: `${indexPct}%` }} />
            </div>
            <span className="rag-progress-label">{indexPct < 100 ? `${indexPct}%` : 'Done'}</span>
          </div>
        )}

        {/* Tab: Search */}
        {tab === 'search' && (
          <div className="rag-search-pane">
            <div className="rag-search-bar">
              <input
                className="s-input rag-search-input"
                placeholder="Search your workspace files…"
                value={query}
                onChange={e => setQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && doSearch()}
                autoFocus
              />
              <button className="btn btn-accent btn-sm" onClick={() => doSearch()} disabled={searching || !query.trim()}>
                {searching ? <span className="spin" style={{ width: 13, height: 13 }} /> : 'Search'}
              </button>
            </div>

            {/* Quick chips from indexed files */}
            {!results.length && !searching && files.length > 0 && (
              <div className="rag-chips">
                {files.slice(0, 8).map(f => (
                  <button key={f.path} className="rag-chip" onClick={() => { setQuery(f.path.split('/').pop()); doSearch(f.path.split('/').pop()); }}>
                    {f.path.split('/').pop()}
                  </button>
                ))}
              </div>
            )}

            <div className="rag-results-list">
              {searching && (
                <div className="loading-center" style={{ padding: 32 }}><span className="spin" /> Searching…</div>
              )}
              {!searching && results.length === 0 && query && (
                <div className="rag-empty">No results for "{query}"</div>
              )}
              {!searching && results.length === 0 && !query && !files.length && (
                <div className="rag-empty">Index your workspace first, then search here.</div>
              )}
              {results.map((res, i) => (
                <div key={i} className={`rag-result${expanded === i ? ' expanded' : ''}`}>
                  <div className="rag-result-hdr" onClick={() => setExpanded(expanded === i ? null : i)}>
                    <div className="rag-result-source-row">
                      <button className="rag-file-btn" onClick={e => { e.stopPropagation(); setFileViewer({ path: res.source }); }}>
                        <FileIcon />
                        <span className="rag-file-name">{res.source.split('/').pop()}</span>
                        <span className="rag-file-path">{res.source}</span>
                      </button>
                    </div>
                    <div className="rag-result-meta">
                      <span className="rag-score-pill" style={{ '--s': res.score }}>{Math.round(res.score * 100)}%</span>
                      <span className="rag-line-ref">line {res.line}</span>
                      <button className="rag-expand-btn">{expanded === i ? '▲' : '▼'}</button>
                    </div>
                  </div>
                  <div className="rag-result-body">
                    <pre className="rag-result-text">{res.text}</pre>
                    <div className="rag-result-actions">
                      <button className="tb-btn" onClick={() => setNoteSeed(`> From \`${res.source}:${res.line}\`\n\n${res.text}\n\n`)}>Add to note</button>
                      <button className="tb-btn" onClick={() => { setChatInput(`Based on ${res.source}: ${res.text.slice(0, 80)}… `); setTab('chat'); }}>Ask AI</button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Tab: Chat */}
        {tab === 'chat' && (
          <div className="rag-chat-pane">
            <div className="rag-chat-messages">
              {chatHistory.length === 0 && (
                <div className="rag-chat-empty">
                  <div className="rag-chat-empty-title">Ask about your workspace</div>
                  <div className="rag-chat-empty-sub">Answers are grounded in your indexed files.</div>
                  <div className="rag-chat-suggestions">
                    {['Summarize the main topics covered', 'What are the key concepts I should know?', 'What files discuss this topic?'].map(s => (
                      <button key={s} className="rag-suggestion" onClick={() => { setChatInput(s); }}>{s}</button>
                    ))}
                  </div>
                </div>
              )}
              {chatHistory.map((msg, i) => (
                <div key={i} className={`rag-chat-msg ${msg.role}`}>
                  <div className="rag-chat-bubble">
                    <div className="rag-chat-content">{msg.content}</div>
                    {msg.sources?.length > 0 && (
                      <div className="rag-chat-sources">
                        <span className="rag-chat-sources-label">Sources:</span>
                        {msg.sources.slice(0, 4).map((s, j) => (
                          <button key={j} className="rag-source-chip" onClick={() => setFileViewer({ path: s.source })}>
                            {s.source.split('/').pop()}:{s.line}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {chatLoading && (
                <div className="rag-chat-msg assistant">
                  <div className="rag-chat-bubble rag-chat-thinking">
                    <span className="spin" style={{ width: 13, height: 13 }} /> Thinking…
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>
            <div className="rag-chat-bar">
              <textarea
                className="rag-chat-input"
                value={chatInput}
                onChange={e => setChatInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doChat(); } }}
                placeholder="Ask about your workspace… (Enter to send, Shift+Enter for newline)"
                rows={2}
              />
              <button className="btn btn-accent" onClick={doChat} disabled={chatLoading || !chatInput.trim()}>
                Send
              </button>
              {chatHistory.length > 0 && (
                <button className="btn btn-muted btn-sm" onClick={() => setChatHistory([])} title="Clear conversation">
                  Clear
                </button>
              )}
            </div>
          </div>
        )}

        {/* Tab: Files */}
        {tab === 'files' && (
          <div className="rag-files-pane">
            {filesLoading ? (
              <div className="loading-center"><span className="spin" /></div>
            ) : files.length === 0 ? (
              <div className="rag-empty" style={{ padding: '48px 0' }}>
                No files indexed yet. Click "Re-index" to scan the workspace.
              </div>
            ) : (
              <>
                <div className="rag-files-header">
                  <span>{files.length} files indexed</span>
                  {status?.db_size_kb ? <span style={{ color: 'var(--txt3)' }}>{status.db_size_kb} KB DB</span> : null}
                </div>
                <div className="rag-file-tree-wrap">
                  <FileTree node={fileTree} onOpen={(path) => setFileViewer({ path })} />
                </div>
              </>
            )}
          </div>
        )}
      </Overlay>

      {fileViewer && (
        <FileViewer
          spaceId={spaceId}
          filePath={fileViewer.path}
          spaceRoadmap={null}
          onClose={() => setFileViewer(null)}
          onTakeNote={(seed) => setNoteSeed(seed)}
        />
      )}
      {noteSeed !== null && (
        <NoteFromSeed spaceId={spaceId} seed={noteSeed} onClose={() => setNoteSeed(null)} />
      )}
    </>
  );
}

// Tiny inline SVG icon helpers
function SearchIcon() { return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>; }
function ChatIcon()   { return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>; }
function FilesIcon()  { return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>; }
function FileIcon()   { return <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/></svg>; }
