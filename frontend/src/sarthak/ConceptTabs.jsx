import { useEffect, useRef, useState, useMemo, useCallback } from 'react';
import { api, fmt } from '../api';
import { useStore } from '../store';
import MarkdownEditor from '../components/MarkdownEditor';
import CodeMirror from '@uiw/react-codemirror';
import { oneDark } from '@codemirror/theme-one-dark';
import { python } from '@codemirror/lang-python';
import { javascript } from '@codemirror/lang-javascript';
import { cpp } from '@codemirror/lang-cpp';
import { java } from '@codemirror/lang-java';
import { php } from '@codemirror/lang-php';
import { StreamLanguage } from '@codemirror/language';
import { shell } from '@codemirror/legacy-modes/mode/shell';
import { perl } from '@codemirror/legacy-modes/mode/perl';
import { ruby } from '@codemirror/legacy-modes/mode/ruby';
import { lua } from '@codemirror/legacy-modes/mode/lua';
import { keymap } from '@codemirror/view';

/** All generated explanations stored in DB. Users can ask custom questions. */
export function ExplainsTab({ spaceId, conceptId, conceptTitle }) {
  const [notes, setNotes]                 = useState([]);
  const [loading, setLoading]             = useState(false);
  const [generating, setGenerating]       = useState(false);
  const [streamContent, setStreamContent] = useState('');
  const [customPrompt, setCustomPrompt]   = useState('');
  const [expandedId, setExpandedId]       = useState(null);
  const scrollRef                         = useRef(null);
  const { ok, err } = useStore();

  useEffect(() => { load(); setStreamContent(''); setExpandedId(null); }, [conceptId]);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api(`/spaces/${spaceId}/notes?type=explain&concept_id=${encodeURIComponent(conceptId || '')}`);
      setNotes(Array.isArray(r) ? r : r.notes || []);
    } catch {}
    setLoading(false);
  };

  const generate = async (prompt = '') => {
    setGenerating(true);
    setStreamContent('');
    setTimeout(() => scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' }), 50);
    try {
      let full = '';
      const url = `/api/spaces/${spaceId}/explain?concept_id=${encodeURIComponent(conceptId || '')}${prompt ? `&prompt=${encodeURIComponent(prompt)}` : ''}`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const reader = r.body.getReader();
      const dec    = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n'); buf = lines.pop() || '';
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const d = line.slice(6); if (d === '[DONE]') break;
          full += d.replace(/\u2028/g, '\n');
          setStreamContent(full);
        }
      }
      setStreamContent('');
      const saved = await api(`/spaces/${spaceId}/notes`, {
        method: 'POST',
        body: JSON.stringify({
          type: 'explain',
          concept_id: conceptId || '',
          title: prompt ? `Q: ${prompt.slice(0, 80)}` : `Explanation: ${conceptTitle || conceptId}`,
          body_md: full,
        }),
      });
      setNotes(n => [saved, ...n]);
      setExpandedId(saved.id);
      setCustomPrompt('');
      ok('Explanation saved');
    } catch (e) { err(e.message); }
    setGenerating(false);
  };

  const deleteNote = async (id) => {
    try {
      await api(`/spaces/${spaceId}/notes/${id}`, { method: 'DELETE' });
      setNotes(n => n.filter(x => x.id !== id));
      if (expandedId === id) setExpandedId(null);
    } catch (e) { err(e.message); }
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0, height: '100%' }}>
      <div style={{ padding: '8px 16px', borderBottom: '1px solid var(--brd)', display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 }}>
        <span style={{ fontSize: 12, color: 'var(--txt3)' }}>{notes.length} saved</span>
        <input className="s-input" style={{ flex: 1, maxWidth: 400, fontSize: 12, padding: '4px 10px' }}
          value={customPrompt}
          onChange={e => setCustomPrompt(e.target.value)}
          placeholder="Ask a custom question about this concept…"
          onKeyDown={e => { if (e.key === 'Enter' && customPrompt.trim()) generate(customPrompt.trim()); }}
        />
        {customPrompt.trim() && (
          <button className="btn btn-muted btn-sm" onClick={() => generate(customPrompt.trim())}>Ask</button>
        )}
        <button className="btn btn-accent btn-sm" style={{ marginLeft: 'auto' }} onClick={() => generate()} disabled={generating}>
          {generating ? <span className="spin" /> : notes.length ? 'New Explanation' : 'Generate'}
        </button>
      </div>

      <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 10, minHeight: 0 }}>
        {generating && streamContent && (
          <div className="card" style={{ borderColor: 'var(--accent-border)' }}>
            <div className="card-hdr" style={{ fontSize: 11, color: 'var(--accent)', display: 'flex', alignItems: 'center', gap: 6 }}>
              <span className="spin" style={{ width: 10, height: 10 }} />
              Generating…
            </div>
            <div className="card-body" style={{ padding: '10px 14px', maxHeight: 400, overflowY: 'auto' }}>
              <MarkdownEditor value={streamContent} readOnly defaultMode="read" streaming={true} />
            </div>
          </div>
        )}

        {loading ? (
          <div className="loading-center"><span className="spin" /></div>
        ) : notes.length === 0 && !streamContent ? (
          <div style={{ color: 'var(--txt3)', textAlign: 'center', padding: '40px 0', fontSize: 13 }}>
            No explanations yet.<br/>
            <span style={{ fontSize: 12 }}>Click <strong>Generate</strong> for an AI explanation, or ask a custom question.</span>
          </div>
        ) : notes.map(n => {
          const isOpen = expandedId === n.id;
          return (
            <div key={n.id} className="card">
              <div
                className="card-hdr"
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', userSelect: 'none' }}
                onClick={() => setExpandedId(isOpen ? null : n.id)}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                  <span style={{ fontSize: 11, color: isOpen ? 'var(--accent)' : 'var(--txt3)', flexShrink: 0 }}>{isOpen ? '▾' : '▸'}</span>
                  <span style={{ fontSize: 12, color: 'var(--txt2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {n.title || 'Explanation'}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                  <span style={{ fontSize: 11, color: 'var(--txt3)' }}>{fmt(n.created_at)}</span>
                  <button
                    className="tb-btn" style={{ color: '#f87171', fontSize: 10 }}
                    onClick={e => { e.stopPropagation(); deleteNote(n.id); }}
                    title="Delete"
                  >x</button>
                </div>
              </div>
              {isOpen && (
                <div className="card-body" style={{ padding: '10px 14px', maxHeight: 600, overflowY: 'auto' }}>
                  <MarkdownEditor value={n.body_md || ''} readOnly defaultMode="read" />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtSecs(s) {
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2,'0')}:${String(s % 60).padStart(2,'0')}`;
}

/** Parse WebVTT cue blocks → [{start, end, text}] */
function parseVTT(vttStr) {
  if (!vttStr || !vttStr.trim()) return [];
  const cues = [];
  const blocks = vttStr.split(/\n\n+/);
  const timeRe = /(\d{2}:\d{2}[:.]\d{2,3})\s*-->\s*(\d{2}:\d{2}[:.]\d{2,3})/;
  for (const block of blocks) {
    const lines = block.trim().split('\n');
    for (let i = 0; i < lines.length; i++) {
      const m = timeRe.exec(lines[i]);
      if (m) {
        const text = lines.slice(i + 1).join(' ').trim();
        if (text) cues.push({ start: vttToSec(m[1]), end: vttToSec(m[2]), text });
        break;
      }
    }
  }
  return cues;
}

function vttToSec(ts) {
  const parts = ts.replace(',', '.').split(':');
  if (parts.length === 3) return +parts[0] * 3600 + +parts[1] * 60 + parseFloat(parts[2]);
  return +parts[0] * 60 + parseFloat(parts[1]);
}

/** Detect if body_md looks like WebVTT */
function isVTT(str) {
  return typeof str === 'string' && (str.startsWith('WEBVTT') || /\d{2}:\d{2}[:.]\d{2}.*-->/.test(str));
}

/** Real-time canvas waveform using Web Audio API */
function WaveformCanvas({ stream, active, height = 48 }) {
  const canvasRef   = useRef(null);
  const rafRef      = useRef(null);
  const analyserRef = useRef(null);
  const ctxRef      = useRef(null);

  useEffect(() => {
    if (!active || !stream) {
      cancelAnimationFrame(rafRef.current);
      const canvas = canvasRef.current;
      if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
      return;
    }
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.8;
    const src = audioCtx.createMediaStreamSource(stream);
    src.connect(analyser);
    analyserRef.current = analyser;
    ctxRef.current = audioCtx;

    const canvas = canvasRef.current;
    const draw = () => {
      if (!canvas) return;
      const W = canvas.width, H = canvas.height;
      const ctx = canvas.getContext('2d');
      const buf = new Uint8Array(analyser.frequencyBinCount);
      analyser.getByteFrequencyData(buf);

      ctx.clearRect(0, 0, W, H);
      const barW = 3, gap = 2, total = barW + gap;
      const bars = Math.floor(W / total);
      const step = Math.floor(buf.length / bars);
      const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#4ade80';

      for (let i = 0; i < bars; i++) {
        const val = buf[i * step] / 255;
        const barH = Math.max(3, val * H * 0.9);
        const y = (H - barH) / 2;
        const alpha = 0.35 + val * 0.65;
        ctx.fillStyle = accent;
        ctx.globalAlpha = alpha;
        ctx.beginPath();
        ctx.roundRect(i * total, y, barW, barH, 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      rafRef.current = requestAnimationFrame(draw);
    };
    draw();

    return () => {
      cancelAnimationFrame(rafRef.current);
      src.disconnect();
      audioCtx.close().catch(() => {});
    };
  }, [active, stream]);

  return (
    <canvas
      ref={canvasRef}
      width={240}
      height={height}
      style={{ display: 'block', width: '100%', height: `${height}px`, borderRadius: 6 }}
    />
  );
}

/** Custom video/audio player with subtitle overlay */
function MediaPlayer({ clip, spaceId, onClose }) {
  const [playing, setPlaying]       = useState(false);
  const [duration, setDuration]     = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [volume, setVolume]         = useState(1);
  const [muted, setMuted]           = useState(false);
  const [expanded, setExpanded]     = useState(false);
  const [activeCue, setActiveCue]   = useState('');
  const mediaRef  = useRef(null);
  const progressRef = useRef(null);

  const cues = useMemo(() => isVTT(clip.body_md) ? parseVTT(clip.body_md) : [], [clip.body_md]);
  const hasSubtitles = cues.length > 0;
  const plainTranscript = !hasSubtitles && clip.body_md ? clip.body_md : null;

  // Sync active cue
  useEffect(() => {
    if (!hasSubtitles) return;
    const cue = cues.find(c => currentTime >= c.start && currentTime < c.end);
    setActiveCue(cue ? cue.text : '');
  }, [currentTime, hasSubtitles]);

  // Sync muted state after mount (browsers ignore the muted attribute on <video> after first render)
  useEffect(() => { if (mediaRef.current) mediaRef.current.muted = muted; }, [muted]);

  const toggle = () => {
    const el = mediaRef.current;
    if (!el) return;
    if (el.paused) { el.play(); setPlaying(true); }
    else           { el.pause(); setPlaying(false); }
  };

  const seek = (e) => {
    if (!duration) return;
    const rect = progressRef.current.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    if (mediaRef.current) mediaRef.current.currentTime = ratio * duration;
  };

  const src = `/api/spaces/${spaceId}/media/${clip.id}/file`;
  const isVideo = clip.type === 'video';

  const playerContent = (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Media area */}
      <div style={{ position: 'relative', flex: isVideo ? 1 : 'none', background: '#000', minHeight: isVideo ? 0 : 'auto' }}>
        {isVideo ? (
          <video
            ref={mediaRef}
            src={src}
            playsInline
            muted={muted}
            style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }}
            onTimeUpdate={e => setCurrentTime(e.target.currentTime)}
            onLoadedMetadata={e => setDuration(e.target.duration)}
            onEnded={() => setPlaying(false)}
          />
        ) : (
          <audio
            ref={mediaRef}
            src={src}
            muted={muted}
            onTimeUpdate={e => setCurrentTime(e.target.currentTime)}
            onLoadedMetadata={e => setDuration(e.target.duration)}
            onEnded={() => setPlaying(false)}
          />
        )}

        {/* Subtitle overlay on video */}
        {isVideo && activeCue && (
          <div style={{
            position: 'absolute', bottom: 12, left: '50%', transform: 'translateX(-50%)',
            background: 'rgba(0,0,0,0.78)', color: '#fff', fontSize: 13, fontWeight: 500,
            padding: '4px 14px', borderRadius: 5, maxWidth: '85%', textAlign: 'center',
            lineHeight: 1.45, pointerEvents: 'none', letterSpacing: 0.01,
          }}>
            {activeCue}
          </div>
        )}

        {/* Audio waveform placeholder for audio type */}
        {!isVideo && (
          <div style={{
            padding: '24px 16px', display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'var(--surface2)', borderBottom: '1px solid var(--brd)', gap: 14,
          }}>
            <div style={{
              width: 44, height: 44, borderRadius: '50%', background: 'var(--accent-dim)',
              border: '1px solid var(--accent-border)', display: 'flex', alignItems: 'center',
              justifyContent: 'center', flexShrink: 0,
            }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2">
                <path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>
              </svg>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--txt)', marginBottom: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {clip.title || 'Audio note'}
              </div>
              <div style={{ fontSize: 11, color: 'var(--txt3)' }}>{fmtSecs(Math.floor(duration))}</div>
            </div>
          </div>
        )}
      </div>

      {/* Controls bar */}
      <div style={{ background: 'var(--surface)', borderTop: '1px solid var(--brd)', padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 8, flexShrink: 0 }}>
        {/* Progress bar */}
        <div
          ref={progressRef}
          onClick={seek}
          style={{ height: 4, background: 'var(--surface3)', borderRadius: 2, cursor: 'pointer', position: 'relative', overflow: 'visible' }}
        >
          <div style={{
            height: '100%', background: 'var(--accent)', borderRadius: 2,
            width: `${duration ? (currentTime / duration) * 100 : 0}%`, transition: 'width .1s linear',
          }} />
          <div style={{
            position: 'absolute', top: '50%', transform: 'translateY(-50%)',
            left: `${duration ? (currentTime / duration) * 100 : 0}%`,
            width: 10, height: 10, borderRadius: '50%', background: 'var(--accent)',
            marginLeft: -5, boxShadow: '0 0 0 2px var(--surface)',
          }} />
        </div>

        {/* Buttons row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button onClick={toggle} style={{
            width: 32, height: 32, borderRadius: '50%', background: 'var(--accent)',
            border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0, color: '#0a0a0a',
          }}>
            {playing ? (
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
            ) : (
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg>
            )}
          </button>

          <span style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--txt2)', minWidth: 72, flexShrink: 0 }}>
            {fmtSecs(Math.floor(currentTime))} / {fmtSecs(Math.floor(duration))}
          </span>

          <div style={{ flex: 1 }} />

          {/* Volume */}
          <button onClick={() => setMuted(m => !m)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: muted ? 'var(--txt3)' : 'var(--txt2)', padding: '4px', display: 'flex', alignItems: 'center' }}>
            {muted ? (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></svg>
            )}
          </button>
          <input type="range" min={0} max={1} step={0.05} value={muted ? 0 : volume}
            onChange={e => { const v = +e.target.value; setVolume(v); if (mediaRef.current) mediaRef.current.volume = v; if (v > 0) setMuted(false); }}
            style={{ width: 60, accentColor: 'var(--accent)', cursor: 'pointer' }}
          />

          {isVideo && (
            <button onClick={() => setExpanded(v => !v)} style={{ background: 'none', border: '1px solid var(--brd2)', borderRadius: 4, cursor: 'pointer', color: 'var(--txt3)', padding: '4px 8px', display: 'flex', alignItems: 'center', fontSize: 10 }}>
              {expanded ? (
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M8 3v3a2 2 0 0 1-2 2H3"/><path d="M21 8h-3a2 2 0 0 1-2-2V3"/><path d="M3 16h3a2 2 0 0 1 2 2v3"/><path d="M16 21v-3a2 2 0 0 1 2-2h3"/></svg>
              ) : (
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/></svg>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Subtitle / transcript panel */}
      {(hasSubtitles || plainTranscript) && (
        <div style={{ borderTop: '1px solid var(--brd)', background: 'var(--bg)', maxHeight: 140, overflowY: 'auto', flexShrink: 0 }}>
          <div style={{ padding: '6px 12px 2px', fontSize: 9.5, letterSpacing: '0.09em', fontWeight: 700, color: 'var(--accent)', textTransform: 'uppercase', borderBottom: '1px solid var(--brd)' }}>
            {hasSubtitles ? 'Subtitles' : 'Transcript'}
          </div>
          <div style={{ padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 4 }}>
            {hasSubtitles ? cues.map((c, i) => (
              <button
                key={i}
                onClick={() => { if (mediaRef.current) { mediaRef.current.currentTime = c.start; mediaRef.current.play(); setPlaying(true); } }}
                style={{
                  display: 'flex', gap: 10, alignItems: 'flex-start', border: 'none',
                  cursor: 'pointer', textAlign: 'left', padding: '3px 6px', borderRadius: 4,
                  background: currentTime >= c.start && currentTime < c.end ? 'var(--accent-dim)' : 'transparent',
                  transition: 'background 150ms',
                }}
              >
                <span style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--accent)', flexShrink: 0, marginTop: 1 }}>{fmtSecs(Math.floor(c.start))}</span>
                <span style={{ fontSize: 12, color: currentTime >= c.start && currentTime < c.end ? 'var(--txt)' : 'var(--txt2)', lineHeight: 1.5 }}>{c.text}</span>
              </button>
            )) : (
              <p style={{ fontSize: 12, color: 'var(--txt2)', whiteSpace: 'pre-wrap', lineHeight: 1.6, margin: 0 }}>{plainTranscript}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );

  if (expanded) {
    return (
      <div
        style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.97)', display: 'flex', flexDirection: 'column' }}
        onClick={e => { if (e.target === e.currentTarget) setExpanded(false); }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 16px', borderBottom: '1px solid rgba(255,255,255,0.08)', flexShrink: 0 }}>
          <span style={{ fontSize: 12.5, color: 'rgba(255,255,255,0.7)', fontWeight: 600 }}>{clip.title || 'Recording'}</span>
          <button onClick={() => setExpanded(false)} style={{ background: 'rgba(255,255,255,0.08)', border: 'none', color: '#fff', borderRadius: 6, padding: '5px 12px', cursor: 'pointer', fontSize: 11.5, fontFamily: 'var(--font)', display: 'flex', alignItems: 'center', gap: 5 }}>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M8 3v3a2 2 0 0 1-2 2H3"/><path d="M21 8h-3a2 2 0 0 1-2-2V3"/><path d="M3 16h3a2 2 0 0 1 2 2v3"/><path d="M16 21v-3a2 2 0 0 1 2-2h3"/></svg>
            Exit
          </button>
        </div>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {playerContent}
        </div>
      </div>
    );
  }

  return playerContent;
}

/** AI feedback panel */
function AnalysisFeedback({ data }) {
  const { feedback = {}, stats = {} } = data;
  const score = feedback.score ?? '—';
  const color = score >= 7 ? 'var(--green)' : score >= 4 ? 'var(--amber)' : 'var(--red)';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 22, fontWeight: 800, color, fontFamily: 'var(--mono)' }}>{score}<span style={{ fontSize: 13, color: 'var(--txt3)' }}>/10</span></span>
        {stats.wpm > 0 && <span style={{ fontSize: 11, color: 'var(--txt3)' }}>{stats.wpm} wpm · {stats.filler_count} fillers ({stats.filler_pct}%)</span>}
      </div>
      {feedback.summary && <p style={{ margin: 0, color: 'var(--txt2)', lineHeight: 1.5 }}>{feedback.summary}</p>}
      {feedback.strengths?.length > 0 && (
        <div><div style={{ fontSize: 10, fontWeight: 700, color: 'var(--green)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>Strengths</div>
          {feedback.strengths.map((s, i) => <div key={i} style={{ color: 'var(--txt2)', marginBottom: 2 }}>· {s}</div>)}
        </div>
      )}
      {feedback.gaps?.length > 0 && (
        <div><div style={{ fontSize: 10, fontWeight: 700, color: 'var(--red)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>Gaps</div>
          {feedback.gaps.map((g, i) => <div key={i} style={{ color: 'var(--txt2)', marginBottom: 2 }}>· {g}</div>)}
        </div>
      )}
      {feedback.next_step && <p style={{ margin: 0, fontSize: 11, color: 'var(--accent)', fontWeight: 600 }}>→ {feedback.next_step}</p>}
    </div>
  );
}

/** Feynman / Teach-It-Back panel */
function FeynmanFeedback({ data }) {
  const score = data.feynman_score ?? '—';
  const color = score >= 7 ? 'var(--green)' : score >= 4 ? 'var(--amber)' : 'var(--red)';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 22, fontWeight: 800, color, fontFamily: 'var(--mono)' }}>{score}<span style={{ fontSize: 13, color: 'var(--txt3)' }}>/10</span></span>
        <span style={{ fontSize: 11, color: 'var(--txt2)', fontWeight: 600 }}>Feynman Score</span>
      </div>
      {data.verdict && <p style={{ margin: 0, color: 'var(--txt2)', lineHeight: 1.5 }}>{data.verdict}</p>}
      {data.covered?.length > 0 && (
        <div><div style={{ fontSize: 10, fontWeight: 700, color: 'var(--green)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>Covered</div>
          {data.covered.map((s, i) => <div key={i} style={{ color: 'var(--txt2)', marginBottom: 2 }}>✓ {s}</div>)}
        </div>
      )}
      {data.missed?.length > 0 && (
        <div><div style={{ fontSize: 10, fontWeight: 700, color: 'var(--amber)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>Missed</div>
          {data.missed.map((s, i) => <div key={i} style={{ color: 'var(--txt2)', marginBottom: 2 }}>· {s}</div>)}
        </div>
      )}
      {data.misconceptions?.length > 0 && (
        <div><div style={{ fontSize: 10, fontWeight: 700, color: 'var(--red)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>Misconceptions</div>
          {data.misconceptions.map((s, i) => <div key={i} style={{ color: 'var(--txt2)', marginBottom: 2 }}>✗ {s}</div>)}
        </div>
      )}
      {data.suggestion && <p style={{ margin: 0, fontSize: 11, color: 'var(--accent)', fontWeight: 600 }}>→ {data.suggestion}</p>}
    </div>
  );
}

/** Single recorded clip row */
function ClipRow({ clip, onRename, onDelete, playing, onSelect, onSubtitle, subtitleLoading, onAnalyze, analyzeLoading, spaceId }) {
  const [editing, setEditing] = useState(false);
  const [name, setName]       = useState(clip.title || (clip.type === 'video' ? 'Video note' : 'Audio note'));
  const inputRef              = useRef(null);

  useEffect(() => { setName(clip.title || (clip.type === 'video' ? 'Video note' : 'Audio note')); }, [clip.title, clip.type]);
  useEffect(() => { if (editing) inputRef.current?.focus(); }, [editing]);

  const commit = () => {
    setEditing(false);
    const trimmed = name.trim();
    if (trimmed && trimmed !== clip.title) onRename(clip.id, trimmed);
  };

  const hasSubtitles = !!(clip.body_md && clip.body_md.trim());

  return (
    <div className={`clip-row${playing ? ' clip-row--playing' : ''}`}>
      <div className="clip-row-icon" style={{ fontSize: 10 }}>
        {clip.type === 'video' ? (
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>
        ) : (
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
        )}
      </div>

      <div className="clip-row-info">
        {editing ? (
          <input
            ref={inputRef}
            className="s-input clip-name-input"
            value={name}
            onChange={e => setName(e.target.value)}
            onBlur={commit}
            onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { setEditing(false); setName(clip.title); } }}
          />
        ) : (
          <span className="clip-name" onDoubleClick={() => setEditing(true)} title="Double-click to rename">
            {name}
          </span>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="clip-meta">{fmt(clip.created_at)}</span>
          {hasSubtitles && (
            <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.06em', color: 'var(--accent)', background: 'var(--accent-dim)', border: '1px solid var(--accent-border)', borderRadius: 3, padding: '1px 5px' }}>
              {isVTT(clip.body_md) ? 'VTT' : 'TXT'}
            </span>
          )}
        </div>
      </div>

      <div className="clip-actions">
        <button className="clip-btn" onClick={() => onSelect(clip)} title={playing ? 'Close' : 'Play'} style={{ background: playing ? 'var(--accent-dim)' : '', borderColor: playing ? 'var(--accent-border)' : '' }}>
          {playing ? (
            <svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
          ) : (
            <svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg>
          )}
        </button>
        <button
          className="clip-btn"
          onClick={() => onSubtitle(clip)}
          title={hasSubtitles ? 'Regenerate subtitles' : 'Generate subtitles (Whisper)'}
          disabled={subtitleLoading}
          style={{ fontSize: 9, width: 34, gap: 3, color: hasSubtitles ? 'var(--accent)' : 'var(--txt3)' }}
        >
          {subtitleLoading ? <span className="spin" style={{ width: 9, height: 9 }} /> : (
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="7" width="20" height="15" rx="2"/><polyline points="17 2 12 7 7 2"/><line x1="8" y1="12" x2="16" y2="12"/><line x1="8" y1="16" x2="14" y2="16"/></svg>
          )}
        </button>
        <button
          className="clip-btn"
          onClick={() => onAnalyze(clip)}
          title="AI feedback"
          disabled={analyzeLoading}
          style={{ color: 'var(--txt3)' }}
        >
          {analyzeLoading ? <span className="spin" style={{ width: 9, height: 9 }} /> : (
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          )}
        </button>
        <button className="clip-btn" onClick={() => setEditing(true)} title="Rename">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        </button>
        <a
          className="clip-btn"
          href={`/api/spaces/${spaceId}/media/${clip.id}/file`}
          download={`${(clip.title || 'recording').replace(/[^a-z0-9_-]/gi, '_')}.webm`}
          title="Download"
          onClick={e => e.stopPropagation()}
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', textDecoration: 'none', color: 'var(--txt3)' }}
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        </a>
        <button className="clip-btn clip-btn--del" onClick={() => onDelete(clip.id)} title="Delete">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
        </button>
      </div>
    </div>
  );
}

/**
 * Redesigned Media Recorder Tab:
 * - Real-time waveform via Web Audio API canvas
 * - Custom video/audio player with subtitle overlay
 * - VTT subtitle display with timeline sync
 * - Clean industrial-minimal aesthetic
 */
export function MediaRecorderTab({ spaceId, conceptId, conceptTitle }) {
  const [mode, setMode]               = useState('audio');
  const [recState, setRecState]       = useState('idle');
  const [secs, setSecs]               = useState(0);
  const [clips, setClips]             = useState([]);
  const [uploading, setUploading]     = useState(false);
  const [pendingName, setPendingName] = useState('');
  const [hasMicPerm, setHasMicPerm]   = useState(true);
  const [subtitleLoadingId, setSubtitleLoadingId] = useState(null);
  const [analyzeLoadingId, setAnalyzeLoadingId]   = useState(null);
  const [analysisResult, setAnalysisResult]       = useState(null); // { clipId, feedback, stats, mode }
  const [selectedClip, setSelectedClip] = useState(null);

  const mediaRef   = useRef(null);
  const chunksRef  = useRef([]);
  const streamRef  = useRef(null);
  const previewRef = useRef(null);
  const timerRef   = useRef(null);
  const mimeRef    = useRef('');
  const { ok, err } = useStore();

  useEffect(() => { loadClips(); return stopAll; }, [conceptId]);

  const stopAll = () => {
    clearInterval(timerRef.current);
    if (mediaRef.current?.state !== 'inactive') mediaRef.current?.stop();
    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;
    setRecState('idle');
    setSecs(0);
  };

  const loadClips = async () => {
    try {
      const r = await api(`/spaces/${spaceId}/media?concept_id=${encodeURIComponent(conceptId || '')}`);
      setClips(Array.isArray(r) ? r.sort((a, b) => b.created_at?.localeCompare(a.created_at)) : []);
    } catch {}
  };

  const startRecording = async () => {
    try {
      const constraints = mode === 'video'
        ? { audio: true, video: { width: { ideal: 1280 }, height: { ideal: 720 }, aspectRatio: 16/9 } }
        : { audio: true };
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      streamRef.current = stream;
      setHasMicPerm(true);

      if (mode === 'video' && previewRef.current) {
        previewRef.current.srcObject = stream;
        previewRef.current.play().catch(() => {});
      }

      chunksRef.current = [];
      const videoMime = ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm']
        .find(t => MediaRecorder.isTypeSupported(t)) || 'video/webm';
      const audioMime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus' : 'audio/webm';
      mimeRef.current = mode === 'video' ? videoMime : audioMime;
      const mr = new MediaRecorder(stream, { mimeType: mimeRef.current });
      mr.ondataavailable = e => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mr.onstop = () => handleStop(stream);
      mediaRef.current = mr;
      mr.start(250);
      setRecState('recording');
      setSecs(0);
      timerRef.current = setInterval(() => setSecs(s => s + 1), 1000);
    } catch (e) {
      if (e.name === 'NotAllowedError') setHasMicPerm(false);
      else err(e.message);
    }
  };

  const pause = () => {
    if (mediaRef.current?.state === 'recording') {
      mediaRef.current.pause();
      clearInterval(timerRef.current);
      setRecState('paused');
    }
  };

  const resume = () => {
    if (mediaRef.current?.state === 'paused') {
      mediaRef.current.resume();
      timerRef.current = setInterval(() => setSecs(s => s + 1), 1000);
      setRecState('recording');
    }
  };

  const stop = () => {
    clearInterval(timerRef.current);
    if (mediaRef.current?.state !== 'inactive') mediaRef.current?.stop();
    if (mode === 'video' && previewRef.current) previewRef.current.srcObject = null;
    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;
    setRecState('idle');
    setSecs(0);
  };

  const handleStop = async (stream) => {
    const blobType = mimeRef.current.startsWith('video') ? 'video/webm' : 'audio/webm';
    const blob     = new Blob(chunksRef.current, { type: blobType });
    chunksRef.current = [];
    stream.getTracks().forEach(t => t.stop());
    const autoName = pendingName.trim() || `${blobType.startsWith('video') ? 'Video' : 'Audio'} — ${conceptTitle || 'note'}`;
    await uploadBlob(blob, blobType, autoName);
    setPendingName('');
  };

  const uploadBlob = async (blob, mimeType, label) => {
    setUploading(true);
    try {
      const isVideo = mimeType.startsWith('video');
      const filename = isVideo ? 'recording_video.webm' : 'recording_audio.webm';
      const typedBlob = new Blob([blob], { type: mimeType });
      const form = new FormData();
      form.append('file', typedBlob, filename);
      const params = new URLSearchParams({ concept_id: conceptId || '', label });
      const res = await fetch(`/api/spaces/${spaceId}/media?${params}`, { method: 'POST', body: form });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      ok(`${isVideo ? 'Video' : 'Audio'} note saved`);
      await loadClips();
    } catch (e) { err(e.message); }
    setUploading(false);
  };

  const generateSubtitle = async (clip) => {
    setSubtitleLoadingId(clip.id);
    try {
      const res = await fetch(
        `/api/spaces/${spaceId}/transcribe-subtitle?note_id=${encodeURIComponent(clip.id)}`,
        { method: 'POST' }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setClips(cs => cs.map(c => c.id === clip.id ? { ...c, body_md: data.transcript } : c));
      if (selectedClip?.id === clip.id) setSelectedClip(c => ({ ...c, body_md: data.transcript }));
      ok('Subtitles generated');
    } catch (e) { err(e.message); }
    setSubtitleLoadingId(null);
  };

  const selectClip = (clip) => {
    if (selectedClip?.id === clip.id) { setSelectedClip(null); return; }
    setSelectedClip(clip);
    if (analysisResult?.clipId !== clip.id) setAnalysisResult(null);
  };

  const analyzeClip = async (clip, analysisMode = 'analyze') => {
    setAnalyzeLoadingId(clip.id);
    setAnalysisResult(null);
    if (selectedClip?.id !== clip.id) setSelectedClip(clip);
    try {
      const endpoint = analysisMode === 'feynman' ? 'teach-it-back' : 'analyze';
      const res = await fetch(`/api/spaces/${spaceId}/media/${clip.id}/${endpoint}`, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setAnalysisResult({ clipId: clip.id, mode: analysisMode, ...data });
    } catch (e) { err(e.message); }
    setAnalyzeLoadingId(null);
  };

  const renameClip = async (id, title) => {
    try {
      const updated = await api(`/spaces/${spaceId}/media/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) });
      setClips(cs => cs.map(c => c.id === id ? { ...c, title: updated.title } : c));
      if (selectedClip?.id === id) setSelectedClip(c => ({ ...c, title: updated.title }));
    } catch (e) { err(e.message); }
  };

  const deleteClip = async (id) => {
    try {
      await api(`/spaces/${spaceId}/media/${id}`, { method: 'DELETE' });
      if (selectedClip?.id === id) setSelectedClip(null);
      setClips(cs => cs.filter(c => c.id !== id));
      ok('Deleted');
    } catch (e) { err(e.message); }
  };

  const isRecording = recState === 'recording';
  const isPaused    = recState === 'paused';
  const isActive    = isRecording || isPaused;
  const modeClips   = clips.filter(c => c.type === mode);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0 }}>

      {/* ── Recorder panel ── */}
      <div style={{ flexShrink: 0, borderBottom: '1px solid var(--brd)', background: 'var(--surface)' }}>

        {/* Top controls bar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', flexWrap: 'wrap' }}>
          {/* Mode selector */}
          <div style={{ display: 'flex', background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 7, padding: 3, gap: 2, flexShrink: 0 }}>
            {[
              { id: 'audio', label: 'Voice', icon: <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/></svg> },
              { id: 'video', label: 'Video', icon: <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg> },
            ].map(m => (
              <button
                key={m.id}
                onClick={() => { if (!isActive) setMode(m.id); }}
                disabled={isActive}
                style={{
                  minWidth: 62, padding: '5px 10px', borderRadius: 5, border: 'none',
                  background: mode === m.id ? 'var(--accent)' : 'none',
                  color: mode === m.id ? '#0a0a0a' : 'var(--txt2)',
                  fontSize: 12, fontWeight: 600, cursor: isActive ? 'not-allowed' : 'pointer',
                  display: 'flex', alignItems: 'center', gap: 5, justifyContent: 'center',
                  fontFamily: 'var(--font)', transition: 'background 150ms, color 150ms',
                  opacity: isActive ? 0.6 : 1,
                }}
              >
                {m.icon}{m.label}
              </button>
            ))}
          </div>

          {/* Waveform or timer */}
          <div style={{ flex: 1, minWidth: 120, maxWidth: 260 }}>
            {mode === 'audio' && isActive ? (
              <WaveformCanvas stream={streamRef.current} active={isRecording} height={36} />
            ) : (
              <div style={{
                display: 'flex', alignItems: 'center', gap: 6,
                fontFamily: 'var(--mono)', fontSize: 14, fontWeight: 700,
                color: isActive ? 'var(--txt)' : 'var(--txt3)', letterSpacing: '0.06em',
              }}>
                {isActive && (
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--red)', display: 'inline-block', animation: 'rec-pulse 1.1s ease-in-out infinite', flexShrink: 0 }} />
                )}
                {fmtSecs(secs)}
              </div>
            )}
          </div>

          {/* Buttons */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginLeft: 'auto', flexShrink: 0 }}>
            {!isActive ? (
              <button
                onClick={startRecording}
                disabled={uploading}
                style={{
                  display: 'flex', alignItems: 'center', gap: 7,
                  background: 'var(--accent)', color: '#0a0a0a',
                  border: 'none', borderRadius: 7, padding: '7px 16px',
                  fontSize: 12.5, fontWeight: 700, cursor: uploading ? 'not-allowed' : 'pointer',
                  fontFamily: 'var(--font)', opacity: uploading ? 0.5 : 1, transition: 'opacity 150ms',
                }}
              >
                {uploading ? (
                  <span className="spin" style={{ width: 12, height: 12 }} />
                ) : (
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#0a0a0a', display: 'inline-block' }} />
                )}
                {uploading ? 'Saving…' : `Record ${mode === 'audio' ? 'Voice' : 'Video'}`}
              </button>
            ) : (
              <>
                {isRecording ? (
                  <button onClick={pause} style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'rgba(251,191,36,.12)', color: 'var(--amber)', border: '1px solid rgba(251,191,36,.35)', borderRadius: 7, padding: '6px 13px', fontSize: 12.5, fontWeight: 600, cursor: 'pointer', fontFamily: 'var(--font)' }}>
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
                    Pause
                  </button>
                ) : (
                  <button onClick={resume} style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'var(--accent-dim)', color: 'var(--accent)', border: '1px solid var(--accent-border)', borderRadius: 7, padding: '6px 13px', fontSize: 12.5, fontWeight: 600, cursor: 'pointer', fontFamily: 'var(--font)' }}>
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg>
                    Resume
                  </button>
                )}
                <button onClick={stop} style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'rgba(248,113,113,.1)', color: 'var(--red)', border: '1px solid rgba(248,113,113,.3)', borderRadius: 7, padding: '6px 13px', fontSize: 12.5, fontWeight: 600, cursor: 'pointer', fontFamily: 'var(--font)' }}>
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="3" width="18" height="18" rx="2"/></svg>
                  Stop & Save
                </button>
              </>
            )}
          </div>
        </div>

        {/* Name input row */}
        {isActive && (
          <div style={{ padding: '0 14px 10px' }}>
            <input
              className="s-input"
              style={{ fontSize: 12.5, padding: '6px 10px' }}
              placeholder={`Name this ${mode} note (optional)…`}
              value={pendingName}
              onChange={e => setPendingName(e.target.value)}
            />
          </div>
        )}

        {/* Small video preview — fixed height so clip history stays visible */}
        {mode === 'video' && (
          <div style={{
            margin: '0 14px 10px', position: 'relative',
            borderRadius: 8, background: '#0a0a0a', overflow: 'hidden',
            border: '1px solid var(--brd2)', height: 130,
            boxShadow: isActive ? '0 0 0 2px var(--accent-border), 0 2px 12px rgba(0,0,0,0.45)' : '0 1px 6px rgba(0,0,0,0.3)',
            transition: 'box-shadow 250ms', flexShrink: 0,
          }}>
            <video
              ref={previewRef} muted playsInline
              style={{ width: '100%', height: '100%', objectFit: 'cover', display: isActive ? 'block' : 'none', borderRadius: 8 }}
            />
            {!isActive && (
              <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 6, background: 'var(--surface2)' }}>
                <div style={{ width: 36, height: 36, borderRadius: '50%', background: 'var(--surface3)', border: '1px solid var(--brd2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--txt3)" strokeWidth="1.5"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>
                </div>
                <span style={{ fontSize: 10.5, color: 'var(--txt3)' }}>Preview starts when recording</span>
              </div>
            )}
            {isRecording && (
              <div style={{ position: 'absolute', top: 7, right: 9, display: 'flex', alignItems: 'center', gap: 4, background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(6px)', borderRadius: 5, padding: '3px 8px', border: '1px solid rgba(248,113,113,0.25)' }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#f87171', display: 'inline-block', animation: 'recDot 1s ease-in-out infinite alternate', flexShrink: 0 }} />
                <span style={{ fontSize: 10, color: '#fff', fontFamily: 'var(--mono)', letterSpacing: '0.04em', fontWeight: 600 }}>{fmtSecs(secs)}</span>
              </div>
            )}
            {isPaused && (
              <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(2px)' }}>
                <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.7)', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>Paused</span>
              </div>
            )}
          </div>
        )}

        {!hasMicPerm && (
          <div style={{ margin: '0 14px 10px', padding: '8px 12px', borderRadius: 6, background: 'rgba(248,113,113,.1)', border: '1px solid rgba(248,113,113,.3)', color: 'var(--red)', fontSize: 12 }}>
            Microphone access denied — check browser permissions.
          </div>
        )}
      </div>

      {/* ── Content area: list + player ── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>

        {/* Clip list */}
        <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden', width: selectedClip ? 240 : '100%', flexShrink: 0, borderRight: selectedClip ? '1px solid var(--brd)' : 'none', transition: 'width 200ms ease' }}>
          {/* List header */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 14px', borderBottom: '1px solid var(--brd)', fontSize: 10.5, fontWeight: 700, color: 'var(--txt2)', textTransform: 'uppercase', letterSpacing: '0.06em', flexShrink: 0, background: 'var(--surface)' }}>
            <span style={{ flex: 1 }}>{mode === 'video' ? 'Videos' : 'Voice'}</span>
            <span style={{ color: 'var(--txt3)', fontWeight: 500 }}>{modeClips.length}</span>
          </div>

          <div style={{ flex: 1, overflowY: 'auto' }}>
            {modeClips.length === 0 ? (
              <div style={{ padding: '32px 14px', textAlign: 'center', fontSize: 12.5, color: 'var(--txt3)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--brd2)" strokeWidth="1.5">
                  {mode === 'video'
                    ? <><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></>
                    : <><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/></>
                  }
                </svg>
                No {mode === 'video' ? 'video' : 'voice'} recordings yet.
              </div>
            ) : modeClips.map(clip => (
              <ClipRow
                key={clip.id}
                clip={clip}
                playing={selectedClip?.id === clip.id}
                onSelect={selectClip}
                onRename={renameClip}
                onDelete={deleteClip}
                onSubtitle={generateSubtitle}
                subtitleLoading={subtitleLoadingId === clip.id}
                onAnalyze={analyzeClip}
                analyzeLoading={analyzeLoadingId === clip.id}
                spaceId={spaceId}
              />
            ))}
          </div>
        </div>

        {/* Player panel */}
        {selectedClip && (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0, background: 'var(--bg)' }}>
            {/* Player header */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', borderBottom: '1px solid var(--brd)', background: 'var(--surface)', flexShrink: 0 }}>
              <span style={{ flex: 1, fontSize: 12, fontWeight: 600, color: 'var(--txt)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {selectedClip.title || 'Recording'}
              </span>
              <button
                onClick={() => setSelectedClip(null)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--txt3)', padding: '2px', display: 'flex', alignItems: 'center', flexShrink: 0 }}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>

            <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              <MediaPlayer key={selectedClip.id} clip={selectedClip} spaceId={spaceId} />
              {/* Analysis toolbar */}
              <div style={{ display: 'flex', gap: 6, padding: '6px 12px', borderTop: '1px solid var(--brd)', background: 'var(--surface)', flexShrink: 0 }}>
                <button
                  onClick={() => analyzeClip(selectedClip, 'analyze')}
                  disabled={!!analyzeLoadingId}
                  style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '4px 10px', borderRadius: 5, border: '1px solid var(--brd)', background: 'none', color: 'var(--txt2)', fontSize: 11, cursor: 'pointer', fontFamily: 'var(--font)' }}
                >
                  {analyzeLoadingId === selectedClip.id ? <span className="spin" style={{ width: 9, height: 9 }} /> : '✦'} AI Feedback
                </button>
                <button
                  onClick={() => analyzeClip(selectedClip, 'feynman')}
                  disabled={!!analyzeLoadingId}
                  style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '4px 10px', borderRadius: 5, border: '1px solid var(--brd)', background: 'none', color: 'var(--txt2)', fontSize: 11, cursor: 'pointer', fontFamily: 'var(--font)' }}
                >
                  {analyzeLoadingId === selectedClip.id ? <span className="spin" style={{ width: 9, height: 9 }} /> : '🧠'} Teach-It-Back
                </button>
                {analysisResult?.clipId === selectedClip.id && (
                  <button onClick={() => setAnalysisResult(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--txt3)', fontSize: 11, fontFamily: 'var(--font)' }}>✕ close</button>
                )}
              </div>
              {/* Analysis result panel */}
              {analysisResult?.clipId === selectedClip.id && (
                <div style={{ padding: '10px 14px', borderTop: '1px solid var(--brd)', background: 'var(--bg)', overflowY: 'auto', maxHeight: 260, fontSize: 12 }}>
                  {analysisResult.mode === 'analyze' ? (
                    <AnalysisFeedback data={analysisResult} />
                  ) : (
                    <FeynmanFeedback data={analysisResult} />
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <style>{`
        @keyframes recDot { from { opacity: 1; } to { opacity: 0.2; } }
      `}</style>
    </div>
  );
}

// ── Code Playground helpers ─────────────────────────────────────────────────

// Module-level language cache — fetched once per app session
let _langsCache = null;
let _langsCacheKey = null;

const LANG_DEFAULTS = {
  python:     'print("Hello, World!")',
  javascript: 'console.log("Hello, World!");',
  typescript: 'const msg: string = "Hello, World!";\nconsole.log(msg);',
  bash:       'echo "Hello, World!"',
  perl:       'print "Hello, World!\\n";',
  ruby:       'puts "Hello, World!"',
  php:        '<?php\necho "Hello, World!\\n";',
  lua:        'print("Hello, World!")',
  c:          '#include <stdio.h>\nint main() {\n    printf("Hello, World!\\n");\n    return 0;\n}',
  cpp:        '#include <iostream>\nint main() {\n    std::cout << "Hello, World!" << std::endl;\n    return 0;\n}',
  java:       'System.out.println("Hello, World!");',
};

function outputColor(exitCode, hasStderr) {
  if (exitCode === 124) return 'var(--amber)';
  if (exitCode !== 0) return 'var(--red)';
  if (hasStderr) return 'var(--amber)';
  return 'var(--accent)';
}

const _LANG_EXTS = {
  python:     () => [python()],
  javascript: () => [javascript()],
  typescript: () => [javascript({ typescript: true })],
  bash:       () => [StreamLanguage.define(shell)],
  perl:       () => [StreamLanguage.define(perl)],
  ruby:       () => [StreamLanguage.define(ruby)],
  php:        () => [php()],
  lua:        () => [StreamLanguage.define(lua)],
  c:          () => [cpp()],
  cpp:        () => [cpp()],
  java:       () => [java()],
};

function CodeEditor({ value, onChange, language, onRun, disabled }) {
  const extensions = useMemo(() => [
    ...(_LANG_EXTS[language]?.() ?? []),
    keymap.of([{ key: 'Ctrl-Enter', mac: 'Cmd-Enter', run: () => { onRun?.(); return true; } }]),
  ], [language, onRun]);

  return (
    <CodeMirror
      value={value}
      height="100%"
      extensions={extensions}
      theme={oneDark}
      onChange={onChange}
      editable={!disabled}
      style={{ flex: 1, overflow: 'hidden', fontSize: 13 }}
      basicSetup={{ lineNumbers: true, foldGutter: false, autocompletion: true, indentOnInput: true }}
    />
  );
}

/** Code Playground tab — real backend execution */
export function PlaygroundTab({ spaceId, conceptId, conceptTitle }) {
  const [langs, setLangs]               = useState([]);
  // Bug 2 fix: initialize lang from localStorage, update after fetch
  const [lang, setLang]                 = useState(() => localStorage.getItem('pg_lang') || 'python');
  // Per-language draft map (Bug 3 improvement)
  const draftRef                        = useRef({});
  const [code, setCode]                 = useState('');
  const [stdin, setStdin]               = useState('');
  const [showStdin, setShowStdin]       = useState(false);
  const [running, setRunning]           = useState(false);
  const [result, setResult]             = useState(null);
  const [snippets, setSnippets]         = useState([]);
  const [showSnippets, setShowSnippets] = useState(false);
  const [showHistory, setShowHistory]   = useState(false);
  const [history, setHistory]           = useState([]);
  const [saving, setSaving]             = useState(false);
  const [snippetName, setSnippetName]   = useState('');
  // Multi-file: second helper file
  const [helperCode, setHelperCode]     = useState('');
  const [showHelper, setShowHelper]     = useState(false);
  const [helperTab, setHelperTab]       = useState(false); // true = viewing helper
  const [explaining, setExplaining]     = useState(false);
  const [explanation, setExplanation]   = useState(null);
  const [generating, setGenerating]     = useState(false);
  const [execMs, setExecMs]             = useState(null);
  // Resizable output panel
  const [outputH, setOutputH]           = useState(280);
  const outputRef     = useRef(null);
  const dragRef       = useRef(null);
  const { ok, err }   = useStore();

  const cid = conceptId || '';

  // Load languages once per spaceId (module-level cache)
  useEffect(() => {
    const cacheKey = spaceId;
    if (_langsCache && _langsCacheKey === cacheKey) {
      setLangs(_langsCache);
      // Bug 2 fix: only switch if current lang not available
      if (!_langsCache.find(r => r.id === lang) && _langsCache.length)
        setLang(_langsCache[0].id);
      return;
    }
    api(`/spaces/${spaceId}/playground/languages`)
      .then(rows => {
        const list = Array.isArray(rows) ? rows : [];
        _langsCache = list;
        _langsCacheKey = cacheKey;
        setLangs(list);
        setLang(prev => {
          if (list.find(r => r.id === prev)) return prev;
          return list[0]?.id || prev;
        });
      })
      .catch(() => {});
  }, [spaceId]);

  // Bug 2 fix: initialize code from draft or default when lang is ready
  useEffect(() => {
    const draft = draftRef.current[lang];
    setCode(draft !== undefined ? draft : (LANG_DEFAULTS[lang] || ''));
    setResult(null);
    setExplanation(null);
    setExecMs(null);
    localStorage.setItem('pg_lang', lang);
  }, [lang]);

  // Bug 8 fix: wrap loadSnippets with useCallback capturing cid
  const loadSnippets = useCallback(async () => {
    try {
      const rows = await api(`/spaces/${spaceId}/playground/snippets?concept_id=${encodeURIComponent(cid)}`);
      setSnippets(Array.isArray(rows) ? rows : []);
    } catch {}
  }, [spaceId, cid]);

  const loadHistory = useCallback(async () => {
    try {
      const rows = await api(`/spaces/${spaceId}/playground/history?concept_id=${encodeURIComponent(cid)}&limit=20`);
      setHistory(Array.isArray(rows) ? rows : []);
    } catch {}
  }, [spaceId, cid]);

  useEffect(() => { loadSnippets(); }, [loadSnippets]);

  const run = useCallback(async () => {
    if (!code.trim() || running) return;
    setRunning(true);
    setResult(null);
    setExplanation(null);
    setExecMs(null);
    const t0 = Date.now();
    try {
      const body = { language: lang, code, stdin: showStdin ? stdin : '', concept_id: cid };
      if (showHelper && helperCode.trim()) body.helper_code = helperCode;
      const res = await api(`/spaces/${spaceId}/playground/run`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      setExecMs(Date.now() - t0);
      setResult(res);
      requestAnimationFrame(() => outputRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
    } catch (e) { err(e.message); }
    setRunning(false);
  }, [code, lang, helperCode, showHelper, stdin, showStdin, running, spaceId, cid]);

  // Ctrl+S → save snippet (scoped to playground container)
  useEffect(() => {
    const handler = (e) => {
      if (!e.target.closest('[data-playground]')) return;
      if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); saveSnippet(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [run]);

  const explainError = async () => {
    if (!result) return;
    setExplaining(true);
    setExplanation(null);
    try {
      const res = await api(`/spaces/${spaceId}/playground/explain-error`, {
        method: 'POST',
        body: JSON.stringify({ language: lang, code, stderr: result.stderr, stdout: result.stdout }),
      });
      setExplanation(res.explanation);
    } catch (e) { err(e.message); }
    setExplaining(false);
  };

  const generateCode = async () => {
    setGenerating(true);
    try {
      const res = await api(`/spaces/${spaceId}/playground/generate-code`, {
        method: 'POST',
        body: JSON.stringify({ language: lang, concept_title: conceptTitle || '', concept_id: cid }),
      });
      const generated = res.code || '';
      draftRef.current[lang] = generated;
      setCode(generated);
      setResult(null);
    } catch (e) { err(e.message); }
    setGenerating(false);
  };

  const saveSnippet = async () => {
    if (!code.trim()) return;
    const name = snippetName.trim() || `${lang} — ${conceptTitle || 'snippet'}`;
    // Prepend language header so body_md is self-describing
    const COMMENT = { python:'#', bash:'#', perl:'#', ruby:'#', lua:'--' };
    const marker = COMMENT[lang] || '//';
    const bodyWithHeader = `${marker} language: ${lang}\n${code}`;
    setSaving(true);
    try {
      const saved = await api(`/spaces/${spaceId}/playground/snippets`, {
        method: 'POST',
        body: JSON.stringify({ concept_id: cid, language: lang, title: name, code: bodyWithHeader }),
      });
      setSnippets(s => [saved, ...s]);
      setSnippetName('');
      ok('Snippet saved');
    } catch (e) { err(e.message); }
    setSaving(false);
  };

  const updateSnippet = async (sn) => {
    try {
      const COMMENT = { python:'#', bash:'#', perl:'#', ruby:'#', lua:'--' };
      const marker = COMMENT[lang] || '//';
      const bodyWithHeader = `${marker} language: ${lang}\n${code}`;
      const updated = await api(`/spaces/${spaceId}/playground/snippets/${sn.id}`, {
        method: 'PUT',
        body: JSON.stringify({ language: lang, code: bodyWithHeader }),
      });
      setSnippets(s => s.map(x => x.id === sn.id ? updated : x));
      ok('Snippet updated');
    } catch (e) { err(e.message); }
  };

  const loadSnippet = (sn) => {
    // Language stored as first line comment: // language: python\n...
    const body = sn.body_md || '';
    const headerMatch = body.match(/^(?:\/\/|#|--) language: (\w+)\n/);
    const titleMatch  = sn.title?.match(/^\[(\w+)\]\s*(.*)$/);
    const snLangId = headerMatch?.[1] || titleMatch?.[1];
    if (snLangId && langs.find(l => l.id === snLangId)) setLang(snLangId);
    const newCode = headerMatch ? body.slice(body.indexOf('\n') + 1) : body;
    draftRef.current[snLangId || lang] = newCode;
    setCode(newCode);
    setResult(null);
    setShowSnippets(false);
  };

  const deleteSnippet = async (id) => {
    try {
      await api(`/spaces/${spaceId}/playground/snippets/${id}`, { method: 'DELETE' });
      setSnippets(s => s.filter(x => x.id !== id));
    } catch (e) { err(e.message); }
  };

  // Track code changes in draft
  const handleCodeChange = (v) => {
    draftRef.current[lang] = v;
    setCode(v);
  };

  // Drag-to-resize output panel
  const startDrag = (e) => {
    e.preventDefault();
    const startY = e.clientY;
    const startH = outputH;
    const onMove = (ev) => setOutputH(Math.max(80, Math.min(700, startH + (startY - ev.clientY))));
    const onUp   = () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  const exitColor = result ? outputColor(result.exit_code, !!result.stderr?.trim()) : 'var(--txt3)';
  const hasError  = result && result.exit_code !== 0;

  return (
    <div data-playground="1" style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0 }}>

      {/* Toolbar */}
      <div style={{ flexShrink: 0, borderBottom: '1px solid var(--brd)', padding: '6px 12px', display: 'flex', alignItems: 'center', gap: 8, background: 'var(--surface)', flexWrap: 'wrap' }}>
        <select
          value={lang}
          onChange={e => setLang(e.target.value)}
          disabled={running}
          style={{ background: 'var(--surface2)', border: '1px solid var(--brd)', borderRadius: 5, color: 'var(--txt)', padding: '4px 8px', fontSize: 12, fontFamily: 'var(--font)', cursor: 'pointer' }}
        >
          {(langs.length ? langs : Object.keys(LANG_DEFAULTS).map(id => ({ id, label: id }))).map(l => (
            <option key={l.id} value={l.id}>{l.label || l.id}</option>
          ))}
        </select>

        <button
          onClick={run}
          disabled={running || !code.trim()}
          style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'var(--accent)', color: '#0a0a0a', border: 'none', borderRadius: 6, padding: '5px 14px', fontSize: 12.5, fontWeight: 700, cursor: running ? 'not-allowed' : 'pointer', fontFamily: 'var(--font)', opacity: running ? 0.6 : 1 }}
        >
          {running ? <span className="spin" style={{ width: 11, height: 11 }} /> : <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21" /></svg>}
          {running ? 'Running…' : 'Run'}
        </button>

        <span style={{ fontSize: 10.5, color: 'var(--txt3)' }}>Ctrl+Enter</span>

        <button
          onClick={generateCode}
          disabled={generating || running}
          style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, padding: '4px 9px', borderRadius: 5, border: '1px solid var(--brd)', background: 'none', color: 'var(--txt2)', cursor: 'pointer', fontFamily: 'var(--font)' }}
          title="AI: generate starter code for this concept"
        >
          {generating ? <span className="spin" style={{ width: 9, height: 9 }} /> : '✦'} Generate
        </button>

        {/* Multi-file helper toggle (C/C++/Java benefit most) */}
        <button
          onClick={() => setShowHelper(v => !v)}
          style={{ fontSize: 11, padding: '4px 9px', borderRadius: 5, border: `1px solid ${showHelper ? 'var(--accent-border)' : 'var(--brd)'}`, background: showHelper ? 'var(--accent-dim)' : 'none', color: showHelper ? 'var(--accent)' : 'var(--txt3)', cursor: 'pointer', fontFamily: 'var(--font)' }}
          title="Add a helper file (multi-file mode)"
        >+ helper</button>

        {execMs !== null && (
          <span style={{ fontSize: 10.5, color: 'var(--txt3)', fontFamily: 'var(--mono)' }}>{execMs}ms</span>
        )}

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
          <button
            onClick={() => setShowStdin(v => !v)}
            style={{ fontSize: 11, padding: '4px 9px', borderRadius: 5, border: `1px solid ${showStdin ? 'var(--accent-border)' : 'var(--brd)'}`, background: showStdin ? 'var(--accent-dim)' : 'none', color: showStdin ? 'var(--accent)' : 'var(--txt3)', cursor: 'pointer', fontFamily: 'var(--font)' }}
          >stdin</button>
          <button
            onClick={() => { setShowSnippets(v => !v); setShowHistory(false); }}
            style={{ fontSize: 11, padding: '4px 9px', borderRadius: 5, border: `1px solid ${showSnippets ? 'var(--accent-border)' : 'var(--brd)'}`, background: showSnippets ? 'var(--accent-dim)' : 'none', color: showSnippets ? 'var(--accent)' : 'var(--txt3)', cursor: 'pointer', fontFamily: 'var(--font)' }}
          >Snippets ({snippets.length})</button>
          <button
            onClick={() => { setShowHistory(v => !v); setShowSnippets(false); if (!showHistory) loadHistory(); }}
            style={{ fontSize: 11, padding: '4px 9px', borderRadius: 5, border: `1px solid ${showHistory ? 'var(--accent-border)' : 'var(--brd)'}`, background: showHistory ? 'var(--accent-dim)' : 'none', color: showHistory ? 'var(--accent)' : 'var(--txt3)', cursor: 'pointer', fontFamily: 'var(--font)' }}
          >History</button>
        </div>
      </div>

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
        {/* Editor column */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0, borderRight: (showSnippets || showHistory) ? '1px solid var(--brd)' : 'none' }}>
          {showStdin && (
            <div style={{ flexShrink: 0, borderBottom: '1px solid var(--brd)', padding: '6px 12px', background: 'var(--surface)' }}>
              <div style={{ fontSize: 10.5, color: 'var(--txt3)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 700 }}>stdin</div>
              <textarea value={stdin} onChange={e => setStdin(e.target.value)} placeholder="Input fed to stdin…"
                style={{ width: '100%', height: 60, resize: 'vertical', fontFamily: 'var(--mono)', fontSize: 12, padding: '6px 8px', background: 'var(--bg)', border: '1px solid var(--brd)', borderRadius: 5, color: 'var(--txt)', outline: 'none', boxSizing: 'border-box' }} />
            </div>
          )}

          {/* File tabs when helper is active */}
          {showHelper && (
            <div style={{ flexShrink: 0, display: 'flex', borderBottom: '1px solid var(--brd)', background: 'var(--surface)' }}>
              {['main', 'helper'].map(tab => (
                <button
                  key={tab}
                  onClick={() => setHelperTab(tab === 'helper')}
                  style={{ padding: '5px 14px', fontSize: 11.5, border: 'none', borderBottom: `2px solid ${helperTab === (tab === 'helper') ? 'var(--accent)' : 'transparent'}`, background: 'none', color: helperTab === (tab === 'helper') ? 'var(--accent)' : 'var(--txt3)', cursor: 'pointer', fontFamily: 'var(--font)', fontWeight: helperTab === (tab === 'helper') ? 700 : 400 }}
                >{tab === 'main' ? `main.${lang}` : `helper.${lang}`}</button>
              ))}
            </div>
          )}

          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0, borderBottom: result ? '1px solid var(--brd)' : 'none' }}>
            {(!showHelper || !helperTab) && <CodeEditor value={code} onChange={handleCodeChange} language={lang} onRun={run} disabled={running} />}
            {showHelper && helperTab && <CodeEditor value={helperCode} onChange={v => setHelperCode(v)} language={lang} onRun={run} disabled={running} />}
          </div>

          {/* Drag handle */}
          {result && (
            <div
              onMouseDown={startDrag}
              style={{ height: 4, background: 'var(--brd)', cursor: 'row-resize', flexShrink: 0, userSelect: 'none' }}
            />
          )}

          {/* Output panel */}
          {result && (
            <div ref={outputRef} style={{ flexShrink: 0, height: outputH, overflowY: 'auto', background: 'var(--bg)', fontFamily: 'var(--mono)', fontSize: 12.5 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 12px', borderBottom: '1px solid var(--brd)', background: 'var(--surface)', fontSize: 11, position: 'sticky', top: 0, zIndex: 1 }}>
                <span style={{ color: exitColor, fontWeight: 700 }}>
                  exit {result.exit_code}{result.exit_code === 124 && ' (timeout)'}
                </span>
                {result.error && <span style={{ color: 'var(--red)' }}>{result.error}</span>}
                {execMs !== null && <span style={{ color: 'var(--txt3)', fontFamily: 'var(--mono)' }}>{execMs}ms</span>}
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
                  {hasError && (
                    <button
                      onClick={explainError}
                      disabled={explaining}
                      style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10.5, padding: '3px 8px', borderRadius: 4, border: '1px solid var(--brd)', background: 'none', color: 'var(--amber)', cursor: 'pointer', fontFamily: 'var(--font)' }}
                    >
                      {explaining ? <span className="spin" style={{ width: 8, height: 8 }} /> : '✦'} Explain error
                    </button>
                  )}
                  <button
                    onClick={() => { navigator.clipboard.writeText((result.stdout || '') + (result.stderr || '')); ok('Copied'); }}
                    style={{ fontSize: 10.5, padding: '3px 7px', borderRadius: 4, border: '1px solid var(--brd)', background: 'none', color: 'var(--txt3)', cursor: 'pointer', fontFamily: 'var(--font)' }}
                    title="Copy output"
                  >Copy</button>
                  <button
                    onClick={() => { setResult(null); setExplanation(null); setExecMs(null); }}
                    style={{ fontSize: 10.5, padding: '3px 7px', borderRadius: 4, border: '1px solid var(--brd)', background: 'none', color: 'var(--txt3)', cursor: 'pointer', fontFamily: 'var(--font)' }}
                    title="Clear output"
                  >Clear</button>
                </div>
              </div>

              {result.stdout && (
                <div style={{ padding: '8px 12px', borderBottom: result.stderr ? '1px solid var(--brd)' : 'none' }}>
                  <div style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>stdout</div>
                  <pre style={{ margin: 0, color: 'var(--txt)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.55 }}>{result.stdout}</pre>
                </div>
              )}
              {result.stderr && (
                <div style={{ padding: '8px 12px' }}>
                  <div style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--amber)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>stderr</div>
                  <pre style={{ margin: 0, color: 'var(--amber)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.55, opacity: 0.85 }}>{result.stderr}</pre>
                </div>
              )}
              {!result.stdout && !result.stderr && (
                <div style={{ padding: '10px 12px', color: 'var(--txt3)', fontStyle: 'italic' }}>(no output)</div>
              )}

              {/* AI error explanation */}
              {explanation && (
                <div style={{ padding: '8px 12px', borderTop: '1px solid var(--brd)', background: 'var(--surface)' }}>
                  <div style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>AI Fix Suggestion</div>
                  <MarkdownEditor value={explanation} readOnly defaultMode="read" />
                </div>
              )}
            </div>
          )}

          {/* Save bar */}
          <div style={{ flexShrink: 0, borderTop: '1px solid var(--brd)', padding: '6px 12px', display: 'flex', gap: 6, alignItems: 'center', background: 'var(--surface)' }}>
            <input
              className="s-input"
              style={{ flex: 1, maxWidth: 280, fontSize: 12, padding: '4px 8px' }}
              placeholder="Save snippet name… (Ctrl+S)"
              value={snippetName}
              onChange={e => setSnippetName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') saveSnippet(); }}
            />
            <button className="btn btn-muted btn-sm" style={{ fontSize: 11 }} onClick={saveSnippet} disabled={saving || !code.trim()}>
              {saving ? <span className="spin" /> : 'Save'}
            </button>
          </div>
        </div>

        {/* Snippets sidebar */}
        {showSnippets && (
          <div style={{ width: 230, flexShrink: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--surface)' }}>
            <div style={{ padding: '7px 12px', borderBottom: '1px solid var(--brd)', fontSize: 10.5, fontWeight: 700, color: 'var(--txt2)', textTransform: 'uppercase', letterSpacing: '0.06em', flexShrink: 0 }}>
              Saved ({snippets.length})
            </div>
            <div style={{ flex: 1, overflowY: 'auto' }}>
              {cid && <div style={{ padding: '5px 12px 4px', fontSize: 10, color: 'var(--accent)', fontStyle: 'italic', borderBottom: '1px solid var(--brd)' }}>for: {conceptTitle || cid}</div>}
              {snippets.length === 0 ? (
                <div style={{ padding: '20px 12px', color: 'var(--txt3)', fontSize: 12, textAlign: 'center' }}>No saved snippets{cid ? ' for this concept' : ''}.</div>
              ) : snippets.map(sn => {
                const m = sn.title?.match(/^\[(\w+)\]\s*(.*)$/);
                const snLang = m?.[1] || 'code';
                const snName = m?.[2] || sn.title || 'Snippet';
                return (
                  <div key={sn.id} style={{ display: 'flex', alignItems: 'center', borderBottom: '1px solid var(--brd)', padding: '6px 10px', gap: 6 }}>
                    <button onClick={() => loadSnippet(sn)} style={{ flex: 1, textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'var(--font)', minWidth: 0 }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--txt2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{snName}</div>
                      <div style={{ fontSize: 10, color: 'var(--accent)', marginTop: 1 }}>{snLang}</div>
                      <div style={{ fontSize: 10, color: 'var(--txt3)', marginTop: 1 }}>{fmt(sn.created_at)}</div>
                    </button>
                    <button onClick={() => updateSnippet(sn)} title="Update with current code" style={{ flexShrink: 0, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--accent)', padding: '2px 4px', borderRadius: 3, fontSize: 10 }}>↑</button>
                    <button onClick={() => deleteSnippet(sn.id)} style={{ flexShrink: 0, background: 'none', border: 'none', cursor: 'pointer', color: '#f87171', padding: '2px 4px', borderRadius: 3, fontSize: 10 }}>x</button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* History sidebar */}
        {showHistory && (
          <div style={{ width: 230, flexShrink: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--surface)' }}>
            <div style={{ padding: '7px 12px', borderBottom: '1px solid var(--brd)', fontSize: 10.5, fontWeight: 700, color: 'var(--txt2)', textTransform: 'uppercase', letterSpacing: '0.06em', flexShrink: 0 }}>
              Run History
            </div>
            <div style={{ flex: 1, overflowY: 'auto' }}>
              {history.length === 0 ? (
                <div style={{ padding: '20px 12px', color: 'var(--txt3)', fontSize: 12, textAlign: 'center' }}>No history yet.</div>
              ) : history.map(h => {
                const meta = (() => { try { return JSON.parse(h.audio_path || '{}'); } catch { return {}; } })();
                const exitOk = meta.exit_code === 0;
                return (
                  <div
                    key={h.id}
                    onClick={() => { const m = h.title?.match(/^\[(\w+)\]/); if (m) setLang(m[1]); handleCodeChange(h.body_md || ''); setResult(meta.exit_code !== undefined ? { stdout: meta.stdout || '', stderr: meta.stderr || '', exit_code: meta.exit_code, language: m?.[1] || lang, error: null } : null); setShowHistory(false); }}
                    style={{ padding: '7px 10px', borderBottom: '1px solid var(--brd)', cursor: 'pointer' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 2 }}>
                      <span style={{ width: 6, height: 6, borderRadius: '50%', background: exitOk ? 'var(--accent)' : 'var(--red)', display: 'inline-block', flexShrink: 0 }} />
                      <span style={{ fontSize: 10, color: 'var(--txt3)', fontFamily: 'var(--mono)' }}>exit {meta.exit_code ?? '?'}</span>
                      <span style={{ fontSize: 10, color: 'var(--txt3)', marginLeft: 'auto' }}>{fmt(h.created_at)}</span>
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--txt2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {h.title?.replace(/^\[[\w+]+\]\s*/, '') || 'run'}
                    </div>
                    {meta.stdout && <div style={{ fontSize: 10, color: 'var(--txt3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: 'var(--mono)' }}>{meta.stdout.slice(0, 60)}</div>}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const MARIMO_BASE = 'https://marimo.app?embed=true&show-chrome=true';

function marimoUrl(code) {
  if (!code?.trim()) return MARIMO_BASE;
  return `${MARIMO_BASE}&code=${encodeURIComponent(code)}`;
}

function defaultNotebookCode(title) {
  const safe = (title || 'concept').replace(/["'\\]/g, '');
  return [
    'import marimo as mo',
    '',
    'mo.md("""',
    `# ${safe}`,
    '',
    `Explore **${safe}** interactively below.`,
    '""")',
    '',
    'import numpy as np',
    'import matplotlib.pyplot as plt',
    '',
    'x = np.linspace(0, 2 * np.pi, 200)',
    'fig, ax = plt.subplots(figsize=(7, 3))',
    'ax.plot(x, np.sin(x))',
    `ax.set_title("${safe}")`,
    'plt.tight_layout()',
    'fig',
  ].join('\n');
}

/** Marimo WASM notebook tab — persists notebooks to backend. */
export function NotebookTab({ conceptTitle, spaceId, conceptId }) {
  const [notebooks, setNotebooks] = useState([]);
  const [active, setActive]       = useState(null); // NoteRow
  const [editing, setEditing]     = useState(false);
  const [editorCode, setEditorCode] = useState('');
  const [saving, setSaving]       = useState(false);
  const [loading, setLoading]     = useState(false);
  const textareaRef = useRef(null);
  const { ok, err } = useStore();

  const cid = conceptId || '';

  useEffect(() => { load(); }, [spaceId, cid]);

  const load = async () => {
    setLoading(true);
    try {
      const rows = await api(`/spaces/${spaceId}/notebooks?concept_id=${encodeURIComponent(cid)}`);
      setNotebooks(Array.isArray(rows) ? rows : []);
      if (Array.isArray(rows) && rows.length > 0 && !active) setActive(rows[0]);
    } catch {}
    setLoading(false);
  };

  const createNew = async () => {
    const code = defaultNotebookCode(conceptTitle);
    setSaving(true);
    try {
      const nb = await api(`/spaces/${spaceId}/notebooks`, {
        method: 'POST',
        body: JSON.stringify({ concept_id: cid, title: conceptTitle || 'Notebook', code }),
      });
      setNotebooks(ns => [nb, ...ns]);
      setActive(nb);
      ok('Notebook created');
    } catch (e) { err(e.message); }
    setSaving(false);
  };

  const saveCode = async (code) => {
    if (!active) return;
    setSaving(true);
    try {
      const updated = await api(`/spaces/${spaceId}/notebooks/${active.id}`, {
        method: 'PUT',
        body: JSON.stringify({ title: active.title, code }),
      });
      setNotebooks(ns => ns.map(n => n.id === updated.id ? updated : n));
      setActive(updated);
    } catch (e) { err(e.message); }
    setSaving(false);
  };

  const deleteNb = async (id) => {
    try {
      await api(`/spaces/${spaceId}/notebooks/${id}`, { method: 'DELETE' });
      const next = notebooks.filter(n => n.id !== id);
      setNotebooks(next);
      setActive(active?.id === id ? (next[0] ?? null) : active);
      ok('Deleted');
    } catch (e) { err(e.message); }
  };

  const openEditor = () => {
    setEditorCode(active?.body_md || defaultNotebookCode(conceptTitle));
    setEditing(true);
    setTimeout(() => textareaRef.current?.focus(), 50);
  };

  const applyEditor = async () => {
    const code = editorCode.trim();
    setEditing(false);
    if (active) {
      await saveCode(code);
    } else {
      // Create new notebook with this code
      setSaving(true);
      try {
        const nb = await api(`/spaces/${spaceId}/notebooks`, {
          method: 'POST',
          body: JSON.stringify({ concept_id: cid, title: conceptTitle || 'Notebook', code }),
        });
        setNotebooks(ns => [nb, ...ns]);
        setActive(nb);
      } catch (e) { err(e.message); }
      setSaving(false);
    }
  };

  const activeCode = active?.body_md || defaultNotebookCode(conceptTitle);
  const iframeUrl  = marimoUrl(activeCode);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0 }}>

      {/* Toolbar */}
      <div style={{ padding: '6px 14px', borderBottom: '1px solid var(--brd)', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, color: 'var(--txt3)' }}>marimo WASM · runs in browser</span>
        {active && (
          <span style={{ fontSize: 11, color: 'var(--txt2)', fontStyle: 'italic' }}>{active.title}</span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button className="btn btn-accent btn-sm" style={{ fontSize: 11 }} onClick={createNew} disabled={saving}>
            {saving ? <span className="spin" /> : 'New'}
          </button>
          {active && (
            <>
              <button className="btn btn-muted btn-sm" style={{ fontSize: 11 }} onClick={openEditor}>Edit code</button>
              <button
                className="btn btn-muted btn-sm"
                style={{ fontSize: 11, color: '#f87171' }}
                onClick={() => deleteNb(active.id)}
              >Delete</button>
            </>
          )}
        </div>
      </div>

      {/* Notebook list (when >1) */}
      {notebooks.length > 1 && (
        <div style={{ display: 'flex', gap: 4, padding: '4px 14px', borderBottom: '1px solid var(--brd)', overflowX: 'auto', flexShrink: 0, background: 'var(--surface)' }}>
          {notebooks.map(nb => (
            <button
              key={nb.id}
              onClick={() => setActive(nb)}
              style={{
                flexShrink: 0, fontSize: 11, padding: '3px 10px', borderRadius: 5, border: '1px solid',
                borderColor: active?.id === nb.id ? 'var(--accent-border)' : 'var(--brd)',
                background: active?.id === nb.id ? 'var(--accent-dim)' : 'none',
                color: active?.id === nb.id ? 'var(--accent)' : 'var(--txt2)',
                cursor: 'pointer', fontFamily: 'var(--font)',
              }}
            >
              {nb.title || 'Notebook'}
            </button>
          ))}
        </div>
      )}

      {/* Code editor panel */}
      {editing && (
        <div style={{ flexShrink: 0, borderBottom: '1px solid var(--brd)', padding: '8px 14px', background: 'var(--surface)', display: 'flex', flexDirection: 'column', gap: 6 }}>
          <textarea
            ref={textareaRef}
            className="s-input"
            style={{ width: '100%', height: 180, resize: 'vertical', fontFamily: 'var(--mono)', fontSize: 12, padding: '8px', boxSizing: 'border-box' }}
            value={editorCode}
            onChange={e => setEditorCode(e.target.value)}
            onKeyDown={e => { if (e.key === 'Escape') setEditing(false); }}
          />
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="btn btn-accent btn-sm" style={{ fontSize: 11 }} onClick={applyEditor} disabled={saving}>
              {saving ? <span className="spin" /> : 'Apply & reload'}
            </button>
            <button className="btn btn-muted btn-sm" style={{ fontSize: 11 }} onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </div>
      )}

      {/* Marimo iframe */}
      <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
        {loading ? (
          <div className="loading-center"><span className="spin" /></div>
        ) : notebooks.length === 0 && !editing ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 12, color: 'var(--txt3)', fontSize: 13 }}>
            No notebooks yet.
            <button className="btn btn-accent btn-sm" onClick={createNew} disabled={saving}>
              {saving ? <span className="spin" /> : 'Create notebook'}
            </button>
          </div>
        ) : (
          <iframe
            key={iframeUrl}
            src={iframeUrl}
            title="marimo notebook"
            frameBorder="0"
            sandbox="allow-scripts allow-same-origin allow-downloads allow-popups"
            allow="microphone"
            style={{ display: 'block', border: 'none', width: '100%', height: '100%' }}
          />
        )}
      </div>
    </div>
  );
}

/** 5-minute challenge generator with history. */
export function QuickTestTab({ spaceId, conceptId, topicTitle }) {
  const [current, setCurrent] = useState(null);
  const [history, setHistory] = useState([]);
  const [showHistory, setShowHistory] = useState(false);
  const [mode, setMode] = useState('notes');
  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [voiceRec, setVoiceRec] = useState(false); // recording mic for voice prompt
  const voiceMediaRef = useRef(null);
  const voiceChunks   = useRef([]);
  const { err } = useStore();

  useEffect(() => { loadHistory(); setCurrent(null); setPrompt(''); }, [conceptId]);

  const loadHistory = async () => {
    if (!spaceId) return;
    try {
      const cid = conceptId || '';
      const r = await api(`/spaces/${spaceId}/quicktest${cid ? `?concept_id=${encodeURIComponent(cid)}` : ''}`);
      setHistory(Array.isArray(r) ? r : []);
    } catch {}
  };

  const generate = async (overridePrompt) => {
    if (!spaceId) return;
    setLoading(true);
    setCurrent(null);
    try {
      const p = overridePrompt ?? (mode === 'user' ? prompt.trim() : '');
      const created = await api(`/spaces/${spaceId}/quicktest`, {
        method: 'POST',
        body: JSON.stringify({ input_mode: p ? 'user' : mode, prompt: p, concept_id: conceptId || '' }),
      });
      setCurrent(created);
      setHistory(h => [created, ...h.filter(x => x.id !== created.id)]);
    } catch (e) { err(e.message); }
    setLoading(false);
  };

  const toggleVoice = async () => {
    if (voiceRec) {
      // stop and transcribe
      voiceMediaRef.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      voiceChunks.current = [];
      const mr = new MediaRecorder(stream, { mimeType: MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm' });
      mr.ondataavailable = e => { if (e.data.size > 0) voiceChunks.current.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        setVoiceRec(false);
        setLoading(true);
        try {
          const blob = new Blob(voiceChunks.current, { type: 'audio/webm' });
          const form = new FormData();
          form.append('file', blob, 'voice.webm');
          const res = await fetch(`/api/spaces/${spaceId}/transcribe`, { method: 'POST', body: form });
          const data = await res.json();
          const spoken = data.transcript?.trim();
          if (spoken) { setPrompt(spoken); await generate(spoken); }
        } catch (e) { err(e.message); setLoading(false); }
      };
      mr.start();
      voiceMediaRef.current = mr;
      setVoiceRec(true);
    } catch (e) { err(e.message); }
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div className="qt-toolbar">
        <div className="qt-toolbar-left">
          <div className="qt-title">QuickTest</div>
          <div className="qt-sub">5-minute challenge for {topicTitle}</div>
        </div>
        <div className="qt-toolbar-actions">
          <button className={`btn btn-muted btn-sm${showHistory ? ' active' : ''}`} onClick={() => setShowHistory(v => !v)}>
            History ({history.length})
          </button>
          <button
            onClick={toggleVoice}
            disabled={loading}
            title={voiceRec ? 'Stop & generate' : 'Speak your prompt'}
            style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '4px 10px', borderRadius: 5, border: `1px solid ${voiceRec ? 'var(--red)' : 'var(--brd)'}`, background: voiceRec ? 'rgba(248,113,113,.1)' : 'none', color: voiceRec ? 'var(--red)' : 'var(--txt2)', fontSize: 11, cursor: 'pointer', fontFamily: 'var(--font)' }}
          >
            {voiceRec ? (
              <><span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--red)', display: 'inline-block', animation: 'recDot 1s ease-in-out infinite alternate' }} /> Stop</>
            ) : (
              <><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/></svg> Voice</>
            )}
          </button>
          <button className="btn btn-accent btn-sm" onClick={() => generate()} disabled={loading || voiceRec}>
            {loading ? <span className="spin" /> : 'Generate'}
          </button>
        </div>
      </div>

      <div className="qt-controls">
        <div className="qt-control">
          <label className="qt-label">Mode</label>
          <div className="pt-seg">
            {['notes', 'random', 'user'].map(m => (
              <button key={m} className={`seg-btn${mode === m ? ' active' : ''}`} onClick={() => setMode(m)}>
                {m === 'user' ? 'custom' : m}
              </button>
            ))}
          </div>
        </div>
        <div className="qt-control">
          <label className="qt-label">Prompt</label>
          <input className="s-input" placeholder="Optional instruction for the challenge" value={prompt} onChange={e => setPrompt(e.target.value)} />
        </div>
      </div>

      <div className="qt-body">
        {showHistory && (
          <div className="qt-history">
            <div className="qt-history-title">Past QuickTests ({history.length})</div>
            {history.length === 0 ? (
              <div className="qt-empty">No saved tests yet.</div>
            ) : history.map(h => (
              <button key={h.id} className={`qt-history-item${current?.id === h.id ? ' active' : ''}`} onClick={() => setCurrent(h)}>
                <div className="qt-history-meta">{fmt(h.created_at)}</div>
                <div className="qt-history-titleline">{(h.prompt || h.input_mode || 'QuickTest').slice(0, 60)}</div>
              </button>
            ))}
          </div>
        )}
        <div className="qt-view">
          {!current && !loading ? (
            <div className="qt-empty">Click <strong>Generate</strong> to create a new challenge.</div>
          ) : current ? (
            <div className="qt-card">
              <div className="qt-card-hdr">
                <div>
                  <div className="qt-card-title">QuickTest</div>
                  <div className="qt-card-meta">{fmt(current.created_at)} · {current.input_mode || 'notes'}</div>
                </div>
              </div>
              <div className="qt-card-body">
                <MarkdownEditor value={current.response_md || ''} readOnly defaultMode="read" />
              </div>
            </div>
          ) : (
            <div className="loading-center"><span className="spin" /></div>
          )}
        </div>
      </div>
    </div>
  );
}
