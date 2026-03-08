/**
 * ForceGraph — interactive SVG-based concept graph.
 *
 * Props:
 *   nodes: Array<{ id, label, type: 'chapter'|'concept'|'topic', status, chapterId }>
 *   links: Array<{ source, target, type: 'hierarchy'|'related' }>
 *   onNodeClick: (node) => void
 *   width, height: number
 */
import { useEffect, useRef, useCallback } from 'react';

const NODE_R = { chapter: 22, topic: 13, concept: 8 };
const NODE_COLOR = {
  chapter: { fill: '#1e1e2e', stroke: '#6366f1' },
  topic:   { fill: '#1a2230', stroke: '#38bdf8' },
  concept: { fill: '#1a2a1a', stroke: '#4ade80' },
};
const STATUS_STROKE = {
  completed:   '#4ade80',
  in_progress: '#fbbf24',
  review:      '#38bdf8',
  not_started: null,
};

const REPULSION = 4000;
const LINK_K    = 0.05;
const GRAVITY   = 0.004;
const DAMPING   = 0.8;
const MAX_V     = 14;
const LINK_REST = { hierarchy: 90, related: 140 };

export default function ForceGraph({ nodes, links, onNodeClick, width = 800, height = 560 }) {
  const svgRef    = useRef(null);
  const stateRef  = useRef({ nodes: [], links: [], pan: { x: 0, y: 0 }, zoom: 1, drag: null, drag_start: null, pan_start: null, raf: null, running: true });

  // Init physics state from props
  useEffect(() => {
    const s = stateRef.current;
    const cx = width / 2, cy = height / 2;

    // Position chapter nodes in a ring, topics/concepts orbit from there
    const chNodes = nodes.filter(n => n.type === 'chapter');
    const nodeMap  = {};

    s.nodes = nodes.map((n, i) => {
      const r  = NODE_R[n.type] || 8;
      const ch = chNodes.find(c => c.id === n.chapterId);
      let x = cx + (Math.random() - 0.5) * 200;
      let y = cy + (Math.random() - 0.5) * 200;

      if (n.type === 'chapter') {
        const angle = (chNodes.indexOf(n) / Math.max(chNodes.length, 1)) * 2 * Math.PI - Math.PI / 2;
        const ring  = Math.min(width, height) * 0.28;
        x = cx + Math.cos(angle) * ring;
        y = cy + Math.sin(angle) * ring;
      } else if (ch) {
        x = ch.x || cx;
        y = ch.y || cy;
      }

      const node = { ...n, x, y, vx: 0, vy: 0, r, mass: n.type === 'chapter' ? 5 : n.type === 'topic' ? 2 : 1 };
      nodeMap[n.id] = node;
      return node;
    });

    s.links = links.map(l => ({ ...l }));
    s.nodeMap = nodeMap;
    s.pan = { x: 0, y: 0 };
    s.zoom = 1;
  }, [nodes, links, width, height]);

  // Animation loop
  useEffect(() => {
    const s  = stateRef.current;
    const svg = svgRef.current;
    if (!svg) return;

    s.running = true;

    const tick = () => {
      if (!s.running) return;
      simulate(s, width, height);
      render(svg, s);
      s.raf = requestAnimationFrame(tick);
    };
    s.raf = requestAnimationFrame(tick);

    return () => {
      s.running = false;
      cancelAnimationFrame(s.raf);
    };
  }, [nodes, links, width, height]);

  // Pointer events
  const onPointerDown = useCallback((e) => {
    const s   = stateRef.current;
    const svg = svgRef.current;
    if (!svg) return;
    const pt  = svgPoint(svg, e.clientX, e.clientY);
    const wx  = (pt.x - s.pan.x) / s.zoom;
    const wy  = (pt.y - s.pan.y) / s.zoom;
    const hit = s.nodes.find(n => Math.hypot(n.x - wx, n.y - wy) <= n.r + 4);
    if (hit) {
      s.drag = hit;
      s.drag_start = { x: e.clientX, y: e.clientY };
    } else {
      s.pan_start = { mx: pt.x, my: pt.y, px: s.pan.x, py: s.pan.y };
    }
    e.preventDefault();
  }, []);

  const onPointerMove = useCallback((e) => {
    const s = stateRef.current;
    const svg = svgRef.current;
    if (!svg) return;
    const pt = svgPoint(svg, e.clientX, e.clientY);
    if (s.drag) {
      const wx = (pt.x - s.pan.x) / s.zoom;
      const wy = (pt.y - s.pan.y) / s.zoom;
      s.drag.x = wx;
      s.drag.y = wy;
      s.drag.vx = 0; s.drag.vy = 0;
    } else if (s.pan_start) {
      s.pan.x = s.pan_start.px + (pt.x - s.pan_start.mx);
      s.pan.y = s.pan_start.py + (pt.y - s.pan_start.my);
    }
  }, []);

  const onPointerUp = useCallback((e) => {
    const s = stateRef.current;
    if (s.drag && onNodeClick && s.drag_start) {
      const dx = e.clientX - s.drag_start.x;
      const dy = e.clientY - s.drag_start.y;
      if (Math.hypot(dx, dy) < 6) {
        onNodeClick(s.drag);
      }
    }
    s.drag = null;
    s.drag_start = null;
    s.pan_start = null;
  }, [onNodeClick]);

  const onWheel = useCallback((e) => {
    e.preventDefault();
    const s   = stateRef.current;
    const svg = svgRef.current;
    if (!svg) return;
    const delta  = -e.deltaY * 0.0008;
    const prev   = s.zoom;
    s.zoom       = Math.max(0.3, Math.min(3, s.zoom + delta));
    const pt     = svgPoint(svg, e.clientX, e.clientY);
    const wx     = (pt.x - s.pan.x) / prev;
    const wy     = (pt.y - s.pan.y) / prev;
    s.pan.x      = pt.x - wx * s.zoom;
    s.pan.y      = pt.y - wy * s.zoom;
  }, []);

  return (
    <svg
      ref={svgRef}
      width={width}
      height={height}
      style={{ display: 'block', cursor: 'grab', userSelect: 'none', background: 'var(--surface)' }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onWheel={onWheel}
    >
      <g id="fg-root" />
    </svg>
  );
}

// ── Physics ───────────────────────────────────────────────────────────────────
function simulate(s, W, H) {
  const { nodes, links, nodeMap } = s;

  nodes.forEach(n => { n.fx = 0; n.fy = 0; });

  // Repulsion
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      const dx = b.x - a.x, dy = b.y - a.y;
      const dist = Math.max(Math.hypot(dx, dy), 1);
      if (dist < (a.r + b.r + 30) * 4) {
        const f  = REPULSION / (dist * dist);
        const nx = dx / dist, ny = dy / dist;
        a.fx -= nx * f / a.mass;
        a.fy -= ny * f / a.mass;
        b.fx += nx * f / b.mass;
        b.fy += ny * f / b.mass;
      }
    }
  }

  // Spring links
  links.forEach(l => {
    const src = nodeMap[l.source], tgt = nodeMap[l.target];
    if (!src || !tgt) return;
    const dx   = tgt.x - src.x, dy = tgt.y - src.y;
    const dist = Math.max(Math.hypot(dx, dy), 1);
    const rest = LINK_REST[l.type] || 100;
    const f    = LINK_K * (dist - rest);
    const nx   = dx / dist, ny = dy / dist;
    src.fx += nx * f / src.mass;
    src.fy += ny * f / src.mass;
    tgt.fx -= nx * f / tgt.mass;
    tgt.fy -= ny * f / tgt.mass;
  });

  // Gravity to center
  nodes.forEach(n => {
    n.fx += (W / 2 - n.x) * GRAVITY * n.mass;
    n.fy += (H / 2 - n.y) * GRAVITY * n.mass;
  });

  // Integrate
  nodes.forEach(n => {
    if (n === s.drag) return;
    n.vx = (n.vx + n.fx) * DAMPING;
    n.vy = (n.vy + n.fy) * DAMPING;
    const spd = Math.hypot(n.vx, n.vy);
    if (spd > MAX_V) { n.vx *= MAX_V / spd; n.vy *= MAX_V / spd; }
    n.x += n.vx;
    n.y += n.vy;
    const m = n.r + 10;
    if (n.x < m) { n.x = m; n.vx *= -0.4; }
    if (n.x > W - m) { n.x = W - m; n.vx *= -0.4; }
    if (n.y < m) { n.y = m; n.vy *= -0.4; }
    if (n.y > H - m) { n.y = H - m; n.vy *= -0.4; }
  });
}

// ── Render ────────────────────────────────────────────────────────────────────
function render(svg, s) {
  const root = svg.getElementById('fg-root');
  if (!root) return;

  const { nodes, links, nodeMap, pan, zoom } = s;
  root.setAttribute('transform', `translate(${pan.x},${pan.y}) scale(${zoom})`);

  // Sync link elements
  let linkG = root.querySelector('#fg-links');
  if (!linkG) { linkG = svgEl('g', { id: 'fg-links' }); root.insertBefore(linkG, root.firstChild); }
  reconcileLines(linkG, links, nodeMap);

  // Sync node elements
  let nodeG = root.querySelector('#fg-nodes');
  if (!nodeG) { nodeG = svgEl('g', { id: 'fg-nodes' }); root.appendChild(nodeG); }
  reconcileNodes(nodeG, nodes);
}

function reconcileLines(parent, links, nodeMap) {
  const existing = [...parent.children];
  // Remove extras
  while (parent.children.length > links.length) parent.removeChild(parent.lastChild);
  // Add missing
  while (parent.children.length < links.length) parent.appendChild(svgEl('line', {}));

  links.forEach((l, i) => {
    const src = nodeMap[l.source], tgt = nodeMap[l.target];
    const el  = parent.children[i];
    if (!src || !tgt) { el.setAttribute('stroke-opacity', '0'); return; }
    attrs(el, {
      x1: src.x, y1: src.y, x2: tgt.x, y2: tgt.y,
      stroke: l.type === 'related' ? 'rgba(120,120,160,0.3)' : 'rgba(120,120,160,0.55)',
      'stroke-width': l.type === 'related' ? 0.6 : 1,
      'stroke-opacity': 1,
    });
  });
}

function reconcileNodes(parent, nodes) {
  // Ensure correct count of groups
  while (parent.children.length > nodes.length) parent.removeChild(parent.lastChild);
  while (parent.children.length < nodes.length) {
    const g   = svgEl('g', { style: 'cursor:pointer' });
    g.appendChild(svgEl('circle', {}));
    g.appendChild(svgEl('text', { 'pointer-events': 'none' }));
    parent.appendChild(g);
  }

  nodes.forEach((n, i) => {
    const g      = parent.children[i];
    const circle = g.children[0];
    const text   = g.children[1];
    const base   = NODE_COLOR[n.type] || NODE_COLOR.concept;
    const stroke = STATUS_STROKE[n.status] || base.stroke;
    const r = n.r;

    attrs(circle, {
      cx: n.x, cy: n.y, r,
      fill: base.fill,
      stroke,
      'stroke-width': n.type === 'chapter' ? 2 : 1.5,
      'stroke-opacity': 0.9,
    });

    // Label — always shown; concepts truncated shorter
    const label   = n.label || '';
    const maxLen  = n.type === 'chapter' ? 22 : n.type === 'topic' ? 18 : 14;
    const display = label.length > maxLen ? label.slice(0, maxLen - 1) + '…' : label;
    attrs(text, {
      x: n.x,
      y: n.y + r + (n.type === 'concept' ? 9 : 12),
      'text-anchor': 'middle',
      'font-size': n.type === 'chapter' ? 11 : n.type === 'topic' ? 9 : 7.5,
      fill: n.type === 'chapter' ? '#c9d1d9' : n.type === 'topic' ? 'rgba(180,200,220,0.85)' : 'rgba(160,175,190,0.6)',
      display: '',
    });
    text.textContent = display;

    g.dataset.id = n.id;
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function svgEl(tag, attrMap) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  if (attrMap) attrs(el, attrMap);
  return el;
}

function attrs(el, map) {
  for (const [k, v] of Object.entries(map)) el.setAttribute(k, v);
}

function svgPoint(svg, clientX, clientY) {
  const rect = svg.getBoundingClientRect();
  return { x: clientX - rect.left, y: clientY - rect.top };
}
