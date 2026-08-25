import * as d3 from "d3";

/**
 * Curation-history replay animation shared by the PWA Graph tab and
 * the VS Code Graph webview. Drives an SVG; the caller owns the overlay
 * chrome (button, counts, fade).
 */

export type ReplayEvent =
  | { t: number; op: "node"; id: string; title: string; type: string }
  | { t: number; op: "edge"; source: string; target: string };

export type HistoryDoc = {
  duration: number;
  events: ReplayEvent[];
  source: string;
  generated_at?: number;
  node_count?: number;
  degree?: Record<string, number>;
};

const TYPE_COLOR: Record<string, string> = {
  project: "#4d1ae8",
  analysis: "#1d6996",
  concept: "#38a6a5",
  entity: "#0f8554",
  evidence: "#73af48",
  fact: "#edad08",
  figure: "#e17c05",
  table: "#cc503e",
  source: "#94346e",
  note: "#6f4070",
  "todo-list": "#9656a2",
  unclassified: "#ffffff",
};
function colorFor(t: string): string {
  return TYPE_COLOR[t] ?? TYPE_COLOR.unclassified ?? "#ffffff";
}

const NODE_R_MIN = 4 + Math.sqrt(1) * 1.6;
function radiusFor(deg: number): number {
  return 4 + Math.sqrt((deg || 0) + 1) * 1.6;
}
const PHYSICS = { charge: -420, link: 110, collide: 10 };

type SimNode = d3.SimulationNodeDatum & {
  id: string;
  title: string;
  type: string;
  finalDeg: number;
  r: number;
};
type SimLink = d3.SimulationLinkDatum<SimNode> & {
  source: string | SimNode;
  target: string | SimNode;
};

export function playCurationReplay(
  svg: SVGSVGElement,
  opts: {
    history: HistoryDoc | null;
    onDone?: () => void;
    onCounts?: (nodes: number, edges: number) => void;
  },
): () => void {
  let cancelled = false;
  const W = 1000;
  const H = 600;
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

  const sel = d3.select(svg);
  sel.selectAll("*").remove();
  const root = sel.append("g").attr("class", "cr-root");
  const linkG = root.append("g").attr("class", "cr-links");
  const nodeG = root.append("g").attr("class", "cr-nodes");
  const labelG = root.append("g").attr("class", "cr-labels");

  const events = (opts.history?.events ?? []).slice();
  const finalDegree = opts.history?.degree ?? {};
  const TOP_LABELS = 30;
  const labelledIds = new Set(
    Object.entries(finalDegree)
      .sort((a, b) => b[1] - a[1])
      .slice(0, TOP_LABELS)
      .map(([id]) => id),
  );

  const nodes: SimNode[] = [];
  const links: SimLink[] = [];
  const byId = new Map<string, SimNode>();
  const incidentCount = new Map<string, number>();
  const counts = { n: 0, e: 0 };

  const sim = d3
    .forceSimulation<SimNode>(nodes)
    .force("charge", d3.forceManyBody<SimNode>().strength(PHYSICS.charge).distanceMax(500))
    .force("center", d3.forceCenter(W / 2, H / 2).strength(0.05))
    .force("collide", d3.forceCollide<SimNode>((d) => d.r + PHYSICS.collide))
    .force(
      "link",
      d3.forceLink<SimNode, SimLink>(links).id((d) => d.id).distance(PHYSICS.link).strength(0.55),
    )
    .alphaDecay(0.005)
    .alphaTarget(0.03)
    .velocityDecay(0.35);

  let userInteracted = false;
  const zoom = d3.zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.15, 6])
    .on("zoom", (event) => {
      root.attr("transform", event.transform.toString());
    });
  sel.call(zoom);
  sel.call(zoom.transform, d3.zoomIdentity);
  const markUser = () => { userInteracted = true; };
  zoom.on("start.user", (event) => {
    if (event.sourceEvent) userInteracted = true;
  });
  svg.addEventListener("wheel", markUser, { passive: true });
  svg.addEventListener("mousedown", markUser);
  svg.addEventListener("touchstart", markUser, { passive: true });

  const easeAutoFit = () => {
    if (userInteracted || nodes.length === 0) return;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of nodes) {
      const x = n.x ?? W / 2;
      const y = n.y ?? H / 2;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    }
    const pad = Math.max(40, Math.min(maxX - minX, maxY - minY) * 0.12);
    const cloudW = Math.max(220, maxX - minX + pad * 2);
    const cloudH = Math.max(220, maxY - minY + pad * 2);
    const scale = Math.min(W / cloudW, H / cloudH, 1.5);
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    const tx = W / 2 - cx * scale;
    const ty = H / 2 - cy * scale;
    const target = d3.zoomIdentity.translate(tx, ty).scale(scale);
    const current = d3.zoomTransform(svg);
    const k = 0.08;
    const blended = d3.zoomIdentity
      .translate(
        current.x + (target.x - current.x) * k,
        current.y + (target.y - current.y) * k,
      )
      .scale(current.k + (target.k - current.k) * k);
    sel.call(zoom.transform, blended);
  };

  let tickCount = 0;
  sim.on("tick", () => {
    tickCount += 1;
    linkG.selectAll<SVGLineElement, SimLink>("line")
      .attr("x1", (d) => (d.source as SimNode).x ?? 0)
      .attr("y1", (d) => (d.source as SimNode).y ?? 0)
      .attr("x2", (d) => (d.target as SimNode).x ?? 0)
      .attr("y2", (d) => (d.target as SimNode).y ?? 0);
    nodeG.selectAll<SVGCircleElement, SimNode>("circle")
      .attr("cx", (d) => d.x ?? 0)
      .attr("cy", (d) => d.y ?? 0)
      .attr("r", (d) => d.r);
    labelG.selectAll<SVGTextElement, SimNode>("text")
      .attr("x", (d) => d.x ?? 0)
      .attr("y", (d) => (d.y ?? 0) - d.r - 4);
    if (tickCount % 5 === 0) easeAutoFit();
  });

  const inflateRadii = () => {
    for (const n of nodes) {
      const target = radiusFor(incidentCount.get(n.id) ?? 0);
      if (Math.abs(target - n.r) > 0.05) n.r += (target - n.r) * 0.18;
    }
  };

  let next = 0;
  const startedAt = performance.now();
  let raf = 0;
  let doneFired = false;
  let settleStarted = false;
  let settleStartedAt: number | null = null;
  let pendingNodeAdds = 0;
  let eventsPerFrame = 40;
  let lastFrameAt = startedAt;

  const step = () => {
    if (cancelled) return;
    const now = performance.now();
    const frameMs = now - lastFrameAt;
    lastFrameAt = now;
    if (frameMs > 22 && eventsPerFrame > 5) {
      eventsPerFrame = Math.max(5, Math.floor(eventsPerFrame * 0.8));
    } else if (frameMs < 14 && eventsPerFrame < 120) {
      eventsPerFrame = Math.min(120, eventsPerFrame + 4);
    }
    let processed = 0;
    let mutated = false;
    while (next < events.length && processed < eventsPerFrame) {
      const ev = events[next]!;
      processed += 1;
      if (ev.op === "node") {
        const angle = (next * 0.61803) * Math.PI * 2;
        const r = 180 + Math.random() * 80;
        const cx = nodes.length
          ? nodes.reduce((s, n) => s + (n.x ?? W / 2), 0) / nodes.length
          : W / 2;
        const cy = nodes.length
          ? nodes.reduce((s, n) => s + (n.y ?? H / 2), 0) / nodes.length
          : H / 2;
        const n: SimNode = {
          id: ev.id,
          title: ev.title,
          type: ev.type,
          finalDeg: finalDegree[ev.id] ?? 0,
          r: NODE_R_MIN,
          x: cx + Math.cos(angle) * r,
          y: cy + Math.sin(angle) * r,
        };
        nodes.push(n);
        byId.set(ev.id, n);
        incidentCount.set(ev.id, 0);
        mutated = true;
        pendingNodeAdds += 1;
        counts.n += 1;
      } else if (ev.op === "edge") {
        const s = byId.get(ev.source);
        const t = byId.get(ev.target);
        if (s && t) {
          links.push({ source: s, target: t });
          incidentCount.set(s.id, (incidentCount.get(s.id) ?? 0) + 1);
          incidentCount.set(t.id, (incidentCount.get(t.id) ?? 0) + 1);
          mutated = true;
          counts.e += 1;
        }
      }
      next++;
    }
    if (mutated) opts.onCounts?.(counts.n, counts.e);
    if (mutated) {
      nodeG.selectAll<SVGCircleElement, SimNode>("circle")
        .data(nodes, (d) => d.id)
        .join((enter) =>
          enter.append("circle")
            .attr("r", (d) => d.r)
            .attr("fill", (d) => colorFor(d.type))
            .attr("stroke", "rgba(0,0,0,0.35)")
            .attr("stroke-width", 0.6)
            .attr("opacity", 0)
            .call((selN) => selN.transition().duration(500).attr("opacity", 0.95)),
        );
      labelG.selectAll<SVGTextElement, SimNode>("text")
        .data(nodes.filter((n) => labelledIds.has(n.id)), (d) => d.id)
        .join((enter) =>
          enter.append("text")
            .attr("class", "cr-label")
            .attr("text-anchor", "middle")
            .attr("fill", "var(--text-muted, #aaa)")
            .attr("font-size", 10)
            .attr("opacity", 0)
            .text((d) => d.title)
            .call((selT) => selT.transition().duration(700).attr("opacity", 0.85)),
        );
      linkG.selectAll<SVGLineElement, SimLink>("line")
        .data(links)
        .join((enter) =>
          enter.append("line")
            .attr("stroke", "#888")
            .attr("stroke-width", 0.5)
            .attr("stroke-opacity", 0)
            .call((selL) => selL.transition().duration(700).attr("stroke-opacity", 0.35)),
        );
      sim.nodes(nodes);
      (sim.force("link") as d3.ForceLink<SimNode, SimLink>).links(links);
      if (pendingNodeAdds > 0 && sim.alpha() < 0.22) {
        const kick = Math.min(0.22, 0.06 + pendingNodeAdds * 0.004);
        sim.alpha(kick);
      }
      pendingNodeAdds = 0;
    }
    if (tickCount % 3 === 0) inflateRadii();
    const eventsDrained = next >= events.length;
    if (eventsDrained && !settleStarted) {
      settleStarted = true;
      settleStartedAt = now;
      sim.alphaTarget(0).alpha(0.6).restart();
    }
    const alpha = sim.alpha();
    const stable = settleStarted && alpha < 0.04;
    const settleElapsed = settleStarted ? (now - (settleStartedAt || now)) / 1000 : 0;
    if (!doneFired && (stable || settleElapsed > 6.0 || events.length === 0)) {
      doneFired = true;
      opts.onDone?.();
    }
    raf = requestAnimationFrame(step);
  };
  raf = requestAnimationFrame(step);

  return () => {
    cancelled = true;
    cancelAnimationFrame(raf);
    sim.stop();
    sel.selectAll("*").remove();
    svg.removeEventListener("wheel", markUser);
    svg.removeEventListener("mousedown", markUser);
    svg.removeEventListener("touchstart", markUser);
  };
}

/** Overlay + ↻ button for hosts that are not React (VS Code webview). */
export function installReplayChrome(
  pane: HTMLElement,
  loadHistory: () => Promise<HistoryDoc | null>,
): () => void {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "sy-graph-replay-btn";
  btn.dataset.tour = "graph-replay";
  btn.title = "Replay the curation history animation";
  btn.setAttribute("aria-label", "Replay curation history");
  btn.textContent = "↻";
  pane.appendChild(btn);

  let overlay: HTMLDivElement | null = null;
  let stopPlay: (() => void) | null = null;
  let fadeTimer = 0;

  const tearOverlay = () => {
    window.clearTimeout(fadeTimer);
    stopPlay?.();
    stopPlay = null;
    overlay?.remove();
    overlay = null;
    btn.disabled = false;
  };

  const start = async () => {
    if (btn.disabled) return;
    btn.disabled = true;
    tearOverlay();
    overlay = document.createElement("div");
    overlay.className = "sy-curation-replay";
    overlay.innerHTML = `
      <svg class="sy-curation-replay-svg"></svg>
      <div class="sy-curation-replay-label">Loading curation history…</div>
      <div class="sy-graph-count"><span data-n>0</span> nodes · <span data-e>0</span> edges</div>`;
    pane.appendChild(overlay);
    const svg = overlay.querySelector("svg")!;
    const label = overlay.querySelector(".sy-curation-replay-label")!;
    const nEl = overlay.querySelector("[data-n]")!;
    const eEl = overlay.querySelector("[data-e]")!;
    let history: HistoryDoc | null = null;
    try {
      history = await loadHistory();
    } catch {
      history = null;
    }
    if (!overlay.isConnected) return;
    const nEvents = history?.events?.length ?? 0;
    label.textContent = nEvents
      ? "Replaying curation history — scroll or drag to zoom/pan"
      : "No curation history yet";
    stopPlay = playCurationReplay(svg, {
      history,
      onCounts: (n, e) => {
        nEl.textContent = String(n);
        eEl.textContent = String(e);
      },
      onDone: () => {
        if (!overlay) return;
        overlay.classList.add("sy-curation-replay--fading");
        fadeTimer = window.setTimeout(() => {
          tearOverlay();
        }, 1500);
      },
    });
  };

  const onClick = () => { void start(); };
  btn.addEventListener("click", onClick);
  return () => {
    btn.removeEventListener("click", onClick);
    tearOverlay();
    btn.remove();
  };
}
