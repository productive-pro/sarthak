import { useEffect, useRef } from 'react';

export default function PromptInline({
  title,
  value,
  onChange,
  onSubmit,
  onCancel,
  placeholder = 'Optional instructions…',
  submitLabel = 'Generate',
  multiline = true,
  autoFocus = true,
}) {
  const inputRef = useRef(null);

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') { onCancel?.(); return; }
    if (!multiline && e.key === 'Enter') { e.preventDefault(); onSubmit?.(); }
    if (multiline && (e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); onSubmit?.(); }
  };

  const Field = multiline ? 'textarea' : 'input';

  return (
    <div style={{ padding: 12, marginBottom: 16, background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ fontSize: 12, color: 'var(--txt2)', fontWeight: 600 }}>{title}</div>
      <Field
        ref={inputRef}
        className="s-input"
        rows={multiline ? 2 : undefined}
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        style={multiline ? { resize: 'vertical', fontSize: 12.5, lineHeight: 1.55 } : { fontSize: 12.5, padding: '6px 10px' }}
      />
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button className="btn btn-accent btn-sm" onClick={() => onSubmit?.()}>{submitLabel}</button>
        <button className="btn btn-muted btn-sm" onClick={() => onCancel?.()}>Cancel</button>
        <span style={{ fontSize: 10.5, color: 'var(--txt3)', marginLeft: 'auto' }}>
          {multiline ? 'Ctrl+Enter to submit' : 'Enter to submit'}
        </span>
      </div>
    </div>
  );
}
