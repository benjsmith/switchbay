import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSelection } from "../../selection/SelectionContext";
import { useTabs } from "../../center/TabsContext";
import {
  clearDeckRun, getDeckRun, setDeckRun,
  subscribe as subscribeDeckRuns,
  takePrimedAnalysis,
} from "./deckRuns";
import { ackUiCommand, takeSketchShow } from "../../lib/pendingUiCommands";

/**
 * Sketch tab — Excalidraw + drawio on the same canvas area, slide-deck
 * nav between sketches, PNG exports auto-written to `wiki/figures/`.
 *
 * Each sketch has a fixed kind set at creation (`excalidraw` or
 * `drawio`); the underlying data formats are incompatible so switching
 * kind for an existing sketch isn't supported. The "New" affordance
 * lets the user (or agent) pick which tool a new sketch uses.
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

type Analysis = {
  slug: string;
  path: string;
  title: string;
  slides: string[];
  sources: string[];
  // {sketch_id: presenter-note}. May be absent on older daemons /
  // primed records — treat as {}.
  slide_notes?: Record<string, string>;
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
  const { switchToKind } = useTabs();
  const [sketches, setSketches] = useState<SketchMeta[] | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [active, setActive] = useState<Sketch | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  // "Create new" overlay state.
  const [creating, setCreating] = useState<{ name: string; kind: SketchKind } | null>(null);
  // When the user (or agent) navigates to an analysis page, the
  // Sketch tab enters "deck mode" — the slide-deck nav steps through
  // that analysis's slides in order rather than every sketch in the
  // workspace. `analysis` is the deck spine; `null` = library mode.
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  // Bumped on Clear to force the canvas component to re-mount with
  // the fresh empty scene. Excalidraw's `initialData` is only read
  // on first render so we key the canvas by `${id}:${clearVersion}`.
  const [clearVersion, setClearVersion] = useState(0);
  // Inline rename — same UX as Vega's title input. `null` = static
  // span; non-null = textbox open with this draft value.
  const [nameDraft, setNameDraft] = useState<string | null>(null);
  // run_id of an in-flight autopopulate run for the active deck. Set
  // by the editor's → Slides path via the deckRuns store; cleared
  // when the daemon's `/api/runs/active` no longer lists it. Drives
  // the spinner shown next to the deck title.
  const [populateRunId, setPopulateRunId] = useState<string | null>(null);

  // Resync the populate-run badge whenever the active analysis
  // changes or another tab posts a new run via deckRuns.
  useEffect(() => {
    const sync = () => {
      const id = analysis?.path ? getDeckRun(analysis.path) ?? null : null;
      setPopulateRunId(id);
    };
    sync();
    return subscribeDeckRuns(sync);
  }, [analysis?.path]);

  // Poll `/api/runs/active` every couple of seconds while a populate
  // run is in flight; clear the badge when the run drops off the
  // active list. Cheap call (in-process registry, returns ~10 rows).
  useEffect(() => {
    if (!populateRunId || !analysis?.path) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await fetch("/api/runs/active");
        if (!r.ok) return;
        const body = await r.json() as { runs?: { run_id: string }[] };
        const live = (body.runs ?? []).some((x) => x.run_id === populateRunId);
        if (!cancelled && !live) {
          clearDeckRun(analysis.path);
        }
      } catch { /* transient */ }
    };
    const id = window.setInterval(() => void tick(), 2000);
    void tick();
    return () => { cancelled = true; window.clearInterval(id); };
  }, [populateRunId, analysis?.path]);

  const onSpinnerClick = useCallback(() => {
    if (!populateRunId) return;
    switchToKind("agents");
    // Defer one tick so AgentDashboardTab has mounted before the
    // expand-run event fires (matches the pattern used for project
    // back-links and rail jump arrows).
    window.setTimeout(() => {
      window.dispatchEvent(new CustomEvent("sy:expand-run", {
        detail: { run_id: populateRunId },
      }));
    }, 0);
  }, [populateRunId, switchToKind]);

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

  // Sketches the user has explicitly "Closed deck" against. The
  // auto-detect below skips these so a close doesn't immediately
  // re-enter deck mode via the by-slide lookup.
  const dismissedSlidesRef = useRef<Set<string>>(new Set());

  // Per-sketch cache of by-slide lookups so navigating between
  // sketches doesn't fan out a fetch on every arrow key. Maps
  // sketch id → owning Analysis (or null when known to have no
  // owner). Resets only when explicit deck-mode transitions
  // happen below.
  const bySlideCacheRef = useRef<Map<string, Analysis | null>>(new Map());

  // Auto-detect deck mode from the active sketch. If the user
  // arrived at a sketch that belongs to an analysis's slides[]
  // (because they clicked one in the library, or because the
  // active was preserved across a workspace switch), pull the
  // owning analysis and enter deck mode.
  //
  // Also promote selection to the analysis *page* so a leftover
  // sketch selection can't re-assert itself on list reload and
  // pin the canvas back to one slide (the goTo/picker stomp bug).
  useEffect(() => {
    if (analysis) return;  // already in deck mode
    if (!activeId) return;
    if (dismissedSlidesRef.current.has(activeId)) return;

    const enterDeck = (a: Analysis) => {
      setAnalysis(a);
      if (
        selection?.kind !== "page"
        || selection.path !== a.path
      ) {
        setSelection({ kind: "page", id: a.path, path: a.path });
      }
    };

    // Cache hit — skip the round-trip.
    if (bySlideCacheRef.current.has(activeId)) {
      const cached = bySlideCacheRef.current.get(activeId);
      if (cached) enterDeck(cached);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(
          `/api/analysis/by-slide?sketch_id=${encodeURIComponent(activeId)}`,
        );
        if (cancelled || !r.ok) return;
        const body = (await r.json()) as { analysis: Analysis | null };
        if (cancelled) return;
        bySlideCacheRef.current.set(activeId, body.analysis);
        if (!body.analysis) return;
        if (dismissedSlidesRef.current.has(activeId)) return;
        enterDeck(body.analysis);
      } catch { /* no match — stay in library mode */ }
    })();
    return () => { cancelled = true; };
  }, [activeId, analysis, selection, setSelection]);

  // When the active sketch drifts OUTSIDE the current deck's
  // slides (e.g. user picks a different-deck slide via the
  // picker while still in deck A), drop to library mode so the
  // auto-detect above can pick up the correct deck. Without
  // this, the badge claimed "deck: A" while the canvas showed
  // a slide that wasn't in A — confusing.
  useEffect(() => {
    if (!analysis || !activeId) return;
    if (!analysis.slides.includes(activeId)) {
      setAnalysis(null);
    }
  }, [activeId, analysis]);

  // Workspace switch (selection set to null with no page kind on
  // first mount of the new workspace's selection) → reset
  // session-scoped state. Without this, dismissed slide ids from
  // a prior workspace could mute deck mode in the new one if a
  // sketch id collision occurred.
  const lastWsRef = useRef<string | null>(null);
  useEffect(() => {
    // We don't have a workspace handle here; use the sketches
    // list URL implicitly via reloadList. As a proxy, reset on
    // every sketches transition from a non-empty list to a
    // genuinely different non-empty list (size + first id).
    if (!sketches || sketches.length === 0) return;
    const fingerprint = `${sketches.length}:${sketches[0]!.id}`;
    if (lastWsRef.current && lastWsRef.current !== fingerprint) {
      dismissedSlidesRef.current = new Set();
      bySlideCacheRef.current = new Map();
    }
    lastWsRef.current = fingerprint;
  }, [sketches]);

  // Watch selection for analysis pages. A SelectionPage that points
  // at `wiki/<slug>.md` may or may not be analysis-kind; the
  // /api/analysis endpoint returns 404 for non-analysis pages so a
  // single fetch decides. On match, enter deck mode. Prefer keeping
  // the already-active slide when it's a member of the deck (so
  // arrow/picker nav isn't stomped when selection re-asserts the
  // same page); only pin slides[0] when entering cold.
  useEffect(() => {
    if (selection?.kind !== "page") {
      // Don't unset analysis on every non-page selection — sketch
      // selections inside an active deck shouldn't break the deck.
      if (selection?.kind !== "sketch" && analysis) {
        setAnalysis(null);
      }
      return;
    }
    // Fast path: if the modal primed an analysis record on the way
    // in (via sy:open-as-deck), use it directly so the deck badge
    // appears on the very next render — no round-trip needed.
    const primed = takePrimedAnalysis(selection.path);
    if (primed) {
      const a = primed as unknown as Analysis;
      setAnalysis(a);
      if (a.slides && a.slides.length > 0) {
        setActiveId((cur) =>
          cur && a.slides.includes(cur) ? cur : a.slides[0]!,
        );
      }
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(
          `/api/analysis?path=${encodeURIComponent(selection.path)}`,
        );
        if (cancelled) return;
        if (!r.ok) { setAnalysis(null); return; }
        const body = (await r.json()) as { analysis: Analysis };
        setAnalysis(body.analysis);
        if (body.analysis.slides.length > 0) {
          setActiveId((cur) =>
            cur && body.analysis.slides.includes(cur)
              ? cur
              : body.analysis.slides[0]!,
          );
        }
      } catch { setAnalysis(null); }
    })();
    return () => { cancelled = true; };
  }, [selection]); // eslint-disable-line react-hooks/exhaustive-deps

  // Selection → active sketch. CRITICAL: do NOT depend on `activeId`.
  // In-deck navigation (arrows / picker) updates activeId while
  // leaving selection on the analysis page. Re-running this on every
  // activeId change was stomping deck nav: goTo(slide N) → effect →
  // setActiveId(selection.sketch) → stuck on slide 1.
  useEffect(() => {
    if (selection?.kind === "sketch") {
      // Library pick. If we already auto-entered a deck whose slides
      // include this id, don't fight deck-mode activeId walks — the
      // enterDeck path promotes selection to the page, so this branch
      // should only fire for true library browsing.
      setActiveId(selection.id);
      return;
    }
    if (selection?.kind === "page") {
      // Page effect above owns deck entry; don't fight it here.
      return;
    }
    if (!sketches) return;
    if (sketches.length === 0) { setActiveId(null); return; }
    // Auto-pick a default only when we have no usable activeId.
    // Functional update so we don't need activeId in deps.
    setActiveId((cur) => {
      if (cur && sketches.some((s) => s.id === cur)) return cur;
      // Skip slides the user explicitly closed (Close deck).
      const usable = sketches.find(
        (s) => !dismissedSlidesRef.current.has(s.id),
      );
      return usable ? usable.id : null;
    });
  }, [sketches, selection]);

  // PNG render-on-demand → CANONICAL Excalidraw export.
  //
  // `author_slide` writes an immediate Pillow preview so the deck
  // page's <img> is not broken. That preview uses a system sans and
  // can tofu Unicode (e.g. →). The Sketch canvas (Virgil) looks fine.
  // We therefore re-export every non-empty Excalidraw scene once per
  // tab session with exportToBlob and OVERWRITE the Pillow PNG —
  // even when has_png is already true.
  //
  // Per-id guard (`exportedPngRef`) so we don't loop after reloadList.
  // drawio still needs a mounted iframe; skipped here.
  const exportedPngRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!sketches) return;
    const candidates = analysis
      ? analysis.slides
          .map((id) => sketches.find((m) => m.id === id))
          .filter((s): s is SketchMeta => Boolean(s))
      : sketches;
    const pending: SketchMeta[] = [];
    for (const s of candidates) {
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
          // exportToBlob throws on a zero-element scene.
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
          // Allow one more attempt next time sketches reloads.
          exportedPngRef.current.delete(meta.id);
        }
      }
      // Bust image caches that key on ?t=updated_at only after writes.
      if (!cancelled && wrote > 0) await reloadList();
    })();
    return () => { cancelled = true; };
  }, [analysis, sketches, reloadList]);

  // The slide-deck nav reads from `deckSketches` — either the
  // analysis's ordered slides (deck mode) or every workspace sketch
  // (library mode, the default). Resolved into the same SketchMeta
  // shape so the toolbar code below doesn't branch.
  const deckSketches: SketchMeta[] = useMemo(() => {
    if (!sketches) return [];
    if (analysis) {
      const byId = new Map(sketches.map((s) => [s.id, s]));
      // Dedup slide ids before mapping — a duplicate id in the deck
      // frontmatter would otherwise render the same slide twice.
      const seen = new Set<string>();
      return analysis.slides
        .filter((id) => (seen.has(id) ? false : (seen.add(id), true)))
        .map((id) => byId.get(id))
        .filter((s): s is SketchMeta => Boolean(s));
    }
    return sketches;
  }, [sketches, analysis]);

  // Bumped when an agent re-authors the same slide so we re-fetch
  // even if activeId didn't change.
  const [reloadToken, setReloadToken] = useState(0);

  // Fetch the full record on activeId change (or agent reload).
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

  // Publish visible slide focus for sketch_context / author_slide default.
  const lastSketchFocusRef = useRef("");
  useEffect(() => {
    if (!activeId) return;
    const slideIndex = analysis && activeId
      ? analysis.slides.indexOf(activeId)
      : -1;
    const payload = {
      surface: "sketch",
      sketch_id: activeId,
      name: active?.name || activeId,
      kind: active?.kind || "excalidraw",
      slide_index: slideIndex >= 0 ? slideIndex : null,
      deck_title: analysis?.title || null,
      analysis_path: analysis?.path || null,
      deck_len: analysis?.slides?.length ?? null,
    };
    const serialised = JSON.stringify(payload);
    if (serialised === lastSketchFocusRef.current) return;
    lastSketchFocusRef.current = serialised;
    void fetch("/api/ui/focus", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: serialised,
    }).catch(() => { /* ignore */ });
  }, [activeId, active, analysis]);

  // Agent sketch_show / author_slide nudge (+ cold-mount stash).
  useEffect(() => {
    const applyShow = (d: {
      sketch_id?: string | null;
      slide_index?: number | null;
    }) => {
      if (typeof d.slide_index === "number" && analysis?.slides?.length) {
        const id = analysis.slides[d.slide_index];
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
    // Drain App stash if this tab just mounted for an agent show.
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
  }, [analysis]);

  const idx = useMemo(() => {
    if (!deckSketches.length || !activeId) return -1;
    return deckSketches.findIndex((s) => s.id === activeId);
  }, [deckSketches, activeId]);

  const goTo = useCallback((delta: number) => {
    if (deckSketches.length === 0) return;
    // If the active sketch isn't in the current list (e.g. just
    // entered deck mode from a library orphan), treat as index 0
    // so → still advances instead of no-oping on idx === -1.
    const cur = idx >= 0 ? idx : 0;
    const next = (cur + delta + deckSketches.length) % deckSketches.length;
    const nx = deckSketches[next];
    if (!nx) return;
    setActiveId(nx.id);
    // Library mode: keep selection in lock-step with the canvas so
    // other tabs / slash commands see the active sketch.
    // Deck mode: leave selection alone (usually the analysis page).
    // Never set selection to a sketch while analysis is set — that
    // used to re-trigger the selection→activeId effect and pin us
    // back to whatever sketch selection still held from library
    // browsing. (See the selection-effect comment above.)
    if (!analysis && (selection?.kind !== "sketch" || selection.id !== nx.id)) {
      setSelection({ kind: "sketch", id: nx.id, name: nx.name });
    }
  }, [deckSketches, idx, analysis, selection, setSelection]);

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
    // Long titles get a 3-4 word LM-compacted slug so the filename
    // stays readable. Daemon falls back to a deterministic
    // word-truncate when no provider is configured, so this is safe
    // offline.
    const compactedSlug = await compactSlug(creating.name);
    const fresh = await persistWithId(
      compactedSlug,
      { name: creating.name || "Untitled sketch", kind: creating.kind, data: seed },
    );
    setCreating(null);
    if (!fresh) return;
    // If we're in deck mode, append the new slide to the analysis
    // automatically. If not, and there are no existing analyses but
    // the user is sketching, we leave the analysis creation for the
    // explicit "save as deck" path (or the Editor → Slides button)
    // — Add Sketch shouldn't surprise-create wiki pages on click.
    if (analysis) {
      try {
        const r = await fetch("/api/analysis/append-slide", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slug: analysis.slug, sketch_id: fresh.id }),
        });
        if (r.ok) {
          const j = (await r.json()) as { analysis: Analysis };
          setAnalysis(j.analysis);
        }
      } catch { /* non-fatal — sketch saved, just not linked yet */ }
    }
    setActiveId(fresh.id);
    if (!analysis) {
      setSelection({ kind: "sketch", id: fresh.id, name: fresh.name });
    }
  }, [creating, analysis, setSelection]); // eslint-disable-line react-hooks/exhaustive-deps

  const onDelete = useCallback(async () => {
    if (!active) return;
    if (!window.confirm(`Delete sketch "${active.name}"? (PNG export removed too.)`)) return;
    const deletedId = active.id;

    // In deck mode, also drop the deleted slide from the analysis's
    // `slides:` frontmatter list. Otherwise the picker keeps showing
    // a "deck: <name>" badge while every nav step skips the now-
    // missing sketch — visually identical to "all slides deleted",
    // which is what the user perceives.
    if (analysis) {
      const remaining = analysis.slides.filter((id) => id !== deletedId);
      try {
        await fetch("/api/analysis", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: analysis.path, slides: remaining }),
        });
        setAnalysis({ ...analysis, slides: remaining });
      } catch {
        // Best-effort: even if the analysis update fails, the
        // sketch itself still gets deleted below — better that
        // than a visible orphan.
      }
    }

    await fetch(`/api/sketch?id=${encodeURIComponent(deletedId)}`, { method: "DELETE" });

    // Pick a sibling to activate so the canvas doesn't go blank
    // and trick the user into thinking the whole deck vanished.
    // Use the same `deckSketches` ordering the nav arrows do.
    const next = deckSketches.find((s) => s.id !== deletedId) || null;
    setActive(null);
    setActiveId(next ? next.id : null);
    if (analysis && next) {
      // In deck mode, selection stays pinned to the analysis page;
      // activeId alone drives which slide the canvas mounts.
    } else if (next) {
      setSelection({ kind: "sketch", id: next.id, name: next.name });
    } else {
      // Genuinely empty now — clear any sketch-shaped selection so
      // the empty-state branch renders instead of a stale chip.
      if (selection?.kind === "sketch") setSelection(null);
    }
    await reloadList();
  }, [active, analysis, deckSketches, reloadList, selection, setSelection]);

  const onDuplicate = useCallback(async () => {
    if (!active) return;
    // Save a fresh copy under a derived name; backend mints a new id
    // because we don't pass `id`. The original stays put.
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

    // In deck mode: insert the copy immediately after the original
    // in the analysis's slides[] list, shunting following slides
    // forward by one.
    if (analysis) {
      const here = analysis.slides.indexOf(active.id);
      const insertAt = here >= 0 ? here + 1 : analysis.slides.length;
      const next = [
        ...analysis.slides.slice(0, insertAt),
        fresh.id,
        ...analysis.slides.slice(insertAt),
      ];
      try {
        await fetch("/api/analysis", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: analysis.path, slides: next }),
        });
        setAnalysis({ ...analysis, slides: next });
      } catch { /* sketch exists either way */ }
    }
    await reloadList();
    setActiveId(fresh.id);
    if (!analysis) {
      setSelection({ kind: "sketch", id: fresh.id, name: fresh.name });
    }
  }, [active, analysis, reloadList, setSelection]);

  // ── Thumbnail picker dropdown ─────────────────────────────────
  // The "browse all slides" affordance — popover with a
  // fixed-height scrollable list of thumbnails. Closes on outside
  // click. Right-click on a thumbnail surfaces a per-row context
  // menu with Delete / Duplicate that reuses the same handlers as
  // the toolbar buttons.
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerMenu, setPickerMenu] = useState<{
    sketchId: string; x: number; y: number;
  } | null>(null);
  // Anchor point for the picker — computed from the toggle button's
  // bounding rect on open so the dropdown lands directly under it
  // regardless of stacking/overflow context (Excalidraw paints inside
  // sy-sketch-host with its own internal stacking, which could mask
  // an absolutely-positioned picker even with a high z-index).
  const pickerBtnRef = useRef<HTMLButtonElement | null>(null);
  const [pickerAnchor, setPickerAnchor] = useState<
    { top: number; left: number } | null
  >(null);

  useEffect(() => {
    if (!pickerOpen && !pickerMenu) return;
    const onDocClick = (ev: MouseEvent) => {
      const t = ev.target as Element | null;
      // Keep the picker open if the click landed inside it. The
      // per-row context menu has its own handler.
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
    // Explicit picker selection counts as the user opting back
    // INTO the sketch — clear any dismissed-deck marker for it so
    // the auto-detect can re-engage deck mode (otherwise picking
    // a closed deck's slide stays library-mode silently, which
    // contradicts the empty-state hint).
    if (dismissedSlidesRef.current.has(id)) {
      dismissedSlidesRef.current.delete(id);
      // Also clear the cached "this slide → analysis X" so the
      // auto-detect refires with a fresh fetch.
      bySlideCacheRef.current.delete(id);
    }
    if (id === activeId) {
      // activeId didn't change so the auto-detect effect won't
      // re-run. Manually nudge it by fetching here.
      void fetch(`/api/analysis/by-slide?sketch_id=${encodeURIComponent(id)}`)
        .then((r) => r.ok ? r.json() : null)
        .then((b) => {
          if (b?.analysis) setAnalysis(b.analysis);
        }).catch(() => { /* ignore */ });
      return;
    }
    setActiveId(id);
    // Library mode (or a pick outside the active deck): emit a
    // sketch selection so the rest of the app tracks the canvas.
    // In-deck picks only set activeId — changing selection to a
    // sketch while analysis is set would re-fire the selection
    // effect and fight subsequent arrow keys.
    if (!analysis || !analysis.slides.includes(id)) {
      const meta = deckSketches.find((s) => s.id === id)
        ?? sketches?.find((s) => s.id === id);
      if (meta) setSelection({ kind: "sketch", id: meta.id, name: meta.name });
    }
  }, [activeId, analysis, deckSketches, sketches, setSelection]);

  // Right-click on a thumbnail → reuse the toolbar Delete/Duplicate
  // flow, but targeted at the specific row. We activate that sketch
  // first so `active` (which both handlers read) matches.
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
    // The Duplicate handler reads `active` (full record) so we
    // need a render cycle for the activeId change to flow before
    // calling it. Defer one tick.
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

  // ── Move-to dialog ────────────────────────────────────────────
  // `null` = closed; non-null = open with this draft destination
  // index (1-based, matching the user-visible "1 / N" counter).
  const [moveDraft, setMoveDraft] = useState<string | null>(null);

  // ── Deck menu (toolbar "Deck ▾" + badge click) ────────────────
  // `{x, y}` of the open menu; null when hidden. Prefer the
  // toolbar button — the badge alone was too easy to miss.
  const [deckMenu, setDeckMenu] = useState<{ x: number; y: number } | null>(null);
  const deckMenuBtnRef = useRef<HTMLButtonElement | null>(null);
  // Confirmation modal triggered from the menu's "Delete deck"
  // item — this is a heavy op (file removal + optional run cancel),
  // worth a deliberate Yes/No.
  const [confirmDeleteDeck, setConfirmDeleteDeck] = useState(false);

  const openDeckMenu = useCallback((
    e: React.MouseEvent,
    anchor: "button" | "pointer" = "pointer",
  ) => {
    e.preventDefault();
    e.stopPropagation();
    if (anchor === "button" && deckMenuBtnRef.current) {
      const r = deckMenuBtnRef.current.getBoundingClientRect();
      // Drop below the button, right-aligned (menu ~200px wide).
      setDeckMenu({
        x: Math.max(8, r.right - 200),
        y: r.bottom + 6,
      });
      return;
    }
    setDeckMenu({ x: e.clientX, y: e.clientY });
  }, []);

  useEffect(() => {
    if (!deckMenu) return;
    const close = () => setDeckMenu(null);
    // Delay attach one tick so the opening click doesn't instantly
    // close the menu (same pattern as the slide picker).
    const t = window.setTimeout(() => {
      window.addEventListener("click", close);
    }, 0);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("click", close);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [deckMenu]);

  const onCloseDeck = useCallback(() => {
    if (!analysis) return;
    setDeckMenu(null);
    // Remember every slide of the closed deck so the by-slide
    // auto-detect effect doesn't immediately re-enter deck mode
    // when the library lands on one of these sketches as the
    // default active.
    const deckSlides = new Set(analysis.slides ?? []);
    for (const sid of deckSlides) {
      dismissedSlidesRef.current.add(sid);
    }
    setAnalysis(null);
    if (selection?.kind === "page" && selection.path === analysis.path) {
      setSelection(null);
    }
    // Move the canvas off the deck's slides — without this the
    // user just saw the badge vanish while the same slide stayed
    // on screen and complained the deck "wasn't actually closed".
    // Pick the first workspace sketch that isn't part of the
    // closed deck; if there are none, drop to a blank canvas.
    const fallback = (sketches ?? []).find((s) => !deckSlides.has(s.id));
    setActive(null);
    setActiveId(fallback ? fallback.id : null);
  }, [analysis, selection, setSelection, sketches]);

  const onRequestEdits = useCallback(() => {
    if (!analysis) return;
    setDeckMenu(null);
    // Drop a prefilled deck-edit prompt into the rail input and
    // focus it. The text points the model at the analysis page +
    // slide files so it has a concrete starting point; the user
    // appends what they actually want changed and presses enter.
    const slideRefs = (analysis.slides || [])
      .map((sid) => `  · ${sid} → .workbench/sketches/${sid}.json`)
      .join("\n");
    const prompt = (
      `Edit the deck at ${analysis.path}.\n\n` +
      `Slides (Excalidraw scenes, one .json per sketch id):\n${slideRefs}\n\n` +
      `Tools available:\n` +
      `  · author_slide(layout, slots, sketch_id=<id>) — overwrite a slide's scene\n` +
      `  · append_slide(slug, sketch_id) — add a new slide to the deck\n` +
      `  · Read the analysis page first to see slides:, sources:, and prose.\n\n` +
      `Edits I want:\n  · `
    );
    window.dispatchEvent(new CustomEvent("sy:rail-set-input", {
      detail: { text: prompt, focus: true },
    }));
  }, [analysis]);

  const onExport = useCallback(async (fmt: "pptx" | "html") => {
    if (!analysis) return;
    setDeckMenu(null);
    try {
      const r = await fetch(`/api/decks/export/${fmt}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: analysis.path }),
      });
      if (!r.ok) {
        const eb = await r.json().catch(() => ({} as Record<string, string>));
        window.alert(`Export to ${fmt} failed: ${eb.error ?? r.status}`);
        return;
      }
      const j = (await r.json()) as { path?: string };
      window.dispatchEvent(new CustomEvent("sy:rail-system-tip", {
        detail: { text: `Saved deck as \`${j.path ?? `vault/exports/…${fmt}`}\``, focus: false },
      }));
    } catch (e) {
      window.alert(`Export to ${fmt} failed: ${(e as Error).message}`);
    }
  }, [analysis]);

  const onRepopulate = useCallback(async () => {
    if (!analysis) return;
    setDeckMenu(null);
    try {
      const r = await fetch("/api/analysis/populate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ analysis_path: analysis.path }),
      });
      if (!r.ok) {
        window.alert(`Repopulate failed: HTTP ${r.status}`);
        return;
      }
      const j = (await r.json()) as { run_id?: string };
      if (j.run_id) {
        // Same spinner-tagging path the initial populate uses, so
        // the deck badge shows the autopopulating indicator and the
        // user can jump to the live transcript in Agents.
        setDeckRun(analysis.path, j.run_id);
      }
    } catch (e) {
      window.alert(`Repopulate failed: ${(e as Error).message}`);
    }
  }, [analysis]);

  const onDeleteDeck = useCallback(async () => {
    if (!analysis) return;
    setConfirmDeleteDeck(false);
    try {
      const r = await fetch(
        `/api/analysis?path=${encodeURIComponent(analysis.path)}`,
        { method: "DELETE" },
      );
      if (!r.ok) {
        window.alert(`Delete deck failed: HTTP ${r.status}`);
        return;
      }
    } catch (e) {
      window.alert(`Delete deck failed: ${(e as Error).message}`);
      return;
    }
    // Drop deck-mode + clear any breadcrumb/spinner state. The
    // selection/page that pinned us into deck mode is gone, so
    // the empty-state branch will render until the user picks a
    // new sketch or analysis.
    clearDeckRun(analysis.path);
    setAnalysis(null);
    setActive(null);
    setActiveId(null);
    if (selection?.kind === "page" && selection.path === analysis.path) {
      setSelection(null);
    }
    await reloadList();
  }, [analysis, reloadList, selection, setSelection]);

  const onMoveSubmit = useCallback(async () => {
    if (moveDraft === null || !active || !analysis) return;
    const dest1 = parseInt(moveDraft.trim(), 10);
    if (!Number.isFinite(dest1)) {
      setMoveDraft(null);
      return;
    }
    const here0 = analysis.slides.indexOf(active.id);
    if (here0 < 0) { setMoveDraft(null); return; }
    const dest0 = Math.max(
      0,
      Math.min(analysis.slides.length - 1, dest1 - 1),
    );
    if (dest0 === here0) { setMoveDraft(null); return; }
    // Splice-out then splice-in: stable across move-up vs move-down.
    const next = analysis.slides.slice();
    const [moved] = next.splice(here0, 1);
    next.splice(dest0, 0, moved);
    try {
      await fetch("/api/analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: analysis.path, slides: next }),
      });
      setAnalysis({ ...analysis, slides: next });
    } catch (e) {
      window.alert(`Move failed: ${(e as Error).message}`);
    }
    setMoveDraft(null);
  }, [moveDraft, active, analysis]);

  // ←/→ as global slide nav, but ONLY when the user isn't typing
  // into something. Excalidraw and drawio both rely on arrow keys
  // for canvas operations (panning, nudging selection), so we also
  // skip when the canvas itself owns focus. Heuristic: anything
  // inside an editable element or inside the canvas host bails.
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
      if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
      const t = document.activeElement;
      if (!t) return;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA") return;
      const el = t as HTMLElement;
      if (el.isContentEditable) return;
      if (el.closest(".sy-sketch-host")) return;  // canvas owns arrows
      goTo(ev.key === "ArrowLeft" ? -1 : 1);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [goTo]);

  // Drop any in-flight rename when the active sketch changes —
  // editing slide A's title should never bleed into slide B.
  useEffect(() => { setNameDraft(null); }, [active?.id]);

  const commitRename = useCallback(() => {
    if (nameDraft === null) return;
    const trimmed = nameDraft.trim();
    setNameDraft(null);
    if (!active || !trimmed || trimmed === active.name) return;
    void persist({ name: trimmed });
  }, [active, nameDraft, persist]);

  // "Clear" replaces the active sketch's scene with an empty one.
  // Destructive but reversible via Cmd-Z within the 5 s autosave
  // window — that's the whole reason the autosave is debounced.
  // Drawio's reset is a re-init through the iframe protocol; we
  // signal that via a kind-specific reset event.
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
    // Bump the canvas key so the embedded tool re-reads initialData
    // and renders the now-empty scene.
    setClearVersion((v) => v + 1);
  }, [active, persist]);

  // Image-deck mode (a .pptx rendered to PNGs, etc.) skips every
  // Sketcher control surface and renders a standalone deck viewer.
  // Hooks above this branch keep firing in stable order so React
  // doesn't blow up on a kind-flip mid-session.
  if (selection?.kind === "image-deck") {
    return (
      <ImageDeckViewer
        selection={selection}
        onClose={() => setSelection(null)}
      />
    );
  }

  // ── Toolbar ────────────────────────────────────────────────────────
  return (
    <div className="sy-sketch">
      <div className="sy-sketch-toolbar">
        <button
          type="button"
          className="sy-vega-nav"
          onClick={() => goTo(-1)}
          disabled={deckSketches.length < 2}
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
            {idx >= 0 && deckSketches.length > 0
              ? `${idx + 1} / ${deckSketches.length}${analysis ? " · in deck" : ""}`
              : ""}
            {active && (
              <span className="sy-sketch-kind"> · {active.kind}</span>
            )}
          </span>
          {analysis && (
            <span
              className="sy-sketch-deck-badge"
              data-tip="Click to open deck menu"
              title={`${analysis.path}`}
              role="button"
              tabIndex={0}
              aria-haspopup="menu"
              aria-expanded={Boolean(deckMenu)}
              aria-label={`Deck: ${analysis.title}. Click to open deck menu.`}
              onClick={(e) => openDeckMenu(e, "pointer")}
              onContextMenu={(e) => openDeckMenu(e, "pointer")}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  // Synthetic position: under the badge centre.
                  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
                  setDeckMenu({ x: r.left, y: r.bottom + 6 });
                }
              }}
            >
              deck: {analysis.title}
              {populateRunId && (
                <button
                  type="button"
                  className="sy-deck-spinner"
                  onClick={(e) => {
                    e.stopPropagation();
                    onSpinnerClick();
                  }}
                  title="Autopopulating slides — click to open the live transcript in Agents"
                  aria-label="Autopopulating slides"
                />
              )}
              <button
                type="button"
                className="sy-sketch-deck-close"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onCloseDeck();
                }}
                title="Exit deck mode — drop back to the Sketch library. The deck file stays on disk."
                aria-label="Close deck"
              >×</button>
            </span>
          )}
        </div>
        <button
          type="button"
          className="sy-vega-nav"
          onClick={() => goTo(1)}
          disabled={deckSketches.length < 2}
          title="Next sketch"
        >→</button>
        <button
          ref={pickerBtnRef}
          type="button"
          className="sy-vega-nav sy-vega-nav--picker"
          onClick={(e) => {
            // Stop bubbling so the window-level close-on-outside
            // handler (attached when the picker is already open)
            // doesn't fire on this same event and immediately undo
            // the open we're about to schedule.
            e.stopPropagation();
            setPickerOpen((v) => {
              const next = !v;
              if (next && pickerBtnRef.current) {
                const r = pickerBtnRef.current.getBoundingClientRect();
                // Drop the panel just below + right-aligned to the
                // toggle. 320px is the picker width (matches CSS).
                setPickerAnchor({
                  top: r.bottom + 6,
                  left: Math.max(8, r.right - 320),
                });
              }
              return next;
            });
          }}
          disabled={deckSketches.length === 0}
          aria-haspopup="true"
          aria-expanded={pickerOpen}
          title="Browse all slides"
        >▾</button>
        <span className="sy-spacer" />
        {saveStatus && <span className="sy-sketch-save">{saveStatus}</span>}
        {active && (
          <button
            type="button"
            className="sy-vega-toolbar-btn"
            onClick={() => void onDuplicate()}
            title={
              analysis
                ? "Duplicate this slide; the copy lands immediately after"
                : "Duplicate this sketch"
            }
          >Duplicate</button>
        )}
        {active && analysis && deckSketches.length > 1 && (
          <button
            type="button"
            className="sy-vega-toolbar-btn"
            onClick={() => setMoveDraft(String(idx + 1))}
            title="Move this slide to a different position in the deck"
          >Move</button>
        )}
        {analysis && (
          <button
            type="button"
            className="sy-vega-toolbar-btn"
            onClick={onRequestEdits}
            title="Drop a deck-edit primer into the rail and focus the cursor — describe what you want changed in plain English"
          >Edits…</button>
        )}
        {analysis && (
          <button
            ref={deckMenuBtnRef}
            type="button"
            className={
              "sy-vega-toolbar-btn sy-sketch-deck-menu-btn"
              + (deckMenu ? " sy-vega-toolbar-btn--active" : "")
            }
            onClick={(e) => {
              if (deckMenu) {
                e.stopPropagation();
                setDeckMenu(null);
              } else {
                openDeckMenu(e, "button");
              }
            }}
            aria-haspopup="menu"
            aria-expanded={Boolean(deckMenu)}
            title="Deck menu — regenerate, export, close, delete"
          >
            Deck ▾
          </button>
        )}
        <button
          type="button"
          className="sy-vega-toolbar-btn"
          onClick={() => setCreating({ name: "", kind: "excalidraw" })}
          title={
            analysis
              ? `Add a sketch and append it to "${analysis.title}"`
              : "Start a new sketch"
          }
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
      {deckMenu && analysis && (
        <ul
          className="sy-context-menu sy-sketch-deck-menu"
          role="menu"
          style={{ top: deckMenu.y, left: deckMenu.x }}
          onClick={(e) => e.stopPropagation()}
        >
          <li
            role="menuitem"
            className="sy-context-menu-item"
            onClick={() => { void onRepopulate(); }}
            title="Re-run the autopopulate agent against this deck’s placeholders"
          >
            Regenerate deck
          </li>
          <li
            role="menuitem"
            className="sy-context-menu-item"
            onClick={onRequestEdits}
            title="Drop into the rail chat with a prefilled edit prompt"
          >
            Request edits…
          </li>
          <li
            role="menuitem"
            className="sy-context-menu-item"
            onClick={() => { void onExport("pptx"); }}
            title="Render this deck as a PowerPoint file in vault/exports/"
          >
            ↓ Save as .pptx
          </li>
          <li
            role="menuitem"
            className="sy-context-menu-item"
            onClick={() => { void onExport("html"); }}
            title="Render this deck as a single-file reveal.js HTML in vault/exports/"
          >
            ↓ Save as .html
          </li>
          <li
            role="menuitem"
            className="sy-context-menu-item"
            onClick={onCloseDeck}
            title="Exit deck mode without deleting the deck"
          >
            Close deck
          </li>
          <li
            role="menuitem"
            className="sy-context-menu-item sy-context-menu-item--danger"
            onClick={() => {
              setDeckMenu(null);
              setConfirmDeleteDeck(true);
            }}
          >
            Delete deck…
          </li>
        </ul>
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
            {analysis ? (
              <>Slides in <strong>{analysis.title}</strong> ({deckSketches.length})</>
            ) : (
              <>All sketches ({deckSketches.length})</>
            )}
          </div>
          <ul className="sy-sketch-picker-list">
            {deckSketches.map((s, i) => (
              <li
                key={s.id}
                className={
                  "sy-sketch-picker-row" +
                  (s.id === activeId ? " sy-sketch-picker-row--active" : "")
                }
                // mousedown (not click): the window click-outside
                // listener that closes the picker can race the row's
                // click and drop the select — empty/placeholder rows
                // then look "not selectable". mousedown fires first.
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
                      // No PNG yet (autopopulate hasn't rendered, or
                      // empty placeholder). Show a dashed empty frame
                      // instead of a broken-image icon so the row
                      // still reads as a real, clickable slide.
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
      {confirmDeleteDeck && analysis && (
        <div
          className="sy-confirm-backdrop"
          onClick={() => setConfirmDeleteDeck(false)}
        >
          <div
            className="sy-confirm"
            role="dialog"
            aria-labelledby="sy-sketch-delete-deck-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div id="sy-sketch-delete-deck-title" className="sy-confirm-title">
              Delete deck
            </div>
            <div className="sy-confirm-body">
              <p>
                <strong>{analysis.title}</strong> ({analysis.slides.length}{" "}
                slide{analysis.slides.length === 1 ? "" : "s"}) will be removed:
              </p>
              <ul style={{ margin: "8px 0 0 18px", padding: 0, fontSize: 12 }}>
                <li>any in-flight populate agent for this deck is cancelled</li>
                <li>every member sketch + its PNG export deleted</li>
                <li>the analysis page at <code>{analysis.path}</code> deleted</li>
              </ul>
            </div>
            <div className="sy-confirm-actions">
              <button
                type="button"
                className="sy-confirm-btn"
                onClick={() => setConfirmDeleteDeck(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="sy-confirm-btn sy-confirm-btn--primary"
                onClick={() => void onDeleteDeck()}
              >
                Delete deck
              </button>
            </div>
          </div>
        </div>
      )}
      {moveDraft !== null && active && analysis && (
        <div
          className="sy-confirm-backdrop"
          onClick={() => setMoveDraft(null)}
        >
          <div
            className="sy-confirm"
            role="dialog"
            aria-labelledby="sy-sketch-move-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div id="sy-sketch-move-title" className="sy-confirm-title">
              Move slide
            </div>
            <div className="sy-confirm-body">
              <p>
                <strong>{active.name}</strong> is currently slide{" "}
                <strong>{idx + 1}</strong> of <strong>{deckSketches.length}</strong>.
                Enter a destination position (1–{deckSketches.length}).
              </p>
              <input
                type="number"
                inputMode="numeric"
                min={1}
                max={deckSketches.length}
                step={1}
                autoFocus
                className="sy-ws-input"
                value={moveDraft}
                onChange={(e) => setMoveDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void onMoveSubmit();
                  }
                  if (e.key === "Escape") {
                    e.preventDefault();
                    setMoveDraft(null);
                  }
                }}
              />
            </div>
            <div className="sy-confirm-actions">
              <button
                type="button"
                className="sy-confirm-btn"
                onClick={() => setMoveDraft(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="sy-confirm-btn sy-confirm-btn--primary"
                onClick={() => void onMoveSubmit()}
              >
                Move
              </button>
            </div>
          </div>
        </div>
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
        {!creating && !active && analysis && analysis.slides.length === 0 && (
          <div className="sy-vega-empty">
            <h2>No slides in “{analysis.title}” yet</h2>
            <p>
              This deck’s <code>slides:</code> list is empty — usually a
              failed autopopulate left the placeholders behind as
              library orphans. Click <strong>Deck ▾</strong> in the
              toolbar → <strong>Regenerate deck</strong> to re-scaffold
              and fill placeholders, or <strong>+ Add Sketch</strong>
              to author the first slide by hand. Source:{" "}
              <code>{analysis.path}</code>.
            </p>
          </div>
        )}
        {!creating && !active && !analysis && sketches && sketches.length === 0 && (
          <div className="sy-vega-empty">
            <h2>No sketches yet</h2>
            <p>
              Click <strong>+ Add Sketch</strong> to start one. Sketches save to
              <code> .workbench/sketches/</code> as JSON; PNG exports go
              to <code>figures/</code> alongside the rest of the workspace
              for easy embedding in docs. Open a doc and hit
              <strong> → Slides</strong> in the Editor to scaffold a deck
              from its headings.
            </p>
          </div>
        )}
        {!creating && !active && !analysis && sketches && sketches.length > 0 && (
          <div className="sy-vega-empty">
            <h2>Deck closed</h2>
            <p>
              You closed the deck — every workspace sketch belongs to a
              dismissed deck. Click <strong>+ Add Sketch</strong> to start
              fresh, or pick a sketch from the <strong>▾</strong> dropdown
              to reopen it (deck mode will re-engage automatically).
            </p>
          </div>
        )}
      </div>
      {/* Presenter notes for the active slot — deck mode only. Keyed by
          activeId so it re-seeds per slide and flushes a pending save on
          slot switch (unmount). Written into the pptx (notes page) and
          html (reveal speaker notes) exports. */}
      {analysis && activeId && (
        <SlotNotes
          key={activeId}
          analysisPath={analysis.path}
          sketchId={activeId}
          initial={analysis.slide_notes?.[activeId] ?? ""}
          onSaved={(id, text) =>
            setAnalysis((a) =>
              a ? { ...a, slide_notes: { ...(a.slide_notes ?? {}), [id]: text } } : a,
            )
          }
        />
      )}
    </div>
  );
}


// ── Presenter notes (deck mode) ─────────────────────────────────────


function SlotNotes(props: {
  analysisPath: string;
  sketchId: string;
  initial: string;
  onSaved: (sketchId: string, text: string) => void;
}) {
  const { analysisPath, sketchId, initial, onSaved } = props;
  const [text, setText] = useState(initial);
  const [status, setStatus] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef(initial);
  const saved = useRef(initial);

  const save = useCallback(async (t: string) => {
    try {
      const r = await fetch("/api/analysis/note", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: analysisPath, sketch_id: sketchId, note: t }),
      });
      if (!r.ok) { setStatus("save failed"); return; }
      saved.current = t;
      setStatus("saved");
      onSaved(sketchId, t);
    } catch {
      setStatus("save failed");
    }
  }, [analysisPath, sketchId, onSaved]);

  // Flush a pending edit when switching slots (this component unmounts
  // on activeId change because it's keyed by it).
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
    if (latest.current !== saved.current) void save(latest.current);
  }, [save]);

  const onChange = (t: string) => {
    setText(t);
    latest.current = t;
    setStatus("…");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => void save(t), 1000);
  };

  return (
    <div className="sy-sketch-notes">
      <div className="sy-sketch-notes-head">
        <span className="sy-sketch-notes-label">Presenter notes</span>
        {status && <span className="sy-sketch-notes-status">{status}</span>}
      </div>
      <textarea
        className="sy-sketch-notes-area"
        value={text}
        onChange={(e) => onChange(e.target.value)}
        onBlur={() => {
          if (timer.current) clearTimeout(timer.current);
          if (latest.current !== saved.current) void save(latest.current);
        }}
        placeholder="Presenter notes for this slide — written into the pptx (notes page) and html (reveal speaker view) exports."
        spellCheck
      />
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
