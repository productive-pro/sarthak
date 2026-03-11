/**
 * Modal — reusable modal/overlay dialog.
 *
 * Props:
 *   title       string
 *   children    ReactNode
 *   onClose     fn
 *   footer      ReactNode
 *   wide        bool   — wider max-width (760px)
 *   width       string — explicit width (turns into slide-in overlay style)
 *   height      string — explicit height (slide-in overlay style)
 *   bodyStyle   object
 *   bodyClassName string
 *   style       object — extra style on box
 */
import { useEffect, useRef } from 'react';

export default function Modal({
  title, children, onClose, footer,
  wide, width, height,
  bodyStyle, bodyClassName, style,
}) {
  const ref = useRef();
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const h = (e) => { if (e.key === 'Escape') onCloseRef.current?.(); };
    document.addEventListener('keydown', h);
    return () => document.removeEventListener('keydown', h);
  }, []);

  const boxStyle = width
    ? { width, height: height || '70%', maxWidth: '96vw', maxHeight: '90vh', ...style }
    : { maxWidth: wide ? 760 : undefined, ...style };

  return (
    <div className="modal-backdrop" ref={ref} onClick={e => e.target === ref.current && onClose()}>
      <div className="modal-box" style={boxStyle}>
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
