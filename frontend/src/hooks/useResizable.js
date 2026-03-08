import { useCallback, useRef, useState } from 'react';

/**
 * Drag-resizable width that persists across sessions via localStorage.
 * Returns [width, onMouseDown] — attach onMouseDown to the drag handle element.
 *
 * Uses a ref for current width so the stable onMouseDown callback always
 * reads the latest value without being recreated on every drag step.
 */
export function useResizable(storageKey, defaultWidth, min = 140, max = 520) {
  const [width, setWidth] = useState(() => {
    const v = localStorage.getItem(storageKey);
    return v ? parseInt(v, 10) : defaultWidth;
  });
  // Mirror width into a ref so onMouseDown closure stays stable
  const widthRef = useRef(width);
  widthRef.current = width;

  const onMouseDown = useCallback((e) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = widthRef.current;  // read current width via ref — no stale closure

    const onMove = (ev) => {
      const next = Math.max(min, Math.min(max, startW + (ev.clientX - startX)));
      setWidth(next);
      localStorage.setItem(storageKey, String(next));
    };
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [storageKey, min, max]);  // stable — never recreated

  return [width, onMouseDown];
}
