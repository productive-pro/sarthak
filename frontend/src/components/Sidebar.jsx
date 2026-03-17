import { useState } from 'react';
import { useStore } from '../store';
import { DashIcon, ChatIcon, SpaceIcon, AgentIcon, ConfigIcon, AguiIcon } from './icons';
import SettingsPanel from './SettingsPanel';

const NAV = [
  { id: 'dashboard', label: 'Dashboard', Icon: DashIcon },
  { id: 'chat',      label: 'Chat',      Icon: ChatIcon },
  { id: 'agui',      label: 'Copilot',   Icon: AguiIcon },
  { id: 'spaces',    label: 'Spaces',    Icon: SpaceIcon },
  { id: 'agents',    label: 'Agents',    Icon: AgentIcon },
  { id: 'config',    label: 'Config',    Icon: ConfigIcon },
];

function SettingsIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
    </svg>
  );
}

export default function Sidebar() {
  const { page, setPage } = useStore();
  const [pinned, setPinned] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <aside id="sidebar" className={pinned ? 'sidebar-pinned' : ''}>
      {/* Pin toggle */}
      <button title="Toggle sidebar" className="sb-toggle"
        style={{ position: 'absolute', top: 14, right: -14, zIndex: 200, width: 22, height: 22,
          background: 'var(--surface2)', border: '1px solid var(--brd2)', borderRadius: '50%',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          cursor: 'pointer', color: 'var(--txt3)', opacity: 0, transition: 'opacity 150ms' }}
        onClick={() => setPinned(p => !p)}>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/>
        </svg>
      </button>

      {/* Logo */}
      <div className="logo">
        <div className="logo-mark">
          <img src="/sarthak_icon.svg" alt="S" onError={e => { e.currentTarget.style.display = 'none'; }} />
        </div>
        <div className="logo-text">
          <span className="logo-name">Sarthak AI</span>
          <span className="logo-tag">Intelligence Platform</span>
        </div>
      </div>

      {/* Nav */}
      <nav className="nav-section">
        <div className="nav-lbl">Main</div>
        {NAV.map(({ id, label, Icon }) => (
          <button key={id} className={`nav-item${page === id ? ' active' : ''}`} onClick={() => setPage(id)}>
            <span className="nav-icon"><Icon size={16} /></span>
            <span className="nav-label">{label}</span>
          </button>
        ))}
      </nav>

      {/* Footer — settings + version */}
      <div className="sidebar-footer">
        <span className="nav-label sf-version">v0.2.0</span>
        <button className={`settings-trigger${settingsOpen ? ' active' : ''}`}
          onClick={() => setSettingsOpen(o => !o)} title="Preferences">
          <SettingsIcon size={15} />
          <span className="nav-label">Settings</span>
        </button>
      </div>

      {/* Settings panel — floats above footer */}
      {settingsOpen && <SettingsPanel onClose={() => setSettingsOpen(false)} />}
    </aside>
  );
}
