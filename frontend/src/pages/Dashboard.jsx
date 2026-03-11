import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { fmtDur } from '../utils/format';
import SpaceCard from '../components/SpaceCard';
import { useStore } from '../store';
import useFetch from '../hooks/useFetch';
import { StatCard, XPBar, ConceptPills, Spinner } from '../components/ui';

export default function Dashboard() {
  const [hours, setHours] = useState(8);
  const [selected, setSelected] = useState(null);
  const { data, loading: loadingData, reload: reloadData } = useFetch(`/dashboard?hours=${hours}`, [hours], { initialData: null });
  const { data: spaces = [], loading: loadingSpaces, reload: reloadSpaces } = useFetch('/spaces', [], { initialData: [] });
  const { data: agents = [], loading: loadingAgents, reload: reloadAgents } = useFetch('/agents', [], { initialData: [] });
  const { data: profilesList = [], reload: reloadProfiles } = useFetch('/spaces/profiles', [], { initialData: [] });

  const profiles = useMemo(() => {
    if (!Array.isArray(profilesList)) return {};
    return Object.fromEntries(profilesList.filter(p => p?.name).map(p => [p.name, p]));
  }, [profilesList]);

  const refresh = () => { reloadData(); reloadSpaces(); reloadAgents(); reloadProfiles(); };

  return (
    <div className="page">
      <header className="pg-header">
        <div className="pg-title-group">
          <h1 className="pg-title">Dashboard</h1>
          <p className="pg-sub">{spaces.length} space{spaces.length !== 1 ? 's' : ''} · learning overview</p>
        </div>
        <div className="pg-actions">
          <select className="s-select" style={{ width: 130 }} value={hours} onChange={e => setHours(+e.target.value)}>
            <option value={3}>Last 3h</option>
            <option value={8}>Last 8h</option>
            <option value={24}>Last 24h</option>
            <option value={72}>Last 3 days</option>
            <option value={168}>Last week</option>
          </select>
          <button className="btn btn-muted btn-sm" onClick={refresh}>Refresh</button>
        </div>
      </header>
      <div className="pg-body">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {(loadingData || loadingSpaces) ? <Spinner /> : data?.active_space
            ? <ActiveSpaceHero space={data.active_space} profile={profiles[data.active_space.name]} />
            : spaces.length > 0 ? <NoActiveSpaceBanner /> : null}
          {!loadingSpaces && <SpacesGrid spaces={spaces} profiles={profiles} onSelect={setSelected} />}
          <ActivitySection data={data} hours={hours} />
          {!loadingAgents && <AgentsStrip agents={agents} />}
        </div>
      </div>
      {selected && (
        <SpaceDrillDown space={selected} profile={profiles[selected.name]} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
// ── Active Space Hero ─────────────────────────────────────────────────────────
function ActiveSpaceHero({ space, profile }) {
  const { setCurrentSpace, setSpaceRoadmap, setSpacesView, setPage } = useStore();
  const xp = profile?.xp ?? space.xp ?? 0;
  const xpNext = profile?.xp_to_next ?? space.xp_to_next ?? 1;
  const streak = profile?.streak_days ?? space.streak_days ?? 0;
  const sessions = profile?.session_count ?? space.session_count ?? 0;
  const level = profile?.level ?? space.level ?? '';
  const domain = profile?.domain ?? space.domain ?? '';
  const mastered = (profile?.mastered_concepts || space.skills || []).slice(-6);
  const struggling = (profile?.struggling_concepts || []).slice(0, 4);
  const badges = (profile?.badges || []).slice(0, 5);

  const goToSpace = () => {
    setCurrentSpace({ name: space.name, directory: space.directory, space_type: space.space_type });
    setSpaceRoadmap(null); setSpacesView('home'); setPage('spaces');
  };

  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--accent-border)', borderRadius: 12, padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--accent)', background: 'var(--accent-dim)', border: '1px solid var(--accent-border)', borderRadius: 4, padding: '2px 7px' }}>Active Space</span>
            {space.space_type && <span style={{ fontSize: 10.5, color: 'var(--txt3)' }}>{space.space_type.replace(/_/g, ' ')}</span>}
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--txt)', lineHeight: 1.2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{space.name}</div>
          {domain && <div style={{ fontSize: 12.5, color: 'var(--txt3)', marginTop: 3 }}>{domain}</div>}
        </div>
        <button className="btn btn-accent btn-sm" style={{ flexShrink: 0 }} onClick={goToSpace}>Open</button>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        {[{ val: `${xp}`, lbl: 'XP' }, { val: level || '—', lbl: 'Level' }, { val: `${streak}d`, lbl: 'Streak' }, { val: `${sessions}`, lbl: 'Sessions' }].map(s => (
          <StatCard key={s.lbl} val={s.val} lbl={s.lbl} />
        ))}
      </div>
      <XPBar xp={xp} xpNext={xpNext} />
      <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
        <ConceptPills concepts={mastered} label="Mastered" type="mastered" />
        <ConceptPills concepts={struggling} label="Needs review" type="struggling" />
        {badges.length > 0 && (
          <div>
            <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.04em' }}>Badges</div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {badges.map(b => <span key={b} className="badge badge-muted" style={{ fontSize: 10.5 }}>{b}</span>)}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function NoActiveSpaceBanner() {
  const { setPage } = useStore();
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 10, padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
      <div>
        <div style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--txt)' }}>No active space</div>
        <div style={{ fontSize: 12, color: 'var(--txt3)', marginTop: 2 }}>Activate a space to track your active learning session here.</div>
      </div>
      <button className="btn btn-accent btn-sm" onClick={() => setPage('spaces')}>Go to Spaces</button>
    </div>
  );
}

// ── Spaces Grid ───────────────────────────────────────────────────────────────
function SpacesGrid({ spaces, profiles, onSelect }) {
  const { setCurrentSpace, setSpaceRoadmap, setSpacesView, setPage } = useStore();
  if (!spaces.length) return (
    <div className="card">
      <div className="card-hdr">Spaces</div>
      <div className="card-body" style={{ color: 'var(--txt3)', fontSize: 13, display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-start' }}>
        <span>No spaces yet.</span>
        <button className="btn btn-accent btn-sm" onClick={() => setPage('spaces')}>Create your first space</button>
      </div>
    </div>
  );
  const openSpace = (s) => { setCurrentSpace(s); setSpaceRoadmap(null); setSpacesView('home'); setPage('spaces'); };
  return (
    <div className="card">
      <div className="card-hdr" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>Spaces</span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'var(--txt3)', fontWeight: 400 }}>{spaces.length} total</span>
          <button className="btn btn-muted btn-xs" onClick={() => setPage('spaces')}>Manage</button>
        </div>
      </div>
      <div className="card-body" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 10 }}>
        {spaces.map(s => (
          <SpaceCard key={s.name || s.directory} variant="dashboard" space={s} profile={profiles[s.name]}
            onDrillDown={() => onSelect(s)} onOpen={() => openSpace(s)} />
        ))}
      </div>
    </div>
  );
}

// ── Space drill-down sheet ────────────────────────────────────────────────────
function SpaceDrillDown({ space, profile: cachedProfile, onClose }) {
  const [profile, setProfile] = useState(cachedProfile || null);
  const [loading, setLoading] = useState(!cachedProfile);
  const { setCurrentSpace, setSpaceRoadmap, setSpacesView, setPage } = useStore();

  useEffect(() => {
    if (cachedProfile) return;
    let alive = true;
    api(`/spaces/${encodeURIComponent(space.name)}/profile`)
      .then(p => { if (alive) { setProfile(p); setLoading(false); } })
      .catch(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [space.name, cachedProfile]);

  const lr = profile;
  const xp = lr?.xp ?? 0;
  const xpNext = lr?.xp_to_next ?? 1;

  const goToSpace = () => {
    setCurrentSpace(space); setSpaceRoadmap(null); setSpacesView('home'); setPage('spaces'); onClose();
  };

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 400, display: 'flex', alignItems: 'flex-end', justifyContent: 'center', background: 'rgba(0,0,0,0.55)' }} onClick={onClose}>
      <div style={{ background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: '14px 14px 0 0', width: '100%', maxWidth: 760, padding: 28, maxHeight: '78vh', overflowY: 'auto' }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 19, fontWeight: 700, color: 'var(--txt)' }}>{space.name}</div>
            {lr?.domain && <div style={{ fontSize: 12, color: 'var(--txt3)', marginTop: 2 }}>{lr.domain}</div>}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-accent btn-sm" onClick={goToSpace}>Open Space</button>
            <button className="btn btn-muted btn-sm" onClick={onClose}>Close</button>
          </div>
        </div>
        {loading ? <Spinner /> : !lr ? (
          <div style={{ color: 'var(--txt3)', fontSize: 13 }}>No profile yet. Initialize this space first.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
              {[{ val: `${lr.xp ?? 0}`, lbl: 'XP' }, { val: lr.level || lr.skill_level || '—', lbl: 'Level' },
                { val: `${lr.streak_days ?? 0}d`, lbl: 'Streak' }, { val: `${lr.session_count ?? lr.total_sessions ?? 0}`, lbl: 'Sessions' }
              ].map(st => <StatCard key={st.lbl} val={st.val} lbl={st.lbl} />)}
            </div>
            <XPBar xp={xp} xpNext={xpNext} />
            {(lr.goal || lr.background) && (
              <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
                {lr.goal && <div style={{ flex: 1, minWidth: 160 }}><div style={{ fontSize: 10.5, color: 'var(--txt3)', marginBottom: 3, textTransform: 'uppercase', letterSpacing: '.04em' }}>Goal</div><div style={{ fontSize: 12.5, color: 'var(--txt2)' }}>{lr.goal}</div></div>}
                {lr.background && <div style={{ flex: 1, minWidth: 160 }}><div style={{ fontSize: 10.5, color: 'var(--txt3)', marginBottom: 3, textTransform: 'uppercase', letterSpacing: '.04em' }}>Background</div><div style={{ fontSize: 12.5, color: 'var(--txt2)' }}>{lr.background}</div></div>}
              </div>
            )}
            <ConceptPills concepts={(lr.mastered_concepts || []).slice(-15)} label={`Mastered concepts (${lr.mastered_count ?? (lr.mastered_concepts || []).length})`} type="mastered" />
            <ConceptPills concepts={lr.struggling_concepts} label="Needs review" type="struggling" />
            {(lr.badges || []).length > 0 && (
              <div>
                <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '.04em' }}>Badges</div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {lr.badges.map(b => <span key={b} className="badge badge-muted" style={{ fontSize: 11 }}>{b}</span>)}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Activity Section ──────────────────────────────────────────────────────────
function ActivitySection({ data: d, hours }) {
  if (!d) return null;
  return (
    <div className="card">
      <div className="card-hdr" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>Learning Activity</span>
        {!d.aw_available && <span style={{ fontSize: 11, color: 'var(--txt3)' }}>ActivityWatch not running — start <code style={{ background: 'var(--surface2)', padding: '1px 5px', borderRadius: 3 }}>aw-server</code></span>}
        {d.is_afk && <span style={{ fontSize: 11, color: 'var(--amber)' }}>AFK</span>}
      </div>
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 10 }}>
          {[{ label: 'Tracked', val: d.total_minutes ? fmtDur(d.total_minutes) : '—' },
            { label: 'Focus time', val: d.focus_minutes ? fmtDur(d.focus_minutes) : '—' },
            { label: 'Learning time', val: d.learning_minutes ? fmtDur(d.learning_minutes) : '—' },
            { label: 'Focus score', val: d.aw_available ? `${d.focus_score ?? 0}%` : '—' },
          ].map(s => <StatCard key={s.label} val={s.val} lbl={s.label} />)}
        </div>
        {d.aw_available && d.focus_minutes > 0 && (
          <FocusSplit learningMin={d.learning_minutes} focusMin={d.focus_minutes} totalMin={d.total_minutes} />
        )}
        {(d.top_apps || []).length > 0 && <AppTimeList apps={d.top_apps} hours={hours} />}
      </div>
    </div>
  );
}

function FocusSplit({ learningMin, focusMin, totalMin }) {
  const segments = [
    { label: 'Learning', min: learningMin, color: 'var(--accent)' },
    { label: 'Other', min: Math.max(0, focusMin - learningMin), color: 'var(--accent-dim)' },
    { label: 'Idle', min: Math.max(0, totalMin - focusMin), color: 'var(--brd2)' },
  ].filter(s => s.min > 0);
  const total = segments.reduce((s, x) => s + x.min, 0) || 1;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', height: 7, borderRadius: 4, overflow: 'hidden', gap: 1 }}>
        {segments.map(s => <div key={s.label} style={{ flex: s.min / total, background: s.color, minWidth: 2 }} title={`${s.label}: ${fmtDur(s.min)}`} />)}
      </div>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        {segments.map(s => (
          <div key={s.label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div style={{ width: 8, height: 8, borderRadius: 2, background: s.color, flexShrink: 0 }} />
            <span style={{ fontSize: 11.5, color: 'var(--txt2)' }}>{s.label}</span>
            <span style={{ fontSize: 11.5, color: 'var(--txt3)' }}>{fmtDur(s.min)}</span>
            <span style={{ fontSize: 10.5, color: 'var(--txt3)' }}>({Math.round(s.min / total * 100)}%)</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AppTimeList({ apps, hours }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? apps : apps.slice(0, 6);
  const maxDur = Math.max(...apps.map(a => a.duration || 0), 1);
  const totalSec = apps.reduce((s, a) => s + (a.duration || 0), 0);
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--txt3)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '.04em' }}>App time — last {hours}h</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
        {visible.map((a, i) => {
          const durMin = Math.round(a.duration / 60);
          const pct = Math.round((a.duration / maxDur) * 100);
          const share = totalSec > 0 ? Math.round(a.duration / totalSec * 100) : 0;
          return (
            <div key={i} className="app-bar-row">
              <span className="app-bar-label" style={{ color: a.is_learning ? 'var(--accent)' : 'var(--txt2)' }}>{a.app}</span>
              <div className="app-bar-track"><div className="app-bar-fill" style={{ width: `${pct}%`, background: a.is_learning ? 'var(--accent)' : 'var(--accent-dim)' }} /></div>
              <span className="app-bar-val">{durMin > 0 ? fmtDur(durMin) : '<1m'}</span>
              <span style={{ fontSize: 10, color: 'var(--txt3)', minWidth: 28, textAlign: 'right' }}>{share}%</span>
            </div>
          );
        })}
      </div>
      {apps.length > 6 && <button className="tb-btn" style={{ marginTop: 8, fontSize: 11.5, color: 'var(--txt3)' }} onClick={() => setExpanded(v => !v)}>{expanded ? 'Show less' : `+${apps.length - 6} more apps`}</button>}
    </div>
  );
}

function AgentsStrip({ agents }) {
  const { setPage } = useStore();
  if (!agents.length) return null;
  const active = agents.filter(a => a.enabled).length;
  return (
    <div className="card">
      <div className="card-hdr" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span>Agents</span>
          <span style={{ fontSize: 10.5, color: active > 0 ? 'var(--accent)' : 'var(--txt3)' }}>{active} active</span>
        </div>
        <button className="btn btn-muted btn-xs" onClick={() => setPage('agents')}>Manage</button>
      </div>
      <div className="card-body" style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {agents.slice(0, 8).map(a => (
          <div key={a.agent_id} style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 6, padding: '5px 10px' }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: a.enabled ? 'var(--accent)' : 'var(--brd2)', flexShrink: 0 }} />
            <span style={{ fontSize: 12, color: 'var(--txt2)' }}>{a.name || `Agent ${(a.agent_id || '').slice(0, 6)}`}</span>
            {a.schedule && <code style={{ fontSize: 10, color: 'var(--txt3)', background: 'var(--surface3)', padding: '1px 4px', borderRadius: 3 }}>{a.schedule}</code>}
          </div>
        ))}
        {agents.length > 8 && <span style={{ fontSize: 11, color: 'var(--txt3)', alignSelf: 'center' }}>+{agents.length - 8} more</span>}
      </div>
    </div>
  );
}
