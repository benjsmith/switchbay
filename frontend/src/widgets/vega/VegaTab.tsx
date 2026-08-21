import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { useSelection } from "../../selection/SelectionContext";
import PlotAdjustDialog from "./PlotAdjustDialog";
import { ackUiCommand, takePlotShow } from "../../lib/pendingUiCommands";
import { prepareSpecForEmbed, tileSizeFor } from "./prepareSpec";

/**
 * Vega-Lite plot tab — tiled gallery.
 *
 * Every plot in `<workspace>/.workbench/plots/` renders as a card
 * in a CSS grid; each card has its own vega-embed instance + an
 * actions row (Save, Clone, Delete). Double-click anywhere on a
 * card opens a floating JSON editor modal for the spec.
 *
 * Vega-embed is heavy (~600 KB gzipped) so it's lazy-imported on
 * first card mount and reused across cards via the dynamic-import
 * cache.
 */

type PlotMeta = {
  id: string;
  name: string;
  origin?: string | null;
  created_at?: number;
  updated_at?: number;
};

type Plot = PlotMeta & {
  spec: Record<string, unknown>;
};

type VegaView = {
  toImageURL: (format: "png" | "svg", scaleFactor?: number) => Promise<string>;
};
type EmbedResult = {
  finalize?: () => void;
  view?: VegaView;
};

// Switch Bay's per-type palette — same hex values the graph viewer
// + wiki sidebar use. Passed as the categorical scheme to vega so
// chart marks share the visual language of the rest of the app.
const SWITCHBAY_CATEGORY_PALETTE = [
  "#1d6996",  // analysis blue
  "#38a6a5",  // concept teal
  "#0f8554",  // entity green
  "#edad08",  // fact yellow-orange
  "#e17c05",  // figure orange
  "#cc503e",  // table red
  "#94346e",  // source magenta
  "#73af48",  // evidence lime
  "#4d1ae8",  // project violet
  "#6f4070",  // note purple
  "#9656a2",  // todo purple-lighter
];

// Build the vega config dynamically so axis / title / legend
// colours track the active theme. Earlier we hard-coded
// dark-mode greys which read as washed-out on light themes.
//
// Modern-styling choices made here:
//   · no domain (axis) line — minimal chrome, lets the marks
//     own the visual weight (Tufte-ish).
//   · dotted, very faint grid — present enough to read values,
//     not loud enough to fight the data.
//   · system font stack so plots match the rest of the app
//     instead of vega's serif default.
//   · padding 16 + autosize fit-x — plots breathe in the
//     container without title/legend clipping.
function buildSwitchbayVegaConfig(): Record<string, unknown> {
  const isLight =
    typeof document !== "undefined"
    && document.documentElement.dataset.theme === "light";

  const textStrong = isLight ? "#1a1d22" : "#e6e8eb";
  const textBody   = isLight ? "#3a3f47" : "#c0c4cb";
  const textMuted  = isLight ? "#5a6068" : "#9aa0a8";
  const grid       = isLight ? "rgba(0,0,0,0.08)" : "rgba(255,255,255,0.06)";
  const tick       = isLight ? "rgba(0,0,0,0.18)" : "rgba(255,255,255,0.18)";

  const fontStack =
    "system-ui, -apple-system, 'SF Pro Text', 'Segoe UI', Inter, " +
    "'Helvetica Neue', Arial, sans-serif";

  return {
    background: "transparent",
    padding: { top: 28, right: 24, bottom: 32, left: 36 },
    // `fit` (both axes) pairs with the spec-level
    // `width/height: "container"` defaults injected at render
    // time — chart fills both card dimensions instead of just
    // matching width.
    autosize: { type: "fit", contains: "padding" },
    font: fontStack,
    axis: {
      labelColor: textBody,
      titleColor: textStrong,
      labelFont: fontStack,
      titleFont: fontStack,
      labelFontSize: 11,
      titleFontSize: 12,
      titleFontWeight: 500,
      titlePadding: 14,
      titleLimit: 180,
      titleLineHeight: 14,
      labelPadding: 6,
      labelLimit: 88,
      domain: false,            // skip the axis line
      tickColor: tick,
      tickSize: 4,
      tickWidth: 1,
      grid: true,
      gridColor: grid,
      gridDash: [2, 3],         // soft dotted grid
      gridWidth: 1,
    },
    legend: {
      labelColor: textBody,
      titleColor: textStrong,
      labelFont: fontStack,
      titleFont: fontStack,
      labelFontSize: 11,
      titleFontSize: 12,
      titleFontWeight: 500,
      symbolSize: 80,
      symbolStrokeWidth: 1.5,
      symbolOpacity: 1,
      orient: "right",
      padding: 12,
      offset: 8,
    },
    header: {
      labelColor: textStrong,
      titleColor: textMuted,
      labelFont: fontStack,
      titleFont: fontStack,
      labelFontSize: 12,
      labelFontWeight: 600,
      labelPadding: 6,
      labelLimit: 420,
    },
    title: {
      color: textStrong,
      subtitleColor: textMuted,
      font: fontStack,
      subtitleFont: fontStack,
      fontSize: 14,
      fontWeight: 600,
      anchor: "start",
      offset: 12,
      // Per-line truncation guard. Wrapping is handled
      // up-stream by prepareSpecForEmbed() which splits long
      // string titles into a line array; this limit only
      // kicks in for pathologically long unbreakable tokens.
      limit: 600,
      lineHeight: 18,
    },
    view: {
      stroke: "transparent",    // drop vega's default panel border
    },
    range: {
      category: SWITCHBAY_CATEGORY_PALETTE,
    },
    mark: {
      color: SWITCHBAY_CATEGORY_PALETTE[0],
    },
    bar: {
      cornerRadius: 2,
      cornerRadiusTopLeft: 2,
      cornerRadiusTopRight: 2,
    },
    point: {
      size: 60,
      filled: true,
      strokeWidth: 0,
    },
    line: {
      strokeWidth: 2,
    },
  };
}

/** Pull a one-line caption out of a Vega-Lite spec, if the
 *  author supplied one. CE-authored plots include a `description`
 *  field that explains what's plotted; some also nest a
 *  `title.subtitle`. We surface whichever is present so the card
 *  has a figure legend without forcing the agent to write it
 *  twice. */
function captionFor(spec: Record<string, unknown>): string | null {
  const desc = (spec as { description?: unknown }).description;
  if (typeof desc === "string" && desc.trim()) return desc.trim();
  const title = (spec as { title?: unknown }).title;
  if (title && typeof title === "object") {
    const sub = (title as { subtitle?: unknown }).subtitle;
    if (typeof sub === "string" && sub.trim()) return sub.trim();
    if (Array.isArray(sub)) {
      const joined = sub.filter((s) => typeof s === "string").join(" ");
      if (joined.trim()) return joined.trim();
    }
  }
  return null;
}


/** One plot tile. Mounts its own vega-embed instance; exposes the
 *  live view via the `onView` callback so the parent can drive
 *  Save / Save-All without re-rendering. */
type PlotCardProps = {
  plot: Plot;
  selected: boolean;
  themeGen: number;
  onSelect: () => void;
  onEdit: () => void;
  onAdjust: () => void;
  onSaveFigure: (view: VegaView) => void;
  onCopyPng: (view: VegaView) => void;
  onClear: () => void;
  onClone: () => void;
  onDelete: () => void;
  onRegenerate: () => void;
};
function PlotCard(props: PlotCardProps) {
  const {
    plot, selected, themeGen, onSelect, onEdit, onAdjust, onSaveFigure,
    onCopyPng, onClear, onClone, onDelete, onRegenerate,
  } = props;
  const hostRef = useRef<HTMLDivElement>(null);
  const embedRef = useRef<EmbedResult | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  // Right-click menu — `{x, y}` are viewport coords. Outside-click
  // and Esc close. We don't worry about off-screen positioning
  // here because the typical card is large enough that the menu
  // fits in the same screen region as the click.
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); setMenu(null); }
    };
    window.addEventListener("click", close);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [menu]);

  useEffect(() => {
    if (!hostRef.current) return;
    let cancelled = false;
    (async () => {
      try {
        const { default: embed } = await import("vega-embed");
        if (cancelled || !hostRef.current) return;
        if (embedRef.current?.finalize) {
          try { embedRef.current.finalize(); } catch { /* ignore */ }
        }
        const specWithSize = prepareSpecForEmbed(plot.spec);
        const result = await embed(hostRef.current, specWithSize, {
          actions: false,
          config: buildSwitchbayVegaConfig(),
        }) as EmbedResult;
        if (cancelled) {
          try { result.finalize?.(); } catch { /* ignore */ }
          return;
        }
        embedRef.current = result;
        // vega-embed sometimes "succeeds" on a spec that lacks
        // mark or encoding and produces a blank SVG. Surface that
        // explicitly — silently-empty cards are worse than an
        // error label since the user can't tell whether it's
        // still loading.
        const svg = hostRef.current?.querySelector("svg");
        const hasVisibleMark = svg
          && svg.querySelector("path, rect, circle, line, text") !== null;
        if (!hasVisibleMark) {
          const spec = plot.spec as Record<string, unknown>;
          const issues: string[] = [];
          if (!spec.mark && !(spec as { layer?: unknown }).layer) {
            issues.push("missing `mark`");
          }
          if (!spec.encoding && !(spec as { layer?: unknown }).layer) {
            issues.push("missing `encoding`");
          }
          const data = (spec.data ?? {}) as { values?: unknown[]; name?: string };
          if (!data.name && (!Array.isArray(data.values) || data.values.length === 0)) {
            issues.push("empty / missing `data.values`");
          }
          setRenderError(
            issues.length
              ? `spec rendered empty — ${issues.join(", ")}`
              : "spec rendered empty (no visible marks)",
          );
        } else {
          setRenderError(null);
        }
      } catch (e) {
        if (!cancelled) setRenderError((e as Error).message);
      }
    })();
    return () => { cancelled = true; };
  }, [plot.spec, themeGen]);

  useEffect(() => () => {
    if (embedRef.current?.finalize) {
      try { embedRef.current.finalize(); } catch { /* ignore */ }
    }
  }, []);

  const caption = captionFor(plot.spec);
  const tile = tileSizeFor(plot.spec);
  // `grid-column / grid-row` span tells the parent grid to let
  // this card occupy more than one cell. Capped via tileSizeFor
  // so a runaway spec can't blow out the layout.
  const tileStyle: CSSProperties = {
    gridColumn: tile.cols > 1 ? `span ${tile.cols}` : undefined,
    gridRow: tile.rows > 1 ? `span ${tile.rows}` : undefined,
  };

  return (
    <article
      className={"sy-plot-card" + (selected ? " sy-plot-card--selected" : "")}
      style={tileStyle}
      onClick={onSelect}
      onDoubleClick={(e) => {
        const t = e.target as HTMLElement | null;
        if (t && t.closest && t.closest("button")) return;
        e.preventDefault();
        onEdit();
      }}
      onContextMenu={(e) => {
        e.preventDefault();
        e.stopPropagation();
        setMenu({ x: e.clientX, y: e.clientY });
      }}
      aria-label={`${plot.name}. Double-click to edit, right-click for actions`}
    >
      <header className="sy-plot-card-head">
        <span className="sy-plot-card-title" title={plot.name}>{plot.name}</span>
        <span className="sy-plot-card-actions">
          <button
            type="button"
            className="sy-plot-card-btn"
            onClick={(e) => {
              e.stopPropagation();
              const view = embedRef.current?.view;
              if (view) onSaveFigure(view);
            }}
            title="Save this plot as a wiki figure doc + PNG asset"
            aria-label="Save plot"
          >↓</button>
          <button
            type="button"
            className="sy-plot-card-btn"
            onClick={(e) => { e.stopPropagation(); onAdjust(); }}
            title="Adjust axes, scale, ticks, titles"
            aria-label="Adjust plot"
          >⚙</button>
          <button
            type="button"
            className="sy-plot-card-btn"
            onClick={(e) => { e.stopPropagation(); onClone(); }}
            title="Duplicate this plot"
            aria-label="Clone plot"
          >⎘</button>
          <button
            type="button"
            className="sy-plot-card-btn sy-plot-card-btn--danger"
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            title="Delete this plot"
            aria-label="Delete plot"
          >✕</button>
        </span>
      </header>
      <div ref={hostRef} className="sy-plot-card-canvas" />
      {caption && <p className="sy-plot-card-caption">{caption}</p>}
      {renderError && (
        <p className="sy-plot-card-err">Render error: {renderError}</p>
      )}
      {menu && (
        <ul
          className="sy-context-menu"
          role="menu"
          style={{ position: "fixed", top: menu.y, left: menu.x }}
          onClick={(e) => e.stopPropagation()}
        >
          <li
            role="menuitem"
            className="sy-context-menu-item"
            onClick={() => {
              setMenu(null);
              const view = embedRef.current?.view;
              if (view) onCopyPng(view);
            }}
            title="Copy the plot as a PNG to the clipboard"
          >Copy PNG</li>
          <li
            role="menuitem"
            className="sy-context-menu-item"
            onClick={() => {
              setMenu(null);
              const view = embedRef.current?.view;
              if (view) onSaveFigure(view);
            }}
            title="Write PNG to wiki/figures/_assets and create a figure doc"
          >Save as figure</li>
          <li
            role="menuitem"
            className="sy-context-menu-item"
            onClick={() => { setMenu(null); onEdit(); }}
            title="Edit the Vega-Lite spec directly"
          >Edit spec…</li>
          <li
            role="menuitem"
            className="sy-context-menu-item"
            onClick={() => { setMenu(null); onRegenerate(); }}
            title="Describe a change in natural language; agent rewrites the spec"
          >Regenerate with edits…</li>
          <li
            role="menuitem"
            className="sy-context-menu-item"
            onClick={() => { setMenu(null); onClone(); }}
            title="Duplicate this plot under a new id"
          >Clone</li>
          <li
            role="menuitem"
            className="sy-context-menu-item"
            onClick={() => { setMenu(null); onClear(); }}
            title="Hide this plot from the gallery; the file stays on disk"
          >Clear from canvas</li>
          <li
            role="menuitem"
            className="sy-context-menu-item sy-context-menu-item--danger"
            onClick={() => { setMenu(null); onDelete(); }}
            title="Delete this plot file from .workbench/plots/"
          >Delete…</li>
        </ul>
      )}
    </article>
  );
}


export default function VegaTab() {
  const { selection, setSelection } = useSelection();
  const [plots, setPlots] = useState<PlotMeta[] | null>(null);
  const [specs, setSpecs] = useState<Record<string, Plot>>({});
  const [listError, setListError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [saveAllBusy, setSaveAllBusy] = useState(false);
  // Plot ids the user has "cleared from canvas" via the
  // right-click menu. Non-destructive — the JSON file stays on
  // disk. Persisted so a reload preserves the hide state.
  const HIDDEN_KEY = "sy.vega.hidden";
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem(HIDDEN_KEY);
      if (!raw) return new Set();
      const arr = JSON.parse(raw);
      return Array.isArray(arr) ? new Set(arr.map(String)) : new Set();
    } catch { return new Set(); }
  });
  useEffect(() => {
    try {
      localStorage.setItem(HIDDEN_KEY, JSON.stringify([...hiddenIds]));
    } catch { /* quota / disabled storage — best-effort */ }
  }, [hiddenIds]);
  // Editor modal — open when non-null, holds the plot being edited
  // + the raw JSON draft. Save validates + persists; Cancel drops.
  const [adjusting, setAdjusting] = useState<Plot | null>(null);
  const [editing, setEditing] = useState<{
    plot: Plot;
    draft: string;
    error: string | null;
    saving: boolean;
  } | null>(null);
  // Theme generation counter — same MutationObserver pattern as
  // before, propagated to every card so axis colours track the
  // active theme.
  const [themeGen, setThemeGen] = useState(0);
  useEffect(() => {
    if (typeof MutationObserver === "undefined") return;
    const obs = new MutationObserver(() => setThemeGen((g) => g + 1));
    obs.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => obs.disconnect();
  }, []);

  const reloadList = useCallback(async () => {
    try {
      const r = await fetch("/api/plots");
      if (!r.ok) { setListError(`HTTP ${r.status}`); return; }
      const body = (await r.json()) as { plots: PlotMeta[] };
      setPlots(body.plots);
      setListError(null);
    } catch (e) {
      setListError((e as Error).message);
    }
  }, []);

  useEffect(() => { void reloadList(); }, [reloadList]);

  // Polling so agent-authored plots appear without a manual
  // refresh. Cheap — single glob over .workbench/plots/.
  useEffect(() => {
    const id = window.setInterval(() => { void reloadList(); }, 2500);
    return () => window.clearInterval(id);
  }, [reloadList]);

  // Fetch full spec for each plot (small JSON files). Tile layout
  // means we need every spec in memory; do it sparingly by caching
  // by id and only fetching the missing ones.
  useEffect(() => {
    if (!plots) return;
    let cancelled = false;
    (async () => {
      const next: Record<string, Plot> = { ...specs };
      for (const meta of plots) {
        const existing = next[meta.id];
        if (existing && existing.updated_at === meta.updated_at) continue;
        try {
          const r = await fetch(`/api/plot?id=${encodeURIComponent(meta.id)}`);
          if (!r.ok) continue;
          const body = (await r.json()) as { plot: Plot };
          if (cancelled) return;
          next[meta.id] = body.plot;
        } catch { /* skip; next poll will retry */ }
      }
      // Drop specs for plots that no longer exist.
      const live = new Set(plots.map((p) => p.id));
      for (const k of Object.keys(next)) {
        if (!live.has(k)) delete next[k];
      }
      if (!cancelled) setSpecs(next);
    })();
    return () => { cancelled = true; };
  }, [plots]); // eslint-disable-line react-hooks/exhaustive-deps

  // Selection-driven scroll: when another tab dispatches a plot
  // selection (e.g. /plot sales), highlight that card and scroll
  // it into view.
  const cardRefs = useRef<Map<string, HTMLElement | null>>(new Map());
  const scrolledFor = useRef<string | null>(null);
  const selectedId = selection?.kind === "plot" ? selection.id : null;

  // Publish focused plot for plot_context / plot_update.
  const lastPlotFocusRef = useRef("");
  useEffect(() => {
    const id = selectedId
      || (plots && plots.length === 1 ? plots[0]!.id : null);
    if (!id) return;
    const meta = plots?.find((p) => p.id === id);
    const full = specs[id];
    const payload = {
      surface: "plot",
      id,
      name: meta?.name || full?.name || id,
      origin: meta?.origin ?? full?.origin ?? null,
      // Spec can be large — only include mark/encoding keys for the
      // focus blob; plot_context loads the full file from disk.
      mark: full?.spec && typeof full.spec === "object"
        ? (full.spec as { mark?: unknown }).mark
        : undefined,
      updated_at: meta?.updated_at ?? full?.updated_at,
    };
    const serialised = JSON.stringify(payload);
    if (serialised === lastPlotFocusRef.current) return;
    lastPlotFocusRef.current = serialised;
    void fetch("/api/ui/focus", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: serialised,
    }).catch(() => { /* ignore */ });
  }, [selectedId, plots, specs]);

  // Agent plot_show — reload list; drain cold-mount stash; ACK wait_ack.
  useEffect(() => {
    const applyShow = async (detail?: { id?: string; name?: string; command_id?: string }) => {
      try {
        await reloadList();
        if (detail?.command_id) {
          await ackUiCommand({
            command_id: detail.command_id,
            ok: true,
            surface: "plot",
            applied: true,
            label: detail.id || detail.name,
          });
        }
      } catch (e) {
        if (detail?.command_id) {
          await ackUiCommand({
            command_id: detail.command_id,
            ok: false,
            surface: "plot",
            error: (e as Error).message,
          });
        }
      }
    };
    const onShow = (ev: Event) => {
      void applyShow(
        (ev as CustomEvent<{ id?: string; name?: string; command_id?: string }>).detail,
      );
    };
    window.addEventListener("sy:plot-show", onShow);
    const stashed = takePlotShow();
    if (stashed) void applyShow(stashed);
    return () => window.removeEventListener("sy:plot-show", onShow);
  }, [reloadList]);

  useEffect(() => {
    if (!selectedId) { scrolledFor.current = null; return; }
    if (scrolledFor.current === selectedId) return; // already scrolled
    const el = cardRefs.current.get(selectedId);
    if (el && el.scrollIntoView) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      scrolledFor.current = selectedId;
    }
    // `plots` in deps: a freshly-imported plot (e.g. OWID) may not be in
    // the list the instant its selection arrives — re-check on reload,
    // but the ref guard keeps it to one scroll per selection.
  }, [selectedId, plots]);

  // ── Action handlers (per-plot) ───────────────────────────────────

  const renderSpecToPng = useCallback(async (
    spec: Record<string, unknown>,
  ): Promise<string> => {
    const { default: embed } = await import("vega-embed");
    const host = document.createElement("div");
    host.style.cssText =
      "position:absolute; left:-10000px; top:0; width:800px; height:500px;";
    document.body.appendChild(host);
    try {
      const specWithSize = prepareSpecForEmbed(spec);
      const result = await embed(host, specWithSize, {
        actions: false,
        config: buildSwitchbayVegaConfig(),
      }) as EmbedResult;
      const view = result.view;
      if (!view) throw new Error("vega-embed returned no view");
      const url = await view.toImageURL("png", 2);
      try { result.finalize?.(); } catch { /* ignore */ }
      return url;
    } finally {
      host.remove();
    }
  }, []);

  const onSaveOne = useCallback(async (plot: Plot, view: VegaView) => {
    setSaveStatus(`saving ${plot.name}…`);
    try {
      const png_b64 = await view.toImageURL("png", 2);
      const r = await fetch("/api/plot/save-as-figure", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: plot.id, png_b64 }),
      });
      const body = await r.json();
      if (!r.ok) { setSaveStatus(body.error ?? `HTTP ${r.status}`); return; }
      setSaveStatus(`saved → ${body.figure_path}`);
      window.setTimeout(() => setSaveStatus(null), 3500);
    } catch (e) {
      setSaveStatus(`save failed: ${(e as Error).message}`);
    }
  }, []);

  const onCloneOne = useCallback(async (plot: Plot) => {
    try {
      const r = await fetch("/api/plot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: `${plot.name} (copy)`,
          spec: plot.spec,
        }),
      });
      if (!r.ok) { setListError(`clone failed: HTTP ${r.status}`); return; }
      const j = (await r.json()) as { plot: Plot };
      await reloadList();
      setSelection({ kind: "plot", id: j.plot.id, name: j.plot.name });
    } catch (e) {
      setListError((e as Error).message);
    }
  }, [reloadList, setSelection]);

  const onDeleteOne = useCallback(async (plot: Plot) => {
    if (!window.confirm(`Delete plot "${plot.name}"?`)) return;
    try {
      await fetch(`/api/plot?id=${encodeURIComponent(plot.id)}`, {
        method: "DELETE",
      });
    } catch (e) {
      setListError((e as Error).message);
      return;
    }
    if (selection?.kind === "plot" && selection.id === plot.id) {
      setSelection(null);
    }
    await reloadList();
  }, [reloadList, selection, setSelection]);

  const onEditOne = useCallback((plot: Plot) => {
    setEditing({
      plot,
      draft: JSON.stringify(plot.spec, null, 2),
      error: null,
      saving: false,
    });
  }, []);

  const onCopyPngOne = useCallback(async (plot: Plot, view: VegaView) => {
    setSaveStatus(`copying ${plot.name}…`);
    try {
      const url = await view.toImageURL("png", 2);
      // url is a data: URL — fetch gives us a Blob the Clipboard
      // API can write directly.
      const blob = await fetch(url).then((r) => r.blob());
      // Some browsers gate ClipboardItem behind isSecureContext;
      // an HTTP localhost is secure-context by spec, so this works
      // in the daemon's dev env.
      const item = new ClipboardItem({ [blob.type || "image/png"]: blob });
      await navigator.clipboard.write([item]);
      setSaveStatus(`copied ${plot.name} to clipboard`);
      window.setTimeout(() => setSaveStatus(null), 3000);
    } catch (e) {
      setSaveStatus(`copy failed: ${(e as Error).message}`);
    }
  }, []);

  /** Per-plot "Regenerate with edits…" entry point. Drops a
   *  primer prompt into the rail naming the plot id + path and
   *  positions the cursor at the end of an "Edits I want:" block
   *  so the user types what they want changed and hits enter.
   *  The agent reads the current spec, edits, and re-saves with
   *  the same id so the card updates in place. */
  const onRegenerateOne = useCallback((plot: Plot) => {
    const prompt = (
      `Re-author the plot \`${plot.id}\` (\`.workbench/plots/${plot.id}.json\`) `
      + `keeping the same id so the existing card updates in place. `
      + `Read the current spec first; preserve its data unless the user `
      + `explicitly asks for new data; keep \`name\`, \`origin\`, and `
      + `\`description\` unless the requested edit changes their meaning.\n\n`
      + `Use save_plot(id="${plot.id}", name="${plot.name}", spec={...}) `
      + `to write back.\n\n`
      + `Edits I want:\n  · `
    );
    window.dispatchEvent(new CustomEvent("sy:rail-set-input", {
      detail: { text: prompt, focus: true },
    }));
  }, []);

  const onClearOne = useCallback((plot: Plot) => {
    setHiddenIds((cur) => {
      const next = new Set(cur);
      next.add(plot.id);
      return next;
    });
  }, []);

  const unhideAll = useCallback(() => {
    setHiddenIds(new Set());
  }, []);

  /** + New Plot — drop a primer + instructions into the rail and
   *  put the cursor at the end of the prompt so the user just
   *  appends what they want plotted. Two events: a system tip
   *  surfaces the available data sources / tool guidance as a
   *  rail notice (transcript-visible), and a set-input writes
   *  the actual primer into the chat field with focus. */
  const onNewPlot = useCallback(() => {
    window.dispatchEvent(new CustomEvent("sy:rail-system-tip", {
      detail: {
        text:
          "Authoring a plot. The `save_plot` tool stores a Vega-Lite "
          + "spec at `.workbench/plots/<id>.json` and the Plot tab "
          + "renders it. Data sources you can pull from:\n"
          + "  · Inline values in `spec.data.values: [...]` — best "
          + "for small derived series you've already computed.\n"
          + "  · The pre-seeded DuckDB tables `files` / `pages` via "
          + "`{\"data\": {\"name\": \"pages\"}}` — workspace-wide.\n"
          + "  · CSVs in the workspace via DuckDB — query first, then "
          + "inline the aggregated rows.\n"
          + "Include `spec.description` (one short sentence) so the "
          + "plot card has a figure legend. Give the plot a "
          + "descriptive name (`save_plot(name=…, spec=…)`) — that "
          + "becomes the tile title.",
        focus: false,
      },
    }));
    window.dispatchEvent(new CustomEvent("sy:rail-set-input", {
      detail: {
        text:
          "Author a Vega-Lite plot via save_plot. Title it with a "
          + "concise descriptor and include a one-sentence "
          + "`description` field in the spec.\n\n"
          + "Plot to make:\n  · ",
        focus: true,
      },
    }));
  }, []);

  // ── Save-All-as-PNG ──────────────────────────────────────────────

  const saveAllAsFigures = useCallback(async () => {
    if (!plots || plots.length === 0 || saveAllBusy) return;
    setSaveAllBusy(true);
    setSaveStatus(`saving 0 / ${plots.length}`);
    let saved = 0;
    let failed = 0;
    for (const meta of plots) {
      try {
        const pj = specs[meta.id];
        if (!pj) throw new Error("spec missing");
        const png_b64 = await renderSpecToPng(pj.spec);
        const sr = await fetch("/api/plot/save-as-figure", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: meta.id, png_b64 }),
        });
        if (!sr.ok) {
          const eb = await sr.json().catch(() => ({} as Record<string, string>));
          throw new Error(eb.error ?? `save HTTP ${sr.status}`);
        }
        saved++;
      } catch (e) {
        console.warn("Plot save failed:", meta.id, e);
        failed++;
      }
      setSaveStatus(
        `saving ${saved + failed} / ${plots.length}` +
        (failed ? ` (${failed} failed)` : ""),
      );
    }
    setSaveStatus(
      failed
        ? `done — ${saved} saved, ${failed} failed`
        : `saved ${saved} figure${saved === 1 ? "" : "s"}`,
    );
    window.setTimeout(() => setSaveStatus(null), 5000);
    setSaveAllBusy(false);
  }, [plots, specs, renderSpecToPng, saveAllBusy]);

  // ── Editor modal commits ─────────────────────────────────────────

  const commitEditor = useCallback(async () => {
    if (!editing) return;
    let parsed: Record<string, unknown>;
    try {
      const v = JSON.parse(editing.draft);
      if (!v || typeof v !== "object" || Array.isArray(v)) {
        throw new Error("spec must be a JSON object");
      }
      parsed = v as Record<string, unknown>;
    } catch (e) {
      setEditing((cur) =>
        cur ? { ...cur, error: (e as Error).message } : cur,
      );
      return;
    }
    setEditing((cur) => cur ? { ...cur, saving: true, error: null } : cur);
    try {
      const r = await fetch("/api/plot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: editing.plot.id,
          name: editing.plot.name,
          spec: parsed,
        }),
      });
      if (!r.ok) {
        const eb = await r.json().catch(() => ({} as Record<string, string>));
        setEditing((cur) =>
          cur ? { ...cur, saving: false, error: eb.error ?? `HTTP ${r.status}` } : cur,
        );
        return;
      }
      // Drop the spec cache so the card refetches the new version.
      setSpecs((cur) => {
        const next = { ...cur };
        delete next[editing.plot.id];
        return next;
      });
      setEditing(null);
      await reloadList();
    } catch (e) {
      setEditing((cur) =>
        cur ? { ...cur, saving: false, error: (e as Error).message } : cur,
      );
    }
  }, [editing, reloadList]);

  // Esc closes the editor without saving; Cmd/Ctrl-S commits.
  useEffect(() => {
    if (!editing) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); setEditing(null); }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        void commitEditor();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editing, commitEditor]);

  // ── Render ───────────────────────────────────────────────────────

  if (plots === null) {
    return <div className="sy-vega-banner">Loading plots…</div>;
  }
  if (plots.length === 0) {
    return (
      <div className="sy-vega">
        <div className="sy-vega-toolbar">
          <span
            className="sy-tab-engine"
            title="Plot engine — Vega-Lite specs rendered via vega-embed"
          >
            Vega-Lite
          </span>
          <button
            type="button"
            className="sy-vega-toolbar-btn"
            onClick={onNewPlot}
            title="Drop a primer prompt into the rail chat and focus the cursor so you can describe the plot you want"
          >
            + New Plot…
          </button>
        </div>
        <div className="sy-vega-empty">
          <h2>No plots yet</h2>
          <p>
            Plots are Vega-Lite specs — click <strong>+ New Plot…</strong>{" "}
            to drop a primer into the rail chat, or ask the agent
            yourself (“plot quarterly revenue from sales.csv”).
            You can also click <strong>↗ Plot</strong> on a table to
            fan out a few plots from its data.
          </p>
          {listError && <p className="sy-vega-err">List error: {listError}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="sy-vega">
      <div className="sy-vega-toolbar">
        <span
          className="sy-tab-engine"
          title="Plot engine — Vega-Lite specs rendered via vega-embed"
        >
          Vega-Lite
        </span>
        <button
          type="button"
          className="sy-vega-toolbar-btn sy-vega-save-all"
          onClick={() => { void saveAllAsFigures(); }}
          disabled={saveAllBusy || plots.length === 0}
          title="Render every plot to PNG and create a figure doc per plot under wiki/figures/"
        >
          ↓ Save All as PNG
        </button>
        <button
          type="button"
          className="sy-vega-toolbar-btn"
          onClick={onNewPlot}
          title="Drop a primer prompt into the rail chat and focus the cursor so you can describe the plot you want"
        >
          + New Plot…
        </button>
        {saveStatus && (
          <span className="sy-vega-save-status" title={saveStatus}>
            {saveStatus}
          </span>
        )}
        <span className="sy-spacer" />
        {hiddenIds.size > 0 && (
          <button
            type="button"
            className="sy-vega-toolbar-btn"
            onClick={unhideAll}
            title="Restore plots cleared from the canvas via right-click → Clear"
          >Show {hiddenIds.size} hidden</button>
        )}
        <span className="sy-vega-counter">
          {plots.length - hiddenIds.size} / {plots.length} shown
        </span>
      </div>
      <div className="sy-plot-grid">
        {plots.filter((meta) => !hiddenIds.has(meta.id)).map((meta) => {
          const full = specs[meta.id];
          if (!full) {
            return (
              <article key={meta.id} className="sy-plot-card sy-plot-card--loading">
                <header className="sy-plot-card-head">
                  <span className="sy-plot-card-title">{meta.name}</span>
                </header>
                <div className="sy-plot-card-canvas" />
                <p className="sy-plot-card-caption">Loading spec…</p>
              </article>
            );
          }
          return (
            <div
              key={meta.id}
              ref={(el) => { cardRefs.current.set(meta.id, el); }}
              style={{ display: "contents" }}
            >
              <PlotCard
                plot={full}
                selected={selectedId === meta.id}
                themeGen={themeGen}
                onSelect={() => setSelection({
                  kind: "plot", id: full.id, name: full.name,
                })}
                onEdit={() => onEditOne(full)}
                onAdjust={() => setAdjusting(full)}
                onSaveFigure={(view) => { void onSaveOne(full, view); }}
                onCopyPng={(view) => { void onCopyPngOne(full, view); }}
                onClear={() => onClearOne(full)}
                onRegenerate={() => onRegenerateOne(full)}
                onClone={() => { void onCloneOne(full); }}
                onDelete={() => { void onDeleteOne(full); }}
              />
            </div>
          );
        })}
      </div>
      {adjusting && (
        <PlotAdjustDialog
          plot={adjusting}
          onClose={() => setAdjusting(null)}
          onApplied={(sel) => {
            // Evict the (over)written plot from the spec cache so the
            // card refetches the adjusted spec instead of keeping the
            // stale one (the specs effect only refetches on updated_at
            // change; a hard evict guarantees the refresh).
            if (sel) {
              setSpecs((s) => { const n = { ...s }; delete n[sel.id]; return n; });
            }
            void reloadList();
            if (sel) setSelection({ kind: "plot", id: sel.id, name: sel.name });
          }}
        />
      )}
      {editing && (
        <div
          className="sy-plot-editor-backdrop"
          onClick={() => setEditing(null)}
        >
          <div
            className="sy-plot-editor"
            role="dialog"
            aria-labelledby="sy-plot-editor-title"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="sy-plot-editor-head">
              <span id="sy-plot-editor-title" className="sy-plot-editor-title">
                Edit · <strong>{editing.plot.name}</strong>
              </span>
              <span className="sy-plot-editor-hint">
                Vega-Lite spec (JSON)
              </span>
            </header>
            <textarea
              className="sy-plot-editor-text"
              value={editing.draft}
              spellCheck={false}
              autoFocus
              onChange={(e) => setEditing((cur) =>
                cur ? { ...cur, draft: e.target.value } : cur,
              )}
            />
            {editing.error && (
              <div className="sy-plot-editor-err">{editing.error}</div>
            )}
            <footer className="sy-plot-editor-foot">
              <span className="sy-plot-editor-help">
                ⌘S to save, Esc to cancel
              </span>
              <span className="sy-spacer" />
              <button
                type="button"
                className="sy-vega-toolbar-btn"
                onClick={() => setEditing(null)}
                disabled={editing.saving}
              >Cancel</button>
              <button
                type="button"
                className="sy-vega-toolbar-btn"
                onClick={() => { void commitEditor(); }}
                disabled={editing.saving}
              >{editing.saving ? "Saving…" : "Save"}</button>
            </footer>
          </div>
        </div>
      )}
    </div>
  );
}
