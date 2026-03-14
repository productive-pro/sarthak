import { useState } from 'react';
import { fmt } from '../utils/format';
import { typeColor, typeAbbr } from '../pages/spaces/shared';

// Strip clarifying questions from description/goal text.
function stripQuestions(text = '') {
  if (!text) return '';
  return text.split('\n').filter(line => {
    const t = line.trim();
    if (/^\d+[\.\)]\s+.+\?$/.test(t)) return false;
    if (/^[-*•]\s+.+\?$/.test(t)) return false;
    if (/^(what|how|why|when|where|which|who|do|did|does|are|is|can|could|would|should|will|have|has)\b/i.test(t) && t.endsWith('?')) return false;
    return true;
  }).join('\n').trim().replace(/\n{3,}/g, '\n\n');
}

// ── Mini circular progress ring ───────────────────────────────────────────────
function MiniRing({ pct = 0, size = 40, stroke = 3, color = 'var(--accent)' }) {
  const r = (size - stroke * 2) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ - (Math.min(pct, 100) / 100) * circ;
  return (
    <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}
        style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--brd2)" strokeWidth={stroke} />
        {pct > 0 && (
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color}
            strokeWidth={stroke} strokeDasharray={circ.toFixed(2)}
            strokeDashoffset={offset.toFixed(2)} strokeLinecap="round" />
        )}
      </svg>
      <div style={{
        position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
        justifyContent: 'center', fontSize: size < 36 ? 7.5 : 9.5, fontWeight: 700, color,
      }}>
        {Math.round(pct)}%
      </div>
    </div>
  );
}

// ── TypeBadge — colored text abbreviation instead of emoji ───────────────────
function TypeBadge({ space, size = 28 }) {
  const color = typeColor(space);
  const abbr  = typeAbbr(space);
  return (
    <div style={{
      width: size, height: size, borderRadius: Math.round(size * 0.28),
      background: `${color}22`, border: `1px solid ${color}55`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: size < 30 ? 9 : 10.5, fontWeight: 700, color,
      fontFamily: 'var(--mono)', letterSpacing: '.04em', flexShrink: 0,
    }}>
      {abbr}
    </div>
  );
}

export default function SpaceCard({
  variant = 'dashboard', space, profile = null,
  onDrillDown, onOpen, onClick, onToggleActive, onSettings,
}) {

  // ── Dashboard variant (compact strip card) ────────────────────────────────
  if (variant === 'dashboard') {
    const xp       = profile?.xp ?? 0;
    const streak   = profile?.streak_days ?? 0;
    const mastered = (profile?.mastered_concepts || []).length;
    const level    = profile?.level ?? '';
    const sessions = profile?.session_count ?? 0;
    const progress = space.progress || profile?.progress_pct || 0;
    const color    = typeColor(space);
    const desc     = stripQuestions(space.goal || space.description || '');

    return (
      <div className="lift" onClick={onDrillDown}
        style={{ background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 10, padding: '10px 13px', display: 'flex', flexDirection: 'column', gap: 8, cursor: 'pointer', position: 'relative', overflow: 'hidden' }}>
        {/* Left accent stripe */}
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 3, background: color, borderRadius: '10px 0 0 10px', opacity: .75 }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingLeft: 6 }}>
          <TypeBadge space={space} size={28} />
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
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 4, paddingLeft: 6 }}>
          {[{ val: xp, lbl: 'XP' }, { val: `${streak}d`, lbl: 'Streak' }, { val: mastered, lbl: 'Done' }].map(st => (
            <div key={st.lbl} style={{ background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 6, padding: '4px 5px', textAlign: 'center' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color, lineHeight: 1.2 }}>{st.val}</div>
              <div style={{ fontSize: 9, color: 'var(--txt3)', marginTop: 1, textTransform: 'uppercase', letterSpacing: '.04em' }}>{st.lbl}</div>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingLeft: 6 }}>
          {level && <span style={{ fontSize: 10, color: 'var(--txt3)' }}>{level}{sessions > 0 ? ` · ${sessions}s` : ''}</span>}
          <button className="btn btn-muted btn-xs" style={{ marginLeft: 'auto', fontSize: 10.5, padding: '2px 8px' }}
            onClick={e => { e.stopPropagation(); onOpen?.(); }}>
            Open
          </button>
        </div>
      </div>
    );
  }

  // ── List variant (full card in Spaces list page) ──────────────────────────
  const [hovered, setHovered] = useState(false);
  const progress = space.progress || 0;
  const isActive = !!space.is_active;
  const color    = typeColor(space);
  const dirShort = space.directory?.split('/').slice(-2).join('/') || '';
  const desc     = stripQuestions(space.goal || space.description || '');
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
      <div className="sc2-accent-bar" />
      <div className="sc2-body">
        <div className="sc2-header">
          <TypeBadge space={space} size={36} />
          <div className="sc2-info">
            <div className="sc2-name">
              {space.name || 'Unnamed'}
              {isActive && <span className="sc2-active-pill">ACTIVE</span>}
            </div>
            {dirShort && <div className="sc2-dir">~/{dirShort}</div>}
          </div>
          <MiniRing pct={progress} size={42} stroke={3} color={color} />
        </div>

        {firstLine && (
          <div className={`sc2-desc${hovered ? ' sc2-desc--open' : ''}`}>{firstLine}</div>
        )}

        {(space.xp || space.streak_days || space.session_count) ? (
          <div className="sc2-stats">
            {space.xp         != null && <span className="sc2-stat"><strong>{space.xp}</strong> XP</span>}
            {space.streak_days != null && <span className="sc2-stat"><strong>{space.streak_days}d</strong> streak</span>}
            {space.session_count != null && <span className="sc2-stat"><strong>{space.session_count}</strong> sessions</span>}
          </div>
        ) : null}

        <div className="sc2-foot">
          {space.updated_at && <span className="sc2-date">{fmt(space.updated_at)}</span>}
          <div className="sc2-actions">
            <button className="btn btn-muted btn-sm sc2-settings-btn" title="Space settings"
              onClick={e => { e.stopPropagation(); onSettings?.(space); }}>
              Settings
            </button>
            <button
              className={`btn btn-sm${isActive ? ' btn-muted' : ' sc2-activate-btn'}`}
              style={!isActive ? { background: `${color}20`, color, border: `1px solid ${color}50` } : {}}
              onClick={e => { e.stopPropagation(); onToggleActive?.(space, !isActive); }}>
              {isActive ? 'Deactivate' : 'Set Active'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
