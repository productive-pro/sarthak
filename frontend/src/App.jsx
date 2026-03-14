import { useEffect } from 'react';
import { useStore } from './store';
import Sidebar from './components/Sidebar';
import Toast from './components/Toast';
import Dashboard from './pages/Dashboard';
import Chat from './pages/Chat';
import Spaces from './pages/Spaces';
import Agents from './pages/Agents';
import Config from './pages/Config';

// Apply saved theme on load
const savedTheme = localStorage.getItem('theme') || 'dark';
document.documentElement.setAttribute('data-theme', savedTheme);

/** Map of page id → component. Add new pages here only. */
const PAGES = {
  dashboard: Dashboard,
  chat:      Chat,
  spaces:    Spaces,
  agents:    Agents,
  config:    Config,
};

export default function App() {
  const { page, setPage } = useStore();

  useEffect(() => {
    // Sync store to URL on initial load (replace so there's no extra history entry)
    const hash = window.location.hash.replace('#', '').trim();
    if (hash) setPage(hash, { replace: true });

    // On browser back/forward, sync store WITHOUT pushing a new history entry
    const onPopState = (e) => {
      const h = window.location.hash.replace('#', '').trim();
      const next = h || e.state?.page || 'dashboard';
      setPage(next, { replace: true });
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [setPage]);

  const Page = PAGES[page] ?? Dashboard;

  return (
    <div id="app">
      <Sidebar />
      <main id="main">
        <Page />
      </main>
      <Toast />
    </div>
  );
}
