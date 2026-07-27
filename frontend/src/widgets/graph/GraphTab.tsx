import { useEffect, useMemo, useRef, useState } from "react";
import { mountGraph } from "./init";
import type { GraphData } from "./types";
import { useSelection } from "../../selection/SelectionContext";
import { useTabs } from "../../center/TabsContext";
import { ingestFile } from "../../lib/ingest";
import CurationReplay from "./CurationReplay";

type Props = {
  data: GraphData | null;
  error: string | null;
  /** Zen mode: page selections open in the right-pane Editor, so the
   *  in-graph doc modal must never open (Power keeps it). Focus /
   *  sidebar-highlight still track the selection. */
  suppressDocModal?: boolean;
  /** Zen mode: show a `+` add-file button next to the ↻/✂ toolbar
   *  icons. Power has this affordance in the Browser sidebar, so it's
   *  off there. */
  showAddFile?: boolean;
};

export default function GraphTab({ data, error, suppressDocModal, showAddFile }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const addFileInputRef = useRef<HTMLInputElement>(null);
  const [addingFile, setAddingFile] = useState(false);
  // The curation replay is OPT-IN now (top-left ↻ button) — it
  // never auto-mounts on workspace load. First-load shows the
  // "Building bundle…" placeholder until data arrives, then the
  // real graph; the user can summon the replay overlay at any
  // time afterwards.
  const [showReplay, setShowReplay] = useState(false);
  const [replayDone, setReplayDone] = useState(false);
  const [replayFading, setReplayFading] = useState(false);
  // Bumped on each replay click so CurationReplay rebuilds its
  // simulation from scratch.
  const [replayKey, setReplayKey] = useState(0);
  useEffect(() => {
    if (replayDone && showReplay) {
      setReplayFading(true);
      const id = window.setTimeout(() => setShowReplay(false), 1500);
      return () => window.clearTimeout(id);
    }
  }, [replayDone, showReplay]);
  const triggerReplay = () => {
    setReplayDone(false);
    setReplayFading(false);
    setShowReplay(true);
    setReplayKey((k) => k + 1);
  };

  // Zen add-file: same ingest pipeline + Agents-jump as the Power
  // sidebar's `+`. The sy:open-agents-run handler (App) is Zen-aware,
  // so it opens the Agents surface with the run auto-expanded.
  const onAddFileChosen = async (ev: React.ChangeEvent<HTMLInputElement>) => {
    const file = ev.target.files?.[0];
    ev.target.value = "";
    if (!file) return;
    setAddingFile(true);
    try {
      const runId = await ingestFile(file);
      if (!runId) {
        window.dispatchEvent(new CustomEvent("sy:toast", {
          detail: { text: `Couldn't ingest ${file.name}`, err: true },
        }));
        return;
      }
      window.dispatchEvent(new CustomEvent("sy:open-agents-run", {
        detail: { run_id: runId },
      }));
    } catch (e) {
      window.dispatchEvent(new CustomEvent("sy:toast", {
        detail: { text: `Ingest failed: ${(e as Error).message}`, err: true },
      }));
    } finally {
      setAddingFile(false);
    }
  };

  // Track which dataset is currently mounted so a workspace switch
  // (new GraphData reference) re-mounts the CE modules without
  // forcing a full page reload. Module-level state inside CE's
  // graph.js lives across re-mounts; mountGraph resets the
  // container DOM and calls each module's `init(data)` afresh.
  const mountedDataRef = useRef<GraphData | null>(null);
  const [mounted, setMounted] = useState(false);
  const { selection, setSelection } = useSelection();
  const { switchToKind, tabs } = useTabs();
  const hasEditor = useMemo(() => tabs.some((t) => t.kind === "markdown"), [tabs]);

  // ── Split mode (D4): one review surface for both gestures ──────
  // null = off; otherwise the live selection with per-node policy.
  const [splitSel, setSplitSel] = useState<
    Array<{ id: string; policy: "move" | "copy" }> | null
  >(null);
  const [splitName, setSplitName] = useState("");
  const [splitBusy, setSplitBusy] = useState(false);
  const [splitError, setSplitError] = useState<string | null>(null);
  const splitActive = splitSel !== null;

  const enterSplit = (seed: Array<string | { id: string; policy?: "move" | "copy" }> = []) => {
    setSplitError(null);
    setSplitSel([]);
    try {
      window.Graph.splitEnter(seed, (sel) => setSplitSel(sel));
    } catch { /* older bundle */ }
  };
  const exitSplit = () => {
    try { window.Graph.splitExit(); } catch { /* ignore */ }
    setSplitSel(null);
    setSplitName("");
    setSplitError(null);
  };

  // Agent-driven gesture: a split proposal arrives (rail tool /
  // event) with a pre-highlighted page set — same surface, seeded.
  useEffect(() => {
    const onPropose = (ev: Event) => {
      const detail = (ev as CustomEvent<{ pages?: string[] }>).detail;
      if (detail?.pages?.length) enterSplit(detail.pages);
    };
    window.addEventListener("sy:split-proposal", onPropose);
    return () => window.removeEventListener("sy:split-proposal", onPropose);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submitSplit = async () => {
    if (!splitSel || splitSel.length === 0 || !splitName.trim() || splitBusy) return;
    setSplitBusy(true);
    setSplitError(null);
    try {
      const r = await fetch("/api/workspaces/split", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: splitName.trim(),
          move: splitSel.filter((s) => s.policy === "move").map((s) => s.id),
          copy: splitSel.filter((s) => s.policy === "copy").map((s) => s.id),
        }),
      });
      const b = await r.json().catch(() => ({} as { error?: string }));
      if (!r.ok) {
        setSplitError(b.error ?? `HTTP ${r.status}`);
        return;
      }
      exitSplit();
    } catch (e) {
      setSplitError((e as Error).message);
    } finally {
      setSplitBusy(false);
    }
  };

  // Mount / re-mount CE viewer when data arrives or changes
  // (e.g. workspace switch). Modal-close → clear selection
  // (wired here so the callback can capture setSelection).
  useEffect(() => {
    if (!data || !containerRef.current) return;
    if (mountedDataRef.current === data) return;
    mountedDataRef.current = data;
    mountGraph(containerRef.current, data);
    if (window.Modal && window.Modal.setOnClose) {
      window.Modal.setOnClose(() => {
        try { window.Graph.clearFocus(); } catch { /* ignore */ }
        setSelection(null);
      });
    }
    setMounted(true);
  }, [data, setSelection]);

  // Drive CE modules from the selection layer.
  useEffect(() => {
    if (!mounted) return;
    if (!selection || selection.kind !== "page") {
      if (!suppressDocModal) {
        try { window.Modal.close(); } catch { /* ignore */ }
      }
      try { window.Graph.clearFocus(); } catch { /* ignore */ }
      return;
    }
    if (!suppressDocModal) {
      try { window.Modal.open(selection.id); } catch { /* ignore */ }
    }
    try { window.Graph.focus(selection.id); } catch { /* ignore */ }
    try { window.Sidebar.setActive(selection.id); } catch { /* ignore */ }
  }, [selection, mounted, suppressDocModal]);

  if (error) {
    return (
      <div className="sy-placeholder">
        <h2>Graph unavailable</h2>
        <p>{error}</p>
        <p>Switch Bay's graph tab needs a curiosity-engine workspace (a folder with a <code>wiki/</code> subdirectory).</p>
        <button
          type="button"
          className="sy-vega-toolbar-btn"
          style={{ marginTop: 12 }}
          onClick={() => window.dispatchEvent(new CustomEvent("sy:graph-reload"))}
        >
          Retry
        </button>
      </div>
    );
  }
  if (!data) {
    // First-load / workspace-switch placeholder. The animation is
    // opt-in via the replay button (which only appears once data
    // is ready) so cold loads stay quiet instead of getting
    // distracted by the unfinished history.
    return (
      <div className="sy-placeholder">
        <h2>Graph</h2>
        <p>Building bundle (running <code>viewer.sh build</code>)…</p>
      </div>
    );
  }
  return (
    <div className="sy-graph-host">
      {hasEditor && selection?.kind === "page" && (
        <button
          type="button"
          className="sy-tab-swap"
          data-tour="graph-editor-jump"
          onClick={() => switchToKind("markdown")}
          title="Open the current page in the Editor tab"
        >
          ↗ Editor
        </button>
      )}
      <button
        type="button"
        className="sy-graph-replay-btn"
        data-tour="graph-replay"
        onClick={triggerReplay}
        title="Replay the curation history animation"
        aria-label="Replay curation history"
        disabled={showReplay}
      >
        ↻
      </button>
      <button
        type="button"
        className={"sy-graph-split-btn" + (splitActive ? " sy-graph-split-btn--on" : "")}
        onClick={() => (splitActive ? exitSplit() : enterSplit())}
        title={splitActive
          ? "Exit split mode (selection discarded)"
          : "Split this workspace: click nodes (⌘/Ctrl-drag for many) to pick what leaves"}
        aria-label="Split workspace mode"
      >
        ✂
      </button>
      {showAddFile && (
        <>
          <button
            type="button"
            className="sy-graph-add-btn"
            onClick={() => addFileInputRef.current?.click()}
            disabled={addingFile}
            title="Add a file — ingests it into this workspace"
            aria-label="Add a file"
          >
            {addingFile ? "…" : "+"}
          </button>
          <input
            ref={addFileInputRef}
            type="file"
            style={{ display: "none" }}
            onChange={(e) => void onAddFileChosen(e)}
          />
        </>
      )}
      <div ref={containerRef} className="sy-graph-mount" />
      {splitActive && (
        <div className="sy-split-bar">
          <span className="sy-split-bar-count">
            {splitSel!.filter((s) => s.policy === "move").length} move ·{" "}
            {splitSel!.filter((s) => s.policy === "copy").length} copy
          </span>
          <span className="sy-split-bar-hint" title="Click a node to add/remove it. ⌘/Ctrl-drag rubber-bands a region. Right-click (or ⌥-click) flips move ↔ copy — dashed green = copied to both sides; solid amber = moves out. Right-clicking an unselected node selects it with the flipped policy. Entities/concepts default to copy — shared reference material usually belongs on both sides.">
            click · ⌘drag · right-click flips
          </span>
          <input
            type="text"
            className="sy-split-bar-name"
            placeholder="new workspace name"
            value={splitName}
            onChange={(e) => setSplitName(e.target.value)}
            spellCheck={false}
            disabled={splitBusy}
          />
          <button
            type="button"
            className="sy-split-bar-go"
            onClick={() => void submitSplit()}
            disabled={splitBusy || splitSel!.length === 0 || !splitName.trim()}
            title="Build the new workspace in the background (moved pages go to the Trash here; a toast lands when it's ready)"
          >
            {splitBusy ? "Splitting…" : "Split"}
          </button>
          <button
            type="button"
            className="sy-split-bar-cancel"
            onClick={exitSplit}
            disabled={splitBusy}
          >
            Cancel
          </button>
          {splitError && <span className="sy-split-bar-err">{splitError}</span>}
        </div>
      )}
      {!showReplay && (
        <div className="sy-graph-count">
          {(data.nodes?.length ?? 0)} nodes ·{" "}
          {(data.edges?.length ?? 0)} edges
        </div>
      )}
      {showReplay && (
        <CurationReplay
          replayKey={replayKey}
          onDone={() => setReplayDone(true)}
          fading={replayFading}
        />
      )}
    </div>
  );
}
