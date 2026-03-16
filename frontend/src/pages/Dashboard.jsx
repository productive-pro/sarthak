import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import SpaceCard from '../components/SpaceCard';
import { useStore } from '../store';
import useFetch from '../hooks/useFetch';
import { StatCard, XPBar, ConceptPills, Spinner, Section, AgentPill } from '../components/ui';

export default function Dashboard() {
  const [selected, setSelected] = useState(null);

  const { data, loading: loadingData, reload: reloadData }           = useFetch(`/dashboard`, [], { initialData: null });
  const { data: spaces = [], loading: loadingSpaces, reload: reloadSpaces } = useFetch('/spaces', [], { initialData: [] });
  const { data: agents = [], loading: loadingAgents, reload: reloadAgents } = useFetch('/agents', [], { initialData: [] });
  const { data: profilesList = [], reload: reloadProfiles }           = useFetch('/spaces/profiles', [], { initialData: [] });

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
          <button className="btn btn-muted btn-sm" onClick={refresh}>Refresh</button>
        </div>
      </header>
      <div className="pg-body">
        <div className="dash-col">
          {(loadingData || loadingSpaces) ? <Spinner /> : data?.active_space
            ? <ActiveSpaceHero space={data.active_space} profile={profiles[data.active_space.name]} />
            : spaces.length > 0 ? <NoActiveSpaceBanner /> : null}
          {!loadingSpaces && <SpacesGrid spaces={spaces} profiles={profiles} onSelect={setSelected} />}
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
  const xp       = profile?.xp       ?? space.xp       ?? 0;
  const xpNext   = profile?.xp_to_next ?? space.xp_to_next ?? 1;
  const streak   = profile?.streak_days ?? space.streak_days ?? 0;
  const sessions = profile?.session_count ?? space.session_count ?? 0;
  const level    = profile?.level    ?? space.level    ?? '';
  const domain   = profile?.domain   ?? space.domain   ?? '';
  const mastered   = (profile?.mastered_concepts || space.skills  || []).slice(-6);
  const struggling = (profile?.struggling_concepts || []).slice(0, 4);
  const badges     = (profile?.badges || []).slice(0, 5);

  const goToSpace = () => {
    setCurrentSpace({ name: space.name, directory: space.directory, space_type: space.space_type });
    setSpaceRoadmap(null); setSpacesView('home'); setPage('spaces');
  };

  return (
    <div className="active-hero">
      <div className="active-hero-top">
        <div className="active-hero-info">
          <div className="active-hero-labels">
            <span className="badge badge-active">Active Space</span>
            {space.space_type && <span className="active-hero-type">{space.space_type.replace(/_/g, ' ')}</span>}
          </div>
          <div className="active-hero-name">{space.name}</div>
          {domain && <div className="active-hero-domain">{domain}</div>}
        </div>
        <button className="btn btn-accent btn-sm" onClick={goToSpace}>Open</button>
      </div>
      <div className="stats-grid-4">
        {[{ val: `${xp}`, lbl: 'XP' }, { val: level || '—', lbl: 'Level' },
          { val: `${streak}d`, lbl: 'Streak' }, { val: `${sessions}`, lbl: 'Sessions' }]
          .map(s => <StatCard key={s.lbl} val={s.val} lbl={s.lbl} />)}
      </div>
      <XPBar xp={xp} xpNext={xpNext} />
      <div className="active-hero-concepts">
        <ConceptPills concepts={mastered} label="Mastered" type="mastered" />
        <ConceptPills concepts={struggling} label="Needs review" type="struggling" />
        {badges.length > 0 && (
          <div>
            <div className="meta-label">Badges</div>
            <div className="pill-row">
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
    <div className="no-active-banner">
      <div>
        <div className="no-active-title">No active space</div>
        <div className="no-active-sub">Activate a space to track your active learning session here.</div>
      </div>
      <button className="btn btn-accent btn-sm" onClick={() => setPage('spaces')}>Go to Spaces</button>
    </div>
  );
}

// ── Spaces Grid ───────────────────────────────────────────────────────────────
function SpacesGrid({ spaces, profiles, onSelect }) {
  const { setCurrentSpace, setSpaceRoadmap, setSpacesView, setPage } = useStore();
  const openSpace = (s) => { setCurrentSpace(s); setSpaceRoadmap(null); setSpacesView('home'); setPage('spaces'); };

  const right = (
    <div className="card-hdr-right">
      <span className="txt-muted-xs">{spaces.length} total</span>
      <button className="btn btn-muted btn-xs" onClick={() => setPage('spaces')}>Manage</button>
    </div>
  );

  if (!spaces.length) return (
    <Section title="Spaces">
      <div className="empty-inline">
        <span>No spaces yet.</span>
        <button className="btn btn-accent btn-sm" onClick={() => setPage('spaces')}>Create your first space</button>
      </div>
    </Section>
  );

  return (
    <Section title="Spaces" right={right}>
      <div className="spaces-dash-grid">
        {spaces.map(s => (
          <SpaceCard key={s.name || s.directory} variant="dashboard" space={s} profile={profiles[s.name]}
            onDrillDown={() => onSelect(s)} onOpen={() => openSpace(s)} />
        ))}
      </div>
    </Section>
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
    <div className="drilldown-backdrop" onClick={onClose}>
      <div className="drilldown-sheet" onClick={e => e.stopPropagation()}>
        <div className="drilldown-hdr">
          <div>
            <div className="drilldown-title">{space.name}</div>
            {lr?.domain && <div className="drilldown-domain">{lr.domain}</div>}
          </div>
          <div className="drilldown-actions">
            <button className="btn btn-accent btn-sm" onClick={goToSpace}>Open Space</button>
            <button className="btn btn-muted btn-sm" onClick={onClose}>Close</button>
          </div>
        </div>
        {loading ? <Spinner /> : !lr ? (
          <div className="txt-muted-sm">No profile yet. Initialize this space first.</div>
        ) : (
          <div className="drilldown-body">
            <div className="stats-grid-4">
              {[{ val: `${lr.xp ?? 0}`, lbl: 'XP' }, { val: lr.level || lr.skill_level || '—', lbl: 'Level' },
                { val: `${lr.streak_days ?? 0}d`, lbl: 'Streak' }, { val: `${lr.session_count ?? lr.total_sessions ?? 0}`, lbl: 'Sessions' }]
                .map(st => <StatCard key={st.lbl} val={st.val} lbl={st.lbl} />)}
            </div>
            <XPBar xp={xp} xpNext={xpNext} />
            {(lr.goal || lr.background) && (
              <div className="meta-row">
                {lr.goal && <MetaField label="Goal" value={lr.goal} />}
                {lr.background && <MetaField label="Background" value={lr.background} />}
              </div>
            )}
            <ConceptPills
              concepts={(lr.mastered_concepts || []).slice(-15)}
              label={`Mastered concepts (${lr.mastered_count ?? (lr.mastered_concepts || []).length})`}
              type="mastered" />
            <ConceptPills concepts={lr.struggling_concepts} label="Needs review" type="struggling" />
            {(lr.badges || []).length > 0 && (
              <div>
                <div className="meta-label">Badges</div>
                <div className="pill-row">
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

/** Small labelled text field used in drill-down */
function MetaField({ label, value }) {
  return (
    <div className="meta-field">
      <div className="meta-label">{label}</div>
      <div className="meta-value">{value}</div>
    </div>
  );
}

// ── Agents Strip ──────────────────────────────────────────────────────────────
function AgentsStrip({ agents }) {
  const { setPage } = useStore();
  if (!agents.length) return null;
  const active = agents.filter(a => a.enabled).length;

  const right = (
    <div className="card-hdr-right">
      <span className={active > 0 ? 'txt-accent-xs' : 'txt-muted-xs'}>{active} active</span>
      <button className="btn btn-muted btn-xs" onClick={() => setPage('agents')}>Manage</button>
    </div>
  );

  return (
    <Section title="Agents" right={right}>
      <div className="agents-strip">
        {agents.slice(0, 8).map(a => <AgentPill key={a.agent_id} agent={a} />)}
        {agents.length > 8 && <span className="txt-muted-xs">+{agents.length - 8} more</span>}
      </div>
    </Section>
  );
}
