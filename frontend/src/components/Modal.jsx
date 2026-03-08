import { useEffect, useRef } from 'react';

export default function Modal({ title, children, onClose, footer }) {
  const ref = useRef();

  useEffect(() => {
    const handler = (e) => { if (e.target === ref.current) onClose(); };
    const keyHandler = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', keyHandler);
    return () => document.removeEventListener('keydown', keyHandler);
  }, [onClose]);

  return (
    <div className="modal-backdrop" ref={ref} onClick={e => e.target === ref.current && onClose()}>
      <div className="modal-box">
        <div className="modal-hdr">
          <span className="modal-title">{title}</span>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body-inner">
          {children}
        </div>
        {footer && <div className="modal-ftr">{footer}</div>}
      </div>
    </div>
  );
}
