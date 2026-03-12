import { create } from 'zustand';

const NAV_PAGES = new Set(['dashboard', 'chat', 'spaces', 'agents', 'config']);

// ── Settings helpers ───────────────────────────────────────────
const ACCENT_KEY   = 'ui_accent';
const DENSITY_KEY  = 'ui_density';
const FONTSIZE_KEY = 'ui_fontsize';

const DEFAULT_ACCENT = '#4ade80';

function applyAccent(hex) {
  // Derive dim/border/hover from the base hex
  const r = parseInt(hex.slice(1,3),16);
  const g = parseInt(hex.slice(3,5),16);
  const b = parseInt(hex.slice(5,7),16);
  const root = document.documentElement;
  root.style.setProperty('--accent',        hex);
  root.style.setProperty('--accent-dim',    `rgba(${r},${g},${b},.10)`);
  root.style.setProperty('--accent-border', `rgba(${r},${g},${b},.28)`);
  root.style.setProperty('--accent-hover',  shiftLuminance(hex, -0.08));
}

function shiftLuminance(hex, delta) {
  let r = parseInt(hex.slice(1,3),16)/255;
  let g = parseInt(hex.slice(3,5),16)/255;
  let b = parseInt(hex.slice(5,7),16)/255;
  r = Math.max(0, Math.min(1, r + delta));
  g = Math.max(0, Math.min(1, g + delta));
  b = Math.max(0, Math.min(1, b + delta));
  return `#${Math.round(r*255).toString(16).padStart(2,'0')}${Math.round(g*255).toString(16).padStart(2,'0')}${Math.round(b*255).toString(16).padStart(2,'0')}`;
}

function applyDensity(d) {
  document.documentElement.setAttribute('data-density', d);
}

function applyFontSize(f) {
  document.documentElement.setAttribute('data-fontsize', f);
}

// Apply stored settings on module load
(function initSettings() {
  try {
    const accent = localStorage.getItem(ACCENT_KEY) || DEFAULT_ACCENT;
    const density = localStorage.getItem(DENSITY_KEY) || 'default';
    const fontSize = localStorage.getItem(FONTSIZE_KEY) || 'default';
    applyAccent(accent);
    applyDensity(density);
    applyFontSize(fontSize);
  } catch {}
})();

function readPageFromLocation() {
  if (typeof window === 'undefined') return 'dashboard';
  try {
    const hash = window.location.hash.replace('#', '').trim();
    if (NAV_PAGES.has(hash)) return hash;
    const saved = localStorage.getItem('ui_page') || '';
    if (NAV_PAGES.has(saved)) return saved;
  } catch { /* ignore storage errors */ }
  return 'dashboard';
}

export const useStore = create((set) => ({
  // Theme
  isDark: (typeof localStorage !== 'undefined' ? localStorage.getItem('theme') : null) !== 'light',
  toggleTheme: () => set(s => {
    const next = !s.isDark;
    document.documentElement.setAttribute('data-theme', next ? 'dark' : 'light');
    localStorage.setItem('theme', next ? 'dark' : 'light');
    return { isDark: next };
  }),

  // Accent color
  accent: (typeof localStorage !== 'undefined' ? localStorage.getItem(ACCENT_KEY) : null) || DEFAULT_ACCENT,
  setAccent: (hex) => set(() => {
    applyAccent(hex);
    try { localStorage.setItem(ACCENT_KEY, hex); } catch {}
    return { accent: hex };
  }),

  // Message density
  density: (typeof localStorage !== 'undefined' ? localStorage.getItem(DENSITY_KEY) : null) || 'default',
  setDensity: (d) => set(() => {
    applyDensity(d);
    try { localStorage.setItem(DENSITY_KEY, d); } catch {}
    return { density: d };
  }),

  // Font size
  fontSize: (typeof localStorage !== 'undefined' ? localStorage.getItem(FONTSIZE_KEY) : null) || 'default',
  setFontSize: (f) => set(() => {
    applyFontSize(f);
    try { localStorage.setItem(FONTSIZE_KEY, f); } catch {}
    return { fontSize: f };
  }),

  // Navigation
  page: readPageFromLocation(),
  setPage: (page, opts = {}) => set(() => {
    const next = NAV_PAGES.has(page) ? page : 'dashboard';
    if (typeof window !== 'undefined') {
      localStorage.setItem('ui_page', next);
      const url = `#${next}`;
      if (opts.replace) window.history.replaceState({ page: next }, '', url);
      else window.history.pushState({ page: next }, '', url);
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
  setCurrentSpace: (s) => set({ currentSpace: s, currentChapter: null, currentTopic: null, spaceRoadmap: null }),
  setCurrentChapter: (c) => set({ currentChapter: c }),
  setCurrentTopic: (t) => set({ currentTopic: t }),
  setSpaceRoadmap: (rm) => set({ spaceRoadmap: rm }),
  setSpaceSessions: (ss) => set({ spaceSessions: ss }),
}));
