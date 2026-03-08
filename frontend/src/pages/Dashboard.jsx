import { useState, useEffect } from 'react';
import { api, fmt, fmtDur } from '../api';
import { useStore } from '../store';

export default function Dashboard() {
  const [data, setData]         = useState(null);
  const [spaces, setSpaces]     = useState([]);
  const [profiles, setProfiles] = useState({});  // name -> profile
  const [agents, setAgents]     = useState([]);
  const [hours, setHours]       = useState(8);
  const [loading, setLoading]   = useState(false);
  const [selected, setSelected] = useState(null);
  const { err } = useStore();

  useEffect(() => { load(); }, [hours]);

  const load = async () => {
    setLoading(true);
    const [d, sp, ag] = await Promise.allSettled([
      api(`/dashboard?hours=${hours}`),
      api('/spaces'),
      api('/agents'),
    ]);
    const spaceList = sp.status === 'fulfilled' && Array.isArray(sp.value) ? sp.value : [];
    if (d.status === 'fulfilled') setData(d.value);
    else err(d.reason?.message);
    setSpaces(spaceList);
    setAgents(ag.status === 'fulfilled' && Array.isArray(ag.value) ? ag.value : []);

    // Fetch profiles for all spaces in parallel
    const profileEntries = await Promise.allSettled(
      spaceList.map(s =>
        api(`/spaces/${encodeURIComponent(s.name)}/profile`)
          .then(p => [s.name, p])
          .catch(() => [s.name, null])
      )
    );
    const profileMap = {};
    profileEntries.forEach(r => {
      if (r.status === 'fulfilled' && r.value) profileMap[r.value[0]] = r.value[1];
    });
    setProfiles(profileMap);
    setLoading(false);
  };

  const activeSpace = data?.active_space;

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
          <button className="btn btn-muted btn-sm" onClick={load}>Refresh</button>
        </div>
      </header>

      <div className="pg-body">
        {loading ? (
          <div className="loading-center"><span className="spin" /></div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

            {/* ── Active Space Hero ─────────────────────────────────── */}
            {activeSpace ? (
              <ActiveSpaceHero space={activeSpace} profile={profiles[activeSpace.name]} />
            ) : spaces.length > 0 ? (
              <NoActiveSpaceBanner />
            ) : null}

            {/* ── All Spaces Grid ───────────────────────────────────── */}
            <SpacesGrid spaces={spaces} profiles={profiles} onSelect={setSelected} />

            {/* ── AW Learning Activity ──────────────────────────────── */}
            <ActivitySection data={data} hours={hours} />

            {/* ── Agents strip ──────────────────────────────────────── */}
            <AgentsStrip agents={agents} />
          </div>
        )}
      </div>

      {selected && (
        <SpaceDrillDown
          space={selected}
          profile={profiles[selected.name]}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}

// ── Active Space Hero ─────────────────────────────────────────────────────────

function ActiveSpaceHero({ space, profile }) {
  const { setCurrentSpace, setSpaceRoadmap, setSpacesView } = useStore();

  const xp      = profile?.xp ?? space.xp ?? 0;
  const xpNext  = profile?.xp_to_next ?? space.xp_to_next ?? 1;
  const pct     = xpNext > 0 ? Math.min(100, Math.round(xp / (xp + xpNext) * 100)) : 100;
  const streak  = profile?.streak_days ?? space.streak_days ?? 0;
  const sessions = profile?.session_count ?? space.session_count ?? 0;
  const level   = profile?.level ?? space.level ?? '';
  const domain  = profile?.domain ?? space.domain ?? '';
  const mastered = (profile?.mastered_concepts || space.skills || []).slice(-6);
  const struggling = (profile?.struggling_concepts || []).slice(0, 4);
  const badges  = (profile?.badges || []).slice(0, 5);

  const goToSpace = () => {
    setCurrentSpace({ name: space.name, directory: space.directory, space_type: space.space_type });
    setSpaceRoadmap(null);
    setSpacesView('home');
    useStore.getState().setPage('spaces');
  };

  return (
    <div style={{
      background: 'var(--surface)',
      border: '1px solid var(--accent-border)',
      borderRadius: 12,
      padding: '20px 24px',
      display: 'flex',
      flexDirection: 'column',
      gap: 16,
    }}>
      {/* top row */}
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

      {/* stats row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        {[
          { val: `${xp}`, lbl: 'XP' },
          { val: level || '—', lbl: 'Level' },
          { val: `${streak}d`, lbl: 'Streak' },
          { val: `${sessions}`, lbl: 'Sessions' },
        ].map(s => (
          <div key={s.lbl} style={{ background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 8, padding: '10px 12px', textAlign: 'center' }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--accent)', lineHeight: 1.2 }}>{s.val}</div>
            <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginTop: 2, textTransform: 'uppercase', letterSpacing: '.04em' }}>{s.lbl}</div>
          </div>
        ))}
      </div>

      {/* XP bar */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, color: 'var(--txt3)', marginBottom: 5 }}>
          <span>{xp} XP</span>
          <span>{xpNext} to next level</span>
        </div>
        <div style={{ height: 5, background: 'var(--brd2)', borderRadius: 3, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: 'var(--accent)', borderRadius: 3, transition: 'width 0.5s' }} />
        </div>
      </div>

      {/* concepts / badges */}
      <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
        {mastered.length > 0 && (
          <div style={{ flex: 1, minWidth: 160 }}>
            <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.04em' }}>Mastered</div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {mastered.map(c => (
                <span key={c} style={{ fontSize: 10.5, background: 'rgba(74,222,128,0.09)', color: 'var(--accent)', border: '1px solid rgba(74,222,128,0.2)', borderRadius: 4, padding: '2px 7px' }}>{c}</span>
              ))}
            </div>
          </div>
        )}
        {struggling.length > 0 && (
          <div style={{ flex: 1, minWidth: 160 }}>
            <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.04em' }}>Needs review</div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {struggling.map(c => (
                <span key={c} style={{ fontSize: 10.5, background: 'rgba(248,113,113,0.09)', color: '#f87171', border: '1px solid rgba(248,113,113,0.2)', borderRadius: 4, padding: '2px 7px' }}>{c}</span>
              ))}
            </div>
          </div>
        )}
        {badges.length > 0 && (
          <div>
            <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.04em' }}>Badges</div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {badges.map(b => (
                <span key={b} className="badge badge-muted" style={{ fontSize: 10.5 }}>{b}</span>
              ))}
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
          <SpaceCard
            key={s.name || s.directory}
            space={s}
            profile={profiles[s.name]}
            onDrillDown={() => onSelect(s)}
            onOpen={() => {
              setCurrentSpace(s);
              setSpaceRoadmap(null);
              setSpacesView('home');
              setPage('spaces');
            }}
          />
        ))}
      </div>
    </div>
  );
}

function SpaceCard({ space: s, profile, onDrillDown, onOpen }) {
  const xp      = profile?.xp ?? 0;
  const streak  = profile?.streak_days ?? 0;
  const sessions = profile?.session_count ?? 0;
  const mastered = (profile?.mastered_concepts || []).length;
  const level   = profile?.level ?? '';
  const progress = s.progress || profile?.progress_pct || 0;
  const circ = 2 * Math.PI * 13;
  const offset = circ - (progress / 100) * circ;

  return (
    <div
      style={{
        background: 'var(--surface2)',
        border: '1px solid var(--brd)',
        borderRadius: 9,
        padding: '12px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        cursor: 'pointer',
        transition: 'border-color 0.15s, box-shadow 0.15s',
      }}
      onClick={onDrillDown}
      onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent-border)'; e.currentTarget.style.boxShadow = '0 2px 12px rgba(0,0,0,0.18)'; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--brd)'; e.currentTarget.style.boxShadow = ''; }}
    >
      {/* Name row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 650, color: 'var(--txt)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name || 'Unnamed'}</div>
          <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginTop: 2 }}>{(s.space_type || s.type || 'custom').replace(/_/g, ' ')}</div>
        </div>
        {/* progress ring */}
        <div style={{ position: 'relative', width: 30, height: 30, flexShrink: 0 }}>
          <svg width="30" height="30" viewBox="0 0 30 30">
            <circle cx="15" cy="15" r="13" fill="none" stroke="var(--brd2)" strokeWidth="2.5" />
            <circle cx="15" cy="15" r="13" fill="none" stroke="var(--accent)" strokeWidth="2.5"
              strokeDasharray={circ.toFixed(2)} strokeDashoffset={offset.toFixed(2)}
              strokeLinecap="round" style={{ transform: 'rotate(-90deg)', transformOrigin: 'center' }} />
          </svg>
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 7, fontWeight: 700, color: 'var(--accent)' }}>
            {progress}%
          </div>
        </div>
      </div>

      {/* Mini stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 5 }}>
        {[
          { val: xp, lbl: 'XP' },
          { val: `${streak}d`, lbl: 'Streak' },
          { val: mastered, lbl: 'Mastered' },
        ].map(st => (
          <div key={st.lbl} style={{ background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 5, padding: '5px 6px', textAlign: 'center' }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent)', lineHeight: 1.2 }}>{st.val}</div>
            <div style={{ fontSize: 9.5, color: 'var(--txt3)', marginTop: 1, textTransform: 'uppercase', letterSpacing: '.04em' }}>{st.lbl}</div>
          </div>
        ))}
      </div>

      {/* Footer */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        {level && <span style={{ fontSize: 10.5, color: 'var(--txt3)' }}>{level}{sessions > 0 ? ` · ${sessions} sessions` : ''}</span>}
        {s.updated_at && <span style={{ fontSize: 10, color: 'var(--txt3)' }}>{fmt(s.updated_at)}</span>}
        <button
          className="btn btn-muted btn-xs"
          style={{ marginLeft: 'auto' }}
          onClick={e => { e.stopPropagation(); onOpen(); }}
        >Open</button>
      </div>
    </div>
  );
}

// ── Space drill-down modal ────────────────────────────────────────────────────

function SpaceDrillDown({ space, profile: cachedProfile, onClose }) {
  const [profile, setProfile] = useState(cachedProfile || null);
  const [loading, setLoading] = useState(!cachedProfile);
  const { setCurrentSpace, setSpaceRoadmap, setSpacesView, setPage } = useStore();

  useEffect(() => {
    if (cachedProfile) return;
    let mounted = true;
    setLoading(true);
    api(`/spaces/${encodeURIComponent(space.name)}/profile`)
      .then(p => { if (mounted) { setProfile(p); setLoading(false); } })
      .catch(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [space.name, cachedProfile]);

  const lr = profile;
  const xp = lr?.xp ?? 0;
  const xpNext = lr?.xp_to_next ?? 1;
  const pct = xpNext > 0 ? Math.min(100, Math.round(xp / (xp + xpNext) * 100)) : 100;

  const goToSpace = () => {
    setCurrentSpace(space);
    setSpaceRoadmap(null);
    setSpacesView('home');
    setPage('spaces');
    onClose();
  };

  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 400, display: 'flex', alignItems: 'flex-end', justifyContent: 'center', background: 'rgba(0,0,0,0.55)' }}
      onClick={onClose}
    >
      <div
        style={{ background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: '14px 14px 0 0', width: '100%', maxWidth: 760, padding: 28, maxHeight: '78vh', overflowY: 'auto' }}
        onClick={e => e.stopPropagation()}
      >
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

        {loading ? (
          <div className="loading-center"><span className="spin" /></div>
        ) : !lr ? (
          <div style={{ color: 'var(--txt3)', fontSize: 13 }}>No profile yet. Initialize this space first.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
              {[
                { val: `${lr.xp ?? 0}`, lbl: 'XP' },
                { val: lr.level || lr.skill_level || '—', lbl: 'Level' },
                { val: `${lr.streak_days ?? 0}d`, lbl: 'Streak' },
                { val: `${lr.session_count ?? lr.total_sessions ?? 0}`, lbl: 'Sessions' },
              ].map(st => (
                <div key={st.lbl} className="stat-card">
                  <div className="stat-val">{st.val}</div>
                  <div className="stat-lbl">{st.lbl}</div>
                </div>
              ))}
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, color: 'var(--txt3)', marginBottom: 5 }}>
                <span>{xp} XP earned</span>
                <span>{xpNext} to next level</span>
              </div>
              <div style={{ height: 5, background: 'var(--brd2)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${pct}%`, background: 'var(--accent)', borderRadius: 3, transition: 'width 0.4s' }} />
              </div>
            </div>

            {(lr.goal || lr.background) && (
              <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
                {lr.goal && (
                  <div style={{ flex: 1, minWidth: 160 }}>
                    <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginBottom: 3, textTransform: 'uppercase', letterSpacing: '.04em' }}>Goal</div>
                    <div style={{ fontSize: 12.5, color: 'var(--txt2)' }}>{lr.goal}</div>
                  </div>
                )}
                {lr.background && (
                  <div style={{ flex: 1, minWidth: 160 }}>
                    <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginBottom: 3, textTransform: 'uppercase', letterSpacing: '.04em' }}>Background</div>
                    <div style={{ fontSize: 12.5, color: 'var(--txt2)' }}>{lr.background}</div>
                  </div>
                )}
              </div>
            )}

            {(lr.mastered_concepts || []).length > 0 && (
              <div>
                <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '.04em' }}>
                  Mastered concepts ({lr.mastered_count ?? lr.mastered_concepts.length})
                </div>
                <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                  {(lr.mastered_concepts || []).slice(-15).map(c => (
                    <span key={c} style={{ fontSize: 10.5, background: 'rgba(74,222,128,0.09)', color: 'var(--accent)', border: '1px solid rgba(74,222,128,0.2)', borderRadius: 4, padding: '2px 7px' }}>{c}</span>
                  ))}
                </div>
              </div>
            )}

            {(lr.struggling_concepts || []).length > 0 && (
              <div>
                <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '.04em' }}>Needs review</div>
                <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                  {lr.struggling_concepts.map(c => (
                    <span key={c} style={{ fontSize: 10.5, background: 'rgba(248,113,113,0.09)', color: '#f87171', border: '1px solid rgba(248,113,113,0.2)', borderRadius: 4, padding: '2px 7px' }}>{c}</span>
                  ))}
                </div>
              </div>
            )}

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
        {!d.aw_available && (
          <span style={{ fontSize: 11, color: 'var(--txt3)' }}>
            ActivityWatch not running — start <code style={{ background: 'var(--surface2)', padding: '1px 5px', borderRadius: 3 }}>aw-server</code>
          </span>
        )}
        {d.is_afk && <span style={{ fontSize: 11, color: 'var(--amber)' }}>AFK</span>}
      </div>
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* Stats row */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 10 }}>
          {[
            { label: 'Tracked', val: d.total_minutes ? fmtDur(d.total_minutes) : '—' },
            { label: 'Focus time', val: d.focus_minutes ? fmtDur(d.focus_minutes) : '—' },
            { label: 'Learning time', val: d.learning_minutes ? fmtDur(d.learning_minutes) : '—' },
            { label: 'Focus score', val: d.aw_available ? `${d.focus_score ?? 0}%` : '—' },
          ].map(s => (
            <div key={s.label} className="stat-card">
              <div className="stat-val">{s.val}</div>
              <div className="stat-lbl">{s.label}</div>
            </div>
          ))}
        </div>

        {/* Focus split bar */}
        {d.aw_available && d.focus_minutes > 0 && (
          <FocusSplit learningMin={d.learning_minutes} focusMin={d.focus_minutes} totalMin={d.total_minutes} />
        )}

        {/* App time */}
        {(d.top_apps || []).length > 0 && (
          <AppTimeList apps={d.top_apps} hours={hours} />
        )}
      </div>
    </div>
  );
}

function FocusSplit({ learningMin, focusMin, totalMin }) {
  const otherMin = Math.max(0, focusMin - learningMin);
  const idleMin  = Math.max(0, totalMin - focusMin);
  const segments = [
    { label: 'Learning', min: learningMin, color: 'var(--accent)' },
    { label: 'Other',    min: otherMin,    color: 'var(--accent-dim)' },
    { label: 'Idle',     min: idleMin,     color: 'var(--brd2)' },
  ].filter(s => s.min > 0);
  const total = segments.reduce((s, x) => s + x.min, 0) || 1;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', height: 7, borderRadius: 4, overflow: 'hidden', gap: 1 }}>
        {segments.map(s => (
          <div key={s.label} style={{ flex: s.min / total, background: s.color, minWidth: 2 }} title={`${s.label}: ${fmtDur(s.min)}`} />
        ))}
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
      <div style={{ fontSize: 11, color: 'var(--txt3)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '.04em' }}>
        App time — last {hours}h
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
        {visible.map((a, i) => {
          const durMin = Math.round(a.duration / 60);
          const pct    = Math.round((a.duration / maxDur) * 100);
          const share  = totalSec > 0 ? Math.round(a.duration / totalSec * 100) : 0;
          return (
            <div key={i} className="app-bar-row">
              <span className="app-bar-label" style={{ color: a.is_learning ? 'var(--accent)' : 'var(--txt2)' }}>{a.app}</span>
              <div className="app-bar-track">
                <div className="app-bar-fill" style={{ width: `${pct}%`, background: a.is_learning ? 'var(--accent)' : 'var(--accent-dim)' }} />
              </div>
              <span className="app-bar-val">{durMin > 0 ? fmtDur(durMin) : '<1m'}</span>
              <span style={{ fontSize: 10, color: 'var(--txt3)', minWidth: 28, textAlign: 'right' }}>{share}%</span>
            </div>
          );
        })}
      </div>
      {apps.length > 6 && (
        <button className="tb-btn" style={{ marginTop: 8, fontSize: 11.5, color: 'var(--txt3)' }} onClick={() => setExpanded(v => !v)}>
          {expanded ? 'Show less' : `+${apps.length - 6} more apps`}
        </button>
      )}
    </div>
  );
}

// ── Agents strip ──────────────────────────────────────────────────────────────

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
