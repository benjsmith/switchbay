/**
 * Graph legend labels from data.metaOntology.
 *
 * The shell HTML is the default vocabulary. This runs after data.json
 * loads and only rewrites labels when that object is present. With no
 * metaOntology key, any earlier overlay is cleared and the shell text
 * stands.
 */

export type LegendRow = { type: string; label: string };

export type LegendPlan = {
  relabel: Array<{ type: string; label: string; color?: string; description?: string }>;
  add: Array<{ type: string; label: string; color?: string; description?: string }>;
  edges: Array<{
    type: string;
    label: string;
    description?: string;
    color?: string;
    source?: string[];
    target?: string[];
  }>;
};

type OntologyNode = {
  type?: string;
  label?: string;
  description?: string;
  color?: string;
};

type OntologyEdge = {
  type?: string;
  label?: string;
  description?: string;
  color?: string;
  source?: string[];
  target?: string[];
};

type MetaOntology = {
  nodes?: OntologyNode[];
  edges?: OntologyEdge[];
};

export function readMetaOntology(data: unknown): MetaOntology | null {
  if (!data || typeof data !== "object" || !("metaOntology" in data)) return null;
  const raw = (data as { metaOntology?: unknown }).metaOntology;
  if (!raw || typeof raw !== "object") return null;
  return raw as MetaOntology;
}

export function planLegend(existing: LegendRow[], data: unknown): LegendPlan | null {
  const ont = readMetaOntology(data);
  if (!ont) return null;
  const have = new Set(existing.map((row) => row.type));
  const relabel: LegendPlan["relabel"] = [];
  const add: LegendPlan["add"] = [];
  for (const node of ont.nodes || []) {
    const type = (node.type || "").trim();
    const label = (node.label || "").trim();
    if (!type || !label) continue;
    const paletteColor = paletteColorOf(data, type);
    const item = {
      type,
      label,
      color: node.color || paletteColor,
      description: node.description,
    };
    if (have.has(type)) relabel.push(item);
    else add.push(item);
  }
  const edges: LegendPlan["edges"] = [];
  for (const edge of ont.edges || []) {
    const type = (edge.type || "").trim();
    const label = (edge.label || "").trim();
    if (!type || !label) continue;
    const source = stringList(edge.source);
    const target = stringList(edge.target);
    edges.push({
      type,
      label,
      description: edge.description,
      color: edge.color,
      source,
      target,
    });
  }
  return { relabel, add, edges };
}

export function applyMetaOntologyChrome(root: ParentNode, data: unknown): void {
  const panel = root.querySelector?.("#label-types-panel");
  if (!panel) return;
  clearOverlay(panel);
  clearInjectedEdgeStyle(root);
  applyPaletteVars(root, data);
  const existing = currentRows(panel);
  const plan = planLegend(existing, data);
  if (!plan) {
    return;
  }
  for (const change of plan.relabel) {
    const row = panel.querySelector(`.label-types-row[data-type="${cssAttr(change.type)}"]`);
    if (!row) continue;
    const textEl = labelSpan(row);
    if (!textEl) continue;
    if (!textEl.dataset.metaDefault) textEl.dataset.metaDefault = textEl.textContent || "";
    textEl.textContent = change.label;
    textEl.dataset.metaLabel = "1";
    if (change.description) row.setAttribute("title", change.description);
  }
  const reset = panel.querySelector("#label-types-reset");
  for (const extra of plan.add) {
    const row = document.createElement("label");
    row.className = "label-types-row";
    row.dataset.type = extra.type;
    row.dataset.metaAdded = "1";
    if (extra.description) row.title = extra.description;
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = true;
    const dot = document.createElement("span");
    dot.className = "dot";
    if (extra.color) dot.style.background = extra.color;
    const text = document.createElement("span");
    text.textContent = extra.label;
    row.append(box, dot, text);
    if (reset) panel.insertBefore(row, reset);
    else panel.append(row);
  }
  if (plan.edges.length) {
    const head = document.createElement("div");
    head.className = "label-types-head";
    head.dataset.metaAdded = "1";
    head.textContent = "Edges";
    const anchor = panel.querySelector("#label-types-reset");
    if (anchor) panel.insertBefore(head, anchor);
    else panel.append(head);
    for (const edge of plan.edges) {
      const row = document.createElement("div");
      row.className = "label-types-row";
      row.dataset.metaAdded = "1";
      row.dataset.edge = edge.type;
      if (edge.description) row.title = edge.description;
      if (edge.color) {
        const dot = document.createElement("span");
        dot.className = "dot";
        dot.style.background = edge.color;
        row.append(dot);
      }
      const text = document.createElement("span");
      const ends = edge.source?.length && edge.target?.length
        ? ` ${edge.source.join(", ")} → ${edge.target.join(", ")}`
        : "";
      text.textContent = `${edge.label} (${edge.type})${ends}`;
      row.append(text);
      if (anchor) panel.insertBefore(row, anchor);
      else panel.append(row);
    }
  }
}

function clearOverlay(panel: Element): void {
  panel.querySelectorAll("[data-meta-added]").forEach((node) => node.remove());
  panel.querySelectorAll("[data-meta-label]").forEach((node) => {
    const el = node as HTMLElement;
    if (el.dataset.metaDefault != null) el.textContent = el.dataset.metaDefault;
    delete el.dataset.metaLabel;
  });
  panel.querySelectorAll("[data-meta-color]").forEach((node) => {
    const el = node as HTMLElement;
    el.style.background = "";
    delete el.dataset.metaColor;
  });
}

function currentRows(panel: Element): LegendRow[] {
  const rows: LegendRow[] = [];
  panel.querySelectorAll(".label-types-row[data-type]").forEach((row) => {
    const type = row.getAttribute("data-type") || "";
    const text = labelSpan(row);
    if (!type || !text) return;
    rows.push({ type, label: text.dataset.metaDefault || text.textContent || "" });
  });
  return rows;
}

function labelSpan(row: Element): HTMLElement | null {
  for (const span of row.querySelectorAll("span")) {
    if (!span.classList.contains("dot")) return span;
  }
  return null;
}

function cssAttr(value: string): string {
  return value.replace(/["\\]/g, "");
}

function stringList(raw: unknown): string[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  const items = raw.map((item) => String(item || "").trim()).filter(Boolean);
  return items.length ? items : undefined;
}

function paletteColorOf(data: unknown, type: string): string | undefined {
  if (!data || typeof data !== "object" || !("palette" in data)) return undefined;
  const raw = (data as { palette?: unknown }).palette;
  if (!raw || typeof raw !== "object") return undefined;
  const color = (raw as Record<string, unknown>)[type];
  return typeof color === "string" && color.trim() ? color.trim() : undefined;
}

function applyPaletteVars(root: ParentNode, data: unknown): void {
  if (!data || typeof data !== "object" || !("palette" in data)) return;
  const raw = (data as { palette?: unknown }).palette;
  if (!raw || typeof raw !== "object") return;
  const doc = root instanceof Document ? root : (root as Node).ownerDocument;
  const el = doc?.documentElement;
  if (!el) return;
  for (const [typeName, color] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof color !== "string") continue;
    const hex = color.trim();
    if (!/^#[0-9a-fA-F]{6}$/.test(hex)) continue;
    const safe = typeName.replace(/[^a-zA-Z0-9_-]/g, "");
    if (!safe) continue;
    el.style.setProperty(`--type-${safe}`, hex);
  }
}

function clearInjectedEdgeStyle(root: ParentNode): void {
  // Older Switch Bay builds injected stroke rules that overrode the
  // payload colour. Drop any leftover stylesheet if it is still present.
  const doc = root instanceof Document ? root : (root as Node).ownerDocument;
  doc?.getElementById("meta-ontology-edge-style")?.remove();
}
