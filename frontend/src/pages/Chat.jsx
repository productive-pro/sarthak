import { useState, useEffect, useRef, useCallback } from 'react';
import { api, fmt } from '../api';
import { useStore } from '../store';
import MarkdownEditor from '../components/MarkdownEditor';

function SessionPicker({ sessions, sessionId, onSelect }) {
  const [open, setOpen] = useState(false);
  const ref = useRef();

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const current = sessions.find(s => (s.session_id || s.id) === sessionId);
  const label = current
    ? (current.preview ? current.preview.slice(0, 40) + (current.preview.length > 40 ? '…' : '') : fmt(current.last_ts))
    : 'New session';

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        className="s-select"
        style={{ width: 220, textAlign: 'left', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}
        onClick={() => setOpen(o => !o)}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{label}</span>
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M2 3.5l3 3 3-3"/></svg>
      </button>
      {open && (
        <div style={{
          position: 'absolute', top: '110%', left: 0, right: 0, zIndex: 200,
          background: 'var(--surface)', border: '1px solid var(--brd)', borderRadius: 7,
          boxShadow: '0 4px 20px rgba(0,0,0,0.3)', maxHeight: 280, overflowY: 'auto',
        }}>
          <div
            style={{ padding: '7px 12px', cursor: 'pointer', fontSize: 12.5, color: sessionId ? 'var(--txt2)' : 'var(--accent)', borderBottom: '1px solid var(--brd)' }}
            onClick={() => { onSelect(''); setOpen(false); }}
          >
            + New session
          </div>
          {sessions.map(s => {
            const sid = s.session_id || s.id;
            const active = sid === sessionId;
            const title = s.preview ? s.preview.slice(0, 55) + (s.preview.length > 55 ? '…' : '') : fmt(s.last_ts);
            const meta = `${s.msg_count || 0} msgs · ${fmt(s.last_ts)}`;
            return (
              <div
                key={sid}
                onClick={() => { onSelect(sid); setOpen(false); }}
                style={{
                  padding: '8px 12px', cursor: 'pointer', borderBottom: '1px solid var(--brd)',
                  background: active ? 'var(--accent-dim)' : 'transparent',
                  transition: 'background 100ms',
                }}
                onMouseEnter={e => { if (!active) e.currentTarget.style.background = 'var(--surface2)'; }}
                onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent'; }}
              >
                <div style={{ fontSize: 12.5, color: active ? 'var(--accent)' : 'var(--txt)', fontWeight: active ? 600 : 400, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{title}</div>
                <div style={{ fontSize: 11, color: 'var(--txt3)', marginTop: 2 }}>{meta}</div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function Chat() {
  const [messages, setMessages]   = useState([]);
  const [sessions, setSessions]   = useState([]);
  const [sessionId, setSessionId] = useState('');
  const [input, setInput]         = useState('');
  const [streaming, setStreaming] = useState(false);
  const bottomRef   = useRef();
  const textareaRef = useRef();
  const { err } = useStore();

  useEffect(() => { loadSessions(); }, []);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const loadSessions = async () => {
    try {
      const r = await api('/chat/sessions');
      const raw = Array.isArray(r) ? r : r.sessions || [];
      // Enrich each session with a preview of the first user message
      const enriched = await Promise.all(raw.map(async (s) => {
        try {
          const hist = await api(`/chat/history?session_id=${s.session_id}&limit=2`);
          const first = (hist.messages || []).find(m => m.role === 'user');
          return { ...s, preview: first?.content?.slice(0, 60) || '' };
        } catch { return s; }
      }));
      setSessions(enriched);
    } catch {}
  };

  const deleteSession = async (sid) => {
    try {
      await api(`/chat/sessions/${sid}`, { method: 'DELETE' });
      if (sessionId === sid) { setMessages([]); setSessionId(''); }
      loadSessions();
    } catch (e) { err(e.message); }
  };

  const loadSession = async (sid) => {
    setSessionId(sid);
    if (!sid) { setMessages([]); return; }
    try {
      const r = await api(`/chat/history?session_id=${sid}`);
      setMessages(r.messages || []);
    } catch (e) { err(e.message); }
  };

  const sendChat = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput('');
    if (textareaRef.current) { textareaRef.current.style.height = 'auto'; }

    const userMsg   = { role: 'user', content: text, ts: new Date().toISOString() };
    const assistIdx = Date.now();
    setMessages(m => [...m, userMsg, { role: 'assistant', content: '', id: assistIdx, streaming: true }]);
    setStreaming(true);

    let assistantContent = '';
    try {
      const body = { message: text };
      if (sessionId) body.session_id = sessionId;
      const r = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const reader = r.body.getReader();
      const dec    = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n'); buf = lines.pop() || '';
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const d = line.slice(6);
          if (d === '[DONE]') break;
          if (d.startsWith('[SESSION:') && d.endsWith(']')) {
            const sid = d.slice(9, -1).trim();
            if (sid && !sessionId) { setSessionId(sid); }
            continue;
          }
          try {
            const parsed = JSON.parse(d);
            if (parsed.session_id && !sessionId) { setSessionId(parsed.session_id); }
            assistantContent = typeof parsed.content === 'string'
              ? (parsed.delta ? assistantContent + parsed.content : parsed.content)
              : (typeof parsed === 'string' ? parsed : assistantContent);
          } catch {
            assistantContent += d;
          }
          setMessages(m => m.map(msg => msg.id === assistIdx ? { ...msg, content: assistantContent } : msg));
        }
      }
    } catch (e) { assistantContent = `Error: ${e.message}`; }

    setMessages(m => m.map(msg => msg.id === assistIdx ? { ...msg, content: assistantContent, streaming: false } : msg));
    setStreaming(false);
    loadSessions();
  }, [input, streaming, sessionId]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
  };

  const handleInput = (e) => {
    setInput(e.target.value);
    const ta = e.target;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px';
  };

  return (
    <div className="page">
      <header className="pg-header">
        <div className="pg-title-group">
          <h1 className="pg-title">Chat</h1>
          <p className="pg-sub">Streaming AI conversation</p>
        </div>
        <div className="pg-actions">
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', position: 'relative' }}>
            <SessionPicker
              sessions={sessions}
              sessionId={sessionId}
              onSelect={loadSession}
            />
            {sessionId && (
              <button
                className="btn btn-muted btn-sm"
                title="Delete this session"
                onClick={() => { if (confirm('Delete this session?')) deleteSession(sessionId); }}
                style={{ color: '#f87171', borderColor: 'rgba(248,113,113,0.3)' }}
              >
                Delete
              </button>
            )}
            <button className="btn btn-muted btn-sm" onClick={() => { setMessages([]); setSessionId(''); }}>New</button>
          </div>
        </div>
      </header>

      <div id="chat-messages">
        {messages.length === 0 && (
          <div style={{ display: 'flex', flex: 1, alignItems: 'center', justifyContent: 'center', color: 'var(--txt3)', fontSize: 13 }}>
            Start a conversation
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={msg.id || i} className={`bubble ${msg.role}`}>
            <div className={`b-av ${msg.role}`}>{msg.role === 'user' ? 'U' : 'AI'}</div>
            <div className={`b-content${msg.role === 'assistant' ? ' b-content--editor' : ''}`}>
              {msg.role === 'assistant' && msg.streaming && !msg.content ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '6px 2px' }}>
                  {[0, 1, 2].map(j => (
                    <span key={j} style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--accent)', display: 'inline-block', opacity: 0.5, animation: `typingDot 1.2s ${j * 0.2}s ease-in-out infinite` }} />
                  ))}
                </div>
              ) : msg.role === 'assistant' ? (
                <MarkdownEditor
                  value={msg.content || ''}
                  readOnly
                  defaultMode="read"
                  streaming={!!msg.streaming}
                />
              ) : (
                <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div id="chat-bar">
        <textarea
          ref={textareaRef}
          id="chat-input"
          rows={1}
          value={input}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder="Ask anything…  Enter = send, Shift+Enter = new line"
          disabled={streaming}
        />
        <button
          className="btn btn-accent btn-sm"
          onClick={sendChat}
          disabled={streaming || !input.trim()}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </div>
    </div>
  );
}
