import React, { useState } from 'react';

const TABS = [
  { id: 'overview', label: '✦ Overview' },
  { id: 'config', label: 'Config' },
  { id: 'learner', label: 'Learner' },
  { id: 'identity', label: 'Identity' },
  { id: 'memory', label: 'Memory' },
  { id: 'context', label: 'AI Context' },
  { id: 'files', label: 'Files' },
];

const TextArea = ({ value, onChange, minHeight, placeholder, style }) => (
  <textarea
    className="s-input"
    style={{
      width: '100%',
      minHeight: minHeight || 180,
      fontFamily: 'var(--mono)',
      fontSize: 12,
      resize: 'vertical',
      lineHeight: 1.6,
      ...style,
    }}
    value={value}
    onChange={e => onChange(e.target.value)}
    placeholder={placeholder}
  />
);

// ── Extracted sub-components (defined outside to prevent re-mount on every render) ──

function TagPills({ form, field, color, input, setInput, onAddTag, onRemoveTag }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {(form[field] || []).map(v => (
          <span
            key={v}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              fontSize: 11,
              padding: '2px 8px',
              borderRadius: 20,
              background: `${color}18`,
              color,
              border: `1px solid ${color}44`,
            }}
          >
            {v}
            <button
              onClick={() => onRemoveTag(field, v)}
              style={{ background: 'none', border: 'none', color, cursor: 'pointer', padding: 0, lineHeight: 1, fontSize: 13 }}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          className="s-input"
          style={{ flex: 1, fontSize: 12, padding: '4px 8px' }}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') onAddTag(field, input, setInput); }}
          placeholder="Type and press Enter…"
        />
        <button className="btn btn-muted btn-xs" onClick={() => onAddTag(field, input, setInput)}>Add</button>
      </div>
    </div>
  );
}

function SaveBar({ onSave, saving }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: 12, borderTop: '1px solid var(--brd)', marginTop: 8 }}>
      <button className="btn btn-accent btn-sm" onClick={onSave} disabled={saving}>
        {saving ? 'Saving…' : 'Save Changes'}
      </button>
    </div>
  );
}

export default function SettingsTabs({ tab, setTab, settings, form, onChange, onSave, saving, onDelete, onRegenerateRoadmap, regenerating }) {
  const [conceptInput, setConceptInput] = useState('');
  const [strugglingInput, setStrugglingInput] = useState('');
  const [badgeInput, setBadgeInput] = useState('');

  const addTag = (field, val, setter) => {
    const v = val.trim();
    if (!v) return;
    const current = form[field] || [];
    if (!current.includes(v)) onChange({ [field]: [...current, v] });
    setter('');
  };

  const removeTag = (field, val) => onChange({ [field]: (form[field] || []).filter(x => x !== val) });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', gap: 4, padding: '0 0 12px', borderBottom: '1px solid var(--brd)', marginBottom: 16, flexWrap: 'wrap', flexShrink: 0 }}>
        {TABS.map(t => (
          <button key={t.id} className={`td-tab${tab === t.id ? ' active' : ''}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, flex: 1, overflowY: 'auto' }}>
          {!settings.overview || Object.keys(settings.overview).length === 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '40px 20px', gap: 12, color: 'var(--txt3)', fontSize: 13, textAlign: 'center' }}>
              <div style={{ fontSize: 28 }}>🧭</div>
              <div style={{ fontWeight: 600, color: 'var(--txt2)' }}>Overview not generated yet</div>
              <div style={{ fontSize: 12, maxWidth: 320 }}>The AI overview is generated in the background after roadmap creation. It may take a minute to appear. Try regenerating the roadmap in Config.</div>
            </div>
          ) : (
            <>
              {settings.overview.what_is_this && (
                <div style={{ padding: '12px 14px', background: 'var(--accent-dim)', border: '1px solid var(--accent-border)', borderRadius: 9, borderLeft: '3px solid var(--accent)' }}>
                  <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 6 }}>What is this?</div>
                  <div style={{ fontSize: 13, color: 'var(--txt)', lineHeight: 1.6 }}>{settings.overview.what_is_this}</div>
                </div>
              )}
              {settings.overview.starting_overview && (
                <div style={{ padding: '12px 14px', background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 9 }}>
                  <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--txt2)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 6 }}>Where You Start</div>
                  <div style={{ fontSize: 13, color: 'var(--txt2)', lineHeight: 1.6 }}>{settings.overview.starting_overview}</div>
                </div>
              )}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                {settings.overview.prerequisites?.length > 0 && (
                  <div style={{ padding: '12px 14px', background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 9 }}>
                    <div style={{ fontSize: 10.5, fontWeight: 700, color: '#fbbf24', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 8 }}>Prerequisites</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                      {settings.overview.prerequisites.map((p, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 7, fontSize: 12, color: 'var(--txt2)', lineHeight: 1.4 }}>
                          <span style={{ color: '#fbbf24', marginTop: 1, flexShrink: 0 }}>◆</span>{p}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {settings.overview.efficient_methods?.length > 0 && (
                  <div style={{ padding: '12px 14px', background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 9 }}>
                    <div style={{ fontSize: 10.5, fontWeight: 700, color: '#34d399', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 8 }}>Efficient Methods</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                      {settings.overview.efficient_methods.map((m, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 7, fontSize: 12, color: 'var(--txt2)', lineHeight: 1.4 }}>
                          <span style={{ color: '#34d399', marginTop: 1, flexShrink: 0 }}>✓</span>{m}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
              {settings.overview.pro_tips?.length > 0 && (
                <div style={{ padding: '12px 14px', background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 9 }}>
                  <div style={{ fontSize: 10.5, fontWeight: 700, color: '#a78bfa', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 8 }}>Pro Tips</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {settings.overview.pro_tips.map((t, i) => (
                      <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 7, fontSize: 12, color: 'var(--txt2)', lineHeight: 1.4 }}>
                        <span style={{ color: '#a78bfa', marginTop: 1, flexShrink: 0 }}>★</span>{t}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {tab === 'config' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, flex: 1, overflowY: 'auto' }}>
          <div style={{ padding: '7px 11px', background: 'var(--surface2)', borderRadius: 6, border: '1px solid var(--brd)', fontSize: 11.5, color: 'var(--txt3)', fontFamily: 'var(--mono)' }}>
            {settings.directory}
          </div>
          <div>
            <label className="form-label">Domain name</label>
            <input className="s-input" value={form.domain_name} onChange={e => onChange({ domain_name: e.target.value })} placeholder="e.g. Bhagavad Gita: Philosophy & Application" />
          </div>
          <div>
            <label className="form-label">Learning goal</label>
            <input className="s-input" value={form.goal} onChange={e => onChange({ goal: e.target.value })} placeholder="What do you want to master?" />
          </div>
          <div>
            <label className="form-label">Your background</label>
            <input className="s-input" value={form.background} onChange={e => onChange({ background: e.target.value })} placeholder="e.g. final-year BTech, intermediate Python" />
          </div>
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'center' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--txt2)', cursor: 'pointer' }}>
              <input type="checkbox" checked={form.rag_enabled} onChange={e => onChange({ rag_enabled: e.target.checked })} />
              Enable RAG (vector search)
            </label>
          </div>
          {settings.tags?.length > 0 && (
            <div>
              <label className="form-label">Tags</label>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {settings.tags.map(t => <span key={t} className="badge badge-muted">{t}</span>)}
              </div>
            </div>
          )}
          <div style={{ marginTop: 10, paddingTop: 12, borderTop: '1px solid var(--brd)' }}>
            <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--accent)', marginBottom: 6 }}>Roadmap</div>
            <div style={{ fontSize: 11.5, color: 'var(--txt3)', marginBottom: 8 }}>
              Discard the current roadmap and generate a fresh one using the current goal and background.
            </div>
            <button className="btn btn-muted btn-sm" onClick={onRegenerateRoadmap} disabled={regenerating}>
              {regenerating ? 'Regenerating…' : '↻ Regenerate Roadmap'}
            </button>
          </div>
          <div style={{ marginTop: 10, paddingTop: 12, borderTop: '1px solid var(--brd)' }}>
            <div style={{ fontSize: 11.5, fontWeight: 700, color: '#f87171', marginBottom: 6 }}>Danger Zone</div>
            <div style={{ fontSize: 11.5, color: 'var(--txt3)', marginBottom: 8 }}>
              Deleting a space moves the folder to local trash and removes it from Sarthak.
            </div>
            <button className="btn btn-del btn-sm" onClick={onDelete}>
              Delete Space
            </button>
          </div>
          <SaveBar onSave={onSave} saving={saving} />
        </div>
      )}

      {tab === 'learner' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, flex: 1, overflowY: 'auto' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
            {[
              { lbl: 'XP', val: settings.xp ?? 0 },
              { lbl: 'Level', val: settings.skill_level || '—' },
              { lbl: 'Streak', val: `${settings.streak_days ?? 0}d` },
              { lbl: 'Sessions', val: settings.total_sessions ?? 0 },
            ].map(s => (
              <div key={s.lbl} style={{ background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 7, padding: '8px 10px', textAlign: 'center' }}>
                <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--accent)' }}>{s.val}</div>
                <div style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '.04em', marginTop: 2 }}>{s.lbl}</div>
              </div>
            ))}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label className="form-label">Preferred learning style</label>
              <input className="s-input" value={form.preferred_style} onChange={e => onChange({ preferred_style: e.target.value })} placeholder="e.g. visual + hands-on" />
            </div>
            <div>
              <label className="form-label">Daily goal (minutes)</label>
              <input className="s-input" type="number" min={5} max={480} value={form.daily_goal_minutes} onChange={e => onChange({ daily_goal_minutes: +e.target.value })} />
            </div>
          </div>
          <div>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--txt2)', cursor: 'pointer' }}>
              <input type="checkbox" checked={form.is_technical} onChange={e => onChange({ is_technical: e.target.checked })} />
              Technical learner (enables code-first explanations)
            </label>
          </div>
          <div>
            <label className="form-label">Mastered concepts <span style={{ color: 'var(--txt3)', fontWeight: 400 }}>({form.mastered_concepts.length})</span></label>
            <TagPills form={form} field="mastered_concepts" color="var(--accent)" input={conceptInput} setInput={setConceptInput} onAddTag={addTag} onRemoveTag={removeTag} />
          </div>
          <div>
            <label className="form-label">Struggling concepts</label>
            <TagPills form={form} field="struggling_concepts" color="#f87171" input={strugglingInput} setInput={setStrugglingInput} onAddTag={addTag} onRemoveTag={removeTag} />
          </div>
          <div>
            <label className="form-label">Badges</label>
            <TagPills form={form} field="badges" color="#fbbf24" input={badgeInput} setInput={setBadgeInput} onAddTag={addTag} onRemoveTag={removeTag} />
          </div>
          <SaveBar onSave={onSave} saving={saving} />
        </div>
      )}

      {tab === 'identity' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1, overflowY: 'auto' }}>
          <div style={{ fontSize: 12, color: 'var(--txt3)', lineHeight: 1.5, padding: '8px 12px', background: 'var(--surface2)', borderRadius: 6, border: '1px solid var(--brd)' }}>
            <strong style={{ color: 'var(--accent)' }}>SOUL.md</strong> — defines the AI agent's identity and behavior for this space. Edits here persist and are loaded at every session.
          </div>
          <div style={{ flex: 1 }}>
            <TextArea value={form.soul_md} onChange={v => onChange({ soul_md: v })} minHeight={300} placeholder="# SOUL.md\nDefine how the AI should behave in this space…" />
          </div>
          <SaveBar onSave={onSave} saving={saving} />
        </div>
      )}

      {tab === 'memory' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1, overflowY: 'auto' }}>
          <div style={{ fontSize: 12, color: 'var(--txt3)', lineHeight: 1.5, padding: '8px 12px', background: 'var(--surface2)', borderRadius: 6, border: '1px solid var(--brd)' }}>
            <strong style={{ color: 'var(--accent)' }}>MEMORY.md</strong> — long-term agent memory, distilled weekly. Edit to add permanent notes the AI should always remember.
          </div>
          {settings.user_md && (
            <details style={{ fontSize: 11, color: 'var(--txt3)' }}>
              <summary style={{ cursor: 'pointer', color: 'var(--txt2)', fontWeight: 600 }}>USER.md (auto-synced, read-only)</summary>
              <pre style={{ marginTop: 8, padding: '10px', background: 'var(--surface2)', borderRadius: 6, border: '1px solid var(--brd)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.5 }}>{settings.user_md}</pre>
            </details>
          )}
          {settings.heartbeat_md && (
            <details style={{ fontSize: 11, color: 'var(--txt3)' }}>
              <summary style={{ cursor: 'pointer', color: 'var(--txt2)', fontWeight: 600 }}>HEARTBEAT.md (auto-synced, read-only)</summary>
              <pre style={{ marginTop: 8, padding: '10px', background: 'var(--surface2)', borderRadius: 6, border: '1px solid var(--brd)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.5 }}>{settings.heartbeat_md}</pre>
            </details>
          )}
          <div style={{ flex: 1 }}>
            <TextArea value={form.memory_md} onChange={v => onChange({ memory_md: v })} minHeight={240} placeholder="# MEMORY.md\nLong-term agent memory…" />
          </div>
          <SaveBar onSave={onSave} saving={saving} />
        </div>
      )}

      {tab === 'context' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1, overflowY: 'auto' }}>
          <div style={{ fontSize: 12, color: 'var(--txt3)', lineHeight: 1.5, padding: '8px 12px', background: 'var(--surface2)', borderRadius: 6, border: '1px solid var(--brd)' }}>
            <strong style={{ color: 'var(--accent)' }}>llm_context.md</strong> — injected into every AI call for this space. Use for persistent constraints, domain context, or personal preferences the AI should always apply.
          </div>
          <div style={{ flex: 1 }}>
            <TextArea
              value={form.llm_context}
              onChange={v => onChange({ llm_context: v })}
              minHeight={280}
              placeholder="e.g. I'm a BTech student. Focus on actionable insights. Use neuroscience lens when possible. Avoid verbose theory."
            />
          </div>
          <SaveBar onSave={onSave} saving={saving} />
        </div>
      )}

      {tab === 'files' && (
        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 14 }}>
          {Object.keys(settings.md_files || {}).length === 0
            ? <div style={{ color: 'var(--txt3)', fontSize: 13, padding: '24px 0', textAlign: 'center' }}>No files found in .spaces/</div>
            : Object.entries(settings.md_files).map(([fname, content]) => (
              <details key={fname} open={fname === 'directory_structure.md'}>
                <summary style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--accent)', cursor: 'pointer', fontFamily: 'var(--mono)', padding: '4px 0', userSelect: 'none' }}>{fname}</summary>
                <pre style={{ fontSize: 11, color: 'var(--txt2)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.5, margin: '6px 0 0', padding: '10px 12px', background: 'var(--surface2)', borderRadius: 6, border: '1px solid var(--brd)', maxHeight: 320, overflowY: 'auto' }}>{content}</pre>
              </details>
            ))}
        </div>
      )}
    </div>
  );
}
