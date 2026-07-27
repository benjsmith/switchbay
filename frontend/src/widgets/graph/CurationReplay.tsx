import { useEffect, useRef } from "react";
import * as d3 from "d3";

/**
 * CurationReplay — opening animation for the Graph tab.
 *
 * Plays back the workspace's wiki/ git history as a force-directed
 * graph that grows over ~15 seconds and progressively comes to
 * resemble the real graph viewer (same palette, degree-proportional
 * node sizes, labels on the most-connected nodes). The parent
 * crossfades the real graph in beneath us when both data and the
 * replay's tail-settle are ready.
 *
 * The replay key (parent state) is incremented on user "replay"
 * requests so the effect re-runs cleanly with a fresh simulation.
 */

type Event =
  | { t: number; op: "node"; id: string; title: string; type: string }
  | { t: number; op: "edge"; source: string; target: string };

type HistoryDoc = {
  duration: number;
  events: Event[];
  source: string;
  generated_at?: number;
  node_count?: number;
  /** id → degree count, computed from the emitted edges. Used to
   *  size nodes so the closing frame matches the real graph. */
  degree?: Record<string, number>;
};

// Same palette the real graph + sidebar use, so the transition into
// the real view doesn't flicker.
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

// Mirrors graph.js's nodeRadius formula exactly so the closing
// frame of the replay matches the real viewer's node sizing.
// graph.js: `4 + Math.sqrt((d.degree || 0) + 1) * 1.6`.
const NODE_R_MIN = 4 + Math.sqrt(1) * 1.6;  // ≈ 5.6
function radiusFor(deg: number): number {
  return 4 + Math.sqrt((deg || 0) + 1) * 1.6;
}

// Same PHYSICS_DEFAULTS as the real graph viewer (graph.js).
// Aligning these makes the replay's closing frame settle into
// the same shape the real viewer renders.
const PHYSICS = { charge: -420, link: 110, collide: 10 };

type SimNode = d3.SimulationNodeDatum & {
  id: string;
  title: string;
  type: string;
  finalDeg: number;
  /** Current rendered radius. Lerped toward `radiusFor(finalDeg)`
   *  as more incident edges arrive so the dot grows visibly. */
  r: number;
};
type SimLink = d3.SimulationLinkDatum<SimNode> & {
  source: string | SimNode;
  target: string | SimNode;
};

type Props = {
  /** Bump to force a fresh replay (used by the parent's replay
   *  button). The effect's [replayKey] dep re-runs the whole
   *  animation. */
  replayKey?: number;
  onDone?: () => void;
  fading?: boolean;
};

export default function CurationReplay({ replayKey = 0, onDone, fading }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;
  // Live counts surfaced in the bottom-right corner. Updated
  // imperatively from the tick loop so we don't pay for a React
  // re-render on every frame; the labels are written via refs
  // straight into a couple of <span>s.
  const countRef = useRef<{ n: number; e: number }>({ n: 0, e: 0 });
  const nodeCountSpanRef = useRef<HTMLSpanElement>(null);
  const edgeCountSpanRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    let cancelled = false;
    let cleanup = () => { /* set below */ };
    countRef.current = { n: 0, e: 0 };
    if (nodeCountSpanRef.current) nodeCountSpanRef.current.textContent = "0";
    if (edgeCountSpanRef.current) edgeCountSpanRef.current.textContent = "0";

    (async () => {
      let history: HistoryDoc | null = null;
      try {
        const r = await fetch("/api/curation/history");
        if (r.ok) history = (await r.json()) as HistoryDoc;
      } catch {
        // Quiet failure mode — better to render an empty canvas
        // than crash the loading-state component.
      }
      if (cancelled || !svgRef.current) return;
      const svg = svgRef.current;
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

      const events = (history?.events ?? []).slice();
      // `history.duration` is no longer used to pace the animation
      // (we now run as fast as the browser can render with an
      // adaptive per-frame event budget) but the field is kept on
      // the JSON for backward compat with older caches.
      const finalDegree = history?.degree ?? {};
      // Top-N most-connected nodes get a label drawn alongside,
      // mirroring the real graph viewer's labelling. 30 keeps the
      // canvas readable without crowding.
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
      const incidentCount = new Map<string, number>();  // running tally

      // Physics matched to the real graph viewer (graph.js
      // PHYSICS_DEFAULTS) so the closing frame settles into the
      // same shape the real viewer renders. Earlier the replay
      // used a much-compressed parameter set and the cloud read
      // as too dense vs the real picture.
      const sim = d3
        .forceSimulation<SimNode>(nodes)
        .force("charge", d3.forceManyBody<SimNode>()
          .strength(PHYSICS.charge)
          .distanceMax(500))
        .force("center", d3.forceCenter(W / 2, H / 2).strength(0.05))
        .force("collide", d3.forceCollide<SimNode>((d) => d.r + PHYSICS.collide))
        .force(
          "link",
          d3.forceLink<SimNode, SimLink>(links)
            .id((d) => d.id)
            .distance(PHYSICS.link)
            .strength(0.55),
        )
        // alphaTarget keeps the sim lightly hot so new events
        // get absorbed without restart() kicks that visibly
        // pulse the cloud.
        .alphaDecay(0.005)
        .alphaTarget(0.03)
        .velocityDecay(0.35);

      // Zoom + pan via d3.zoom on the root <g>. Auto-fit runs
      // until the user manually interacts (wheel / drag); after
      // that, programmatic transforms back off so the user
      // controls the camera. Click-and-drag pans; wheel zooms.
      let userInteracted = false;
      const zoom = d3.zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.15, 6])
        .on("zoom", (event) => {
          root.attr("transform", event.transform.toString());
        });
      sel.call(zoom);
      // Initial identity transform.
      sel.call(zoom.transform, d3.zoomIdentity);
      const markUser = () => { userInteracted = true; };
      // .on("start") with sourceEvent set means the zoom came
      // from a real DOM event (not a programmatic .transform()
      // call). That's the signal to stop auto-fitting.
      zoom.on("start.user", (event) => {
        if (event.sourceEvent) userInteracted = true;
      });
      // Also mark on any direct pointer/wheel interaction with
      // the svg, in case d3 misses an edge case.
      svg.addEventListener("wheel", markUser, { passive: true });
      svg.addEventListener("mousedown", markUser);
      svg.addEventListener("touchstart", markUser, { passive: true });

      // Auto-fit ease: compute target zoom transform that frames
      // the current node cloud, lerp toward it. Skipped once the
      // user has taken over.
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
        // Lerp the current transform toward target so the camera
        // glides rather than snaps.
        const current = d3.zoomTransform(svg);
        const k = 0.08;
        const blended = d3.zoomIdentity
          .translate(
            current.x + (target.x - current.x) * k,
            current.y + (target.y - current.y) * k,
          )
          .scale(current.k + (target.k - current.k) * k);
        // Use zoom.transform so d3.zoom stays in sync (next
        // user interaction starts from this transform).
        sel.call(zoom.transform, blended);
      };

      // Per-tick DOM updates are the hot path. d3's selectAll-by-data
      // joins are cheap; what kills FPS is doing both a 500-node
      // viewBox recompute AND a 500-node radius lerp every tick on
      // top of the force computation. Throttle the heavy ops to
      // every Nth tick — the picture moves continuously, but the
      // camera + radii ease in at ~12 Hz instead of 60.
      const tick = () => {
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
        if (tickCount % 5 === 0) {
          easeAutoFit();
        }
      };
      sim.on("tick", tick);

      let next = 0;
      const startedAt = performance.now();
      let raf = 0;
      let doneFired = false;
      let tickCount = 0;
      let settleStarted = false;
      let settleStartedAt: number | null = null;
      // Count how many new nodes arrived since the last force-table
      // refresh so we only bump alpha when something genuinely
      // structural happened (not on every isolated edge add).
      let pendingNodeAdds = 0;

      // Inflate node radius gradually toward its final degree-based
      // size. Each tick after an incident-count change, lerp the
      // rendered `r` 20% toward the target — looks like nodes
      // growing organically as connections land.
      const inflateRadii = () => {
        let any = false;
        for (const n of nodes) {
          const target = radiusFor(incidentCount.get(n.id) ?? 0);
          if (Math.abs(target - n.r) > 0.05) {
            n.r += (target - n.r) * 0.18;
            any = true;
          }
        }
        return any;
      };

      // Adaptive event budget. We want to process events as fast
      // as the browser can render — no fixed-duration pacing. But
      // dropping a thousand nodes in a single frame stalls the
      // tick (force computation is O(N²) for charge), which kills
      // FPS. Instead: tune budget per frame based on observed
      // frame time. Aim for 16ms; throttle harder if we exceed
      // it, open up if we're under.
      let eventsPerFrame = 40;
      let lastFrameAt = startedAt;
      const step = () => {
        if (cancelled) return;
        const now = performance.now();
        const frameMs = now - lastFrameAt;
        lastFrameAt = now;
        // Tune budget toward the 16ms target. Smooth the
        // adjustment so a single jittery frame doesn't slam the
        // budget; keep it inside [5, 120].
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
            const finalDeg = finalDegree[ev.id] ?? 0;
            // Drop on a golden-angle spiral around centre of mass.
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
              finalDeg,
              r: NODE_R_MIN,
              x: cx + Math.cos(angle) * r,
              y: cy + Math.sin(angle) * r,
            };
            nodes.push(n);
            byId.set(ev.id, n);
            incidentCount.set(ev.id, 0);
            mutated = true;
            pendingNodeAdds += 1;
            countRef.current.n += 1;
          } else if (ev.op === "edge") {
            const s = byId.get(ev.source);
            const t = byId.get(ev.target);
            if (s && t) {
              links.push({ source: s, target: t });
              incidentCount.set(s.id, (incidentCount.get(s.id) ?? 0) + 1);
              incidentCount.set(t.id, (incidentCount.get(t.id) ?? 0) + 1);
              mutated = true;
              countRef.current.e += 1;
            }
          }
          next++;
        }
        // Imperative DOM write so the counter updates without a
        // React re-render. Cheap — two textContent assignments.
        if (mutated) {
          if (nodeCountSpanRef.current) {
            nodeCountSpanRef.current.textContent = String(countRef.current.n);
          }
          if (edgeCountSpanRef.current) {
            edgeCountSpanRef.current.textContent = String(countRef.current.e);
          }
        }
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
                .call((selN) =>
                  selN.transition().duration(500).attr("opacity", 0.95),
                ),
            );
          labelG.selectAll<SVGTextElement, SimNode>("text")
            .data(
              nodes.filter((n) => labelledIds.has(n.id)),
              (d) => d.id,
            )
            .join((enter) =>
              enter.append("text")
                .attr("class", "cr-label")
                .attr("text-anchor", "middle")
                .attr("fill", "var(--text-muted, #aaa)")
                .attr("font-size", 10)
                .attr("opacity", 0)
                .text((d) => d.title)
                .call((selT) =>
                  selT.transition().duration(700).attr("opacity", 0.85),
                ),
            );
          linkG.selectAll<SVGLineElement, SimLink>("line")
            .data(links)
            .join((enter) =>
              enter.append("line")
                .attr("stroke", "#888")
                .attr("stroke-width", 0.5)
                .attr("stroke-opacity", 0)
                .call((selL) =>
                  selL.transition().duration(700).attr("stroke-opacity", 0.35),
                ),
            );
          sim.nodes(nodes);
          (sim.force("link") as d3.ForceLink<SimNode, SimLink>).links(links);
          // The sim is already running (alphaTarget keeps it hot).
          // Only ensure d3 picks up the new node/edge arrays — no
          // alpha kick needed unless a meaningful batch of nodes
          // arrived, in which case a small bump helps them slot
          // into the layout. Skip the kick when only edges came
          // along (they exert force immediately via the link
          // constraint without a reheat).
          if (pendingNodeAdds > 0 && sim.alpha() < 0.22) {
            // Gentle kick scaled by how many new nodes landed —
            // a single new node barely moves alpha; a 10-node
            // burst gets a small but visible bump. Capped so it
            // never spikes hard enough to pulse the layout.
            const kick = Math.min(0.22, 0.06 + pendingNodeAdds * 0.004);
            sim.alpha(kick);
          }
          pendingNodeAdds = 0;
        }
        // Radius inflation is a 500-node pass; throttle it the
        // same way as viewBox.
        if (tickCount % 3 === 0) inflateRadii();
        // Tail-settle phase. Once every event has fired, drop
        // alphaTarget (let the sim decay) and inject a strong
        // alpha so the late-arriving edges actually pull their
        // endpoints into place before we hand off. Previously the
        // tail ran with alphaTarget=0.03 (gentle motion) and the
        // wiring didn't visibly converge before fade-out.
        const eventsDrained = next >= events.length;
        if (eventsDrained && !settleStarted) {
          settleStarted = true;
          settleStartedAt = now;
          sim.alphaTarget(0).alpha(0.6).restart();
        }
        // Fire onDone once the layout looks stable (alpha low)
        // after the settle phase. A wall-clock safety guards
        // against a layout that refuses to decay.
        const alpha = sim.alpha();
        const stable = settleStarted && alpha < 0.04;
        const settleElapsed = settleStarted
          ? (now - (settleStartedAt || now)) / 1000
          : 0;
        const settleTimeout = settleElapsed > 6.0;
        if (!doneFired && (stable || settleTimeout)) {
          doneFired = true;
          onDoneRef.current?.();
        }
        raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);

      cleanup = () => {
        cancelAnimationFrame(raf);
        sim.stop();
        sel.selectAll("*").remove();
      };
    })();

    return () => {
      cancelled = true;
      cleanup();
    };
  }, [replayKey]);

  return (
    <div
      className={
        "sy-curation-replay" + (fading ? " sy-curation-replay--fading" : "")
      }
    >
      <svg ref={svgRef} className="sy-curation-replay-svg" />
      <div className="sy-curation-replay-label">
        Replaying curation history — scroll or drag to zoom/pan
      </div>
      <div className="sy-graph-count">
        <span ref={nodeCountSpanRef}>0</span> nodes ·{" "}
        <span ref={edgeCountSpanRef}>0</span> edges
      </div>
    </div>
  );
}
