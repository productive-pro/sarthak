import { useEffect } from 'react';
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
  useEffect(() => {
    const timer = setTimeout(onDone, 3500);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div className={`toast-item ${toast.type === 'err' ? 'toast-err' : 'toast-ok'}`}>
      {toast.msg}
    </div>
  );
}
