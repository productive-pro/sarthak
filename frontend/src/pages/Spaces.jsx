import React, { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../api';
import { fmt } from '../utils/format';
import SpaceCard from '../components/SpaceCard';
import { useStore } from '../store';
import { useResizable } from '../hooks/useResizable';
import useFetch from '../hooks/useFetch';
import Modal from '../components/Modal';
import Overlay from '../components/Overlay';
import MarkdownEditor from '../components/MarkdownEditor';
import DropdownMenu from '../components/DropdownMenu';
import PromptInline from '../components/PromptInline';
import { ExplainsTab, QuickTestTab, MediaRecorderTab, NotebookTab, PlaygroundTab } from '../sarthak/ConceptTabs';
import SettingsTabs from '../components/spaces/SpaceSettingsTabs';
import PanelHost from './SpacePanels';

// ── Expert domain catalogue ──────────────────────────────────────────────────
const EXPERT_SPACES = [
  {
    id: 'data_science', label: 'Data Science & AI', icon: '🧠',
    desc: 'ML from first principles, PyTorch, MLflow, production pipelines',
    expertTip: 'Experts derive gradients by hand before touching frameworks.',
    tools: ['polars', 'duckdb', 'marimo', 'mlflow', 'ruff'],
    folders: ['notebooks', 'src', 'data', 'experiments', 'models', 'reports'],
    color: '#6366f1',
  },
  {
    id: 'ai_engineering', label: 'AI Engineering', icon: '⚡',
    desc: 'LLMs, fine-tuning, RAG systems, agent frameworks, LLMOps',
    expertTip: 'Build your own attention block before using transformers.',
    tools: ['pydantic-ai', 'vllm', 'langchain', 'wandb'],
    folders: ['agents', 'evals', 'notebooks', 'src', 'data'],
    color: '#8b5cf6',
  },
  {
    id: 'software_engineering', label: 'Software Engineering', icon: '⚙️',
    desc: 'System design, distributed systems, clean architecture, testing',
    expertTip: 'Senior engineers think in trade-offs, not right answers.',
    tools: ['pytest', 'ruff', 'httpx', 'docker'],
    folders: ['src', 'tests', 'docs', 'scripts'],
    color: '#3b82f6',
  },
  {
    id: 'medicine', label: 'Medicine / Medical AI', icon: '🏥',
    desc: 'Clinical data science, medical imaging, EHR analysis',
    expertTip: 'Validate on held-out institutions, not just held-out patients.',
    tools: ['lifelines', 'pydicom', 'medspacy'],
    folders: ['cases', 'notes', 'literature', 'data'],
    color: '#10b981',
  },
  {
    id: 'education', label: 'Education & Learning Science', icon: '📚',
    desc: 'Knowledge tracing, adaptive learning, learning analytics',
    expertTip: 'Spaced repetition beats re-reading by 3-4× — evidence-backed.',
    tools: ['gradio', 'streamlit', 'pandas'],
    folders: ['curriculum', 'notes', 'assessments', 'resources'],
    color: '#f59e0b',
  },
  {
    id: 'exam_prep', label: 'Exam Preparation', icon: '🎯',
    desc: 'GATE, UPSC, JEE, GRE — structured mastery + spaced repetition',
    expertTip: 'Weak-area drilling beats full-syllabus re-reading every time.',
    tools: [],
    folders: ['subjects', 'mock_tests', 'weak_areas', 'flashcards'],
    color: '#ef4444',
  },
  {
    id: 'research', label: 'Research & Academia', icon: '🔬',
    desc: 'Experiment design, reproducibility, statistical inference',
    expertTip: 'Pre-register your hypothesis before collecting data.',
    tools: ['dvc', 'scipy', 'jupyter'],
    folders: ['papers', 'experiments', 'notes', 'data', 'reports'],
    color: '#06b6d4',
  },
  {
    id: 'business', label: 'Business Analytics', icon: '📈',
    desc: 'Product analytics, A/B testing, cohort analysis, strategy',
    expertTip: 'Measure with metrics trees; never optimise vanity metrics.',
    tools: ['duckdb', 'plotly', 'streamlit'],
    folders: ['dashboards', 'data', 'reports', 'notes'],
    color: '#84cc16',
  },
  {
    id: 'custom', label: 'Custom Domain', icon: '✨',
    desc: 'Any topic — philosophy, spirituality, history, music, language…',
    expertTip: 'AI will collaboratively design your space from scratch.',
    tools: [],
    folders: ['notes', 'resources', 'reflections', 'projects'],
    color: '#f472b6',
  },
];

// ── Inline editable text ──────────────────────────────────────────────────────
function InlineEdit({ value, onSave, style, className, placeholder = 'Untitled', forceEdit, onEditDone }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(value);
  const inputRef = useRef(null);
  useEffect(() => { setVal(value); }, [value]);
  useEffect(() => { if (editing) inputRef.current?.focus(); }, [editing]);
  useEffect(() => { if (forceEdit) setEditing(true); }, [forceEdit]);
  const commit = () => {
    setEditing(false); onEditDone?.();
    const trimmed = val.trim() || value; setVal(trimmed);
    if (trimmed !== value) onSave(trimmed);
  };
  if (editing) return (
    <input ref={inputRef} value={val} onChange={e => setVal(e.target.value)} onBlur={commit}
      onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { setEditing(false); setVal(value); } }}
      style={{ ...style, background: 'var(--surface2)', border: '1px solid var(--accent-border)', borderRadius: 4, padding: '2px 6px', color: 'var(--txt)', fontFamily: 'var(--font)', outline: 'none' }}
      className={className} placeholder={placeholder} />
  );
  return <span style={{ ...style, cursor: 'text' }} className={className} title="Double-click to edit" onDoubleClick={() => setEditing(true)}>{value || placeholder}</span>;
}

// ── Drag-to-reorder ───────────────────────────────────────────────────────────
const _drag = { id: null, colKey: null };
function Reorderable({ items, onReorder, renderItem, itemKey, colKey, onDragToColumn, dragRef }) {
  const drag = dragRef?.current ?? _drag;
  const [overId, setOverId] = useState(null);
  const onDragStart = (item) => (e) => { drag.id = itemKey(item); drag.colKey = colKey; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', JSON.stringify({ id: itemKey(item), colKey })); };
  const onDragOver = (item) => (e) => { e.preventDefault(); e.stopPropagation(); setOverId(itemKey(item)); };
  const onDrop = (targetItem) => (e) => {
    e.preventDefault(); e.stopPropagation(); setOverId(null);
    const srcId = drag.id; const srcCol = drag.colKey; drag.id = null; drag.colKey = null;
    if (!srcId) return;
    if (srcCol !== colKey) { onDragToColumn?.(srcId, colKey); return; }
    const fromIdx = items.findIndex(x => itemKey(x) === srcId);
    const toIdx = items.findIndex(x => itemKey(x) === itemKey(targetItem));
    if (fromIdx === -1 || toIdx === -1 || fromIdx === toIdx) return;
    const next = [...items]; const [moved] = next.splice(fromIdx, 1); next.splice(toIdx, 0, moved); onReorder(next);
  };
  const onDragEnd = () => { drag.id = null; drag.colKey = null; setOverId(null); };
  return items.map((item) => (
    <div key={itemKey(item)} draggable onDragStart={onDragStart(item)} onDragOver={onDragOver(item)} onDrop={onDrop(item)} onDragEnd={onDragEnd}
      style={{ opacity: overId === itemKey(item) ? 0.4 : 1, outline: overId === itemKey(item) ? '2px dashed var(--accent-border)' : 'none', borderRadius: 6, transition: 'opacity 100ms' }}>
      {renderItem(item)}
    </div>
  ));
}

// ── Roadmap Board ──────────────────────────────────────────────────────────────
const STATUS_COLS = [
  { key: 'not_started', label: 'Not Started', color: 'var(--txt3)' },
  { key: 'in_progress', label: 'In Progress', color: '#fbbf24' },
  { key: 'review', label: 'Review', color: '#38bdf8' },
  { key: 'completed', label: 'Completed', color: 'var(--accent)' },
];

function RoadmapBoard({ roadmap, onChapterClick, onAddChapter, onPatchChapters, onGenerateChapter, onEditChapterDesc }) {
  const chapters = roadmap?.chapters || [];
  const dragRef = useRef({ id: null, colKey: null });
  if (!chapters.length) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 200, flexDirection: 'column', gap: 12, color: 'var(--txt3)', fontSize: 13 }}>
      <span>No chapters yet.</span>
      <button className="btn btn-accent btn-sm" onClick={onAddChapter}>+ Add Chapter</button>
    </div>
  );
  const byStatus = Object.fromEntries(STATUS_COLS.map(c => [c.key, []]));
  chapters.forEach(ch => { byStatus[ch.status in byStatus ? ch.status : 'not_started'].push(ch); });
  const totalDone = chapters.filter(c => c.status === 'completed').length;
  const totalActive = chapters.filter(c => c.status === 'in_progress').length;
  const moveToColumn = (chId, ns) => onPatchChapters(chapters.map(c => c.id === chId ? { ...c, status: ns } : c));
  const reorderInColumn = (reordered) => {
    const ids = new Set(reordered.map(c => c.id));
    const next = [...chapters]; let slot = 0;
    for (let i = 0; i < next.length; i++) { if (ids.has(next[i].id)) next[i] = reordered[slot++]; }
    onPatchChapters(next);
  };
  const columnDropProps = (colKey) => ({
    onDragOver: (e) => e.preventDefault(),
    onDrop: (e) => {
      e.preventDefault();
      let srcId = dragRef.current.id;
      let srcCol = dragRef.current.colKey;
      if (!srcId) {
        try { const d = JSON.parse(e.dataTransfer.getData('text/plain')); srcId = d.id; srcCol = d.colKey; } catch {}
      }
      dragRef.current.id = null; dragRef.current.colKey = null;
      if (srcId && srcCol !== colKey) moveToColumn(srcId, colKey);
    },
  });
  return (
    <div>
      <div style={{ display: 'flex', gap: 16, padding: '8px 2px', marginBottom: 4, fontSize: 11, color: 'var(--txt3)' }}>
        <span>{chapters.length} chapters</span>
        <span style={{ color: '#fbbf24' }}>{totalActive} in progress</span>
        <span style={{ color: 'var(--accent)' }}>{totalDone} completed</span>
        <span style={{ marginLeft: 'auto', fontSize: 10.5 }}>double-click to rename · drag to reorder</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        {STATUS_COLS.map(col => (
          <div key={col.key} style={{ background: 'var(--surface)', border: '1px solid var(--brd)', borderTop: `2px solid ${col.color}`, borderRadius: 8, display: 'flex', flexDirection: 'column', minHeight: 120 }} {...columnDropProps(col.key)}>
            <div style={{ padding: '10px 12px 8px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: col.color, textTransform: 'uppercase', letterSpacing: '.05em' }}>{col.label}</span>
              <span style={{ fontSize: 10.5, color: 'var(--txt3)', background: 'var(--surface2)', borderRadius: 10, padding: '1px 7px' }}>{byStatus[col.key].length}</span>
            </div>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6, padding: '4px 8px 10px' }}>
              {byStatus[col.key].length === 0
                ? <div style={{ fontSize: 11.5, color: 'var(--txt3)', textAlign: 'center', padding: '20px 8px', opacity: 0.5 }}>drop here</div>
                : <Reorderable items={byStatus[col.key]} itemKey={ch => ch.id} colKey={col.key}
                    onReorder={reorderInColumn} onDragToColumn={moveToColumn} dragRef={dragRef}
                    renderItem={(ch) => <RoadmapCard chapter={ch} colColor={col.color} allChapters={chapters}
                      onClick={() => onChapterClick(ch)}
                      onRename={(title) => onPatchChapters(chapters.map(c => c.id === ch.id ? { ...c, title } : c))}
                      onDelete={(e) => { e.stopPropagation(); if (confirm('Delete chapter?')) onPatchChapters(chapters.filter(c => c.id !== ch.id)); }}
                      onGenerate={() => onGenerateChapter?.(ch.id)}
                      onEditDesc={() => onEditChapterDesc?.(ch.id)} />} />}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


function RoadmapCard({ chapter: ch, colColor, onClick, allChapters, onRename, onDelete, onGenerate, onEditDesc }) {
  const [hovered, setHovered] = useState(false);
  const progress = ch.progress_pct || 0; const done = ch.status === 'completed'; const active = ch.status === 'in_progress';
  const topicCount = (ch.topics || []).length;
  const conceptCount = (ch.topics || []).reduce((a, t) => a + (t.concepts || []).length, 0);
  const circ = 2 * Math.PI * 10; const offset = circ - (progress / 100) * circ;
  const chIdx = allChapters.findIndex(c => c.id === ch.id);
  return (
    <div onClick={onClick}
      style={{ background: active ? 'rgba(251,191,36,0.06)' : done ? 'rgba(74,222,128,0.05)' : 'var(--surface2)', border: `1px solid ${active ? 'rgba(251,191,36,0.3)' : done ? 'rgba(74,222,128,0.25)' : 'var(--brd)'}`, borderRadius: 7, padding: '10px 12px', cursor: 'pointer', transition: 'border-color 0.15s, box-shadow 0.15s', userSelect: 'none' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 7, gap: 6 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
            <div style={{ fontSize: 10, color: 'var(--txt3)' }}>#{chIdx + 1}</div>
            <DropdownMenu trigger={<span style={{ padding: '0 6px', color: 'var(--txt3)', fontSize: 14 }}>⋮</span>}
              items={[{ label: 'Edit Description', onClick: (e) => { e?.stopPropagation?.(); onEditDesc?.(); } }, { label: 'Generate Topics (LLM)', onClick: (e) => { e?.stopPropagation?.(); onGenerate?.(); } }, { label: 'Delete', danger: true, onClick: (e) => onDelete?.(e) }]} />
          </div>
          <InlineEdit value={ch.title} onSave={onRename} style={{ fontSize: 12.5, fontWeight: 600, color: done ? 'var(--accent)' : active ? '#fbbf24' : 'var(--txt)', lineHeight: 1.35, display: 'block' }} />
        </div>
        <svg width="26" height="26" viewBox="0 0 26 26" style={{ flexShrink: 0 }}>
          <circle cx="13" cy="13" r="10" fill="none" stroke="var(--brd2)" strokeWidth="2.5"/>
          {progress > 0 && <circle cx="13" cy="13" r="10" fill="none" stroke={colColor} strokeWidth="2.5" strokeDasharray={circ.toFixed(2)} strokeDashoffset={offset.toFixed(2)} strokeLinecap="round" style={{ transform: 'rotate(-90deg)', transformOrigin: 'center' }} />}
          {done ? <path d="M8.5 13l3 3 6-6" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            : <text x="13" y="17" textAnchor="middle" fontSize="7" fontFamily="var(--mono)" fill={progress > 0 ? colColor : 'var(--txt3)'}>{progress > 0 ? `${Math.round(progress)}` : '·'}</text>}
        </svg>
      </div>
      {ch.description && hovered && <div style={{ fontSize: 11, color: 'var(--txt3)', marginBottom: 7, lineHeight: 1.4 }}>{ch.description}</div>}
      <div style={{ display: 'flex', gap: 8, paddingTop: 4 }}>
        {topicCount > 0 && <span style={{ fontSize: 10, color: 'var(--txt3)', background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 4, padding: '1px 5px' }}>{topicCount}t</span>}
        {conceptCount > 0 && <span style={{ fontSize: 10, color: 'var(--txt3)', background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 4, padding: '1px 5px' }}>{conceptCount}c</span>}
        {active && <span style={{ fontSize: 10, color: '#fbbf24', marginLeft: 'auto' }}>active</span>}
      </div>
    </div>
  );
}

// ── Space generating animation ────────────────────────────────────────────────
function SpaceGeneratingAnimation({ step }) {
  const steps = ['Analysing domain…', 'Discovering expert patterns…', 'Scaffolding workspace…', 'Initialising learning DB…', 'Generating roadmap…', 'Almost ready…'];
  const [cur, setCur] = useState(0);
  useEffect(() => { const t = setInterval(() => setCur(s => (s + 1) % steps.length), 1400); return () => clearInterval(t); }, []);
  const R = 48, cx = 64, cy = 64;
  const dots = Array.from({ length: 6 }, (_, i) => ({ x: cx + R * Math.cos((i / 6) * 2 * Math.PI), y: cy + R * Math.sin((i / 6) * 2 * Math.PI), delay: i * 0.2 }));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 20 }}>
      <svg width="128" height="128" viewBox="0 0 128 128" style={{ overflow: 'visible' }}>
        <style>{`@keyframes sOrbit{0%,100%{opacity:.2}50%{opacity:1}}@keyframes sSpin{to{transform:rotate(360deg)}}.sg-ring{transform-origin:64px 64px;animation:sSpin 2.4s linear infinite}.sg-dot{animation:sOrbit 1.2s ease-in-out infinite}`}</style>
        <circle cx={cx} cy={cy} r="30" fill="none" stroke="var(--accent-border)" strokeWidth="2" />
        <circle cx={cx} cy={cy} r="30" fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeDasharray="48 140" strokeLinecap="round" style={{ transformOrigin: `${cx}px ${cy}px`, animation: 'sSpin 1.6s linear infinite' }} />
        <text x={cx} y={cy + 6} textAnchor="middle" fontSize="20" fill="var(--accent)">⚡</text>
        <g className="sg-ring">{dots.map((d, i) => <circle key={i} className="sg-dot" cx={d.x} cy={d.y} r="4" fill="var(--accent)" style={{ animationDelay: `${d.delay}s` }} />)}</g>
      </svg>
      <div style={{ fontSize: 13, color: 'var(--accent)', minWidth: 220, textAlign: 'center', fontFamily: 'var(--mono)' }}>{steps[cur]}</div>
    </div>
  );
}

// ── Shared: generate topics + concepts for a chapter ────────────────────────
// Limit concurrency when fetching concepts for multiple topics in parallel.
async function generateTopicsAndConcepts(spaceId, chapter, instruction, onPatchChapter) {
  const baseId = Date.now().toString(36);
  const r = await api(`/spaces/${spaceId}/roadmap/generate-children`, {
    method: 'POST',
    body: JSON.stringify({ parent_type: 'chapter', parent_title: chapter.title, instruction: instruction.trim() }),
  });
  const topicTitles = (r.children || []).filter(Boolean);

  // Fetch concepts with max 3 concurrent requests to avoid hammering the API
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
    id: `tp_${baseId}_${i}`,
    title: tTitle,
    order: (chapter.topics || []).length + i,
    status: 'not_started',
    concepts: (conceptResults[i]?.children || []).filter(Boolean).map((cTitle, j) => ({
      id: `cn_${baseId}_${i}_${j}`, title: cTitle, description: '', status: 'not_started', order: j,
      tags: [], related_concepts: [], notes: [], quicktests: [],
    })),
  }));
  await onPatchChapter({ ...chapter, topics: [...(chapter.topics || []), ...newTopics] });
}

// ── Spaces router ─────────────────────────────────────────────────────────────
export default function Spaces() {
  const { spacesView, currentSpace, currentChapter, currentTopic } = useStore();
  if (spacesView === 'home') return <SpaceHome key={currentSpace?.name} />;
  if (spacesView === 'chapter') return <ChapterView key={currentChapter?.id} />;
  if (spacesView === 'topic') return <TopicView key={`${currentTopic?.id}-${currentTopic?._openConceptId}`} />;
  return <SpacesList />;
}


// ── Space creation wizard ─────────────────────────────────────────────────────
function CreateSpaceWizard({ onClose, onCreated, onSpaceCreated }) {
  const [step, setStep] = useState(1); // 1=domain 2=details 3=creating 4=clarify 5=overview
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState(null);
  const [form, setForm] = useState({ dir: '', name: '', bg: '', goal: '', rag: false });
  const [creating, setCreating] = useState(false);
  const [refining, setRefining] = useState(false);
  const [clarifyQs, setClarifyQs] = useState([]);
  const [clarifyAnswers, setClarifyAnswers] = useState({});
  const [createResult, setCreateResult] = useState(null);
  const [overviewData, setOverviewData] = useState(null);
  const [roadmapReady, setRoadmapReady] = useState(false);
  const { ok, err } = useStore();

  useEffect(() => {
    if (step !== 5 || !createResult) return;
    let cancelled = false;
    let timeoutId = null;
    const poll = async () => {
      const spaceId = encodeURIComponent(createResult?.name || '');
      while (!cancelled) {
        try {
          const rm = await api(`/spaces/${spaceId}/roadmap`);
          if (rm?.chapters?.length > 0) {
            if (!cancelled) setRoadmapReady(true);
            return;
          }
        } catch { /* continue polling */ }
        await new Promise(res => { timeoutId = setTimeout(res, 3000); });
      }
    };
    poll();
    return () => { cancelled = true; clearTimeout(timeoutId); };
  }, [step, createResult]);
  const pf = (p) => setForm(f => ({ ...f, ...p }));

  const _fetchOverviewAndShowIntro = async (res) => {
    const spaceId = encodeURIComponent(res?.name || '');
    let overview = null;
    if (spaceId) {
      for (let i = 0; i < 4; i++) {
        try {
          const d = await api(`/spaces/${spaceId}/overview`);
          if (d && Object.keys(d).length > 0) { overview = d; break; }
        } catch {}
        await new Promise(r => setTimeout(r, 2000));
      }
    }
    setOverviewData(overview || {});
    setCreateResult(res);
    setStep(5);
    onSpaceCreated?.(res);
  };

  const filteredDomains = EXPERT_SPACES.filter(d =>
    !search || d.label.toLowerCase().includes(search.toLowerCase()) ||
    d.desc.toLowerCase().includes(search.toLowerCase()) ||
    (d.tools || []).some(t => t.includes(search.toLowerCase()))
  );

  const handleCreate = async () => {
    if (creating) return;
    const dir = form.dir.trim();
    if (!dir) { err('Workspace directory is required'); return; }
    if (selected?.id === 'custom' && !form.goal.trim()) { err('Learning goal is required for custom domains'); return; }
    setCreating(true);
    setStep(3); // show creating animation immediately
    try {
      const res = await api('/spaces/init', {
        method: 'POST',
        body: JSON.stringify({
          directory: dir, space_type: selected?.id || 'custom',
          name: form.name.trim(), background: form.bg.trim(), goal: form.goal.trim(), rag_enabled: form.rag,
        }),
      });
      setCreateResult(res);
      onSpaceCreated?.(res); // always notify parent so modal close navigates correctly
      const qs = res?.clarifying_questions || [];
      if (qs.length > 0) {
        setClarifyQs(qs);
        setStep(4);
      } else {
        ok('Space created!');
        _fetchOverviewAndShowIntro(res);
      }
    } catch (e) {
      err(e.message);
      setCreating(false);
      setStep(2); // go back to form on error
    }
  };

  // Step 3: Creating animation (replaces fullscreen overlay)
  if (step === 3) return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '40px 0', gap: 24 }}>
      <SpaceGeneratingAnimation />
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--accent)', marginBottom: 6 }}>Setting up your Space…</div>
        <div style={{ fontSize: 12.5, color: 'var(--txt3)' }}>AI is discovering your domain and scaffolding the workspace.</div>
      </div>
    </div>
  );

  // Step 1: Domain picker
  if (step === 1) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <style>{`@keyframes cardIn{from{opacity:0;transform:translateY(8px) scale(.97)}to{opacity:1;transform:none}}.domain-card{animation:cardIn .22s ease both}`}</style>
      <div>
        <input className="s-input" style={{ width: '100%', marginBottom: 12 }}
          placeholder="🔍  Search domains, tools…" value={search} onChange={e => setSearch(e.target.value)} autoFocus />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, maxHeight: 360, overflowY: 'auto' }}>
          {filteredDomains.map((d, idx) => (
            <div key={d.id} className="domain-card" onClick={() => setSelected(d)}
              style={{ border: `2px solid ${selected?.id === d.id ? d.color : 'var(--brd)'}`, borderRadius: 10, padding: '12px 14px', cursor: 'pointer', transition: 'border-color 0.18s, box-shadow 0.18s, transform 0.15s, background 0.18s', background: selected?.id === d.id ? `${d.color}14` : 'var(--surface2)', animationDelay: `${idx * 0.04}s` }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = d.color; e.currentTarget.style.boxShadow = `0 0 0 1px ${d.color}40`; e.currentTarget.style.transform = 'translateY(-2px)'; }}
              onMouseLeave={e => { e.currentTarget.style.transform = ''; if (selected?.id !== d.id) { e.currentTarget.style.borderColor = 'var(--brd)'; e.currentTarget.style.boxShadow = ''; } }}>
              <div style={{ fontSize: 22, marginBottom: 6 }}>{d.icon}</div>
              <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--txt)', marginBottom: 4 }}>{d.label}</div>
              <div style={{ fontSize: 11, color: 'var(--txt3)', lineHeight: 1.4, marginBottom: 8 }}>{d.desc}</div>
              {d.tools.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
                  {d.tools.slice(0, 3).map(t => <span key={t} style={{ fontSize: 9.5, padding: '1px 5px', borderRadius: 4, background: `${d.color}22`, color: d.color, border: `1px solid ${d.color}44` }}>{t}</span>)}
                </div>
              )}
              {selected?.id === d.id && (
                <div style={{ marginTop: 8, padding: '6px 8px', background: `${d.color}18`, borderRadius: 6, borderLeft: `3px solid ${d.color}` }}>
                  <div style={{ fontSize: 10, color: d.color, fontWeight: 600, marginBottom: 2 }}>EXPERT TIP</div>
                  <div style={{ fontSize: 10.5, color: 'var(--txt2)', lineHeight: 1.4 }}>{d.expertTip}</div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button className="btn btn-muted btn-sm" onClick={onClose}>Cancel</button>
        <button className="btn btn-accent btn-sm" disabled={!selected} onClick={() => setStep(2)}>
          Continue with {selected ? selected.label : '…'} →
        </button>
      </div>
    </div>
  );

  // Step 2: Details
  if (step === 2) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', background: `${selected.color}14`, borderRadius: 8, border: `1px solid ${selected.color}44` }}>
        <span style={{ fontSize: 24 }}>{selected.icon}</span>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--txt)' }}>{selected.label}</div>
          <div style={{ fontSize: 11, color: 'var(--txt3)' }}>{selected.desc}</div>
        </div>
        <button className="btn btn-muted btn-sm" style={{ marginLeft: 'auto', fontSize: 10.5 }} onClick={() => setStep(1)}>Change</button>
      </div>
      <div>
        <label className="form-label">Workspace directory *</label>
        <input className="s-input mono" value={form.dir} onChange={e => pf({ dir: e.target.value })} placeholder="/home/user/my-space" autoFocus />
        {selected?.id === 'custom' && <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginTop: 4 }}>AI will discover your domain from your goal and background.</div>}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        <div>
          <label className="form-label">Display name</label>
          <input className="s-input" value={form.name} onChange={e => pf({ name: e.target.value })} placeholder="My Space" />
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', paddingBottom: 2 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--txt2)', cursor: 'pointer' }}>
            <input type="checkbox" checked={form.rag} onChange={e => pf({ rag: e.target.checked })} />
            Enable RAG (vector search)
          </label>
        </div>
      </div>
      <div>
        <label className="form-label">Your background</label>
        <input className="s-input" value={form.bg} onChange={e => pf({ bg: e.target.value })} placeholder="e.g. final-year Btech, intermediate Python, interest in spirituality" />
      </div>
      <div>
        <label className="form-label">Learning goal {selected?.id === 'custom' ? '*' : ''}</label>
        <input className="s-input" value={form.goal} onChange={e => pf({ goal: e.target.value })}
          placeholder={selected?.id === 'custom' ? "e.g. decode Bhagavad Gita for modern life" : "e.g. master ML for production systems"} />
      </div>
      {selected?.folders?.length > 0 && (
        <div style={{ fontSize: 11, color: 'var(--txt3)', padding: '8px 10px', background: 'var(--surface2)', borderRadius: 6, border: '1px solid var(--brd)' }}>
          <strong style={{ color: 'var(--txt2)' }}>Workspace folders: </strong>{selected.folders.join(', ')}
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button className="btn btn-muted btn-sm" onClick={() => setStep(1)}>← Back</button>
        <button className="btn btn-accent btn-sm" onClick={handleCreate} disabled={creating || step === 3 || !form.dir.trim()}>
          {creating || step === 3 ? 'Creating…' : 'Create Space'}
        </button>
      </div>
    </div>
  );

  // Step 5: Brief overview / orientation
  if (step === 5) {
    const ov = overviewData || {};
    const hasContent = ov.what_is_this || ov.prerequisites?.length || ov.efficient_methods?.length;
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        <style>{`@keyframes ovFadeUp{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}.ov-card{animation:ovFadeUp .35s ease both}`}</style>
        <div className="ov-card" style={{ animationDelay: '0s', padding: '10px 14px', background: 'var(--accent-dim)', border: '1px solid var(--accent-border)', borderRadius: 9, marginBottom: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent)', marginBottom: 2 }}>🎉 Your space is ready!</div>
          <div style={{ fontSize: 12, color: 'var(--txt2)' }}>Your roadmap is generating in the background. Here's your orientation:</div>
        </div>
        {!hasContent ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '24px 0', gap: 10, color: 'var(--txt3)', fontSize: 12 }}>
            <SpaceGeneratingAnimation />
            <div style={{ marginTop: 6 }}>Generating your personalised overview…</div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 360, overflowY: 'auto', paddingRight: 4 }}>
            {ov.what_is_this && (
              <div className="ov-card" style={{ animationDelay: '.05s', padding: '10px 13px', background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 8, borderLeft: '3px solid var(--accent)' }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 4 }}>What is this?</div>
                <div style={{ fontSize: 12.5, color: 'var(--txt)', lineHeight: 1.6 }}>{ov.what_is_this}</div>
              </div>
            )}
            {ov.starting_overview && (
              <div className="ov-card" style={{ animationDelay: '.1s', padding: '10px 13px', background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 8 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--txt2)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 4 }}>Where You Start</div>
                <div style={{ fontSize: 12.5, color: 'var(--txt2)', lineHeight: 1.6 }}>{ov.starting_overview}</div>
              </div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {ov.prerequisites?.length > 0 && (
                <div className="ov-card" style={{ animationDelay: '.15s', padding: '10px 12px', background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 8 }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: '#fbbf24', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 6 }}>Prerequisites</div>
                  {ov.prerequisites.map((p, i) => <div key={i} style={{ fontSize: 11.5, color: 'var(--txt2)', lineHeight: 1.4, marginBottom: 3 }}>◆ {p}</div>)}
                </div>
              )}
              {ov.efficient_methods?.length > 0 && (
                <div className="ov-card" style={{ animationDelay: '.2s', padding: '10px 12px', background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 8 }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: '#34d399', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 6 }}>Efficient Methods</div>
                  {ov.efficient_methods.map((m, i) => <div key={i} style={{ fontSize: 11.5, color: 'var(--txt2)', lineHeight: 1.4, marginBottom: 3 }}>✓ {m}</div>)}
                </div>
              )}
            </div>
            {ov.pro_tips?.length > 0 && (
              <div className="ov-card" style={{ animationDelay: '.25s', padding: '10px 13px', background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 8 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: '#a78bfa', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 6 }}>Pro Tips</div>
                {ov.pro_tips.map((t, i) => <div key={i} style={{ fontSize: 11.5, color: 'var(--txt2)', lineHeight: 1.4, marginBottom: 3 }}>★ {t}</div>)}
              </div>
            )}
          </div>
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 10, marginTop: 14 }}>
          {roadmapReady
            ? <button className="btn btn-accent btn-sm" onClick={() => onCreated(createResult)}>Enter Space →</button>
            : <span style={{ fontSize: 11.5, color: 'var(--txt3)', display: 'flex', alignItems: 'center', gap: 6 }}><span className="spin" style={{ width: 12, height: 12, borderWidth: 2 }} />Roadmap generating…</span>
          }
        </div>
      </div>
    );
  }

  // Step 4: Clarifying questions from AI
  if (step === 4) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ padding: '10px 14px', background: 'var(--accent-dim)', borderRadius: 8, border: '1px solid var(--accent-border)' }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent)', marginBottom: 4 }}>✨ Space created!</div>
          <div style={{ fontSize: 12, color: 'var(--txt2)' }}>AI has a couple of questions to refine your learning path.</div>
        </div>
        {clarifyQs.map((q, i) => (
          <div key={i}>
            <label className="form-label">{q}</label>
            <input className="s-input" value={clarifyAnswers[i] || ''} onChange={e => setClarifyAnswers(a => ({ ...a, [i]: e.target.value }))} placeholder="Your answer…" />
          </div>
        ))}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button className="btn btn-muted btn-sm" disabled={refining} onClick={() => { setRefining(true); _fetchOverviewAndShowIntro(createResult).finally(() => setRefining(false)); }}>{refining ? 'Please wait…' : 'Skip'}</button>
          <button
            className="btn btn-accent btn-sm"
            disabled={refining}
            onClick={async () => {
              if (refining) return;
              setRefining(true);
              try {
                await api(`/spaces/refine`, {
                  method: 'POST',
                  body: JSON.stringify({
                    directory: createResult?.directory || form.dir,
                    answers: clarifyQs.map((q, i) => `${q}: ${clarifyAnswers[i] || ''}`).join('\n'),
                  }),
                });
                ok('Preferences saved!');
              } catch { /* non-fatal */ }
              setRefining(false);
              await _fetchOverviewAndShowIntro(createResult);
            }}
          >
            {refining ? 'Generating…' : 'Save & Continue'}
          </button>
        </div>
      </div>
    );
  }
}


// ── Space Settings Overlay ────────────────────────────────────────────────────
function SpaceSettingsOverlay({ space, onClose, defaultTab }) {
  const [settings, setSettings] = useState(null);
  const [tab, setTab] = useState(defaultTab || 'config');
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({});
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const { ok, err, setSpacesView, setCurrentSpace, setSpaceRoadmap } = useStore();
  const sid = encodeURIComponent(space?.name || '');

  useEffect(() => {
    if (!space?.name) return;
    api(`/spaces/${sid}/settings`).then(s => {
      setSettings(s);
      setForm({
        goal: s.goal || '',
        background: s.background || '',
        domain_name: s.domain || '',
        rag_enabled: s.rag_enabled || false,
        llm_context: s.llm_context || '',
        soul_md: s.soul_md || '',
        memory_md: s.memory_md || '',
        preferred_style: s.preferred_style || 'visual + hands-on',
        daily_goal_minutes: s.daily_goal_minutes ?? 30,
        is_technical: s.is_technical || false,
        mastered_concepts: s.mastered_concepts || [],
        struggling_concepts: s.struggling_concepts || [],
        badges: s.badges || [],
      });
    }).catch(() => {});
  }, [space?.name]);

  const save = async () => {
    setSaving(true);
    try {
      await api(`/spaces/${sid}/settings`, { method: 'PATCH', body: JSON.stringify(form) });
      ok('Settings saved');
    } catch (e) { err(e.message); }
    setSaving(false);
  };

  const pf = (p) => setForm(f => ({ ...f, ...p }));

  const regenRoadmap = async () => {
    if (!space?.directory || regenerating) return;
    setRegenerating(true);
    try {
      await api('/spaces/regenerate-roadmap', {
        method: 'POST',
        body: JSON.stringify({ directory: space.directory }),
      });
      setSpaceRoadmap(null);
      ok('Roadmap regeneration started — reload the space to see changes');
    } catch (e) { err(e.message); }
    setRegenerating(false);
  };

  const handleDelete = async () => {
    if (!space?.name || deleting) return;
    if (confirmText.trim() !== space.name) {
      err('Please type the exact space name to confirm.');
      return;
    }
    setDeleting(true);
    try {
      await api('/spaces/delete', {
        method: 'POST',
        body: JSON.stringify({ directory: space.directory, name: space.name }),
      });
      ok('Space moved to trash');
      setCurrentSpace(null);
      setSpaceRoadmap(null);
      setSpacesView('list');
      onClose();
    } catch (e) {
      err(e.message);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Overlay title={`⚙ Settings — ${space?.name}`} onClose={onClose} width="700px" height="82%">
      {regenerating ? (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 20 }}>
          <SpaceGeneratingAnimation />
          <div style={{ fontSize: 12, color: 'var(--txt3)', textAlign: 'center' }}>Rebuilding your roadmap — this takes about a minute…</div>
        </div>
      ) : !settings ? (
        <div className="loading-center"><span className="spin" /></div>
      ) : (
        <SettingsTabs
          tab={tab}
          setTab={setTab}
          settings={settings}
          form={form}
          onChange={pf}
          onSave={save}
          saving={saving}
          onDelete={() => setConfirmOpen(true)}
          onRegenerateRoadmap={regenRoadmap}
          regenerating={regenerating}
        />
      )}

      {confirmOpen && (
        <Modal
          title="Delete Space"
          onClose={() => { if (!deleting) { setConfirmOpen(false); setConfirmText(''); } }}
          footer={
            <>
              <button className="btn btn-muted btn-sm" onClick={() => { setConfirmOpen(false); setConfirmText(''); }} disabled={deleting}>Cancel</button>
              <button className="btn btn-del btn-sm" onClick={handleDelete} disabled={deleting}>
                {deleting ? 'Deleting…' : 'Delete Space'}
              </button>
            </>
          }
        >
          <div style={{ fontSize: 12.5, color: 'var(--txt2)', marginBottom: 10 }}>
            Type the space name to confirm deletion:
          </div>
          <div style={{ fontSize: 12, color: 'var(--txt3)', marginBottom: 10 }}>
            <strong>{space?.name}</strong>
          </div>
          <input
            className="s-input"
            value={confirmText}
            onChange={e => setConfirmText(e.target.value)}
            placeholder="Enter space name exactly"
            autoFocus
          />
        </Modal>
      )}
    </Overlay>
  );
}



// ── Spaces list ───────────────────────────────────────────────────────────────
function SpacesList() {
  const [showCreate, setShowCreate] = useState(false);
  const [wizardCreatedResult, setWizardCreatedResult] = useState(null);
  const [settingsSpace, setSettingsSpace] = useState(null);
  const [manageOpen, setManageOpen] = useState(false);
  const [trashed, setTrashed] = useState([]);
  const [trashLoading, setTrashLoading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleteConfirm, setDeleteConfirm] = useState('');
  const { setSpacesView, setCurrentSpace, setSpaceRoadmap, ok, err } = useStore();

  // Memoize transform so useFetch doesn't re-run when SpacesList re-renders
  const spacesTransform = useCallback(
    (r) => (Array.isArray(r) ? r : r?.spaces ?? r?.items ?? []),
    []
  );
  const { data: spaces = [], loading, reload, setData: setSpaces } = useFetch('/spaces', [], {
    initialData: [],
    transform: spacesTransform,
  });

  const toggleActive = async (space, activate) => {
    // Optimistic update: only one space can be active at a time
    setSpaces(prev => prev.map(s => ({
      ...s,
      is_active: activate ? (s.directory === space.directory) : (s.directory === space.directory ? false : s.is_active),
    })));
    try {
      await api('/spaces/activate', {
        method: 'POST',
        body: JSON.stringify({ directory: activate ? space.directory : '' }),
      });
      ok(activate ? `${space.name} set as active space` : `${space.name} deactivated`);
      reload();
    } catch (e) {
      err(e.message);
      reload(); // revert optimistic update on error
    }
  };

  const loadTrashed = async () => {
    setTrashLoading(true);
    try {
      const r = await api('/spaces/trashed');
      setTrashed(Array.isArray(r) ? r : []);
    } catch (e) { err(e.message); }
    setTrashLoading(false);
  };

  const openManage = async () => {
    setManageOpen(true);
    await loadTrashed();
  };

  const recoverSpace = async (space) => {
    try {
      const r = await api('/spaces/recover', { method: 'POST', body: JSON.stringify({ directory: space.directory }) });
      const status = r?.space?.recovery_status;
      if (status === 'already_exists') {
        const conflictPath = r?.space?.conflict_trash_path;
        ok(conflictPath
          ? `Space already exists. Kept backup at ${conflictPath}`
          : 'Space already exists. Kept trashed backup for safety.');
      } else {
        ok('Space recovered');
      }
      await Promise.all([reload(), loadTrashed()]);
    } catch (e) { err(e.message); }
  };

  const confirmPermanentDelete = (space) => {
    setDeleteTarget(space);
    setDeleteConfirm('');
  };

  const deletePermanently = async () => {
    if (!deleteTarget) return;
    if ((deleteConfirm || '').trim() !== deleteTarget.name) {
      err('Please type the exact space name to confirm.');
      return;
    }
    try {
      await api('/spaces/delete-permanent', { method: 'POST', body: JSON.stringify({ directory: deleteTarget.directory }) });
      ok('Space permanently deleted');
      setDeleteTarget(null);
      setDeleteConfirm('');
      await loadTrashed();
    } catch (e) {
      err(e.message);
    }
  };

  const handleSpaceCreated = async (created) => {
    setShowCreate(false);
    setWizardCreatedResult(null);
    await reload();
    if (created?.directory) {
      setCurrentSpace({ name: created.name, directory: created.directory, space_type: created.space_type });
      setSpaceRoadmap(null);
      setSpacesView('home');
    }
  };

  return (
    <div className="page">
      <header className="pg-header">
        <div className="pg-title-group">
          <h1 className="pg-title">Spaces</h1>
          <p className="pg-sub">Mastery-learning workspaces</p>
        </div>
        <div className="pg-actions">
          <button className="btn btn-muted btn-sm" onClick={openManage}>Manage</button>
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
            {spaces.map(s => <SpaceCard key={s.name || s.id} variant="list" space={s}
              onClick={() => { setCurrentSpace(s); setSpaceRoadmap(null); setSpacesView('home'); }}
              onToggleActive={toggleActive}
              onSettings={setSettingsSpace} />)}
          </div>
        )}
      </div>

      {showCreate && (
        <Modal
          title="Create Space"
          onClose={() => {
            if (wizardCreatedResult) {
              // space was already created (step 3) — treat close as Skip so we navigate correctly
              handleSpaceCreated(wizardCreatedResult);
              return;
            }
            setShowCreate(false);
            setWizardCreatedResult(null);
          }}
          wide
        >
          <CreateSpaceWizard
            onClose={() => { setShowCreate(false); setWizardCreatedResult(null); }}
            onSpaceCreated={(res) => setWizardCreatedResult(res)}
            onCreated={handleSpaceCreated}
          />
        </Modal>
      )}

      {settingsSpace && <SpaceSettingsOverlay space={settingsSpace} onClose={() => setSettingsSpace(null)} />}

      {manageOpen && (
        <Modal title="Manage Spaces" onClose={() => setManageOpen(false)} wide>
          {trashLoading ? (
            <div className="loading-center"><span className="spin" /></div>
          ) : trashed.length === 0 ? (
            <div className="empty">
              <div className="empty-ttl">No trashed spaces</div>
              <div className="empty-desc">Deleted spaces stay here for 30 days.</div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {trashed.map(s => (
                <div key={s.directory} className="card" style={{ padding: '10px 12px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--txt)' }}>{s.name || s.directory}</div>
                      <div style={{ fontSize: 11, color: 'var(--txt3)' }}>{s.directory}</div>
                    </div>
                    <button className="btn btn-muted btn-sm" onClick={() => recoverSpace(s)}>Recover</button>
                    <button className="btn btn-del btn-sm" onClick={() => confirmPermanentDelete(s)}>Delete</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Modal>
      )}

      {deleteTarget && (
        <Modal
          title="Delete Permanently"
          onClose={() => { setDeleteTarget(null); setDeleteConfirm(''); }}
          footer={
            <>
              <button className="btn btn-muted btn-sm" onClick={() => { setDeleteTarget(null); setDeleteConfirm(''); }}>Cancel</button>
              <button className="btn btn-del btn-sm" onClick={deletePermanently}>Delete Permanently</button>
            </>
          }
        >
          <div style={{ fontSize: 12.5, color: 'var(--txt2)', marginBottom: 10 }}>
            Type the space name to confirm permanent deletion:
          </div>
          <div style={{ fontSize: 12, color: 'var(--txt3)', marginBottom: 10 }}>
            <strong>{deleteTarget?.name}</strong>
          </div>
          <input
            className="s-input"
            value={deleteConfirm}
            onChange={e => setDeleteConfirm(e.target.value)}
            placeholder="Enter space name exactly"
            autoFocus
          />
        </Modal>
      )}
    </div>
  );
}


// ── Space Home ────────────────────────────────────────────────────────────────
function SpaceHome() {
  const { currentSpace, spaceRoadmap, setSpaceRoadmap, setCurrentChapter, setCurrentTopic, setSpacesView, ok, err } = useStore();
  const [hero, setHero] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [activePanel, setActivePanel] = useState(null);
  const [showHistory, setShowHistory] = useState(false);
  const [addingChapter, setAddingChapter] = useState(false);
  const [newChapterTitle, setNewChapterTitle] = useState('');
  const [newChapterDesc, setNewChapterDesc] = useState('');
  const [promptBar, setPromptBar] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [insightsPreview, setInsightsPreview] = useState(null);
  const sid = encodeURIComponent(currentSpace?.name || '');

  const loadHero = useCallback(async () => {
    try { setHero(await api(`/spaces/${sid}/profile`)); } catch {}
  }, [sid]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadRoadmap = useCallback(async () => {
    try { setSpaceRoadmap(await api(`/spaces/${sid}/roadmap`)); } catch {}
  }, [sid, setSpaceRoadmap]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadInsightsPreview = useCallback(async () => {
    try {
      const r = await api(`/spaces/${sid}/workspace/insights`);
      setInsightsPreview(r.has_content ? r : null);
    } catch { /* insights may not exist yet */ }
  }, [sid]);

  useEffect(() => {
    if (!currentSpace) return;
    loadHero();
    loadInsightsPreview();
  }, [currentSpace?.name, loadHero, loadInsightsPreview]);

  // Only load roadmap if not already loaded for this space
  useEffect(() => {
    if (!currentSpace || spaceRoadmap) return;
    loadRoadmap();
  }, [currentSpace?.name, loadRoadmap, spaceRoadmap]);

  useEffect(() => {
    if (spaceRoadmap?.sessions) setSessions([...(spaceRoadmap.sessions)].reverse().slice(0, 20));
  }, [spaceRoadmap?.sessions]);

  const patchChapters = async (chapters) => {
    const withOrder = chapters.map((c, i) => ({ ...c, order: i }));
    try { const rm = await api(`/spaces/${sid}/roadmap`, { method: 'PATCH', body: JSON.stringify({ chapters: withOrder }) }); setSpaceRoadmap(rm); } catch (e) { err(e.message); }
  };
  const patchChapter = async (updatedChapter) => {
    const chapters = (spaceRoadmap?.chapters || []).map(c => c.id === updatedChapter.id ? updatedChapter : c);
    await patchChapters(chapters);
  };

  const addChapter = async () => {
    const title = newChapterTitle.trim(); if (!title) return;
    const ch = { id: `ch_${Date.now().toString(36)}`, title, description: newChapterDesc.trim(), order: spaceRoadmap?.chapters?.length || 0, status: 'not_started', progress_pct: 0, topics: [] };
    await patchChapters([...(spaceRoadmap?.chapters || []), ch]);
    ok(`Chapter "${title}" added`); setNewChapterTitle(''); setNewChapterDesc(''); setAddingChapter(false);
  };

  const generateChapterTopics = async (chId, instruction = '') => {
    const ch = (spaceRoadmap?.chapters || []).find(c => c.id === chId); if (!ch) return;
    ok('Generating topics and concepts…');
    try {
      await generateTopicsAndConcepts(sid, ch, instruction, patchChapter);
      ok('Topics generated successfully.');
    } catch (e) { err(e.message); }
  };

  const editChapterDescription = async (chId, next) => {
    const ch = (spaceRoadmap?.chapters || []).find(c => c.id === chId); if (!ch) return;
    await patchChapter({ ...ch, description: next.trim() }); ok("Description updated.");
  };

  if (!currentSpace) return null;

  const continueLearning = React.useMemo(() => {
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
  }, [spaceRoadmap?.chapters, sessions]);

  const goToContinue = () => {
    if (!continueLearning) return;
    setCurrentChapter({ id: continueLearning.chapter.id, title: continueLearning.chapter.title, data: continueLearning.chapter });
    if (continueLearning.topic) { setCurrentTopic({ ...continueLearning.topic, chapterId: continueLearning.chapter.id }); setSpacesView('topic'); }
    else setSpacesView('chapter');
  };

  const panels = [
    { id: 'notes', label: 'Notes' }, { id: 'tasks', label: 'Tasks' }, { id: 'files', label: 'Workspace' },
    { id: 'srs', label: 'SRS' }, { id: 'graph', label: 'Graph' }, { id: 'digest', label: 'Digest' },
    { id: 'practice', label: 'Practice' }, { id: 'optimizer', label: 'Insights' }, { id: 'agents', label: 'Agents' },
  ];

  const progress = React.useMemo(() => {
    const chs = spaceRoadmap?.chapters || [];
    if (!chs.length) return 0;
    return Math.round(chs.reduce((a, c) => a + (c.progress_pct || 0), 0) / chs.length);
  }, [spaceRoadmap?.chapters]);
  const displayDomain = hero?.domain || currentSpace?.domain || (currentSpace?.space_type === 'custom' ? '' : (currentSpace?.space_type || '').replace(/_/g, ' '));

  return (
    <div className="page">
      <div className="space-home-hdr">
        <div className="sh-left">
          <nav className="breadcrumb">
            <button className="bc-link" onClick={() => setSpacesView('list')}>Spaces</button>
            <span className="bc-sep">›</span>
            <span className="bc-current">{currentSpace.name}</span>
          </nav>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <h1 className="pg-title">{currentSpace.name}</h1>
            <button className="btn btn-muted btn-sm" style={{ fontSize: 12, padding: '3px 10px' }} title="Space settings" onClick={() => setSettingsOpen(true)}>⚙ Settings</button>
          </div>
          {displayDomain && <p className="pg-sub">{displayDomain}</p>}
        </div>
        <div className="sh-right">
          <div className="progress-ring-wrap">
            <svg width="64" height="64" viewBox="0 0 64 64">
              <circle cx="32" cy="32" r="26" className="progress-ring-bg" />
              <circle cx="32" cy="32" r="26" className="progress-ring-fg"
                style={{ strokeDasharray: `${2 * Math.PI * 26}`, strokeDashoffset: `${2 * Math.PI * 26 * (1 - progress / 100)}`, transform: 'rotate(-90deg)', transformOrigin: 'center' }} />
            </svg>
            <div className="ring-label"><div className="ring-pct">{progress}%</div><div className="ring-done">done</div></div>
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
              <button key={p.id} className="btn btn-muted btn-sm"
                style={p.id === 'optimizer' && insightsPreview ? { borderColor: 'var(--accent)', color: 'var(--accent)', position: 'relative' } : {}}
                onClick={() => setActivePanel({ name: p.id, props: {} })}>
                {p.label}
                {p.id === 'optimizer' && insightsPreview && (
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent)', display: 'inline-block', marginLeft: 5, verticalAlign: 'middle' }} />
                )}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Insights preview card — shown when workspace analyser has run */}
      {insightsPreview && (
        <div style={{ margin: '0 0 16px 0', padding: '12px 18px', background: 'var(--surface)',
          border: '1px solid var(--accent-border)', borderRadius: 10,
          borderLeft: '3px solid var(--accent)', cursor: 'pointer', transition: 'background 0.15s' }}
          onClick={() => setActivePanel({ name: 'optimizer', props: {} })}
          onMouseEnter={e => e.currentTarget.style.background = 'var(--accent-dim)'}
          onMouseLeave={e => e.currentTarget.style.background = 'var(--surface)'}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 15 }}>⚡</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 3 }}>
                Workspace Insights Available
              </div>
              <div style={{ fontSize: 12.5, color: 'var(--txt2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {insightsPreview.content
                  ? insightsPreview.content.split('\n').find(l => l.trim() && !l.startsWith('#'))?.trim()?.slice(0, 120) || 'View workspace analysis and personalised recommendations'
                  : 'View workspace analysis and personalised recommendations'}
              </div>
            </div>
            <span style={{ color: 'var(--accent)', fontSize: 14, flexShrink: 0 }}>View →</span>
          </div>
        </div>
      )}

      <div className="space-home-body">
        <div className="roadmap-section">
          <div className="roadmap-section-hdr">
            <span className="roadmap-section-title">Roadmap</span>
            <span className="roadmap-hint">double-click to rename · drag between columns</span>
            {addingChapter ? (
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                <input className="s-input" style={{ width: 200, fontSize: 12, padding: '3px 8px' }} autoFocus value={newChapterTitle}
                  onChange={e => setNewChapterTitle(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') addChapter(); if (e.key === 'Escape') { setAddingChapter(false); setNewChapterTitle(''); setNewChapterDesc(''); } }}
                  placeholder="Chapter title…" />
                <input className="s-input" style={{ width: 280, fontSize: 12, padding: '3px 8px' }} value={newChapterDesc}
                  onChange={e => setNewChapterDesc(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Escape') { setAddingChapter(false); setNewChapterTitle(''); setNewChapterDesc(''); } }}
                  placeholder="Short description…" />
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
            <PromptInline title={`Generate topics for: ${promptBar.title}`} value={promptBar.value}
              onChange={(v) => setPromptBar(p => ({ ...p, value: v }))}
              onSubmit={async () => { const p = promptBar; setPromptBar(null); await generateChapterTopics(p.chId, p.value || ''); }}
              onCancel={() => setPromptBar(null)} placeholder="Optional instructions…" submitLabel="Generate" multiline />
          )}
          {promptBar?.type === 'chapter_desc' && (
            <PromptInline title={`Edit description: ${promptBar.title}`} value={promptBar.value}
              onChange={(v) => setPromptBar(p => ({ ...p, value: v }))}
              onSubmit={async () => { const p = promptBar; setPromptBar(null); await editChapterDescription(p.chId, p.value || ''); }}
              onCancel={() => setPromptBar(null)} placeholder="Short description…" submitLabel="Save" multiline={false} />
          )}
          {continueLearning && (
            <div onClick={goToContinue} style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '10px 16px', marginBottom: 14, background: 'var(--surface)', border: '1px solid var(--accent-border)', borderRadius: 10, cursor: 'pointer', transition: 'background 0.15s' }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--accent-dim)'}
              onMouseLeave={e => e.currentTarget.style.background = 'var(--surface)'}>
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
          <RoadmapBoard roadmap={spaceRoadmap}
            onChapterClick={(chData) => { setCurrentChapter({ id: chData.id, title: chData.title, data: chData }); setSpacesView('chapter'); }}
            onAddChapter={() => setAddingChapter(true)} onPatchChapters={patchChapters}
            onGenerateChapter={(chId) => { const ch = (spaceRoadmap?.chapters || []).find(c => c.id === chId); if (!ch) return; setPromptBar({ type: 'chapter_generate', chId, title: ch.title, value: '' }); }}
            onEditChapterDesc={(chId) => { const ch = (spaceRoadmap?.chapters || []).find(c => c.id === chId); if (!ch) return; setPromptBar({ type: 'chapter_desc', chId, title: ch.title, value: ch.description || '' }); }} />
        </div>
      </div>

      {activePanel && <PanelHost panel={activePanel} onClose={() => setActivePanel(null)} space={currentSpace} spaceId={sid} spaceRoadmap={spaceRoadmap} refreshHero={loadHero} />}
      {settingsOpen && <SpaceSettingsOverlay space={currentSpace} onClose={() => setSettingsOpen(false)} />}

      {showHistory && (
        <Overlay title="Session History" onClose={() => setShowHistory(false)} width="520px" height="65%">
          {sessions.length === 0 ? <div style={{ color: 'var(--txt3)', fontSize: 13, padding: '32px 0', textAlign: 'center' }}>No sessions yet.</div>
            : <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {sessions.map((s, i) => {
                const goTo = () => {
                  if (!spaceRoadmap?.chapters) return;
                  for (const ch of spaceRoadmap.chapters) {
                    for (const tp of ch.topics || []) {
                      const cn = (tp.concepts || []).find(c => c.title === s.concept);
                      if (cn) { setCurrentChapter({ id: ch.id, title: ch.title, data: ch }); setCurrentTopic({ ...tp, chapterId: ch.id, _openConceptId: cn.id }); setSpacesView('topic'); setShowHistory(false); return; }
                    }
                  }
                };
                return (
                  <div key={i} onClick={goTo} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', borderRadius: 8, cursor: 'pointer', border: '1px solid var(--brd)', background: 'var(--surface)', transition: 'background 0.12s' }}
                    onMouseEnter={e => e.currentTarget.style.background = 'var(--surface2)'}
                    onMouseLeave={e => e.currentTarget.style.background = 'var(--surface)'}>
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
            </div>}
        </Overlay>
      )}
    </div>
  );
}


// ── Chapter View ──────────────────────────────────────────────────────────────
function ChapterView() {
  const { currentSpace, currentChapter, setCurrentChapter, setCurrentTopic, setSpacesView, setSpaceRoadmap, spaceRoadmap, ok, err } = useStore();
  const [noteVal, setNoteVal] = useState('');
  const [noteId, setNoteId] = useState(null);
  const [tab, setTab] = useState('topics');
  const [addingTopic, setAddingTopic] = useState(false);
  const [newTopicTitle, setNewTopicTitle] = useState('');
  const [promptBar, setPromptBar] = useState(null);
  const spaceId = encodeURIComponent(currentSpace?.name || '');
  const noteKey = `notes:${currentSpace?.name}:${currentChapter?.id}`;

  useEffect(() => {
    setNoteVal(localStorage.getItem(noteKey) || ''); setNoteId(null);
    if (!spaceId || !currentChapter?.id) return;
    let cancelled = false;
    api(`/spaces/${spaceId}/notes?type=chapter_note&concept_id=${encodeURIComponent(currentChapter.id)}`)
      .then(r => {
        if (cancelled) return;
        const list = Array.isArray(r) ? r : r.notes || [];
        if (list.length) { setNoteVal(list[0].body_md || ''); setNoteId(list[0].id); }
      }).catch(() => {});
    return () => { cancelled = true; };
  }, [noteKey, spaceId, currentChapter?.id]);

  const getChapter = () => (spaceRoadmap?.chapters || []).find(c => c.id === currentChapter?.id) || currentChapter?.data || {};

  const patchRoadmapChapter = async (updatedChapter) => {
    const chapters = (spaceRoadmap?.chapters || []).map(c => c.id === updatedChapter.id ? updatedChapter : c);
    const withOrder = chapters.map((c, i) => ({ ...c, order: i }));
    try {
      const rm = await api(`/spaces/${spaceId}/roadmap`, { method: 'PATCH', body: JSON.stringify({ chapters: withOrder }) });
      setSpaceRoadmap(rm); setCurrentChapter(prev => ({ ...prev, title: updatedChapter.title, data: updatedChapter }));
    } catch {}
  };

  const addTopic = async () => {
    const title = newTopicTitle.trim(); if (!title) return;
    const ch = getChapter();
    await patchRoadmapChapter({ ...ch, topics: [...(ch.topics || []), { id: `tp_${Date.now().toString(36)}`, title, order: (ch.topics || []).length, concepts: [] }] });
    setNewTopicTitle(''); setAddingTopic(false);
  };

  const generateTopics = async (instruction = '') => {
    const ch = getChapter();
    ok('Generating topics and concepts…');
    try {
      await generateTopicsAndConcepts(spaceId, ch, instruction,
        updatedChapter => patchRoadmapChapter(updatedChapter)
      );
      ok('Topics generated.');
    } catch (e) { err(e.message); }
  };

  const generateConcepts = async (tpId, instruction = '') => {
    try {
      ok("Generating concepts…");
      const ch = getChapter(); const topic = (ch.topics || []).find(t => t.id === tpId); if (!topic) return;
      const r = await api(`/spaces/${spaceId}/roadmap/generate-children`, { method: 'POST', body: JSON.stringify({ parent_type: 'topic', parent_title: topic.title, instruction: instruction.trim() }) });
      const newConcepts = (r.children || []).map((cTitle, i) => ({ id: `cn_${Date.now().toString(36)}_${i}`, title: cTitle, description: '', status: 'not_started', order: (topic.concepts || []).length + i }));
      await patchRoadmapChapter({ ...ch, topics: (ch.topics || []).map(t => t.id !== tpId ? t : { ...t, concepts: [...(t.concepts || []), ...newConcepts] }) });
      ok("Concepts generated.");
    } catch (e) { err(e.message); }
  };

  const saveNotes = async (val) => {
    localStorage.setItem(noteKey, val);
    try {
      if (noteId) { await api(`/spaces/${spaceId}/notes/${noteId}`, { method: 'PUT', body: JSON.stringify({ title: `Chapter: ${currentChapter?.title || ''}`, body_md: val }) }); }
      else { const saved = await api(`/spaces/${spaceId}/notes`, { method: 'POST', body: JSON.stringify({ type: 'chapter_note', concept_id: currentChapter?.id || '', title: `Chapter: ${currentChapter?.title || ''}`, body_md: val }) }); if (saved?.id) setNoteId(saved.id); }
    } catch {}
    ok(`Notes saved (${val.trim().split(/\s+/).filter(Boolean).length}w)`);
  };

  const topics = getChapter().topics || [];
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
        <div className="pg-actions"><button className="btn btn-muted btn-sm" onClick={() => setSpacesView('home')}>Back</button></div>
      </header>
      <div className="chapter-body" style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div className="topic-tab-bar" style={{ padding: '0 24px' }}>
          {['topics', 'notes', 'sessions'].map(t => <button key={t} className={`td-tab${tab === t ? ' active' : ''}`} onClick={() => setTab(t)}>{t.charAt(0).toUpperCase() + t.slice(1)}</button>)}
          {tab === 'topics' && <>
            <button className="btn btn-muted btn-sm" style={{ marginLeft: 'auto' }} onClick={() => setPromptBar({ type: 'topic_generate', value: '' })}>Generate (LLM)</button>
            <button className="btn btn-accent btn-sm" onClick={() => setAddingTopic(true)}>+ Topic</button>
          </>}
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: 24, background: 'var(--surface2)' }}>
          {promptBar?.type === 'topic_generate' && (
            <PromptInline title={`Generate topics for: ${currentChapter.title}`} value={promptBar.value}
              onChange={(v) => setPromptBar(p => ({ ...p, value: v }))}
              onSubmit={async () => { const p = promptBar; setPromptBar(null); await generateTopics(p.value || ''); }}
              onCancel={() => setPromptBar(null)} placeholder="Optional instructions…" submitLabel="Generate" multiline />
          )}
          {promptBar?.type === 'concept_generate' && (
            <PromptInline title={`Generate concepts for: ${promptBar.title}`} value={promptBar.value}
              onChange={(v) => setPromptBar(p => ({ ...p, value: v }))}
              onSubmit={async () => { const p = promptBar; setPromptBar(null); await generateConcepts(p.tpId, p.value || ''); }}
              onCancel={() => setPromptBar(null)} placeholder="Optional instructions…" submitLabel="Generate" multiline />
          )}
          {addingTopic && (
            <div style={{ padding: '16px', marginBottom: 24, background: 'var(--surface)', borderRadius: 8, border: '1px solid var(--brd)', display: 'flex', gap: 6 }}>
              <input className="s-input" style={{ fontSize: 13, padding: '6px 10px', flex: 1 }} autoFocus value={newTopicTitle}
                onChange={e => setNewTopicTitle(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') addTopic(); if (e.key === 'Escape') { setAddingTopic(false); setNewTopicTitle(''); } }}
                placeholder="Topic title…" />
              <button className="btn btn-accent" onClick={addTopic}>Add Topic</button>
              <button className="btn btn-muted" onClick={() => { setAddingTopic(false); setNewTopicTitle(''); }}>Cancel</button>
            </div>
          )}
          {tab === 'topics' && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 24 }}>
              {topics.length === 0
                ? <div style={{ color: 'var(--txt3)', fontSize: 13, gridColumn: '1 / -1' }}>No topics yet.</div>
                : <Reorderable items={topics} itemKey={tp => tp.id} colKey="topics"
                    onReorder={async (ts) => { const ch = getChapter(); await patchRoadmapChapter({ ...ch, topics: ts.map((t, i) => ({ ...t, order: i })) }); }}
                    renderItem={(tp) => <TopicCard topic={tp}
                      onOpen={() => { setCurrentTopic({ ...tp, chapterId: currentChapter.id }); setSpacesView('topic'); }}
                      onDelete={async () => { if (!confirm('Delete topic?')) return; const ch = getChapter(); await patchRoadmapChapter({ ...ch, topics: (ch.topics || []).filter(t => t.id !== tp.id) }); }}
                      onGenerate={() => setPromptBar({ type: 'concept_generate', tpId: tp.id, title: tp.title, value: '' })} />}
                    style={{ display: 'contents' }} />}
            </div>
          )}
          {tab === 'notes' && (
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--surface)', borderRadius: 8, border: '1px solid var(--brd)', overflow: 'hidden' }}>
              <MarkdownEditor value={noteVal} onChange={setNoteVal} onSave={saveNotes} placeholder={`Write chapter notes for ${currentChapter.title}…`} historyKey={noteKey} />
            </div>
          )}
          {tab === 'sessions' && (
            <div style={{ background: 'var(--surface)', borderRadius: 8, padding: 16, border: '1px solid var(--brd)', color: 'var(--txt3)', fontSize: 13 }}>No sessions yet for this chapter.</div>
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
    <div className="topic-card" onClick={onOpen} style={{ background: 'var(--surface)', borderRadius: 14, padding: 24, border: '1px solid var(--brd)', cursor: 'pointer', transition: 'all 0.2s', display: 'flex', flexDirection: 'column', gap: 18, boxShadow: '0 4px 14px rgba(0,0,0,0.08)', minHeight: 200 }}
      onMouseEnter={e => e.currentTarget.style.transform = 'translateY(-2px)'} onMouseLeave={e => e.currentTarget.style.transform = 'none'}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <h3 style={{ margin: 0, fontSize: 18, color: 'var(--txt)', fontWeight: 650, lineHeight: 1.3 }}>{tp.title}</h3>
        <div onClick={e => e.stopPropagation()}>
          <DropdownMenu trigger={<button className="tb-btn" style={{ padding: '2px 6px', color: 'var(--txt3)' }}>⋮</button>}
            items={[{ label: 'Generate Concepts (LLM)', onClick: onGenerate }, { label: 'Delete Topic', danger: true, onClick: onDelete }]} />
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
        <span style={{ fontSize: 11, color: 'var(--txt2)', background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 999, padding: '3px 8px' }}>Tests: {testsTaken}</span>
        <span style={{ fontSize: 11, color: 'var(--txt2)', background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 999, padding: '3px 8px' }}>Coverage: {coveragePct}%</span>
      </div>
      <div style={{ fontSize: 12, color: 'var(--txt2)', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
        {concepts.length === 0 ? <span style={{ color: 'var(--txt3)', fontStyle: 'italic' }}>No concepts yet.</span> : concepts.map(c => c.title).join(' • ')}
      </div>
    </div>
  );
}


// ── Topic View ────────────────────────────────────────────────────────────────
function TopicView() {
  const { currentSpace, currentChapter, currentTopic, setCurrentTopic, setSpaceRoadmap, spaceRoadmap, setSpacesView, ok, err } = useStore();
  const [tab, setTab] = useState('notes');
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
      if (list.length) { setNoteVal(list[0].body_md || ''); setNoteIdMap(m => ({ ...m, [cid]: list[0].id })); }
    } catch {}
  };

  useEffect(() => {
    const openCn = currentTopic?._openConceptId || null;
    setActiveCn(openCn);
    setTab(currentTopic?._openTab || 'notes');
    loadConceptNote(openCn);
    setCnSearch('');
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentTopic?.id, currentTopic?._openConceptId]);

  if (!currentTopic) return null;
  const concepts = currentTopic.concepts || [];
  const sid = encodeURIComponent(currentSpace?.name || '');

  const patchTopic = async (updatedConcepts) => {
    const updatedTopic = { ...currentTopic, concepts: updatedConcepts };
    const liveChapter = (spaceRoadmap?.chapters || []).find(c => c.id === currentChapter.id) || {};
    const updatedChapter = { ...liveChapter, topics: (liveChapter.topics || []).map(t => t.id === currentTopic.id ? updatedTopic : t) };
    const chapters = (spaceRoadmap?.chapters || []).map(c => c.id === updatedChapter.id ? updatedChapter : c);
    try {
      const rm = await api(`/spaces/${sid}/roadmap`, { method: 'PATCH', body: JSON.stringify({ chapters }) });
      setSpaceRoadmap(rm);
      setCurrentTopic(updatedTopic);
    } catch (e) { err(e.message); }
  };

  const saveNotes = async (val) => {
    const cid = activeCn || currentTopic?.id || '';
    const key = noteKey(activeCn);
    localStorage.setItem(key, val);
    try {
      const existingId = noteIdMap[cid];
      const cnTitle = concepts.find(c => c.id === activeCn)?.title || currentTopic?.title || '';
      if (existingId) { await api(`/spaces/${spaceId}/notes/${existingId}`, { method: 'PUT', body: JSON.stringify({ title: `Notes: ${cnTitle}`, body_md: val }) }); }
      else { const saved = await api(`/spaces/${spaceId}/notes`, { method: 'POST', body: JSON.stringify({ type: 'concept_note', concept_id: cid, title: `Notes: ${cnTitle}`, body_md: val }) }); if (saved?.id) setNoteIdMap(m => ({ ...m, [cid]: saved.id })); }
    } catch {}
    ok(`Notes saved (${val.trim().split(/\s+/).filter(Boolean).length}w)`);
  };

  const importConceptDocument = async (file, mode = 'vision') => {
    if (!file) return;
    try {
      const form = new FormData(); form.append('file', file);
      const res = await fetch(`/api/spaces/${spaceId}/notes/import?concept_id=${encodeURIComponent(activeCn)}&ocr_mode=${encodeURIComponent(mode)}`, { method: 'POST', body: form });
      if (!res.ok) { let msg = `HTTP ${res.status}`; try { msg = (await res.json()).detail || msg; } catch {} throw new Error(msg); }
      const data = await res.json().catch(() => ({}));
      const md = (data.markdown || '').trim();
      if (!md) { err("No content extracted."); return; }
      setNoteVal(prev => prev ? `${prev.trim()}\n\n${md}` : md);
      ok("Document converted to markdown.");
    } catch (e) { err(e.message); }
  };

  const markConceptStatus = async (cnId, status) => {
    try { await patchTopic(concepts.map(cn => cn.id === cnId ? { ...cn, status } : cn)); ok(status === 'completed' ? 'Marked complete' : 'Status updated'); } catch {}
  };

  const renameConcept = async (cnId, title) => {
    try { await patchTopic(concepts.map(cn => cn.id === cnId ? { ...cn, title } : cn)); ok('Renamed'); } catch { err('Failed'); }
    setEditingCnId(null);
  };

  const deleteConcept = async (cnId) => {
    if (!confirm('Delete this concept?')) return;
    try { await patchTopic(concepts.filter(cn => cn.id !== cnId)); if (activeCn === cnId) setActiveCn(null); ok('Deleted'); } catch { err('Failed'); }
  };

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
        <div style={{ width: sidebarWidth, flexShrink: 0, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--brd)', background: 'var(--surface)', overflow: 'hidden', position: 'relative' }}>
          <div className="pane-hdr"><span>Concepts</span><span style={{ fontSize: 10.5, color: 'var(--txt3)' }}>{concepts.length}</span></div>
          <div style={{ padding: '6px 8px', borderBottom: '1px solid var(--brd)', flexShrink: 0 }}>
            <input className="s-input" style={{ fontSize: 12, padding: '4px 8px', width: '100%' }} placeholder="Filter concepts…" value={cnSearch} onChange={e => setCnSearch(e.target.value)} />
          </div>
          <div onMouseDown={onSidebarDrag} style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: 5, cursor: 'col-resize', zIndex: 10, background: 'transparent', transition: 'background 150ms' }}
            onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent-border)'; }} onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }} />
          <div style={{ flex: 1, overflowY: 'auto', padding: '8px 6px', display: 'flex', flexDirection: 'column', gap: 3 }}>
            {[{ id: null, title: `All — ${currentTopic.title.slice(0, 16)}` }, ...concepts.filter(cn => !cnSearch.trim() || cn.title.toLowerCase().includes(cnSearch.toLowerCase()))].map(cn => (
              <div key={cn.id ?? '__all__'} style={{ position: 'relative', display: 'flex', alignItems: 'center', borderRadius: 6, background: activeCn === cn.id ? 'var(--accent-dim)' : 'transparent', border: `1px solid ${activeCn === cn.id ? 'var(--accent-border)' : 'transparent'}`, transition: 'background 120ms' }} className="concept-sidebar-row">
                {editingCnId === cn.id
                  ? <input ref={editInputRef} defaultValue={cn.title}
                      onBlur={e => renameConcept(cn.id, e.target.value.trim() || cn.title)}
                      onKeyDown={e => { if (e.key === 'Enter') renameConcept(cn.id, e.target.value.trim() || cn.title); if (e.key === 'Escape') setEditingCnId(null); }}
                      style={{ flex: 1, fontSize: 12.5, padding: '6px 10px', background: 'var(--surface2)', border: '1px solid var(--accent-border)', borderRadius: 5, color: 'var(--txt)', fontFamily: 'var(--font)', outline: 'none' }} onClick={e => e.stopPropagation()} />
                  : <button onClick={() => { setActiveCn(cn.id); loadConceptNote(cn.id); }}
                      style={{ flex: 1, textAlign: 'left', background: 'transparent', border: 'none', padding: '7px 10px', cursor: 'pointer', color: 'var(--txt2)', fontSize: 12.5, fontWeight: cn.id === null ? 600 : 500, fontFamily: 'var(--font)' }}>
                      {cn.title}
                    </button>}
                {cn.id !== null && (
                  <div style={{ flexShrink: 0, paddingRight: 4, display: 'flex', alignItems: 'center', gap: 2 }} onClick={e => e.stopPropagation()}>
                    <button title={concepts.find(c => c.id === cn.id)?.status === 'completed' ? 'Mark in progress' : 'Mark complete'}
                      onClick={() => { const cur = concepts.find(c => c.id === cn.id); markConceptStatus(cn.id, cur?.status === 'completed' ? 'in_progress' : 'completed'); }}
                      style={{ background: 'transparent', border: 'none', cursor: 'pointer', padding: '2px 4px', color: concepts.find(c => c.id === cn.id)?.status === 'completed' ? 'var(--accent)' : 'var(--txt3)', fontSize: 13, lineHeight: 1, borderRadius: 4 }}>
                      {concepts.find(c => c.id === cn.id)?.status === 'completed'
                        ? <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                        : <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9"/></svg>}
                    </button>
                    <DropdownMenu trigger={<button style={{ background: 'transparent', border: 'none', color: 'var(--txt3)', cursor: 'pointer', padding: '2px 5px', fontSize: 13, borderRadius: 4, lineHeight: 1 }}>⋮</button>}
                      items={[{ label: 'Edit title', onClick: () => setEditingCnId(cn.id) }, { label: 'Delete', danger: true, onClick: () => deleteConcept(cn.id) }]} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0 }}>
          <div className="topic-tab-bar">
            {['notes', 'explains', 'quicktest', 'recordings', 'notebook', 'playground'].map(t => (
              <button key={t} className={`td-tab${tab === t ? ' active' : ''}`} onClick={() => setTab(t)}>
                {t === 'recordings' ? 'Record' : t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
            {activeCn && <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--txt3)', fontStyle: 'italic', padding: '0 12px' }}>{concepts.find(c => c.id === activeCn)?.title || ''}</span>}
          </div>
          <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            {tab === 'notes' && (
              !activeCn
                ? <div style={{ flex: 1, padding: 24, overflowY: 'auto' }}>
                    <h2 style={{ margin: '0 0 16px', fontSize: 18, color: 'var(--txt)' }}>Topic Analysis: {currentTopic.title}</h2>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 24 }}>
                      <div style={{ background: 'var(--surface2)', borderRadius: 8, padding: 16, border: '1px solid var(--brd)' }}>
                        <div style={{ fontSize: 12, color: 'var(--accent)', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.05em' }}>Concepts</div>
                        <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--txt)', marginTop: 8 }}>{concepts.length}</div>
                      </div>
                      <div style={{ background: 'var(--surface2)', borderRadius: 8, padding: 16, border: '1px solid var(--brd)' }}>
                        <div style={{ fontSize: 12, color: 'var(--accent)', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.05em' }}>Notes written</div>
                        <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--txt)', marginTop: 8 }}>{noteVal.trim().split(/\s+/).filter(Boolean).length} <span style={{ fontSize: 14, color: 'var(--txt3)', fontWeight: 400 }}>words</span></div>
                      </div>
                    </div>
                    <MarkdownEditor value={noteVal} onChange={setNoteVal} onSave={saveNotes} historyKey={noteKey(activeCn)} placeholder={`Notes for ${currentTopic.title}…`} onUploadDocument={importConceptDocument} spaceId={sid} />
                  </div>
                : <MarkdownEditor value={noteVal} onChange={setNoteVal} onSave={saveNotes} historyKey={noteKey(activeCn)} placeholder={`Notes for ${concepts.find(c => c.id === activeCn)?.title || 'concept'}…`} onUploadDocument={importConceptDocument} spaceId={sid} />
            )}
            {tab === 'explains' && <ExplainsTab spaceId={sid} conceptId={activeCn || currentTopic.id} conceptTitle={activeCn ? (concepts.find(c => c.id === activeCn)?.title || currentTopic.title) : currentTopic.title} />}
            {tab === 'quicktest' && <QuickTestTab spaceId={sid} conceptId={activeCn} topicTitle={currentTopic.title} />}
            {tab === 'recordings' && <MediaRecorderTab spaceId={sid} conceptId={activeCn || currentTopic.id} conceptTitle={activeCn ? (concepts.find(c => c.id === activeCn)?.title || currentTopic.title) : currentTopic.title} />}
            {tab === 'notebook' && <NotebookTab spaceId={sid} conceptId={activeCn || currentTopic.id} conceptTitle={activeCn ? (concepts.find(c => c.id === activeCn)?.title || currentTopic.title) : currentTopic.title} />}
            {tab === 'playground' && <PlaygroundTab spaceId={sid} conceptId={activeCn || currentTopic.id} conceptTitle={activeCn ? (concepts.find(c => c.id === activeCn)?.title || currentTopic.title) : currentTopic.title} />}
          </div>
        </div>
      </div>
    </div>
  );
}
