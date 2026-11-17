import assert from "node:assert/strict";
import { test } from "node:test";

import { planLegend, readMetaOntology } from "./metaOntologyChrome.ts";

const rows = [
  { type: "evidence", label: "Evidence" },
  { type: "fact", label: "Facts" },
];

test("no metaOntology leaves the legend plan empty", () => {
  assert.equal(readMetaOntology({ nodes: [] }), null);
  assert.equal(planLegend(rows, { palette: { evidence: "#111" } }), null);
  assert.equal(planLegend(rows, null), null);
});

test("configured labels relabel known types and add the rest", () => {
  const plan = planLegend(rows, {
    metaOntology: {
      nodes: [
        { type: "evidence", label: "Observation", color: "#73af48", description: "An observation." },
        { type: "hypothesis", label: "Hypothesis" },
      ],
      edges: [{ type: "cites", label: "cites", description: "Same paragraph." }],
    },
  });
  assert.ok(plan);
  assert.deepEqual(plan.relabel.map((row) => row.label), ["Observation"]);
  assert.equal(plan.relabel[0].color, "#73af48");
  assert.deepEqual(plan.add.map((row) => row.type), ["hypothesis"]);
  assert.deepEqual(plan.edges.map((row) => [row.type, row.label]), [["cites", "cites"]]);
});
