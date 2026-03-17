/**
 * pages/Spaces.jsx — Router + SpaceHome + ChapterView + TopicView
 * SpacesList is extracted to pages/spaces/SpacesList.jsx
 * RoadmapBoard → pages/spaces/RoadmapBoard.jsx
 * CreateWizard  → pages/spaces/CreateWizard.jsx
 * Shared utils  → pages/spaces/shared.jsx
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../api';
import { fmt } from '../utils/format';
import { useStore } from '../store';
import { useResizable } from '../hooks/useResizable';
import Overlay from '../components/Overlay';
import Modal from '../components/Modal';
import MarkdownEditor from '../components/MarkdownEditor';
import DropdownMenu from '../components/DropdownMenu';
import PromptInline from '../components/PromptInline';
import { ExplainsTab, QuickTestTab, MediaRecorderTab, NotebookTab, PlaygroundTab } from '../sarthak/ConceptTabs';
import SettingsTabs from '../components/spaces/SpaceSettingsTabs';
import PanelHost from './SpacePanels';
import SpacesList from './spaces/SpacesList';
import RoadmapBoard from './spaces/RoadmapBoard';
import { SpaceGeneratingAnimation, generateTopicsAndConcepts, Reorderable } from './spaces/shared';

// ── Spaces Router ─────────────────────────────────────────────────────────────
export default function Spaces() {
  const { spacesView, currentSpace, currentChapter, currentTopic } = useStore();
  if (spacesView === 'home')    return <SpaceHome    key={currentSpace?.name} />;
  if (spacesView === 'chapter') return <ChapterView  key={currentChapter?.id} />;
  if (spacesView === 'topic')   return <TopicView    key={`${currentTopic?.id}-${currentTopic?._openConceptId}`} />;
  return <SpacesList />;
}

// ── Space Settings Overlay ────────────────────────────────────────────────────
function SpaceSettingsOverlay({ space, onClose, defaultTab }) {
  const [settings, setSettings] = useState(null);
  const [tab, setTab] = useState(defaultTab || 'config');
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({});
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const { ok, err, setSpacesView, setCurrentSpace, setSpaceRoadmap } = useStore();
  const sid = encodeURIComponent(space?.name || '');

  useEffect(() => {
    if (!space?.name) return;
    api(`/spaces/${sid}/settings`).then(s => {
      setSettings(s);
      setForm({ goal:s.goal||'',background:s.background||'',domain_name:s.domain||'',rag_enabled:s.rag_enabled||false,llm_context:s.llm_context||'',soul_md:s.soul_md||'',memory_md:s.memory_md||'',preferred_style:s.preferred_style||'visual + hands-on',daily_goal_minutes:s.daily_goal_minutes??30,is_technical:s.is_technical||false,mastered_concepts:s.mastered_concepts||[],struggling_concepts:s.struggling_concepts||[],badges:s.badges||[] });
    }).catch(()=>{});
  }, [space?.name, sid]);

  const save = async () => { setSaving(true); try { await api(`/spaces/${sid}/settings`,{method:'PATCH',body:JSON.stringify(form)}); ok('Settings saved'); } catch(e){err(e.message);} setSaving(false); };

  const regenRoadmap = async () => {
    if (!space?.directory||regenerating) return;
    setRegenerating(true);
    try { await api('/spaces/regenerate-roadmap',{method:'POST',body:JSON.stringify({directory:space.directory})}); setSpaceRoadmap(null); ok('Roadmap regeneration started — reload the space to see changes'); }
    catch(e){err(e.message);}
    setRegenerating(false);
  };

  const handleDelete = async () => {
    if (!space?.name||deleting) return;
    if (confirmText.trim()!==space.name){err('Please type the exact space name to confirm.');return;}
    setDeleting(true);
    try { await api('/spaces/delete',{method:'POST',body:JSON.stringify({directory:space.directory,name:space.name})}); ok('Space moved to trash'); setCurrentSpace(null); setSpaceRoadmap(null); setSpacesView('list'); onClose(); }
    catch(e){err(e.message);}
    finally{setDeleting(false);}
  };

  return (
    <Overlay title={`Settings — ${space?.name}`} onClose={onClose} width="700px" height="82%">
      {regenerating
        ? <div style={{ display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',height:'100%',gap:20 }}><SpaceGeneratingAnimation/><div style={{ fontSize:12,color:'var(--txt3)',textAlign:'center' }}>Rebuilding your roadmap…</div></div>
        : !settings ? <div className="loading-center"><span className="spin"/></div>
        : <SettingsTabs tab={tab} setTab={setTab} settings={settings} form={form} onChange={p=>setForm(f=>({...f,...p}))} onSave={save} saving={saving} onDelete={()=>setConfirmOpen(true)} onRegenerateRoadmap={regenRoadmap} regenerating={regenerating}/>}
      {confirmOpen && (
        <Modal title="Delete Space" onClose={()=>{if(!deleting){setConfirmOpen(false);setConfirmText('');} }}
          footer={<><button className="btn btn-muted btn-sm" onClick={()=>{setConfirmOpen(false);setConfirmText('');}} disabled={deleting}>Cancel</button><button className="btn btn-del btn-sm" onClick={handleDelete} disabled={deleting}>{deleting?'Deleting…':'Delete Space'}</button></>}>
          <div style={{ fontSize:12.5,color:'var(--txt2)',marginBottom:10 }}>Type the space name to confirm deletion:</div>
          <div style={{ fontSize:12,color:'var(--txt3)',marginBottom:10 }}><strong>{space?.name}</strong></div>
          <input className="s-input" value={confirmText} onChange={e=>setConfirmText(e.target.value)} placeholder="Enter space name exactly" autoFocus/>
        </Modal>
      )}
    </Overlay>
  );
}

// ── Space Home ────────────────────────────────────────────────────────────────
// ── WelcomeBanner — shown once after space creation (Fix 9) ──────────────────
function WelcomeBanner({ spaceName, firstConcept, onEnterConcept, onDismiss }) {
  return (
    <div style={{
      marginBottom: 16,
      padding: '14px 18px',
      background: 'linear-gradient(135deg, color-mix(in srgb, var(--accent) 8%, var(--surface)) 0%, var(--surface) 100%)',
      border: '1px solid var(--accent-border)',
      borderLeft: '3px solid var(--accent)',
      borderRadius: 10,
      display: 'flex',
      alignItems: 'flex-start',
      gap: 14,
      animation: 'ovFadeUp .4s ease both',
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 3 }}>Welcome to your space</div>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--txt)', marginBottom: 6 }}>Your roadmap has been personalised for <strong>{spaceName}</strong>.</div>
        <div style={{ fontSize: 12, color: 'var(--txt2)', lineHeight: 1.55 }}>
          Work through chapters in order — each one builds on the last. Use quicktests and notes to lock in understanding before moving on.
        </div>
        {firstConcept && (
          <button className="btn btn-accent btn-sm" style={{ marginTop: 10 }} onClick={onEnterConcept}>
            Start with: {firstConcept}
          </button>
        )}
      </div>
      <button className="btn btn-ghost btn-xs" style={{ flexShrink: 0, fontSize: 18, lineHeight: 1, padding: '0 2px', color: 'var(--txt3)' }} onClick={onDismiss} title="Dismiss">×</button>
    </div>
  );
}

function SpaceHome() {
  const { currentSpace, setCurrentSpace, spaceRoadmap, setSpaceRoadmap, setCurrentChapter, setCurrentTopic, setSpacesView, justCreatedSpace, clearJustCreatedSpace, ok, err } = useStore();
  const [hero, setHero] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [activePanel, setActivePanel] = useState(null);
  const [showHistory, setShowHistory] = useState(false);
  const [addingChapter, setAddingChapter] = useState(false);
  const [newChapterTitle, setNewChapterTitle] = useState('');
  const [newChapterDesc, setNewChapterDesc] = useState('');
  const [promptBar, setPromptBar] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [insightsPreview, setInsightsPreview] = useState(null);
  const sid = encodeURIComponent(currentSpace?.name || '');

  const loadHero = useCallback(async () => {
    if (!sid) return;
    try {
      const h = await api(`/spaces/${sid}/profile`);
      setHero(h);
      // Backfill space_type and domain into currentSpace if missing (registry gap)
      if (h && (!currentSpace?.space_type || !currentSpace?.domain)) {
        setCurrentSpace({
          ...currentSpace,
          space_type: h.space_type || currentSpace?.space_type || 'custom',
          domain:     h.domain     || currentSpace?.domain     || '',
        });
      }
    } catch {}
  }, [sid]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadRoadmap = useCallback(async () => {
    try { setSpaceRoadmap(await api(`/spaces/${sid}/roadmap`)); } catch {}
  }, [sid, setSpaceRoadmap]);

  const loadInsightsPreview = useCallback(async () => {
    try { const r=await api(`/spaces/${sid}/workspace/insights`); setInsightsPreview(r.has_content?r:null); } catch {}
  }, [sid]);

  useEffect(() => {
    if (!currentSpace) return;
    loadHero(); loadInsightsPreview();
  }, [currentSpace?.name, loadHero, loadInsightsPreview]);

  useEffect(() => {
    if (!currentSpace || spaceRoadmap) return;
    loadRoadmap();
  }, [currentSpace?.name, loadRoadmap, spaceRoadmap]);

  useEffect(() => {
    if (spaceRoadmap?.sessions) setSessions([...(spaceRoadmap.sessions)].reverse().slice(0,20));
  }, [spaceRoadmap?.sessions]);

  const patchChapters = async (chapters) => {
    const withOrder = chapters.map((c,i)=>({...c,order:i}));
    try { const rm=await api(`/spaces/${sid}/roadmap`,{method:'PATCH',body:JSON.stringify({chapters:withOrder})}); setSpaceRoadmap(rm); } catch(e){err(e.message);}
  };
  const patchChapter = async (ch) => { const chapters=(spaceRoadmap?.chapters||[]).map(c=>c.id===ch.id?ch:c); await patchChapters(chapters); };

  const addChapter = async () => {
    const title=newChapterTitle.trim(); if(!title) return;
    const ch={id:`ch_${Date.now().toString(36)}`,title,description:newChapterDesc.trim(),order:spaceRoadmap?.chapters?.length||0,status:'not_started',progress_pct:0,topics:[]};
    await patchChapters([...(spaceRoadmap?.chapters||[]),ch]);
    ok(`Chapter "${title}" added`); setNewChapterTitle(''); setNewChapterDesc(''); setAddingChapter(false);
  };

  const generateChapterTopics = async (chId,instruction='') => {
    const ch=(spaceRoadmap?.chapters||[]).find(c=>c.id===chId); if(!ch) return;
    ok('Generating topics and concepts…');
    try { await generateTopicsAndConcepts(sid,ch,instruction,patchChapter); ok('Topics generated successfully.'); }
    catch(e){err(e.message);}
  };

  const editChapterDescription = async (chId,next) => {
    const ch=(spaceRoadmap?.chapters||[]).find(c=>c.id===chId); if(!ch) return;
    await patchChapter({...ch,description:next.trim()}); ok('Description updated.');
  };

  if (!currentSpace) return null;

  const continueLearning = React.useMemo(()=>{
    if (!spaceRoadmap?.chapters) return null;
    const lastSession=sessions[0];
    if (lastSession?.concept) {
      for (const ch of spaceRoadmap.chapters) {
        for (const tp of ch.topics||[]) {
          const cn=(tp.concepts||[]).find(c=>c.title===lastSession.concept);
          if (cn){const cns=tp.concepts||[];const done=cns.filter(c=>c.status==='completed').length;return{chapter:ch,topic:tp,concept:lastSession.concept,pct:cns.length?Math.round((done/cns.length)*100):0};}
        }
      }
    }
    const inP=spaceRoadmap.chapters.find(c=>c.status==='in_progress');
    if (inP) return{chapter:inP,topic:null,concept:null,pct:inP.progress_pct||0};
    return null;
  },[spaceRoadmap?.chapters,sessions]);

  const goToContinue = () => {
    if (!continueLearning) return;
    setCurrentChapter({id:continueLearning.chapter.id,title:continueLearning.chapter.title,data:continueLearning.chapter});
    if (continueLearning.topic){setCurrentTopic({...continueLearning.topic,chapterId:continueLearning.chapter.id});setSpacesView('topic');}
    else setSpacesView('chapter');
  };

  const panels=[{id:'notes',label:'Notes'},{id:'tasks',label:'Tasks'},{id:'files',label:'Workspace'},{id:'srs',label:'SRS'},{id:'graph',label:'Graph'},{id:'digest',label:'Digest'},{id:'practice',label:'Practice'},{id:'optimizer',label:'Insights'},{id:'agents',label:'Agents'}];

  const progress=React.useMemo(()=>{
    const chs=spaceRoadmap?.chapters||[]; if(!chs.length) return 0;
    return Math.round(chs.reduce((a,c)=>a+(c.progress_pct||0),0)/chs.length);
  },[spaceRoadmap?.chapters]);

  const displayDomain=hero?.domain||currentSpace?.domain||(currentSpace?.space_type==='custom'?'':(currentSpace?.space_type||'').replace(/_/g,' '));

  return (
    <div className="page">
      {/* Page header */}
      <header className="pg-header">
        <div className="pg-title-group">
          <nav className="breadcrumb">
            <button className="bc-link" onClick={()=>setSpacesView('list')}>Spaces</button>
            <span className="bc-sep">›</span>
            <span className="bc-current">{currentSpace.name}</span>
          </nav>
          <div style={{ display:'flex',alignItems:'center',gap:10 }}>
            <h1 className="pg-title">{currentSpace.name}</h1>
            <button className="btn btn-muted btn-sm" style={{ fontSize:12,padding:'3px 10px' }} onClick={()=>setSettingsOpen(true)}>Settings</button>
          </div>
          {displayDomain && <p className="pg-sub">{displayDomain}</p>}
        </div>
        <div className="pg-actions" style={{ alignItems:'center',gap:14 }}>
          {/* Progress ring */}
          <div style={{ position:'relative',width:52,height:52,flexShrink:0 }}>
            <svg width="52" height="52" viewBox="0 0 52 52">
              <circle cx="26" cy="26" r="20" fill="none" stroke="var(--brd2)" strokeWidth="3"/>
              <circle cx="26" cy="26" r="20" fill="none" stroke="var(--accent)" strokeWidth="3"
                strokeDasharray={`${2*Math.PI*20}`}
                strokeDashoffset={`${2*Math.PI*20*(1-progress/100)}`}
                strokeLinecap="round"
                style={{ transform:'rotate(-90deg)',transformOrigin:'center',transition:'stroke-dashoffset 0.6s ease' }}/>
            </svg>
            <div style={{ position:'absolute',inset:0,display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center' }}>
              <span style={{ fontSize:11,fontWeight:700,color:'var(--txt)',lineHeight:1 }}>{progress}%</span>
            </div>
          </div>
          {/* Stats */}
          {hero && (
            <div style={{ display:'flex',gap:16,fontSize:12,color:'var(--txt2)' }}>
              <span><strong style={{ color:'var(--accent)' }}>{hero.xp||0}</strong> XP</span>
              <span><strong>{hero.streak_days||0}d</strong> streak</span>
              <span><strong>{hero.session_count||hero.total_sessions||0}</strong> sessions</span>
            </div>
          )}
          {/* Panel buttons */}
          <div style={{ display:'flex',gap:4,flexWrap:'wrap' }}>
            {panels.map(p=>(
              <button key={p.id} className={`btn btn-muted btn-sm${p.id==='optimizer'&&insightsPreview?' btn-accent':''}`}
                style={{ padding:'4px 10px',fontSize:11.5 }}
                onClick={()=>setActivePanel({name:p.id,props:{}})}>
                {p.label}{p.id==='optimizer'&&insightsPreview&&<span style={{ width:5,height:5,borderRadius:'50%',background:'currentColor',display:'inline-block',marginLeft:5,verticalAlign:'middle',opacity:.8 }}/>}
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="pg-body">
        {/* Welcome banner — shown once after space creation */}
        {justCreatedSpace === currentSpace?.name && (
          <WelcomeBanner
            spaceName={currentSpace.name}
            firstConcept={spaceRoadmap?.chapters?.[0]?.topics?.[0]?.concepts?.[0]?.title || null}
            onEnterConcept={() => {
              clearJustCreatedSpace();
              const ch = spaceRoadmap?.chapters?.[0];
              const tp = ch?.topics?.[0];
              if (ch && tp) { setCurrentChapter({ id: ch.id, title: ch.title, data: ch }); setCurrentTopic({ ...tp, chapterId: ch.id }); setSpacesView('topic'); }
            }}
            onDismiss={clearJustCreatedSpace}
          />
        )}
        {/* Insights preview */}
        {insightsPreview && (
          <div style={{ marginBottom:16,padding:'10px 16px',background:'var(--surface)',border:'1px solid var(--accent-border)',borderRadius:10,borderLeft:'3px solid var(--accent)',cursor:'pointer',transition:'background 0.15s' }}
            onClick={()=>setActivePanel({name:'optimizer',props:{}})}
            onMouseEnter={e=>e.currentTarget.style.background='var(--accent-dim)'}
            onMouseLeave={e=>e.currentTarget.style.background='var(--surface)'}>
            <div style={{ display:'flex',alignItems:'center',gap:10 }}>
              <span style={{ fontSize:14 }}>⚡</span>
              <div style={{ flex:1,minWidth:0 }}>
                <div style={{ fontSize:10,fontWeight:700,color:'var(--accent)',textTransform:'uppercase',letterSpacing:'.06em',marginBottom:2 }}>Workspace Insights</div>
                <div style={{ fontSize:12,color:'var(--txt2)',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap' }}>
                  {insightsPreview.content?.split('\n').find(l=>l.trim()&&!l.startsWith('#'))?.trim()?.slice(0,120)||'View workspace analysis and recommendations'}
                </div>
              </div>
              <span style={{ color:'var(--accent)',fontSize:13,flexShrink:0 }}>View →</span>
            </div>
          </div>
        )}

        {/* Continue learning strip */}
        {continueLearning && (
          <div onClick={goToContinue} style={{ display:'flex',alignItems:'center',gap:14,padding:'10px 16px',marginBottom:16,background:'var(--surface)',border:'1px solid var(--accent-border)',borderRadius:10,cursor:'pointer',transition:'background 0.15s' }}
            onMouseEnter={e=>e.currentTarget.style.background='var(--accent-dim)'}
            onMouseLeave={e=>e.currentTarget.style.background='var(--surface)'}>
            <div style={{ flex:1,minWidth:0 }}>
              <div style={{ fontSize:10,color:'var(--accent)',fontWeight:700,letterSpacing:'0.05em',textTransform:'uppercase',marginBottom:2 }}>Continue Learning</div>
              <div style={{ fontSize:13,fontWeight:600,color:'var(--txt)',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap' }}>
                {continueLearning.topic?.title||continueLearning.chapter.title}
                {continueLearning.concept&&<span style={{ fontSize:11,color:'var(--txt3)',marginLeft:8 }}>— {continueLearning.concept}</span>}
              </div>
            </div>
            <div style={{ display:'flex',alignItems:'center',gap:8,flexShrink:0 }}>
              <span style={{ fontSize:12,color:'var(--txt2)' }}>{continueLearning.pct}%</span>
              <div style={{ width:56,height:3,background:'var(--surface2)',borderRadius:2,overflow:'hidden' }}>
                <div style={{ width:`${continueLearning.pct}%`,height:'100%',background:'var(--accent)',borderRadius:2 }}/>
              </div>
              <span style={{ color:'var(--accent)',fontSize:14 }}>→</span>
            </div>
          </div>
        )}

        {/* Roadmap section */}
        <div className="card">
          <div className="card-hdr">
            <span>Roadmap</span>
            <div style={{ display:'flex',gap:6,alignItems:'center' }}>
              {addingChapter ? (
                <>
                  <input className="s-input" style={{ width:180,fontSize:12,padding:'3px 8px' }} autoFocus value={newChapterTitle} onChange={e=>setNewChapterTitle(e.target.value)}
                    onKeyDown={e=>{if(e.key==='Enter')addChapter();if(e.key==='Escape'){setAddingChapter(false);setNewChapterTitle('');setNewChapterDesc('');}}} placeholder="Chapter title…"/>
                  <input className="s-input" style={{ width:220,fontSize:12,padding:'3px 8px' }} value={newChapterDesc} onChange={e=>setNewChapterDesc(e.target.value)} placeholder="Short description…"/>
                  <button className="btn btn-accent btn-sm" onClick={addChapter}>Add</button>
                  <button className="btn btn-muted btn-sm" onClick={()=>{setAddingChapter(false);setNewChapterTitle('');setNewChapterDesc('');}}>Cancel</button>
                </>
              ) : (
                <>
                  <button className="btn btn-muted btn-xs" onClick={()=>setShowHistory(true)}>History</button>
                  <button className="btn btn-muted btn-xs" onClick={()=>setAddingChapter(true)}>+ Chapter</button>
                </>
              )}
            </div>
          </div>
          <div className="card-body" style={{ padding:'14px 16px' }}>
            {promptBar?.type==='chapter_generate' && (
              <PromptInline title={`Generate topics for: ${promptBar.title}`} value={promptBar.value}
                onChange={v=>setPromptBar(p=>({...p,value:v}))}
                onSubmit={async()=>{const p=promptBar;setPromptBar(null);await generateChapterTopics(p.chId,p.value||'');}}
                onCancel={()=>setPromptBar(null)} placeholder="Optional instructions…" submitLabel="Generate" multiline/>
            )}
            {promptBar?.type==='chapter_desc' && (
              <PromptInline title={`Edit description: ${promptBar.title}`} value={promptBar.value}
                onChange={v=>setPromptBar(p=>({...p,value:v}))}
                onSubmit={async()=>{const p=promptBar;setPromptBar(null);await editChapterDescription(p.chId,p.value||'');}}
                onCancel={()=>setPromptBar(null)} placeholder="Short description…" submitLabel="Save" multiline={false}/>
            )}
            <RoadmapBoard roadmap={spaceRoadmap}
              onChapterClick={chData=>{setCurrentChapter({id:chData.id,title:chData.title,data:chData});setSpacesView('chapter');}}
              onAddChapter={()=>setAddingChapter(true)} onPatchChapters={patchChapters}
              onGenerateChapter={chId=>{const ch=(spaceRoadmap?.chapters||[]).find(c=>c.id===chId);if(!ch)return;setPromptBar({type:'chapter_generate',chId,title:ch.title,value:''}); }}
              onEditChapterDesc={chId=>{const ch=(spaceRoadmap?.chapters||[]).find(c=>c.id===chId);if(!ch)return;setPromptBar({type:'chapter_desc',chId,title:ch.title,value:ch.description||''}); }}/>
          </div>
        </div>
      </div>

      {activePanel && <PanelHost panel={activePanel} onClose={()=>setActivePanel(null)} space={currentSpace} spaceId={sid} spaceRoadmap={spaceRoadmap} refreshHero={loadHero}/>}
      {settingsOpen && <SpaceSettingsOverlay space={currentSpace} onClose={()=>setSettingsOpen(false)}/>}

      {showHistory && (
        <Overlay title="Session History" onClose={()=>setShowHistory(false)} width="520px" height="65%">
          {sessions.length===0 ? <div style={{ color:'var(--txt3)',fontSize:13,padding:'32px 0',textAlign:'center' }}>No sessions yet.</div>
          : <div style={{ display:'flex',flexDirection:'column',gap:6 }}>
            {sessions.map((s,i)=>{
              const goTo=()=>{
                if(!spaceRoadmap?.chapters) return;
                for (const ch of spaceRoadmap.chapters){for (const tp of ch.topics||[]){const cn=(tp.concepts||[]).find(c=>c.title===s.concept);if(cn){setCurrentChapter({id:ch.id,title:ch.title,data:ch});setCurrentTopic({...tp,chapterId:ch.id,_openConceptId:cn.id});setSpacesView('topic');setShowHistory(false);return;}}}
              };
              return (
                <div key={i} onClick={goTo} style={{ display:'flex',justifyContent:'space-between',alignItems:'center',padding:'10px 14px',borderRadius:8,cursor:'pointer',border:'1px solid var(--brd)',background:'var(--surface)',transition:'background 0.12s' }}
                  onMouseEnter={e=>e.currentTarget.style.background='var(--surface2)'}
                  onMouseLeave={e=>e.currentTarget.style.background='var(--surface)'}>
                  <div style={{ minWidth:0 }}>
                    <div style={{ fontSize:13,fontWeight:600,color:'var(--txt)',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap' }}>{s.concept||'Session'}</div>
                    <div style={{ fontSize:11,color:'var(--txt3)',marginTop:2 }}>{fmt(s.timestamp||s.ts)}</div>
                  </div>
                  <div style={{ textAlign:'right',flexShrink:0,marginLeft:12 }}>
                    {s.xp_earned?<div style={{ fontSize:11,color:'var(--accent)',fontWeight:600 }}>+{s.xp_earned} XP</div>:null}
                    {s.level?<div style={{ fontSize:11,color:'var(--txt3)' }}>{s.level}</div>:null}
                  </div>
                </div>
              );
            })}
          </div>}
        </Overlay>
      )}
    </div>
  );
}

// ── Chapter View ──────────────────────────────────────────────────────────────
function ChapterView() {
  const { currentSpace,currentChapter,setCurrentChapter,setCurrentTopic,setSpacesView,setSpaceRoadmap,spaceRoadmap,ok,err } = useStore();
  const [noteVal,setNoteVal]=useState('');const [noteId,setNoteId]=useState(null);const [tab,setTab]=useState('topics');
  const [addingTopic,setAddingTopic]=useState(false);const [newTopicTitle,setNewTopicTitle]=useState('');const [promptBar,setPromptBar]=useState(null);
  const spaceId=encodeURIComponent(currentSpace?.name||'');const noteKey=`notes:${currentSpace?.name}:${currentChapter?.id}`;

  useEffect(()=>{
    setNoteVal(localStorage.getItem(noteKey)||'');setNoteId(null);
    if(!spaceId||!currentChapter?.id)return;let cancelled=false;
    api(`/spaces/${spaceId}/notes?type=chapter_note&concept_id=${encodeURIComponent(currentChapter.id)}`).then(r=>{if(cancelled)return;const list=Array.isArray(r)?r:r.notes||[];if(list.length){setNoteVal(list[0].body_md||'');setNoteId(list[0].id);}}).catch(()=>{});
    return()=>{cancelled=true;};
  },[noteKey,spaceId,currentChapter?.id]);

  const getChapter=()=>(spaceRoadmap?.chapters||[]).find(c=>c.id===currentChapter?.id)||currentChapter?.data||{};

  const patchRoadmapChapter=async(updatedChapter)=>{
    const chapters=(spaceRoadmap?.chapters||[]).map(c=>c.id===updatedChapter.id?updatedChapter:c);
    const withOrder=chapters.map((c,i)=>({...c,order:i}));
    try{const rm=await api(`/spaces/${spaceId}/roadmap`,{method:'PATCH',body:JSON.stringify({chapters:withOrder})});setSpaceRoadmap(rm);setCurrentChapter(prev=>({...prev,title:updatedChapter.title,data:updatedChapter}));}catch{}
  };

  const addTopic=async()=>{const title=newTopicTitle.trim();if(!title)return;const ch=getChapter();await patchRoadmapChapter({...ch,topics:[...(ch.topics||[]),{id:`tp_${Date.now().toString(36)}`,title,order:(ch.topics||[]).length,concepts:[]}]});setNewTopicTitle('');setAddingTopic(false);};

  const generateTopics=async(instruction='')=>{const ch=getChapter();ok('Generating topics and concepts…');try{await generateTopicsAndConcepts(spaceId,ch,instruction,updatedChapter=>patchRoadmapChapter(updatedChapter));ok('Topics generated.');}catch(e){err(e.message);}};

  const generateConcepts=async(tpId,instruction='')=>{
    try{ok('Generating concepts…');const ch=getChapter();const topic=(ch.topics||[]).find(t=>t.id===tpId);if(!topic)return;
    const r=await api(`/spaces/${spaceId}/roadmap/generate-children`,{method:'POST',body:JSON.stringify({parent_type:'topic',parent_title:topic.title,instruction:instruction.trim()})});
    const newConcepts=(r.children||[]).map((cTitle,i)=>({id:`cn_${Date.now().toString(36)}_${i}`,title:cTitle,description:'',status:'not_started',order:(topic.concepts||[]).length+i,tags:[],related_concepts:[],notes:[],quicktests:[]}));
    await patchRoadmapChapter({...ch,topics:(ch.topics||[]).map(t=>t.id!==tpId?t:{...t,concepts:[...(t.concepts||[]),...newConcepts]})});ok('Concepts generated.');}catch(e){err(e.message);}
  };

  const saveNotes=async(val)=>{localStorage.setItem(noteKey,val);try{if(noteId){await api(`/spaces/${spaceId}/notes/${noteId}`,{method:'PUT',body:JSON.stringify({title:`Chapter: ${currentChapter?.title||''}`,body_md:val})});}else{const saved=await api(`/spaces/${spaceId}/notes`,{method:'POST',body:JSON.stringify({type:'chapter_note',concept_id:currentChapter?.id||'',title:`Chapter: ${currentChapter?.title||''}`,body_md:val})});if(saved?.id)setNoteId(saved.id);}}catch{}ok(`Notes saved (${val.trim().split(/\s+/).filter(Boolean).length}w)`);};

  const topics=getChapter().topics||[];if(!currentChapter)return null;
  return(
    <div className="page">
      <header className="pg-header">
        <div className="pg-title-group">
          <nav className="breadcrumb"><button className="bc-link" onClick={()=>setSpacesView('list')}>Spaces</button><span className="bc-sep">›</span><button className="bc-link" onClick={()=>setSpacesView('home')}>{currentSpace?.name}</button><span className="bc-sep">›</span><span className="bc-current">{currentChapter.title}</span></nav>
          <h1 className="pg-title">{currentChapter.title}</h1>
        </div>
        <div className="pg-actions"><button className="btn btn-muted btn-sm" onClick={()=>setSpacesView('home')}>Back</button></div>
      </header>
      <div style={{ flex:1,display:'flex',flexDirection:'column',overflow:'hidden' }}>
        <div className="tab-bar" style={{ padding:'0 24px' }}>
          {['topics','notes','sessions'].map(t=><button key={t} className={`tab-btn${tab===t?' active':''}`} onClick={()=>setTab(t)}>{t.charAt(0).toUpperCase()+t.slice(1)}</button>)}
          {tab==='topics'&&<><button className="btn btn-muted btn-sm" style={{ marginLeft:'auto' }} onClick={()=>setPromptBar({type:'topic_generate',value:''})}>Generate (LLM)</button><button className="btn btn-accent btn-sm" onClick={()=>setAddingTopic(true)}>+ Topic</button></>}
        </div>
        <div style={{ flex:1,overflowY:'auto',padding:24,background:'var(--surface2)' }}>
          {promptBar?.type==='topic_generate'&&<PromptInline title={`Generate topics for: ${currentChapter.title}`} value={promptBar.value} onChange={v=>setPromptBar(p=>({...p,value:v}))} onSubmit={async()=>{const p=promptBar;setPromptBar(null);await generateTopics(p.value||'');}} onCancel={()=>setPromptBar(null)} placeholder="Optional instructions…" submitLabel="Generate" multiline/>}
          {promptBar?.type==='concept_generate'&&<PromptInline title={`Generate concepts for: ${promptBar.title}`} value={promptBar.value} onChange={v=>setPromptBar(p=>({...p,value:v}))} onSubmit={async()=>{const p=promptBar;setPromptBar(null);await generateConcepts(p.tpId,p.value||'');}} onCancel={()=>setPromptBar(null)} placeholder="Optional instructions…" submitLabel="Generate" multiline/>}
          {addingTopic&&<div style={{ padding:16,marginBottom:24,background:'var(--surface)',borderRadius:8,border:'1px solid var(--brd)',display:'flex',gap:6,flexWrap:'wrap' }}>
            <input className="s-input" style={{ fontSize:13,padding:'6px 10px',flex:1 }} autoFocus value={newTopicTitle} onChange={e=>setNewTopicTitle(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')addTopic();if(e.key==='Escape'){setAddingTopic(false);setNewTopicTitle('');}}} placeholder="Topic title…"/>
            <button className="btn btn-accent" onClick={addTopic}>Add Topic</button>
            <button className="btn btn-muted" onClick={()=>{setAddingTopic(false);setNewTopicTitle('');}}>Cancel</button>
          </div>}
          {tab==='topics'&&(
            <div style={{ display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(320px,1fr))',gap:24 }}>
              {topics.length===0?<div style={{ color:'var(--txt3)',fontSize:13,gridColumn:'1/-1' }}>No topics yet.</div>
              :<Reorderable items={topics} itemKey={tp=>tp.id} colKey="topics"
                  onReorder={async(ts)=>{const ch=getChapter();await patchRoadmapChapter({...ch,topics:ts.map((t,i)=>({...t,order:i}))});}}
                  renderItem={tp=><TopicCard topic={tp} onOpen={()=>{setCurrentTopic({...tp,chapterId:currentChapter.id});setSpacesView('topic');}}
                    onDelete={async()=>{if(!confirm('Delete topic?'))return;const ch=getChapter();await patchRoadmapChapter({...ch,topics:(ch.topics||[]).filter(t=>t.id!==tp.id).map((t,i)=>({...t,order:i}))});}}
                    onGenerate={()=>setPromptBar({type:'concept_generate',tpId:tp.id,title:tp.title,value:''})}/>}/>}
            </div>
          )}
          {tab==='notes'&&<div style={{ background:'var(--surface)',borderRadius:8,border:'1px solid var(--brd)',overflow:'hidden',height:'100%',minHeight:400 }}><MarkdownEditor value={noteVal} onChange={setNoteVal} onSave={saveNotes} placeholder={`Write chapter notes for ${currentChapter.title}…`} historyKey={noteKey}/></div>}
          {tab==='sessions'&&<div style={{ background:'var(--surface)',borderRadius:8,padding:16,border:'1px solid var(--brd)',color:'var(--txt3)',fontSize:13 }}>No sessions yet for this chapter.</div>}
        </div>
      </div>
    </div>
  );
}

function TopicCard({topic:tp,onOpen,onDelete,onGenerate}){
  const concepts=tp.concepts||[];const completed=concepts.filter(c=>c.status==='completed').length;
  const progressPct=concepts.length?Math.round((completed/concepts.length)*100):0;
  const testsTaken=concepts.reduce((sum,c)=>sum+((c.quicktests||[]).length),0);
  const testedConcepts=concepts.filter(c=>(c.quicktests||[]).length>0).length;
  const coveragePct=concepts.length?Math.round((testedConcepts/concepts.length)*100):0;
  const topicNum = (tp.order ?? 0) + 1;
  return(
    <div className="lift" onClick={onOpen} style={{ background:'var(--surface)',borderRadius:12,padding:20,border:'1px solid var(--brd)',cursor:'pointer',display:'flex',flexDirection:'column',gap:14,boxShadow:'var(--shadow-sm)',minHeight:180 }}>
      <div style={{ display:'flex',justifyContent:'space-between',alignItems:'flex-start' }}>
        <div style={{ flex:1,minWidth:0 }}>
          <div style={{ fontSize:10,fontWeight:700,color:'var(--txt3)',letterSpacing:'.05em',textTransform:'uppercase',marginBottom:3 }}>Topic {topicNum}</div>
          <h3 style={{ margin:0,fontSize:15,color:'var(--txt)',fontWeight:650,lineHeight:1.3 }}>{tp.title}</h3>
        </div>
        <div onClick={e=>e.stopPropagation()}>
          <DropdownMenu trigger={<button className="btn btn-ghost btn-xs" style={{ padding:'2px 6px' }}>⋮</button>}
            items={[{label:'Generate Concepts (LLM)',onClick:onGenerate},{label:'Delete Topic',danger:true,onClick:onDelete}]}/>
        </div>
      </div>
      <div>
        <div style={{ display:'flex',justifyContent:'space-between',fontSize:11,marginBottom:5,color:'var(--txt3)' }}>
          <span style={{ fontWeight:600,color:'var(--accent)',textTransform:'uppercase',letterSpacing:'0.05em' }}>Concepts</span>
          <span>{completed} / {concepts.length} done</span>
        </div>
        <div className="prog"><div className="prog-fill" style={{ width:`${progressPct}%` }}/></div>
      </div>
      <div style={{ display:'flex',gap:6,flexWrap:'wrap' }}>
        <span className="badge badge-muted">Tests: {testsTaken}</span>
        <span className="badge badge-muted">Coverage: {coveragePct}%</span>
      </div>
      <div style={{ fontSize:12,color:'var(--txt3)',display:'-webkit-box',WebkitLineClamp:2,WebkitBoxOrient:'vertical',overflow:'hidden' }}>
        {concepts.length===0?<span style={{ fontStyle:'italic' }}>No concepts yet.</span>
         :concepts.map((c,i)=><span key={c.id}><span style={{ color:'var(--txt3)',opacity:.5 }}>{i+1}.</span> {c.title}{i<concepts.length-1?<span style={{ opacity:.3 }}> · </span>:''}</span>)}
      </div>
    </div>
  );
}

// ── Concept sidebar header: count + filter + inline add ───────────────────────
function ConceptSidebarHeader({ concepts, cnSearch, setCnSearch, onAdd }) {
  const [adding, setAdding] = useState(false);
  const [val, setVal] = useState('');
  const commit = () => { onAdd(val); setVal(''); setAdding(false); };
  return (
    <>
      <div className="card-hdr" style={{ padding:'8px 10px 8px 12px' }}>
        <span>Concepts <span style={{ color:'var(--txt3)',fontWeight:400,fontSize:10 }}>{concepts.length}</span></span>
        <button className="btn btn-ghost btn-xs" title="Add concept" onClick={()=>setAdding(a=>!a)}
          style={{ fontSize:16,lineHeight:1,padding:'0 4px',color: adding ? 'var(--accent)' : 'var(--txt3)' }}>+</button>
      </div>
      {adding && (
        <div style={{ padding:'6px 8px',borderBottom:'1px solid var(--brd)',flexShrink:0,display:'flex',gap:4 }}>
          <input className="s-input" style={{ fontSize:12,padding:'4px 8px',flex:1 }} autoFocus
            value={val} onChange={e=>setVal(e.target.value)} placeholder="Concept title…"
            onKeyDown={e=>{ if(e.key==='Enter')commit(); if(e.key==='Escape'){setAdding(false);setVal('');} }}/>
          <button className="btn btn-accent btn-xs" onClick={commit}>Add</button>
        </div>
      )}
      <div style={{ padding:'6px 8px',borderBottom:'1px solid var(--brd)',flexShrink:0 }}>
        <input className="s-input" style={{ fontSize:12,padding:'4px 8px' }} placeholder="Filter…"
          value={cnSearch} onChange={e=>setCnSearch(e.target.value)}/>
      </div>
    </>
  );
}

// ── Topic View ────────────────────────────────────────────────────────────────
function TopicView(){
  const{currentSpace,currentChapter,currentTopic,setCurrentTopic,setSpaceRoadmap,spaceRoadmap,setSpacesView,ok,err}=useStore();
  const[tab,setTab]=useState('notes');const[activeCn,setActiveCn]=useState(null);const[noteVal,setNoteVal]=useState('');
  const[editingCnId,setEditingCnId]=useState(null);const[cnSearch,setCnSearch]=useState('');
  const editInputRef=useRef(null);useEffect(()=>{if(editingCnId&&editInputRef.current)editInputRef.current.focus();},[editingCnId]);
  const[sidebarWidth,onSidebarDrag]=useResizable('topic-sidebar-width',260,160,480);
  const spaceId=encodeURIComponent(currentSpace?.name||'');
  const noteKey=(cnId)=>`notes:${currentSpace?.name}:topic:${currentTopic?.id}:${cnId||'__topic__'}`;
  const[noteIdMap,setNoteIdMap]=useState({});

  const loadConceptNote=async(cnId)=>{
    setNoteVal(localStorage.getItem(noteKey(cnId))||'');if(!spaceId)return;
    try{const cid=cnId||currentTopic?.id||'';const r=await api(`/spaces/${spaceId}/notes?type=concept_note&concept_id=${encodeURIComponent(cid)}`);const list=Array.isArray(r)?r:r.notes||[];if(list.length){setNoteVal(list[0].body_md||'');setNoteIdMap(m=>({...m,[cid]:list[0].id}));}}catch{}
  };

  useEffect(()=>{const openCn=currentTopic?._openConceptId||null;setActiveCn(openCn);setTab(currentTopic?._openTab||'notes');loadConceptNote(openCn);setCnSearch('');// eslint-disable-next-line react-hooks/exhaustive-deps
  },[currentTopic?.id,currentTopic?._openConceptId]);

  if(!currentTopic)return null;
  const concepts=currentTopic.concepts||[];const sid=encodeURIComponent(currentSpace?.name||'');

  const patchTopic=async(updatedConcepts)=>{
    const updatedTopic={...currentTopic,concepts:updatedConcepts};
    const liveChapter=(spaceRoadmap?.chapters||[]).find(c=>c.id===currentChapter.id)||{};
    const updatedChapter={...liveChapter,topics:(liveChapter.topics||[]).map(t=>t.id===currentTopic.id?updatedTopic:t)};
    const chapters=(spaceRoadmap?.chapters||[]).map(c=>c.id===updatedChapter.id?updatedChapter:c);
    try{const rm=await api(`/spaces/${sid}/roadmap`,{method:'PATCH',body:JSON.stringify({chapters})});setSpaceRoadmap(rm);setCurrentTopic(updatedTopic);}catch(e){err(e.message);}
  };

  const saveNotes=async(val)=>{const cid=activeCn||currentTopic?.id||'';localStorage.setItem(noteKey(activeCn),val);try{const existingId=noteIdMap[cid];const cnTitle=concepts.find(c=>c.id===activeCn)?.title||currentTopic?.title||'';if(existingId){await api(`/spaces/${spaceId}/notes/${existingId}`,{method:'PUT',body:JSON.stringify({title:`Notes: ${cnTitle}`,body_md:val})});}else{const saved=await api(`/spaces/${spaceId}/notes`,{method:'POST',body:JSON.stringify({type:'concept_note',concept_id:cid,title:`Notes: ${cnTitle}`,body_md:val})});if(saved?.id)setNoteIdMap(m=>({...m,[cid]:saved.id}));}}catch{}ok(`Notes saved (${val.trim().split(/\s+/).filter(Boolean).length}w)`);};

  const importConceptDocument=async(file,mode='vision')=>{if(!file)return;try{const form=new FormData();form.append('file',file);const res=await fetch(`/api/spaces/${spaceId}/notes/import?concept_id=${encodeURIComponent(activeCn)}&ocr_mode=${encodeURIComponent(mode)}`,{method:'POST',body:form});if(!res.ok){let msg=`HTTP ${res.status}`;try{msg=(await res.json()).detail||msg;}catch{}throw new Error(msg);}const data=await res.json().catch(()=>({}));const md=(data.markdown||'').trim();if(!md){err('No content extracted.');return;}setNoteVal(prev=>prev?`${prev.trim()}\n\n${md}`:md);ok('Document converted to markdown.');}catch(e){err(e.message);}};

  const reorder=arr=>arr.map((x,i)=>({...x,order:i}));
  const markConceptStatus=async(cnId,status)=>{try{await patchTopic(concepts.map(cn=>cn.id===cnId?{...cn,status}:cn));ok(status==='completed'?'Marked complete':'Status updated');}catch{}};
  const renameConcept=async(cnId,title)=>{try{await patchTopic(concepts.map(cn=>cn.id===cnId?{...cn,title}:cn));ok('Renamed');}catch{err('Failed');}setEditingCnId(null);};
  const deleteConcept=async(cnId)=>{if(!confirm('Delete this concept?'))return;try{await patchTopic(reorder(concepts.filter(cn=>cn.id!==cnId)));if(activeCn===cnId)setActiveCn(null);ok('Deleted');}catch{err('Failed');}};  
  const addConcept=async(title)=>{const t=title.trim();if(!t)return;const newCn={id:`cn_${Date.now().toString(36)}`,title:t,description:'',status:'not_started',order:concepts.length,tags:[],related_concepts:[],notes:[],quicktests:[]};try{await patchTopic(reorder([...concepts,newCn]));ok(`Concept "${t}" added`);}catch(e){err(e.message);}};

  useEffect(()=>{let el=document.getElementById('__sarthak_space');if(!el){el=document.createElement('div');el.id='__sarthak_space';el.style.display='none';document.body.appendChild(el);}el.dataset.id=sid;return()=>{el.dataset.id='';};}, [sid]);

  const TABS=['notes','explains','quicktest','recordings','notebook','playground'];
  return(
    <div className="page">
      <header className="pg-header">
        <div className="pg-title-group">
          <nav className="breadcrumb">
            <button className="bc-link" onClick={()=>setSpacesView('list')}>Spaces</button><span className="bc-sep">›</span>
            <button className="bc-link" onClick={()=>setSpacesView('home')}>{currentSpace?.name}</button><span className="bc-sep">›</span>
            <button className="bc-link" onClick={()=>setSpacesView('chapter')}>{currentChapter?.title||'Chapter'}</button><span className="bc-sep">›</span>
            <span className="bc-current">{currentTopic.title}</span>
          </nav>
          <h1 className="pg-title">{currentTopic.title}</h1>
          <p className="pg-sub">{concepts.length} concepts</p>
        </div>
        <div className="pg-actions">
          <button className="btn btn-muted btn-sm" onClick={()=>setSpacesView('chapter')}>Back</button>
          <button className="btn btn-accent btn-sm" onClick={()=>setTab('quicktest')}>QuickTest</button>
        </div>
      </header>
      <div style={{ flex:1,display:'flex',overflow:'hidden',minHeight:0 }}>
        {/* Concept sidebar */}
        <div style={{ width:sidebarWidth,flexShrink:0,display:'flex',flexDirection:'column',borderRight:'1px solid var(--brd)',background:'var(--surface)',overflow:'hidden',position:'relative' }}>
          <ConceptSidebarHeader concepts={concepts} cnSearch={cnSearch} setCnSearch={setCnSearch} onAdd={addConcept}/>
          <div onMouseDown={onSidebarDrag} style={{ position:'absolute',right:0,top:0,bottom:0,width:5,cursor:'col-resize',zIndex:10 }} onMouseEnter={e=>e.currentTarget.style.background='var(--accent-border)'} onMouseLeave={e=>e.currentTarget.style.background='transparent'}/>
          <div style={{ flex:1,overflowY:'auto',padding:'6px',display:'flex',flexDirection:'column',gap:2 }}>
            {/* All-topics row (no serial, no drag) */}
            {(()=>{const cn={id:null,title:`All — ${currentTopic.title.slice(0,18)}`};return(
              <div style={{ display:'flex',alignItems:'center',borderRadius:6,background:activeCn===null?'var(--accent-dim)':'transparent',border:`1px solid ${activeCn===null?'var(--accent-border)':'transparent'}`,transition:'background 120ms' }}>
                <button onClick={()=>{setActiveCn(null);loadConceptNote(null);}} style={{ flex:1,textAlign:'left',background:'transparent',border:'none',padding:'7px 10px',cursor:'pointer',color:'var(--txt2)',fontSize:12.5,fontWeight:600,fontFamily:'var(--font)' }}>{cn.title}</button>
              </div>
            );})()}
            {/* Draggable concept rows */}
            <Reorderable
              items={concepts.filter(cn=>!cnSearch.trim()||cn.title.toLowerCase().includes(cnSearch.toLowerCase()))}
              itemKey={cn=>cn.id}
              colKey="concepts"
              onReorder={async(reordered)=>{
                // merge reordered back into full concepts list preserving non-visible items
                const ids=new Set(reordered.map(c=>c.id));
                const others=concepts.filter(c=>!ids.has(c.id));
                await patchTopic(reorder([...reordered,...others]));
              }}
              renderItem={cn=>{
                const conceptIdx=concepts.findIndex(c=>c.id===cn.id);
                const serialNum=(concepts[conceptIdx]?.order??conceptIdx)+1;
                return(
                  <div style={{ display:'flex',alignItems:'center',borderRadius:6,background:activeCn===cn.id?'var(--accent-dim)':'transparent',border:`1px solid ${activeCn===cn.id?'var(--accent-border)':'transparent'}`,transition:'background 120ms' }}>
                    {editingCnId===cn.id
                      ?<input ref={editInputRef} defaultValue={cn.title} onBlur={e=>renameConcept(cn.id,e.target.value.trim()||cn.title)} onKeyDown={e=>{if(e.key==='Enter')renameConcept(cn.id,e.target.value.trim()||cn.title);if(e.key==='Escape')setEditingCnId(null);}} style={{ flex:1,fontSize:12.5,padding:'6px 10px',background:'var(--surface2)',border:'1px solid var(--accent-border)',borderRadius:5,color:'var(--txt)',fontFamily:'var(--font)',outline:'none' }} onClick={e=>e.stopPropagation()}/>
                      :<button onClick={()=>{setActiveCn(cn.id);loadConceptNote(cn.id);}} style={{ flex:1,textAlign:'left',background:'transparent',border:'none',padding:'7px 10px',cursor:'pointer',color:'var(--txt2)',fontSize:12.5,fontWeight:500,fontFamily:'var(--font)',display:'flex',alignItems:'baseline',gap:5 }}>
                        <span style={{ fontSize:10,fontWeight:700,color:'var(--txt3)',opacity:.6,minWidth:16,flexShrink:0 }}>{serialNum}.</span>
                        <span>{cn.title}</span>
                      </button>}
                    <div style={{ flexShrink:0,paddingRight:4,display:'flex',alignItems:'center',gap:2 }} onClick={e=>e.stopPropagation()}>
                      <button title={cn.status==='completed'?'Mark in progress':'Mark complete'} onClick={()=>markConceptStatus(cn.id,cn.status==='completed'?'in_progress':'completed')} style={{ background:'transparent',border:'none',cursor:'pointer',padding:'2px 4px',color:cn.status==='completed'?'var(--accent)':'var(--txt3)',fontSize:13,lineHeight:1,borderRadius:4 }}>
                        {cn.status==='completed'?<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>:<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9"/></svg>}
                      </button>
                      <DropdownMenu trigger={<button style={{ background:'transparent',border:'none',color:'var(--txt3)',cursor:'pointer',padding:'2px 5px',fontSize:13,borderRadius:4,lineHeight:1 }}>⋮</button>} items={[{label:'Edit title',onClick:()=>setEditingCnId(cn.id)},{label:'Delete',danger:true,onClick:()=>deleteConcept(cn.id)}]}/>
                    </div>
                  </div>
                );
              }}
            />
          </div>
        </div>
        {/* Main content */}
        <div style={{ flex:1,display:'flex',flexDirection:'column',overflow:'hidden',minHeight:0 }}>
          <div className="tab-bar">
            {TABS.map(t=><button key={t} className={`tab-btn${tab===t?' active':''}`} onClick={()=>setTab(t)}>{t==='recordings'?'Record':t.charAt(0).toUpperCase()+t.slice(1)}</button>)}
            {activeCn&&<span style={{ marginLeft:'auto',fontSize:11,color:'var(--txt3)',fontStyle:'italic',padding:'0 12px' }}>{concepts.find(c=>c.id===activeCn)?.title||''}</span>}
          </div>
          <div style={{ flex:1,overflow:'hidden',display:'flex',flexDirection:'column',minHeight:0 }}>
            {tab==='notes'&&(!activeCn
              ?<div style={{ flex:1,padding:24,overflowY:'auto' }}>
                  <h2 style={{ margin:'0 0 14px',fontSize:17,color:'var(--txt)' }}>Topic Analysis: {currentTopic.title}</h2>
                  <div style={{ display:'grid',gridTemplateColumns:'1fr 1fr',gap:10,marginBottom:20 }}>
                    <div className="stat-card"><div className="stat-val">{concepts.length}</div><div className="stat-lbl">Concepts</div></div>
                    <div className="stat-card"><div className="stat-val">{noteVal.trim().split(/\s+/).filter(Boolean).length}</div><div className="stat-lbl">Words written</div></div>
                  </div>
                  <MarkdownEditor value={noteVal} onChange={setNoteVal} onSave={saveNotes} historyKey={noteKey(activeCn)} placeholder={`Notes for ${currentTopic.title}…`} onUploadDocument={importConceptDocument} spaceId={sid}/>
                </div>
              :<MarkdownEditor value={noteVal} onChange={setNoteVal} onSave={saveNotes} historyKey={noteKey(activeCn)} placeholder={`Notes for ${concepts.find(c=>c.id===activeCn)?.title||'concept'}…`} onUploadDocument={importConceptDocument} spaceId={sid}/>
            )}
            {tab==='explains'&&<ExplainsTab spaceId={sid} conceptId={activeCn||currentTopic.id} conceptTitle={activeCn?(concepts.find(c=>c.id===activeCn)?.title||currentTopic.title):currentTopic.title}/>}
            {tab==='quicktest'&&<QuickTestTab spaceId={sid} conceptId={activeCn} topicTitle={currentTopic.title}/>}
            {tab==='recordings'&&<MediaRecorderTab spaceId={sid} conceptId={activeCn||currentTopic.id} conceptTitle={activeCn?(concepts.find(c=>c.id===activeCn)?.title||currentTopic.title):currentTopic.title}/>}
            {tab==='notebook'&&<NotebookTab spaceId={sid} conceptId={activeCn||currentTopic.id} conceptTitle={activeCn?(concepts.find(c=>c.id===activeCn)?.title||currentTopic.title):currentTopic.title}/>}
            {tab==='playground'&&<PlaygroundTab spaceId={sid} conceptId={activeCn||currentTopic.id} conceptTitle={activeCn?(concepts.find(c=>c.id===activeCn)?.title||currentTopic.title):currentTopic.title}/>}
          </div>
        </div>
      </div>
    </div>
  );
}
