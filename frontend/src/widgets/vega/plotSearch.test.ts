import assert from "node:assert/strict";
import { test } from "node:test";
import { highlightParts, matchesQuery, searchBlob } from "./plotSearch.ts";

test("search matches title, caption, axis titles, and legend together", () => {
  const blob = searchBlob({
    title: "Revenue by region",
    caption: "Quarterly revenue split by region.",
    axis_titles: ["Quarter", "Revenue"],
    legend_titles: ["Region"],
    legend_entries: ["North", "South"],
  });
  assert.equal(matchesQuery(blob, ""), true);
  assert.equal(matchesQuery(blob, "north"), true);
  assert.equal(matchesQuery(blob, "quarter revenue"), true);
  assert.equal(matchesQuery(blob, "quarter glucose"), false);
  assert.equal(matchesQuery(blob, "region split"), true);
});

test("every token has to match", () => {
  const glucose = searchBlob({
    title: "Glucose curve",
    caption: "Plasma glucose after the meal.",
    axis_titles: ["Time", "Concentration"],
    legend_entries: ["control", "treated"],
  });
  assert.equal(matchesQuery(glucose, "treated concentration"), true);
  assert.equal(matchesQuery(glucose, "treated revenue"), false);
});

test("highlight marks the matched span without changing the other text", () => {
  const parts = highlightParts("Revenue by region", "rev");
  assert.deepEqual(parts.map((part) => part.text).join(""), "Revenue by region");
  assert.equal(parts[0]?.hit, true);
  assert.equal(parts[0]?.text.toLowerCase(), "rev");
  const merged = highlightParts("North region", "north region");
  assert.equal(merged.filter((part) => part.hit).map((part) => part.text).join(" "), "North region");
});

test("filtering hundreds of figures stays in memory and quick", () => {
  const blobs = Array.from({ length: 400 }, (_, i) => searchBlob({
    title: `Series ${i}`,
    caption: i % 17 === 0 ? "glucose response curve" : "quarterly revenue",
    axis_titles: ["Week", i % 17 === 0 ? "Concentration" : "Revenue"],
    legend_entries: [i % 17 === 0 ? "treated" : "North"],
  }));
  const started = performance.now();
  let hits = 0;
  for (let pass = 0; pass < 40; pass += 1) {
    hits = blobs.filter((blob) => matchesQuery(blob, "glucose concentration")).length;
  }
  const elapsed = performance.now() - started;
  assert.equal(hits, Math.ceil(400 / 17));
  assert.ok(elapsed < 250, `filter took ${elapsed.toFixed(1)}ms`);
});
