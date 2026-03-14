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
      <div style={{ display:'flex', justifyContent:'space-between', fontSize:10.5, color:'var(--txt3)', marginBottom:5 }}>
        <span>{xp} XP</span>
        <span>{xpNext} to next level</span>
      </div>
      <div className="prog">
        <div className="prog-fill" style={{ width:`${pct}%` }} />
      </div>
    </div>
  );
}

/** Single concept pill badge */
export function ConceptPill({ label, type = 'mastered' }) {
  const styles = {
    mastered:   { bg:'rgba(74,222,128,0.09)',  color:'var(--accent)',  border:'1px solid rgba(74,222,128,0.2)' },
    struggling: { bg:'rgba(248,113,113,0.09)', color:'#f87171',        border:'1px solid rgba(248,113,113,0.2)' },
  };
  const s = styles[type] || styles.mastered;
  return (
    <span style={{ fontSize:10.5, background:s.bg, color:s.color, border:s.border, borderRadius:4, padding:'2px 7px' }}>
      {label}
    </span>
  );
}

/** Labeled group of concept pills */
export function ConceptPills({ concepts, label, type }) {
  if (!concepts?.length) return null;
  return (
    <div>
      <div style={{ fontSize:10.5, color:'var(--txt3)', marginBottom:5, textTransform:'uppercase', letterSpacing:'.04em' }}>{label}</div>
      <div style={{ display:'flex', gap:4, flexWrap:'wrap' }}>
        {concepts.map(c => <ConceptPill key={c} label={c} type={type} />)}
      </div>
    </div>
  );
}

/** Centered loading spinner */
export function Spinner() {
  return <div className="loading-center"><span className="spin" /></div>;
}

/** Centered empty state with optional CTA */
export function Empty({ icon = '—', title, desc, action }) {
  return (
    <div className="empty">
      {icon && <div style={{ fontSize:28, marginBottom:8 }}>{icon}</div>}
      {title && <div className="empty-title">{title}</div>}
      {desc  && <div className="empty-desc">{desc}</div>}
      {action}
    </div>
  );
}

/** Card section: header label + children body */
export function Section({ title, right, children, style }) {
  return (
    <div className="card" style={style}>
      <div className="card-hdr">
        <span>{title}</span>
        {right && <div className="card-hdr-right">{right}</div>}
      </div>
      <div className="card-body">{children}</div>
    </div>
  );
}

/** Agent status pill (used in dashboard strip + agents page) */
export function AgentPill({ agent }) {
  return (
    <div className="agent-pill">
      <span className="agent-pill-dot" style={{ background: agent.enabled ? 'var(--accent)' : 'var(--brd2)' }} />
      <span className="agent-pill-name">{agent.name || `Agent ${(agent.agent_id || '').slice(0, 6)}`}</span>
      {agent.schedule && <code className="agent-pill-cron">{agent.schedule}</code>}
    </div>
  );
}

/** Small inline tag/badge */
export function Tag({ label, color = 'var(--txt3)', bg = 'var(--surface2)' }) {
  return (
    <span style={{ fontSize:10.5, padding:'2px 7px', borderRadius:4, background:bg, color, border:`1px solid ${color}44`, display:'inline-block', whiteSpace:'nowrap' }}>
      {label}
    </span>
  );
}

/** Generic progress bar (height and color configurable) */
export function Progress({ value = 0, max = 100, height = 3, color = 'var(--accent)', style }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="prog" style={{ height, ...style }}>
      <div className="prog-fill" style={{ width:`${pct}%`, background:color }} />
    </div>
  );
}

/** Horizontal row of labelled metadata items */
export function MetaRow({ items }) {
  return (
    <div className="meta-row">
      {items.filter(Boolean).map((item, i) => (
        <div key={i} className="meta-field">
          <div className="meta-label">{item.label}</div>
          <div className="meta-value">{item.value}</div>
        </div>
      ))}
    </div>
  );
}
