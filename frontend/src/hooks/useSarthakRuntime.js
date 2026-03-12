/**
 * useSarthakRuntime — bridges Sarthak SSE stream to @assistant-ui/react useLocalRuntime.
 *
 * SSE protocol (all events are JSON):
 *   {"type":"tool_start","tool":"..."}   ← tool activity
 *   {"type":"tool_done","tool":"..."}
 *   {"type":"text","text":"..."}         ← CUMULATIVE reply text (not delta)
 *   {"type":"error","text":"..."}
 *   [SESSION:<uuid>]                     ← session id handshake
 *   [DONE]                               ← stream end
 *
 * NOTE: backend streams cumulative text, so we forward it directly — no re-accumulation.
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

/**
 * Hook that creates a single useLocalRuntime adapter for a given session.
 * Caller is responsible for mounting/unmounting (via key) to create a new session.
 *
 * @param {string|null} sessionId  - current session id (null = new)
 * @param {Function} onSessionId   - called when server assigns a session id
 * @param {Function} onToolEvent   - called with {type, tool} events
 * @param {Array}    initialMessages - messages to seed the thread (history)
 */
export function useSarthakRuntime({ sessionId, onSessionId, onToolEvent, initialMessages = [] }) {
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  const onSessionIdRef = useRef(onSessionId);
  onSessionIdRef.current = onSessionId;

  const onToolEventRef = useRef(onToolEvent);
  onToolEventRef.current = onToolEvent;

  const adapter = useRef({
    async *run({ messages, abortSignal }) {
      const history = toHistory(messages.slice(0, -1));
      const userText = msgText(messages[messages.length - 1]);

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
      const dec = new TextDecoder();
      let buf = '';

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

            // Session handshake
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
              // Backend sends cumulative text — yield directly, no re-accumulation
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
    },
  }).current;

  // Seed with history messages when loading an existing session
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
