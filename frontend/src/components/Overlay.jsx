import { useEffect, useRef } from 'react';

export default function Overlay({
  title,
  children,
  onClose,
  footer,
  width = '70%',
  height = '70%',
  bodyStyle,
  bodyClassName,
}) {
  const ref = useRef();

  useEffect(() => {
    const keyHandler = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', keyHandler);
    return () => document.removeEventListener('keydown', keyHandler);
  }, [onClose]);

  return (
    <div className="modal-backdrop" ref={ref} onClick={e => e.target === ref.current && onClose()}>
      <div className="modal-box" style={{ width, height, maxWidth: '96vw', maxHeight: '90vh' }}>
        <div className="modal-hdr">
          <span className="modal-title">{title}</span>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className={`modal-body-inner${bodyClassName ? ` ${bodyClassName}` : ''}`} style={bodyStyle}>
          {children}
        </div>
        {footer && <div className="modal-ftr">{footer}</div>}
      </div>
    </div>
  );
}
