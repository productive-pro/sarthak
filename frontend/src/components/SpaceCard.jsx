import { useState } from 'react';
import { fmt } from '../utils/format';

// Strip clarifying questions from description/goal text.
// Removes anything that looks like a numbered/bulleted question list.
function stripQuestions(text = '') {
  if (!text) return '';
  const lines = text.split('\n');
  const cleaned = lines.filter(line => {
    const t = line.trim();
    // Drop lines that are numbered/bulleted questions
    if (/^\d+[\.\)]\s+.+\?$/.test(t)) return false;
    if (/^[-*•]\s+.+\?$/.test(t)) return false;
    // Drop lines that start with question words and end with ?
    if (/^(what|how|why|when|where|which|who|do|did|does|are|is|can|could|would|should|will|have|has)\b/i.test(t) && t.endsWith('?')) return false;
    return true;
  });
  return cleaned.join('\n').trim().replace(/\n{3,}/g, '\n\n');
}

// ── Space type → accent colour ──────────────────────────────────────────────
const TYPE_COLORS = {
  data_science:        '#6366f1',
  ai_engineering:      '#8b5cf6',
  software_engineering:'#3b82f6',
  medicine:            '#10b981',
  education:           '#f59e0b',
  exam_prep:           '#ef4444',
  research:            '#06b6d4',
  business:            '#84cc16',
  custom:              '#f472b6',
};
const TYPE_ICONS = {
  data_science: '🧠', ai_engineering: '⚡', software_engineering: '⚙️',
  medicine: '🏥', education: '📚', exam_prep: '🎯',
  research: '🔬', business: '📈', custom: '✨',
};

function typeColor(space) {
  return TYPE_COLORS[space.space_type] || TYPE_COLORS[space.type] || 'var(--accent)';
}
function typeIcon(space) {
  return TYPE_ICONS[space.space_type] || TYPE_ICONS[space.type] || '📂';
}

// ── Mini circular progress ───────────────────────────────────────────────────
function MiniRing({ pct = 0, size = 40, stroke = 3, color = 'var(--accent)' }) {
  const r = (size - stroke * 2) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ - (Math.min(pct, 100) / 100) * circ;
  return (
    <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="var(--brd2)" strokeWidth={stroke} />
        {pct > 0 && (
          <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color}
            strokeWidth={stroke} strokeDasharray={circ.toFixed(2)}
            strokeDashoffset={offset.toFixed(2)} strokeLinecap="round" />
        )}
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
        justifyContent: 'center', fontSize: size < 36 ? 7.5 : 9.5, fontWeight: 700, color }}>
        {Math.round(pct)}%
      </div>
    </div>
  );
}

export default function SpaceCard({
  variant = 'dashboard',
  space,
  profile = null,
  onDrillDown,
  onOpen,
  onClick,
  onToggleActive,
  onSettings,
}) {
  // ── Dashboard variant (compact, used in Dashboard strip) ─────────────────
  if (variant === 'dashboard') {
    const xp       = profile?.xp ?? 0;
    const streak   = profile?.streak_days ?? 0;
    const sessions = profile?.session_count ?? 0;
    const mastered = (profile?.mastered_concepts || []).length;
    const level    = profile?.level ?? '';
    const progress = space.progress || profile?.progress_pct || 0;
    const color    = typeColor(space);
    const icon     = typeIcon(space);
    const desc     = stripQuestions(space.goal || space.description || '');

    return (
      <div
        onClick={onDrillDown}
        style={{
          background: 'var(--surface2)',
          border: '1px solid var(--brd)',
          borderRadius: 10,
          padding: '10px 13px',
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
          cursor: 'pointer',
          transition: 'border-color 0.15s, box-shadow 0.15s',
          position: 'relative',
          overflow: 'hidden',
        }}
        onMouseEnter={e => {
          e.currentTarget.style.borderColor = color + '80';
          e.currentTarget.style.boxShadow = `0 2px 14px rgba(0,0,0,0.22)`;
        }}
        onMouseLeave={e => {
          e.currentTarget.style.borderColor = 'var(--brd)';
          e.currentTarget.style.boxShadow = '';
        }}
      >
        {/* Faint left accent stripe */}
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 3, background: color, borderRadius: '10px 0 0 10px', opacity: 0.7 }} />

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingLeft: 6 }}>
          <span style={{ fontSize: 16 }}>{icon}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--txt)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {space.name || 'Unnamed'}
            </div>
            {desc && (
              <div style={{ fontSize: 10.5, color: 'var(--txt3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginTop: 1 }}>
                {desc.split('\n')[0]}
              </div>
            )}
          </div>
          <MiniRing pct={progress} size={34} stroke={2.5} color={color} />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 5, paddingLeft: 6 }}>
          {[{ val: xp, lbl: 'XP' }, { val: `${streak}d`, lbl: 'Streak' }, { val: mastered, lbl: 'Mastered' }].map(st => (
            <div key={st.lbl} style={{ background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 6, padding: '4px 5px', textAlign: 'center' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color, lineHeight: 1.2 }}>{st.val}</div>
              <div style={{ fontSize: 9, color: 'var(--txt3)', marginTop: 1, textTransform: 'uppercase', letterSpacing: '.04em' }}>{st.lbl}</div>
            </div>
          ))}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingLeft: 6 }}>
          {level && <span style={{ fontSize: 10, color: 'var(--txt3)' }}>{level}{sessions > 0 ? ` · ${sessions}s` : ''}</span>}
          <button className="btn btn-muted btn-xs" style={{ marginLeft: 'auto', fontSize: 10.5, padding: '2px 8px' }}
            onClick={e => { e.stopPropagation(); onOpen && onOpen(); }}>
            Open
          </button>
        </div>
      </div>
    );
  }

  // ── List variant (full card in Spaces list page) ──────────────────────────
  const [hovered, setHovered] = useState(false);
  const progress  = space.progress || 0;
  const isActive  = !!space.is_active;
  const color     = typeColor(space);
  const icon      = typeIcon(space);
  const dirShort  = space.directory?.split('/').slice(-2).join('/') || '';
  const rawDesc   = space.goal || space.description || '';
  const desc      = stripQuestions(rawDesc);
  const firstLine = desc.split('\n').find(l => l.trim()) || '';

  return (
    <div
      className="space-card-v2"
      data-active={isActive}
      style={{ '--card-color': color }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={onClick}
    >
      {/* Top accent bar */}
      <div className="sc2-accent-bar" />

      <div className="sc2-body">
        {/* Header row */}
        <div className="sc2-header">
          <div className="sc2-icon">{icon}</div>
          <div className="sc2-info">
            <div className="sc2-name">
              {space.name || 'Unnamed'}
              {isActive && <span className="sc2-active-pill">ACTIVE</span>}
            </div>
            {dirShort && <div className="sc2-dir">~/{dirShort}</div>}
          </div>
          <MiniRing pct={progress} size={42} stroke={3} color={color} />
        </div>

        {/* Description — single truncated line, expands on hover */}
        {firstLine && (
          <div className={`sc2-desc${hovered ? ' sc2-desc--open' : ''}`}>
            {firstLine}
          </div>
        )}

        {/* Stats row (only shown if space has any data) */}
        {(space.xp || space.streak_days || space.session_count) ? (
          <div className="sc2-stats">
            {space.xp        != null && <span className="sc2-stat"><strong>{space.xp}</strong> XP</span>}
            {space.streak_days != null && <span className="sc2-stat"><strong>{space.streak_days}d</strong> streak</span>}
            {space.session_count != null && <span className="sc2-stat"><strong>{space.session_count}</strong> sessions</span>}
          </div>
        ) : null}

        {/* Footer row */}
        <div className="sc2-foot">
          {space.updated_at && (
            <span className="sc2-date">{fmt(space.updated_at)}</span>
          )}
          <div className="sc2-actions">
            <button
              className="btn btn-muted btn-sm sc2-settings-btn"
              title="Space settings"
              onClick={e => { e.stopPropagation(); onSettings && onSettings(space); }}
            >⚙</button>
            <button
              className={`btn btn-sm ${isActive ? 'btn-muted' : 'sc2-activate-btn'}`}
              style={!isActive ? { background: color + '20', color, border: `1px solid ${color}50` } : {}}
              onClick={e => { e.stopPropagation(); onToggleActive && onToggleActive(space, !isActive); }}
            >
              {isActive ? 'Deactivate' : 'Set Active'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
