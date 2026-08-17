/**
 * Render-time Vega-Lite fixes so agent-authored specs don't clip
 * legends, collide axis titles with facet headers, or collapse
 * faceted charts into `height: "container"`.
 */

type Spec = Record<string, unknown>;

const COMPOSED_KEYS = ["layer", "hconcat", "vconcat", "concat"] as const;

function isObj(v: unknown): v is Spec {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

/** Walk every unit / layer / facet child (mutates in place). */
export function eachUnit(spec: unknown, visit: (unit: Spec) => void): void {
  if (!isObj(spec)) return;
  visit(spec);
  for (const key of COMPOSED_KEYS) {
    const arr = spec[key];
    if (Array.isArray(arr)) {
      for (const child of arr) eachUnit(child, visit);
    }
  }
  if (isObj(spec.spec)) eachUnit(spec.spec, visit);
}

export function isComposedLayout(spec: Spec): boolean {
  // `layer` is still one view — it should fill the card. Only
  // multi-view concatenations / facets need auto height so
  // panels aren't crushed into `height: container`.
  if (spec.facet || spec.repeat) return true;
  return ["hconcat", "vconcat", "concat"].some((k) => Array.isArray(spec[k]));
}

function collectColorEncodings(root: Spec): Spec[] {
  const out: Spec[] = [];
  eachUnit(root, (unit) => {
    const enc = unit.encoding;
    if (!isObj(enc)) return;
    const color = enc.color;
    if (isObj(color) && typeof color.field === "string" && color.field) {
      out.push(color);
    }
  });
  return out;
}

/**
 * Vega-Lite shares one color legend across layers. `legend: null` on
 * ANY layer removes that shared legend — agents often set it on
 * bands/error bars so those marks don't add extra entries, and the
 * country/category key disappears. If at least one layer wanted a
 * default or explicit legend, drop the nulls so the key comes back.
 */
export function restoreSharedColorLegend(root: Spec): void {
  const colors = collectColorEncodings(root);
  if (colors.length < 2) return;
  const hid = colors.filter((c) => c.legend === null);
  const kept = colors.filter((c) => c.legend !== null);
  if (hid.length === 0 || kept.length === 0) return;
  for (const c of hid) delete c.legend;
}

/**
 * Row facets default to a left-side header, rotated. Long values
 * ("Annual change (first derivative)") then sit on top of the
 * y-axis title. Put unspecified row headers above each panel.
 */
export function liftRowFacetHeaders(root: Spec): void {
  eachUnit(root, (unit) => {
    const facet = unit.facet;
    if (!isObj(facet)) return;
    const rows: Spec[] = [];
    if (isObj(facet.row)) rows.push(facet.row);
    // Shorthand `facet: { field, type }` is a column wrap — skip.
    for (const row of rows) {
      if (isObj(row.header)) continue;
      row.header = {
        labelOrient: "top",
        labelAnchor: "start",
        labelAlign: "left",
        labelPadding: 6,
        labelLimit: 420,
        title: null,
      };
    }
  });
}

/** Vega draws title.text as a single line unless given an array. */
export function wrapTitleText(title: unknown, tileCols: number): unknown {
  const maxCharsPerLine = 38 + Math.max(0, tileCols - 1) * 24;
  const split = (text: string): string[] => {
    if (text.length <= maxCharsPerLine) return [text];
    const words = text.split(/\s+/);
    const lines: string[] = [];
    let cur = "";
    for (const w of words) {
      const trial = cur ? cur + " " + w : w;
      if (trial.length > maxCharsPerLine && cur) {
        lines.push(cur);
        cur = w;
      } else {
        cur = trial;
      }
    }
    if (cur) lines.push(cur);
    return lines;
  };
  if (typeof title === "string") {
    const lines = split(title);
    return lines.length > 1 ? lines : title;
  }
  if (title && typeof title === "object" && !Array.isArray(title)) {
    const obj = title as { text?: unknown };
    if (typeof obj.text === "string") {
      const lines = split(obj.text);
      if (lines.length > 1) return { ...obj, text: lines };
    }
  }
  return title;
}

export type TileSize = { cols: number; rows: number };

export function tileSizeFor(spec: Spec): TileSize {
  const usermeta = spec.usermeta;
  if (!isObj(usermeta)) return { cols: 1, rows: 1 };
  const tile = usermeta.tile;
  if (!isObj(tile)) return { cols: 1, rows: 1 };
  if (typeof tile.size === "string") {
    switch (tile.size) {
      case "wide": return { cols: 2, rows: 1 };
      case "tall": return { cols: 1, rows: 2 };
      case "large": return { cols: 2, rows: 2 };
      case "full": return { cols: 4, rows: 1 };
    }
  }
  const cols = typeof tile.cols === "number" && tile.cols >= 1 && tile.cols <= 4
    ? Math.round(tile.cols) : 1;
  const rows = typeof tile.rows === "number" && tile.rows >= 1 && tile.rows <= 3
    ? Math.round(tile.rows) : 1;
  return { cols, rows };
}

/** Clone + apply layout/legend/title fixes for vega-embed. */
export function prepareSpecForEmbed(spec: Spec): Spec {
  const prepared: Spec = structuredClone(spec);
  restoreSharedColorLegend(prepared);
  liftRowFacetHeaders(prepared);
  const composed = isComposedLayout(prepared);
  if (prepared.width === undefined) prepared.width = "container";
  // `height: container` on facet/vconcat cramps each panel and
  // overlaps axis titles. Leave height unset so Vega-Lite sizes
  // the composition; the card CSS still gives the tile room.
  if (prepared.height === undefined && !composed) {
    prepared.height = "container";
  }
  if (composed && prepared.padding === undefined) {
    prepared.padding = { top: 8, right: 8, bottom: 8, left: 12 };
  }
  if (prepared.title !== undefined) {
    const ts = tileSizeFor(spec);
    prepared.title = wrapTitleText(prepared.title, ts.cols);
  }
  return prepared;
}
