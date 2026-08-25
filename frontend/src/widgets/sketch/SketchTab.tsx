import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSelection } from "../../selection/SelectionContext";
import { ackUiCommand, takeSketchShow } from "../../lib/pendingUiCommands";

/**
 * Sketch tab — Excalidraw + drawio on the same canvas area, with a
 * library picker over every workspace sketch. PNG exports auto-write
 * to `wiki/figures/`.
 *
 * Presentations are HTML slideshows (`slideshows/<slug>/`, Slideshow
 * tab). This surface is diagrams and whiteboards only. Legacy
 * `kind: deck` wiki pages stay on disk; their member sketches remain
 * ordinary library items.
 *
 * Persistence: backend `src/switchbay/sketches.py` stores
 * `<workspace>/.workbench/sketches/<id>.json` and writes the PNG
 * export alongside at `wiki/figures/_assets/<id>.png` on every save
 * (legacy root `figures/` still served for pre-migration workspaces).
 *
 * Excalidraw runs as a React component (lazy-imported). drawio runs in
 * an iframe pointed at `https://embed.diagrams.net/` with the JSON
 * protocol; saves and exports come back as postMessage events.
 */

type SketchKind = "excalidraw" | "drawio";

type SketchMeta = {
  id: string;
  name: string;
  kind: SketchKind;
  created_at?: number;
  updated_at?: number;
  has_png?: boolean;
};

type Sketch = SketchMeta & {
  data: unknown;
};

type ExcalidrawAPI = {
  getSceneElements: () => readonly unknown[];
  getAppState: () => Record<string, unknown>;
  getFiles: () => Record<string, unknown>;
};

// 5 s is the minimum delay the user asked for: long enough that
// Cmd-Z still has time to undo a mistake before the disk takes it,
// short enough that you don't lose more than ~5 s of work to a crash.
const AUTOSAVE_MS = 5000;
const DRAWIO_ORIGIN = "https://embed.diagrams.net";
// Embed flags: ui=min collapses chrome to keep our toolbar canonical;
// proto=json picks the postMessage protocol; spin keeps the loader
// visible until we feed initial XML; saveAndExit shows a Save button
// even though we drive saves on a timer.
const DRAWIO_URL =
  `${DRAWIO_ORIGIN}/?embed=1&proto=json&ui=min&spin=1&saveAndExit=0&libraries=1`;

export default function SketchTab() {
  const { selection, setSelection } = useSelection();
  const [sketches, setSketches] = useState<SketchMeta[] | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [active, setActive] = useState<Sketch | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [creating, setCreating] = useState<{ name: string; kind: SketchKind } | null>(null);
  // Bumped on Clear to force the canvas component to re-mount with
  // the fresh empty scene. Excalidraw's `initialData` is only read
  // on first render so we key the canvas by `${id}:${clearVersion}`.
  const [clearVersion, setClearVersion] = useState(0);
  // Inline rename — same UX as Vega's title input. `null` = static
  // span; non-null = textbox open with this draft value.
  const [nameDraft, setNameDraft] = useState<string | null>(null);

  const reloadList = useCallback(async () => {
    try {
      const r = await fetch("/api/sketches");
      if (!r.ok) { setListError(`HTTP ${r.status}`); return; }
      const body = (await r.json()) as { sketches: SketchMeta[] };
      setSketches(body.sketches);
      setListError(null);
    } catch (e) { setListError((e as Error).message); }
  }, []);

  useEffect(() => { void reloadList(); }, [reloadList]);

  // Selection → active sketch. Page selections (including leftover
  // kind: deck wiki pages) no longer enter a sketch-deck mode.
  useEffect(() => {
    if (selection?.kind === "sketch") {
      setActiveId(selection.id);
      return;
    }
    if (!sketches) return;
    if (sketches.length === 0) { setActiveId(null); return; }
    setActiveId((cur) => {
      if (cur && sketches.some((s) => s.id === cur)) return cur;
      return sketches[0]!.id;
    });
  }, [sketches, selection]);

  // PNG render-on-demand → CANONICAL Excalidraw export.
  //
  // `author_sketch` writes an immediate Pillow preview. That preview
  // uses a system sans and can tofu Unicode (e.g. →). The Sketch
  // canvas (Virgil) looks fine. We therefore re-export every
  // non-empty Excalidraw scene once per tab session with exportToBlob
  // and OVERWRITE the Pillow PNG — even when has_png is already true.
  const exportedPngRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!sketches) return;
    const pending: SketchMeta[] = [];
    for (const s of sketches) {
      if (s.kind !== "excalidraw") continue;
      if (exportedPngRef.current.has(s.id)) continue;
      pending.push(s);
    }
    if (pending.length === 0) return;
    let cancelled = false;
    (async () => {
      const mod = await import("@excalidraw/excalidraw");
      const exportToBlob = mod.exportToBlob as (args: Record<string, unknown>) => Promise<Blob>;
      let wrote = 0;
      for (const meta of pending) {
        if (cancelled) return;
        exportedPngRef.current.add(meta.id);
        try {
          const r = await fetch(`/api/sketch?id=${encodeURIComponent(meta.id)}`);
          if (!r.ok) continue;
          const body = (await r.json()) as { sketch: Sketch };
          const data = body.sketch.data as Record<string, unknown>;
          const elements = (data.elements as unknown[]) || [];
          if (!Array.isArray(elements) || elements.length === 0) {
            continue;
          }
          const blob = await exportToBlob({
            elements,
            appState: data.appState || {},
            files: data.files || {},
            mimeType: "image/png",
            exportPadding: 16,
          });
          const png_b64 = await blobToBase64(blob);
          const pr = await fetch("/api/sketch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              id: body.sketch.id,
              name: body.sketch.name,
              kind: body.sketch.kind,
              data: body.sketch.data,
              png_b64,
            }),
          });
          if (pr.ok) wrote += 1;
        } catch {
          exportedPngRef.current.delete(meta.id);
        }
      }
      if (!cancelled && wrote > 0) await reloadList();
    })();
    return () => { cancelled = true; };
  }, [sketches, reloadList]);

  const librarySketches: SketchMeta[] = useMemo(
    () => sketches ?? [],
    [sketches],
  );

  // Bumped when an agent re-authors the same sketch so we re-fetch
  // even if activeId didn't change.
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!activeId) { setActive(null); return; }
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`/api/sketch?id=${encodeURIComponent(activeId)}`);
        if (!r.ok) return;
        const body = (await r.json()) as { sketch: Sketch };
        if (!cancelled) setActive(body.sketch);
      } catch { /* swallow */ }
    })();
    return () => { cancelled = true; };
  }, [activeId, reloadToken]);

  // Publish visible sketch focus for sketch_context / author_sketch.
  const lastSketchFocusRef = useRef("");
  useEffect(() => {
    if (!activeId) return;
    const payload = {
      surface: "sketch",
      sketch_id: activeId,
      name: active?.name || activeId,
      kind: active?.kind || "excalidraw",
      slide_index: null,
      deck_title: null,
      analysis_path: null,
      deck_len: null,
    };
    const serialised = JSON.stringify(payload);
    if (serialised === lastSketchFocusRef.current) return;
    lastSketchFocusRef.current = serialised;
    void fetch("/api/ui/focus", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: serialised,
    }).catch(() => { /* ignore */ });
  }, [activeId, active]);

  // Agent sketch_show / author_sketch nudge (+ cold-mount stash).
  useEffect(() => {
    const applyShow = (d: {
      sketch_id?: string | null;
      slide_index?: number | null;
    }) => {
      if (typeof d.slide_index === "number" && librarySketches.length) {
        const id = librarySketches[d.slide_index]?.id;
        if (id) {
          setActiveId(id);
          setReloadToken((t) => t + 1);
          return;
        }
      }
      if (d.sketch_id) {
        setActiveId(d.sketch_id);
        setReloadToken((t) => t + 1);
        void fetch("/api/sketches")
          .then((r) => r.json())
          .then((body: { sketches?: SketchMeta[] }) => {
            if (Array.isArray(body.sketches)) setSketches(body.sketches);
          })
          .catch(() => { /* ignore */ });
      }
    };
    const onShow = (ev: Event) => {
      const detail = (ev as CustomEvent<{
        sketch_id?: string | null;
        slide_index?: number | null;
        command_id?: string;
      }>).detail || {};
      applyShow(detail);
      if (detail.command_id) {
        void ackUiCommand({
          command_id: detail.command_id,
          ok: true,
          surface: "sketch",
          applied: true,
          label: detail.sketch_id || undefined,
        });
      }
    };
    window.addEventListener("sy:sketch-show", onShow);
    const stashed = takeSketchShow();
    if (stashed) {
      applyShow(stashed);
      if (stashed.command_id) {
        void ackUiCommand({
          command_id: stashed.command_id,
          ok: true,
          surface: "sketch",
          applied: true,
          label: stashed.sketch_id || undefined,
        });
      }
    }
    return () => window.removeEventListener("sy:sketch-show", onShow);
  }, [librarySketches]);

  const idx = useMemo(() => {
    if (!librarySketches.length || !activeId) return -1;
    return librarySketches.findIndex((s) => s.id === activeId);
  }, [librarySketches, activeId]);

  const goTo = useCallback((delta: number) => {
    if (librarySketches.length === 0) return;
    const cur = idx >= 0 ? idx : 0;
    const next = (cur + delta + librarySketches.length) % librarySketches.length;
    const nx = librarySketches[next];
    if (!nx) return;
    setActiveId(nx.id);
    if (selection?.kind !== "sketch" || selection.id !== nx.id) {
      setSelection({ kind: "sketch", id: nx.id, name: nx.name });
    }
  }, [librarySketches, idx, selection, setSelection]);

  const persistWithId = useCallback(async (
    desiredId: string | null,
    next: { name: string; kind: SketchKind; data: unknown; png_b64?: string },
  ): Promise<Sketch | null> => {
    setSaveStatus("saving…");
    try {
      const body: Record<string, unknown> = {
        name: next.name, kind: next.kind, data: next.data,
      };
      if (desiredId) body.id = desiredId;
      if (next.png_b64) body.png_b64 = next.png_b64;
      const r = await fetch("/api/sketch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) { setSaveStatus(`error: HTTP ${r.status}`); return null; }
      const j = (await r.json()) as { sketch: Sketch };
      setSaveStatus("saved");
      window.setTimeout(() => setSaveStatus(null), 1200);
      await reloadList();
      return j.sketch;
    } catch (e) {
      setSaveStatus(`error: ${(e as Error).message}`);
      return null;
    }
  }, [reloadList]);

  const persist = useCallback(async (
    next: { name?: string; kind?: SketchKind; data?: unknown; png_b64?: string },
    opts: { newSketch?: boolean } = {},
  ) => {
    if (!opts.newSketch && !active) return null;
    const body: Record<string, unknown> = opts.newSketch
      ? {
          name: next.name ?? "Untitled",
          kind: next.kind ?? "excalidraw",
          data: next.data ?? null,
        }
      : {
          id: active!.id,
          name: next.name ?? active!.name,
          kind: next.kind ?? active!.kind,
          data: next.data ?? active!.data,
        };
    if (next.png_b64) body.png_b64 = next.png_b64;
    setSaveStatus("saving…");
    try {
      const r = await fetch("/api/sketch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) { setSaveStatus(`error: HTTP ${r.status}`); return null; }
      const j = (await r.json()) as { sketch: Sketch };
      setSaveStatus("saved");
      window.setTimeout(() => setSaveStatus(null), 1200);
      if (!opts.newSketch) setActive(j.sketch);
      await reloadList();
      return j.sketch;
    } catch (e) {
      setSaveStatus(`error: ${(e as Error).message}`);
      return null;
    }
  }, [active, reloadList]);

  const onCreate = useCallback(async () => {
    if (!creating) return;
    const seed: unknown = creating.kind === "excalidraw"
      ? { elements: [], appState: {}, files: {} }
      : "<mxGraphModel><root><mxCell id=\"0\"/><mxCell id=\"1\" parent=\"0\"/></root></mxGraphModel>";
    const compactedSlug = await compactSlug(creating.name);
    const fresh = await persistWithId(
      compactedSlug,
      { name: creating.name || "Untitled sketch", kind: creating.kind, data: seed },
    );
    setCreating(null);
    if (!fresh) return;
    setActiveId(fresh.id);
    setSelection({ kind: "sketch", id: fresh.id, name: fresh.name });
  }, [creating, persistWithId, setSelection]);

  const onDelete = useCallback(async () => {
    if (!active) return;
    if (!window.confirm(`Delete sketch "${active.name}"? (PNG export removed too.)`)) return;
    const deletedId = active.id;
    await fetch(`/api/sketch?id=${encodeURIComponent(deletedId)}`, { method: "DELETE" });
    const next = librarySketches.find((s) => s.id !== deletedId) || null;
    setActive(null);
    setActiveId(next ? next.id : null);
    if (next) {
      setSelection({ kind: "sketch", id: next.id, name: next.name });
    } else if (selection?.kind === "sketch") {
      setSelection(null);
    }
    await reloadList();
  }, [active, librarySketches, reloadList, selection, setSelection]);

  const onDuplicate = useCallback(async () => {
    if (!active) return;
    const copyName = active.name.match(/\(copy(?: \d+)?\)$/)
      ? active.name
      : `${active.name} (copy)`;
    let fresh: SketchMeta | null = null;
    try {
      const r = await fetch("/api/sketch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: copyName, kind: active.kind, data: active.data }),
      });
      if (!r.ok) {
        window.alert(`Duplicate failed: HTTP ${r.status}`);
        return;
      }
      const body = (await r.json()) as { sketch: SketchMeta };
      fresh = body.sketch;
    } catch (e) {
      window.alert(`Duplicate failed: ${(e as Error).message}`);
      return;
    }
    if (!fresh) return;
    await reloadList();
    setActiveId(fresh.id);
    setSelection({ kind: "sketch", id: fresh.id, name: fresh.name });
  }, [active, reloadList, setSelection]);

  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerMenu, setPickerMenu] = useState<{
    sketchId: string; x: number; y: number;
  } | null>(null);
  const pickerBtnRef = useRef<HTMLButtonElement | null>(null);
  const [pickerAnchor, setPickerAnchor] = useState<
    { top: number; left: number } | null
  >(null);

  useEffect(() => {
    if (!pickerOpen && !pickerMenu) return;
    const onDocClick = (ev: MouseEvent) => {
      const t = ev.target as Element | null;
      if (t && t.closest && t.closest(".sy-sketch-picker")) return;
      if (t && t.closest && t.closest(".sy-context-menu")) return;
      setPickerOpen(false);
      setPickerMenu(null);
    };
    window.addEventListener("click", onDocClick);
    return () => window.removeEventListener("click", onDocClick);
  }, [pickerOpen, pickerMenu]);

  const onPickerSelect = useCallback((id: string) => {
    setPickerOpen(false);
    setPickerMenu(null);
    setActiveId(id);
    const meta = librarySketches.find((s) => s.id === id)
      ?? sketches?.find((s) => s.id === id);
    if (meta) setSelection({ kind: "sketch", id: meta.id, name: meta.name });
  }, [librarySketches, sketches, setSelection]);

  const onPickerContextMenu = useCallback((e: React.MouseEvent, id: string) => {
    e.preventDefault();
    setPickerMenu({ sketchId: id, x: e.clientX, y: e.clientY });
  }, []);

  const onPickerDuplicate = useCallback(async () => {
    if (!pickerMenu) return;
    const targetId = pickerMenu.sketchId;
    setPickerMenu(null);
    setPickerOpen(false);
    if (activeId !== targetId) setActiveId(targetId);
    window.setTimeout(() => { void onDuplicate(); }, 0);
  }, [pickerMenu, activeId]); // eslint-disable-line react-hooks/exhaustive-deps

  const onPickerDelete = useCallback(() => {
    if (!pickerMenu) return;
    const targetId = pickerMenu.sketchId;
    setPickerMenu(null);
    setPickerOpen(false);
    if (activeId !== targetId) setActiveId(targetId);
    window.setTimeout(() => { void onDelete(); }, 0);
  }, [pickerMenu, activeId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
      if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
      const t = document.activeElement;
      if (!t) return;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA") return;
      const el = t as HTMLElement;
      if (el.isContentEditable) return;
      if (el.closest(".sy-sketch-host")) return;
      goTo(ev.key === "ArrowLeft" ? -1 : 1);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [goTo]);

  useEffect(() => { setNameDraft(null); }, [active?.id]);

  const commitRename = useCallback(() => {
    if (nameDraft === null) return;
    const trimmed = nameDraft.trim();
    setNameDraft(null);
    if (!active || !trimmed || trimmed === active.name) return;
    void persist({ name: trimmed });
  }, [active, nameDraft, persist]);

  const onClear = useCallback(async () => {
    if (!active) return;
    if (!window.confirm("Clear the canvas? Cmd-Z still undoes within 5 s.")) return;
    if (active.kind === "excalidraw") {
      const empty = { elements: [], appState: {}, files: {} };
      await persist({ data: empty });
    } else {
      await persist({
        data: "<mxGraphModel><root><mxCell id=\"0\"/><mxCell id=\"1\" parent=\"0\"/></root></mxGraphModel>",
      });
    }
    setClearVersion((v) => v + 1);
  }, [active, persist]);

  if (selection?.kind === "image-deck") {
    return (
      <ImageDeckViewer
        selection={selection}
        onClose={() => setSelection(null)}
      />
    );
  }

  return (
    <div className="sy-sketch">
      <div className="sy-sketch-toolbar">
        <button
          type="button"
          className="sy-vega-nav"
          onClick={() => goTo(-1)}
          disabled={librarySketches.length < 2}
          title="Previous sketch"
        >←</button>
        <div className="sy-vega-title-block">
          {nameDraft !== null ? (
            <input
              type="text"
              className="sy-vega-title-input"
              value={nameDraft}
              autoFocus
              onChange={(e) => setNameDraft(e.target.value)}
              onBlur={commitRename}
              onKeyDown={(e) => {
                if (e.key === "Enter") { e.preventDefault(); commitRename(); }
                if (e.key === "Escape") { e.preventDefault(); setNameDraft(null); }
              }}
            />
          ) : (
            <button
              type="button"
              className="sy-vega-title"
              onClick={() => active && setNameDraft(active.name)}
              title="Click to rename"
              disabled={!active}
            >
              {active?.name ?? (sketches && sketches.length === 0 ? "—" : "…")}
            </button>
          )}
          <span className="sy-vega-counter">
            {idx >= 0 && librarySketches.length > 0
              ? `${idx + 1} / ${librarySketches.length}`
              : ""}
            {active && (
              <span className="sy-sketch-kind"> · {active.kind}</span>
            )}
          </span>
        </div>
        <button
          type="button"
          className="sy-vega-nav"
          onClick={() => goTo(1)}
          disabled={librarySketches.length < 2}
          title="Next sketch"
        >→</button>
        <button
          ref={pickerBtnRef}
          type="button"
          className="sy-vega-nav sy-vega-nav--picker"
          onClick={(e) => {
            e.stopPropagation();
            setPickerOpen((v) => {
              const next = !v;
              if (next && pickerBtnRef.current) {
                const r = pickerBtnRef.current.getBoundingClientRect();
                setPickerAnchor({
                  top: r.bottom + 6,
                  left: Math.max(8, r.right - 320),
                });
              }
              return next;
            });
          }}
          disabled={librarySketches.length === 0}
          aria-haspopup="true"
          aria-expanded={pickerOpen}
          title="Browse all sketches"
        >▾</button>
        <span className="sy-spacer" />
        {saveStatus && <span className="sy-sketch-save">{saveStatus}</span>}
        {active && (
          <button
            type="button"
            className="sy-vega-toolbar-btn"
            onClick={() => void onDuplicate()}
            title="Duplicate this sketch"
          >Duplicate</button>
        )}
        <button
          type="button"
          className="sy-vega-toolbar-btn"
          onClick={() => setCreating({ name: "", kind: "excalidraw" })}
          title="Start a new sketch"
        >+ Add Sketch</button>
        {active && (
          <button
            type="button"
            className="sy-vega-toolbar-btn"
            onClick={onClear}
            title="Blank the canvas (5 s autosave delay leaves room for Cmd-Z)"
          >Clear</button>
        )}
        {active && (
          <button
            type="button"
            className="sy-vega-toolbar-btn"
            onClick={onDelete}
            title="Delete this sketch and its PNG export"
          >Delete</button>
        )}
      </div>
      {listError && (
        <div className="sy-vega-banner sy-vega-banner--err">List error: {listError}</div>
      )}
      {pickerOpen && (
        <div
          className="sy-sketch-picker"
          role="listbox"
          style={
            pickerAnchor
              ? {
                  position: "fixed",
                  top: pickerAnchor.top,
                  left: pickerAnchor.left,
                  right: "auto",
                }
              : undefined
          }
        >
          <div className="sy-sketch-picker-header">
            All sketches ({librarySketches.length})
          </div>
          <ul className="sy-sketch-picker-list">
            {librarySketches.map((s, i) => (
              <li
                key={s.id}
                className={
                  "sy-sketch-picker-row" +
                  (s.id === activeId ? " sy-sketch-picker-row--active" : "")
                }
                onMouseDown={(e) => {
                  if (e.button !== 0) return;
                  e.preventDefault();
                  e.stopPropagation();
                  onPickerSelect(s.id);
                }}
                onContextMenu={(e) => onPickerContextMenu(e, s.id)}
                role="option"
                aria-selected={s.id === activeId}
              >
                <span className="sy-sketch-picker-thumb-wrap">
                  <img
                    className="sy-sketch-picker-thumb"
                    src={`/figures/${encodeURIComponent(s.id)}.png?t=${s.updated_at ?? 0}`}
                    alt=""
                    onError={(e) => {
                      const img = e.currentTarget as HTMLImageElement;
                      img.style.display = "none";
                      const wrap = img.parentElement;
                      if (wrap && !wrap.querySelector(".sy-sketch-picker-empty")) {
                        const ph = document.createElement("span");
                        ph.className = "sy-sketch-picker-empty";
                        ph.textContent = "empty";
                        wrap.appendChild(ph);
                      }
                    }}
                  />
                </span>
                <div className="sy-sketch-picker-meta">
                  <span className="sy-sketch-picker-idx">{i + 1}</span>
                  <span className="sy-sketch-picker-name" title={s.name}>{s.name}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
      {pickerMenu && (
        <ul
          className="sy-context-menu"
          role="menu"
          style={{ top: pickerMenu.y, left: pickerMenu.x }}
          onClick={(e) => e.stopPropagation()}
        >
          <li
            role="menuitem"
            className="sy-context-menu-item"
            onClick={() => void onPickerDuplicate()}
          >
            Duplicate
          </li>
          <li
            role="menuitem"
            className="sy-context-menu-item sy-context-menu-item--danger"
            onClick={onPickerDelete}
          >
            Delete…
          </li>
        </ul>
      )}
      <div className="sy-sketch-host">
        {creating && (
          <CreateOverlay
            value={creating}
            onChange={setCreating}
            onSubmit={onCreate}
            onCancel={() => setCreating(null)}
          />
        )}
        {!creating && active?.kind === "excalidraw" && (
          <ExcalidrawCanvas
            key={`${active.id}:${clearVersion}`}
            sketch={active}
            onPersist={(data, png_b64) => persist({ data, png_b64 })}
          />
        )}
        {!creating && active?.kind === "drawio" && (
          <DrawioCanvas
            key={`${active.id}:${clearVersion}`}
            sketch={active}
            onPersist={(data, png_b64) => persist({ data, png_b64 })}
          />
        )}
        {!creating && !active && sketches && sketches.length === 0 && (
          <div className="sy-vega-empty">
            <h2>No sketches yet</h2>
            <p>
              Click <strong>+ Add Sketch</strong> to start one. Sketches save to
              <code> .workbench/sketches/</code> as JSON; PNG exports go
              to <code>figures/</code> alongside the rest of the workspace
              for easy embedding in docs. Presentations are HTML slideshows
              — use <strong>→ Slideshow</strong> in the Editor.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}


// ── Create overlay ──────────────────────────────────────────────────


function CreateOverlay(props: {
  value: { name: string; kind: SketchKind };
  onChange: (v: { name: string; kind: SketchKind }) => void;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  const { value, onChange, onSubmit, onCancel } = props;
  return (
    <div className="sy-sketch-create">
      <h3>New sketch</h3>
      <label className="sy-sketch-create-row">
        <span>Name</span>
        <input
          type="text"
          value={value.name}
          autoFocus
          onChange={(e) => onChange({ ...value, name: e.target.value })}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.preventDefault(); onSubmit(); }
            if (e.key === "Escape") { e.preventDefault(); onCancel(); }
          }}
          placeholder="Architecture diagram"
        />
      </label>
      <div className="sy-sketch-create-row">
        <span>Tool</span>
        <div className="sy-sketch-kind-toggle">
          {(["excalidraw", "drawio"] as SketchKind[]).map((k) => (
            <button
              key={k}
              type="button"
              data-active={value.kind === k}
              onClick={() => onChange({ ...value, kind: k })}
            >
              {k === "excalidraw" ? "Excalidraw (freehand)" : "drawio (structured)"}
            </button>
          ))}
        </div>
      </div>
      <div className="sy-sketch-create-actions">
        <button type="button" className="sy-vega-toolbar-btn" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="sy-vega-toolbar-btn"
          onClick={onSubmit}
          data-active="true"
        >
          Create
        </button>
      </div>
    </div>
  );
}


// ── Excalidraw canvas ───────────────────────────────────────────────


function ExcalidrawCanvas(props: {
  sketch: Sketch;
  onPersist: (data: unknown, png_b64?: string) => void;
}) {
  const { sketch, onPersist } = props;
  const [Comp, setComp] = useState<React.ComponentType<Record<string, unknown>> | null>(null);
  const [exportToBlob, setExportToBlob] = useState<((args: Record<string, unknown>) => Promise<Blob>) | null>(null);
  const apiRef = useRef<ExcalidrawAPI | null>(null);
  const lastSerialisedRef = useRef<string>("");
  const dirtyRef = useRef<boolean>(false);

  // Lazy-import Excalidraw on first activation.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const mod = await import("@excalidraw/excalidraw");
      // Side-effect CSS import — Vite handles it via the package.
      await import("@excalidraw/excalidraw/index.css");
      if (cancelled) return;
      setComp(() => mod.Excalidraw as React.ComponentType<Record<string, unknown>>);
      setExportToBlob(() => mod.exportToBlob as (args: Record<string, unknown>) => Promise<Blob>);
    })();
    return () => { cancelled = true; };
  }, []);

  // Reset dirty tracking when the active sketch changes.
  useEffect(() => {
    dirtyRef.current = false;
    lastSerialisedRef.current = "";
  }, [sketch.id]);

  // Autosave loop — serialise scene, compare, persist + PNG export
  // when something actually changed. Excalidraw fires onChange on
  // every mouse move during a drag, so coalescing is critical.
  useEffect(() => {
    if (!Comp || !exportToBlob) return;
    let cancelled = false;
    const tick = async () => {
      const api = apiRef.current;
      if (!api || !dirtyRef.current) return;
      const elements = api.getSceneElements();
      const appState = api.getAppState();
      const files = api.getFiles();
      const serialised = JSON.stringify({ elements, appState });
      if (serialised === lastSerialisedRef.current) return;
      lastSerialisedRef.current = serialised;
      dirtyRef.current = false;
      let png_b64: string | undefined;
      // Skip exportToBlob for empty scenes — Excalidraw throws on
      // zero elements ("Cannot read properties of undefined" inside
      // the bounds calculator), same as the render-on-demand path.
      if (Array.isArray(elements) && elements.length > 0) {
        try {
          const blob = await exportToBlob({
            elements, appState, files,
            mimeType: "image/png",
            // Bake a transparent background; the embedding doc decides
            // theming so a fixed colour would fight downstream styling.
            exportPadding: 16,
          });
          png_b64 = await blobToBase64(blob);
        } catch (e) {
          // Surface in the console so a real export failure shows up
          // when investigating "no PNG in figures/" — JSON save still
          // proceeds.
          console.warn("[SketchTab] PNG export failed:", e);
        }
      }
      if (cancelled) return;
      onPersist(
        { elements, appState, files },
        png_b64,
      );
    };
    const id = window.setInterval(() => { void tick(); }, AUTOSAVE_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
      // Final flush on unmount.
      void tick();
    };
  }, [Comp, exportToBlob, onPersist]);

  if (!Comp) return <div className="sy-vega-banner">Loading Excalidraw…</div>;
  // Excalidraw's appState contains a `collaborators` field that is
  // a Map at runtime. JSON round-trip strips the Map type — when
  // we hydrate a saved sketch the field becomes `undefined` (or a
  // plain object), and Excalidraw's render path crashes inside
  // `appState.collaborators.forEach(...)`. Normalise here.
  const initialData = normaliseExcalidrawData(sketch.data);
  return (
    <div className="sy-sketch-excalidraw" key={sketch.id}>
      <Comp
        initialData={initialData}
        excalidrawAPI={(api: ExcalidrawAPI) => { apiRef.current = api; }}
        onChange={() => { dirtyRef.current = true; }}
      />
    </div>
  );
}


function normaliseExcalidrawData(raw: unknown): Record<string, unknown> {
  const base = raw && typeof raw === "object"
    ? raw as Record<string, unknown>
    : {};
  const elements = Array.isArray(base.elements) ? base.elements : [];
  const files = base.files && typeof base.files === "object"
    ? base.files as Record<string, unknown>
    : {};
  const appStateRaw = base.appState && typeof base.appState === "object"
    ? base.appState as Record<string, unknown>
    : {};
  // Force the Map types Excalidraw expects. Without this, the
  // forEach in render crashes the entire React tree.
  const appState: Record<string, unknown> = { ...appStateRaw };
  if (!(appState.collaborators instanceof Map)) {
    appState.collaborators = new Map();
  }
  return { elements, appState, files };
}


/** Ask the daemon for a 3-4 word LM-compacted slug; falls back to a
 *  hand-truncated word slug when the network/provider isn't there.
 *  Short titles bypass the call entirely (the daemon returns a
 *  trivial slug for ≤4 words). */
async function compactSlug(title: string): Promise<string | null> {
  if (!title.trim()) return null;
  try {
    const r = await fetch("/api/llm/slug", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    if (!r.ok) return null;
    const body = (await r.json()) as { slug: string };
    return body.slug || null;
  } catch {
    return null;
  }
}


function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}


// ── drawio canvas ───────────────────────────────────────────────────


function DrawioCanvas(props: {
  sketch: Sketch;
  onPersist: (data: unknown, png_b64?: string) => void;
}) {
  const { sketch, onPersist } = props;
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const initialXmlRef = useRef<string>(typeof sketch.data === "string" ? sketch.data : "");
  // Track whether we've sent the initial load — drawio sends `init`
  // when it's ready; we reply with the saved XML.
  const initedRef = useRef<boolean>(false);
  const dirtyRef = useRef<boolean>(false);

  useEffect(() => {
    initialXmlRef.current = typeof sketch.data === "string" ? sketch.data : "";
    initedRef.current = false;
    dirtyRef.current = false;
  }, [sketch.id]);

  // Listen for drawio postMessage events.
  useEffect(() => {
    const onMessage = (ev: MessageEvent) => {
      if (ev.origin !== DRAWIO_ORIGIN) return;
      let msg: Record<string, unknown> | null = null;
      try {
        msg = typeof ev.data === "string" ? JSON.parse(ev.data) : ev.data;
      } catch { return; }
      if (!msg) return;
      const event = msg.event;
      const iframe = iframeRef.current;
      if (!iframe?.contentWindow) return;
      const send = (payload: Record<string, unknown>) => {
        iframe.contentWindow!.postMessage(JSON.stringify(payload), DRAWIO_ORIGIN);
      };
      if (event === "init" && !initedRef.current) {
        initedRef.current = true;
        send({ action: "load", xml: initialXmlRef.current, autosave: 1 });
      } else if (event === "autosave" || event === "save") {
        const xml = (msg.xml as string) || "";
        dirtyRef.current = true;
        // After receiving XML, ask drawio for a PNG export so we save
        // both at once. The response comes back as `event === "export"`.
        send({ action: "export", format: "xmlpng", xml });
      } else if (event === "export") {
        const dataUrl = (msg.data as string) || "";
        // The XML round-trips inside the xmlpng but we already have it
        // from the autosave event above. Pull from the message if
        // present for safety; fall back to the iframe's current state.
        const xml = (msg.xml as string) || initialXmlRef.current;
        if (xml) initialXmlRef.current = xml;
        onPersist(xml, dataUrl);
        dirtyRef.current = false;
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [onPersist]);

  return (
    <iframe
      key={sketch.id}
      ref={iframeRef}
      className="sy-sketch-drawio"
      src={DRAWIO_URL}
      title={`drawio: ${sketch.name}`}
    />
  );
}


// ── Image-deck viewer ────────────────────────────────────────────
// Stand-in for the core .pptx-rendered-to-PNGs flow. Reuses the
// Sketch tab's chrome shape (toolbar with ← / counter / →, host
// area below) but mounts an <img> per slide instead of an
// Excalidraw canvas, since the user can't edit a PPTX inline. The
// LibreOffice pack (task #20) will override this routing with a
// proper Impress tab when installed.

type ImageDeckSelection = {
  kind: "image-deck";
  title: string;
  source_path: string;
  slides: { src: string; name: string }[];
};

function ImageDeckViewer({
  selection, onClose,
}: { selection: ImageDeckSelection; onClose: () => void }) {
  const [idx, setIdx] = useState(0);
  const total = selection.slides.length;

  // Reset to the first slide whenever the underlying deck changes
  // (different .pptx clicked from the browser).
  useEffect(() => {
    setIdx(0);
  }, [selection.source_path]);

  // ←/→ arrow nav, same heuristics as the editable-deck path: skip
  // when an editable element owns focus.
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
      if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
      const t = document.activeElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
      if (total === 0) return;
      ev.preventDefault();
      setIdx((i) => {
        const next = ev.key === "ArrowLeft" ? i - 1 : i + 1;
        return Math.max(0, Math.min(total - 1, next));
      });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [total]);

  const current = selection.slides[idx];
  return (
    <div className="sy-sketch sy-imagedeck">
      <div className="sy-vega-toolbar">
        <button
          type="button"
          className="sy-vega-nav"
          onClick={() => setIdx((i) => Math.max(0, i - 1))}
          disabled={idx === 0}
          title="Previous slide"
        >←</button>
        <div className="sy-vega-title-block">
          <span className="sy-vega-title sy-vega-title--static">
            {selection.title}
          </span>
          <span className="sy-vega-counter">
            {total > 0 ? `${idx + 1} / ${total}` : ""}
            <span className="sy-sketch-kind"> · pptx</span>
          </span>
        </div>
        <button
          type="button"
          className="sy-vega-nav"
          onClick={() => setIdx((i) => Math.min(total - 1, i + 1))}
          disabled={idx >= total - 1}
          title="Next slide"
        >→</button>
        <span className="sy-spacer" />
        <span className="sy-sketch-save" title={selection.source_path}>
          read-only · {selection.source_path}
        </span>
        <button
          type="button"
          className="sy-vega-toolbar-btn"
          onClick={onClose}
          title="Close this deck — drops back to the Sketch library so you can create a new sketch or pick another."
        >
          × Close deck
        </button>
      </div>
      <div className="sy-imagedeck-stage">
        {current && (
          <img
            className="sy-imagedeck-slide"
            src={current.src}
            alt={current.name}
          />
        )}
        {!current && (
          <div className="sy-sketch-empty">
            <h2>Couldn't load slides</h2>
            <p>The deck rendered but no slide paths came back. Try clicking the file again.</p>
          </div>
        )}
      </div>
    </div>
  );
}
