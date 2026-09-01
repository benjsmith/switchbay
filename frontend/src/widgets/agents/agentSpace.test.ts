import assert from "node:assert/strict";
import { test } from "node:test";
import { BLACKBOARD_ID, CHIEF_ID, spaceEdges } from "./spaceGraph.ts";

type Node = { id: string; kind: string };

function edgesOf(
  nodes: Node[],
  deps: Record<string, string[]> = {},
  opts: { board?: boolean } = {},
): string[] {
  const all: Node[] = [{ id: CHIEF_ID, kind: "chief" }, ...nodes];
  if (opts.board !== false) all.push({ id: BLACKBOARD_ID, kind: "blackboard" });
  const byId = new Set(all.map((n) => n.id));
  return spaceEdges(all, new Map(Object.entries(deps)), byId)
    .map((e) => `${e.from}->${e.to}`);
}

test("a lone synthesizer hangs off the chief, not the blackboard", () => {
  // The CE-curate shape: one worker, fed by the board. It used to be
  // drawn as a child OF the board, leaving the chief unconnected.
  const edges = edgesOf([{ id: "curate", kind: "synthesize" }]);
  assert.deepEqual(new Set(edges), new Set([
    "chief->blackboard",
    "chief->curate",
    "blackboard->curate",
  ]));
});

test("lineage follows declared dependencies", () => {
  const edges = edgesOf(
    [
      { id: "inv-0", kind: "investigate" },
      { id: "inv-1", kind: "investigate" },
      { id: "verify", kind: "verify" },
      { id: "synth", kind: "synthesize" },
    ],
    { verify: ["inv-0", "inv-1"], synth: ["verify"] },
  );
  // Dispatched by the chief (no deps of their own) …
  assert.ok(edges.includes("chief->inv-0"));
  assert.ok(edges.includes("chief->inv-1"));
  // … and by their dependencies where the plan declares them.
  assert.ok(edges.includes("inv-0->verify"));
  assert.ok(edges.includes("inv-1->verify"));
  assert.ok(edges.includes("verify->synth"));
  assert.ok(!edges.includes("chief->verify"));
  assert.ok(!edges.includes("chief->synth"));
});

test("board edges point the way each kind uses the board", () => {
  const edges = edgesOf([
    { id: "inv-0", kind: "investigate" },
    { id: "exec", kind: "execute" },
    { id: "red", kind: "reduce" },
    { id: "verify", kind: "verify" },
    { id: "synth", kind: "synthesize" },
  ]);
  // Writers post findings; readers get the board in their prompt.
  assert.ok(edges.includes("inv-0->blackboard"));
  assert.ok(edges.includes("exec->blackboard"));
  assert.ok(edges.includes("red->blackboard"));
  assert.ok(edges.includes("blackboard->verify"));
  assert.ok(edges.includes("blackboard->synth"));
  assert.ok(edges.includes("chief->blackboard"));
});

test("no board node → no board edges, and the chief still owns everyone", () => {
  const edges = edgesOf([{ id: "curate", kind: "synthesize" }], {}, { board: false });
  assert.deepEqual(edges, ["chief->curate"]);
});

test("edges are unique, never self-directed, and drop unknown deps", () => {
  const edges = edgesOf(
    [{ id: "a", kind: "investigate" }, { id: "b", kind: "verify" }],
    { a: ["a", "ghost", BLACKBOARD_ID], b: ["a", "a"] },
  );
  assert.equal(new Set(edges).size, edges.length);
  assert.ok(!edges.some((e) => e.split("->")[0] === e.split("->")[1]));
  assert.ok(!edges.includes("ghost->a"));
  // A dep on the board is not lineage — `a` falls back to the chief.
  assert.ok(edges.includes("chief->a"));
  assert.equal(edges.filter((e) => e === "a->b").length, 1);
});
