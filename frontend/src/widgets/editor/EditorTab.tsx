import { useEffect, useMemo, useRef, useState } from "react";
import { marked } from "marked";
import { sanitizeHtml } from "../../lib/sanitizeHtml";
import { useSelection } from "../../selection/SelectionContext";
import { useTabs } from "../../center/TabsContext";
import { expandWikilinks, parseFrontmatter } from "./mdview";
import { isCollapsibleList, readSourcesOpen, writeSourcesOpen } from "./previewLists";
import MiniGraph from "./MiniGraph";
import type { GraphData } from "../graph/types";
import {
  getBreadcrumb, subscribe as subscribeBreadcrumb,
  type ProjectBreadcrumb,
} from "../projects/breadcrumb";
import { setDeckRun } from "../sketch/deckRuns";
import CodeView, { detectLanguage, LANGUAGE_CHOICES, type CodeLanguage } from "./CodeView";
import { notifyHtmlDeckOpen } from "../htmldeck/htmlDeckOpen";

// Markdown view mode, driven by the chevron handle on the pane divider.
// Ordered raw → split → rendered. The chevrons move the split the way
// they POINT (like dragging the divider): ‹ grows the right (rendered)
// pane, › grows the left (raw) pane.
type EditorView = "raw" | "split" | "rendered";
const EDITOR_VIEW_KEY = "sy:editor-view";
const VIEW_ORDER: EditorView[] = ["raw", "split", "rendered"];
function readEditorView(): EditorView {
  try {
    const v = localStorage.getItem(EDITOR_VIEW_KEY);
    if (v === "raw" || v === "split" || v === "rendered") return v;
  } catch { /* storage disabled */ }
  return "split";
}

type LoadState =
  | { kind: "idle" }
  | { kind: "loading" }
  // File lives on a cloud-sync service (iCloud/OneDrive/…) and its
  // bytes aren't local yet; the daemon is hydrating it in the
  // background. We poll until it's available instead of hanging.
  | { kind: "syncing"; service: string | null }
  | { kind: "ready"; original: string; draft: string }
  | { kind: "saving"; original: string; draft: string }
  | { kind: "error"; message: string };

export default function EditorTab() {
  const { selection, setSelection } = useSelection();
  const { switchToKind, tabs } = useTabs();
  const [state, setState] = useState<LoadState>({ kind: "idle" });
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const sourceRef = useRef<HTMLTextAreaElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);

  const path = selection?.kind === "page" ? selection.path : null;
  const pageId = selection?.kind === "page" ? selection.id : null;
  const hasGraphTab = useMemo(() => tabs.some((t) => t.kind === "graph"), [tabs]);
  const hasProjectsTab = useMemo(() => tabs.some((t) => t.kind === "projects"), [tabs]);
  const hasSheetTab = useMemo(() => tabs.some((t) => t.kind === "univer"), [tabs]);
  const hasSketchTab = useMemo(
    () => tabs.some((t) => t.kind === "sketch"),
    [tabs],
  );

  // Track the project the current page was opened from. Set by the
  // Projects tab when the user clicks a row; cleared when the user
  // navigates somewhere unrelated (selection.path no longer matches).
  const [breadcrumb, setBreadcrumbState] = useState<ProjectBreadcrumb | null>(getBreadcrumb);
  useEffect(() => subscribeBreadcrumb(setBreadcrumbState), []);
  // Show the back-link only when the breadcrumb still describes the
  // currently-open page. Avoids stale links if the user opened the
  // doc from project X, then navigated to a different doc by some
  // other route.
  const projectBackLink = breadcrumb && path && breadcrumb.path === path
    ? breadcrumb : null;

  // In-flight lock for the → Sketch deck button. Prevents a second
  // click (when the daemon's frontmatter walk takes a moment on a big
  // workspace) from scaffolding a duplicate deck.
  const [creatingSketchDeck, setCreatingSketchDeck] = useState(false);
  // Code-mode language. Auto-detected from path + content on each
  // new load; the toolbar selector lets the user override.
  const [langOverride, setLangOverride] = useState<CodeLanguage | null>(null);
  // Markdown view mode: raw ↔ split (default) ↔ rendered. Persisted;
  // code files ignore it (they have no preview pane).
  const [viewMode, setViewMode] = useState<EditorView>(readEditorView);
  useEffect(() => {
    try { localStorage.setItem(EDITOR_VIEW_KEY, viewMode); } catch { /* quota */ }
  }, [viewMode]);
  const vIdx = VIEW_ORDER.indexOf(viewMode);
  const stepView = (d: -1 | 1) => {
    setViewMode(VIEW_ORDER[Math.max(0, Math.min(VIEW_ORDER.length - 1, vIdx + d))]!);
  };

  // Fetch the workspace's graph data once so MiniGraph below has
  // something to draw. The daemon caches data.json in-memory so this
  // is a single round-trip per Editor mount; subsequent renders use
  // the cached state.
  useEffect(() => {
    let cancelled = false;
    fetch("/api/graph/data")
      .then(async (r) => (r.ok ? ((await r.json()) as GraphData) : null))
      .then((d) => { if (!cancelled && d) setGraphData(d); })
      .catch(() => { /* fresh workspace, no wiki/ — fine */ });
    return () => { cancelled = true; };
  }, []);

  // Hooks below MUST run on every render — placing them before any
  // early `return` so React's hook-call sequence stays stable.
  const draft = state.kind === "ready" || state.kind === "saving" ? state.draft : "";
  const original = state.kind === "ready" || state.kind === "saving" ? state.original : "";
  const { properties, body } = useMemo(() => parseFrontmatter(draft), [draft]);
  const previewHtml = useMemo(
    () => (draft ? sanitizeHtml(marked.parse(expandWikilinks(body), { async: false }) as string) : ""),
    [draft, body],
  );

  // After every preview re-render, walk the rendered DOM and drop a
  // small "↗ Sheet" button before each <table> so the user can swap
  // a markdown table into the Sheet tab without hand-editing pipes.
  // Click → parse the table cells into a 2D array, set a `table-data`
  // selection, switch tabs.
  const hasPlotTab = useMemo(() => tabs.some((t) => t.kind === "vega"), [tabs]);
  useEffect(() => {
    if (!hasSheetTab && !hasPlotTab) return;
    const root = previewRef.current?.querySelector(".sy-mdview");
    if (!root) return;
    // Clean up any buttons left over from a previous render.
    root.querySelectorAll(".sy-mdview-table-linkout, .sy-mdview-table-linkout-row")
      .forEach((b) => b.remove());
    const tables = root.querySelectorAll<HTMLTableElement>("table");
    tables.forEach((table, i) => {
      const row = document.createElement("div");
      row.className = "sy-mdview-table-linkout-row";
      const origin = `${path ?? "editor"}#table-${i + 1}`;

      if (hasSheetTab) {
        const sheetBtn = document.createElement("button");
        sheetBtn.type = "button";
        sheetBtn.className = "sy-mdview-table-linkout";
        sheetBtn.textContent = "↗ Sheet";
        sheetBtn.title = "Open this table in the Sheet tab for editing";
        sheetBtn.addEventListener("click", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          const values = parseTableValues(table);
          if (values.length === 0) return;
          setSelection({ kind: "table-data", origin, values });
          switchToKind("univer");
        });
        row.appendChild(sheetBtn);
      }

      if (hasPlotTab) {
        const plotBtn = document.createElement("button");
        plotBtn.type = "button";
        plotBtn.className = "sy-mdview-table-linkout";
        plotBtn.textContent = "↗ Plot";
        plotBtn.title = "Ask the agent to author Vega-Lite plots from this table";
        plotBtn.addEventListener("click", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          const values = parseTableValues(table);
          if (values.length === 0) return;
          plotBtn.disabled = true;
          (async () => {
            // Existence check — skip the agent run if this table
            // already has plots tagged with the same origin. The
            // Plot tab's "Regenerate with edits…" right-click item
            // is the path for asking for changes.
            try {
              const list = await fetch("/api/plots").then((r) =>
                r.ok ? r.json() : null,
              );
              const matches = (list?.plots ?? []).filter(
                (p: { origin?: string }) => p.origin === origin,
              );
              if (matches.length > 0) {
                switchToKind("vega");
                return;
              }
            } catch { /* fall through to generate */ }
            try {
              const body = await fetch("/api/plots/from-table", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ origin, values }),
              }).then((r) => r.json());
              if (body && body.run_id) {
                window.dispatchEvent(new CustomEvent("sy:rail-system-tip", {
                  detail: {
                    text:
                      `Plotting from \`${origin}\` — the agent is `
                      + `authoring 2-4 Vega-Lite plots from the table. `
                      + `Watch them land in the Plot tab, or open the `
                      + `Agents tab to follow the transcript (run `
                      + `\`${body.run_id}\`).`,
                    focus: false,
                  },
                }));
                switchToKind("vega");
              } else {
                console.warn("Editor: from-table failed", body);
              }
            } catch (e) {
              console.warn("Editor: from-table crashed", e);
            }
          })().finally(() => { plotBtn.disabled = false; });
        });
        row.appendChild(plotBtn);
      }

      // Place the button row as a sibling immediately before the
      // table so it sits in the document flow without disturbing
      // layout.
      table.parentNode?.insertBefore(row, table);
    });
  }, [previewHtml, hasSheetTab, hasPlotTab, path, setSelection, switchToKind]);

  // Wiki markdown pages flow through /api/page (handles graph
  // rebuild on save). Any other in-workspace text file uses
  // /api/file — no graph rebuild but full read/write support.
  //
  // File browser reuses selection.kind "page" for code files too
  // (slideshows/…/deck.json, scripts, …). Only actual .md that
  // looks like a wiki page must hit /api/page — otherwise the
  // page endpoint returns "invalid path".
  const isMarkdownPage = (() => {
    if (!path || !path.endsWith(".md")) return false;
    // Explicit non-wiki trees never go through the wiki page API.
    if (
      path.startsWith("slideshows/")
      || path.startsWith("decks/")
      || path.startsWith("vault/")
      || path.startsWith("figures/")
    ) {
      return false;
    }
    if (path.startsWith("wiki/")) return true;
    // Graph / wiki sidebar: bare slug.md or concepts/foo.md with
    // kind "page" (path relative to wiki/, without the wiki/ prefix).
    if (selection?.kind === "page") return true;
    if (!path.includes("/")) return true;
    return false;
  })();

  useEffect(() => {
    if (!path) {
      setState({ kind: "idle" });
      return;
    }
    let cancelled = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    setState({ kind: "loading" });
    const url = isMarkdownPage
      ? `/api/page?path=${encodeURIComponent(path)}`
      : `/api/file?path=${encodeURIComponent(path)}`;
    const load = () => {
      fetch(url)
        .then(async (r) => {
          const body = (await r.json().catch(() => ({}))) as {
            content?: string; text?: string; error?: string;
            syncing?: boolean; service?: string | null;
          };
          // 202 + {syncing} — the daemon is pulling the file down from
          // the sync service. Show an honest state and poll, rather
          // than blocking on a read that could take tens of seconds.
          if (r.status === 202 && body.syncing) {
            if (!cancelled) {
              setState({ kind: "syncing", service: body.service ?? null });
              retry = setTimeout(load, 1500);
            }
            return;
          }
          if (!r.ok) throw new Error(body.error ?? `HTTP ${r.status}`);
          const content = body.content ?? body.text ?? "";
          if (!cancelled) setState({ kind: "ready", original: content, draft: content });
        })
        .catch((e: Error) => {
          if (!cancelled) setState({ kind: "error", message: e.message });
        });
    };
    load();
    return () => {
      cancelled = true;
      if (retry) clearTimeout(retry);
    };
  }, [path, isMarkdownPage]);

  const onSave = async () => {
    if (state.kind !== "ready" || !path) return;
    setState({ kind: "saving", original: state.original, draft: state.draft });
    try {
      const url = isMarkdownPage ? "/api/page" : "/api/file";
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, content: state.draft }),
      });
      if (!r.ok) {
        const body = (await r.json().catch(() => ({}))) as { error?: string };
        throw new Error(body.error ?? `HTTP ${r.status}`);
      }
      // Re-load to confirm what was written and reset the dirty flag.
      const rereadUrl = isMarkdownPage
        ? `/api/page?path=${encodeURIComponent(path)}`
        : `/api/file?path=${encodeURIComponent(path)}`;
      const reread = await fetch(rereadUrl);
      const body = await reread.json() as { content?: string; text?: string };
      const content = body.content ?? body.text ?? "";
      setState({ kind: "ready", original: content, draft: content });
    } catch (e) {
      setState({ kind: "error", message: (e as Error).message });
    }
  };

  // Reset the language override when the active file changes; the
  // toolbar selector is sticky-per-file, not per-session. Must run
  // on every render so the hook order stays stable across the
  // empty / loading / error / ready branches below — moving this
  // after the early returns gave us hooks-count mismatches and a
  // blank-page crash the first time path changed.
  useEffect(() => { setLangOverride(null); }, [path]);

  const detectedLanguage: CodeLanguage = useMemo(() => (
    path ? detectLanguage(path, draft || original) : "plain"
  ), [path, draft, original]);
  const activeLanguage: CodeLanguage = langOverride ?? detectedLanguage;

  if (!path) {
    return (
      <div className="sy-editor sy-editor--empty">
        <p>Pick a page in the BROWSER (or click a node in the Graph tab) to edit it.</p>
      </div>
    );
  }
  // `idle` happens for one render after `path` flips set — useEffect
  // hasn't transitioned us into `loading` yet. Treat both as loading.
  if (state.kind === "idle" || state.kind === "loading") {
    return <div className="sy-editor sy-editor--empty"><p>Loading {path}…</p></div>;
  }
  if (state.kind === "syncing") {
    return (
      <div className="sy-editor sy-editor--empty">
        <p>
          Downloading {path} from {state.service ?? "the cloud"}…
        </p>
        <p style={{ color: "var(--type-fact)", fontSize: "0.85em" }}>
          This file isn't stored locally yet. The rest of switchbay
          stays responsive while it downloads.
        </p>
      </div>
    );
  }
  if (state.kind === "error") {
    return (
      <div className="sy-editor sy-editor--empty">
        <p style={{ color: "var(--type-fact)" }}>error: {state.message}</p>
      </div>
    );
  }

  // `state` is now ready | saving — both carry original + draft.
  const dirty = draft !== original;
  const isSaving = state.kind === "saving";
  const propRows = Object.entries(properties);
  const title = typeof properties.title === "string" ? properties.title : path;

  return (
    <div className="sy-editor">
      <header className="sy-editor-head">
        <span className="sy-editor-path" title={path}>{path}</span>
        <span className="sy-editor-spacer" />
        {hasProjectsTab && projectBackLink && (
          <button
            type="button"
            className="sy-editor-btn sy-editor-btn--back"
            onClick={() => {
              switchToKind("projects");
              // Defer the focus event so it lands after the tab
              // has actually mounted — the Projects tab listens
              // and then expands + scrolls the row into view.
              window.setTimeout(() => {
                window.dispatchEvent(new CustomEvent("sy:focus-project", {
                  detail: {
                    project: projectBackLink.project,
                    path: projectBackLink.path,
                  },
                }));
              }, 0);
            }}
            title={`Back to the “${projectBackLink.project}” project`}
          >
            ← Project
          </button>
        )}
        {hasGraphTab && (
          <button
            type="button"
            className="sy-editor-btn"
            onClick={() => switchToKind("graph")}
            title="Open the current selection in the Graph tab"
          >
            ↗ Graph
          </button>
        )}
        {hasSketchTab && path && (
          <button
            type="button"
            className="sy-editor-btn"
            disabled={creatingSketchDeck}
            aria-busy={creatingSketchDeck}
            onClick={async () => {
              // Scaffold a Sketch (Excalidraw) deck from this doc's
              // H1/H2 headings and route into the Sketch tab; the
              // autopopulate agent fills the scenes from prose.
              if (creatingSketchDeck) return;
              setCreatingSketchDeck(true);
              try {
                const r = await fetch("/api/analysis/from-doc", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ path }),
                });
                if (!r.ok) {
                  window.alert(`Sketch deck scaffold failed: HTTP ${r.status}`);
                  return;
                }
                const j = (await r.json()) as {
                  analysis: { slug: string; path: string; title: string };
                };
                setSelection({
                  kind: "page",
                  id: j.analysis.path,
                  path: j.analysis.path,
                });
                switchToKind("sketch");
                try {
                  const pop = await fetch("/api/analysis/populate", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ analysis_path: j.analysis.path }),
                  });
                  if (pop.ok) {
                    const pj = await pop.json() as { run_id?: string };
                    if (pj.run_id) setDeckRun(j.analysis.path, pj.run_id);
                  }
                } catch { /* swallowed — deck created either way */ }
              } catch (e) {
                window.alert(`Sketch deck scaffold failed: ${(e as Error).message}`);
              } finally {
                setCreatingSketchDeck(false);
              }
            }}
            title={
              creatingSketchDeck
                ? "Scaffolding the sketch deck — please wait"
                : "Scaffold a Sketch (Excalidraw) deck from this doc's headings"
            }
          >
            {creatingSketchDeck ? "creating…" : "→ Sketch deck"}
          </button>
        )}
        <button
          type="button"
          className="sy-editor-btn"
          onClick={() =>
            setState({ kind: "ready", original, draft: original })
          }
          disabled={!dirty || isSaving}
        >
          Revert
        </button>
        <button
          type="button"
          className="sy-editor-btn sy-editor-btn--primary"
          onClick={onSave}
          disabled={!dirty || isSaving}
        >
          {isSaving ? "Saving…" : "Save"}
        </button>
      </header>
      {!isMarkdownPage && (
        <div className="sy-editor-codebar">
          <span className="sy-editor-codebar-label">language</span>
          <select
            className="sy-editor-codebar-select"
            value={activeLanguage}
            onChange={(e) => setLangOverride(e.target.value as CodeLanguage)}
            title={`Auto-detected: ${detectedLanguage}. Pick another to override.`}
            disabled={isSaving}
          >
            {LANGUAGE_CHOICES.map((l) => (
              <option key={l} value={l}>
                {l}{l === detectedLanguage ? " (auto)" : ""}
              </option>
            ))}
          </select>
        </div>
      )}
      <div
        className={
          "sy-editor-split"
          + (!isMarkdownPage ? " sy-editor-split--code" : "")
        }
      >
        {!isMarkdownPage ? (
          <CodeView
            value={draft}
            language={activeLanguage}
            onChange={(next) => setState({ kind: "ready", original, draft: next })}
            readOnly={isSaving}
          />
        ) : (
          <>
            {viewMode !== "rendered" && (
              <textarea
                ref={sourceRef}
                className="sy-editor-source"
                value={draft}
                spellCheck={false}
                disabled={isSaving}
                onChange={(ev) =>
                  setState({ kind: "ready", original, draft: ev.target.value })
                }
                onClick={() => syncPreviewToSource(sourceRef.current, previewRef.current)}
                onKeyUp={(ev) => {
                  // Sync only on cursor-moving keys; typing already updates draft.
                  if (
                    ev.key === "ArrowUp" || ev.key === "ArrowDown" ||
                    ev.key === "PageUp" || ev.key === "PageDown" ||
                    ev.key === "Home" || ev.key === "End"
                  ) {
                    syncPreviewToSource(sourceRef.current, previewRef.current);
                  }
                }}
              />
            )}
            {/* Pane divider with the view-mode chevron handle, centred
                on the bar (same spot as Zen's resize grip). Each arrow
                EXPANDS the pane it points toward — ‹ grows the rendered
                (right) pane, › grows the raw (left) pane — like dragging
                the divider that way; disabled at each extreme. */}
            <div
              className={"sy-editor-divider sy-editor-divider--" + viewMode}
              role="separator"
              aria-orientation="vertical"
            >
              <div className="sy-editor-viewtoggle" role="group" aria-label="Editor view">
                <button
                  type="button"
                  className="sy-editor-view-chev"
                  onClick={() => stepView(1)}
                  disabled={vIdx === VIEW_ORDER.length - 1}
                  title={viewMode === "raw" ? "Split view" : "Rendered only"}
                  aria-label={viewMode === "raw" ? "Split view" : "Rendered only"}
                >
                  ‹
                </button>
                <button
                  type="button"
                  className="sy-editor-view-chev"
                  onClick={() => stepView(-1)}
                  disabled={vIdx === 0}
                  title={viewMode === "rendered" ? "Split view" : "Raw only"}
                  aria-label={viewMode === "rendered" ? "Split view" : "Raw only"}
                >
                  ›
                </button>
              </div>
            </div>
            {viewMode !== "raw" && (
              <div
                ref={previewRef}
                className="sy-editor-preview"
                onClick={(ev) =>
                  syncSourceToPreview(ev, sourceRef.current, previewRef.current)
                }
              >
                <h1 className="sy-mdview-title">{title}</h1>
                {typeof properties.extracted_from === "string" && properties.extracted_from && (
                  <ProvenanceChip source={properties.extracted_from} pageHtml={previewHtml} />
                )}
                {propRows.length > 0 && (
                  <section className="properties">
                    <div className="properties-head">Properties</div>
                    <table className="sy-mdview-properties">
                      <tbody>
                        {propRows.map(([k, v]) => (
                          <tr key={k}>
                            <td className="prop-key">{k}</td>
                            <td className="prop-val">
                              {isCollapsibleList(k, v)
                                ? <CollapsibleSources items={v.map(String)} />
                                : Array.isArray(v)
                                  ? v.map((item, i) => <div key={i}>{item}</div>)
                                  : v}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </section>
                )}
                <article className="sy-mdview" dangerouslySetInnerHTML={{ __html: previewHtml }} />
                {graphData && pageId && graphData.pages?.[pageId] && (
                  <MiniGraph data={graphData} centerId={pageId} centerPath={path ?? ""} />
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function CollapsibleSources({ items }: { items: string[] }) {
  const [open, setOpen] = useState(readSourcesOpen);
  return (
    <details
      className="sy-prop-list"
      open={open}
      onToggle={(ev) => {
        const next = ev.currentTarget.open;
        setOpen(next);
        writeSourcesOpen(next);
      }}
    >
      <summary>{items.length} sources</summary>
      {items.map((item, i) => <div key={i}>{item}</div>)}
    </details>
  );
}

/** Provenance chip (D5): shown when the page's frontmatter carries
 *  `extracted_from`. Says where the page came from and offers "open
 *  original" (+ "re-extract" and a side-by-side "compare" trust view
 *  for in-workspace originals — the ingest agent and the raw-file
 *  endpoint are workspace-scoped, so external files can only be
 *  opened, not re-read). URLs (comms-stream deep links) open in a
 *  new tab. */
function ProvenanceChip({ source, pageHtml }: { source: string; pageHtml?: string }) {
  const [busy, setBusy] = useState(false);
  const [comparing, setComparing] = useState(false);
  const isUrl = /^https?:\/\//.test(source);
  const isExternal = !isUrl && (source.startsWith("/") || source.startsWith("~"));
  const isInternal = !isUrl && !isExternal;
  const shortName = isUrl
    ? source.replace(/^https?:\/\//, "").slice(0, 60)
    : source.split("/").pop() ?? source;

  const openOriginal = async () => {
    if (isUrl) {
      window.open(source, "_blank", "noopener");
      return;
    }
    const endpoint = isInternal ? "/api/fs/open-external" : "/api/sources/open";
    try {
      const r = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: source }),
      });
      if (!r.ok) {
        const b = await r.json().catch(() => ({} as { error?: string }));
        window.alert(`Couldn't open the original: ${b.error ?? r.status}`);
      }
    } catch (e) {
      window.alert(`Couldn't open the original: ${(e as Error).message}`);
    }
  };

  const reExtract = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await fetch("/api/ingest/from-path", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: source }),
      });
      if (!r.ok) {
        const b = await r.json().catch(() => ({} as { error?: string }));
        window.alert(`Re-extract failed: ${b.error ?? r.status}`);
        return;
      }
      const b = (await r.json()) as { run_id?: string };
      if (b.run_id) {
        window.dispatchEvent(new CustomEvent("sy:open-agents-run", {
          detail: { run_id: b.run_id },
        }));
      }
    } catch (e) {
      window.alert(`Re-extract failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sy-prov-chip" title={source}>
      <span className="sy-prov-chip-label">
        from <code>{shortName}</code>
      </span>
      <button
        type="button"
        className="sy-prov-chip-btn"
        onClick={() => void openOriginal()}
        title={isUrl ? "Open the source link" : "Open the original with the system default app"}
      >
        {isUrl ? "open link ↗" : "open original"}
      </button>
      {isInternal && (
        <button
          type="button"
          className="sy-prov-chip-btn"
          disabled={busy}
          onClick={() => void reExtract()}
          title="Dispatch a fresh ingest agent against the original (watch it in Agents)"
        >
          {busy ? "re-extracting…" : "re-extract"}
        </button>
      )}
      {isInternal && pageHtml !== undefined && (
        <button
          type="button"
          className="sy-prov-chip-btn"
          onClick={() => setComparing(true)}
          title="Side-by-side: the original next to what was extracted from it"
        >
          ⇆ compare
        </button>
      )}
      {comparing && (
        <TrustCompare
          source={source}
          pageHtml={pageHtml ?? ""}
          onClose={() => setComparing(false)}
          onOpenOriginal={() => void openOriginal()}
        />
      )}
    </div>
  );
}


/** Source-vs-extraction trust view (D5): the original file rendered
 *  beside the extracted page, so a first ingest can be eyeballed —
 *  "did it actually capture my document?". In-workspace originals
 *  only (fetched via the workspace-scoped raw endpoint); text and
 *  images render inline, other binaries get an honest note + the
 *  open-original hand-off. */
function TrustCompare({
  source, pageHtml, onClose, onOpenOriginal,
}: {
  source: string;
  pageHtml: string;
  onClose: () => void;
  onOpenOriginal: () => void;
}) {
  const [original, setOriginal] = useState<
    | { kind: "loading" }
    | { kind: "text"; text: string }
    | { kind: "image"; url: string }
    | { kind: "binary" }
    | { kind: "error"; message: string }
  >({ kind: "loading" });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    const lower = source.toLowerCase();
    const url = `/api/fs/raw?path=${encodeURIComponent(source)}`;
    const IMAGE = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"];
    const TEXT = [
      ".md", ".txt", ".csv", ".tsv", ".json", ".jsonl", ".log",
      ".py", ".js", ".ts", ".html", ".htm", ".css", ".xml",
      ".yaml", ".yml", ".toml", ".ini", ".sh",
    ];
    if (IMAGE.some((e) => lower.endsWith(e))) {
      setOriginal({ kind: "image", url });
      return;
    }
    if (!TEXT.some((e) => lower.endsWith(e))) {
      setOriginal({ kind: "binary" });
      return;
    }
    void (async () => {
      try {
        const r = await fetch(url);
        if (!r.ok) {
          if (!cancelled) setOriginal({ kind: "error", message: `HTTP ${r.status}` });
          return;
        }
        const text = await r.text();
        if (!cancelled) {
          setOriginal({
            kind: "text",
            text: text.length > 200_000 ? text.slice(0, 200_000) + "\n… (truncated)" : text,
          });
        }
      } catch (e) {
        if (!cancelled) setOriginal({ kind: "error", message: (e as Error).message });
      }
    })();
    return () => { cancelled = true; };
  }, [source]);

  const name = source.split("/").pop() ?? source;
  return (
    <div className="sy-confirm-backdrop" onClick={onClose}>
      <div className="sy-trust" role="dialog" aria-label="Compare source and extraction" onClick={(e) => e.stopPropagation()}>
        <div className="sy-trust-head">
          <span>original ⇆ extraction</span>
          <span style={{ flex: 1 }} />
          <button type="button" className="sy-prov-chip-btn" onClick={onOpenOriginal}>
            open original
          </button>
          <button type="button" className="sy-prov-chip-btn" onClick={onClose}>
            close
          </button>
        </div>
        <div className="sy-trust-panes">
          <div className="sy-trust-pane">
            <div className="sy-trust-pane-head" title={source}>{name}</div>
            {original.kind === "loading" && <div className="sy-trust-note">loading…</div>}
            {original.kind === "error" && (
              <div className="sy-trust-note">couldn't load the original: {original.message}</div>
            )}
            {original.kind === "binary" && (
              <div className="sy-trust-note">
                Binary file — no inline preview. Use “open original” to view
                it in its own app and compare by eye.
              </div>
            )}
            {original.kind === "image" && (
              <img className="sy-trust-img" src={original.url} alt={name} />
            )}
            {original.kind === "text" && (
              <pre className="sy-trust-pre">{original.text}</pre>
            )}
          </div>
          <div className="sy-trust-pane">
            <div className="sy-trust-pane-head">extracted page</div>
            <article
              className="sy-mdview sy-trust-md"
              dangerouslySetInnerHTML={{ __html: pageHtml }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

/** Click in the source — scroll the preview to the matching fraction
 *  of its scrollable height so the line under the cursor is roughly
 *  centred. Markdown line ↔ rendered offset isn't 1:1, so we use the
 *  cursor's position as a fraction of the source. */
function syncPreviewToSource(
  src: HTMLTextAreaElement | null,
  pre: HTMLDivElement | null,
) {
  if (!src || !pre) return;
  const text = src.value;
  if (!text) return;
  const cursor = src.selectionStart ?? 0;
  // Use lines, not chars, so long-line documents don't bias toward the start.
  const linesBefore = countLineBreaks(text, 0, cursor);
  const totalLines = countLineBreaks(text, 0, text.length) + 1;
  const frac = totalLines > 1 ? linesBefore / (totalLines - 1) : 0;
  const preTravel = Math.max(0, pre.scrollHeight - pre.clientHeight);
  const target = frac * preTravel;
  // Centre-ish: subtract a third of the viewport so the matched line
  // sits in the upper-middle, not flush at the top.
  pre.scrollTo({ top: Math.max(0, target - pre.clientHeight / 3), behavior: "smooth" });
}

/** Click in the preview — find the closest block-level element, walk
 *  back from the click position to the previous sentence boundary, and
 *  search the source for that snippet. Drops the cursor at the match. */
function syncSourceToPreview(
  ev: React.MouseEvent<HTMLDivElement>,
  src: HTMLTextAreaElement | null,
  _pre: HTMLDivElement | null,
) {
  if (!src) return;
  const target = ev.target as HTMLElement;
  // HTML slideshow links open the Slideshow tab (not Sketch decks).
  const showAnchor = target.closest(
    "a.wikilink--slideshow, a[data-slideshow-slug], a[href^='#slideshow=']",
  ) as HTMLAnchorElement | null;
  if (showAnchor) {
    const href = showAnchor.getAttribute("href") || "";
    const m = href.match(/^#slideshow=(.+)$/);
    const showSlug =
      showAnchor.getAttribute("data-slideshow-slug") || (m ? m[1] : null);
    if (showSlug) {
      ev.preventDefault();
      ev.stopPropagation();
      const slug = decodeURIComponent(showSlug);
      notifyHtmlDeckOpen(slug);
      void fetch("/api/slideshows/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug }),
      }).catch(() => { /* daemon offline */ });
      return;
    }
  }
  const repAnchor = target.closest(
    "a.wikilink--report, a[data-report-slug], a[href^='#report=']",
  ) as HTMLAnchorElement | null;
  if (repAnchor) {
    const href = repAnchor.getAttribute("href") || "";
    const m = href.match(/^#report=(.+)$/);
    const slugRaw =
      repAnchor.getAttribute("data-report-slug") || (m ? m[1] : null);
    if (slugRaw) {
      ev.preventDefault();
      ev.stopPropagation();
      const slug = decodeURIComponent(slugRaw);
      void import("../library/reportDocOpen").then(({ notifyReportDocOpen }) => {
        notifyReportDocOpen(slug);
      });
      void fetch("/api/report-packages/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug }),
      }).catch(() => {});
      return;
    }
  }
  const wsAnchor = target.closest(
    "a.wikilink--worksheet, a[data-worksheet-slug], a[href^='#worksheet=']",
  ) as HTMLAnchorElement | null;
  if (wsAnchor) {
    const href = wsAnchor.getAttribute("href") || "";
    const m = href.match(/^#worksheet=(.+)$/);
    const slugRaw =
      wsAnchor.getAttribute("data-worksheet-slug") || (m ? m[1] : null);
    if (slugRaw) {
      ev.preventDefault();
      ev.stopPropagation();
      const slug = decodeURIComponent(slugRaw);
      void fetch("/api/worksheets/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug }),
      }).catch(() => {});
      return;
    }
  }
  if (target.tagName === "A") return;  // other wikilinks navigate normally
  const block = target.closest<HTMLElement>(
    "h1, h2, h3, h4, h5, h6, p, li, pre, blockquote, table, hr",
  );
  if (!block || !block.closest(".sy-mdview")) return;
  const text = src.value;

  const snippet = sentenceSnippet(block, ev.clientX, ev.clientY);
  if (!snippet) return;
  const offset = findOffsetForSnippet(text, snippet);
  if (offset < 0) return;
  src.focus();
  src.setSelectionRange(offset, offset);
  const linesBefore = (text.slice(0, offset).match(/\n/g) ?? []).length;
  const totalLines = (text.match(/\n/g) ?? []).length + 1;
  const lineH = src.scrollHeight / Math.max(1, totalLines);
  src.scrollTop = Math.max(0, linesBefore * lineH - src.clientHeight / 3);
}

/** Return the index within `block.textContent` corresponding to the
 *  caret position at (x, y). -1 if outside any text node. Cross-browser
 *  via caretRangeFromPoint (WebKit/Blink) and caretPositionFromPoint
 *  (Firefox). */
function caretIndexInBlock(block: HTMLElement, x: number, y: number): number {
  type Caret = { node: Text; offset: number } | null;
  let caret: Caret = null;
  const docAny = document as unknown as {
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
  };
  if (docAny.caretRangeFromPoint) {
    const r = docAny.caretRangeFromPoint(x, y);
    if (r && r.startContainer.nodeType === Node.TEXT_NODE) {
      caret = { node: r.startContainer as Text, offset: r.startOffset };
    }
  } else if (docAny.caretPositionFromPoint) {
    const p = docAny.caretPositionFromPoint(x, y);
    if (p && p.offsetNode.nodeType === Node.TEXT_NODE) {
      caret = { node: p.offsetNode as Text, offset: p.offset };
    }
  }
  if (!caret) return -1;
  const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
  let acc = 0;
  let n: Node | null;
  while ((n = walker.nextNode())) {
    if (n === caret.node) return acc + caret.offset;
    acc += (n.textContent ?? "").length;
  }
  return -1;
}

/** Walk back from the clicked character to the start of the current
 *  sentence (or the block start), then return up to ~60 chars from
 *  there as the search snippet. */
function sentenceSnippet(block: HTMLElement, x: number, y: number): string {
  const fullText = block.textContent ?? "";
  if (!fullText) return "";
  const clickIdx = caretIndexInBlock(block, x, y);
  const cap = clickIdx >= 0 ? Math.min(clickIdx, fullText.length) : 0;
  // Sentence boundaries: . ! ? followed by whitespace, or a newline.
  const before = fullText.slice(0, cap);
  const re = /[.!?]\s+|\n/g;
  let start = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(before)) !== null) {
    start = m.index + m[0].length;
  }
  return fullText.slice(start).trim().slice(0, 60);
}

/** Find the offset of `snippet` in `text`, tolerating the markdown
 *  source's syntax noise (wikilinks render as plain text in the
 *  preview, etc.). Tries the snippet at successively shorter lengths. */
function findOffsetForSnippet(text: string, snippet: string): number {
  const haystack = text.replace(/\s+/g, " ");
  const needleFull = snippet.replace(/\s+/g, " ").trim();
  if (!needleFull) return -1;
  for (const len of [60, 40, 20, 10]) {
    const needle = needleFull.slice(0, len);
    const hit = haystack.indexOf(needle);
    if (hit >= 0) return mapCollapsedToOriginal(text, hit);
  }
  return -1;
}

function mapCollapsedToOriginal(orig: string, collapsedIdx: number): number {
  let i = 0;
  let j = 0;
  while (i < orig.length && j < collapsedIdx) {
    const c = orig.charCodeAt(i);
    const isSpace = c === 32 || c === 9 || c === 10 || c === 13;
    if (isSpace) {
      // Consume run of whitespace in orig, count it as one space in collapsed.
      while (i < orig.length) {
        const cc = orig.charCodeAt(i);
        if (cc !== 32 && cc !== 9 && cc !== 10 && cc !== 13) break;
        i++;
      }
      j++;
    } else {
      i++;
      j++;
    }
  }
  return Math.min(i, orig.length);
}

function countLineBreaks(s: string, start: number, end: number): number {
  let n = 0;
  for (let i = start; i < end; i++) if (s.charCodeAt(i) === 10) n++;
  return n;
}

/** Walk a rendered <table>'s thead/tbody and return rows as a 2D
 *  array of cell text. Header cells are returned as a single first
 *  row so the Sheet tab's setValues lays out a normal spreadsheet. */
function parseTableValues(table: HTMLTableElement): (string | number | null)[][] {
  const rows: (string | number | null)[][] = [];
  const headRow = table.tHead?.rows?.[0];
  if (headRow) {
    const cells: (string | number | null)[] = [];
    for (const cell of Array.from(headRow.cells)) {
      cells.push((cell.textContent ?? "").trim());
    }
    rows.push(cells);
  }
  for (const tbody of Array.from(table.tBodies)) {
    for (const tr of Array.from(tbody.rows)) {
      const cells: (string | number | null)[] = [];
      for (const cell of Array.from(tr.cells)) {
        const text = (cell.textContent ?? "").trim();
        // Coerce digit-shaped cells to numbers so the Sheet treats
        // them as numeric (formulas etc. work). Anything else stays
        // as string.
        if (/^-?\d+(?:\.\d+)?$/.test(text)) {
          rows.push.length;  // no-op to keep tsc happy about the cast
          cells.push(Number(text));
        } else {
          cells.push(text);
        }
      }
      rows.push(cells);
    }
  }
  return rows;
}
