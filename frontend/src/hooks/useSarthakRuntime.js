/**
 * useSarthakRuntime — bridges Sarthak SSE streams to @assistant-ui/react useLocalRuntime.
 *
 * mode='chat' (default) — hits /api/chat, Sarthak SSE protocol:
 *   {"type":"tool_start","tool":"..."}
 *   {"type":"tool_done","tool":"..."}
 *   {"type":"text","text":"..."}   ← CUMULATIVE text
 *   [SESSION:<uuid>]
 *   [DONE]
 *
 * mode='agui' — hits /api/ag-ui, AG-UI SSE protocol:
 *   data: {"type":"RUN_STARTED",...}
 *   data: {"type":"TEXT_MESSAGE_START",...}
 *   data: {"type":"TEXT_MESSAGE_CONTENT","delta":"..."}
 *   data: {"type":"TEXT_MESSAGE_END",...}
 *   data: {"type":"TOOL_CALL_START","toolCallId":"...","toolCallName":"..."}
 *   data: {"type":"TOOL_CALL_END","toolCallId":"..."}
 *   data: {"type":"STATE_DELTA","delta":[...JSON-Patch ops...]}
 *   data: {"type":"RUN_FINISHED",...}
 *
 *   STATE_DELTA carries JSON-Patch (RFC 6902) operations. We apply them to
 *   the current agUiState and call onStateDelta(newState) so the UI can
 *   re-render live XP/streak/concept panels.
 */
import { useLocalRuntime } from '@assistant-ui/react';
import { useRef } from 'react';

const toHistory = (messages) =>
  messages
    .filter(m => m.role === 'user' || m.role === 'assistant')
    .map(m => ({
      role: m.role,
      content: (m.content || []).filter(c => c.type === 'text').map(c => c.text).join(''),
    }));

const msgText = (msg) =>
  (msg?.content ?? []).filter(c => c.type === 'text').map(c => c.text).join('');

/** Apply JSON-Patch ops (RFC 6902 subset: replace, add, remove) to an object. */
function applyPatch(obj, ops) {
  const out = { ...obj };
  for (const op of ops ?? []) {
    // path is "/key" or "/key/subkey"
    const parts = (op.path || '').replace(/^\//, '').split('/').filter(Boolean);
    if (!parts.length) continue;
    if (parts.length === 1) {
      const k = parts[0];
      if (op.op === 'remove') delete out[k];
      else out[k] = op.value;            // 'add' and 'replace' both set value
    }
    // deeper paths not needed for SarthakUIState (all top-level fields)
  }
  return out;
}

/**
 * Hook that creates a single useLocalRuntime adapter for a given session.
 *
 * @param {string|null}   sessionId      - current session id (null = new)
 * @param {Function}      onSessionId    - called when server assigns a session id
 * @param {Function}      onToolEvent    - called with {type, tool} events
 * @param {Array}         initialMessages - messages to seed the thread
 * @param {'chat'|'agui'} mode           - which backend endpoint to use
 * @param {object}        agUiState      - current shared state (agui mode only)
 * @param {Function}      onStateDelta   - called with updated state after STATE_DELTA
 */
export function useSarthakRuntime({
  sessionId,
  onSessionId,
  onToolEvent,
  initialMessages = [],
  mode = 'chat',
  agUiState = {},
  onStateDelta,
}) {
  const sessionIdRef    = useRef(sessionId);
  sessionIdRef.current  = sessionId;

  const onSessionIdRef  = useRef(onSessionId);
  onSessionIdRef.current = onSessionId;

  const onToolEventRef  = useRef(onToolEvent);
  onToolEventRef.current = onToolEvent;

  const agUiStateRef    = useRef(agUiState);
  agUiStateRef.current  = agUiState;

  const onStateDeltaRef = useRef(onStateDelta);
  onStateDeltaRef.current = onStateDelta;

  const modeRef = useRef(mode);
  modeRef.current = mode;

  const adapter = useRef({
    async *run({ messages, abortSignal }) {
      const history  = toHistory(messages.slice(0, -1));
      const userText = msgText(messages[messages.length - 1]);

      if (modeRef.current === 'agui') {
        yield* runAguiStream(userText, agUiStateRef, onStateDeltaRef, onToolEventRef, abortSignal);
      } else {
        yield* runChatStream(userText, history, sessionIdRef, onSessionIdRef, onToolEventRef, abortSignal);
      }
    },
  }).current;

  const seedMessages = initialMessages.length > 0
    ? initialMessages.map((m, i) => ({
        id: `h_${i}`,
        role: m.role,
        content: [{ type: 'text', text:
          typeof m.content === 'string' ? m.content
          : (m.content || []).filter(c => c.type === 'text').map(c => c.text).join(''),
        }],
        ...(m.role === 'assistant' ? { status: { type: 'complete', reason: 'stop' } } : {}),
        createdAt: m.ts ? new Date(m.ts * 1000) : new Date(),
      }))
    : undefined;

  return useLocalRuntime(adapter, { initialMessages: seedMessages });
}

// ── /api/chat stream reader (original protocol) ───────────────────────────────
async function* runChatStream(userText, history, sessionIdRef, onSessionIdRef, onToolEventRef, abortSignal) {
  const resp = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: userText,
      session_id: sessionIdRef.current || null,
      history,
    }),
    signal: abortSignal,
  });

  if (!resp.ok) {
    const body = await resp.text().catch(() => '');
    throw new Error(`HTTP ${resp.status}: ${body}`);
  }

  const reader = resp.body.getReader();
  const dec    = new TextDecoder();
  let buf      = '';

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() ?? '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (raw === '[DONE]') return;

        if (raw.startsWith('[SESSION:') && raw.endsWith(']')) {
          const sid = raw.slice(9, -1).trim();
          if (sid) onSessionIdRef.current?.(sid);
          continue;
        }
        if (!raw.startsWith('{')) continue;

        let evt;
        try { evt = JSON.parse(raw); } catch { continue; }

        if (evt.type === 'tool_start' || evt.type === 'tool_done') {
          onToolEventRef.current?.(evt);
          continue;
        }
        if (evt.type === 'text' && evt.text) {
          yield { content: [{ type: 'text', text: evt.text }] };
          continue;
        }
        if (evt.type === 'error' && evt.text) {
          yield { content: [{ type: 'text', text: `⚠ ${evt.text}` }] };
          continue;
        }
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}

// ── /api/ag-ui stream reader (AG-UI protocol) ─────────────────────────────────
async function* runAguiStream(userText, agUiStateRef, onStateDeltaRef, onToolEventRef, abortSignal) {
  // Build AG-UI RunAgentInput — messages array + state blob
  const body = JSON.stringify({
    thread_id: `agui-${Date.now()}`,
    run_id:    `run-${Date.now()}`,
    messages:  [{ role: 'user', content: userText }],
    state:     agUiStateRef.current ?? {},
    tools:     [],
    context:   [],
    forwarded_props: {},
  });

  const resp = await fetch('/api/ag-ui', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
    body,
    signal: abortSignal,
  });

  if (!resp.ok) {
    const errBody = await resp.text().catch(() => '');
    throw new Error(`AG-UI HTTP ${resp.status}: ${errBody}`);
  }

  const reader = resp.body.getReader();
  const dec    = new TextDecoder();
  let buf      = '';
  let textBuf  = '';   // accumulate delta chunks into one text block

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() ?? '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (!raw || raw === '[DONE]') continue;

        let evt;
        try { evt = JSON.parse(raw); } catch { continue; }

        switch (evt.type) {
          case 'TEXT_MESSAGE_CONTENT':
            // AG-UI sends incremental deltas — accumulate then yield
            textBuf += evt.delta ?? '';
            yield { content: [{ type: 'text', text: textBuf }] };
            break;

          case 'TEXT_MESSAGE_END':
            textBuf = '';   // reset for next message
            break;

          case 'TOOL_CALL_START':
            onToolEventRef.current?.({ type: 'tool_start', tool: evt.toolCallName ?? evt.tool_name ?? 'tool' });
            break;

          case 'TOOL_CALL_END':
            onToolEventRef.current?.({ type: 'tool_done', tool: evt.toolCallName ?? evt.tool_name ?? 'tool' });
            break;

          case 'STATE_DELTA': {
            // delta is an array of JSON-Patch (RFC 6902) operations
            const ops      = evt.delta ?? [];
            const newState = applyPatch(agUiStateRef.current ?? {}, ops);
            agUiStateRef.current = newState;
            onStateDeltaRef.current?.(newState);
            break;
          }

          case 'RUN_FINISHED':
          case 'RUN_ERROR':
            return;

          default:
            break;
        }
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}
