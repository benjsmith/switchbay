import { useMemo, useState } from "react";
import * as d3 from "d3";
import type { GraphData } from "../graph/types";
import { useSelection } from "../../selection/SelectionContext";

type Props = {
  data: GraphData;
  centerId: string;
  /** Workspace-relative path of the centre page; used to set selection
   *  when the user clicks back on the centre. */
  centerPath: string;
};

/** 1-hop force-directed subgraph rendered below the Editor preview.
 *
 *  Mirrors what the Graph tab's modal subgraph shows when you click
 *  a page: centre node + immediate neighbours, edges between any
 *  pair in the visible set so triangles surface. Layout uses d3-
 *  force (same parameters as the modal's subgraph) run for ~280
 *  static ticks at mount, so the result is laid out but doesn't
 *  jitter on re-renders.
 *
 *  Click on a non-centre node sets selection to that page; the
 *  Editor effect picks up the new selection and re-renders with
 *  the new centre. */
export default function MiniGraph({ data, centerId, centerPath }: Props) {
  const { setSelection } = useSelection();
  // Only the centre is labelled by default (like the Graph tab's modal
  // subgraph); a neighbour reveals its label on hover. Labelling every
  // node turns a 100-neighbour hub into an unreadable wall of text.
  const [hoverId, setHoverId] = useState<string | null>(null);

  const layout = useMemo(() => buildLayout(data, centerId), [data, centerId]);
  if (!layout) return null;

  const { center, neighbours, edges, w, h, palette } = layout;
  const colourFor = (t: string) => palette[t] || palette.default || "#7a7a7a";

  return (
    <section className="sy-editor-mini">
      <header className="sy-editor-mini-head">
        Connections ({neighbours.length})
      </header>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        width={w}
        height={h}
        className="sy-editor-mini-svg"
      >
        <g className="mini-edges">
          {edges.map((e, i) => (
            <line
              key={`e-${i}`}
              x1={e.x1}
              y1={e.y1}
              x2={e.x2}
              y2={e.y2}
              data-kind={e.type}
            />
          ))}
        </g>
        <g className="mini-circles">
          {[center, ...neighbours].map((n) => {
            const isCenter = n.id === centerId;
            const r = nodeRadius(n.degree ?? 0, isCenter);
            return (
              <g
                key={n.id}
                className={"mini-node" + (isCenter ? " mini-node--center" : "")}
                onMouseEnter={() => setHoverId(n.id)}
                onMouseLeave={() => setHoverId((cur) => (cur === n.id ? null : cur))}
                onClick={() => {
                  if (isCenter) return;
                  // Reuse the page-kinded selection the Editor already
                  // listens for. CE data.json paths are wiki-relative;
                  // the Editor accepts both forms via _resolve_wiki_md.
                  const path = n.path?.startsWith("wiki/") ? n.path : `wiki/${n.path ?? ""}`;
                  setSelection({ kind: "page", id: n.id, path });
                }}
              >
                <circle cx={n.x} cy={n.y} r={r} fill={colourFor(n.type)} />
              </g>
            );
          })}
        </g>
        <g className="mini-labels">
          {[center, ...neighbours]
            .filter((n) => n.id === centerId || n.id === hoverId)
            .map((n) => {
            const isCenter = n.id === centerId;
            const r = nodeRadius(n.degree ?? 0, isCenter);
            return (
              <text
                key={`l-${n.id}`}
                className={"mini-label" + (isCenter ? " mini-label--center" : "")}
                x={n.x}
                y={n.y - r - 4}
                textAnchor="middle"
              >
                {truncate(n.title || n.id, 36)}
              </text>
            );
          })}
        </g>
      </svg>
      {/* centerPath stays in the DOM as a data hint for tests / future
          deeplinks; actual nav is handled via setSelection above. */}
      <div className="sy-editor-mini-foot" data-center-path={centerPath}>
        click a node to open
      </div>
    </section>
  );
}

type LaidOutNode = {
  id: string;
  title?: string;
  type: string;
  path?: string;
  degree?: number;
  x: number;
  y: number;
};
type LaidOutEdge = { x1: number; y1: number; x2: number; y2: number; type: string };

function buildLayout(
  data: GraphData,
  centerId: string,
): {
  center: LaidOutNode;
  neighbours: LaidOutNode[];
  edges: LaidOutEdge[];
  w: number;
  h: number;
  palette: Record<string, string>;
} | null {
  const allNodes = data.nodes ?? [];
  const allEdges = data.edges ?? [];
  const palette = (data.palette ?? {}) as Record<string, string>;
  const byId = new Map(allNodes.map((n) => [n.id, n] as const));
  const center = byId.get(centerId);
  if (!center) return null;

  // 1-hop neighbour ids, deduplicated.
  const hop1 = new Set<string>();
  for (const e of allEdges) {
    const s = typeof e.source === "object" ? (e.source as { id: string }).id : (e.source as string);
    const t = typeof e.target === "object" ? (e.target as { id: string }).id : (e.target as string);
    if (s === centerId && t !== centerId) hop1.add(t);
    else if (t === centerId && s !== centerId) hop1.add(s);
  }
  const neighbourNodes = Array.from(hop1)
    .map((id) => byId.get(id))
    .filter((n): n is NonNullable<typeof n> => !!n);

  // Force-directed layout — same parameters as the Graph modal's
  // subgraph. Centre is pinned via fx/fy; neighbours relax around it.
  const N = neighbourNodes.length;
  const w = 560;
  const h = Math.max(220, Math.min(440, 240 + N * 4));
  const cx = w / 2;
  const cy = h / 2;

  type SN = d3.SimulationNodeDatum & {
    id: string;
    title?: string;
    type: string;
    path?: string;
    degree?: number;
    hop: number;
  };
  type SE = d3.SimulationLinkDatum<SN> & { type: string };

  const simNodes: SN[] = [
    { ...center, hop: 0 } as SN,
    ...neighbourNodes.map((n) => ({ ...n, hop: 1 }) as SN),
  ];
  const idToSim = new Map(simNodes.map((n) => [n.id, n] as const));
  const centreSim = idToSim.get(center.id)!;
  centreSim.fx = cx;
  centreSim.fy = cy;

  const simLinks: SE[] = [];
  for (const e of allEdges) {
    const s = typeof e.source === "object" ? (e.source as { id: string }).id : (e.source as string);
    const t = typeof e.target === "object" ? (e.target as { id: string }).id : (e.target as string);
    if (s === t) continue;
    const sn = idToSim.get(s);
    const tn = idToSim.get(t);
    if (!sn || !tn) continue;
    simLinks.push({ source: sn, target: tn, type: e.type ?? "" });
  }

  const sim = d3.forceSimulation<SN>(simNodes)
    .force("link", d3.forceLink<SN, SE>(simLinks).id((d) => d.id)
      .distance(60).strength(0.5))
    .force("charge", d3.forceManyBody<SN>()
      .strength((d) => (d.hop === 0 ? -480 : -220))
      .distanceMax(320))
    .force("collide", d3.forceCollide<SN>((d) =>
      nodeRadius(d.degree ?? 0, d.hop === 0) + 8,
    ))
    .alpha(1)
    .alphaDecay(0.055)
    .stop();
  for (let i = 0; i < 280; i++) sim.tick();

  // Clamp inside the canvas margin so nothing escapes.
  const margin = 28;
  for (const n of simNodes) {
    n.x = Math.max(margin, Math.min(w - margin, n.x ?? cx));
    n.y = Math.max(margin, Math.min(h - margin, n.y ?? cy));
  }

  const placed: Record<string, LaidOutNode> = {};
  const centreLaid: LaidOutNode = { ...center, x: centreSim.x!, y: centreSim.y! };
  placed[center.id] = centreLaid;
  const neighbours: LaidOutNode[] = neighbourNodes.map((n) => {
    const sn = idToSim.get(n.id)!;
    const out = { ...n, x: sn.x!, y: sn.y! };
    placed[n.id] = out;
    return out;
  });

  const edges: LaidOutEdge[] = [];
  for (const e of allEdges) {
    const s = typeof e.source === "object" ? (e.source as { id: string }).id : (e.source as string);
    const t = typeof e.target === "object" ? (e.target as { id: string }).id : (e.target as string);
    if (s === t) continue;
    const ps = placed[s];
    const pt = placed[t];
    if (!ps || !pt) continue;
    edges.push({ x1: ps.x, y1: ps.y, x2: pt.x, y2: pt.y, type: e.type ?? "" });
  }

  return { center: centreLaid, neighbours, edges, w, h, palette };
}

function nodeRadius(degree: number, isCenter: boolean): number {
  const base = 4 + Math.sqrt(degree + 1) * 1.4;
  return isCenter ? base + 2 : base;
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return s.slice(0, n - 1).trimEnd() + "…";
}
