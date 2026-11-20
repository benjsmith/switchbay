import assert from "node:assert/strict";
import { test } from "node:test";

import { edgeStyleCss, planLegend, readMetaOntology } from "./metaOntologyChrome.ts";

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

test("typed edges keep source, target, and a distinct stroke", () => {
  const plan = planLegend(rows, {
    metaOntology: {
      edges: [
        {
          type: "supports",
          label: "supports",
          color: "#0072b2",
          source: ["evidence"],
          target: ["hypothesis"],
          description: "The result matches a prediction.",
        },
        {
          type: "contradicts",
          label: "contradicts",
          color: "#d55e00",
          source: ["evidence"],
          target: ["hypothesis"],
        },
      ],
    },
  });
  assert.ok(plan);
  assert.deepEqual(plan.edges[0].source, ["evidence"]);
  assert.deepEqual(plan.edges[0].target, ["hypothesis"]);
  assert.equal(plan.edges[0].color, "#0072b2");
  assert.equal(plan.edges[1].color, "#d55e00");
  const css = edgeStyleCss(plan.edges);
  assert.match(css, /\.edge\[data-kind="supports"\][^{]*\{ stroke: #0072b2;/);
  assert.match(css, /\.edge\[data-kind="contradicts"\][^{]*\{ stroke: #d55e00;/);
  assert.notEqual(plan.edges[0].color, plan.edges[1].color);
});
