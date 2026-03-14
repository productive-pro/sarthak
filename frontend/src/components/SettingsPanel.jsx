/**
 * SettingsPanel.jsx — floating preferences panel rendered by Sidebar.
 * Extracted so Sidebar stays under ~100 lines.
 */
import { useRef, useEffect } from 'react';
import { useStore } from '../store';

const ACCENTS = [
  { name: 'Sage',   hex: '#4ade80' },
  { name: 'Sky',    hex: '#38bdf8' },
  { name: 'Violet', hex: '#a78bfa' },
  { name: 'Rose',   hex: '#fb7185' },
  { name: 'Amber',  hex: '#fbbf24' },
  { name: 'Coral',  hex: '#f97316' },
  { name: 'Cyan',   hex: '#22d3ee' },
  { name: 'Indigo', hex: '#818cf8' },
];

export default function SettingsPanel({ onClose }) {
  const { isDark, toggleTheme, accent, setAccent, density, setDensity, fontSize, setFontSize } = useStore();
  const ref = useRef(null);

  // Close on outside click
  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  return (
    <div className="settings-panel" ref={ref}>
      <div className="settings-hdr">
        <span className="settings-title">Preferences</span>
        <button className="settings-close" onClick={onClose} aria-label="Close">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <path d="M18 6 6 18M6 6l12 12"/>
          </svg>
        </button>
      </div>

      <div className="settings-body">
        {/* Accent color */}
        <div className="settings-section">
          <div className="settings-label">Accent color</div>
          <div className="accent-grid">
            {ACCENTS.map(a => (
              <button key={a.hex} className={`accent-swatch${accent === a.hex ? ' active' : ''}`}
                style={{ '--sw-color': a.hex }} title={a.name} onClick={() => setAccent(a.hex)} />
            ))}
          </div>
          <div className="accent-custom-row">
            <span className="settings-sublabel">Custom</span>
            <input type="color" className="accent-custom-input"
              value={accent} onChange={e => setAccent(e.target.value)} />
            <span className="accent-hex-label">{accent}</span>
          </div>
        </div>

        {/* Theme */}
        <div className="settings-section">
          <div className="settings-label">Theme</div>
          <div className="settings-row">
            <button className={`settings-chip${!isDark ? ' active' : ''}`} onClick={() => isDark && toggleTheme()}>Light</button>
            <button className={`settings-chip${isDark ? ' active' : ''}`} onClick={() => !isDark && toggleTheme()}>Dark</button>
          </div>
        </div>

        {/* Font size */}
        <div className="settings-section">
          <div className="settings-label">Font size</div>
          <div className="settings-row">
            {['compact', 'default', 'large'].map(f => (
              <button key={f} className={`settings-chip${fontSize === f ? ' active' : ''}`}
                onClick={() => setFontSize(f)}>
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* Message density */}
        <div className="settings-section">
          <div className="settings-label">Message style</div>
          <div className="settings-row">
            {[['bubbles', 'Bubbles'], ['minimal', 'Minimal']].map(([val, label]) => (
              <button key={val} className={`settings-chip${density === val ? ' active' : ''}`}
                onClick={() => setDensity(val)}>
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
