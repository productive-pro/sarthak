/**
 * pages/spaces/RoadmapBoard.jsx
 * Kanban-style roadmap board with drag-to-reorder.
 */
import { useRef, useState } from 'react';
import { InlineEdit, Reorderable } from './shared';
import DropdownMenu from '../../components/DropdownMenu';

const STATUS_COLS = [
  { key: 'not_started', label: 'Not Started', color: 'var(--txt3)' },
  { key: 'in_progress', label: 'In Progress', color: '#fbbf24' },
  { key: 'review',      label: 'Review',       color: '#38bdf8' },
  { key: 'completed',   label: 'Completed',    color: 'var(--accent)' },
];

// ── Individual chapter card ───────────────────────────────────────────────────
function RoadmapCard({ chapter: ch, colColor, allChapters, onClick, onRename, onDelete, onGenerate, onEditDesc }) {
  const [hovered, setHovered] = useState(false);
  const progress = ch.progress_pct || 0;
  const done   = ch.status === 'completed';
  const active = ch.status === 'in_progress';
  const topicCount   = (ch.topics || []).length;
  const conceptCount = (ch.topics || []).reduce((a, t) => a + (t.concepts || []).length, 0);
  const circ   = 2 * Math.PI * 10;
  const offset = circ - (progress / 100) * circ;
  const chIdx  = allChapters.findIndex(c => c.id === ch.id);

  return (
    <div
      className={`roadmap-card${active ? ' roadmap-card--active' : done ? ' roadmap-card--done' : ''}`}
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className="roadmap-card-hdr">
        <div style={{ flex:1, minWidth:0 }}>
          <div className="roadmap-card-meta">
            <span className="roadmap-card-idx">#{chIdx + 1}</span>
            <DropdownMenu
              trigger={<span style={{ padding:'0 6px', color:'var(--txt3)', fontSize:14 }}>⋮</span>}
              items={[
                { label: 'Edit Description', onClick: e => { e?.stopPropagation?.(); onEditDesc?.(); } },
                { label: 'Generate Topics (LLM)', onClick: e => { e?.stopPropagation?.(); onGenerate?.(); } },
                { label: 'Delete', danger: true, onClick: e => onDelete?.(e) },
              ]}
            />
          </div>
          <InlineEdit
            value={ch.title}
            onSave={onRename}
            className="roadmap-card-title"
            style={{ color: done ? 'var(--accent)' : active ? '#fbbf24' : 'var(--txt)' }}
          />
        </div>
        <svg width="26" height="26" viewBox="0 0 26 26" style={{ flexShrink:0 }}>
          <circle cx="13" cy="13" r="10" fill="none" stroke="var(--brd2)" strokeWidth="2.5"/>
          {progress > 0 && (
            <circle cx="13" cy="13" r="10" fill="none" stroke={colColor} strokeWidth="2.5"
              strokeDasharray={circ.toFixed(2)} strokeDashoffset={offset.toFixed(2)}
              strokeLinecap="round" style={{ transform:'rotate(-90deg)', transformOrigin:'center' }}/>
          )}
          {done
            ? <path d="M8.5 13l3 3 6-6" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            : <text x="13" y="17" textAnchor="middle" fontSize="7" fontFamily="var(--mono)" fill={progress>0?colColor:'var(--txt3)'}>{progress>0?`${Math.round(progress)}`:'·'}</text>}
        </svg>
      </div>
      {ch.description && hovered && <div className="roadmap-card-desc">{ch.description}</div>}
      <div className="roadmap-card-tags">
        {topicCount   > 0 && <span className="roadmap-card-tag">{topicCount}t</span>}
        {conceptCount > 0 && <span className="roadmap-card-tag">{conceptCount}c</span>}
        {active && <span className="roadmap-card-active-badge">active</span>}
      </div>
    </div>
  );
}

// ── Board ─────────────────────────────────────────────────────────────────────
export default function RoadmapBoard({ roadmap, onChapterClick, onAddChapter, onPatchChapters, onGenerateChapter, onEditChapterDesc }) {
  const chapters = roadmap?.chapters || [];
  const dragRef  = useRef({ id: null, colKey: null });

  if (!chapters.length) return (
    <div style={{ display:'flex',alignItems:'center',justifyContent:'center',height:200,flexDirection:'column',gap:12,color:'var(--txt3)',fontSize:13 }}>
      <span>No chapters yet.</span>
      <button className="btn btn-accent btn-sm" onClick={onAddChapter}>+ Add Chapter</button>
    </div>
  );

  const byStatus = Object.fromEntries(STATUS_COLS.map(c => [c.key, []]));
  chapters.forEach(ch => { byStatus[ch.status in byStatus ? ch.status : 'not_started'].push(ch); });

  const totalDone   = chapters.filter(c => c.status === 'completed').length;
  const totalActive = chapters.filter(c => c.status === 'in_progress').length;

  const moveToColumn = (chId, ns) => onPatchChapters(chapters.map(c => c.id === chId ? { ...c, status: ns } : c));
  const reorderInColumn = (reordered) => {
    const ids = new Set(reordered.map(c => c.id));
    const next = [...chapters]; let slot = 0;
    for (let i = 0; i < next.length; i++) { if (ids.has(next[i].id)) next[i] = reordered[slot++]; }
    onPatchChapters(next);
  };

  const columnDropProps = (colKey) => ({
    onDragOver: e => e.preventDefault(),
    onDrop: e => {
      e.preventDefault();
      let srcId = dragRef.current.id, srcCol = dragRef.current.colKey;
      if (!srcId) { try { const d = JSON.parse(e.dataTransfer.getData('text/plain')); srcId=d.id; srcCol=d.colKey; } catch {} }
      dragRef.current.id = null; dragRef.current.colKey = null;
      if (srcId && srcCol !== colKey) moveToColumn(srcId, colKey);
    },
  });

  return (
    <div>
      <div className="board-meta">
        <span>{chapters.length} chapters</span>
        <span style={{ color:'#fbbf24' }}>{totalActive} in progress</span>
        <span style={{ color:'var(--accent)' }}>{totalDone} completed</span>
        <span className="board-meta-hint">double-click to rename · drag to reorder</span>
      </div>
      <div className="board-grid">
        {STATUS_COLS.map(col => (
          <div key={col.key} className="board-col" style={{ borderTop:`2px solid ${col.color}` }} {...columnDropProps(col.key)}>
            <div className="board-col-hdr">
              <span className="board-col-label" style={{ color: col.color }}>{col.label}</span>
              <span className="board-col-count">{byStatus[col.key].length}</span>
            </div>
            <div className="board-col-body">
              {byStatus[col.key].length === 0
                ? <div className="board-col-empty">drop here</div>
                : <Reorderable items={byStatus[col.key]} itemKey={ch=>ch.id} colKey={col.key}
                    onReorder={reorderInColumn} onDragToColumn={moveToColumn} dragRef={dragRef}
                    renderItem={ch => (
                      <RoadmapCard chapter={ch} colColor={col.color} allChapters={chapters}
                        onClick={() => onChapterClick(ch)}
                        onRename={title => onPatchChapters(chapters.map(c => c.id===ch.id ? {...c,title} : c))}
                        onDelete={e => { e.stopPropagation(); if (confirm('Delete chapter?')) onPatchChapters(chapters.filter(c=>c.id!==ch.id)); }}
                        onGenerate={() => onGenerateChapter?.(ch.id)}
                        onEditDesc={() => onEditChapterDesc?.(ch.id)}
                      />
                    )}
                  />}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
