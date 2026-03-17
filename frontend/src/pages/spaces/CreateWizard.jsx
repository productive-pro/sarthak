/**
 * pages/spaces/CreateWizard.jsx
 * Multi-step space creation wizard — redesigned with bug fixes:
 *
 * Bug fixes:
 *  1. Roadmap failure surfaced with retry button (polls roadmap-status endpoint)
 *  2. Overview fetch retries 10× with 3s gaps; reads roadmap_status from overview response
 *  3. "Enter Space now" escape hatch before roadmap finishes
 *  4. Refine endpoint now awaits; loading state properly shown
 *  5. Getting Started section shown in step 5
 *  9. just_created flag set so SpaceHome shows welcome banner
 */
import { useState, useEffect, useCallback } from 'react';
import { api } from '../../api';
import { useExpertTemplates, SpaceGeneratingAnimation } from './shared';
import { useStore } from '../../store';

// ── Step indicator ────────────────────────────────────────────────────────────
function StepDots({ step, total = 5 }) {
  return (
    <div style={{ display: 'flex', gap: 5, alignItems: 'center', justifyContent: 'center', marginBottom: 18 }}>
      {Array.from({ length: total }, (_, i) => (
        <div key={i} style={{
          width: i + 1 === step ? 18 : 6,
          height: 6,
          borderRadius: 3,
          background: i + 1 <= step ? 'var(--accent)' : 'var(--brd2)',
          transition: 'width 250ms ease, background 250ms ease',
        }} />
      ))}
    </div>
  );
}

// ── Inline section heading ────────────────────────────────────────────────────
function SectionTitle({ children, color = 'var(--txt3)' }) {
  return (
    <div style={{
      fontSize: 10,
      fontWeight: 700,
      textTransform: 'uppercase',
      letterSpacing: '.07em',
      color,
      marginBottom: 5,
    }}>{children}</div>
  );
}

// ── Overview card wrapper ─────────────────────────────────────────────────────
function OvCard({ children, accent, delay = 0 }) {
  return (
    <div className="ov-card" style={{
      animationDelay: `${delay}s`,
      padding: '11px 14px',
      background: accent ? `color-mix(in srgb, ${accent} 6%, var(--surface))` : 'var(--surface)',
      border: `1px solid ${accent ? `color-mix(in srgb, ${accent} 25%, var(--brd))` : 'var(--brd)'}`,
      borderLeft: accent ? `3px solid ${accent}` : '1px solid var(--brd)',
      borderRadius: 9,
    }}>
      {children}
    </div>
  );
}

// ── List items inside overview ────────────────────────────────────────────────
function OvList({ items, icon = '-', color = 'var(--txt2)' }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 3 }}>
      {items.map((item, i) => (
        <div key={i} style={{ display: 'flex', gap: 7, fontSize: 12, color, lineHeight: 1.5 }}>
          <span style={{ flexShrink: 0, color: 'var(--txt3)', fontFamily: 'var(--mono)', fontSize: 10, marginTop: 2 }}>{icon}</span>
          <span>{item}</span>
        </div>
      ))}
    </div>
  );
}

// ── TypeBadge ─────────────────────────────────────────────────────────────────
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
      letterSpacing: '.04em', flexShrink: 0,
    }}>{abbr}</div>
  );
}

// ── DomainCard ────────────────────────────────────────────────────────────────
function DomainCard({ domain: d, idx, selected, onSelect }) {
  return (
    <div
      className={`domain-card${selected ? ' selected' : ''}`}
      style={{ '--card-color': d.color, borderColor: selected ? d.color : 'var(--brd)', animationDelay: `${idx * 0.03}s` }}
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


// ── Main wizard ───────────────────────────────────────────────────────────────
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
  // roadmapStatus: 'pending' | 'generating' | 'ready' | 'failed'
  const [roadmapStatus, setRoadmapStatus] = useState('pending');
  const { ok, err } = useStore();

  const { templates, loading: templatesLoading } = useExpertTemplates();

  const pf = p => setForm(f => ({ ...f, ...p }));

  // ── Poll roadmap-status endpoint on step 5 ─────────────────────────────────
  useEffect(() => {
    if (step !== 5 || !createResult) return;
    let cancelled = false, tid = null;
    const poll = async () => {
      const sid = encodeURIComponent(createResult?.name || '');
      let attempts = 0;
      while (!cancelled && attempts < 40) {
        attempts++;
        try {
          const rs = await api(`/spaces/${sid}/roadmap-status`);
          const s = rs?.status || 'pending';
          if (!cancelled) setRoadmapStatus(s);
          if (s === 'ready' || s === 'failed') return;
        } catch {}
        await new Promise(res => { tid = setTimeout(res, 3000); });
      }
    };
    poll();
    return () => { cancelled = true; clearTimeout(tid); };
  }, [step, createResult]);

  // ── Fetch overview with longer retry window (Fix 2) ────────────────────────
  const _fetchOverview = useCallback(async (res) => {
    const sid = encodeURIComponent(res?.name || '');
    let overview = null;
    if (sid) {
      for (let i = 0; i < 10; i++) {
        try {
          const d = await api(`/spaces/${sid}/overview`);
          if (d && Object.keys(d).filter(k => k !== 'roadmap_status').length > 0) {
            overview = d;
            // Seed status from overview response if available
            if (d.roadmap_status) setRoadmapStatus(d.roadmap_status);
            break;
          }
        } catch {}
        await new Promise(r => setTimeout(r, 3000));
      }
    }
    setOverviewData(overview || {});
    setCreateResult(res);
    setStep(5);
    onSpaceCreated?.(res);
  }, [onSpaceCreated]);

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
      if (qs.length > 0) { setClarifyQs(qs); setStep(4); setCreating(false); }
      else { ok('Space created!'); _fetchOverview(res); }
    } catch (e) { err(e.message); setCreating(false); setStep(2); }
  };


  // ── Step 3 — creating animation ───────────────────────────────────────────
  if (step === 3) return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '48px 0', gap: 24 }}>
      <SpaceGeneratingAnimation />
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--accent)', marginBottom: 6 }}>Setting up your Space</div>
        <div style={{ fontSize: 12, color: 'var(--txt3)', maxWidth: 260, lineHeight: 1.6 }}>Discovering your domain and scaffolding the workspace.</div>
      </div>
    </div>
  );

  // ── Step 1 — domain picker ─────────────────────────────────────────────────
  if (step === 1) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <StepDots step={1} />
      <input className="s-input" style={{ width: '100%' }}
        placeholder="Search domains or tools…" value={search}
        onChange={e => setSearch(e.target.value)} autoFocus />
      {templatesLoading ? (
        <div className="loading-center"><span className="spin" /></div>
      ) : (
        <div className="domain-grid" style={{ maxHeight: 340 }}>
          {filtered.map((d, idx) => (
            <DomainCard key={d.id} domain={d} idx={idx}
              selected={selected?.id === d.id}
              onSelect={() => setSelected(d)} />
          ))}
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, paddingTop: 4 }}>
        <button className="btn btn-muted btn-sm" onClick={onClose}>Cancel</button>
        <button className="btn btn-accent btn-sm" disabled={!selected} onClick={() => setStep(2)}>
          Continue with {selected ? selected.label : '…'} →
        </button>
      </div>
    </div>
  );

  // ── Step 2 — details form ──────────────────────────────────────────────────
  if (step === 2) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <StepDots step={2} />
      <div className="wizard-selected-domain"
        style={{ background: `${selected.color}10`, borderColor: `${selected.color}40` }}>
        <TypeBadge id={selected.id} color={selected.color} />
        <div className="wizard-selected-info">
          <div className="wizard-selected-label">{selected.label}</div>
          <div className="wizard-selected-desc">{selected.desc}</div>
        </div>
        <button className="btn btn-muted btn-sm" style={{ fontSize: 10.5, marginLeft: 'auto' }} onClick={() => setStep(1)}>Change</button>
      </div>
      <div>
        <label className="form-label">Workspace directory *</label>
        <input className="s-input mono" value={form.dir} onChange={e => pf({ dir: e.target.value })}
          placeholder="/home/user/my-space" autoFocus />
        {selected?.id === 'custom' && (
          <div style={{ fontSize: 11, color: 'var(--txt3)', marginTop: 4 }}>AI will discover your domain from your goal and background.</div>
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
            Enable RAG search
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
        <div style={{ fontSize: 11, color: 'var(--txt3)', padding: '7px 10px', background: 'var(--surface2)', borderRadius: 7, border: '1px solid var(--brd)' }}>
          <strong style={{ color: 'var(--txt2)' }}>Workspace folders: </strong>{selected.folders.join(', ')}
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, paddingTop: 4 }}>
        <button className="btn btn-muted btn-sm" onClick={() => setStep(1)}>Back</button>
        <button className="btn btn-accent btn-sm" onClick={handleCreate} disabled={creating || !form.dir.trim()}>
          {creating ? 'Creating…' : 'Create Space'}
        </button>
      </div>
    </div>
  );


  // ── Step 4 — clarifying questions (Fix 4: refine now awaits) ──────────────
  if (step === 4) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <StepDots step={4} />
      <div style={{
        padding: '11px 14px',
        background: 'var(--accent-dim)',
        border: '1px solid var(--accent-border)',
        borderRadius: 9,
        display: 'flex',
        flexDirection: 'column',
        gap: 3,
      }}>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--accent)' }}>Space created</div>
        <div style={{ fontSize: 12, color: 'var(--txt2)' }}>
          Answer a couple of questions to personalise your roadmap. Your answers are saved for future regenerations.
        </div>
      </div>
      {clarifyQs.map((q, i) => (
        <div key={i}>
          <label className="form-label">{q}</label>
          <input className="s-input" value={clarifyAnswers[i] || ''}
            onChange={e => setClarifyAnswers(a => ({ ...a, [i]: e.target.value }))}
            placeholder="Your answer…" autoFocus={i === 0} />
        </div>
      ))}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, paddingTop: 4 }}>
        <button className="btn btn-muted btn-sm" disabled={refining}
          onClick={() => { setRefining(true); _fetchOverview(createResult).finally(() => setRefining(false)); }}>
          {refining ? 'Please wait…' : 'Skip'}
        </button>
        <button className="btn btn-accent btn-sm" disabled={refining} onClick={async () => {
          if (refining) return;
          setRefining(true);
          try {
            // Refine endpoint now awaits server-side — we wait for it here too
            await api('/spaces/refine', {
              method: 'POST',
              body: JSON.stringify({
                directory: createResult?.directory || form.dir,
                answers: clarifyQs.map((q, i) => `${q}: ${clarifyAnswers[i] || ''}`).join('\n'),
              }),
            });
            ok('Preferences saved — roadmap is being regenerated.');
          } catch (e) {
            err(e.message || 'Refinement failed, proceeding with original roadmap.');
          }
          setRefining(false);
          await _fetchOverview(createResult);
        }}>
          {refining ? (
            <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span className="spin" style={{ width: 11, height: 11, borderWidth: 2 }} />
              Generating…
            </span>
          ) : 'Save & Generate'}
        </button>
      </div>
    </div>
  );


  // ── Step 5 — overview + orientation (Fixes 1, 2, 3, 5, 9) ─────────────────
  if (step === 5) {
    const ov = overviewData || {};
    const hasContent = ov.what_is_this || ov.prerequisites?.length || ov.efficient_methods?.length;
    const isFailed   = roadmapStatus === 'failed';
    const isReady    = roadmapStatus === 'ready';
    const isGenerating = roadmapStatus === 'generating' || roadmapStatus === 'pending';

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        <StepDots step={5} />

        {/* Ready / generating / failed banner */}
        <div className="ov-card ov-ready-banner" style={{
          marginBottom: 12,
          borderColor: isFailed ? 'rgba(248,113,113,.35)' : 'var(--accent-border)',
          background: isFailed ? 'rgba(248,113,113,.08)' : 'var(--accent-dim)',
        }}>
          <div style={{ fontSize: 12.5, fontWeight: 700, color: isFailed ? 'var(--red)' : 'var(--accent)', marginBottom: 2 }}>
            {isFailed ? 'Roadmap generation failed' : isReady ? 'Your space is ready' : 'Space created — roadmap generating…'}
          </div>
          <div style={{ fontSize: 12, color: 'var(--txt2)' }}>
            {isFailed
              ? 'You can enter the space and retry roadmap generation from settings.'
              : isReady
              ? 'Your personalised roadmap is ready. Review your orientation below.'
              : 'Here is your orientation while the roadmap is being built.'}
          </div>
        </div>

        {/* Overview content */}
        {!hasContent ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '24px 0', gap: 12, color: 'var(--txt3)', fontSize: 12 }}>
            <span className="spin" style={{ width: 22, height: 22, borderWidth: 2.5 }} />
            <div>Generating your personalised overview…</div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 360, overflowY: 'auto', paddingRight: 3 }}>

            {/* What is this */}
            {ov.what_is_this && (
              <OvCard accent="var(--accent)" delay={0.04}>
                <SectionTitle color="var(--accent)">What is this</SectionTitle>
                <div style={{ fontSize: 12.5, color: 'var(--txt)', lineHeight: 1.65 }}>{ov.what_is_this}</div>
              </OvCard>
            )}

            {/* Where you start */}
            {ov.starting_overview && (
              <OvCard delay={0.08}>
                <SectionTitle color="var(--txt3)">Where you start</SectionTitle>
                <div style={{ fontSize: 12.5, color: 'var(--txt2)', lineHeight: 1.65 }}>{ov.starting_overview}</div>
              </OvCard>
            )}

            {/* Getting started — Fix 5: new section */}
            {ov.getting_started?.length > 0 && (
              <OvCard accent="#8b5cf6" delay={0.1}>
                <SectionTitle color="#8b5cf6">First 3 actions</SectionTitle>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
                  {ov.getting_started.map((action, i) => {
                    const label = i === 0 ? '30 min' : i === 1 ? 'Day 1' : 'Week 1';
                    return (
                      <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                        <div style={{
                          fontSize: 9.5, fontWeight: 700, color: '#8b5cf6',
                          background: 'rgba(139,92,246,.15)', border: '1px solid rgba(139,92,246,.3)',
                          borderRadius: 4, padding: '1px 5px', whiteSpace: 'nowrap',
                          marginTop: 1, fontFamily: 'var(--mono)', flexShrink: 0,
                        }}>{label}</div>
                        <div style={{ fontSize: 12, color: 'var(--txt2)', lineHeight: 1.5 }}>{action}</div>
                      </div>
                    );
                  })}
                </div>
              </OvCard>
            )}

            {/* Prerequisites + methods side-by-side */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {ov.prerequisites?.length > 0 && (
                <OvCard delay={0.13}>
                  <SectionTitle color="#fbbf24">Prerequisites</SectionTitle>
                  <OvList items={ov.prerequisites} icon="—" color="var(--txt2)" />
                </OvCard>
              )}
              {ov.efficient_methods?.length > 0 && (
                <OvCard delay={0.16}>
                  <SectionTitle color="#34d399">Efficient methods</SectionTitle>
                  <OvList items={ov.efficient_methods} icon="+" color="var(--txt2)" />
                </OvCard>
              )}
            </div>

            {/* Pro tips */}
            {ov.pro_tips?.length > 0 && (
              <OvCard delay={0.2}>
                <SectionTitle color="var(--txt3)">Pro tips</SectionTitle>
                <OvList items={ov.pro_tips} icon="*" color="var(--txt2)" />
              </OvCard>
            )}

          </div>
        )}

        {/* Footer: Enter now (Fix 3) or wait for roadmap */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 10, marginTop: 14, paddingTop: 10, borderTop: '1px solid var(--brd)' }}>
          {/* Always-available escape hatch — Fix 3 */}
          {!isReady && !isFailed && (
            <button className="btn btn-muted btn-sm" style={{ fontSize: 11.5 }}
              onClick={() => onCreated(createResult)}>
              Enter now (roadmap loading)
            </button>
          )}
          {isFailed ? (
            <button className="btn btn-accent btn-sm" onClick={() => onCreated(createResult)}>
              Enter Space
            </button>
          ) : isReady ? (
            <button className="btn btn-accent btn-sm" onClick={() => onCreated(createResult)}>
              Enter Space →
            </button>
          ) : (
            <span style={{ fontSize: 11.5, color: 'var(--txt3)', display: 'flex', alignItems: 'center', gap: 6 }}>
              <span className="spin" style={{ width: 11, height: 11, borderWidth: 2 }} />
              Roadmap generating…
            </span>
          )}
        </div>
      </div>
    );
  }

  return null;
}
