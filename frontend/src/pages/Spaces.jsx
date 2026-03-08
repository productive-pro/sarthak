import { useState, useEffect, useRef } from 'react';

import { api, fmt } from '../api';
import { useStore } from '../store';
import { useResizable } from '../hooks/useResizable';
import Modal from '../components/Modal';
import Overlay from '../components/Overlay';
import MarkdownEditor from '../components/MarkdownEditor';
import DropdownMenu from '../components/DropdownMenu';
import PromptInline from '../components/PromptInline';
import { ExplainsTab, QuickTestTab, MediaRecorderTab, NotebookTab, PlaygroundTab } from '../sarthak/ConceptTabs';
import PanelHost from './SpacePanels';

// ── Inline editable text ───────────────────────────────────────
function InlineEdit({ value, onSave, style, className, placeholder = 'Untitled', forceEdit, onEditDone }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(value);
  const inputRef = useRef(null);

  useEffect(() => { setVal(value); }, [value]);
  useEffect(() => { if (editing) inputRef.current?.focus(); }, [editing]);
  useEffect(() => { if (forceEdit) setEditing(true); }, [forceEdit]);

  const commit = () => {
    setEditing(false);
    onEditDone?.();
    const trimmed = val.trim() || value;
    setVal(trimmed);
    if (trimmed !== value) onSave(trimmed);
  };

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={val}
        onChange={e => setVal(e.target.value)}
        onBlur={commit}
        onKeyDown={e => {
          if (e.key === 'Enter') commit();
          if (e.key === 'Escape') { setEditing(false); setVal(value); }
        }}
        style={{ ...style, background: 'var(--surface2)', border: '1px solid var(--accent-border)', borderRadius: 4, padding: '2px 6px', color: 'var(--txt)', fontFamily: 'var(--font)', outline: 'none' }}
        className={className}
        placeholder={placeholder}
      />
    );
  }
  return (
    <span style={{ ...style, cursor: 'text' }} className={className} title="Double-click to edit" onDoubleClick={() => setEditing(true)}>
      {value || placeholder}
    </span>
  );
}

// ── Drag-to-reorder list ───────────────────────────────────────
/**
 * Drag-to-reorder within a list; calls onReorder(newItems) on same-column drop.
 * onDragToColumn(itemId, targetColKey) called when item lands in another column.
 *
 * Uses a single shared drag-state object in the module scope so each column
 * can read who is being dragged (avoids dataTransfer.getData limitations).
 */
const _drag = { id: null, colKey: null };

function Reorderable({ items, onReorder, renderItem, itemKey, colKey, onDragToColumn, dragRef }) {
  const drag = dragRef?.current ?? _drag;
  const [overId, setOverId] = useState(null);

  const onDragStart = (item) => (e) => {
    drag.id = itemKey(item);
    drag.colKey = colKey;
    e.dataTransfer.effectAllowed = 'move';
    // Keep text/plain for compatibility with column-level drop zones
    e.dataTransfer.setData('text/plain', JSON.stringify({ id: itemKey(item), colKey }));
  };

  const onDragOver = (item) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    setOverId(itemKey(item));
  };

  const onDrop = (targetItem) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    setOverId(null);

    const srcId  = drag.id;
    const srcCol = drag.colKey;
    drag.id = null; drag.colKey = null;
    if (!srcId) return;

    if (srcCol !== colKey) {
      // Cross-column move
      onDragToColumn?.(srcId, colKey);
      return;
    }

    // Same-column reorder
    const fromIdx = items.findIndex(x => itemKey(x) === srcId);
    const toIdx   = items.findIndex(x => itemKey(x) === itemKey(targetItem));
    if (fromIdx === -1 || toIdx === -1 || fromIdx === toIdx) return;
    const next = [...items];
    const [moved] = next.splice(fromIdx, 1);
    next.splice(toIdx, 0, moved);
    onReorder(next);
  };

  const onDragEnd = () => { drag.id = null; drag.colKey = null; setOverId(null); };

  return items.map((item) => (
    <div
      key={itemKey(item)}
      draggable
      onDragStart={onDragStart(item)}
      onDragOver={onDragOver(item)}
      onDrop={onDrop(item)}
      onDragEnd={onDragEnd}
      style={{
        opacity: overId === itemKey(item) ? 0.4 : 1,
        outline: overId === itemKey(item) ? '2px dashed var(--accent-border)' : 'none',
        borderRadius: 6,
        transition: 'opacity 100ms',
      }}
    >
      {renderItem(item)}
    </div>
  ));
}

// ── Roadmap Board (Kanban) ────────────────────────────────────
const STATUS_COLS = [
  { key: 'not_started', label: 'Not Started', color: 'var(--txt3)' },
  { key: 'in_progress', label: 'In Progress', color: '#fbbf24' },
  { key: 'review',      label: 'Review',      color: '#38bdf8' },
  { key: 'completed',   label: 'Completed',   color: 'var(--accent)' },
];

function RoadmapBoard({ roadmap, onChapterClick, onAddChapter, onPatchChapters, onGenerateChapter, onEditChapterDesc }) {
  const chapters = roadmap?.chapters || [];
  const dragRef = React.useRef({ id: null, colKey: null });

  if (!chapters.length) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 200, flexDirection: 'column', gap: 12, color: 'var(--txt3)', fontSize: 13 }}>
      <span>No chapters yet.</span>
      <button className="btn btn-accent btn-sm" onClick={onAddChapter}>+ Add Chapter</button>
    </div>
  );

  const byStatus = Object.fromEntries(STATUS_COLS.map(c => [c.key, []]));
  chapters.forEach(ch => { byStatus[ch.status in byStatus ? ch.status : 'not_started'].push(ch); });

  const totalDone   = chapters.filter(c => c.status === 'completed').length;
  const totalActive = chapters.filter(c => c.status === 'in_progress').length;

  /** Move chapter `chId` to a new status column, persist to backend. */
  const moveToColumn = (chId, newStatus) => {
    const updated = chapters.map((c, i) =>
      c.id === chId ? { ...c, status: newStatus } : c
    );
    onPatchChapters(updated);
  };

  /** Reorder within a column: merge back into full list preserving order. */
  const reorderInColumn = (reordered) => {
    const reorderedIds = new Set(reordered.map(c => c.id));
    // Keep all chapters not in this column, interleave reordered ones at original positions
    const rest = chapters.filter(c => !reorderedIds.has(c.id));
    // Simplest correct merge: put reordered at their slot indices
    const next = [...chapters];
    let slot = 0;
    for (let i = 0; i < next.length; i++) {
      if (reorderedIds.has(next[i].id)) {
        next[i] = reordered[slot++];
      }
    }
    onPatchChapters(next);
  };

  const renameChapter = (chId, title) => {
    onPatchChapters(chapters.map(c => c.id === chId ? { ...c, title } : c));
  };

  const deleteChapter = (chId) => {
    if (!confirm('Delete this chapter and all its topics?')) return;
    onPatchChapters(chapters.filter(c => c.id !== chId));
  };

  // Make each column a drop target for cross-column drags (fires when dropping on empty space)
  const columnDropProps = (colKey) => ({
    onDragOver: (e) => e.preventDefault(),
    onDrop: (e) => {
      e.preventDefault();
      // Use container-scoped dragRef first (most reliable), fall back to dataTransfer
      const srcId  = dragRef.current.id  || (() => { try { return JSON.parse(e.dataTransfer.getData('text/plain')).id; } catch { return null; } })();
      const srcCol = dragRef.current.colKey || (() => { try { return JSON.parse(e.dataTransfer.getData('text/plain')).colKey; } catch { return null; } })();
      dragRef.current.id = null; dragRef.current.colKey = null;
      if (srcId && srcCol !== colKey) moveToColumn(srcId, colKey);
    },
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      <div style={{ display: 'flex', gap: 16, padding: '8px 2px', marginBottom: 4, fontSize: 11, color: 'var(--txt3)' }}>
        <span>{chapters.length} chapters</span>
        <span style={{ color: '#fbbf24' }}>{totalActive} in progress</span>
        <span style={{ color: 'var(--accent)' }}>{totalDone} completed</span>
        <span style={{ marginLeft: 'auto', fontSize: 10.5 }}>double-click to rename · drag to reorder or change status</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        {STATUS_COLS.map(col => (
          <div
            key={col.key}
            style={{ background: 'var(--surface)', border: '1px solid var(--brd)', borderTop: `2px solid ${col.color}`, borderRadius: 8, display: 'flex', flexDirection: 'column', minHeight: 120 }}
            {...columnDropProps(col.key)}
          >
            <div style={{ padding: '10px 12px 8px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: col.color, textTransform: 'uppercase', letterSpacing: '.05em' }}>{col.label}</span>
              <span style={{ fontSize: 10.5, color: 'var(--txt3)', background: 'var(--surface2)', borderRadius: 10, padding: '1px 7px' }}>{byStatus[col.key].length}</span>
            </div>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6, padding: '4px 8px 10px' }}>
              {byStatus[col.key].length === 0 ? (
                <div style={{ fontSize: 11.5, color: 'var(--txt3)', textAlign: 'center', padding: '20px 8px', opacity: 0.5 }}>
                  drop here
                </div>
              ) : (
                <Reorderable
                  items={byStatus[col.key]}
                  itemKey={ch => ch.id}
                  colKey={col.key}
                  onReorder={reorderInColumn}
                  onDragToColumn={moveToColumn}
                  dragRef={dragRef}
                  renderItem={(ch) => (
                    <RoadmapCard
                      chapter={ch}
                      colColor={col.color}
                      allChapters={chapters}
                      onClick={() => onChapterClick(ch)}
                      onRename={(title) => renameChapter(ch.id, title)}
                      onDelete={(e) => { e.stopPropagation(); deleteChapter(ch.id); }}
                      onGenerate={() => onGenerateChapter?.(ch.id)}
                      onEditDesc={() => onEditChapterDesc?.(ch.id)}
                    />
                  )}
                />
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RoadmapCard({ chapter: ch, colColor, onClick, allChapters, onRename, onDelete, onGenerate, onEditDesc }) {
  const [hovered, setHovered] = useState(false);
  const progress     = ch.progress_pct || 0;
  const done         = ch.status === 'completed';
  const active       = ch.status === 'in_progress';
  const inReview     = ch.status === 'review';
  const topicCount   = (ch.topics || []).length;
  const conceptCount = (ch.topics || []).reduce((a, t) => a + (t.concepts || []).length, 0);
  const circ   = 2 * Math.PI * 10;
  const offset = circ - (progress / 100) * circ;
  const chIdx  = allChapters.findIndex(c => c.id === ch.id);

  return (
    <div
      onClick={onClick}
      style={{
        background: active ? 'rgba(251,191,36,0.06)' : done ? 'rgba(74,222,128,0.05)' : 'var(--surface2)',
        border: `1px solid ${active ? 'rgba(251,191,36,0.3)' : done ? 'rgba(74,222,128,0.25)' : 'var(--brd)'}`,
        borderRadius: 7, padding: '10px 12px',
        cursor: 'pointer',
        transition: 'border-color 0.15s, box-shadow 0.15s',
        userSelect: 'none',
      }}
      onMouseEnter={e => { setHovered(true); e.currentTarget.style.boxShadow = '0 2px 12px rgba(0,0,0,0.25)'; e.currentTarget.style.borderColor = colColor; }}
      onMouseLeave={e => { setHovered(false); e.currentTarget.style.boxShadow = ''; e.currentTarget.style.borderColor = active ? 'rgba(251,191,36,0.3)' : done ? 'rgba(74,222,128,0.25)' : inReview ? 'rgba(56,189,248,0.3)' : 'var(--brd)'; }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 7, gap: 6 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
            <div style={{ fontSize: 10, color: 'var(--txt3)' }}>#{chIdx + 1}</div>
            <DropdownMenu
              trigger={<span style={{ padding: '0 6px', color: 'var(--txt3)', fontSize: 14 }}>⋮</span>}
              items={[
                { label: 'Edit Description', onClick: (e) => { e?.stopPropagation?.(); onEditDesc?.(); } },
                { label: 'Generate Topics (LLM)', onClick: (e) => { e?.stopPropagation?.(); onGenerate?.(); } },
                { label: 'Delete', danger: true, onClick: (e) => onDelete?.(e) }
              ]}
            />
          </div>
          <InlineEdit
            value={ch.title}
            onSave={onRename}
            style={{ fontSize: 12.5, fontWeight: 600, color: done ? 'var(--accent)' : active ? '#fbbf24' : 'var(--txt)', lineHeight: 1.35, display: 'block' }}
          />
        </div>
        <svg width="26" height="26" viewBox="0 0 26 26" style={{ flexShrink: 0 }}>
          <circle cx="13" cy="13" r="10" fill="none" stroke="var(--brd2)" strokeWidth="2.5"/>
          {progress > 0 && (
            <circle cx="13" cy="13" r="10" fill="none" stroke={colColor} strokeWidth="2.5"
              strokeDasharray={circ.toFixed(2)} strokeDashoffset={offset.toFixed(2)}
              strokeLinecap="round" style={{ transform: 'rotate(-90deg)', transformOrigin: 'center' }} />
          )}
          {done ? (
            <path d="M8.5 13l3 3 6-6" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          ) : (
            <text x="13" y="17" textAnchor="middle" fontSize="7" fontFamily="var(--mono)" fill={progress > 0 ? colColor : 'var(--txt3)'}>
              {progress > 0 ? `${Math.round(progress)}` : '·'}
            </text>
          )}
        </svg>
      </div>
      {ch.description && hovered && (
        <div style={{ fontSize: 11, color: 'var(--txt3)', marginBottom: 7, lineHeight: 1.4 }}>
          {ch.description}
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, paddingTop: 4 }}>
        {topicCount > 0 && (
          <span style={{ fontSize: 10, color: 'var(--txt3)', background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 4, padding: '1px 5px' }}>
            {topicCount}t
          </span>
        )}
        {conceptCount > 0 && (
          <span style={{ fontSize: 10, color: 'var(--txt3)', background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 4, padding: '1px 5px' }}>
            {conceptCount}c
          </span>
        )}
        {active && <span style={{ fontSize: 10, color: '#fbbf24', marginLeft: 'auto' }}>active</span>}
      </div>
    </div>
  );
}

// ── Spaces router ─────────────────────────────────────────────
export default function Spaces() {
  const { spacesView } = useStore();
  if (spacesView === 'home')    return <SpaceHome />;
  if (spacesView === 'chapter') return <ChapterView />;
  if (spacesView === 'topic')   return <TopicView />;
  return <SpacesList />;
}

// ── Spaces list ───────────────────────────────────────────────
function SpacesList() {
  const [spaces, setSpaces]     = useState([]);
  const [loading, setLoading]   = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ dir: '', type: 'data_science', name: '', bg: '', goal: '', rag: false });
  const { setSpacesView, setCurrentSpace, setSpaceRoadmap, ok, err } = useStore();

  useEffect(() => { load(); }, []);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api('/spaces');
      setSpaces(Array.isArray(r) ? r : r?.spaces ?? r?.items ?? []);
    } catch (e) { err(e.message); }
    setLoading(false);
  };

  const create = async () => {
    if (!form.dir.trim()) { err('Directory required'); return; }
    try {
      await api('/spaces/init', { method: 'POST', body: JSON.stringify({
        directory: form.dir, space_type: form.type, name: form.name,
        background: form.bg, goal: form.goal, rag_enabled: form.rag,
      }) });
      ok('Space created'); setShowCreate(false); load();
    } catch (e) { err(e.message); }
  };

  const patchForm = (patch) => setForm(f => ({ ...f, ...patch }));

  const toggleActive = async (space, activate) => {
    if (!activate) {
      // No deactivate endpoint — just reload to reflect current state
      ok(`${space.name} deactivated`);
      setSpaces(ss => ss.map(s => ({ ...s, is_active: false })));
      return;
    }
    try {
      await api('/spaces/activate', { method: 'POST', body: JSON.stringify({ directory: space.directory }) });
      ok(`${space.name} set as active space`);
      load();
    } catch (e) { err(e.message); }
  };

  return (
    <div className="page">
      <header className="pg-header">
        <div className="pg-title-group">
          <h1 className="pg-title">Spaces</h1>
          <p className="pg-sub">Mastery-learning workspaces</p>
        </div>
        <div className="pg-actions">
          <button className="btn btn-accent btn-sm" onClick={() => setShowCreate(true)}>+ New Space</button>
        </div>
      </header>

      <div className="pg-body">
        {loading ? (
          <div className="loading-center"><span className="spin" /></div>
        ) : spaces.length === 0 ? (
          <div className="empty">
            <div className="empty-ttl">No spaces yet</div>
            <div className="empty-desc">Create a mastery workspace to start structured learning.</div>
            <button className="btn btn-accent btn-sm" style={{ marginTop: 12 }} onClick={() => setShowCreate(true)}>Create First Space</button>
          </div>
        ) : (
          <div className="spaces-grid">
            {spaces.map(s => <SpaceCard key={s.name || s.id} space={s} onClick={() => { setCurrentSpace(s); setSpaceRoadmap(null); setSpacesView('home'); }} onToggleActive={toggleActive} />)}
          </div>
        )}
      </div>

      {showCreate && (
        <Modal title="Create Space" onClose={() => setShowCreate(false)} footer={
          <>
            <button className="btn btn-muted btn-sm" onClick={() => setShowCreate(false)}>Cancel</button>
            <button className="btn btn-accent btn-sm" onClick={create}>Create Space</button>
          </>
        }>
          <div>
            <label className="form-label">Workspace directory *</label>
            <input className="s-input mono" value={form.dir} onChange={e => patchForm({ dir: e.target.value })} placeholder="/home/user/my-project" />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <div>
              <label className="form-label">Type</label>
              <select className="s-select" value={form.type} onChange={e => patchForm({ type: e.target.value })}>
                {['data_science','ai_engineering','software_engineering','medicine','education','exam_prep','research','custom'].map(t => (
                  <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="form-label">Display name</label>
              <input className="s-input" value={form.name} onChange={e => patchForm({ name: e.target.value })} placeholder="My Space" />
            </div>
          </div>
          <div>
            <label className="form-label">Your background</label>
            <input className="s-input" value={form.bg} onChange={e => patchForm({ bg: e.target.value })} placeholder="e.g. software engineer, 2yr Python" />
          </div>
          <div>
            <label className="form-label">Learning goal</label>
            <input className="s-input" value={form.goal} onChange={e => patchForm({ goal: e.target.value })} placeholder="e.g. master ML for GATE exam" />
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--txt2)', cursor: 'pointer' }}>
            <input type="checkbox" checked={form.rag} onChange={e => patchForm({ rag: e.target.checked })} />
            Enable RAG (vector search)
          </label>
        </Modal>
      )}
    </div>
  );
}

function SpaceCard({ space: s, onClick, onToggleActive }) {
  const progress = s.progress || 0;
  const circ     = 2 * Math.PI * 16;
  const offset   = circ - (progress / 100) * circ;
  const dirShort = s.directory?.split('/').pop() || '';
  const isActive = !!s.is_active;
  return (
    <div className="space-card" onClick={onClick} style={{ border: isActive ? '1px solid var(--accent-border)' : undefined }}>
      <div className="space-card-head">
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="space-card-name" style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            {s.name || 'Unnamed'}
            {isActive && <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--accent)', background: 'var(--accent-dim)', border: '1px solid var(--accent-border)', borderRadius: 4, padding: '1px 6px', letterSpacing: '0.04em' }}>ACTIVE</span>}
          </div>
          {dirShort && <div className="space-card-dir">~/{dirShort}</div>}
        </div>
        <div className="prog-ring">
          <svg width="44" height="44" viewBox="0 0 44 44" style={{ transform: 'rotate(-90deg)' }}>
            <circle cx="22" cy="22" r="16" fill="none" stroke="var(--brd2)" strokeWidth="3" />
            <circle cx="22" cy="22" r="16" fill="none" stroke="var(--accent)" strokeWidth="3"
              strokeDasharray={circ.toFixed(2)} strokeDashoffset={offset.toFixed(2)} strokeLinecap="round" />
          </svg>
          <div className="prog-ring-text">{progress}%</div>
        </div>
      </div>
      <div className="space-card-desc">{s.description || s.goal || 'Mastery workspace'}</div>
      <div className="space-card-foot">
        <span className="badge badge-muted">{(s.space_type || s.type || 'custom').replace(/_/g, ' ')}</span>
        <button
          className={`btn btn-sm ${isActive ? 'btn-muted' : 'btn-accent'}`}
          style={{ marginLeft: 'auto', fontSize: 11, padding: '2px 10px' }}
          onClick={e => { e.stopPropagation(); onToggleActive(s, !isActive); }}
        >
          {isActive ? 'Deactivate' : 'Set Active'}
        </button>
      </div>
    </div>
  );
}

// ── Space Home ────────────────────────────────────────────────
function SpaceHome() {
  const { currentSpace, spaceRoadmap, setSpaceRoadmap, setCurrentChapter, setCurrentTopic, setSpacesView, ok, err } = useStore();
  const [hero, setHero]         = useState(null);
  const [sessions, setSessions] = useState([]);
  const [activePanel, setActivePanel] = useState(null);
  const [showHistory, setShowHistory] = useState(false);
  const [addingChapter, setAddingChapter] = useState(false);
  const [newChapterTitle, setNewChapterTitle] = useState('');
  const [newChapterDesc, setNewChapterDesc] = useState('');
  const [promptBar, setPromptBar] = useState(null);

  const sid = encodeURIComponent(currentSpace?.name || '');

  useEffect(() => {
    if (!currentSpace) return;
    loadHero();
    if (!spaceRoadmap) loadRoadmap();
  }, [currentSpace?.name]);

  useEffect(() => {
    loadSessions();
  }, [spaceRoadmap]);

  const loadHero = async () => { try { setHero(await api(`/spaces/${sid}/profile`)); } catch {} };
  const loadRoadmap  = async () => { try { setSpaceRoadmap(await api(`/spaces/${sid}/roadmap`)); } catch {} };
  const loadSessions = () => {
    // Use roadmap sessions which are actual learning sessions with concept/xp data
    if (spaceRoadmap?.sessions) {
      setSessions([...(spaceRoadmap.sessions)].reverse().slice(0, 20));
    }
  };

  /**
   * Persist updated chapters to the API and local store.
   * Sets `order` from array position before sending.
   */
  const patchChapters = async (chapters) => {
    const withOrder = chapters.map((c, i) => ({ ...c, order: i }));
    try {
      const rm = await api(`/spaces/${sid}/roadmap`, { method: 'PATCH', body: JSON.stringify({ chapters: withOrder }) });
      setSpaceRoadmap(rm);
    } catch (e) { err(e.message); }
  };

  const patchChapter = async (updatedChapter) => {
    const chapters = (spaceRoadmap?.chapters || []).map(c =>
      c.id === updatedChapter.id ? updatedChapter : c
    );
    await patchChapters(chapters);
  };

  const addChapter = async () => {
    const title = newChapterTitle.trim();
    if (!title) return;
    const ch = {
      id: `ch_${Date.now().toString(36)}`, title, description: newChapterDesc.trim(),
      order: spaceRoadmap?.chapters?.length || 0,
      status: 'not_started', progress_pct: 0, topics: [],
    };
    await patchChapters([...(spaceRoadmap?.chapters || []), ch]);
    ok(`Chapter "${title}" added`);
    setNewChapterTitle('');
    setNewChapterDesc('');
    setAddingChapter(false);
  };

  const generateChapterTopics = async (chId, instruction = '') => {
    try {
      ok("Generating topics and concepts. This may take a moment...");
      const ch = (spaceRoadmap?.chapters || []).find(c => c.id === chId);
      if (!ch) return;
      const r = await api(`/spaces/${sid}/roadmap/generate-children`, {
        method: 'POST',
        body: JSON.stringify({ parent_type: 'chapter', parent_title: ch.title, instruction: instruction.trim() }),
      });
      const topicTitles = (r.children || []).filter(Boolean);
      const baseId = Date.now().toString(36);
      const newTopics = [];
      for (let i = 0; i < topicTitles.length; i++) {
        const tTitle = topicTitles[i];
        let concepts = [];
        try {
          const cRes = await api(`/spaces/${sid}/roadmap/generate-children`, {
            method: 'POST',
            body: JSON.stringify({ parent_type: 'topic', parent_title: tTitle, instruction: instruction.trim() }),
          });
          concepts = (cRes.children || []).filter(Boolean).map((cTitle, j) => ({
            id: `cn_${baseId}_${i}_${j}`,
            title: cTitle,
            description: '',
            status: 'not_started',
            order: j,
            tags: [],
            related_concepts: [],
            notes: [],
            quicktests: [],
          }));
        } catch {}
        newTopics.push({
          id: `tp_${baseId}_${i}`,
          title: tTitle,
          order: (ch.topics || []).length + i,
          status: 'not_started',
          concepts,
        });
      }
      await patchChapter({ ...ch, topics: [...(ch.topics || []), ...newTopics] });
      ok("Topics and concepts generated successfully.");
    } catch (e) { err(e.message); }
  };

  const editChapterDescription = async (chId, next) => {
    const ch = (spaceRoadmap?.chapters || []).find(c => c.id === chId);
    if (!ch) return;
    await patchChapter({ ...ch, description: next.trim() });
    ok("Chapter description updated.");
  };

  if (!currentSpace) return null;

  const continueLearning = (() => {
    if (!spaceRoadmap?.chapters) return null;
    const lastSession = sessions[0];
    if (lastSession?.concept) {
      for (const ch of spaceRoadmap.chapters) {
        for (const tp of ch.topics || []) {
          const cn = (tp.concepts || []).find(c => c.title === lastSession.concept);
          if (cn) {
            const cns = tp.concepts || [];
            const done = cns.filter(c => c.status === 'completed').length;
            const pct = cns.length ? Math.round((done / cns.length) * 100) : 0;
            return { chapter: ch, topic: tp, concept: lastSession.concept, pct };
          }
        }
      }
    }
    const inProgress = spaceRoadmap.chapters.find(c => c.status === 'in_progress');
    if (inProgress) return { chapter: inProgress, topic: null, concept: null, pct: inProgress.progress_pct || 0 };
    return null;
  })();

  const goToContinue = () => {
    if (!continueLearning) return;
    setCurrentChapter({ id: continueLearning.chapter.id, title: continueLearning.chapter.title, data: continueLearning.chapter });
    if (continueLearning.topic) {
      setCurrentTopic({ ...continueLearning.topic, chapterId: continueLearning.chapter.id });
      setSpacesView('topic');
    } else {
      setSpacesView('chapter');
    }
  };

  const panels = [
    { id: 'notes', label: 'Notes' }, { id: 'tasks', label: 'Tasks' },
    { id: 'files', label: 'Workspace' }, { id: 'srs', label: 'SRS' },
    { id: 'graph', label: 'Graph' }, { id: 'digest', label: 'Digest' },
    { id: 'practice', label: 'Practice' }, { id: 'optimizer', label: 'Insights' },
    { id: 'agents', label: 'Agents' },
  ];

  const progress = (() => {
    const chs = spaceRoadmap?.chapters || [];
    if (!chs.length) return 0;
    return Math.round(chs.reduce((a, c) => a + (c.progress_pct || 0), 0) / chs.length);
  })();

  return (
    <div className="page">
      <div className="space-home-hdr">
        <div className="sh-left">
          <nav className="breadcrumb">
            <button className="bc-link" onClick={() => setSpacesView('list')}>Spaces</button>
            <span className="bc-sep">›</span>
            <span className="bc-current">{currentSpace.name}</span>
          </nav>
          <h1 className="pg-title">{currentSpace.name}</h1>
          {hero?.domain && <p className="pg-sub">{hero.domain}</p>}
        </div>

        <div className="sh-right">
          <div className="progress-ring-wrap">
            <svg width="64" height="64" viewBox="0 0 64 64">
              <circle cx="32" cy="32" r="26" className="progress-ring-bg" />
              <circle cx="32" cy="32" r="26" className="progress-ring-fg"
                style={{ strokeDasharray: `${2 * Math.PI * 26}`, strokeDashoffset: `${2 * Math.PI * 26 * (1 - progress / 100)}`, transform: 'rotate(-90deg)', transformOrigin: 'center' }} />
            </svg>
            <div className="ring-label">
              <div className="ring-pct">{progress}%</div>
              <div className="ring-done">done</div>
            </div>
          </div>
          {hero && (
            <div className="sh-stats">
              <span className="hero-stat"><strong>{hero.xp || 0}</strong> XP</span>
              <span className="hero-stat"><strong>{hero.streak_days || 0}d</strong> streak</span>
              <span className="hero-stat"><strong>{hero.session_count || hero.total_sessions || 0}</strong> sessions</span>
            </div>
          )}
          <div className="sh-actions">
            {panels.map(p => (
              <button key={p.id} className="btn btn-muted btn-sm" onClick={() => setActivePanel({ name: p.id, props: {} })}>
                {p.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="space-home-body">
        <div className="roadmap-section">
          <div className="roadmap-section-hdr">
            <span className="roadmap-section-title">Roadmap</span>
            <span className="roadmap-hint">double-click to rename · drag within/between columns</span>
            {addingChapter ? (
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                <input
                  className="s-input"
                  style={{ width: 200, fontSize: 12, padding: '3px 8px' }}
                  autoFocus
                  value={newChapterTitle}
                  onChange={e => setNewChapterTitle(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter') addChapter();
                    if (e.key === 'Escape') { setAddingChapter(false); setNewChapterTitle(''); setNewChapterDesc(''); }
                  }}
                  placeholder="Chapter title…"
                />
                <input
                  className="s-input"
                  style={{ width: 280, fontSize: 12, padding: '3px 8px' }}
                  value={newChapterDesc}
                  onChange={e => setNewChapterDesc(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Escape') { setAddingChapter(false); setNewChapterTitle(''); setNewChapterDesc(''); } }}
                  placeholder="Short description…"
                />
                <button className="btn btn-accent btn-sm" onClick={addChapter}>Add</button>
                <button className="btn btn-muted btn-sm" onClick={() => { setAddingChapter(false); setNewChapterTitle(''); setNewChapterDesc(''); }}>Cancel</button>
              </div>
            ) : (
              <div style={{ display: 'flex', gap: 6 }}>
                <button className="tb-btn" onClick={() => setShowHistory(true)}>History</button>
                <button className="tb-btn" onClick={() => setAddingChapter(true)}>+ Chapter</button>
              </div>
            )}
          </div>
          {promptBar?.type === 'chapter_generate' && (
            <PromptInline
              title={`Generate topics for: ${promptBar.title}`}
              value={promptBar.value}
              onChange={(v) => setPromptBar(p => ({ ...p, value: v }))}
              onSubmit={async () => {
                const payload = promptBar;
                setPromptBar(null);
                await generateChapterTopics(payload.chId, payload.value || '');
              }}
              onCancel={() => setPromptBar(null)}
              placeholder="Optional instructions for topic generation…"
              submitLabel="Generate"
              multiline
            />
          )}
          {promptBar?.type === 'chapter_desc' && (
            <PromptInline
              title={`Edit description: ${promptBar.title}`}
              value={promptBar.value}
              onChange={(v) => setPromptBar(p => ({ ...p, value: v }))}
              onSubmit={async () => {
                const payload = promptBar;
                setPromptBar(null);
                await editChapterDescription(payload.chId, payload.value || '');
              }}
              onCancel={() => setPromptBar(null)}
              placeholder="Short description…"
              submitLabel="Save"
              multiline={false}
            />
          )}
          {continueLearning && (
            <div
              onClick={goToContinue}
              style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '10px 16px', marginBottom: 14, background: 'var(--surface)', border: '1px solid var(--accent-border)', borderRadius: 10, cursor: 'pointer', transition: 'background 0.15s' }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--accent-dim)'}
              onMouseLeave={e => e.currentTarget.style.background = 'var(--surface)'}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 10, color: 'var(--accent)', fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase', marginBottom: 3 }}>Continue Learning</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--txt)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {continueLearning.topic?.title || continueLearning.chapter.title}
                  {continueLearning.concept && <span style={{ fontSize: 11, color: 'var(--txt3)', marginLeft: 8 }}>— {continueLearning.concept}</span>}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
                <div style={{ fontSize: 12, color: 'var(--txt2)' }}>{continueLearning.pct}%</div>
                <div style={{ width: 64, height: 4, background: 'var(--surface2)', borderRadius: 2, overflow: 'hidden' }}>
                  <div style={{ width: `${continueLearning.pct}%`, height: '100%', background: 'var(--accent)', borderRadius: 2 }} />
                </div>
                <span style={{ color: 'var(--accent)', fontSize: 16, lineHeight: 1 }}>&#8594;</span>
              </div>
            </div>
          )}
          <RoadmapBoard
            roadmap={spaceRoadmap}
            onChapterClick={(chData) => { setCurrentChapter({ id: chData.id, title: chData.title, data: chData }); setSpacesView('chapter'); }}
            onAddChapter={() => setAddingChapter(true)}
            onPatchChapters={patchChapters}
            onGenerateChapter={(chId) => {
              const ch = (spaceRoadmap?.chapters || []).find(c => c.id === chId);
              if (!ch) return;
              setPromptBar({ type: 'chapter_generate', chId, title: ch.title, value: '' });
            }}
            onEditChapterDesc={(chId) => {
              const ch = (spaceRoadmap?.chapters || []).find(c => c.id === chId);
              if (!ch) return;
              setPromptBar({ type: 'chapter_desc', chId, title: ch.title, value: ch.description || '' });
            }}
          />
        </div>

        <div className="rec-strip">
          <span className="rec-title">Up Next</span>
          <span className="rec-body">No recommendations yet.</span>
        </div>
      </div>

      {activePanel && (
        <PanelHost panel={activePanel} onClose={() => setActivePanel(null)} space={currentSpace} spaceId={sid} spaceRoadmap={spaceRoadmap} refreshHero={loadHero} />
      )}

      {showHistory && (
        <Overlay title="Session History" onClose={() => setShowHistory(false)} width="520px" height="65%">
          {sessions.length === 0 ? (
            <div style={{ color: 'var(--txt3)', fontSize: 13, padding: '32px 0', textAlign: 'center' }}>No sessions yet.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {sessions.map((s, i) => {
                const goToConcept = () => {
                  if (!spaceRoadmap?.chapters) return;
                  for (const ch of spaceRoadmap.chapters) {
                    for (const tp of ch.topics || []) {
                      const cn = (tp.concepts || []).find(c => c.title === s.concept);
                      if (cn) {
                        setCurrentChapter({ id: ch.id, title: ch.title, data: ch });
                        setCurrentTopic({ ...tp, chapterId: ch.id, _openConceptId: cn.id });
                        setSpacesView('topic');
                        setShowHistory(false);
                        return;
                      }
                    }
                  }
                  const ch = spaceRoadmap.chapters[0];
                  if (ch) { setCurrentChapter({ id: ch.id, title: ch.title, data: ch }); setSpacesView('chapter'); setShowHistory(false); }
                };
                return (
                  <div
                    key={i}
                    onClick={goToConcept}
                    style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', borderRadius: 8, cursor: 'pointer', border: '1px solid var(--brd)', background: 'var(--surface)', transition: 'background 0.12s' }}
                    onMouseEnter={e => e.currentTarget.style.background = 'var(--surface2)'}
                    onMouseLeave={e => e.currentTarget.style.background = 'var(--surface)'}
                  >
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--txt)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.concept || 'Session'}</div>
                      <div style={{ fontSize: 11, color: 'var(--txt3)', marginTop: 2 }}>{fmt(s.timestamp || s.ts)}</div>
                    </div>
                    <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: 12 }}>
                      {s.xp_earned ? <div style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 600 }}>+{s.xp_earned} XP</div> : null}
                      {s.level ? <div style={{ fontSize: 11, color: 'var(--txt3)' }}>{s.level}</div> : null}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Overlay>
      )}
    </div>
  );
}

// ── Chapter View ──────────────────────────────────────────────
function ChapterView() {
  const { currentSpace, currentChapter, setCurrentChapter, setCurrentTopic, setSpacesView, setSpaceRoadmap, spaceRoadmap, ok, err } = useStore();
  const [noteVal, setNoteVal]     = useState('');
  const [noteId, setNoteId]       = useState(null);
  const [tab, setTab]             = useState('topics');
  const [addingTopic, setAddingTopic] = useState(false);
  const [newTopicTitle, setNewTopicTitle] = useState('');
  const [promptBar, setPromptBar] = useState(null);

  const spaceId = encodeURIComponent(currentSpace?.name || '');
  const noteKey = `notes:${currentSpace?.name}:${currentChapter?.id}`;

  useEffect(() => {
    setNoteVal(localStorage.getItem(noteKey) || '');
    setNoteId(null);
    if (!spaceId || !currentChapter?.id) return;
    api(`/spaces/${spaceId}/notes?type=chapter_note&concept_id=${encodeURIComponent(currentChapter.id)}`)
      .then(r => {
        const list = Array.isArray(r) ? r : r.notes || [];
        if (list.length) { setNoteVal(list[0].body_md || ''); setNoteId(list[0].id); }
      }).catch(() => {});
  }, [noteKey, spaceId, currentChapter?.id]);

  // Live chapter data from roadmap store (updated on every patch)
  const getChapter = () =>
    (spaceRoadmap?.chapters || []).find(c => c.id === currentChapter?.id)
    || currentChapter?.data || {};

  const patchRoadmapChapter = async (updatedChapter) => {
    const chapters = (spaceRoadmap?.chapters || []).map(c =>
      c.id === updatedChapter.id ? updatedChapter : c
    );
    const withOrder = chapters.map((c, i) => ({ ...c, order: i }));
    try {
      const rm = await api(`/spaces/${spaceId}/roadmap`, { method: 'PATCH', body: JSON.stringify({ chapters: withOrder }) });
      setSpaceRoadmap(rm);
      setCurrentChapter(prev => ({ ...prev, title: updatedChapter.title, data: updatedChapter }));
    } catch {}
  };

  const addTopic = async () => {
    const title = newTopicTitle.trim();
    if (!title) return;
    const ch = getChapter();
    const topic = { id: `tp_${Date.now().toString(36)}`, title, order: (ch.topics || []).length, concepts: [] };
    await patchRoadmapChapter({ ...ch, topics: [...(ch.topics || []), topic] });
    setNewTopicTitle('');
    setAddingTopic(false);
  };

  const generateTopics = async (instruction = '') => {
    try {
      ok("Generating topics and concepts. This may take a moment...");
      const ch = getChapter();
      const r = await api(`/spaces/${spaceId}/roadmap/generate-children`, {
        method: 'POST', body: JSON.stringify({ parent_type: 'chapter', parent_title: ch.title, instruction: instruction.trim() })
      });
      const topicTitles = (r.children || []).filter(Boolean);
      const baseId = Date.now().toString(36);
      const newTopics = [];
      for (let i = 0; i < topicTitles.length; i++) {
        const tTitle = topicTitles[i];
        let concepts = [];
        try {
          const cRes = await api(`/spaces/${spaceId}/roadmap/generate-children`, {
            method: 'POST',
            body: JSON.stringify({ parent_type: 'topic', parent_title: tTitle, instruction: instruction.trim() }),
          });
          concepts = (cRes.children || []).filter(Boolean).map((cTitle, j) => ({
            id: `cn_${baseId}_${i}_${j}`,
            title: cTitle,
            description: '',
            status: 'not_started',
            order: j,
            tags: [],
            related_concepts: [],
            notes: [],
            quicktests: [],
          }));
        } catch {}
        newTopics.push({
          id: `tp_${baseId}_${i}`,
          title: tTitle,
          order: (ch.topics || []).length + i,
          status: 'not_started',
          concepts,
        });
      }
      await patchRoadmapChapter({ ...ch, topics: [...(ch.topics || []), ...newTopics] });
      ok("Topics and concepts generated successfully.");
    } catch (e) { err(e.message); }
  };

  const renameTopic = async (tpId, title) => {
    const ch = getChapter();
    await patchRoadmapChapter({ ...ch, topics: (ch.topics || []).map(t => t.id === tpId ? { ...t, title } : t) });
  };

  const reorderTopics = async (topics) => {
    const ch = getChapter();
    await patchRoadmapChapter({ ...ch, topics: topics.map((t, i) => ({ ...t, order: i })) });
  };

  const [addingConceptTpId, setAddingConceptTpId] = useState(null);
  const [newConceptTitle, setNewConceptTitle] = useState('');

  const addConcept = async (tpId, title) => {
    const trimmed = (title || '').trim();
    if (!trimmed) return;
    const ch = getChapter();
    await patchRoadmapChapter({
      ...ch,
      topics: (ch.topics || []).map(t => {
        if (t.id !== tpId) return t;
        const cn = { id: `cn_${Date.now().toString(36)}`, title: trimmed, description: '', status: 'not_started', order: (t.concepts || []).length };
        return { ...t, concepts: [...(t.concepts || []), cn] };
      }),
    });
    setAddingConceptTpId(null);
    setNewConceptTitle('');
  };

  const generateConcepts = async (tpId, instruction = '') => {
    try {
      ok("Generating concepts. This may take a moment...");
      const ch = getChapter();
      const topic = (ch.topics || []).find(t => t.id === tpId);
      if (!topic) return;
      
      const r = await api(`/spaces/${spaceId}/roadmap/generate-children`, {
        method: 'POST', body: JSON.stringify({ parent_type: 'topic', parent_title: topic.title, instruction: instruction.trim() })
      });
      const newConcepts = (r.children || []).map((cTitle, i) => ({
        id: `cn_${Date.now().toString(36)}_${i}`, title: cTitle, description: '', status: 'not_started', order: (topic.concepts || []).length + i
      }));
      
      await patchRoadmapChapter({
        ...ch,
        topics: (ch.topics || []).map(t =>
          t.id !== tpId ? t : { ...t, concepts: [...(t.concepts || []), ...newConcepts] }
        )
      });
      ok("Concepts generated successfully.");
    } catch (e) { err(e.message); }
  };

  const renameConcept = async (tpId, cnId, title) => {
    const ch = getChapter();
    await patchRoadmapChapter({
      ...ch,
      topics: (ch.topics || []).map(t =>
        t.id !== tpId ? t : { ...t, concepts: (t.concepts || []).map(cn => cn.id === cnId ? { ...cn, title } : cn) }
      ),
    });
  };

  const reorderConcepts = async (tpId, concepts) => {
    const ch = getChapter();
    await patchRoadmapChapter({
      ...ch,
      topics: (ch.topics || []).map(t =>
        t.id !== tpId ? t : { ...t, concepts: concepts.map((cn, i) => ({ ...cn, order: i })) }
      ),
    });
  };

  const deleteTopic = async (tpId) => {
    if (!confirm('Delete this topic and all its concepts?')) return;
    const ch = getChapter();
    await patchRoadmapChapter({ ...ch, topics: (ch.topics || []).filter(t => t.id !== tpId) });
  };

  const deleteConcept = async (tpId, cnId) => {
    if (!confirm('Delete this concept?')) return;
    const ch = getChapter();
    await patchRoadmapChapter({
      ...ch,
      topics: (ch.topics || []).map(t =>
        t.id !== tpId ? t : { ...t, concepts: (t.concepts || []).filter(cn => cn.id !== cnId) }
      ),
    });
  };

  const saveNotes = async (val) => {
    localStorage.setItem(noteKey, val);
    localStorage.setItem(`${noteKey}:hist:${Date.now()}`, val.slice(0, 4000));
    try {
      if (noteId) {
        await api(`/spaces/${spaceId}/notes/${noteId}`, {
          method: 'PUT',
          body: JSON.stringify({ title: `Chapter: ${currentChapter?.title || ''}`, body_md: val }),
        });
      } else {
        const saved = await api(`/spaces/${spaceId}/notes`, {
          method: 'POST',
          body: JSON.stringify({ type: 'chapter_note', concept_id: currentChapter?.id || '', title: `Chapter: ${currentChapter?.title || ''}`, body_md: val }),
        });
        if (saved?.id) setNoteId(saved.id);
      }
    } catch {}
    ok(`Notes saved (${val.trim().split(/\s+/).filter(Boolean).length}w)`);
  };

  const topics = getChapter().topics || currentChapter?.data?.topics || [];
  const wordCount = noteVal.trim().split(/\s+/).filter(Boolean).length;

  if (!currentChapter) return null;

  return (
    <div className="page">
      <header className="pg-header">
        <div className="pg-title-group">
          <nav className="breadcrumb">
            <button className="bc-link" onClick={() => setSpacesView('list')}>Spaces</button>
            <span className="bc-sep">›</span>
            <button className="bc-link" onClick={() => setSpacesView('home')}>{currentSpace?.name}</button>
            <span className="bc-sep">›</span>
            <span className="bc-current">{currentChapter.title}</span>
          </nav>
          <h1 className="pg-title">{currentChapter.title}</h1>
        </div>
        <div className="pg-actions">
          <button className="btn btn-muted btn-sm" onClick={() => setSpacesView('home')}>Back</button>
        </div>
      </header>

      <div className="chapter-body" style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div className="topic-tab-bar" style={{ padding: '0 24px' }}>
          {['topics', 'notes', 'sessions'].map(t => (
            <button key={t} className={`td-tab${tab === t ? ' active' : ''}`} onClick={() => setTab(t)}>
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
          {tab === 'topics' && (
            <>
              <button className="btn btn-muted btn-sm" style={{ marginLeft: 'auto' }} onClick={() => setPromptBar({ type: 'topic_generate', value: '' })}>
                Generate (LLM)
              </button>
              <button className="btn btn-accent btn-sm" onClick={() => setAddingTopic(true)}>+ Topic</button>
            </>
          )}
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: 24, background: 'var(--surface2)' }}>
          {promptBar?.type === 'topic_generate' && (
            <PromptInline
              title={`Generate topics for: ${currentChapter.title}`}
              value={promptBar.value}
              onChange={(v) => setPromptBar(p => ({ ...p, value: v }))}
              onSubmit={async () => {
                const payload = promptBar;
                setPromptBar(null);
                await generateTopics(payload.value || '');
              }}
              onCancel={() => setPromptBar(null)}
              placeholder="Optional instructions for topic generation…"
              submitLabel="Generate"
              multiline
            />
          )}
          {promptBar?.type === 'concept_generate' && (
            <PromptInline
              title={`Generate concepts for: ${promptBar.title}`}
              value={promptBar.value}
              onChange={(v) => setPromptBar(p => ({ ...p, value: v }))}
              onSubmit={async () => {
                const payload = promptBar;
                setPromptBar(null);
                await generateConcepts(payload.tpId, payload.value || '');
              }}
              onCancel={() => setPromptBar(null)}
              placeholder="Optional instructions for concept generation…"
              submitLabel="Generate"
              multiline
            />
          )}
          {addingTopic && (
            <div style={{ padding: '16px', marginBottom: 24, background: 'var(--surface)', borderRadius: 8, border: '1px solid var(--brd)', display: 'flex', gap: 6 }}>
              <input
                className="s-input"
                style={{ fontSize: 13, padding: '6px 10px', flex: 1 }}
                autoFocus
                value={newTopicTitle}
                onChange={e => setNewTopicTitle(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') addTopic(); if (e.key === 'Escape') { setAddingTopic(false); setNewTopicTitle(''); } }}
                placeholder="Topic title…"
              />
              <button className="btn btn-accent" onClick={addTopic}>Add Topic</button>
              <button className="btn btn-muted" onClick={() => { setAddingTopic(false); setNewTopicTitle(''); }}>Cancel</button>
            </div>
          )}

          {tab === 'topics' && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 24 }}>
              {topics.length === 0 ? (
                <div style={{ color: 'var(--txt3)', fontSize: 13, gridColumn: '1 / -1' }}>No topics yet. Start by adding one.</div>
              ) : (
                <Reorderable
                  items={topics}
                  itemKey={tp => tp.id}
                  colKey="topics"
                  onReorder={reorderTopics}
                  renderItem={(tp) => (
                    <TopicCard
                      topic={tp}
                      onOpen={() => { setCurrentTopic({ ...tp, chapterId: currentChapter.id }); setSpacesView('topic'); }}
                      onDelete={() => deleteTopic(tp.id)}
                      onGenerate={() => setPromptBar({ type: 'concept_generate', tpId: tp.id, title: tp.title, value: '' })}
                    />
                  )}
                  style={{ display: 'contents' }}
                />
              )}
            </div>
          )}

          {tab === 'notes' && (
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--surface)', borderRadius: 8, border: '1px solid var(--brd)', overflow: 'hidden' }}>
              <MarkdownEditor value={noteVal} onChange={setNoteVal} onSave={saveNotes} placeholder={`Write chapter notes for ${currentChapter.title}…`} historyKey={noteKey} />
            </div>
          )}

          {tab === 'sessions' && (
            <div style={{ background: 'var(--surface)', borderRadius: 8, padding: 16, border: '1px solid var(--brd)', color: 'var(--txt3)', fontSize: 13 }}>
              No sessions yet for this chapter.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function TopicCard({ topic: tp, onOpen, onDelete, onGenerate }) {
  const concepts = tp.concepts || [];
  const completed = concepts.filter(c => c.status === 'completed').length;
  const progressPct = concepts.length ? Math.round((completed / concepts.length) * 100) : 0;
  const testsTaken = concepts.reduce((sum, c) => sum + ((c.quicktests || []).length), 0);
  const testedConcepts = concepts.filter(c => (c.quicktests || []).length > 0).length;
  const coveragePct = concepts.length ? Math.round((testedConcepts / concepts.length) * 100) : 0;

  return (
    <div className="topic-card" onClick={onOpen} style={{
      background: 'var(--surface)', borderRadius: 14, padding: 24, border: '1px solid var(--brd)',
      cursor: 'pointer', transition: 'all 0.2s', display: 'flex', flexDirection: 'column', gap: 18,
      boxShadow: '0 4px 14px rgba(0,0,0,0.08)', minHeight: 200
    }} onMouseEnter={e => e.currentTarget.style.transform = 'translateY(-2px)'} onMouseLeave={e => e.currentTarget.style.transform = 'none'}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <h3 style={{ margin: 0, fontSize: 18, color: 'var(--txt)', fontWeight: 650, lineHeight: 1.3 }}>{tp.title}</h3>
        <div onClick={e => e.stopPropagation()}>
          <DropdownMenu
            trigger={<button className="tb-btn" style={{ padding: '2px 6px', color: 'var(--txt3)' }}>⋮</button>}
            items={[
              { label: 'Generate Concepts (LLM)', onClick: onGenerate },
              { label: 'Delete Topic', danger: true, onClick: onDelete }
            ]}
          />
        </div>
      </div>
      
      <div style={{ flex: 1 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 6, color: 'var(--txt3)' }}>
          <span style={{ fontWeight: 600, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Concepts</span>
          <span>{completed} / {concepts.length} completed</span>
        </div>
        <div style={{ height: 4, background: 'var(--surface2)', borderRadius: 2, overflow: 'hidden' }}>
          <div style={{ width: `${progressPct}%`, height: '100%', background: 'var(--accent)', transition: 'width 0.3s' }} />
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, color: 'var(--txt2)', background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 999, padding: '3px 8px' }}>
          Tests: {testsTaken}
        </span>
        <span style={{ fontSize: 11, color: 'var(--txt2)', background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 999, padding: '3px 8px' }}>
          Coverage: {coveragePct}%
        </span>
        <span style={{ fontSize: 11, color: 'var(--txt2)', background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 999, padding: '3px 8px' }}>
          Tested concepts: {testedConcepts}/{concepts.length}
        </span>
      </div>

      <div style={{ fontSize: 12, color: 'var(--txt2)', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
        {concepts.length === 0 ? <span style={{ color: 'var(--txt3)', fontStyle: 'italic' }}>No concepts in this topic yet.</span> : concepts.map(c => c.title).join(' • ')}
      </div>
    </div>
  );
}

/** Single topic block with inline-editable title, reorderable concepts, and add-concept. */
function TopicBlock({ topic: tp, onOpen, onRename, onDelete, onGenerate, onAddConcept, onRenameConcept, onDeleteConcept, onReorderConcepts, onOpenConceptExplain, onOpenConceptTest }) {
  const [addingConcept, setAddingConcept] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [editingCnId, setEditingCnId] = useState(null);

  const commitConcept = () => {
    const t = newTitle.trim();
    if (t) onAddConcept(t);
    setAddingConcept(false);
    setNewTitle('');
  };

  return (
    <div className="topic-block">
      <div className="topic-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <InlineEdit
          value={tp.title}
          onSave={onRename}
          style={{ fontSize: 12, fontWeight: 650, color: 'var(--txt2)', textTransform: 'uppercase', letterSpacing: '.04em' }}
          placeholder="Topic title"
        />
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <button className="tb-btn" style={{ fontSize: 10.5, padding: '2px 7px' }} onClick={onOpen}>Open</button>
          <button className="tb-btn" style={{ fontSize: 10.5, padding: '2px 7px' }} onClick={() => setAddingConcept(true)}>+ Concept</button>
          <DropdownMenu
            trigger={<span style={{ padding: '0 6px', color: 'var(--txt3)', fontSize: 14 }}>⋮</span>}
            items={[
              { label: 'Generate Concepts (LLM)', onClick: (e) => onGenerate?.() },
              { label: 'Delete Topic', danger: true, onClick: (e) => onDelete?.() }
            ]}
          />
        </div>
      </div>
      {addingConcept && (
        <div style={{ display: 'flex', gap: 6, padding: '6px 14px' }}>
          <input
            className="s-input"
            style={{ flex: 1, fontSize: 12, padding: '4px 8px' }}
            autoFocus
            value={newTitle}
            onChange={e => setNewTitle(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') commitConcept(); if (e.key === 'Escape') { setAddingConcept(false); setNewTitle(''); } }}
            placeholder="Concept title…"
          />
          <button className="btn btn-accent btn-sm" onClick={commitConcept}>Add</button>
          <button className="btn btn-muted btn-sm" onClick={() => { setAddingConcept(false); setNewTitle(''); }}>Cancel</button>
        </div>
      )}
      <div className="concepts-list">
        {(tp.concepts || []).length === 0 ? (
          <div style={{ padding: '10px 14px', color: 'var(--txt3)', fontSize: 12 }}>No concepts yet.</div>
        ) : (
          <Reorderable
            items={tp.concepts || []}
            itemKey={cn => cn.id}
            colKey={`concepts-${tp.id}`}
            onReorder={onReorderConcepts}
            renderItem={(cn) => (
              <div className="concept-card">
                <div className="concept-head">
                  <InlineEdit
                    value={cn.title}
                    onSave={(title) => onRenameConcept(cn.id, title)}
                    style={{ fontSize: 13, fontWeight: 600, color: 'var(--txt)' }}
                    className="concept-title"
                    forceEdit={editingCnId === cn.id}
                    onEditDone={() => setEditingCnId(null)}
                  />
                  <div className="concept-actions">
                    <button className="concept-action-btn" onClick={() => onOpenConceptExplain(cn.id)}>Explain</button>
                    <button className="concept-action-btn concept-action-btn--accent" onClick={() => onOpenConceptTest(cn.id)}>QuickTest</button>
                    <span className={`status-badge ${cn.status || 'not_started'}`}>
                      {(cn.status || 'not started').replace(/_/g, ' ')}
                    </span>
                    <div onClick={e => e.stopPropagation()}>
                      <DropdownMenu
                        trigger={<button className="concept-action-btn" style={{ padding: '2px 6px', color: 'var(--txt3)', fontWeight: 700, letterSpacing: '0.05em' }}>⋮</button>}
                        items={[
                          { label: 'Edit title', onClick: () => setEditingCnId(cn.id) },
                          { label: 'Delete', danger: true, onClick: () => onDeleteConcept(cn.id) },
                        ]}
                      />
                    </div>
                  </div>
                </div>
                {cn.description && <div className="concept-desc">{cn.description}</div>}
              </div>
            )}
          />
        )}
      </div>
    </div>
  );
}

// ── Topic View ────────────────────────────────────────────────
function TopicView() {
  const { currentSpace, currentChapter, currentTopic, setCurrentTopic, setSpaceRoadmap, spaceRoadmap, setSpacesView, ok, err } = useStore();
  const [tab, setTab]       = useState('notes');
  const [activeCn, setActiveCn] = useState(null);
  const [noteVal, setNoteVal] = useState('');
  const [editingCnId, setEditingCnId] = useState(null);
  const [cnSearch, setCnSearch] = useState('');
  const editInputRef = useRef(null);

  useEffect(() => { if (editingCnId && editInputRef.current) editInputRef.current.focus(); }, [editingCnId]);
  const [sidebarWidth, onSidebarDrag] = useResizable('topic-sidebar-width', 260, 160, 480);

  const spaceId = encodeURIComponent(currentSpace?.name || '');
  const noteKey = (cnId) => `notes:${currentSpace?.name}:topic:${currentTopic?.id}:${cnId || '__topic__'}`;
  const [noteIdMap, setNoteIdMap] = useState({});

  const loadConceptNote = async (cnId) => {
    setNoteVal(localStorage.getItem(noteKey(cnId)) || '');
    if (!spaceId) return;
    try {
      const cid = cnId || currentTopic?.id || '';
      const r = await api(`/spaces/${spaceId}/notes?type=concept_note&concept_id=${encodeURIComponent(cid)}`);
      const list = Array.isArray(r) ? r : r.notes || [];
      if (list.length) {
        setNoteVal(list[0].body_md || '');
        setNoteIdMap(m => ({ ...m, [cid]: list[0].id }));
      }
    } catch {}
  };

  useEffect(() => {
    setActiveCn(currentTopic?._openConceptId || null);
    setTab(currentTopic?._openTab || 'notes');
    loadConceptNote(currentTopic?._openConceptId || null);
    setCnSearch('');
  }, [currentTopic?.id]);

  const saveNotes = async (val) => {
    const cid = activeCn || currentTopic?.id || '';
    const key = noteKey(activeCn);
    localStorage.setItem(key, val);
    localStorage.setItem(`${key}:hist:${Date.now()}`, val.slice(0, 4000));
    try {
      const existingId = noteIdMap[cid];
      const cnTitle = concepts.find(c => c.id === activeCn)?.title || currentTopic?.title || '';
      if (existingId) {
        await api(`/spaces/${spaceId}/notes/${existingId}`, {
          method: 'PUT', body: JSON.stringify({ title: `Notes: ${cnTitle}`, body_md: val }),
        });
      } else {
        const saved = await api(`/spaces/${spaceId}/notes`, {
          method: 'POST', body: JSON.stringify({ type: 'concept_note', concept_id: cid, title: `Notes: ${cnTitle}`, body_md: val }),
        });
        if (saved?.id) setNoteIdMap(m => ({ ...m, [cid]: saved.id }));
      }
    } catch {}
    ok(`Notes saved (${val.trim().split(/\s+/).filter(Boolean).length}w)`);
  };

  const importConceptDocument = async (file, mode = 'vision') => {
    if (!file) return;
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch(`/api/spaces/${spaceId}/notes/import?concept_id=${encodeURIComponent(activeCn)}&ocr_mode=${encodeURIComponent(mode)}`, {
        method: 'POST',
        body: form,
      });
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        let msg = `HTTP ${res.status}`;
        try { msg = JSON.parse(text).detail || JSON.parse(text).message || msg; } catch {}
        throw new Error(msg);
      }
      const data = await res.json().catch(() => ({}));
      const md = (data.markdown || '').trim();
      if (!md) { err("No content extracted."); return; }
      const next = noteVal ? `${noteVal.trim()}\n\n${md}` : md;
      setNoteVal(next);
      ok("Document converted to markdown.");
    } catch (e) { err(e.message); }
  };

  const markConceptStatus = async (cnId, status) => {
    const updated = concepts.map(cn => cn.id === cnId ? { ...cn, status } : cn);
    try { await patchTopic(updated); ok(status === 'completed' ? 'Marked complete' : 'Status updated'); } catch {}
  };

  if (!currentTopic) return null;
  const concepts = currentTopic.concepts || [];
  const sid      = encodeURIComponent(currentSpace?.name || '');

  const patchTopic = async (updatedConcepts) => {
    const updatedTopic = { ...currentTopic, concepts: updatedConcepts };
    const liveChapter = (spaceRoadmap?.chapters || []).find(c => c.id === currentChapter.id) || {};
    const updatedChapter = {
      ...liveChapter,
      topics: (liveChapter.topics || []).map(t => t.id === currentTopic.id ? updatedTopic : t),
    };
    const chapters = (spaceRoadmap?.chapters || []).map(c =>
      c.id === updatedChapter.id ? updatedChapter : c
    );
    const rm = await api(`/spaces/${sid}/roadmap`, { method: 'PATCH', body: JSON.stringify({ chapters }) });
    setSpaceRoadmap(rm);
    setCurrentTopic(updatedTopic);
  };

  const renameConcept = async (cnId, title) => {
    const updated = concepts.map(cn => cn.id === cnId ? { ...cn, title } : cn);
    try { await patchTopic(updated); ok('Concept renamed'); } catch { err('Failed to rename'); }
    setEditingCnId(null);
  };

  const deleteConcept = async (cnId) => {
    if (!confirm('Delete this concept?')) return;
    const updated = concepts.filter(cn => cn.id !== cnId);
    try { await patchTopic(updated); if (activeCn === cnId) setActiveCn(null); ok('Concept deleted'); } catch { err('Failed to delete'); }
  };

  // Expose active space ID so MarkdownEditor's STT can find it without prop-drilling
  useEffect(() => {
    let el = document.getElementById('__sarthak_space');
    if (!el) { el = document.createElement('div'); el.id = '__sarthak_space'; el.style.display = 'none'; document.body.appendChild(el); }
    el.dataset.id = sid;
    return () => { el.dataset.id = ''; };
  }, [sid]);

  return (
    <div className="page">
      <header className="pg-header">
        <div className="pg-title-group">
          <nav className="breadcrumb">
            <button className="bc-link" onClick={() => setSpacesView('list')}>Spaces</button>
            <span className="bc-sep">›</span>
            <button className="bc-link" onClick={() => setSpacesView('home')}>{currentSpace?.name}</button>
            <span className="bc-sep">›</span>
            <button className="bc-link" onClick={() => setSpacesView('chapter')}>{currentChapter?.title || 'Chapter'}</button>
            <span className="bc-sep">›</span>
            <span className="bc-current">{currentTopic.title}</span>
          </nav>
          <h1 className="pg-title">{currentTopic.title}</h1>
          <p className="pg-sub">{concepts.length} concepts</p>
        </div>
        <div className="pg-actions">
          <button className="btn btn-muted btn-sm" onClick={() => setSpacesView('chapter')}>Back</button>
          <button className="btn btn-accent btn-sm" onClick={() => setTab('quicktest')}>QuickTest</button>
        </div>
      </header>

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
        {/* Concepts sidebar — width persists in localStorage */}
        <div style={{ width: sidebarWidth, flexShrink: 0, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--brd)', background: 'var(--surface)', overflow: 'hidden', position: 'relative' }}>
          <div className="pane-hdr">
            <span>Concepts</span>
            <span style={{ fontSize: 10.5, color: 'var(--txt3)' }}>{concepts.length}</span>
          </div>
          <div style={{ padding: '6px 8px', borderBottom: '1px solid var(--brd)', flexShrink: 0 }}>
            <input
              className="s-input"
              style={{ fontSize: 12, padding: '4px 8px', width: '100%' }}
              placeholder="Filter concepts…"
              value={cnSearch}
              onChange={e => setCnSearch(e.target.value)}
            />
          </div>
          <div
            onMouseDown={onSidebarDrag}
            style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: 5, cursor: 'col-resize', zIndex: 10, background: 'transparent', transition: 'background 150ms' }}
            onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent-border)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
          />
          <div style={{ flex: 1, overflowY: 'auto', padding: '8px 6px', display: 'flex', flexDirection: 'column', gap: 3 }}>
            {[{ id: null, title: `All — ${currentTopic.title.slice(0, 16)}` }, ...concepts.filter(cn => !cnSearch.trim() || cn.title.toLowerCase().includes(cnSearch.toLowerCase()))].map(cn => (
              <div key={cn.id ?? '__all__'} style={{ position: 'relative', display: 'flex', alignItems: 'center', borderRadius: 6, background: activeCn === cn.id ? 'var(--accent-dim)' : 'transparent', border: `1px solid ${activeCn === cn.id ? 'var(--accent-border)' : 'transparent'}`, transition: 'background 120ms' }}
                className="concept-sidebar-row"
              >
                {editingCnId === cn.id ? (
                  <input
                    ref={editInputRef}
                    defaultValue={cn.title}
                    onBlur={e => renameConcept(cn.id, e.target.value.trim() || cn.title)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') renameConcept(cn.id, e.target.value.trim() || cn.title);
                      if (e.key === 'Escape') setEditingCnId(null);
                    }}
                    style={{ flex: 1, fontSize: 12.5, padding: '6px 10px', background: 'var(--surface2)', border: '1px solid var(--accent-border)', borderRadius: 5, color: 'var(--txt)', fontFamily: 'var(--font)', outline: 'none' }}
                    onClick={e => e.stopPropagation()}
                  />
                ) : (
                  <button onClick={() => { setActiveCn(cn.id); loadConceptNote(cn.id); }}
                    style={{
                      flex: 1, textAlign: 'left', background: 'transparent', border: 'none',
                      padding: '7px 10px', cursor: 'pointer',
                      color: 'var(--txt2)', fontSize: 12.5,
                      fontWeight: cn.id === null ? 600 : 500,
                      fontFamily: 'var(--font)',
                    }}>
                    {cn.title}
                  </button>
                )}
                {cn.id !== null && (
                  <div style={{ flexShrink: 0, paddingRight: 4, display: 'flex', alignItems: 'center', gap: 2 }} onClick={e => e.stopPropagation()}>
                    <button
                      title={concepts.find(c => c.id === cn.id)?.status === 'completed' ? 'Mark in progress' : 'Mark complete'}
                      onClick={() => {
                        const cur = concepts.find(c => c.id === cn.id);
                        markConceptStatus(cn.id, cur?.status === 'completed' ? 'in_progress' : 'completed');
                      }}
                      style={{
                        background: 'transparent', border: 'none', cursor: 'pointer', padding: '2px 4px',
                        color: concepts.find(c => c.id === cn.id)?.status === 'completed' ? 'var(--accent)' : 'var(--txt3)',
                        fontSize: 13, lineHeight: 1, borderRadius: 4,
                      }}
                    >
                      {concepts.find(c => c.id === cn.id)?.status === 'completed' ? (
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                      ) : (
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9"/></svg>
                      )}
                    </button>
                    <DropdownMenu
                      trigger={<button style={{ background: 'transparent', border: 'none', color: 'var(--txt3)', cursor: 'pointer', padding: '2px 5px', fontSize: 13, borderRadius: 4, lineHeight: 1 }}>⋮</button>}
                      items={[
                        { label: 'Edit title', onClick: () => setEditingCnId(cn.id) },
                        { label: 'Delete', danger: true, onClick: () => deleteConcept(cn.id) },
                      ]}
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Main panel */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0 }}>
          <div className="topic-tab-bar">
            {['notes', 'explains', 'quicktest', 'recordings', 'notebook', 'playground'].map(t => (
              <button key={t} className={`td-tab${tab === t ? ' active' : ''}`} onClick={() => setTab(t)}>
                {t === 'recordings' ? 'Record' : t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
            {activeCn && (
              <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--txt3)', fontStyle: 'italic', padding: '0 12px' }}>
                {concepts.find(c => c.id === activeCn)?.title || ''}
              </span>
            )}
          </div>
          <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            {tab === 'notes' && (
              <>
                {/* Topic mode: Analysis dashboard + Overlay notes */}
                {!activeCn && (
                  <div style={{ flex: 1, padding: 24, overflowY: 'auto' }}>
                    <h2 style={{ margin: '0 0 16px', fontSize: 18, color: 'var(--txt)' }}>
                      Topic Analysis: {currentTopic.title}
                    </h2>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 24 }}>
                      <div style={{ background: 'var(--surface2)', borderRadius: 8, padding: 16, border: '1px solid var(--brd)' }}>
                        <div style={{ fontSize: 12, color: 'var(--accent)', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.05em' }}>Concepts</div>
                        <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--txt)', marginTop: 8 }}>{concepts.length}</div>
                      </div>
                      <div style={{ background: 'var(--surface2)', borderRadius: 8, padding: 16, border: '1px solid var(--brd)' }}>
                        <div style={{ fontSize: 12, color: 'var(--accent)', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.05em' }}>Notes written</div>
                        <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--txt)', marginTop: 8 }}>
                          {noteVal.trim().split(/\s+/).filter(Boolean).length} <span style={{fontSize: 14, color: 'var(--txt3)', fontWeight: 400}}>words</span>
                        </div>
                      </div>
                    </div>
                    <div style={{ marginTop: 16 }}>
                      <MarkdownEditor
                        value={noteVal} onChange={setNoteVal} onSave={saveNotes} historyKey={noteKey(activeCn)}
                        placeholder={`Notes for ${currentTopic.title}…`}
                        onUploadDocument={importConceptDocument}
                        spaceId={sid}
                      />
                    </div>
                  </div>
                )}
                
                {/* Concept mode: Inline notes */}
                {activeCn && (
                  <MarkdownEditor
                    value={noteVal} onChange={setNoteVal} onSave={saveNotes} historyKey={noteKey(activeCn)}
                    placeholder={`Notes for ${concepts.find(c => c.id === activeCn)?.title || 'concept'}…`}
                    onUploadDocument={importConceptDocument}
                    spaceId={sid}
                  />
                )}
                
              </>
            )}
            {tab === 'explains' && (
              <ExplainsTab
                spaceId={sid}
                conceptId={activeCn || currentTopic.id}
                conceptTitle={activeCn ? (concepts.find(c => c.id === activeCn)?.title || currentTopic.title) : currentTopic.title}
              />
            )}
            {tab === 'quicktest' && (
              <QuickTestTab spaceId={sid} conceptId={activeCn} topicTitle={currentTopic.title} />
            )}
            {tab === 'recordings' && (
              <MediaRecorderTab
                spaceId={sid}
                conceptId={activeCn || currentTopic.id}
                conceptTitle={activeCn ? (concepts.find(c => c.id === activeCn)?.title || currentTopic.title) : currentTopic.title}
              />
            )}
            {tab === 'notebook' && (
              <NotebookTab
                spaceId={sid}
                conceptId={activeCn || currentTopic.id}
                conceptTitle={activeCn ? (concepts.find(c => c.id === activeCn)?.title || currentTopic.title) : currentTopic.title}
              />
            )}
            {tab === 'playground' && (
              <PlaygroundTab
                spaceId={sid}
                conceptId={activeCn || currentTopic.id}
                conceptTitle={activeCn ? (concepts.find(c => c.id === activeCn)?.title || currentTopic.title) : currentTopic.title}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
