/**
 * Agent-space DAG derivation — pure, no canvas, no React.
 *
 * Kept out of AgentSpace.tsx so the shape of the graph the user sees is
 * testable on its own: whether an edge exists is a claim about what the
 * orchestrator actually did, and it was wrong for long enough to be
 * worth pinning down.
 */

export const CHIEF_ID = "chief";
export const BLACKBOARD_ID = "blackboard";

export type SpaceEdge = { from: string; to: string };

/** Consumes the board rather than posting to it — mirrors the daemon,
 *  which parses findings off investigate/execute/reduce output and
 *  folds the board into verify/synthesize prompts. */
export function readsBoard(kind: string): boolean {
  return kind === "verify" || kind === "synthesize";
}

/**
 * Edges of the DAG as it actually ran.
 *
 * Lineage comes from the plan's own `dependencies`; a node with none
 * was dispatched by the chief. Kind used to stand in for that, which
 * made the blackboard the parent of every verify/synthesize node — a
 * lone synthesizer then hung off the board with no chief edge at all,
 * and the board looked like it was running the orchestration.
 *
 * The board is material, not a dispatcher: it gets one edge per worker,
 * pointing the way that worker uses it, plus the chief's ownership edge.
 */
export function spaceEdges(
  nodes: { id: string; kind: string }[],
  depsById: Map<string, string[]>,
  byId: Set<string>,
): SpaceEdge[] {
  const out: SpaceEdge[] = [];
  const hasBoard = byId.has(BLACKBOARD_ID);
  if (hasBoard) out.push({ from: CHIEF_ID, to: BLACKBOARD_ID });
  for (const n of nodes) {
    if (n.kind === "chief" || n.kind === "blackboard") continue;
    const deps = (depsById.get(n.id) ?? [])
      .filter((d) => d !== n.id && byId.has(d) && d !== BLACKBOARD_ID);
    if (deps.length > 0) {
      for (const d of deps) out.push({ from: d, to: n.id });
    } else {
      out.push({ from: CHIEF_ID, to: n.id });
    }
    if (hasBoard) {
      out.push(readsBoard(n.kind)
        ? { from: BLACKBOARD_ID, to: n.id }
        : { from: n.id, to: BLACKBOARD_ID });
    }
  }
  const seen = new Set<string>();
  return out.filter((e) => {
    if (!byId.has(e.from) || !byId.has(e.to) || e.from === e.to) return false;
    const key = `${e.from}->${e.to}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
