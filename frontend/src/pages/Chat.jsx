/**
 * Chat.jsx — Perplexity-style chat with correct session management.
 *
 * Architecture:
 *   Chat (manages session state + sidebar)
 *     └─ ChatSession key={sessionKey}  (remounts entirely on new/switch session)
 *          ├─ useSarthakRuntime        (creates adapter + useLocalRuntime)
 *          ├─ AssistantRuntimeProvider (scoped inside the keyed boundary)
 *          └─ ChatThread               (UI)
 *
 * Why key remount: useLocalRuntime only reads initialMessages once at construction.
 * To reset to a new empty thread or load a different session's history, the entire
 * provider+runtime must be unmounted and remounted. Putting the key on ChatSession
 * (which wraps AssistantRuntimeProvider) achieves this correctly.
 */
import { useState, useCallback, useEffect, useRef } from 'react';
import {
  AssistantRuntimeProvider,
  ThreadPrimitive,
  MessagePrimitive,
  ComposerPrimitive,
  useThreadRuntime,
} from '@assistant-ui/react';
import { MarkdownTextPrimitive } from '@assistant-ui/react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { useSarthakRuntime } from '../hooks/useSarthakRuntime';
import { api } from '../api';
import { useStore } from '../store';

// ── AG-UI learner state defaults ──────────────────────────────────────────────
const DEFAULT_AGUI_STATE = {
  xp: 0, streak: 0, level: '', concept: '', space_dir: '', session_count: 0, badges: [],
};

// ── Live learner state bar (AG-UI mode only) ──────────────────────────────────
function LearnerStateBar({ state, onSetSpaceDir }) {
  const [editing, setEditing] = useState(false);
  const [input,   setInput]   = useState(state.space_dir || '');

  const commit = () => { onSetSpaceDir(input.trim()); setEditing(false); };

  return (
    <div className="agui-state-bar">
      {/* XP pill */}
      <span className="agui-pill agui-pill--xp" title="XP earned this session">
        ⚡ {state.xp} XP
      </span>
      {/* Streak pill */}
      {state.streak > 0 && (
        <span className="agui-pill agui-pill--streak" title="Day streak">
          🔥 {state.streak}d
        </span>
      )}
      {/* Level pill */}
      {state.level && (
        <span className="agui-pill agui-pill--level" title="Skill level">
          {state.level}
        </span>
      )}
      {/* Active concept */}
      {state.concept && (
        <span className="agui-pill agui-pill--concept" title="Current concept">
          📖 {state.concept}
        </span>
      )}
      {/* Badges (up to 3) */}
      {(state.badges || []).slice(0, 3).map(b => (
        <span key={b} className="agui-pill agui-pill--badge" title={b}>🏅 {b}</span>
      ))}
      {/* Spacer */}
      <span style={{ flex: 1 }} />
      {/* Space dir selector */}
      {editing ? (
        <span className="agui-dir-row">
          <input
            className="agui-dir-input"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false); }}
            placeholder="/path/to/space"
            autoFocus
          />
          <button className="agui-dir-ok" onClick={commit}>✓</button>
        </span>
      ) : (
        <button
          className="agui-pill agui-pill--dir"
          onClick={() => { setInput(state.space_dir || ''); setEditing(true); }}
          title="Set active workspace directory"
        >
          {state.space_dir ? `📁 ${state.space_dir.split('/').slice(-2).join('/')}` : '📁 Set workspace'}
        </button>
      )}
    </div>
  );
}

const STORAGE_KEY      = 'sarthak_chat_session_id';
const STORAGE_KEY_AGUI = 'sarthak_agui_session_id';

const loadStored = (mode) => {
  try { return localStorage.getItem(mode === 'agui' ? STORAGE_KEY_AGUI : STORAGE_KEY) || null; } catch { return null; }
};
const saveStored = (sid, mode) => {
  try {
    const key = mode === 'agui' ? STORAGE_KEY_AGUI : STORAGE_KEY;
    sid ? localStorage.setItem(key, sid) : localStorage.removeItem(key);
  } catch {}
};

const SUGGESTIONS = [
  'What did I work on today?',
  'Summarize my recent activity',
  'What should I focus on next?',
  'Show my productivity trends',
];

// ── Helpers ────────────────────────────────────────────────────────────────────
function parseSessionDate(s) {
  if (!s?.last_ts) return null;
  // last_ts is an ISO string like "2026-03-12T15:30:00.000Z" — parse directly
  const d = new Date(s.last_ts);
  return isNaN(d) ? null : d;
}

function fmtSessionTitle(s) {
  const snippet = s.first_msg;
  if (snippet && snippet.trim()) {
    const trimmed = snippet.trim();
    return trimmed.length > 42 ? trimmed.slice(0, 42) + '…' : trimmed;
  }
  const d = parseSessionDate(s);
  if (!d) return 'Session';
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

function getSessionGroup(d) {
  if (!d) return 'Older';
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diffDays = Math.floor((todayStart - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 864e5);
  if (diffDays === 0) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  if (diffDays <= 7) return 'Previous 7 days';
  if (diffDays <= 30) return 'Previous 30 days';
  return d.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
}

function groupSessions(sessions) {
  const order = [];
  const map = {};
  for (const s of sessions) {
    const d = parseSessionDate(s);
    const group = getSessionGroup(d);
    if (!map[group]) { map[group] = []; order.push(group); }
    map[group].push(s);
  }
  return order.map(g => ({ group: g, items: map[g] }));
}

// ── Session Sidebar (collapsed by default, expands on hover) ──────────────────
function SessionSidebar({ sessions, activeId, onSelect, onNew, onDelete }) {
  const groups = groupSessions(sessions);
  return (
    <aside className="chat-sidebar">
      {/* Collapsed: show only the new-chat icon */}
      <div className="chat-sidebar-icon-row">
        <button className="chat-new-btn chat-new-btn--icon" onClick={onNew} title="New chat">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2.2" strokeLinecap="round">
            <path d="M12 5v14M5 12h14"/>
          </svg>
        </button>
      </div>
      {/* Expanded panel (visible on hover) */}
      <div className="chat-sidebar-panel">
        <div className="chat-sidebar-hdr">
          <span className="chat-sidebar-title">Chats</span>
          <button className="chat-new-btn" onClick={onNew} title="New chat">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2.2" strokeLinecap="round">
              <path d="M12 5v14M5 12h14"/>
            </svg>
          </button>
        </div>
        <div className="chat-sidebar-list">
          {sessions.length === 0 && (
            <div className="chat-sidebar-empty">No history yet</div>
          )}
          {groups.map(({ group, items }) => (
            <div key={group} className="chat-sidebar-group">
              <div className="chat-sidebar-group-label">{group}</div>
              {items.map(s => (
                <div key={s.session_id}
                  className={`chat-sidebar-item ${s.session_id === activeId ? 'active' : ''}`}
                  onClick={() => onSelect(s.session_id)}>
                  <div className="chat-sidebar-item-label">{fmtSessionTitle(s)}</div>
                  <div className="chat-sidebar-item-meta">{s.msg_count || 0} msgs</div>
                  <button className="chat-sidebar-del"
                    onClick={e => { e.stopPropagation(); onDelete(s.session_id); }}
                    title="Delete">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                      strokeWidth="2.5" strokeLinecap="round">
                      <path d="M18 6 6 18M6 6l12 12"/>
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}

// ── Markdown renderer ──────────────────────────────────────────────────────────
const MarkdownText = () => (
  <MarkdownTextPrimitive
    remarkPlugins={[remarkGfm]}
    rehypePlugins={[rehypeHighlight]}
    className="chat-markdown"
  />
);

// ── Typing indicator ───────────────────────────────────────────────────────────
function TypingDots() {
  return (
    <span className="chat-typing">
      {[0, 1, 2].map(i => (
        <span key={i} className="chat-typing-dot" style={{ animationDelay: `${i * 0.2}s` }} />
      ))}
    </span>
  );
}

// ── Messages ───────────────────────────────────────────────────────────────────
function UserMessage() {
  return (
    <MessagePrimitive.Root className="chat-msg chat-msg--user">
      <div className="chat-bubble chat-bubble--user">
        <MessagePrimitive.Content />
      </div>
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="chat-msg chat-msg--assistant">
      <div className="chat-avatar">AI</div>
      <div className="chat-bubble chat-bubble--assistant">
        <ThreadPrimitive.If running>
          <MessagePrimitive.If hasContent={false}>
            <TypingDots />
          </MessagePrimitive.If>
        </ThreadPrimitive.If>
        <MessagePrimitive.Content components={{ Text: MarkdownText }} />
      </div>
    </MessagePrimitive.Root>
  );
}

// ── Tool activity bar ──────────────────────────────────────────────────────────
function ToolActivityBar({ tools }) {
  if (!tools.length) return null;
  return (
    <div className="chat-tool-bar">
      {tools.map(t => (
        <span key={t} className="chat-tool-pill">
          <span className="spin" style={{ width: 10, height: 10, borderWidth: 1.5 }} />
          {t.replace(/_/g, ' ')}
        </span>
      ))}
    </div>
  );
}

// ── Composer ───────────────────────────────────────────────────────────────────
function ChatComposer() {
  return (
    <div className="chat-composer-wrap">
      <ComposerPrimitive.Root className="chat-composer-row">
        <ComposerPrimitive.Input
          className="chat-composer-input"
          autoFocus
          placeholder="Ask anything…"
          submitOnEnter
        />
        <ThreadPrimitive.If running={false}>
          <ComposerPrimitive.Send className="chat-send-btn" aria-label="Send">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"
              style={{ transform: 'rotate(-90deg)' }}>
              <path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>
            </svg>
          </ComposerPrimitive.Send>
        </ThreadPrimitive.If>
        <ThreadPrimitive.If running>
          <ComposerPrimitive.Cancel className="chat-cancel-btn" aria-label="Stop">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
              <rect x="4" y="4" width="16" height="16" rx="2"/>
            </svg>
          </ComposerPrimitive.Cancel>
        </ThreadPrimitive.If>
      </ComposerPrimitive.Root>
    </div>
  );
}

// ── Empty state ────────────────────────────────────────────────────────────────
function EmptyState() {
  const threadRuntime = useThreadRuntime();
  const send = useCallback(text => {
    threadRuntime.append({ role: 'user', content: [{ type: 'text', text }] });
  }, [threadRuntime]);

  return (
    <ThreadPrimitive.Empty>
      <div className="chat-empty">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="1.2" opacity=".18">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
        <p className="chat-empty-title">What do you want to explore?</p>
        <p className="chat-empty-sub">Access to your activity, spaces, notes, and workspace.</p>
        <div className="chat-suggestions">
          {SUGGESTIONS.map(s => (
            <button key={s} className="btn btn-muted btn-sm chat-suggestion" onClick={() => send(s)}>
              {s}
            </button>
          ))}
        </div>
      </div>
    </ThreadPrimitive.Empty>
  );
}

// ── Thread ─────────────────────────────────────────────────────────────────────
function ChatThread({ activeTools, aguiState, onSetSpaceDir }) {
  return (
    <ThreadPrimitive.Root className="chat-thread">
      <ThreadPrimitive.Viewport className="chat-viewport">
        <EmptyState />
        <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
        <ToolActivityBar tools={activeTools} />
      </ThreadPrimitive.Viewport>
      <ThreadPrimitive.ScrollToBottom className="chat-scroll-btn">
        ↓ Scroll to bottom
      </ThreadPrimitive.ScrollToBottom>
      {aguiState && (
        <LearnerStateBar state={aguiState} onSetSpaceDir={onSetSpaceDir} />
      )}
      <ChatComposer />
    </ThreadPrimitive.Root>
  );
}

/**
 * ChatSession — owns the runtime for one session.
 * Remounting (via key) creates a fresh runtime + empty thread.
 */
function ChatSession({ sessionId, initialMessages, onSessionId, onToolEvent, mode = 'chat', spaceDir = '' }) {
  const [activeTools, setActiveTools] = useState([]);
  const [aguiState,   setAguiState]   = useState(mode === 'agui'
    ? { ...DEFAULT_AGUI_STATE, space_dir: spaceDir }
    : null
  );

  const handleToolEvent = useCallback(evt => {
    if (evt.type === 'tool_start')
      setActiveTools(prev => prev.includes(evt.tool) ? prev : [...prev, evt.tool]);
    else if (evt.type === 'tool_done')
      setActiveTools(prev => prev.filter(t => t !== evt.tool));
  }, []);

  const combinedToolEvent = useCallback(evt => {
    handleToolEvent(evt);
    onToolEvent?.(evt);
  }, [handleToolEvent, onToolEvent]);

  const handleStateDelta = useCallback(newState => {
    setAguiState(s => ({ ...s, ...newState }));
  }, []);

  const handleSetSpaceDir = useCallback(dir => {
    setAguiState(s => ({ ...s, space_dir: dir }));
  }, []);

  const runtime = useSarthakRuntime({
    sessionId,
    onSessionId,
    onToolEvent: combinedToolEvent,
    initialMessages,
    mode,
    agUiState:    aguiState ?? {},
    onStateDelta: mode === 'agui' ? handleStateDelta : undefined,
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ChatThread
        activeTools={activeTools}
        aguiState={mode === 'agui' ? aguiState : null}
        onSetSpaceDir={handleSetSpaceDir}
      />
    </AssistantRuntimeProvider>
  );
}

// ── Main Chat page ─────────────────────────────────────────────────────────────
export default function Chat({ mode = 'chat' }) {
  const { err } = useStore();

  const [activeSessionId, setActiveSessionId] = useState(() => loadStored(mode));
  const [sessionKey, setSessionKey]           = useState(0);
  const [initialMessages, setInitialMessages] = useState([]);
  const [sessions,        setSessions]        = useState([]);
  // AG-UI: initial space_dir (user can change it inside ChatSession via LearnerStateBar)
  const initialSpaceDir = '';

  const refreshSessions = useCallback(async () => {
    try {
      const r = await api('/chat/sessions');
      setSessions(r.sessions || []);
    } catch { /* silent */ }
  }, []);

  useEffect(() => { refreshSessions(); }, [refreshSessions]);

  const handleSessionId = useCallback((sid) => {
    setActiveSessionId(sid);
    saveStored(sid, mode);
    refreshSessions();
  }, [refreshSessions, mode]);

  const openSession = useCallback(async (sid) => {
    if (!sid) {
      setActiveSessionId(null);
      saveStored(null, mode);
      setInitialMessages([]);
      setSessionKey(k => k + 1);
      return;
    }
    try {
      const r = await api(`/chat/history?session_id=${sid}`);
      setInitialMessages(r.messages || []);
    } catch {
      setInitialMessages([]);
    }
    setActiveSessionId(sid);
    saveStored(sid, mode);
    setSessionKey(k => k + 1);
  }, [mode]);

  const deleteSession = useCallback(async (sid) => {
    try {
      await api(`/chat/sessions/${sid}`, { method: 'DELETE' });
      if (sid === activeSessionId) {
        setActiveSessionId(null);
        saveStored(null, mode);
        setInitialMessages([]);
        setSessionKey(k => k + 1);
      }
      refreshSessions();
    } catch (e) { err(e.message); }
  }, [activeSessionId, refreshSessions, err, mode]);

  const didRestore = useRef(false);
  useEffect(() => {
    if (didRestore.current) return;
    didRestore.current = true;
    const stored = loadStored(mode);
    if (stored) openSession(stored);
  }, [openSession, mode]);

  return (
    <div className="page">
      <div className="chat-layout">
        <SessionSidebar
          sessions={mode === 'agui' ? [] : sessions}
          activeId={activeSessionId}
          onSelect={openSession}
          onNew={() => openSession(null)}
          onDelete={deleteSession}
        />
        <div className="chat-main">
          <ChatSession
            key={sessionKey}
            sessionId={activeSessionId}
            initialMessages={initialMessages}
            onSessionId={handleSessionId}
            mode={mode}
            spaceDir={initialSpaceDir}
          />
        </div>
      </div>
    </div>
  );
}
