/* Forked from curiosity-engine's wiki-view (MIT License, Copyright (c)
 * 2026 curiosity-engine authors). Adapted for switchbay. See
 * docs/THIRD-PARTY-NOTICES.md. */

/* Subgraph view inside the doc viewer modal.
 *
 * 1-hop force-directed mini-graph:
 *   - Centre node = current modal target. Pinned at the viewport middle
 *     so the rest of the layout fans around it. Label always visible.
 *   - Direct neighbours arrange around it via force simulation, with
 *     edges between any pair of nodes in the visible set drawn too
 *     (so triangles and side-clusters become visible).
 *
 * Layout runs as a normal d3-force simulation but is pre-warmed (~250
 * manual ticks) before any DOM update, so the user sees the settled
 * layout at first paint without watching it relax.
 *
 * Click any non-centre node → push hash, main-router swaps the modal
 * content to that page; the subgraph re-renders for the new centre.
 *
 * Painting order: edges → circles → labels (top). Labels live in a
 * dedicated layer above all circles so a label never gets buried under
 * a sibling node's circle. Hover wiring sets `data-hover="true"` on
 * the label that matches the hovered circle's id; CSS swaps opacity.
 */
window.Subgraph = (function () {
  let allNodes = null, allEdges = null, palette = null;
  let nodeById = new Map();
  let neighbours = new Map();
  let containerEl = null, headEl = null;

  // Title parsing + wrapping (mirrors main graph).
  const TITLE_PREFIX_RE = /^(\[[^\]]+\])\s+(.+)$/;
  function parseTitle(t) {
    const m = TITLE_PREFIX_RE.exec(t);
    if (m) return { prefix: m[1], rest: m[2] };
    return { prefix: '', rest: t };
  }
  function wrapTitleBody(text, wpl) {
    const words = text.split(/\s+/).filter(Boolean);
    const lines = [];
    for (let i = 0; i < words.length; i += wpl) {
      lines.push(words.slice(i, i + wpl).join(' '));
    }
    return lines.length ? lines : [''];
  }
  const SUB_LINE_HEIGHT = 12;

  function buildLabelTspans(title, x) {
    const { prefix, rest } = parseTitle(title);
    const lines = wrapTitleBody(rest, 2);
    const parts = [];
    if (prefix) {
      parts.push(`<tspan class="label-prefix" x="${x}">${escapeHtml(prefix)}</tspan>`);
    }
    lines.forEach((line, i) => {
      const dy = (prefix || i > 0) ? ` dy="${SUB_LINE_HEIGHT}"` : '';
      parts.push(`<tspan x="${x}"${dy}>${escapeHtml(line)}</tspan>`);
    });
    return parts.join('');
  }

  function labelLineCount(title) {
    const { prefix, rest } = parseTitle(title);
    const body = wrapTitleBody(rest, 2);
    return body.length + (prefix ? 1 : 0);
  }

  function init(data) {
    allNodes = data.nodes;
    allEdges = data.edges || [];
    palette = data.palette || {};
    nodeById = new Map(allNodes.map(n => [n.id, n]));
    neighbours = new Map();
    allEdges.forEach(e => {
      const s = (typeof e.source === 'object') ? e.source.id : e.source;
      const t = (typeof e.target === 'object') ? e.target.id : e.target;
      if (!neighbours.has(s)) neighbours.set(s, new Set());
      if (!neighbours.has(t)) neighbours.set(t, new Set());
      neighbours.get(s).add(t);
      neighbours.get(t).add(s);
    });
    containerEl = document.querySelector('#modal-subgraph');
    headEl = document.querySelector('#modal-subgraph-head');

    if (!containerEl) return;

    // Click delegation — neighbour click navigates, centre is inert.
    containerEl.addEventListener('click', (ev) => {
      const g = ev.target.closest && ev.target.closest('.sub-circle');
      if (!g) return;
      if (g.classList.contains('sub-center')) return;
      const id = g.dataset.id;
      if (id) window.location.hash = '#page=' + encodeURIComponent(id);
    });

    // Hover wiring: paint the matching label in the top layer.
    function setHover(id, on) {
      if (!containerEl) return;
      const layer = containerEl.querySelector('.sub-labels');
      if (!layer) return;
      const label = layer.querySelector('[data-id="' + cssEscape(id) + '"]');
      if (label) label.dataset.hover = on ? 'true' : '';
    }
    containerEl.addEventListener('mouseover', (ev) => {
      const g = ev.target.closest && ev.target.closest('.sub-circle');
      if (!g) return;
      const id = g.dataset.id;
      if (id) setHover(id, true);
    });
    containerEl.addEventListener('mouseout', (ev) => {
      const g = ev.target.closest && ev.target.closest('.sub-circle');
      if (!g) return;
      const id = g.dataset.id;
      if (id) setHover(id, false);
    });
  }

  function render(centerId) {
    if (!containerEl) return;
    const center = nodeById.get(centerId);
    if (!center) { clear(); return; }

    const hop1 = neighbours.get(centerId) || new Set();
    if (headEl) {
      headEl.textContent = hop1.size > 0
        ? `Connections (${hop1.size})`
        : 'No connections';
    }
    if (hop1.size === 0) { containerEl.innerHTML = ''; return; }

    // Build node + edge sets — centre + 1-hop neighbours, plus every
    // edge whose endpoints both sit in the set (so triangles between
    // neighbours become visible without expanding to 2-hop).
    const ids = new Set([centerId]);
    hop1.forEach(id => ids.add(id));
    const subNodes = [...ids].map(id => Object.assign({
      hop: id === centerId ? 0 : 1,
    }, nodeById.get(id)));
    const subById = new Map(subNodes.map(n => [n.id, n]));
    const subEdges = [];
    for (const e of allEdges) {
      const sId = (typeof e.source === 'object') ? e.source.id : e.source;
      const tId = (typeof e.target === 'object') ? e.target.id : e.target;
      if (subById.has(sId) && subById.has(tId) && sId !== tId) {
        subEdges.push({ source: sId, target: tId, type: e.type });
      }
    }

    const W = containerEl.clientWidth || 600;
    // Height scales with neighbourhood size so dense hubs get breathing
    // room; small ones stay compact.
    const H = Math.max(420, Math.min(820, 360 + subNodes.length * 4));

    const cn = subById.get(centerId);
    cn.fx = W / 2;
    cn.fy = H / 2;

    const sim = d3.forceSimulation(subNodes)
      .force('link', d3.forceLink(subEdges).id(d => d.id)
        .distance(60).strength(0.5))
      .force('charge', d3.forceManyBody()
        .strength(d => d.hop === 0 ? -560 : -260)
        .distanceMax(360))
      .force('collide', d3.forceCollide(d => subRadius(d) + 8))
      .alpha(1)
      .alphaDecay(0.055)
      .stop();

    for (let i = 0; i < 280; i++) sim.tick();

    // Clamp inside the SVG so nothing escapes off-screen.
    const margin = 32;
    for (const n of subNodes) {
      n.x = Math.max(margin, Math.min(W - margin, n.x));
      n.y = Math.max(margin, Math.min(H - margin, n.y));
    }

    const colourFor = t => palette[t] || palette.default || '#7a7a7a';
    let svg = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">`;

    // ── Edges (bottom layer) ──
    svg += '<g class="sub-edges">';
    for (const e of subEdges) {
      const s = subById.get(typeof e.source === 'object' ? e.source.id : e.source);
      const t = subById.get(typeof e.target === 'object' ? e.target.id : e.target);
      svg += `<line class="sub-edge" data-kind="${escapeAttr(e.type)}" x1="${s.x.toFixed(1)}" y1="${s.y.toFixed(1)}" x2="${t.x.toFixed(1)}" y2="${t.y.toFixed(1)}"/>`;
    }
    svg += '</g>';

    // ── Circles (middle layer) ──
    svg += '<g class="sub-circles">';
    for (const n of subNodes) {
      const r = subRadius(n);
      const isCenter = n.id === centerId;
      const cls = isCenter ? 'sub-circle sub-center' : 'sub-circle';
      svg += `<g class="${cls}" data-id="${escapeAttr(n.id)}" data-type="${escapeAttr(n.type)}">
        <circle cx="${n.x.toFixed(1)}" cy="${n.y.toFixed(1)}" r="${r}" fill="${colourFor(n.type)}"/>
        <title>${escapeHtml(n.title || n.id)}</title>
      </g>`;
    }
    svg += '</g>';

    // ── Labels (top layer) ──
    // Centre's label is permanently visible; others toggle to opacity 1
    // when their corresponding circle is hovered (data-hover="true").
    // Multi-tspan rendering: grey [type] prefix on its own line, body
    // wrapped at ≤2 words per line.
    svg += '<g class="sub-labels">';
    for (const n of subNodes) {
      const r = subRadius(n);
      const isCenter = n.id === centerId;
      const cls = isCenter ? 'sub-label sub-label-centre' : 'sub-label';
      const title = n.title || n.id;
      const numLines = labelLineCount(title);
      const xStr = n.x.toFixed(1);
      const yStr = (n.y - r - 5 - (numLines - 1) * SUB_LINE_HEIGHT).toFixed(1);
      svg += `<text class="${cls}" data-id="${escapeAttr(n.id)}" x="${xStr}" y="${yStr}" text-anchor="middle">${buildLabelTspans(title, xStr)}</text>`;
    }
    svg += '</g>';

    svg += '</svg>';
    containerEl.innerHTML = svg;
  }

  function subRadius(d) {
    const baseR = 4 + Math.sqrt((d.degree || 0) + 1) * 1.4;
    if (d.hop === 0) return baseR + 2;
    return baseR;
  }

  function clear() {
    if (containerEl) containerEl.innerHTML = '';
    if (headEl) headEl.textContent = '';
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }
  function escapeAttr(s) { return escapeHtml(s); }
  function cssEscape(s) {
    if (window.CSS && CSS.escape) return CSS.escape(s);
    return String(s).replace(/[^a-zA-Z0-9_-]/g, c => '\\' + c);
  }

  return { init, render, clear };
})();
