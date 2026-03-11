import React from 'react';
import { useStore } from '../store';
import { DashIcon, ChatIcon, SpaceIcon, AgentIcon, ConfigIcon } from './icons';

const NAV = [
  { id: 'dashboard', label: 'Dashboard', Icon: DashIcon },
  { id: 'chat',      label: 'Chat',      Icon: ChatIcon },
  { id: 'spaces',    label: 'Spaces',    Icon: SpaceIcon },
  { id: 'agents',    label: 'Agents',    Icon: AgentIcon },
  { id: 'config',    label: 'Config',    Icon: ConfigIcon },
];

export default function Sidebar() {
  const { page, setPage, isDark, toggleTheme } = useStore();
  const [pinned, setPinned] = React.useState(false);

  return (
    <aside id="sidebar" className={pinned ? 'sidebar-pinned' : ''}>
      <button
        title="Toggle sidebar"
        className="sb-toggle"
        style={{ position: 'absolute', top: 14, right: -14, zIndex: 200, width: 22, height: 22, background: 'var(--surface2)', border: '1px solid var(--brd2)', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', color: 'var(--txt3)', opacity: 0, transition: 'opacity 150ms' }}
        onClick={() => setPinned(p => !p)}
      >
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/>
        </svg>
      </button>
      <div className="logo">
        <div className="logo-mark">
          <img src="/sarthak_icon.svg" alt="S" onError={e => { e.currentTarget.style.display = 'none'; }} />
        </div>
        <div className="logo-text">
          <span className="logo-name">Sarthak AI</span>
          <span className="logo-tag">Intelligence Platform</span>
        </div>
      </div>
      <nav className="nav-section">
        <div className="nav-lbl">Main</div>
        {NAV.map(({ id, label, Icon }) => (
          <button key={id} className={`nav-item${page === id ? ' active' : ''}`} onClick={() => setPage(id)}>
            <span className="nav-icon"><Icon size={16} /></span>
            <span className="nav-label">{label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">
        <span className="nav-label sf-version">v0.2.0</span>
        <button className="theme-btn" onClick={toggleTheme}>{isDark ? 'Light' : 'Dark'}</button>
      </div>
    </aside>
  );
}
