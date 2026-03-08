import { create } from 'zustand';

const NAV_PAGES = new Set(['dashboard', 'chat', 'spaces', 'agents', 'config']);

function readPageFromLocation() {
  if (typeof window === 'undefined') return 'dashboard';
  const hash = window.location.hash.replace('#', '').trim();
  if (NAV_PAGES.has(hash)) return hash;
  const saved = localStorage.getItem('ui_page') || '';
  if (NAV_PAGES.has(saved)) return saved;
  return 'dashboard';
}

export const useStore = create((set) => ({
  // Theme
  isDark: document.documentElement.getAttribute('data-theme') !== 'light',
  toggleTheme: () => set(s => {
    const next = !s.isDark;
    document.documentElement.setAttribute('data-theme', next ? 'dark' : 'light');
    localStorage.setItem('theme', next ? 'dark' : 'light');
    return { isDark: next };
  }),

  // Navigation
  page: readPageFromLocation(),
  setPage: (page, opts = {}) => set(() => {
    const next = NAV_PAGES.has(page) ? page : 'dashboard';
    if (typeof window !== 'undefined') {
      localStorage.setItem('ui_page', next);
      const url = `#${next}`;
      if (opts.replace) window.history.replaceState({ page: next }, '', url);
      else if (opts.push !== false) window.history.pushState({ page: next }, '', url);
    }
    return { page: next };
  }),

  // Toast
  toasts: [],
  toast: (msg, type = 'info') => set(s => ({ toasts: [...s.toasts, { id: Date.now(), msg, type }] })),
  ok: (msg) => set(s => ({ toasts: [...s.toasts, { id: Date.now(), msg, type: 'ok' }] })),
  err: (msg) => set(s => ({ toasts: [...s.toasts, { id: Date.now(), msg, type: 'err' }] })),
  removeToast: (id) => set(s => ({ toasts: s.toasts.filter(t => t.id !== id) })),

  // Spaces
  spacesView: 'list',         // 'list' | 'home' | 'chapter' | 'topic'
  currentSpace: null,
  currentChapter: null,
  currentTopic: null,
  spaceRoadmap: null,
  spaceSessions: [],

  setSpacesView: (v) => set({ spacesView: v }),
  setCurrentSpace: (s) => set({ currentSpace: s }),
  setCurrentChapter: (c) => set({ currentChapter: c }),
  setCurrentTopic: (t) => set({ currentTopic: t }),
  setSpaceRoadmap: (rm) => set({ spaceRoadmap: rm }),
  setSpaceSessions: (ss) => set({ spaceSessions: ss }),
}));
