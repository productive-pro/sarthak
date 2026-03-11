/**
 * ui.jsx — shared primitive components used across pages.
 * Import from here instead of duplicating inline.
 */

/** Stat card: large value + small label */
export function StatCard({ val, lbl, color = 'var(--accent)', style }) {
  return (
    <div className="stat-card" style={style}>
      <div className="stat-val" style={color !== 'var(--accent)' ? { color } : undefined}>{val}</div>
      <div className="stat-lbl">{lbl}</div>
    </div>
  );
}

/** Horizontal XP progress bar */
export function XPBar({ xp, xpNext }) {
  const pct = xpNext > 0 ? Math.min(100, Math.round(xp / (xp + xpNext) * 100)) : 100;
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, color: 'var(--txt3)', marginBottom: 5 }}>
        <span>{xp} XP</span>
        <span>{xpNext} to next level</span>
      </div>
      <div style={{ height: 5, background: 'var(--brd2)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: 'var(--accent)', borderRadius: 3, transition: 'width 0.5s' }} />
      </div>
    </div>
  );
}

/** Pill badge for concepts (mastered / struggling) */
export function ConceptPill({ label, type = 'mastered' }) {
  const styles = {
    mastered:   { bg: 'rgba(74,222,128,0.09)',  color: 'var(--accent)', border: '1px solid rgba(74,222,128,0.2)' },
    struggling: { bg: 'rgba(248,113,113,0.09)', color: '#f87171',       border: '1px solid rgba(248,113,113,0.2)' },
  };
  const s = styles[type] || styles.mastered;
  return (
    <span style={{ fontSize: 10.5, background: s.bg, color: s.color, border: s.border, borderRadius: 4, padding: '2px 7px' }}>
      {label}
    </span>
  );
}

/** Labeled concept pills section */
export function ConceptPills({ concepts, label, type }) {
  if (!concepts?.length) return null;
  return (
    <div>
      <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.04em' }}>{label}</div>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {concepts.map(c => <ConceptPill key={c} label={c} type={type} />)}
      </div>
    </div>
  );
}

/** Loading spinner centered */
export function Spinner() {
  return <div className="loading-center"><span className="spin" /></div>;
}

/** Empty state */
export function Empty({ icon = '—', title, desc, action }) {
  return (
    <div className="empty">
      {icon && <div style={{ fontSize: 28, marginBottom: 8 }}>{icon}</div>}
      <div className="empty-ttl">{title}</div>
      {desc && <div className="empty-desc">{desc}</div>}
      {action}
    </div>
  );
}
