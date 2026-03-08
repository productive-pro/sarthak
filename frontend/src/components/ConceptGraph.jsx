/**
 * ConceptGraph — interactive force-directed graph for space roadmap.
 * Nodes: chapters (large) + concepts (small). Click a node to navigate.
 * Supports pan, zoom, drag.
 */
import { useEffect, useRef, useState } from 'react';

const COLORS = {
  chapter_bg: '#1c1c22',
  chapter_stroke: '#6b7280',
  chapter_active: '#fbbf24',
  chapter_done: '#4ade80',
  concept_bg: '#24243080',
  concept_stroke: '#4b5563',
  concept_done: '#4ade80',
  concept_active: '#fbbf24',
  link_hierarchy: 'rgba(100,100,120,0.5)',
  link_related: 'rgba(100,100,120,0.25)',
  text: '#e5e7eb',
  text_dim: '#9ca3af',
};

function buildGraph(spaceRoadmap, graphData) {
  const nodes = [];
  const links = [];
  const nodeById = {};

  const chapters = spaceRoadmap?.chapters || [];
  const backNodes = graphData?.nodes || [];
  const backLinks = graphData?.links || [];

  // Chapter nodes
  chapters.forEach(ch => {
    const n = { id: ch.id, label: ch.title, type: 'chapter', status: ch.status || 'not_started', chapterIdx: chapters.indexOf(ch) };
    nodes.push(n);
    nodeById[ch.id] = n;
  });

  // Concept nodes from graph endpoint
  backNodes.forEach(n => {
    const cn = { id: n.id, label: n.title, type: 'concept', status: n.status || 'not_started', chapterLabel: n.chapter || '' };
    nodes.push(cn);
    nodeById[n.id] = cn;
  });

  // Hierarchy links: concept → its chapter
  backNodes.forEach(n => {
    const ch = chapters.find(c => c.title === n.chapter);
    if (ch && nodeById[n.id]) links.push({ source: ch.id, target: n.id, type: 'hierarchy' });
  });

  // Cross links
  backLinks.forEach(l => links.push({ source: l.source, target: l.target, type: 'related' }));

  return { nodes, links, nodeById };
}

function initPositions(nodes, W, H) {
  const chapters = nodes.filter(n => n.type === 'chapter');
  const byChapter = {};

  const CH_R = Math.min(W, H) * 0.28;
  chapters.forEach((ch, i) => {
    const angle = (i / Math.max(chapters.length, 1)) * 2 * Math.PI - Math.PI / 2;
    ch.x = W / 2 + Math.cos(angle) * CH_R;
    ch.y = H / 2 + Math.sin(angle) * CH_R;
    ch.vx = 0; ch.vy = 0; ch.r = 26; ch.mass = 5; ch.angle = angle;
    byChapter[ch.label] = ch;
  });

  nodes.filter(n => n.type === 'concept').forEach((cn, idx) => {
    const parent = byChapter[cn.chapterLabel] || chapters[0];
    if (parent) {
      const angle = (idx * 2.39996) + (parent.angle || 0);
      const r = 70 + (Math.floor(idx / 8)) * 40;
      cn.x = (parent?.x || W / 2) + Math.cos(angle) * r;
      cn.y = (parent?.y || H / 2) + Math.sin(angle) * r;
    } else {
      cn.x = W / 2 + (Math.random() - 0.5) * 200;
      cn.y = H / 2 + (Math.random() - 0.5) * 200;
    }
    cn.vx = 0; cn.vy = 0; cn.r = 7; cn.mass = 1;
  });
}

export default function ConceptGraph({ spaceRoadmap, graphData, onNodeClick }) {
  const canvasRef = useRef(null);
  const stateRef = useRef({ pan: { x: 0, y: 0 }, zoom: 1, dragNode: null, panStart: null, nodes: [], links: [], nodeById: {}, hovered: null, raf: null });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const parent = canvas.parentElement;

    const state = stateRef.current;
    const { nodes, links, nodeById } = buildGraph(spaceRoadmap, graphData);
    state.nodes = nodes;
    state.links = links;
    state.nodeById = nodeById;

    const resize = () => {
      canvas.width = parent.clientWidth;
      canvas.height = parent.clientHeight;
      initPositions(nodes, canvas.width, canvas.height);
    };
    resize();

    const W = () => canvas.width;
    const H = () => canvas.height;

    // ── physics ──
    const REPEL = 3000, LINK_K = 0.04, LINK_REST = 90, GRAV = 0.005, DAMP = 0.82, MAX_V = 10;

    function tick() {
      nodes.forEach(n => { n.fx = 0; n.fy = 0; });
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i], b = nodes[j];
          const dx = b.x - a.x, dy = b.y - a.y;
          const d = Math.max(Math.hypot(dx, dy), 1);
          if (d < (a.r + b.r) * 6) {
            const f = REPEL / (d * d);
            const nx = dx / d, ny = dy / d;
            a.fx -= nx * f; a.fy -= ny * f;
            b.fx += nx * f; b.fy += ny * f;
          }
        }
      }
      links.filter(l => l.type === 'hierarchy').forEach(l => {
        const s = nodeById[l.source], t = nodeById[l.target];
        if (!s || !t) return;
        const dx = t.x - s.x, dy = t.y - s.y;
        const d = Math.max(Math.hypot(dx, dy), 1);
        const f = LINK_K * (d - LINK_REST);
        const nx = dx / d, ny = dy / d;
        s.fx += nx * f; s.fy += ny * f;
        t.fx -= nx * f; t.fy -= ny * f;
      });
      nodes.forEach(n => {
        n.fx += (W() / 2 - n.x) * GRAV * n.mass;
        n.fy += (H() / 2 - n.y) * GRAV * n.mass;
      });
      nodes.forEach(n => {
        if (n === state.dragNode) return;
        n.vx = (n.vx + n.fx / n.mass) * DAMP;
        n.vy = (n.vy + n.fy / n.mass) * DAMP;
        const spd = Math.hypot(n.vx, n.vy);
        if (spd > MAX_V) { n.vx *= MAX_V / spd; n.vy *= MAX_V / spd; }
        n.x += n.vx; n.y += n.vy;
        const m = n.r + 8;
        n.x = Math.max(m, Math.min(W() - m, n.x));
        n.y = Math.max(m, Math.min(H() - m, n.y));
      });
    }

    function toWorld(sx, sy) {
      return { x: (sx - state.pan.x) / state.zoom, y: (sy - state.pan.y) / state.zoom };
    }

    function hitTest(sx, sy) {
      const w = toWorld(sx, sy);
      return nodes.find(n => Math.hypot(n.x - w.x, n.y - w.y) <= n.r + 4);
    }

    // ── draw ──
    function draw() {
      ctx.clearRect(0, 0, W(), H());
      ctx.save();
      ctx.translate(state.pan.x, state.pan.y);
      ctx.scale(state.zoom, state.zoom);

      // links
      links.forEach(l => {
        const s = nodeById[l.source], t = nodeById[l.target];
        if (!s || !t) return;
        ctx.beginPath();
        ctx.strokeStyle = l.type === 'related' ? COLORS.link_related : COLORS.link_hierarchy;
        ctx.lineWidth = l.type === 'related' ? 0.7 : 1;
        ctx.moveTo(s.x, s.y); ctx.lineTo(t.x, t.y);
        ctx.stroke();
      });

      // nodes
      nodes.forEach(n => {
        const isHov = n === state.hovered;
        const done = n.status === 'completed';
        const active = n.status === 'in_progress';
        const strokeColor = done ? COLORS.concept_done : active ? COLORS.chapter_active : (n.type === 'chapter' ? COLORS.chapter_stroke : COLORS.concept_stroke);

        ctx.beginPath();
        ctx.arc(n.x, n.y, isHov ? n.r + 3 : n.r, 0, Math.PI * 2);
        ctx.fillStyle = n.type === 'chapter' ? COLORS.chapter_bg : COLORS.concept_bg;
        ctx.fill();
        ctx.strokeStyle = isHov ? '#a78bfa' : strokeColor;
        ctx.lineWidth = n.type === 'chapter' ? 1.8 : 1;
        ctx.stroke();

        if (n.type === 'chapter' || isHov) {
          ctx.font = `${n.type === 'chapter' ? 11 : 9}px sans-serif`;
          ctx.fillStyle = isHov ? '#e5e7eb' : COLORS.text_dim;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          const maxLen = n.type === 'chapter' ? 14 : 10;
          const label = n.label.length > maxLen ? n.label.slice(0, maxLen - 1) + '…' : n.label;
          ctx.fillText(label, n.x, n.type === 'chapter' ? n.y : n.y + n.r + 8);
        }
      });

      ctx.restore();
    }

    function loop() { tick(); draw(); state.raf = requestAnimationFrame(loop); }
    loop();

    // ── events ──
    const onWheel = (e) => {
      e.preventDefault();
      const delta = -e.deltaY * 0.001;
      const prev = state.zoom;
      state.zoom = Math.min(3, Math.max(0.4, state.zoom + delta));
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const wx = (mx - state.pan.x) / prev, wy = (my - state.pan.y) / prev;
      state.pan.x = mx - wx * state.zoom;
      state.pan.y = my - wy * state.zoom;
    };

    let dragStartPos = null;

    const onDown = (e) => {
      const rect = canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
      const hit = hitTest(sx, sy);
      dragStartPos = { x: sx, y: sy };
      if (hit) {
        state.dragNode = hit;
      } else {
        state.panStart = { x: sx, y: sy, px: state.pan.x, py: state.pan.y };
      }
    };

    const onMove = (e) => {
      const rect = canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
      state.hovered = hitTest(sx, sy);
      canvas.style.cursor = state.hovered ? 'pointer' : (state.dragNode || state.panStart ? 'grabbing' : 'grab');

      if (state.dragNode) {
        const w = toWorld(sx, sy);
        state.dragNode.x = w.x; state.dragNode.y = w.y;
        state.dragNode.vx = 0; state.dragNode.vy = 0;
      } else if (state.panStart) {
        state.pan.x = state.panStart.px + (sx - state.panStart.x);
        state.pan.y = state.panStart.py + (sy - state.panStart.y);
      }
    };

    const onUp = (e) => {
      const rect = canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
      const moved = dragStartPos ? Math.hypot(sx - dragStartPos.x, sy - dragStartPos.y) : 99;

      // click (not drag)
      if (moved < 5 && state.dragNode && onNodeClick) {
        onNodeClick(state.dragNode);
      }
      state.dragNode = null;
      state.panStart = null;
      dragStartPos = null;
    };

    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('mousedown', onDown);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);

    return () => {
      cancelAnimationFrame(state.raf);
      canvas.removeEventListener('wheel', onWheel);
      canvas.removeEventListener('mousedown', onDown);
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [spaceRoadmap, graphData]);

  const chCount = (spaceRoadmap?.chapters || []).length;
  const cnCount = (spaceRoadmap?.chapters || []).reduce((a, ch) => a + (ch.topics || []).reduce((b, t) => b + (t.concepts || []).length, 0), 0);

  if (!chCount) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--txt3)', fontSize: 13 }}>
      No chapters yet — generate a roadmap first.
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 14px', borderBottom: '1px solid var(--brd)', flexShrink: 0 }}>
        <div style={{ display: 'flex', gap: 14, fontSize: 11.5, color: 'var(--txt3)' }}>
          <span><strong style={{ color: 'var(--txt2)' }}>{chCount}</strong> chapters</span>
          <span><strong style={{ color: 'var(--txt2)' }}>{cnCount}</strong> concepts</span>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 11, color: 'var(--txt3)' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: '#4ade80' }} /> done/active</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: '#6b7280' }} /> pending</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><span style={{ display: 'inline-block', width: 12, height: 12, borderRadius: '50%', background: '#1c1c22', border: '1.5px solid #6b7280' }} /> chapter</span>
          <span style={{ opacity: 0.5 }}>scroll to zoom · drag to pan · click node to navigate</span>
        </div>
      </div>
      <div style={{ flex: 1, position: 'relative' }}>
        <canvas ref={canvasRef} style={{ display: 'block', width: '100%', height: '100%' }} />
      </div>
    </div>
  );
}
