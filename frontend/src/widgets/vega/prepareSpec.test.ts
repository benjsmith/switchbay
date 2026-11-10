import assert from "node:assert/strict";
import { test } from "node:test";
import { fitSpecToPlotZone, plotCellSize } from "./prepareSpec.ts";

test("a spec larger than the plot zone is fitted inside it", () => {
  const fitted = fitSpecToPlotZone(
    { mark: "bar", width: 2400, height: 1600, encoding: { x: { field: "a" } } },
    { width: 480, height: 300 },
  );
  assert.equal(fitted.width, "container");
  assert.equal(fitted.height, "container");
});

test("plot cell size comes from the zone instead of an unbounded default", () => {
  const cell = plotCellSize({ width: 900, height: 700 });
  assert.ok(cell.width > 100);
  assert.ok(cell.width < 900);
  assert.ok(cell.height <= 368);
  assert.ok(cell.height > 100);
  const wide = plotCellSize({ width: 1400, height: 800 });
  assert.ok(wide.width < cell.width * 2);
});
