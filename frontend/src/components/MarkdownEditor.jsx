/**
 * MarkdownEditor — reusable live-preview markdown editor component.
 *
 * Props:
 *   value        string     — controlled value
 *   onChange     fn(string) — called on edit
 *   onSave       fn(string) — called on Ctrl+S
 *   readOnly     bool       — disable editing (default false)
 *   defaultMode  'edit'|'read' — initial tab (default 'edit')
 *   streaming    bool       — show blinking cursor at end
 *   placeholder  string
 *   historyKey   string     — localStorage prefix for history snapshots
 *   historyOpen  bool       — show history drawer
 *   onHistoryToggle fn(bool)
 *   onUploadDocument fn(File) — upload and convert document → markdown
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import rehypeHighlight from 'rehype-highlight';
import katex from 'katex';
import 'katex/dist/katex.min.css';
import 'highlight.js/styles/github-dark.css';

import DropdownMenu from './DropdownMenu';

const EDIT_FONT_SIZE = 15;
const EDIT_LINE_HEIGHT = 1.85;
const EDIT_LINE_HEIGHT_PX = Math.round(EDIT_FONT_SIZE * EDIT_LINE_HEIGHT);

// ── Inline markdown parser (no deps) ─────────────────────────
function formatInlineText(text) {
  let s = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  s = s.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/__(.+?)__/g, '<strong>$1</strong>');
  s = s.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
  s = s.replace(/_([^_\n]+)_/g, '<em>$1</em>');
  s = s.replace(/~~(.+?)~~/g, '<del>$1</del>');
  s = s.replace(/==(.+?)==/g, '<mark>$1</mark>');
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  s = s.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img alt="$1" src="$2" />');
  return s;
}

function parseInline(text) {
  const parts = [];
  const re = /\$\$([^$]+?)\$\$|\$([^$\n]+?)\$/g;
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push({ type: 'text', value: text.slice(last, m.index) });
    const val = m[1] || m[2] || '';
    parts.push({ type: 'math', value: val, display: !!m[1] });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ type: 'text', value: text.slice(last) });

  return parts.map(p => {
    if (p.type === 'text') return formatInlineText(p.value);
    try {
      return katex.renderToString(p.value, { displayMode: p.display, throwOnError: false });
    } catch {
      return formatInlineText(p.value);
    }
  }).join('');
}

function renderLine(text) {
  const t = text;
  if (!t.trim()) return `<span style="display:block;min-height:${EDIT_LINE_HEIGHT_PX}px;line-height:${EDIT_LINE_HEIGHT_PX}px"></span>`;

  const hm = t.match(/^(#{1,6})\s+(.+)/);
  if (hm) return `<h${hm[1].length} style="margin:0;line-height:${EDIT_LINE_HEIGHT_PX}px;font-size:${EDIT_FONT_SIZE}px;font-weight:700">${parseInline(hm[2])}</h${hm[1].length}>`;
  if (/^[-*_]{3,}\s*$/.test(t)) return `<hr style="margin:6px 0;line-height:${EDIT_LINE_HEIGHT_PX}px"/>`;
  if (t.startsWith('> ')) return `<blockquote style="margin:0;line-height:${EDIT_LINE_HEIGHT_PX}px">${parseInline(t.slice(2))}</blockquote>`;

  const ulm = t.match(/^(\s*)([-*+])\s+(.+)/);
  if (ulm) {
    const indent = Math.floor(ulm[1].length / 2);
    const inner = ulm[3];
    const cbm = inner.match(/^\[([ x])\]\s+(.+)/i);
    if (cbm) {
      const checked = cbm[1].toLowerCase() === 'x';
      return `<div class="md-checkbox${checked ? ' checked' : ''}"><input type="checkbox" ${checked ? 'checked' : ''} onclick="return false" /><span>${parseInline(cbm[2])}</span></div>`;
    }
    const bullet = ['•', '◦', '▸'][Math.min(indent, 2)];
    return `<div style="display:flex;gap:8px;padding-left:${indent * 16}px"><span style="color:var(--accent);flex-shrink:0">${bullet}</span><span>${parseInline(inner)}</span></div>`;
  }

  const olm = t.match(/^(\s*)(\d+)\.\s+(.+)/);
  if (olm) {
    const indent = Math.floor(olm[1].length / 2);
    return `<div style="display:flex;gap:8px;padding-left:${indent * 16}px"><span style="color:var(--txt3);flex-shrink:0;font-family:var(--mono);font-size:12px">${olm[2]}.</span><span>${parseInline(olm[3])}</span></div>`;
  }

  if (t.startsWith('```') || t.startsWith('~~~'))
    return `<code style="display:block;font-family:var(--mono);font-size:12px;color:var(--txt3)">${t.replace(/&/g, '&amp;').replace(/</g, '&lt;')}</code>`;

  if (t.startsWith('|')) {
    const cells = t.split('|').map(c => c.trim()).filter(Boolean);
    if (cells.every(c => /^[-:]+$/.test(c))) return '<tr class="sep-row" style="display:none"></tr>';
    return `<tr>${cells.map(c => `<td>${parseInline(c)}</td>`).join('')}</tr>`;
  }

  return `<span style="display:block;margin:0;line-height:${EDIT_LINE_HEIGHT_PX}px">${parseInline(t)}</span>`;
}

function renderLines(lines, activeLine) {
  const result = [];
  let i = 0;
  while (i < lines.length) {
    const raw = lines[i];
    const isActive = i === activeLine;

    if (raw.match(/^(`{3,}|~{3,})/)) {
      const fence = raw.match(/^(`{3,}|~{3,})/)[1];
      const lang = raw.slice(fence.length).trim();
      const blockLines = [raw];
      let j = i + 1;
      const closePat = new RegExp('^[' + fence[0] + ']{' + fence.length + ',}\\s*$');
      while (j < lines.length && !closePat.test(lines[j])) { blockLines.push(lines[j]); j++; }
      if (j < lines.length) blockLines.push(lines[j]);
      result.push({ type: 'block', from: i, to: j, lines: blockLines, cursor: activeLine >= i && activeLine <= j, kind: 'code', lang });
      i = j + 1;
      continue;
    }

    if (raw.startsWith('|') && i + 1 < lines.length && lines[i + 1].match(/^\|[-|: ]+\|/)) {
      const blockLines = [raw];
      let j = i + 1;
      while (j < lines.length && lines[j].startsWith('|')) { blockLines.push(lines[j]); j++; }
      result.push({ type: 'block', from: i, to: j - 1, lines: blockLines, cursor: activeLine >= i && activeLine < j, kind: 'table' });
      i = j;
      continue;
    }

    result.push({ type: 'line', index: i, text: raw, active: isActive });
    i++;
  }
  return result;
}

function MarkdownRender({ value }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex, rehypeHighlight]}
    >
      {value}
    </ReactMarkdown>
  );
}

// ── Speech-to-Text (streamed dictation) ────────────────────────────────
const SLICE_MS   = 5000;   // flush PCM to Whisper every 5 s
const TARGET_SR  = 16000;  // whisper-cli native sample rate

/** Encode Float32 PCM samples as a 16-bit mono WAV Blob. */
function pcmToWav(samples, sr) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const s = (o, t) => { for (let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i)); };
  s(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true);
  s(8, 'WAVE'); s(12, 'fmt '); v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, sr, true); v.setUint32(28, sr * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  s(36, 'data'); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++)
    v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, samples[i])) * 0x7fff, true);
  return new Blob([buf], { type: 'audio/wav' });
}

/** Downsample Float32 from browser sample rate to TARGET_SR via OfflineAudioContext. */
async function resampleTo16k(f32, fromSr) {
  if (fromSr === TARGET_SR) return f32;
  const ctx = new OfflineAudioContext(1, Math.ceil(f32.length * TARGET_SR / fromSr), TARGET_SR);
  const buf = ctx.createBuffer(1, f32.length, fromSr);
  buf.copyToChannel(f32, 0);
  const src = ctx.createBufferSource();
  src.buffer = buf; src.connect(ctx.destination); src.start();
  const out = await ctx.startRendering();
  return out.getChannelData(0);
}

function SpeechToTextBtn({ onAppend, spaceId }) {
  const [recording, setRecording]       = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const ctxRef    = useRef(null);   // AudioContext
  const procRef   = useRef(null);   // ScriptProcessorNode
  const chunksRef = useRef([]);     // Float32Array PCM chunks
  const activeRef = useRef(false);
  const timerRef  = useRef(null);
  const srRef     = useRef(TARGET_SR);

  const flush = async () => {
    const chunks = chunksRef.current;
    chunksRef.current = [];
    if (!chunks.length) return;
    const total = chunks.reduce((n, c) => n + c.length, 0);
    if (total < TARGET_SR * 0.3) return; // skip < 0.3 s
    const all = new Float32Array(total);
    let off = 0;
    for (const c of chunks) { all.set(c, off); off += c.length; }
    setTranscribing(true);
    try {
      const resampled = await resampleTo16k(all, srRef.current);
      const wav = pcmToWav(resampled, TARGET_SR);
      const form = new FormData();
      form.append('file', wav, 'stt.wav');
      const res = await fetch(`/api/spaces/${spaceId || '_default'}/transcribe`, {
        method: 'POST', body: form,
      });
      if (res.ok) {
        const { transcript } = await res.json();
        if (transcript?.trim()) onAppend(transcript.trim());
      }
    } catch (e) { console.error('STT error', e); }
    setTranscribing(false);
  };

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new AudioContext();
      ctxRef.current = ctx;
      srRef.current = ctx.sampleRate;
      const src = ctx.createMediaStreamSource(stream);
      // eslint-disable-next-line no-undef
      const proc = ctx.createScriptProcessor(4096, 1, 1);
      procRef.current = proc;
      chunksRef.current = [];
      activeRef.current = true;
      proc.onaudioprocess = (e) => {
        if (activeRef.current)
          chunksRef.current.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      };
      src.connect(proc);
      proc.connect(ctx.destination);
      setRecording(true);
      timerRef.current = setInterval(flush, SLICE_MS);
    } catch (e) {
      console.error('Mic denied', e);
      alert('Microphone access denied or not available.');
    }
  };

  const stopRecording = () => {
    activeRef.current = false;
    clearInterval(timerRef.current);
    procRef.current?.disconnect();
    ctxRef.current?.close();
    flush();
    setRecording(false);
  };

  useEffect(() => () => { activeRef.current = false; clearInterval(timerRef.current); ctxRef.current?.close(); }, []);

  const toggle = () => (recording ? stopRecording() : startRecording());

  const bars = [0.5, 0.9, 0.6, 1.0, 0.7, 0.4, 0.8];

  return (
    <button
      className={`btn btn-xs ${recording ? 'btn-accent' : 'btn-muted'}`}
      onClick={toggle}
      title="Speech to Text — streams dictation via Whisper (5-second slices)"
      style={{
        display: 'flex', alignItems: 'center', gap: 5,
        background: recording ? 'rgba(239,68,68,0.15)' : undefined,
        color: recording ? '#f87171' : undefined,
        borderColor: recording ? 'rgba(239,68,68,0.45)' : undefined,
      }}
    >
      {recording ? (
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 1, height: 12 }}>
            {bars.map((h, i) => (
              <span key={i} style={{
                display: 'inline-block', width: 2,
                height: `${Math.round(h * 10 + 2)}px`,
                background: transcribing ? '#fbbf24' : '#f87171',
                borderRadius: 1,
                animation: `sttBar${i % 4} ${0.45 + (i % 3) * 0.15}s ease-in-out infinite alternate`,
              }} />
            ))}
          </span>
          {transcribing ? 'Transcribing…' : 'Recording…'}
        </span>
      ) : (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
          <line x1="12" y1="19" x2="12" y2="23"/>
          <line x1="8" y1="23" x2="16" y2="23"/>
        </svg>
      )}
      <style>{`
        @keyframes sttBar0 { from { height: 3px; } to { height: 11px; } }
        @keyframes sttBar1 { from { height: 5px; } to { height: 9px;  } }
        @keyframes sttBar2 { from { height: 4px; } to { height: 13px; } }
        @keyframes sttBar3 { from { height: 6px; } to { height: 10px; } }
      `}</style>
    </button>
  );
}

// ── History drawer ────────────────────────────────────────────
function HistoryDrawer({ historyKey, onRestore }) {
  const [entries, setEntries] = useState([]);

  useEffect(() => {
    if (!historyKey) return;
    const found = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(`${historyKey}:hist:`)) {
        const ts = parseInt(k.split(':hist:')[1], 10);
        found.push({ ts, key: k, preview: (localStorage.getItem(k) || '').slice(0, 80) });
      }
    }
    found.sort((a, b) => b.ts - a.ts);
    setEntries(found.slice(0, 20));
  }, [historyKey]);

  if (!entries.length) return (
    <div style={{ padding: '16px', fontSize: 12, color: 'var(--txt3)' }}>No history yet.</div>
  );

  return (
    <div style={{ borderTop: '1px solid var(--brd)', maxHeight: 200, overflowY: 'auto', flexShrink: 0 }}>
      <div style={{ padding: '6px 12px', fontSize: 10, fontWeight: 700, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '.06em' }}>History</div>
      {entries.map(e => (
        <button key={e.key}
          onClick={() => onRestore(localStorage.getItem(e.key) || '')}
          style={{ width: '100%', textAlign: 'left', background: 'none', border: 'none', padding: '6px 12px', cursor: 'pointer', borderBottom: '1px solid var(--brd)', fontFamily: 'var(--font)' }}>
          <div style={{ fontSize: 10, color: 'var(--txt3)' }}>{new Date(e.ts).toLocaleString()}</div>
          <div style={{ fontSize: 11.5, color: 'var(--txt2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.preview}</div>
        </button>
      ))}
    </div>
  );
}

// ── Clip dropdown ─────────────────────────────────────────────
function ClipMenu({ onUploadDocument }) {
  const [open, setOpen] = useState(false);
  const [uploadMode, setUploadMode] = useState('vision');
  const wrapRef = useRef(null);
  const fileRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const pick = (mode) => {
    setOpen(false);
    setUploadMode(mode);
    if (fileRef.current) {
      fileRef.current.accept = mode === 'vision'
        ? 'image/*'
        : 'image/*,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.md,.rtf,.html,.htm';
      fileRef.current.click();
    }
  };

  return (
    <div ref={wrapRef} style={{ position: 'relative', display: 'inline-flex' }}>
      <input
        ref={fileRef}
        type="file"
        style={{ display: 'none' }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onUploadDocument?.(file, uploadMode);
          if (fileRef.current) fileRef.current.value = '';
        }}
      />
      <button
        type="button"
        className="btn btn-muted btn-xs"
        onClick={() => setOpen(v => !v)}
        title="Import file as note (OCR)"
        style={{ display: 'flex', alignItems: 'center', gap: 4 }}
      >
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
        </svg>
        Clip
      </button>
      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 4px)', right: 0, zIndex: 9999,
          background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 6,
          boxShadow: '0 4px 12px rgba(0,0,0,0.35)', minWidth: 150, overflow: 'hidden',
        }}>
          {[
            { label: 'Vision LLM OCR', mode: 'vision' },
            { label: 'OCR + text LLM', mode: 'text_llm' },
          ].map(({ label, mode }) => (
            <div
              key={mode}
              onMouseDown={() => pick(mode)}
              style={{ padding: '8px 12px', fontSize: 12, cursor: 'pointer', color: 'var(--txt)', whiteSpace: 'nowrap', borderBottom: mode === 'vision' ? '1px solid var(--brd)' : 'none' }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--surface2)'}
              onMouseLeave={e => e.currentTarget.style.background = ''}
            >
              {label}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────
export default function MarkdownEditor({
  value = '',
  onChange,
  onSave,
  readOnly = false,
  defaultMode = 'edit',
  streaming = false,
  placeholder = 'Write markdown…',
  historyKey,
  historyOpen = false,
  onHistoryToggle,
  onUploadDocument,
  spaceId,   // URL-encoded space id for STT dictation
}) {
  const [mode, setMode] = useState(defaultMode);
  const [cursorLine, setCursorLine] = useState(0);
  const [showFind, setShowFind] = useState(false);
  const [showLineNumbers, setShowLineNumbers] = useState(false);
  const [findText, setFindText] = useState('');
  const [replaceText, setReplaceText] = useState('');
  const [matchCase, setMatchCase] = useState(false);
  const textareaRef = useRef(null);
  const readPanelRef = useRef(null);
  const historyRef = useRef({ stack: [{ value, start: 0, end: 0 }], index: 0 });
  const skipPushRef = useRef(false);
  const pendingSelRef = useRef(null);

  const selectAll = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.focus();
    ta.select();
  }, []);

  const copySelection = useCallback(async () => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.focus();
    if (ta.selectionStart === ta.selectionEnd) ta.select();
    const selected = ta.value.slice(ta.selectionStart, ta.selectionEnd);
    try {
      await navigator.clipboard.writeText(selected);
    } catch {
      document.execCommand('copy');
    }
  }, []);

  const cutSelection = useCallback(async () => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.focus();
    if (ta.selectionStart === ta.selectionEnd) ta.select();
    const selected = ta.value.slice(ta.selectionStart, ta.selectionEnd);
    try {
      await navigator.clipboard.writeText(selected);
      const next = ta.value.slice(0, ta.selectionStart) + ta.value.slice(ta.selectionEnd);
      onChange?.(next);
    } catch {
      document.execCommand('cut');
    }
  }, [onChange]);

  const pasteClipboard = useCallback(async () => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.focus();
    try {
      const text = await navigator.clipboard.readText();
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const next = value.slice(0, start) + text + value.slice(end);
      onChange?.(next);
      requestAnimationFrame(() => {
        ta.selectionStart = ta.selectionEnd = start + text.length;
      });
    } catch {
      document.execCommand('paste');
    }
  }, [value, onChange]);

  // readOnly or streaming → always read mode
  const effectiveMode = (readOnly || (streaming && !value)) ? 'read' : mode;

  useEffect(() => {
    if (readOnly) setMode('read');
  }, [readOnly]);

  // Auto-focus the read panel so Shift+Enter works without a click
  useEffect(() => {
    if (effectiveMode === 'read' && !readOnly) {
      readPanelRef.current?.focus();
    }
  }, [effectiveMode, readOnly]);

  const lines = useMemo(() => value.split('\n'), [value]);
  const wordCount = useMemo(() => value.trim().split(/\s+/).filter(Boolean).length, [value]);

  const handleInput = useCallback((e) => {
    const next = e.target.value;
    const start = e.target.selectionStart;
    const end = e.target.selectionEnd;
    const hist = historyRef.current;
    const cur = hist.stack[hist.index];
    if (!cur || cur.value !== next) {
      hist.stack = hist.stack.slice(0, hist.index + 1);
      hist.stack.push({ value: next, start, end });
      if (hist.stack.length > 100) hist.stack.shift();
      hist.index = hist.stack.length - 1;
      skipPushRef.current = true;
    }
    onChange?.(next);
  }, [onChange]);

  const handleKeyDown = useCallback((e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      onSave?.(value);
      return;
    }
    if (e.shiftKey && e.key === 'Enter') {
      e.preventDefault();
      setMode(m => m === 'edit' ? 'read' : 'edit');
      return;
    }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) {
      e.preventDefault();
      undo();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.shiftKey && (e.key === 'z' || e.key === 'Z')))) {
      e.preventDefault();
      redo();
      return;
    }
    if (e.key === 'Tab') {
      e.preventDefault();
      const ta = e.target;
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const newVal = value.slice(0, start) + '  ' + value.slice(end);
      onChange?.(newVal);
      requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = start + 2; });
    }
  }, [value, onChange, onSave]);

  const applyHistory = useCallback((entry) => {
    if (!entry) return;
    pendingSelRef.current = { start: entry.start, end: entry.end };
    onChange?.(entry.value);
  }, [onChange]);

  const undo = useCallback(() => {
    const hist = historyRef.current;
    if (hist.index <= 0) return;
    hist.index -= 1;
    applyHistory(hist.stack[hist.index]);
  }, [applyHistory]);

  const redo = useCallback(() => {
    const hist = historyRef.current;
    if (hist.index >= hist.stack.length - 1) return;
    hist.index += 1;
    applyHistory(hist.stack[hist.index]);
  }, [applyHistory]);

  const updateCursor = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    const before = value.slice(0, ta.selectionStart);
    setCursorLine(before.split('\n').length - 1);
  }, [value]);

  useEffect(() => {
    if (streaming) return;
    if (skipPushRef.current) {
      skipPushRef.current = false;
    } else {
      const hist = historyRef.current;
      const cur = hist.stack[hist.index];
      if (!cur || cur.value !== value) {
        hist.stack = hist.stack.slice(0, hist.index + 1);
        hist.stack.push({ value, start: value.length, end: value.length });
        if (hist.stack.length > 100) hist.stack.shift();
        hist.index = hist.stack.length - 1;
      }
    }
    if (pendingSelRef.current && textareaRef.current) {
      const { start, end } = pendingSelRef.current;
      pendingSelRef.current = null;
      requestAnimationFrame(() => {
        if (!textareaRef.current) return;
        textareaRef.current.focus();
        textareaRef.current.selectionStart = start;
        textareaRef.current.selectionEnd = end;
      });
    }
  }, [value, streaming]);

  const findNext = useCallback(() => {
    if (!findText) return;
    const ta = textareaRef.current;
    if (!ta) return;
    const hay = matchCase ? value : value.toLowerCase();
    const needle = matchCase ? findText : findText.toLowerCase();
    const start = ta.selectionEnd || 0;
    let idx = hay.indexOf(needle, start);
    if (idx === -1) idx = hay.indexOf(needle, 0);
    if (idx === -1) return;
    ta.focus();
    ta.selectionStart = idx;
    ta.selectionEnd = idx + needle.length;
    updateCursor();
  }, [findText, matchCase, value, updateCursor]);

  const replaceNext = useCallback(() => {
    if (!findText) return;
    const ta = textareaRef.current;
    if (!ta) return;
    const sel = value.slice(ta.selectionStart, ta.selectionEnd);
    const haySel = matchCase ? sel : sel.toLowerCase();
    const needle = matchCase ? findText : findText.toLowerCase();
    if (haySel === needle) {
      const next = value.slice(0, ta.selectionStart) + replaceText + value.slice(ta.selectionEnd);
      const pos = ta.selectionStart + replaceText.length;
      const hist = historyRef.current;
      hist.stack = hist.stack.slice(0, hist.index + 1);
      hist.stack.push({ value: next, start: pos, end: pos });
      if (hist.stack.length > 100) hist.stack.shift();
      hist.index = hist.stack.length - 1;
      skipPushRef.current = true;
      onChange?.(next);
      pendingSelRef.current = { start: pos, end: pos };
      return;
    }
    findNext();
  }, [findText, matchCase, replaceText, value, onChange, findNext]);

  const replaceAll = useCallback(() => {
    if (!findText) return;
    const flags = matchCase ? 'g' : 'gi';
    const safe = findText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(safe, flags);
    const next = value.replace(re, replaceText);
    if (next === value) return;
    const hist = historyRef.current;
    hist.stack = hist.stack.slice(0, hist.index + 1);
    hist.stack.push({ value: next, start: 0, end: 0 });
    if (hist.stack.length > 100) hist.stack.shift();
    hist.index = hist.stack.length - 1;
    skipPushRef.current = true;
    onChange?.(next);
    pendingSelRef.current = { start: 0, end: 0 };
  }, [findText, matchCase, replaceText, value, onChange]);

  const segments = useMemo(() => renderLines(lines, cursorLine), [lines, cursorLine]);

  const streamCursor = streaming && value;
  const canUpload = !!onUploadDocument && !readOnly;

  return (
    <div className="mde-wrap" style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', minHeight: 0, background: 'var(--surface)', border: 'none' }}>
      {/* Tab bar — hidden when readOnly */}
      {!readOnly && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 12px', borderBottom: '1px solid var(--brd)', background: 'var(--surface)', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, opacity: mode === 'edit' ? 1 : 0.5, transition: 'opacity 0.2s', pointerEvents: mode === 'edit' ? 'auto' : 'none' }}>
            <SpeechToTextBtn spaceId={spaceId} onAppend={(text) => {
              const ta = textareaRef.current;
              if (!ta) return;
              const cur = ta.value;
              const pos = ta.selectionStart ?? cur.length;
              const prefix = (cur.endsWith(' ') || cur.endsWith('\n') || cur === '') ? '' : ' ';
              const next = cur.slice(0, pos) + prefix + text + ' ' + cur.slice(pos);
              onChange?.(next);
              const newPos = pos + prefix.length + text.length + 1;
              requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = newPos; });
            }} />
          </div>

          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 10, color: 'var(--txt3)', fontFamily: 'var(--mono)' }}>{wordCount}w</span>

            {/* Clip + menu grouped flush together */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            {canUpload && (
              <ClipMenu onUploadDocument={onUploadDocument} />
            )}

            <DropdownMenu
              trigger={
                <button type="button" style={{ background: 'none', border: 'none', color: 'var(--txt2)', padding: '2px 6px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/></svg>
                </button>
              }
              items={[
                { label: mode === 'edit' ? 'Switch to Read Mode' : 'Switch to Edit Mode', onClick: () => setMode(mode === 'edit' ? 'read' : 'edit') },
                ...(mode === 'edit' ? [
                  { label: 'Undo', onClick: undo },
                  { label: 'Redo', onClick: redo },
                  { label: 'Select All', onClick: selectAll },
                  { label: 'Copy', onClick: copySelection },
                  { label: 'Cut', onClick: cutSelection },
                  { label: 'Paste', onClick: pasteClipboard },
                  { label: showFind ? 'Hide Find/Replace' : 'Find/Replace', onClick: () => setShowFind(v => !v) },
                  { label: showLineNumbers ? 'Hide Line Numbers' : 'Show Line Numbers', onClick: () => setShowLineNumbers(v => !v) }
                ] : []),
                ...(onHistoryToggle ? [{ label: historyOpen ? 'Hide History' : 'Show History', onClick: () => onHistoryToggle(!historyOpen) }] : [])
              ]}
            />
            </div>{/* end Clip+menu group */}
          </div>
        </div>
      )}

      {showFind && !readOnly && effectiveMode === 'edit' && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', borderBottom: '1px solid var(--brd)', background: 'var(--surface2)', flexShrink: 0 }}>
          <input className="s-input" value={findText} onChange={e => setFindText(e.target.value)} placeholder="Find…" style={{ maxWidth: 220, fontSize: 12 }} />
          <input className="s-input" value={replaceText} onChange={e => setReplaceText(e.target.value)} placeholder="Replace…" style={{ maxWidth: 220, fontSize: 12 }} />
          <button className="btn btn-muted btn-sm" onClick={findNext}>Next</button>
          <button className="btn btn-muted btn-sm" onClick={replaceNext}>Replace</button>
          <button className="btn btn-muted btn-sm" onClick={replaceAll}>Replace All</button>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--txt3)' }}>
            <input type="checkbox" checked={matchCase} onChange={e => setMatchCase(e.target.checked)} />
            Match case
          </label>
        </div>
      )}

      {/* Edit mode */}
      {effectiveMode === 'edit' && !readOnly && (
        <div style={{ flex: 1, overflow: 'hidden', position: 'relative', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: '20px 24px', scrollbarWidth: 'thin', scrollbarColor: 'var(--brd2) transparent', position: 'relative' }}>
            <div style={{ position: 'relative', maxWidth: 720, margin: '0 auto', paddingLeft: showLineNumbers ? 42 : 0 }}>
              {showLineNumbers && (
                <div style={{ position: 'absolute', top: 0, left: 0, width: 36, textAlign: 'right', paddingRight: 8, color: 'var(--txt3)', fontSize: 11.5, fontFamily: 'var(--mono)', userSelect: 'none' }}>
                  {lines.map((_, i) => (
                    <div key={i} style={{ height: '1.85em', lineHeight: 1.85 }}>{i + 1}</div>
                  ))}
                </div>
              )}
              {/* Invisible textarea for input capture */}
              <textarea
                ref={textareaRef}
                value={value}
                onChange={handleInput}
                onKeyDown={handleKeyDown}
                onKeyUp={updateCursor}
                onClick={updateCursor}
                onSelect={updateCursor}
                spellCheck={false}
                autoComplete="off"
                style={{
                  position: 'absolute', inset: 0, width: '100%',
                  opacity: 1, resize: 'none', fontSize: EDIT_FONT_SIZE, zIndex: 10,
                  cursor: 'text', outline: 'none', border: 'none',
                  background: 'transparent', color: 'transparent', WebkitTextFillColor: 'transparent',
                  caretColor: 'var(--accent)', caretWidth: '2px', lineHeight: `${EDIT_LINE_HEIGHT_PX}px`,
                  padding: 0, paddingLeft: showLineNumbers ? 42 : 0, fontFamily: 'var(--mono)', whiteSpace: 'pre-wrap',
                  wordWrap: 'break-word', overflowWrap: 'break-word',
                  overflow: 'hidden',
                  height: `${(lines.length + 5) * EDIT_LINE_HEIGHT_PX}px`,
                  minHeight: '100%',
                }}
                rows={lines.length + 5}
              />

              {/* Live preview layer */}
              <div style={{ position: 'relative', zIndex: 1, pointerEvents: 'none', minHeight: 400, wordWrap: 'break-word', overflowWrap: 'break-word', overflowX: 'hidden' }}>
                {!value && (
                  <div style={{ position: 'absolute', top: 0, left: 0, fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--txt3)', pointerEvents: 'none', userSelect: 'none' }}>
                    {placeholder}
                  </div>
                )}
                <div style={{ fontSize: EDIT_FONT_SIZE, lineHeight: `${EDIT_LINE_HEIGHT_PX}px` }}>
                {segments.map((seg, idx) => {
                  if (seg.type === 'line') {
                    return (
                      <div key={idx} style={{ position: 'relative', minHeight: EDIT_LINE_HEIGHT_PX, lineHeight: `${EDIT_LINE_HEIGHT_PX}px`, fontSize: EDIT_FONT_SIZE }}>
                        {seg.active ? (
                          <span style={{ display: 'block', fontFamily: 'var(--mono)', fontSize: EDIT_FONT_SIZE, lineHeight: `${EDIT_LINE_HEIGHT_PX}px`, color: 'var(--accent)', background: 'rgba(74,222,128,0.06)', borderLeft: '2px solid rgba(74,222,128,0.5)', paddingLeft: 10, marginLeft: -12, borderRadius: '0 4px 4px 0' }}>
                            {seg.text || '\u200b'}
                          </span>
                        ) : (
                          <span dangerouslySetInnerHTML={{ __html: renderLine(seg.text) }} />
                        )}
                      </div>
                    );
                  }
                  if (seg.cursor) {
                    return (
                      <div key={idx}>
                        {seg.lines.map((l, li) => (
                          <div key={li} style={{ position: 'relative', minHeight: EDIT_LINE_HEIGHT_PX, lineHeight: `${EDIT_LINE_HEIGHT_PX}px`, fontSize: EDIT_FONT_SIZE }}>
                            {seg.from + li === cursorLine ? (
                              <span style={{ display: 'block', fontFamily: 'var(--mono)', fontSize: EDIT_FONT_SIZE, lineHeight: `${EDIT_LINE_HEIGHT_PX}px`, color: 'var(--accent)', background: 'rgba(74,222,128,0.06)', borderLeft: '2px solid rgba(74,222,128,0.5)', paddingLeft: 10, marginLeft: -12, borderRadius: '0 4px 4px 0' }}>
                                {l || '\u200b'}
                              </span>
                            ) : (
                              <span dangerouslySetInnerHTML={{ __html: renderLine(l) }} />
                            )}
                          </div>
                        ))}
                      </div>
                    );
                  }
                  if (seg.kind === 'code') {
                    const codeContent = seg.lines.slice(1, -1).join('\n');
                    const lang = seg.lang || '';
                    const fenced = `\`\`\`${lang}\n${codeContent}\n\`\`\``;
                    return (
                      <div key={idx}>
                        <div className="md-preview" style={{ background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 8, padding: '10px 12px', margin: '4px 0' }}>
                          <MarkdownRender value={fenced} />
                        </div>
                      </div>
                    );
                  }
                  if (seg.kind === 'table') {
                    const [header, , ...body] = seg.lines;
                    const heads = header.split('|').map(c => c.trim()).filter(Boolean);
                    const rows = body.map(r => r.split('|').map(c => c.trim()).filter(Boolean));
                    return (
                      <div key={idx}>
                        <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13, margin: '4px 0' }}>
                          <thead><tr>{heads.map((h, i) => <th key={i} style={{ border: '1px solid var(--brd)', padding: '5px 12px', background: 'var(--surface2)', fontFamily: 'var(--mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.04em', color: 'var(--txt2)' }} dangerouslySetInnerHTML={{ __html: parseInline(h) }} />)}</tr></thead>
                          <tbody>{rows.map((r, ri) => <tr key={ri}>{r.map((c, ci) => <td key={ci} style={{ border: '1px solid var(--brd)', padding: '5px 12px' }} dangerouslySetInnerHTML={{ __html: parseInline(c) }} />)}</tr>)}</tbody>
                        </table>
                      </div>
                    );
                  }
                  return null;
                })}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Read mode */}
      {(effectiveMode === 'read' || readOnly) && (
        <div
          ref={readPanelRef}
          className="md-preview"
          tabIndex={readOnly ? undefined : 0}
          onKeyDown={readOnly ? undefined : (e) => {
            if (e.shiftKey && e.key === 'Enter') {
              e.preventDefault();
              setMode('edit');
            }
          }}
          style={{ position: 'relative', flex: 1, overflowY: 'auto', padding: '20px 24px', scrollbarWidth: 'thin', scrollbarColor: 'var(--brd2) transparent', fontSize: 13.5, lineHeight: 1.75, color: 'var(--txt)', outline: 'none' }}
        >
          <MarkdownRender value={value} />
          {streamCursor && <span className="stream-cursor">▋</span>}
        </div>
      )}

      {/* History drawer */}
      {historyOpen && historyKey && (
        <HistoryDrawer historyKey={historyKey} onRestore={(v) => { onChange?.(v); onHistoryToggle?.(false); }} />
      )}
    </div>
  );
}
