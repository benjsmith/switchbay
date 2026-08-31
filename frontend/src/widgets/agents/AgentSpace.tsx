import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";

/**
 * Live 2-d agent-space for a multi-agent DAG.
 *
 * Vertical axis is DAG depth (chief at the top). Horizontal axis is a
 * cheap bag-of-trigram projection of what that node is processing —
 * similar work sits nearby, no embedding model, no React on the
 * animation path. Pulses are structured handoffs, not chat.
 */

export type OrchHandoff = {
  ts: number;
  from: string;
  to: string;
  kind: string;
  text: string;
};

/** One line of the shared evidence board, as the daemon publishes it. */
export type BlackboardRow = {
  id: string;
  node_id: string;
  /** finding | handback | error — what put this row on the board. */
  kind: string;
  verdict?: string;
  claim: string;
  sources?: number;
  ts?: number;
};

export type PlanNodeView = {
  node_id: string;
  kind: string;
  role?: string;
  dependencies?: string[];
  objective?: string;
  method_hint?: string;
  retrieval_query?: string;
  provider?: string | null;
  model?: string | null;
  status?: string;
};

export type SpaceRun = {
  run_id: string;
  provider: string;
  model?: string;
  input_excerpt?: string;
  activity?: string;
  status?: string;
  started_at?: number;
  tool_count?: number;
  current_tool?: string;
  parent_run_id?: string | null;
  node_id?: string | null;
  node_kind?: string | null;
  node_role?: string | null;
  orchestration_strategy?: string | null;
  decision_reason?: string | null;
  arm_reason?: string | null;
  org_summary?: string | null;
  expansions?: number | null;
  continuations?: number | null;
  expansion_reason?: string | null;
  verification_conflicts?: number | null;
  verifier_confidence?: number | null;
  unsupported_rejected?: number | null;
  preference?: number | null;
  tokens?: number | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
  io_mode?: "read" | "write" | "idle" | string | null;
  last_chunk_at?: number;
  workers_total?: number | null;
  workers_running?: number | null;
  plan_nodes?: PlanNodeView[] | null;
  orchestration_messages?: OrchHandoff[] | null;
  blackboard_n?: number | null;
  candidate_findings_n?: number | null;
  unique_sources?: number | null;
  blackboard_rows?: BlackboardRow[] | null;
  objective?: string | null;
  orchestration_stage?: string | null;
  step?: string | null;
  fanout_n?: number | null;
  workspace?: string;
  workspace_name?: string;
};

export const CHIEF_ID = "chief";
export const BLACKBOARD_ID = "blackboard";

type SpaceNode = {
  id: string;
  runId: string | null;
  label: string;
  kind: string;
  status: string;
  activity: string;
  model: string;
  provider: string;
  toolCount: number;
  currentTool: string;
  tokensOut: number;
  tokenRate: number;
  ioMode: "read" | "write" | "idle";
  lastChunkAt: number;
  depth: number;
  tx: number;
  ty: number;
  x: number;
  y: number;
};

type Pulse = {
  from: string;
  to: string;
  t0: number;
  dur: number;
  kind: string;
  read?: boolean;
};

type Props = {
  chief: SpaceRun;
  workers: SpaceRun[];
  selectedId: string;
  onSelect: (id: string, runId: string | null) => void;
  /** Standing desk roster — last effective org, no live activity. */
  idle?: boolean;
  /** Completed root retained for paging; unlike standing, it is historical. */
  recent?: boolean;
};

const KIND_COLOR: Record<string, string> = {
  chief: "",
  investigate: "#7aa2f7",
  verify: "#e0af68",
  synthesize: "#9ece6a",
  reduce: "#9aa5ce",
  execute: "#bb9af7",
  blackboard: "#c0caf5",
};

const READ_HALO = "#7aa2f7";
const WRITE_HALO = "#e0af68";

function fnv1a(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Deterministic 2-d projection of a short text (trigram hash). */
export function projectText(text: string): { x: number; y: number } {
  const t = (text || "").toLowerCase();
  if (t.length < 3) {
    const h = fnv1a(t || "x");
    return { x: ((h % 2000) / 1000) - 1, y: (((h >>> 10) % 2000) / 1000) - 1 };
  }
  const dim = 24;
  const v = new Float32Array(dim);
  for (let i = 0; i < t.length - 2; i++) {
    const g = t.slice(i, i + 3);
    const h = fnv1a(g);
    v[h % dim] += 1;
    v[(h >>> 8) % dim] += 0.45;
  }
  let n2 = 0;
  for (let i = 0; i < dim; i++) n2 += v[i] * v[i];
  const inv = n2 > 0 ? 1 / Math.sqrt(n2) : 1;
  let x = 0;
  let y = 0;
  for (let i = 0; i < dim; i++) {
    const a = v[i] * inv;
    // Two fixed "random" projection directions (coprime steps).
    x += a * Math.cos((i * 2.399) + 0.3);
    y += a * Math.sin((i * 1.618) + 1.1);
  }
  const m = Math.hypot(x, y) || 1;
  return { x: x / m, y: y / m };
}

function kindDepth(kind: string): number {
  if (kind === "chief") return 0;
  if (kind === "investigate" || kind === "execute") return 1;
  if (kind === "blackboard") return 2;
  if (kind === "reduce") return 2;
  if (kind === "verify") return 3;
  return 4;
}

function readCss(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function handoffKey(m: OrchHandoff): string {
  return `${m.ts}|${m.from}|${m.to}|${m.kind}`;
}

function kindLabel(kind: string): string {
  if (kind === "chief") return "chief of staff";
  if (kind === "investigate") return "investigator";
  if (kind === "synthesize") return "synthesizer";
  if (kind === "verify") return "verifier";
  if (kind === "reduce") return "reducer";
  if (kind === "execute") return "executor";
  if (kind === "blackboard") return "blackboard";
  return kind;
}

function liveOrgLead(
  chief: SpaceRun,
  nodes: { kind: string; status: string }[],
  idle: boolean,
): string {
  const roles = nodes.filter(
    (n) => n.kind !== "chief" && n.kind !== "blackboard" && n.status !== "error",
  );
  if (roles.length === 0) {
    return idle
      ? (chief.org_summary || chief.decision_reason || "Last effective roster — waiting for the next run.")
      : (chief.org_summary || chief.decision_reason || chief.step
        || "Coordinating the DAG — click a worker for its transcript.");
  }
  const labels: Record<string, [string, string]> = {
    investigate: ["investigator", "investigators"],
    execute: ["executor", "executors"],
    reduce: ["reducer", "reducers"],
    verify: ["verifier", "verifiers"],
    synthesize: ["synthesizer", "synthesizers"],
  };
  const parts: string[] = [];
  for (const kind of ["investigate", "execute", "reduce", "verify", "synthesize"]) {
    const n = roles.filter((r) => r.kind === kind).length;
    if (!n) continue;
    const [one, many] = labels[kind] ?? [kind, kind];
    parts.push(`${n} ${n === 1 ? one : many}`);
  }
  let lead = parts.join(" → ") || "coordinating";
  const extra: string[] = [];
  if ((chief.expansions ?? 0) > 0) extra.push(`expanded ×${chief.expansions}`);
  if ((chief.continuations ?? 0) > 0) extra.push(`continued ×${chief.continuations}`);
  if (extra.length) lead += ` · ${extra.join(" · ")}`;
  return lead;
}

function ioOf(w?: SpaceRun): "read" | "write" | "idle" {
  const m = w?.io_mode;
  if (m === "read" || m === "write" || m === "idle") return m;
  if (w?.current_tool) return "read";
  if (w?.activity) return "write";
  return "idle";
}

function baseNode(partial: Omit<SpaceNode, "x" | "y" | "tx" | "ty" | "tokensOut" | "tokenRate" | "ioMode" | "lastChunkAt" | "toolCount" | "currentTool"> & Partial<SpaceNode>): Omit<SpaceNode, "x" | "y" | "tx" | "ty"> {
  return {
    toolCount: 0,
    currentTool: "",
    tokensOut: 0,
    tokenRate: 0,
    ioMode: "idle",
    lastChunkAt: 0,
    ...partial,
  };
}

export default function AgentSpace({
  chief, workers, selectedId, onSelect, idle = false, recent = false,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const nodesRef = useRef<Map<string, SpaceNode>>(new Map());
  const pulsesRef = useRef<Pulse[]>([]);
  const seenHandoffs = useRef<Set<string>>(new Set());
  const colorsRef = useRef({
    accent: "#6be8b3",
    text: "#e6e8eb",
    muted: "#9aa0a8",
    faint: "#5a6068",
    line: "#232830",
    bg: "#0f1115",
  });
  const [nowTick, setNowTick] = useState(0);
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;
  const edgesRef = useRef<{ from: string; to: string }[]>([]);

  const workerByNode = useMemo(() => {
    const m = new Map<string, SpaceRun>();
    const ranked = [...workers].sort((a, b) => {
      const live = (r: SpaceRun) =>
        r.status === "done" || r.status === "error" ? 0 : 1;
      return live(a) - live(b);
    });
    for (const w of ranked) {
      if (w.node_id) m.set(w.node_id, w);
    }
    return m;
  }, [workers]);

  const planNodes = chief.plan_nodes ?? [];
  const messages = chief.orchestration_messages ?? [];

  const graph = useMemo(() => {
    const nodes: Omit<SpaceNode, "x" | "y" | "tx" | "ty">[] = [];
    const edges: { from: string; to: string }[] = [];
    const obj = chief.objective || chief.input_excerpt || "";
    nodes.push(baseNode({
      id: CHIEF_ID,
      runId: chief.run_id,
      label: "chief of staff",
      kind: "chief",
      status: chief.status || "running",
      activity: [chief.step, chief.decision_reason, obj].filter(Boolean).join(" · "),
      model: chief.model || chief.provider || "",
      provider: chief.provider || "",
      tokensOut: chief.tokens_out ?? chief.tokens ?? 0,
      lastChunkAt: chief.last_chunk_at ?? 0,
      depth: 0,
    }));
    const byId = new Set<string>([CHIEF_ID]);
    const liveKinds = new Set<string>();
    const visiblePlan = planNodes.filter((n) => {
      const w = workerByNode.get(n.node_id);
      const st = w?.status || n.status || "pending";
      return st !== "error";
    });
    if (visiblePlan.length > 0) {
      for (const n of visiblePlan) {
        const w = workerByNode.get(n.node_id);
        const kind = n.kind || "investigate";
        liveKinds.add(kind);
        const activity = (w?.activity || "").trim()
          || [n.method_hint, n.retrieval_query, n.objective].filter(Boolean).join(" · ");
        nodes.push(baseNode({
          id: n.node_id,
          runId: w?.run_id ?? null,
          label: n.node_id,
          kind,
          status: w?.status || n.status || "pending",
          activity,
          model: w?.model || n.model || "",
          provider: w?.provider || n.provider || "",
          toolCount: w?.tool_count ?? 0,
          currentTool: w?.current_tool || "",
          tokensOut: w?.tokens_out ?? w?.tokens ?? 0,
          ioMode: ioOf(w),
          lastChunkAt: w?.last_chunk_at ?? 0,
          depth: kindDepth(kind),
        }));
        byId.add(n.node_id);
      }
    } else {
      for (const w of workers) {
        if (w.status === "error") continue;
        const id = w.node_id || w.run_id;
        const kind = w.node_kind || "investigate";
        liveKinds.add(kind);
        nodes.push(baseNode({
          id,
          runId: w.run_id,
          label: w.node_id || w.run_id.slice(-6),
          kind,
          status: w.status || "running",
          activity: w.activity || w.input_excerpt || "",
          model: w.model || "",
          provider: w.provider || "",
          toolCount: w.tool_count ?? 0,
          currentTool: w.current_tool || "",
          tokensOut: w.tokens_out ?? w.tokens ?? 0,
          ioMode: ioOf(w),
          lastChunkAt: w.last_chunk_at ?? 0,
          depth: kindDepth(kind),
        }));
        byId.add(id);
      }
    }
    const hasWorkers = [...liveKinds].some((k) => k !== "chief");
    if (hasWorkers) {
      nodes.push(baseNode({
        id: BLACKBOARD_ID,
        runId: null,
        label: "blackboard",
        kind: "blackboard",
        status: idle ? "ready" : (chief.status || "running"),
        // "0 candidates · 0 rows" reads as a broken counter. Say empty
        // when it is empty; count only once there is something to count.
        activity: (chief.blackboard_n ?? 0) > 0
          ? `${chief.blackboard_n} rows · ${chief.candidate_findings_n ?? 0} candidates`
          : "empty — click to open",
        model: "",
        provider: "",
        lastChunkAt: chief.last_chunk_at ?? 0,
        depth: kindDepth("blackboard"),
      }));
      byId.add(BLACKBOARD_ID);
    }
    // The chief owns the board: it posts the objective and reads what
    // comes back. Without this edge a DAG whose only worker is fed BY
    // the blackboard (a lone synthesizer) drew the chief unconnected,
    // floating above a graph it is the root of.
    if (byId.has(BLACKBOARD_ID)) edges.push({ from: CHIEF_ID, to: BLACKBOARD_ID });
    for (const n of nodes) {
      if (n.kind === "chief" || n.kind === "blackboard") continue;
      if (n.kind === "investigate" || n.kind === "execute") {
        edges.push({ from: CHIEF_ID, to: n.id });
        if (byId.has(BLACKBOARD_ID)) edges.push({ from: n.id, to: BLACKBOARD_ID });
      } else if (n.kind === "reduce") {
        edges.push({ from: CHIEF_ID, to: n.id });
        if (byId.has(BLACKBOARD_ID)) edges.push({ from: n.id, to: BLACKBOARD_ID });
      } else if (n.kind === "verify") {
        if (byId.has(BLACKBOARD_ID)) edges.push({ from: BLACKBOARD_ID, to: n.id });
        else edges.push({ from: CHIEF_ID, to: n.id });
      } else if (n.kind === "synthesize") {
        const hasVerify = nodes.some((x) => x.kind === "verify");
        if (hasVerify) {
          const v = nodes.find((x) => x.kind === "verify");
          if (v) edges.push({ from: v.id, to: n.id });
        } else if (byId.has(BLACKBOARD_ID)) {
          edges.push({ from: BLACKBOARD_ID, to: n.id });
        } else {
          edges.push({ from: CHIEF_ID, to: n.id });
        }
      }
    }
    // Anything still unreachable from the chief hangs off it directly —
    // a node with no lineage on screen reads as a rendering bug.
    const hasIncoming = new Set(edges.map((e) => e.to));
    for (const n of nodes) {
      if (n.kind === "chief" || hasIncoming.has(n.id)) continue;
      edges.push({ from: CHIEF_ID, to: n.id });
    }
    const pruned = edges.filter((e) => byId.has(e.from) && byId.has(e.to));
    return { nodes, edges: pruned };
  }, [chief, workers, planNodes, workerByNode, idle]);
  edgesRef.current = graph.edges;

  // Seed / retarget node positions when the graph changes.
  useEffect(() => {
    const map = nodesRef.current;
    const live = new Set(graph.nodes.map((n) => n.id));
    for (const id of [...map.keys()]) {
      if (!live.has(id)) map.delete(id);
    }
    const maxD = Math.max(1, ...graph.nodes.map((n) => n.depth));
    const byDepth = new Map<number, typeof graph.nodes>();
    for (const n of graph.nodes) {
      const arr = byDepth.get(n.depth) ?? [];
      arr.push(n);
      byDepth.set(n.depth, arr);
    }
    for (const n of graph.nodes) {
      const proj = projectText(n.activity || n.label);
      const siblings = byDepth.get(n.depth) ?? [n];
      const idx = siblings.findIndex((s) => s.id === n.id);
      const spread = siblings.length <= 1 ? 0 : (idx / (siblings.length - 1) - 0.5);
      // Mix embedding (what it's processing) with a stable DAG slot
      // so siblings don't sit on top of each other.
      const tx = (n.kind === "chief" || n.kind === "blackboard")
        ? 0
        : (0.22 * proj.x + 0.78 * spread * 2.35);
      const ty = n.kind === "chief" ? -0.82 : (-0.72 + (1.55 * n.depth) / maxD);
      const prev = map.get(n.id);
      map.set(n.id, {
        ...n,
        tx,
        ty,
        x: prev?.x ?? tx,
        y: prev?.y ?? ty,
      });
    }
  }, [graph]);

  const prevToolsRef = useRef<Map<string, number>>(new Map());
  const prevTokRef = useRef<Map<string, { tokens: number; t: number; rate: number }>>(new Map());
  const toolsSeededRef = useRef(false);
  useEffect(() => {
    const prev = prevToolsRef.current;
    const tok = prevTokRef.current;
    const now = performance.now();
    for (const n of graph.nodes) {
      const next = n.toolCount ?? 0;
      const last = prev.get(n.id) ?? 0;
      if (toolsSeededRef.current && next > last && n.kind !== "chief" && n.kind !== "blackboard") {
        const dest = graph.nodes.some((x) => x.id === BLACKBOARD_ID) ? BLACKBOARD_ID : CHIEF_ID;
        pulsesRef.current.push({
          from: n.id, to: dest, t0: performance.now(), dur: 520, kind: "tool",
          read: true,
        });
      }
      prev.set(n.id, next);

      const tprev = tok.get(n.id);
      const tokens = n.tokensOut ?? 0;
      let rate = tprev?.rate ?? 0;
      if (tprev && now > tprev.t) {
        const dt = (now - tprev.t) / 1000;
        const d = Math.max(0, tokens - tprev.tokens);
        const inst = dt > 0.15 ? d / dt : 0;
        rate = rate * 0.55 + inst * 0.45;
        if (toolsSeededRef.current && d > 0 && n.kind !== "chief" && n.kind !== "blackboard") {
          const nPulses = Math.min(6, Math.max(1, Math.round(d / 12)));
          const reading = n.ioMode === "read";
          for (let i = 0; i < nPulses; i++) {
            const from = reading
              ? (n.kind === "verify" || n.kind === "synthesize" ? BLACKBOARD_ID : n.id)
              : n.id;
            const to = reading
              ? n.id
              : (graph.nodes.some((x) => x.id === BLACKBOARD_ID) ? BLACKBOARD_ID : CHIEF_ID);
            if (from === to) continue;
            pulsesRef.current.push({
              from, to,
              t0: performance.now() + i * 70,
              dur: 580 + i * 40,
              kind: "token",
              read: reading,
            });
          }
        }
      }
      tok.set(n.id, { tokens, t: now, rate });
      const mapped = nodesRef.current.get(n.id);
      if (mapped) mapped.tokenRate = rate;
    }
    toolsSeededRef.current = true;
  }, [graph]);

  // New handoffs → pulses. Also accept live WS events.
  useEffect(() => {
    const seen = seenHandoffs.current;
    const first = seen.size === 0;
    const cutoff = Date.now() / 1000 - 8;
    for (const m of messages) {
      const k = handoffKey(m);
      if (seen.has(k)) continue;
      seen.add(k);
      if (first && m.ts < cutoff) continue;
      pulsesRef.current.push({
        from: m.from,
        to: m.to,
        t0: performance.now(),
        dur: 620,
        kind: m.kind,
      });
    }
    if (seen.size > 200) {
      const keep = new Set(messages.slice(-80).map(handoffKey));
      seenHandoffs.current = keep;
    }
  }, [messages]);

  useEffect(() => {
    const onHandoff = (ev: Event) => {
      const d = (ev as CustomEvent<OrchHandoff & { orchestration_id?: string }>).detail;
      if (!d || d.orchestration_id && d.orchestration_id !== chief.run_id) return;
      const k = handoffKey(d);
      if (seenHandoffs.current.has(k)) return;
      seenHandoffs.current.add(k);
      pulsesRef.current.push({
        from: d.from, to: d.to, t0: performance.now(), dur: 620, kind: d.kind,
      });
    };
    window.addEventListener("sy:orch-handoff", onHandoff);
    return () => window.removeEventListener("sy:orch-handoff", onHandoff);
  }, [chief.run_id]);

  // rAF loop — no React state.
  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    const fit = () => {
      const w = Math.max(120, wrap.clientWidth);
      const h = Math.max(140, wrap.clientHeight);
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(wrap);

    colorsRef.current = {
      accent: readCss("--accent", "#6be8b3"),
      text: readCss("--text", "#e6e8eb"),
      muted: readCss("--text-muted", "#9aa0a8"),
      faint: readCss("--text-faint", "#5a6068"),
      line: readCss("--line", "#232830"),
      bg: readCss("--bg-soft", "#161a21"),
    };

    let raf = 0;
    let last = performance.now();
    const toXY = (nx: number, ny: number, w: number, h: number) => ({
      x: w * (0.5 + nx * 0.42),
      y: h * (0.5 + ny * 0.42),
    });

    const loop = (now: number) => {
      if (document.hidden) {
        raf = 0;
        return;
      }
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const w = wrap.clientWidth;
      const h = wrap.clientHeight;
      const col = colorsRef.current;
      ctx.clearRect(0, 0, w, h);

      const k = 1 - Math.exp(-dt * 5.5);
      const map = nodesRef.current;
      for (const n of map.values()) {
        n.x += (n.tx - n.x) * k;
        n.y += (n.ty - n.y) * k;
      }

      // Edges.
      ctx.lineWidth = 1;
      ctx.strokeStyle = col.line;
      for (const e of edgesRef.current) {
        const a = map.get(e.from);
        const b = map.get(e.to);
        if (!a || !b) continue;
        const pa = toXY(a.x, a.y, w, h);
        const pb = toXY(b.x, b.y, w, h);
        ctx.globalAlpha = 0.55;
        ctx.beginPath();
        ctx.moveTo(pa.x, pa.y);
        ctx.lineTo(pb.x, pb.y);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;

      // Pulses along edges.
      const pulses = pulsesRef.current;
      for (let i = pulses.length - 1; i >= 0; i--) {
        const p = pulses[i]!;
        const t = (now - p.t0) / p.dur;
        if (t >= 1) {
          pulses.splice(i, 1);
          continue;
        }
        const a = map.get(p.from);
        const b = map.get(p.to);
        if (!a || !b) continue;
        const pa = toXY(a.x, a.y, w, h);
        const pb = toXY(b.x, b.y, w, h);
        const u = t * t * (3 - 2 * t);
        const mx = (pa.x + pb.x) / 2;
        const my = (pa.y + pb.y) / 2 - 12;
        const x = (1 - u) * (1 - u) * pa.x + 2 * (1 - u) * u * mx + u * u * pb.x;
        const y = (1 - u) * (1 - u) * pa.y + 2 * (1 - u) * u * my + u * u * pb.y;
        ctx.beginPath();
        ctx.fillStyle = p.read ? READ_HALO : (p.kind === "token" ? WRITE_HALO : col.accent);
        ctx.globalAlpha = 0.85 * (1 - t * t);
        ctx.arc(x, y, p.kind === "token" ? 2.5 : 3.2, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
      }

      // Nodes.
      ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      for (const n of map.values()) {
        const p = toXY(n.x, n.y, w, h);
        const live = n.status === "running" || n.status === "planning"
          || n.status === "verifying" || n.status === "expanding"
          || n.status === "synthesizing" || n.status === "merging"
          || n.status === "waiting_limits";
        const fresh = live && n.lastChunkAt > 0 && (Date.now() / 1000 - n.lastChunkAt) < 3;
        const breath = live ? 1 + 0.07 * Math.sin(now / 280 + n.depth) : 1;
        const isChief = n.kind === "chief";
        const isBb = n.kind === "blackboard";
        const r = (isChief ? 11 : isBb ? 8 : 6.5) * breath;
        const fill = isChief ? col.accent : (KIND_COLOR[n.kind] || col.muted);
        const sel = selectedRef.current;
        const selected = sel === n.id || sel === n.runId;
        if (n.status === "pending" || n.status === "ready") ctx.globalAlpha = 0.4;
        else if (n.status === "done" || n.status === "error" || n.status === "idle") ctx.globalAlpha = 0.7;
        else ctx.globalAlpha = 1;
        ctx.beginPath();
        ctx.fillStyle = fill;
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.fill();
        if (isChief || isBb) {
          ctx.lineWidth = isBb ? 1.5 : 2;
          ctx.strokeStyle = isBb ? col.muted : col.text;
          ctx.stroke();
        }
        if (live && !isChief && fresh) {
          const reading = n.ioMode === "read";
          const halo = reading ? READ_HALO : WRITE_HALO;
          const amp = 0.22 + Math.min(0.45, (n.tokenRate || 0) / 80);
          const pulse = 1 + amp * (0.5 + 0.5 * Math.sin(now / (reading ? 160 : 120)));
          ctx.lineWidth = 2.4;
          ctx.strokeStyle = halo;
          ctx.globalAlpha = 0.35 + amp;
          ctx.beginPath();
          ctx.arc(p.x, p.y, (r + 5) * pulse, 0, Math.PI * 2);
          ctx.stroke();
          ctx.lineWidth = 1.5;
          ctx.globalAlpha = 0.9;
          ctx.beginPath();
          ctx.arc(p.x, p.y, r + 4, now / 180, now / 180 + 1.35);
          ctx.stroke();
        }
        if (live && !isChief && !isBb) {
          const dots = Math.min(8, n.toolCount || 0);
          for (let i = 0; i < dots; i++) {
            const a = now / 420 + (i / Math.max(1, dots)) * Math.PI * 2;
            ctx.beginPath();
            ctx.fillStyle = n.ioMode === "read" ? READ_HALO : WRITE_HALO;
            ctx.globalAlpha = 0.7;
            ctx.arc(
              p.x + Math.cos(a) * (r + 9),
              p.y + Math.sin(a) * (r + 9),
              1.6, 0, Math.PI * 2,
            );
            ctx.fill();
          }
        }
        if (selected) {
          ctx.lineWidth = 1.5;
          ctx.strokeStyle = col.text;
          ctx.globalAlpha = 1;
          ctx.beginPath();
          ctx.arc(p.x, p.y, r + 4, 0, Math.PI * 2);
          ctx.stroke();
        }
        ctx.globalAlpha = 1;
        ctx.fillStyle = col.muted;
        ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
        ctx.fillText(n.label, p.x, p.y + r + 4);
        const bits: string[] = [];
        if (n.toolCount > 0) bits.push(`${n.toolCount} tool${n.toolCount === 1 ? "" : "s"}`);
        if (n.tokenRate >= 1 && live) bits.push(`${Math.round(n.tokenRate)} tok/s`);
        if (n.provider && n.kind !== "chief" && n.kind !== "blackboard") {
          bits.push(n.provider.replace(/_/g, " "));
        }
        if (bits.length) {
          ctx.font = "9.5px ui-sans-serif, system-ui, sans-serif";
          ctx.fillStyle = col.faint;
          ctx.fillText(bits.join(" · ").slice(0, 42), p.x, p.y + r + 16);
        }
        const detail = (n.currentTool ? `⚙ ${n.currentTool}` : n.activity || "").trim();
        if (detail && n.kind !== "chief" && live) {
          ctx.font = "9px ui-sans-serif, system-ui, sans-serif";
          ctx.fillStyle = col.muted;
          const clipped = detail.length > 32 ? `${detail.slice(0, 31)}…` : detail;
          ctx.fillText(clipped, p.x, p.y + r + (bits.length ? 28 : 16));
        }
      }

      raf = requestAnimationFrame(loop);
    };
    const onVis = () => {
      if (document.hidden) {
        if (raf) cancelAnimationFrame(raf);
        raf = 0;
        return;
      }
      if (!raf) {
        last = performance.now();
        raf = requestAnimationFrame(loop);
      }
    };
    document.addEventListener("visibilitychange", onVis);
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("visibilitychange", onVis);
      ro.disconnect();
    };
  }, []);

  const onCanvasClick = (ev: MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const rect = canvas.getBoundingClientRect();
    const cx = ev.clientX - rect.left;
    const cy = ev.clientY - rect.top;
    const w = wrap.clientWidth;
    const h = wrap.clientHeight;
    let best: SpaceNode | null = null;
    let bestD = 26;
    for (const n of nodesRef.current.values()) {
      const x = w * (0.5 + n.x * 0.42);
      const y = h * (0.5 + n.y * 0.42);
      const d = Math.hypot(cx - x, cy - y);
      if (d < bestD) {
        bestD = d;
        best = n;
      }
    }
    if (best) onSelect(best.id, best.runId);
  };

  const selectedNode = graph.nodes.find((n) => n.id === selectedId)
    ?? (selectedId === chief.run_id ? graph.nodes.find((n) => n.id === CHIEF_ID) : undefined);
  const selectedWorker = selectedNode?.runId
    ? workers.find((w) => w.run_id === selectedNode.runId)
    : undefined;
  const isChief = selectedId === CHIEF_ID || selectedId === chief.run_id || !selectedNode || selectedNode.kind === "chief";
  const isBb = selectedNode?.kind === "blackboard";
  const orgLead = liveOrgLead(chief, graph.nodes, idle);

  const dagNodes = graph.nodes.filter((n) => n.kind !== "chief");
  // The blackboard is a visible coordination node, not an executing worker.
  // Keep it in the graph/roster while excluding it from worker telemetry.
  const workerDagNodes = dagNodes.filter((n) => n.kind !== "blackboard");
  const done = workerDagNodes.filter((n) => n.status === "done").length;
  const runningN = workerDagNodes.filter((n) => {
    const s = n.status || "";
    return s === "running" || s === "planning" || s === "verifying"
      || s === "expanding" || s === "synthesizing" || s === "merging"
      || s === "waiting_limits";
  }).length;
  const failedN = workerDagNodes.filter((n) => n.status === "error").length;
  const total = workerDagNodes.length || workers.length;
  const liveN = workers.filter((w) => {
    const s = w.status || "";
    return !s || s === "running" || s === "planning" || s === "verifying"
      || s === "expanding" || s === "synthesizing" || s === "merging";
  }).length;
  const toolsN = workers.reduce((s, w) => s + (w.tool_count || 0), 0);
  const tokRate = graph.nodes.reduce((s, n) => s + (nodesRef.current.get(n.id)?.tokenRate || 0), 0);
  const elapsed = chief.started_at
    ? Math.max(0, Date.now() / 1000 - chief.started_at)
    : 0;
  const elapsedLabel = elapsed < 60
    ? `${Math.floor(elapsed)}s`
    : `${Math.floor(elapsed / 60)}m${Math.floor(elapsed % 60).toString().padStart(2, "0")}`;

  // Keep elapsed ticking without touching the canvas.
  useEffect(() => {
    const id = window.setInterval(() => setNowTick((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, []);
  void nowTick;

  const board = [...messages].slice(-40).reverse();
  const bbRows = chief.blackboard_rows ?? [];

  return (
    <div className="sy-agent-space">
      <div className="sy-agent-space-head">
        <h3>Agent space</h3>
        <span className="sy-agents-subtitle">
          {idle
            ? "Standing desk — last effective org, at rest. A new run can replace this roster."
            : recent
            ? "Recently completed DAG — use the root picker to inspect concurrent and earlier runs."
            : "Amber halo = writing tokens · blue halo = reading · dots on edges are token flow"}
        </span>
      </div>
      <div ref={wrapRef} className="sy-agent-space-canvas-wrap">
        <canvas
          ref={canvasRef}
          className="sy-agent-space-canvas"
          onClick={onCanvasClick}
          role="img"
          aria-label="Live agent DAG. Click a node to inspect it."
        />
      </div>
      <div className="sy-agent-space-telem" aria-live="polite">
        <span>{(chief.orchestration_strategy || "auto").replace(/_/g, " ")}</span>
        {runningN > 0 && <span className="sy-agent-space-telem-hot">{runningN} running</span>}
        {!idle && <span>{done} done</span>}
        {failedN > 0 && <span>{failedN} failed</span>}
        {idle
          ? <span>{dagNodes.filter((n) => n.kind !== "blackboard").length} roles</span>
          : <span>{total || "–"} planned</span>}
        {toolsN > 0 && <span className="sy-agent-space-telem-hot">{toolsN} tools</span>}
        {!idle && <span>{liveN} live</span>}
        {tokRate >= 1 && (
          <span className="sy-agent-space-telem-hot">{Math.round(tokRate)} tok/s</span>
        )}
        {typeof chief.tokens === "number" && chief.tokens > 0 && (
          <span>{chief.tokens} tok</span>
        )}
        {idle && <span>at rest</span>}
        {!idle && <span>{elapsedLabel}</span>}
        {typeof chief.verification_conflicts === "number" && (
          <span>{chief.verification_conflicts} conflict{chief.verification_conflicts === 1 ? "" : "s"}</span>
        )}
        {typeof chief.expansions === "number" && chief.expansions > 0 && (
          <span>expanded ×{chief.expansions}</span>
        )}
      </div>
      <div className="sy-agent-space-below">
        <div className="sy-agent-space-overview">
          {isBb ? (
            <>
              <h4>Blackboard</h4>
              <p className="sy-agent-space-lead">
                Shared evidence the workers write into and later nodes read.
                Not a group chat — typed claims with provenance.
              </p>
              <p className="sy-agent-space-bb">
                {bbRows.length > 0
                  ? `${chief.blackboard_n ?? bbRows.length} rows`
                    + ` · ${chief.candidate_findings_n ?? 0} candidates`
                    + (typeof chief.unique_sources === "number"
                      ? ` · ${chief.unique_sources} sources` : "")
                  : "nothing posted yet"}
              </p>
              {bbRows.length > 0 ? (
                <ol className="sy-agent-space-bb-rows">
                  {[...bbRows].reverse().map((r, i) => (
                    <li key={r.id || `${r.node_id}-${i}`}>
                      <div className="sy-agent-space-bb-meta">
                        <span className="sy-agent-space-bb-node">{r.node_id || "—"}</span>
                        {r.verdict && (
                          <span className="sy-agent-space-bb-verdict">{r.verdict}</span>
                        )}
                        {r.kind && r.kind !== "finding" && (
                          <span className="sy-agent-space-bb-kind">{r.kind}</span>
                        )}
                        {typeof r.sources === "number" && r.sources > 0 && (
                          <span>{r.sources} source{r.sources === 1 ? "" : "s"}</span>
                        )}
                      </div>
                      <p className="sy-agent-space-bb-claim">{r.claim}</p>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="sy-agent-space-bb-empty">
                  Workers post here as they hand back. A run whose only
                  worker is a synthesizer never writes findings, so an
                  empty board here is the truth, not a stalled counter.
                </p>
              )}
              <button
                type="button"
                className="sy-agents-row-btn"
                onClick={() => onSelect(CHIEF_ID, chief.run_id)}
              >
                ← chief of staff
              </button>
            </>
          ) : isChief ? (
            <>
              <h4>{idle ? "Standing desk" : recent ? "Completed chief" : "Chief of staff"}</h4>
              <p className="sy-agent-space-lead">
                {orgLead}
              </p>
              {!!chief.arm_reason && chief.arm_reason !== orgLead && (
                <p className="sy-agents-subtitle">Opened as: {chief.arm_reason}</p>
              )}
              <ul className="sy-agent-space-roster">
                {graph.nodes.filter((n) => n.kind !== "chief").map((n) => (
                  <li key={n.id}>
                    <button
                      type="button"
                      className="sy-agent-space-roster-btn"
                      onClick={() => onSelect(n.id, n.runId)}
                    >
                      <span
                        className="sy-agent-space-swatch"
                        style={{ background: KIND_COLOR[n.kind] || "var(--text-muted)" }}
                      />
                      <code>{n.label}</code>
                      <span>{kindLabel(n.kind)}</span>
                      {n.toolCount > 0 && (
                        <span className="sy-agent-space-tools">{n.toolCount} tools</span>
                      )}
                      {n.tokenRate >= 1 && (
                        <span className="sy-agent-space-tools">{Math.round(n.tokenRate)}/s</span>
                      )}
                      <span className="sy-agent-space-st">{n.status}</span>
                    </button>
                  </li>
                ))}
              </ul>
              {(chief.blackboard_n != null || chief.candidate_findings_n != null) && (
                <p className="sy-agent-space-bb">
                  blackboard {chief.candidate_findings_n ?? 0} candidates
                  {typeof chief.blackboard_n === "number" ? ` · ${chief.blackboard_n} rows` : ""}
                  {typeof chief.unique_sources === "number" ? ` · ${chief.unique_sources} sources` : ""}
                </p>
              )}
            </>
          ) : (
            <>
              <h4>{kindLabel(selectedNode?.kind || "agent")}</h4>
              <p className="sy-agent-space-lead">
                <code>{selectedNode?.label}</code>
                {selectedNode?.model ? ` · ${selectedNode.model}` : ""}
                {selectedWorker?.provider ? ` · ${selectedWorker.provider}` : ""}
              </p>
              <p className="sy-agent-space-activity">
                {selectedWorker?.current_tool
                  ? `⚙ ${selectedWorker.current_tool}`
                  : (selectedWorker?.activity || selectedNode?.activity || "waiting")}
              </p>
              {(selectedWorker?.tool_count ?? 0) > 0 && (
                <p className="sy-agent-space-bb">
                  {selectedWorker!.tool_count} tool{selectedWorker!.tool_count === 1 ? "" : "s"}
                  {selectedWorker?.provider ? ` · ${selectedWorker.provider}` : ""}
                  {selectedWorker?.model ? `/${selectedWorker.model}` : ""}
                </p>
              )}
              {selectedNode?.runId ? (
                <p className="sy-agents-subtitle">Transcript is open on this run below.</p>
              ) : (
                <p className="sy-agents-subtitle">This node has not started a Run yet.</p>
              )}
              <button
                type="button"
                className="sy-agents-row-btn"
                onClick={() => onSelect(CHIEF_ID, chief.run_id)}
              >
                ← chief of staff
              </button>
            </>
          )}
        </div>
        <div className="sy-agent-space-board">
          <h4>Message board</h4>
          {board.length === 0 ? (
            <p className="sy-agents-empty">Handoffs will appear here as nodes spawn and write findings.</p>
          ) : (
            <ul className="sy-agent-space-board-list">
              {board.map((m) => (
                <li key={handoffKey(m)} className="sy-agent-space-msg">
                  <div className="sy-agent-space-msg-route">
                    <span>{m.from}</span>
                    <span className="sy-agents-arrow">→</span>
                    <span>{m.to}</span>
                    <span className="sy-agent-space-msg-kind">{m.kind}</span>
                  </div>
                  <div className="sy-agent-space-msg-body">{m.text || "—"}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

export function isOrchestrationRun(r: SpaceRun, workerCount: number): boolean {
  if (workerCount > 0) return true;
  if ((r.fanout_n ?? 0) > 1) return true;
  const s = r.orchestration_strategy;
  return !!s && s !== "single";
}
