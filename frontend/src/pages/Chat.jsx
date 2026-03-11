import { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { api } from '../api';
import { SendIcon, ChevronDownIcon } from '../components/icons';
import { fmt } from '../utils/format';
import { useStore } from '../store';

// ── Custom hook: streaming chat over SSE ──────────────────────────────────────
const STORAGE_KEY = 'sarthak_chat_session_id';

function useChat() {
  const [messages, setMessages] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionIdState] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) || ''; } catch { return ''; }
  });
  const [streaming, setStreaming] = useState(false);
  const { err } = useStore();

  // Persist sessionId to localStorage whenever it changes
  const setSessionId = useCallback((sid) => {
    setSessionIdState(sid);
    try {
      if (sid) localStorage.setItem(STORAGE_KEY, sid);
      else localStorage.removeItem(STORAGE_KEY);
    } catch { /* ignore */ }
  }, []);

  const refreshSessions = useCallback(async () => {
    try {
      const r = await api('/chat/sessions');
      setSessions(r.sessions || (Array.isArray(r) ? r : []));
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { refreshSessions(); }, [refreshSessions]);

  // Load persisted session messages on mount
  useEffect(() => {
    if (!sessionId) return;
    api(`/chat/history?session_id=${sessionId}`)
      .then(r => setMessages((r.messages || []).map((m, i) => ({ ...m, id: `hist_${i}` }))))
      .catch(() => { /* session may be deleted; clear it */ setSessionId(''); });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // run only on mount

  const loadSession = useCallback(async (sid) => {
    setSessionId(sid);
    if (!sid) { setMessages([]); return; }
    try {
      const r = await api(`/chat/history?session_id=${sid}`);
      setMessages((r.messages || []).map((m, i) => ({ ...m, id: `hist_${i}` })));
    } catch (e) { err(e.message); }
  }, [err, setSessionId]);

  const deleteSession = useCallback(async (sid) => {
    try {
      await api(`/chat/sessions/${sid}`, { method: 'DELETE' });
      if (sessionId === sid) { setMessages([]); setSessionId(''); }
      refreshSessions();
    } catch (e) { err(e.message); }
  }, [sessionId, refreshSessions, err, setSessionId]);

  const abortRef = useRef(null);

  const sendMessage = useCallback(async (text) => {
    if (!text.trim() || streaming) return;

    // Cancel any previous in-flight stream
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const ts = Date.now();
    const uid = `u_${ts}`;
    const aid = `a_${ts + 1}`;
    setMessages(m => [
      ...m,
      { id: uid, role: 'user', content: text },
      { id: aid, role: 'assistant', content: '', streaming: true },
    ]);
    setStreaming(true);

    let acc = '';
    let activeSid = sessionId;

    try {
      const resp = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: activeSid || null }),
        signal: controller.signal,
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);

      const reader = resp.body.getReader();
      // Ensure reader is released if the abort signal fires mid-stream
      controller.signal.addEventListener('abort', () => { reader.cancel().catch(() => {}); }, { once: true });
      const dec = new TextDecoder();
      let buf = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop() ?? '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (raw === '[DONE]') { buf = ''; break; }

          // Session ID marker
          if (raw.startsWith('[SESSION:') && raw.endsWith(']')) {
            const sid = raw.slice(9, -1).trim();
            if (sid) { activeSid = sid; setSessionId(sid); }
            continue;
          }

          // The backend streams cumulative text (not deltas) — replace, don't append
          // Try JSON for error/delta payloads, otherwise treat as full accumulated text
          try {
            const p = JSON.parse(raw);
            if (p.session_id) { activeSid = p.session_id; setSessionId(p.session_id); }
            if (p.error) acc = `${acc}\n\n*Error: ${p.error}*`;
            // p.full=true means the payload is the full text so far (replace); otherwise append delta
            else if (typeof p.delta === 'string') acc = (p.full || p.replace_all) ? p.delta : acc + p.delta;
            else if (typeof p.content === 'string') acc = p.content;
          } catch {
            // Plain text from backend: could be cumulative (replace) or delta (append).
            // Backend streams cumulative text, so replace the whole accumulated buffer.
            if (raw && raw !== '[DONE]') acc = raw;
          }
          setMessages(m => m.map(msg => msg.id === aid ? { ...msg, content: acc } : msg));
        }
      }
    } catch (e) {
      if (e.name === 'AbortError') return; // cancelled — don't update state
      acc = acc || `*Error: ${e.message}*`;
    }

    setMessages(m => m.map(msg =>
      msg.id === aid ? { ...msg, content: acc || '*(no response)*', streaming: false } : msg
    ));
    setStreaming(false);
    refreshSessions();
  }, [streaming, sessionId, refreshSessions]);

  return { messages, sessions, sessionId, streaming, loadSession, deleteSession, sendMessage, setMessages, setSessionId, refreshSessions };
}

// ── Session picker ────────────────────────────────────────────────────────────
function SessionPicker({ sessions, sessionId, onSelect }) {
  const [open, setOpen] = useState(false);
  const ref = useRef();

  useEffect(() => {
    if (!open) return;
    const h = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [open]);

  const current = sessions.find(s => s.session_id === sessionId);
  const label = current
    ? `${fmt(current.last_ts)} (${current.msg_count || 0} msgs)`
    : 'New session';

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button className="s-select" onClick={() => setOpen(o => !o)}
        style={{ width: 220, textAlign: 'left', display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12.5 }}>{label}</span>
        <ChevronDownIcon size={9} sw="2" />
      </button>
      {open && (
        <div style={{ position: 'absolute', top: '110%', left: 0, right: 0, zIndex: 400,
          background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 8,
          boxShadow: '0 8px 28px rgba(0,0,0,.4)', maxHeight: 320, overflowY: 'auto' }}>
          <div onClick={() => { onSelect(''); setOpen(false); }}
            style={{ padding: '9px 14px', cursor: 'pointer', fontSize: 12.5, borderBottom: '1px solid var(--brd)',
              color: !sessionId ? 'var(--accent)' : 'var(--txt3)', fontWeight: !sessionId ? 600 : 400 }}>
            ＋ New session
          </div>
          {sessions.map(s => {
            const active = s.session_id === sessionId;
            return (
              <div key={s.session_id} onClick={() => { onSelect(s.session_id); setOpen(false); }}
                style={{ padding: '9px 14px', cursor: 'pointer', borderBottom: '1px solid var(--brd)',
                  background: active ? 'var(--accent-dim)' : 'transparent' }}>
                <div style={{ fontSize: 12.5, color: active ? 'var(--accent)' : 'var(--txt)',
                  fontWeight: active ? 600 : 400 }}>{fmt(s.last_ts)}</div>
                <div style={{ fontSize: 11, color: 'var(--txt3)', marginTop: 2 }}>
                  {s.msg_count || 0} messages
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Message bubble ────────────────────────────────────────────────────────────
function Message({ msg }) {
  const isUser = msg.role === 'user';
  return (
    <div className={`bubble ${msg.role}`}>
      <div className={`b-av ${msg.role}`}>{isUser ? 'U' : 'AI'}</div>
      <div className="b-content">
        {isUser ? (
          <span style={{ whiteSpace: 'pre-wrap', fontSize: 13.5 }}>{msg.content}</span>
        ) : msg.streaming && !msg.content ? (
          <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
            {[0,1,2].map(i => (
              <span key={i} style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent)',
                display: 'inline-block', animation: `typingDot 1.2s ${i*0.2}s ease-in-out infinite` }} />
            ))}
          </span>
        ) : (
          <div className="chat-md-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
              {msg.content || ''}
            </ReactMarkdown>
            {msg.streaming && <span className="stream-cursor">▍</span>}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────
const SUGGESTIONS = [
  'What did I work on today?',
  'Summarize my recent activity',
  'What should I focus on next?',
  'Show my productivity trends',
];

// ── Main Chat page ────────────────────────────────────────────────────────────
export default function Chat() {
  const { messages, sessions, sessionId, streaming,
    loadSession, deleteSession, sendMessage, setMessages, setSessionId, refreshSessions } = useChat();
  const [input, setInput] = useState('');
  const bottomRef = useRef();
  const taRef = useRef();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const send = useCallback(() => {
    const text = input.trim();
    if (!text) return;
    setInput('');
    if (taRef.current) { taRef.current.style.height = 'auto'; }
    sendMessage(text);
  }, [input, sendMessage]);

  const onKey = e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const onInput = e => {
    setInput(e.target.value);
    const ta = e.target;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 180) + 'px';
  };

  const handleNew = () => { setMessages([]); setSessionId(''); setInput(''); refreshSessions(); };

  return (
    <div className="page">
      <header className="pg-header">
        <div className="pg-title-group">
          <h1 className="pg-title">Chat</h1>
          <p className="pg-sub">AI assistant with full memory &amp; context</p>
        </div>
        <div className="pg-actions">
          <SessionPicker sessions={sessions} sessionId={sessionId} onSelect={loadSession} />
          {sessionId && (
            <button className="btn btn-muted btn-sm"
              style={{ color: '#f87171', borderColor: 'rgba(248,113,113,.3)' }}
              onClick={() => { if (confirm('Delete this session?')) deleteSession(sessionId); }}>
              Delete
            </button>
          )}
          <button className="btn btn-muted btn-sm" onClick={handleNew}>New</button>
        </div>
      </header>

      <div id="chat-messages">
        {messages.length === 0 ? (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
            justifyContent: 'center', gap: 16, padding: '40px 20px' }}>
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" opacity=".25">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--txt2)', marginBottom: 4 }}>
                What do you want to explore?
              </div>
              <div style={{ fontSize: 12.5, color: 'var(--txt3)', marginBottom: 16 }}>
                I have access to your activity, spaces, notes, and workspace data.
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'center', maxWidth: 440 }}>
                {SUGGESTIONS.map(s => (
                  <button key={s} className="btn btn-muted btn-sm"
                    style={{ fontSize: 12 }}
                    onClick={() => { setInput(s); taRef.current?.focus(); }}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          messages.map(msg => <Message key={msg.id} msg={msg} />)
        )}
        <div ref={bottomRef} />
      </div>

      <div id="chat-bar">
        <textarea
          ref={taRef}
          id="chat-input"
          rows={1}
          value={input}
          onChange={onInput}
          onKeyDown={onKey}
          disabled={streaming}
          placeholder="Ask anything… Enter = send · Shift+Enter = newline"
        />
        <button className="btn btn-accent btn-sm" onClick={send} disabled={streaming || !input.trim()}>
          {streaming ? <span className="spin" style={{ width: 13, height: 13, borderWidth: 2 }} /> : <SendIcon size={13} sw="2.2" />}
        </button>
      </div>
    </div>
  );
}
