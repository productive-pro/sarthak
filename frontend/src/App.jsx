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

export default function App() {
  const { page, setPage } = useStore();

  useEffect(() => {
    const syncFromHash = () => {
      const hash = window.location.hash.replace('#', '').trim();
      if (hash) setPage(hash, { push: false });
    };
    window.addEventListener('popstate', syncFromHash);
    syncFromHash();
    return () => window.removeEventListener('popstate', syncFromHash);
  }, [setPage]);

  return (
    <div id="app">
      <Sidebar />
      <main id="main">
        {page === 'dashboard' && <Dashboard />}
        {page === 'chat' && <Chat />}
        {page === 'spaces' && <Spaces />}
        {page === 'agents' && <Agents />}
        {page === 'config' && <Config />}
      </main>
      <Toast />
    </div>
  );
}
