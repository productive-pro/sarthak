import { useEffect, useRef } from 'react';
import { useStore } from '../store';

export default function Toast() {
  const { toasts, removeToast } = useStore();

  return (
    <div id="toast-c">
      {toasts.map(t => (
        <ToastItem key={t.id} toast={t} onDone={() => removeToast(t.id)} />
      ))}
    </div>
  );
}

function ToastItem({ toast, onDone }) {
  // Use a ref so the timer is not reset if the parent re-renders (e.g. new toast added)
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    const timer = setTimeout(() => onDoneRef.current(), 3500);
    return () => clearTimeout(timer);
  }, []); // intentionally empty — timer fires once per mount

  return (
    <div className={`toast-item ${toast.type === 'err' ? 'toast-err' : 'toast-ok'}`}>
      {toast.msg}
    </div>
  );
}
