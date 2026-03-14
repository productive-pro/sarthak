/**
 * pages/spaces/SpacesList.jsx
 * Space list view with create, manage, trash, settings.
 */
import React, { useState, useCallback } from 'react';
import { api } from '../../api';
import { useStore } from '../../store';
import useFetch from '../../hooks/useFetch';
import Modal from '../../components/Modal';
import SpaceCard from '../../components/SpaceCard';
import Overlay from '../../components/Overlay';
import SettingsTabs from '../../components/spaces/SpaceSettingsTabs';
import { SpaceGeneratingAnimation } from './shared';
import CreateWizard from './CreateWizard';

// ── SpaceSettingsOverlay ──────────────────────────────────────────────────────
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

  React.useEffect(() => {
    if (!space?.name) return;
    api(`/spaces/${sid}/settings`).then(s => {
      setSettings(s);
      setForm({ goal:s.goal||'', background:s.background||'', domain_name:s.domain||'', rag_enabled:s.rag_enabled||false, llm_context:s.llm_context||'', soul_md:s.soul_md||'', memory_md:s.memory_md||'', preferred_style:s.preferred_style||'visual + hands-on', daily_goal_minutes:s.daily_goal_minutes??30, is_technical:s.is_technical||false, mastered_concepts:s.mastered_concepts||[], struggling_concepts:s.struggling_concepts||[], badges:s.badges||[] });
    }).catch(()=>{});
  }, [space?.name, sid]);

  const save = async () => {
    setSaving(true);
    try { await api(`/spaces/${sid}/settings`, { method:'PATCH', body:JSON.stringify(form) }); ok('Settings saved'); }
    catch (e) { err(e.message); }
    setSaving(false);
  };

  const regenRoadmap = async () => {
    if (!space?.directory || regenerating) return;
    setRegenerating(true);
    try { await api('/spaces/regenerate-roadmap',{method:'POST',body:JSON.stringify({directory:space.directory})}); setSpaceRoadmap(null); ok('Roadmap regeneration started — reload the space to see changes'); }
    catch (e) { err(e.message); }
    setRegenerating(false);
  };

  const handleDelete = async () => {
    if (!space?.name || deleting) return;
    if (confirmText.trim() !== space.name) { err('Please type the exact space name to confirm.'); return; }
    setDeleting(true);
    try { await api('/spaces/delete',{method:'POST',body:JSON.stringify({directory:space.directory,name:space.name})}); ok('Space moved to trash'); setCurrentSpace(null); setSpaceRoadmap(null); setSpacesView('list'); onClose(); }
    catch (e) { err(e.message); }
    finally { setDeleting(false); }
  };

  return (
    <Overlay title={`Settings — ${space?.name}`} onClose={onClose} width="700px" height="82%">
      {regenerating ? (
        <div style={{ display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',height:'100%',gap:20 }}>
          <SpaceGeneratingAnimation />
          <div style={{ fontSize:12,color:'var(--txt3)',textAlign:'center' }}>Rebuilding your roadmap — this takes about a minute…</div>
        </div>
      ) : !settings ? (
        <div className="loading-center"><span className="spin" /></div>
      ) : (
        <SettingsTabs tab={tab} setTab={setTab} settings={settings} form={form}
          onChange={p=>setForm(f=>({...f,...p}))} onSave={save} saving={saving}
          onDelete={()=>setConfirmOpen(true)} onRegenerateRoadmap={regenRoadmap} regenerating={regenerating} />
      )}
      {confirmOpen && (
        <Modal title="Delete Space" onClose={()=>{ if(!deleting){setConfirmOpen(false);setConfirmText('');} }}
          footer={<>
            <button className="btn btn-muted btn-sm" onClick={()=>{setConfirmOpen(false);setConfirmText('');}} disabled={deleting}>Cancel</button>
            <button className="btn btn-del btn-sm" onClick={handleDelete} disabled={deleting}>{deleting?'Deleting…':'Delete Space'}</button>
          </>}>
          <div style={{ fontSize:12.5,color:'var(--txt2)',marginBottom:10 }}>Type the space name to confirm deletion:</div>
          <div style={{ fontSize:12,color:'var(--txt3)',marginBottom:10 }}><strong>{space?.name}</strong></div>
          <input className="s-input" value={confirmText} onChange={e=>setConfirmText(e.target.value)} placeholder="Enter space name exactly" autoFocus />
        </Modal>
      )}
    </Overlay>
  );
}

// ── SpacesList ────────────────────────────────────────────────────────────────
export default function SpacesList() {
  const [showCreate, setShowCreate] = useState(false);
  const [wizardCreatedResult, setWizardCreatedResult] = useState(null);
  const [settingsSpace, setSettingsSpace] = useState(null);
  const [manageOpen, setManageOpen] = useState(false);
  const [trashed, setTrashed] = useState([]);
  const [trashLoading, setTrashLoading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleteConfirm, setDeleteConfirm] = useState('');
  const { setSpacesView, setCurrentSpace, setSpaceRoadmap, ok, err } = useStore();

  const spacesTransform = useCallback(r => (Array.isArray(r) ? r : r?.spaces ?? r?.items ?? []), []);
  const { data: spaces=[], loading, reload, setData:setSpaces } = useFetch('/spaces',[], { initialData:[], transform:spacesTransform });

  const toggleActive = async (space, activate) => {
    setSpaces(prev=>prev.map(s=>({ ...s, is_active: activate ? (s.directory===space.directory) : (s.directory===space.directory ? false : s.is_active) })));
    try { await api('/spaces/activate',{method:'POST',body:JSON.stringify({directory:activate?space.directory:''})}); ok(activate?`${space.name} set as active space`:`${space.name} deactivated`); reload(); }
    catch(e) { err(e.message); reload(); }
  };

  const loadTrashed = async () => {
    setTrashLoading(true);
    try { const r=await api('/spaces/trashed'); setTrashed(Array.isArray(r)?r:[]); }
    catch(e) { err(e.message); }
    setTrashLoading(false);
  };

  const openManage = async () => { setManageOpen(true); await loadTrashed(); };

  const recoverSpace = async (space) => {
    try { const r=await api('/spaces/recover',{method:'POST',body:JSON.stringify({directory:space.directory})}); const status=r?.space?.recovery_status; if(status==='already_exists'){const cp=r?.space?.conflict_trash_path; ok(cp?`Space already exists. Kept backup at ${cp}`:'Space already exists. Kept trashed backup for safety.');} else ok('Space recovered'); await Promise.all([reload(),loadTrashed()]); }
    catch(e) { err(e.message); }
  };

  const deletePermanently = async () => {
    if (!deleteTarget) return;
    if ((deleteConfirm||'').trim()!==deleteTarget.name) { err('Please type the exact space name to confirm.'); return; }
    try { await api('/spaces/delete-permanent',{method:'POST',body:JSON.stringify({directory:deleteTarget.directory})}); ok('Space permanently deleted'); setDeleteTarget(null); setDeleteConfirm(''); await loadTrashed(); }
    catch(e) { err(e.message); }
  };

  const handleSpaceCreated = async (created) => {
    setShowCreate(false); setWizardCreatedResult(null); await reload();
    if (created?.directory) { setCurrentSpace({name:created.name,directory:created.directory,space_type:created.space_type}); setSpaceRoadmap(null); setSpacesView('home'); }
  };

  return (
    <div className="page">
      <header className="pg-header">
        <div className="pg-title-group">
          <h1 className="pg-title">Spaces</h1>
          <p className="pg-sub">Mastery-learning workspaces</p>
        </div>
        <div className="pg-actions">
          <button className="btn btn-muted btn-sm" onClick={openManage}>Manage</button>
          <button className="btn btn-accent btn-sm" onClick={()=>setShowCreate(true)}>+ New Space</button>
        </div>
      </header>
      <div className="pg-body">
        {loading ? <div className="loading-center"><span className="spin"/></div>
        : spaces.length===0 ? (
          <div className="empty">
            <div className="empty-title">No spaces yet</div>
            <div className="empty-desc">Create a mastery workspace to start structured learning.</div>
            <button className="btn btn-accent btn-sm" style={{ marginTop:12 }} onClick={()=>setShowCreate(true)}>Create First Space</button>
          </div>
        ) : (
          <div className="spaces-grid">
            {spaces.map(s=><SpaceCard key={s.name||s.id} variant="list" space={s}
              onClick={()=>{ setCurrentSpace(s); setSpaceRoadmap(null); setSpacesView('home'); }}
              onToggleActive={toggleActive} onSettings={setSettingsSpace} />)}
          </div>
        )}
      </div>

      {showCreate && (
        <Modal title="Create Space" wide
          onClose={()=>{ if(wizardCreatedResult){handleSpaceCreated(wizardCreatedResult);return;} setShowCreate(false);setWizardCreatedResult(null); }}>
          <CreateWizard onClose={()=>{setShowCreate(false);setWizardCreatedResult(null);}}
            onSpaceCreated={res=>setWizardCreatedResult(res)} onCreated={handleSpaceCreated} />
        </Modal>
      )}

      {settingsSpace && <SpaceSettingsOverlay space={settingsSpace} onClose={()=>setSettingsSpace(null)} />}

      {manageOpen && (
        <Modal title="Manage Spaces" onClose={()=>setManageOpen(false)} wide>
          {trashLoading ? <div className="loading-center"><span className="spin"/></div>
          : trashed.length===0 ? <div className="empty"><div className="empty-title">No trashed spaces</div><div className="empty-desc">Deleted spaces stay here for 30 days.</div></div>
          : <div style={{ display:'flex',flexDirection:'column',gap:10 }}>
              {trashed.map(s=>(
                <div key={s.directory} className="card" style={{ padding:'10px 12px' }}>
                  <div style={{ display:'flex',alignItems:'center',gap:10 }}>
                    <div style={{ flex:1,minWidth:0 }}>
                      <div style={{ fontSize:13.5,fontWeight:600,color:'var(--txt)' }}>{s.name||s.directory}</div>
                      <div style={{ fontSize:11,color:'var(--txt3)' }}>{s.directory}</div>
                    </div>
                    <button className="btn btn-muted btn-sm" onClick={()=>recoverSpace(s)}>Recover</button>
                    <button className="btn btn-del btn-sm" onClick={()=>{setDeleteTarget(s);setDeleteConfirm('');}}>Delete</button>
                  </div>
                </div>
              ))}
            </div>}
        </Modal>
      )}

      {deleteTarget && (
        <Modal title="Delete Permanently"
          onClose={()=>{setDeleteTarget(null);setDeleteConfirm('');}}
          footer={<><button className="btn btn-muted btn-sm" onClick={()=>{setDeleteTarget(null);setDeleteConfirm('');}}>Cancel</button><button className="btn btn-del btn-sm" onClick={deletePermanently}>Delete Permanently</button></>}>
          <div style={{ fontSize:12.5,color:'var(--txt2)',marginBottom:10 }}>Type the space name to confirm permanent deletion:</div>
          <div style={{ fontSize:12,color:'var(--txt3)',marginBottom:10 }}><strong>{deleteTarget?.name}</strong></div>
          <input className="s-input" value={deleteConfirm} onChange={e=>setDeleteConfirm(e.target.value)} placeholder="Enter space name exactly" autoFocus />
        </Modal>
      )}
    </div>
  );
}
