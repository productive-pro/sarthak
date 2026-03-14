/**
 * pages/spaces/shared.jsx
 * Utilities and small components shared across Spaces sub-pages.
 */
import { useState, useRef, useEffect } from 'react';
import { api } from '../../api';

// ── TYPE_COLORS: used by SpaceCard and type helpers ───────────────────────────
// These stay client-side — purely visual, no business logic.
export const TYPE_COLORS = {
  data_science:         '#6366f1',
  ai_engineering:       '#8b5cf6',
  software_engineering: '#3b82f6',
  medicine:             '#10b981',
  education:            '#f59e0b',
  exam_prep:            '#ef4444',
  research:             '#06b6d4',
  business:             '#84cc16',
  custom:               '#f472b6',
};

// Text abbreviations for space type icons — no emojis.
export const TYPE_ABBR = {
  data_science:         'DS',
  ai_engineering:       'AI',
  software_engineering: 'SE',
  medicine:             'MD',
  education:            'ED',
  exam_prep:            'EX',
  research:             'RS',
  business:             'BZ',
  custom:               'CU',
};

export const typeColor = (s) =>
  TYPE_COLORS[s?.space_type] || TYPE_COLORS[s?.type] || 'var(--accent)';

export const typeAbbr = (s) =>
  TYPE_ABBR[s?.space_type] || TYPE_ABBR[s?.type] || '??';

// ── useExpertTemplates ────────────────────────────────────────────────────────
// Fetches expert space templates from the backend.
// Returns { templates, loading } — templates is [] until loaded.
export function useExpertTemplates() {
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api('/spaces/expert-templates')
      .then(data => { if (!cancelled) setTemplates(Array.isArray(data) ? data : []); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return { templates, loading };
}

// ── InlineEdit ────────────────────────────────────────────────────────────────
export function InlineEdit({ value, onSave, style, className, placeholder = 'Untitled', forceEdit, onEditDone }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(value);
  const ref = useRef(null);
  useEffect(() => { setVal(value); }, [value]);
  useEffect(() => { if (editing) ref.current?.focus(); }, [editing]);
  useEffect(() => { if (forceEdit) setEditing(true); }, [forceEdit]);
  const commit = () => {
    setEditing(false); onEditDone?.();
    const t = val.trim() || value; setVal(t);
    if (t !== value) onSave(t);
  };
  if (editing) return (
    <input ref={ref} value={val} onChange={e => setVal(e.target.value)} onBlur={commit}
      onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { setEditing(false); setVal(value); } }}
      style={{ ...style, background: 'var(--surface2)', border: '1px solid var(--accent-border)', borderRadius: 4, padding: '2px 6px', color: 'var(--txt)', fontFamily: 'var(--font)', outline: 'none' }}
      className={className} placeholder={placeholder} />
  );
  return (
    <span style={{ ...style, cursor: 'text' }} className={className}
      title="Double-click to rename" onDoubleClick={() => setEditing(true)}>
      {value || placeholder}
    </span>
  );
}

// ── Reorderable (drag-to-reorder list) ───────────────────────────────────────
const _drag = { id: null, colKey: null };
export function Reorderable({ items, onReorder, renderItem, itemKey, colKey, onDragToColumn, dragRef }) {
  const drag = dragRef?.current ?? _drag;
  const [overId, setOverId] = useState(null);
  const onDragStart = (item) => (e) => {
    drag.id = itemKey(item); drag.colKey = colKey;
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', JSON.stringify({ id: itemKey(item), colKey }));
  };
  const onDragOver = (item) => (e) => { e.preventDefault(); e.stopPropagation(); setOverId(itemKey(item)); };
  const onDrop = (targetItem) => (e) => {
    e.preventDefault(); e.stopPropagation(); setOverId(null);
    const srcId = drag.id; const srcCol = drag.colKey; drag.id = null; drag.colKey = null;
    if (!srcId) return;
    if (srcCol !== colKey) { onDragToColumn?.(srcId, colKey); return; }
    const fromIdx = items.findIndex(x => itemKey(x) === srcId);
    const toIdx   = items.findIndex(x => itemKey(x) === itemKey(targetItem));
    if (fromIdx === -1 || toIdx === -1 || fromIdx === toIdx) return;
    const next = [...items]; const [moved] = next.splice(fromIdx, 1); next.splice(toIdx, 0, moved);
    onReorder(next);
  };
  const onDragEnd = () => { drag.id = null; drag.colKey = null; setOverId(null); };
  return items.map(item => (
    <div key={itemKey(item)} draggable
      onDragStart={onDragStart(item)} onDragOver={onDragOver(item)}
      onDrop={onDrop(item)} onDragEnd={onDragEnd}
      style={{ opacity: overId === itemKey(item) ? 0.4 : 1, outline: overId === itemKey(item) ? '2px dashed var(--accent-border)' : 'none', borderRadius: 6, transition: 'opacity 100ms' }}>
      {renderItem(item)}
    </div>
  ));
}

// ── SpaceGeneratingAnimation ──────────────────────────────────────────────────
export function SpaceGeneratingAnimation() {
  const steps = [
    'Analysing domain…', 'Discovering expert patterns…', 'Scaffolding workspace…',
    'Initialising learning DB…', 'Generating roadmap…', 'Almost ready…',
  ];
  const [cur, setCur] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setCur(s => (s + 1) % steps.length), 1400);
    return () => clearInterval(t);
  }, []);
  const cx = 64, cy = 64, R = 48;
  const dots = Array.from({ length: 6 }, (_, i) => ({
    x: cx + R * Math.cos((i / 6) * 2 * Math.PI),
    y: cy + R * Math.sin((i / 6) * 2 * Math.PI),
    delay: i * 0.2,
  }));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 20 }}>
      <svg width="128" height="128" viewBox="0 0 128 128" style={{ overflow: 'visible' }}>
        <circle cx={cx} cy={cy} r="30" fill="none" stroke="var(--accent-border)" strokeWidth="2" />
        <circle cx={cx} cy={cy} r="30" fill="none" stroke="var(--accent)" strokeWidth="2.5"
          strokeDasharray="48 140" strokeLinecap="round"
          style={{ transformOrigin: `${cx}px ${cy}px`, animation: 'sSpin 1.6s linear infinite' }} />
        <text x={cx} y={cy + 5} textAnchor="middle" fontSize="11" fontWeight="700"
          fontFamily="var(--mono)" fill="var(--accent)">sarthak</text>
        <g className="sg-ring">
          {dots.map((d, i) => (
            <circle key={i} className="sg-dot" cx={d.x} cy={d.y} r="4"
              fill="var(--accent)" style={{ animationDelay: `${d.delay}s` }} />
          ))}
        </g>
      </svg>
      <div style={{ fontSize: 13, color: 'var(--accent)', minWidth: 220, textAlign: 'center', fontFamily: 'var(--mono)' }}>
        {steps[cur]}
      </div>
    </div>
  );
}

// ── generateTopicsAndConcepts ─────────────────────────────────────────────────
export async function generateTopicsAndConcepts(spaceId, chapter, instruction, onPatchChapter) {
  const baseId = Date.now().toString(36);
  const r = await api(`/spaces/${spaceId}/roadmap/generate-children`, {
    method: 'POST',
    body: JSON.stringify({ parent_type: 'chapter', parent_title: chapter.title, instruction: instruction.trim() }),
  });
  const topicTitles = (r.children || []).filter(Boolean);
  const CONCURRENCY = 3;
  const conceptResults = [];
  for (let i = 0; i < topicTitles.length; i += CONCURRENCY) {
    const batch = topicTitles.slice(i, i + CONCURRENCY).map(tTitle =>
      api(`/spaces/${spaceId}/roadmap/generate-children`, {
        method: 'POST',
        body: JSON.stringify({ parent_type: 'topic', parent_title: tTitle, instruction: instruction.trim() }),
      }).catch(() => ({ children: [] }))
    );
    conceptResults.push(...(await Promise.all(batch)));
  }
  const newTopics = topicTitles.map((tTitle, i) => ({
    id: `tp_${baseId}_${i}`, title: tTitle, order: (chapter.topics || []).length + i, status: 'not_started',
    concepts: (conceptResults[i]?.children || []).filter(Boolean).map((cTitle, j) => ({
      id: `cn_${baseId}_${i}_${j}`, title: cTitle, description: '', status: 'not_started', order: j,
      tags: [], related_concepts: [], notes: [], quicktests: [],
    })),
  }));
  await onPatchChapter({ ...chapter, topics: [...(chapter.topics || []), ...newTopics] });
}
