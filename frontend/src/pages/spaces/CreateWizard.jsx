/**
 * pages/spaces/CreateWizard.jsx
 * Multi-step space creation wizard. Templates are loaded from the backend.
 */
import { useState, useEffect } from 'react';
import { api } from '../../api';
import { useExpertTemplates, SpaceGeneratingAnimation } from './shared';
import { useStore } from '../../store';

export default function CreateSpaceWizard({ onClose, onCreated, onSpaceCreated }) {
  const [step, setStep] = useState(1);
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

  const { templates, loading: templatesLoading } = useExpertTemplates();

  // Poll for roadmap readiness on step 5
  useEffect(() => {
    if (step !== 5 || !createResult) return;
    let cancelled = false, tid = null;
    const poll = async () => {
      const sid = encodeURIComponent(createResult?.name || '');
      while (!cancelled) {
        try {
          const rm = await api(`/spaces/${sid}/roadmap`);
          if (rm?.chapters?.length > 0) { if (!cancelled) setRoadmapReady(true); return; }
        } catch {}
        await new Promise(res => { tid = setTimeout(res, 3000); });
      }
    };
    poll();
    return () => { cancelled = true; clearTimeout(tid); };
  }, [step, createResult]);

  const pf = p => setForm(f => ({ ...f, ...p }));

  const _fetchOverview = async (res) => {
    const sid = encodeURIComponent(res?.name || '');
    let overview = null;
    if (sid) {
      for (let i = 0; i < 4; i++) {
        try {
          const d = await api(`/spaces/${sid}/overview`);
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

  const filtered = templates.filter(d =>
    !search ||
    d.label.toLowerCase().includes(search.toLowerCase()) ||
    d.desc.toLowerCase().includes(search.toLowerCase()) ||
    (d.tools || []).some(t => t.toLowerCase().includes(search.toLowerCase()))
  );

  const handleCreate = async () => {
    if (creating) return;
    const dir = form.dir.trim();
    if (!dir) { err('Workspace directory is required'); return; }
    if (selected?.id === 'custom' && !form.goal.trim()) { err('Learning goal is required for custom domains'); return; }
    setCreating(true); setStep(3);
    try {
      const res = await api('/spaces/init', {
        method: 'POST',
        body: JSON.stringify({
          directory: dir, space_type: selected?.id || 'custom',
          name: form.name.trim(), background: form.bg.trim(),
          goal: form.goal.trim(), rag_enabled: form.rag,
        }),
      });
      setCreateResult(res);
      onSpaceCreated?.(res);
      const qs = res?.clarifying_questions || [];
      if (qs.length > 0) { setClarifyQs(qs); setStep(4); }
      else { ok('Space created!'); _fetchOverview(res); }
    } catch (e) { err(e.message); setCreating(false); setStep(2); }
  };

  // Step 3 — creating animation
  if (step === 3) return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '40px 0', gap: 24 }}>
      <SpaceGeneratingAnimation />
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--accent)', marginBottom: 6 }}>Setting up your Space…</div>
        <div style={{ fontSize: 12.5, color: 'var(--txt3)' }}>AI is discovering your domain and scaffolding the workspace.</div>
      </div>
    </div>
  );

  // Step 1 — domain picker
  if (step === 1) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <input className="s-input" style={{ width: '100%', marginBottom: 4 }}
        placeholder="Search domains, tools…" value={search}
        onChange={e => setSearch(e.target.value)} autoFocus />
      {templatesLoading ? (
        <div className="loading-center"><span className="spin" /></div>
      ) : (
        <div className="domain-grid">
          {filtered.map((d, idx) => (
            <DomainCard key={d.id} domain={d} idx={idx}
              selected={selected?.id === d.id}
              onSelect={() => setSelected(d)} />
          ))}
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button className="btn btn-muted btn-sm" onClick={onClose}>Cancel</button>
        <button className="btn btn-accent btn-sm" disabled={!selected} onClick={() => setStep(2)}>
          Continue with {selected ? selected.label : '…'} →
        </button>
      </div>
    </div>
  );

  // Step 2 — details form
  if (step === 2) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div className="wizard-selected-domain"
        style={{ background: `${selected.color}14`, borderColor: `${selected.color}44` }}>
        <TypeBadge id={selected.id} color={selected.color} />
        <div className="wizard-selected-info">
          <div className="wizard-selected-label">{selected.label}</div>
          <div className="wizard-selected-desc">{selected.desc}</div>
        </div>
        <button className="btn btn-muted btn-sm" style={{ fontSize: 10.5 }} onClick={() => setStep(1)}>Change</button>
      </div>
      <div>
        <label className="form-label">Workspace directory *</label>
        <input className="s-input mono" value={form.dir} onChange={e => pf({ dir: e.target.value })}
          placeholder="/home/user/my-space" autoFocus />
        {selected?.id === 'custom' && (
          <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginTop: 4 }}>
            AI will discover your domain from your goal and background.
          </div>
        )}
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
        <input className="s-input" value={form.bg} onChange={e => pf({ bg: e.target.value })}
          placeholder="e.g. final-year Btech, intermediate Python" />
      </div>
      <div>
        <label className="form-label">Learning goal{selected?.id === 'custom' ? ' *' : ''}</label>
        <input className="s-input" value={form.goal} onChange={e => pf({ goal: e.target.value })}
          placeholder={selected?.id === 'custom' ? 'e.g. decode Bhagavad Gita for modern life' : 'e.g. master ML for production systems'} />
      </div>
      {selected?.folders?.length > 0 && (
        <div style={{ fontSize: 11, color: 'var(--txt3)', padding: '8px 10px', background: 'var(--surface2)', borderRadius: 6, border: '1px solid var(--brd)' }}>
          <strong style={{ color: 'var(--txt2)' }}>Workspace folders: </strong>{selected.folders.join(', ')}
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button className="btn btn-muted btn-sm" onClick={() => setStep(1)}>Back</button>
        <button className="btn btn-accent btn-sm" onClick={handleCreate} disabled={creating || !form.dir.trim()}>
          {creating ? 'Creating…' : 'Create Space'}
        </button>
      </div>
    </div>
  );

  // Step 4 — clarifying questions
  if (step === 4) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ padding: '10px 14px', background: 'var(--accent-dim)', borderRadius: 8, border: '1px solid var(--accent-border)' }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent)', marginBottom: 4 }}>Space created!</div>
        <div style={{ fontSize: 12, color: 'var(--txt2)' }}>A few questions to refine your learning path.</div>
      </div>
      {clarifyQs.map((q, i) => (
        <div key={i}>
          <label className="form-label">{q}</label>
          <input className="s-input" value={clarifyAnswers[i] || ''}
            onChange={e => setClarifyAnswers(a => ({ ...a, [i]: e.target.value }))}
            placeholder="Your answer…" />
        </div>
      ))}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button className="btn btn-muted btn-sm" disabled={refining}
          onClick={() => { setRefining(true); _fetchOverview(createResult).finally(() => setRefining(false)); }}>
          {refining ? 'Please wait…' : 'Skip'}
        </button>
        <button className="btn btn-accent btn-sm" disabled={refining} onClick={async () => {
          if (refining) return; setRefining(true);
          try {
            await api('/spaces/refine', {
              method: 'POST',
              body: JSON.stringify({
                directory: createResult?.directory || form.dir,
                answers: clarifyQs.map((q, i) => `${q}: ${clarifyAnswers[i] || ''}`).join('\n'),
              }),
            });
            ok('Preferences saved!');
          } catch {}
          setRefining(false);
          await _fetchOverview(createResult);
        }}>
          {refining ? 'Generating…' : 'Save & Continue'}
        </button>
      </div>
    </div>
  );

  // Step 5 — overview / orientation
  if (step === 5) {
    const ov = overviewData || {};
    const hasContent = ov.what_is_this || ov.prerequisites?.length || ov.efficient_methods?.length;
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        <div className="ov-card ov-ready-banner" style={{ animationDelay: '0s' }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent)', marginBottom: 2 }}>Your space is ready!</div>
          <div style={{ fontSize: 12, color: 'var(--txt2)' }}>Roadmap is generating. Here is your orientation:</div>
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
                <div className="ov-section-title" style={{ color: 'var(--accent)' }}>What is this?</div>
                <div style={{ fontSize: 12.5, color: 'var(--txt)', lineHeight: 1.6 }}>{ov.what_is_this}</div>
              </div>
            )}
            {ov.starting_overview && (
              <div className="ov-card" style={{ animationDelay: '.1s', padding: '10px 13px', background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 8 }}>
                <div className="ov-section-title" style={{ color: 'var(--txt2)' }}>Where You Start</div>
                <div style={{ fontSize: 12.5, color: 'var(--txt2)', lineHeight: 1.6 }}>{ov.starting_overview}</div>
              </div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {ov.prerequisites?.length > 0 && (
                <div className="ov-card" style={{ animationDelay: '.15s', padding: '10px 12px', background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 8 }}>
                  <div className="ov-section-title" style={{ color: '#fbbf24' }}>Prerequisites</div>
                  {ov.prerequisites.map((p, i) => <div key={i} style={{ fontSize: 11.5, color: 'var(--txt2)', lineHeight: 1.4, marginBottom: 3 }}>— {p}</div>)}
                </div>
              )}
              {ov.efficient_methods?.length > 0 && (
                <div className="ov-card" style={{ animationDelay: '.2s', padding: '10px 12px', background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 8 }}>
                  <div className="ov-section-title" style={{ color: '#34d399' }}>Efficient Methods</div>
                  {ov.efficient_methods.map((m, i) => <div key={i} style={{ fontSize: 11.5, color: 'var(--txt2)', lineHeight: 1.4, marginBottom: 3 }}>+ {m}</div>)}
                </div>
              )}
            </div>
            {ov.pro_tips?.length > 0 && (
              <div className="ov-card" style={{ animationDelay: '.25s', padding: '10px 13px', background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 8 }}>
                <div className="ov-section-title" style={{ color: '#a78bfa' }}>Pro Tips</div>
                {ov.pro_tips.map((t, i) => <div key={i} style={{ fontSize: 11.5, color: 'var(--txt2)', lineHeight: 1.4, marginBottom: 3 }}>* {t}</div>)}
              </div>
            )}
          </div>
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 10, marginTop: 14 }}>
          {roadmapReady
            ? <button className="btn btn-accent btn-sm" onClick={() => onCreated(createResult)}>Enter Space</button>
            : <span style={{ fontSize: 11.5, color: 'var(--txt3)', display: 'flex', alignItems: 'center', gap: 6 }}>
                <span className="spin" style={{ width: 12, height: 12, borderWidth: 2 }} />
                Roadmap generating…
              </span>}
        </div>
      </div>
    );
  }

  return null;
}

// ── DomainCard ────────────────────────────────────────────────────────────────
// Single card in the domain picker grid. No emojis — uses a colored text badge.
function DomainCard({ domain: d, idx, selected, onSelect }) {
  return (
    <div
      className={`domain-card${selected ? ' selected' : ''}`}
      style={{ '--card-color': d.color, borderColor: selected ? d.color : 'var(--brd)', animationDelay: `${idx * 0.04}s` }}
      onClick={onSelect}
    >
      <TypeBadge id={d.id} color={d.color} />
      <div className="domain-card-label">{d.label}</div>
      <div className="domain-card-desc">{d.desc}</div>
      {d.tools?.length > 0 && (
        <div className="domain-card-tools">
          {d.tools.slice(0, 3).map(t => (
            <span key={t} className="domain-card-tool"
              style={{ background: `${d.color}22`, color: d.color, border: `1px solid ${d.color}44` }}>
              {t}
            </span>
          ))}
        </div>
      )}
      {selected && d.expert_tip && (
        <div className="domain-card-tip" style={{ background: `${d.color}18`, color: d.color }}>
          <div className="domain-card-tip-label">Expert tip</div>
          <div className="domain-card-tip-text">{d.expert_tip}</div>
        </div>
      )}
    </div>
  );
}

// ── TypeBadge ─────────────────────────────────────────────────────────────────
// Small colored text badge used instead of emojis.
function TypeBadge({ id, color }) {
  const ABBR = {
    data_science: 'DS', ai_engineering: 'AI', software_engineering: 'SE',
    medicine: 'MD', education: 'ED', exam_prep: 'EX',
    research: 'RS', business: 'BZ', custom: 'CU',
  };
  const abbr = ABBR[id] || id.slice(0, 2).toUpperCase();
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      width: 32, height: 32, borderRadius: 8, marginBottom: 8,
      background: `${color}22`, border: `1px solid ${color}55`,
      fontSize: 11, fontWeight: 700, color, fontFamily: 'var(--mono)',
      letterSpacing: '.04em',
    }}>
      {abbr}
    </div>
  );
}
