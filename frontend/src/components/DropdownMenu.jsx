import { useState, useEffect, useRef } from 'react';

export default function DropdownMenu({ trigger, items }) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    const handleClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setOpen(false);
    };
    if (open) document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  return (
    <div style={{ position: 'relative', display: 'inline-block' }} ref={menuRef} onClick={e => e.stopPropagation()}>
      <div onClick={() => setOpen(!open)} style={{ cursor: 'pointer', display: 'flex' }}>
        {trigger}
      </div>
      {open && (
        <div style={{
          position: 'absolute', top: '100%', right: 0, marginTop: 4, zIndex: 100,
          background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 6,
          boxShadow: '0 4px 12px rgba(0,0,0,0.3)', minWidth: 120, overflow: 'hidden'
        }}>
          {items.map((item, i) => (
            <div
              key={i}
              onClick={() => { setOpen(false); item.onClick(); }}
              style={{
                padding: '8px 12px', fontSize: 12, color: item.danger ? '#f87171' : 'var(--txt)',
                cursor: 'pointer', whiteSpace: 'nowrap', background: 'transparent',
                borderBottom: i < items.length - 1 ? '1px solid var(--brd)' : 'none'
              }}
              onMouseEnter={e => e.target.style.background = 'var(--surface2)'}
              onMouseLeave={e => e.target.style.background = 'transparent'}
            >
              {item.label}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
