import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import type { GraphData } from "../widgets/graph/types";
import type { Selection } from "../ws";
import type { UiMode } from "../layout/ModeToggle";
import { UI_MODE_KEY } from "../layout/ModeToggle";

/**
 * Interactive product tour — spotlight coach-marks over the live UI.
 * Invoked by `/walkthrough` or once on first install (server marker
 * `walkthrough-shown`). Esc / ✕ exits from any step and marks done so
 * auto-start never loops. No heavy tour library (charter).
 */

export type WalkCtx = {
  graphData: GraphData | null;
  switchToKind: (kind: string) => boolean;
  setSelection: (s: Selection | null) => void;
  setSettingsOpen: (open: boolean) => void;
  setUiMode: (mode: UiMode) => void;
  uiMode: UiMode;
};

type Step = {
  id: string;
  title: string;
  body: string;
  /** Primary spotlight selector (CSS). Optional for centered end card. */
  target?: string;
  /** Extra rings drawn at lower emphasis. */
  targets?: string[];
  requireMode?: "power" | "zen";
  enter?: (ctx: WalkCtx) => void | Promise<void>;
  leave?: (ctx: WalkCtx) => void | Promise<void>;
};

const PAD = 8;

function setMode(mode: UiMode) {
  try { localStorage.setItem(UI_MODE_KEY, mode); } catch { /* quota */ }
  window.dispatchEvent(new CustomEvent("sy:ui-mode", { detail: { mode } }));
}

function pickHighestDegree(g: GraphData | null): GraphData["nodes"][number] | null {
  const nodes = g?.nodes ?? [];
  if (!nodes.length) return null;
  let best = nodes[0]!;
  for (const n of nodes) {
    if ((n.degree ?? 0) > (best.degree ?? 0)) best = n;
  }
  return best;
}

function sleep(ms: number) {
  return new Promise<void>((r) => window.setTimeout(r, ms));
}

function buildSteps(): Step[] {
  return [
    {
      id: "settings",
      title: "Settings",
      body:
        "Configure LLM access here — provider keys, the model ladder, "
        + "and storage. Without a provider, agents stay quiet.",
      target: "[data-tour='settings']",
      requireMode: "power",
      enter: async (ctx) => {
        setMode("power");
        ctx.setSettingsOpen(true);
        await sleep(280);
      },
      leave: (ctx) => { ctx.setSettingsOpen(false); },
    },
    {
      id: "add-files",
      title: "Add files",
      body:
        "Drop files or a folder onto the Browser, or use the + upload "
        + "control. Each file is staged into the vault and a background "
        + "ingest agent extracts wiki pages.",
      target: "[data-tour='add-files']",
      targets: ["[data-tour='browser']"],
      requireMode: "power",
      enter: (ctx) => {
        ctx.setSettingsOpen(false);
        setMode("power");
      },
    },
    {
      id: "curate",
      title: "Curate",
      body:
        "Starts an agent that curates knowledge from your files — "
        + "linking, classifying, and growing the knowledge graph. "
        + "Same as typing /curate in the rail.",
      target: "[data-tour='curate']",
      requireMode: "power",
    },
    {
      id: "chat",
      title: "Chat",
      body:
        "Talk to the rail agent here. Ask what the wiki knows, request "
        + "plots or decks, or type a slash command (/ to autocomplete).",
      target: "[data-tour='chat']",
      requireMode: "power",
    },
    {
      id: "terminal",
      title: "Terminal",
      body:
        "Need a shell? Click >_ for a new terminal thread, or prefix a "
        + "line with ! to run a command. The dashboard (⌘J) shows every "
        + "running agent and shell.",
      target: "[data-tour='terminal']",
      requireMode: "power",
    },
    {
      id: "browser",
      title: "Wiki browser",
      body:
        "The Browser lists wiki pages by type — analyses, concepts, "
        + "entities, evidence, facts, figures, tables, sources, notes, "
        + "todos — plus the on-disk Files and provenance Sources views.",
      target: "[data-tour='browser']",
      requireMode: "power",
    },
    {
      id: "graph",
      title: "Graph",
      body:
        "The knowledge graph. Hit ↻ anytime to replay how the curator "
        + "grew the wiki. Click a node to open its page.",
      target: "[data-tour='graph-replay']",
      requireMode: "power",
      enter: async (ctx) => {
        setMode("power");
        ctx.switchToKind("graph");
        await sleep(200);
      },
    },
    {
      id: "node-modal",
      title: "Node → tools",
      body:
        "A page opens in the graph modal. From here you can jump to the "
        + "Editor, scaffold or open a Sketch deck, or send tables to "
        + "Sheet/Plot. (On an empty wiki this step is a preview — "
        + "curate first, or use the sample workspace when shipped.)",
      target: "[data-tour='node-modal']",
      targets: ["[data-tour='graph-editor-jump']", "#modal-slides", ".sy-tab-swap"],
      requireMode: "power",
      enter: async (ctx) => {
        setMode("power");
        ctx.switchToKind("graph");
        const hub = pickHighestDegree(ctx.graphData);
        if (hub) {
          const page = ctx.graphData?.pages[hub.id];
          ctx.setSelection({
            kind: "page",
            id: hub.id,
            path: page?.path ?? hub.path ?? hub.id,
          });
          // CE modal opens from selection via GraphTab effect.
          await sleep(350);
        } else {
          await sleep(100);
        }
      },
      leave: (ctx) => {
        try { (window as unknown as { Modal?: { close?: () => void } }).Modal?.close?.(); } catch { /* */ }
        ctx.setSelection(null);
      },
    },
    {
      id: "table",
      title: "Table",
      body:
        "The wiki lives in a queryable database. The Table tab runs "
        + "SQL (DuckDB) directly against it — useful for inventories, "
        + "joins, and exports.",
      target: "[data-tour-tab-kind='duckdb']",
      requireMode: "power",
      enter: async (ctx) => {
        try { (window as unknown as { Modal?: { close?: () => void } }).Modal?.close?.(); } catch { /* */ }
        ctx.setSelection(null);
        ctx.switchToKind("duckdb");
        await sleep(200);
      },
    },
    {
      id: "new-tab",
      title: "+ New…",
      body:
        "Need a custom surface? + New… drops a how-to in the rail. "
        + "You can clone a tab, describe a new kind, or install an "
        + "extension pack — pin results globally or per workspace.",
      target: "[data-tour='new-tab']",
      requireMode: "power",
      enter: (ctx) => { ctx.switchToKind("graph"); },
    },
    {
      id: "zen-switch",
      title: "Zen mode",
      body:
        "Prefer a quieter layout? Flip to Zen — graph on the left, "
        + "one surface on the right, chat floating over both. Same "
        + "workbench, less chrome.",
      target: "[data-tour='mode-toggle']",
      requireMode: "power",
    },
    {
      id: "zen-chat",
      title: "Chat & terminal live here",
      body:
        "In Zen, the floating box is your chat. Type ! or open a shell "
        + "thread for a terminal in the same place — promote it to the "
        + "right pane when you need full height.",
      target: "[data-tour='zen-chat']",
      requireMode: "zen",
      enter: async () => {
        setMode("zen");
        await sleep(320);
      },
    },
    {
      id: "zen-tabs",
      title: "Tabs live here",
      body:
        "Surfaces (Editor, Table, Sketch, Agents, …) switch from this "
        + "dropdown — no full tab strip. Artifacts never auto-steal "
        + "focus; a pulse badge jumps you when you're ready.",
      target: "[data-tour='zen-tabs']",
      requireMode: "zen",
    },
    {
      id: "power-return",
      title: "Back to Power",
      body:
        "Flip the same control to return to the full three-column "
        + "workbench — Browser · Tabs · Rail. Mode is remembered per "
        + "browser.",
      target: "[data-tour='mode-toggle']",
      requireMode: "zen",
    },
    {
      id: "done",
      title: "Happy Exploring!",
      body:
        "You're set. Re-run this tour anytime with /walkthrough. "
        + "Open /intro for the full product deck and benchmark story.",
      requireMode: "power",
      enter: async () => {
        setMode("power");
        await sleep(280);
      },
    },
  ];
}

type Rect = { top: number; left: number; width: number; height: number };

function measure(sel: string | undefined): Rect | null {
  if (!sel) return null;
  const el = document.querySelector(sel) as HTMLElement | null;
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width < 2 && r.height < 2) return null;
  return {
    top: r.top - PAD,
    left: r.left - PAD,
    width: r.width + PAD * 2,
    height: r.height + PAD * 2,
  };
}

type Props = {
  open: boolean;
  onClose: () => void;
  ctx: WalkCtx;
};

export default function Walkthrough({ open, onClose, ctx }: Props) {
  const [steps] = useState(buildSteps);
  const [i, setI] = useState(0);
  const [hole, setHole] = useState<Rect | null>(null);
  const [extras, setExtras] = useState<Rect[]>([]);
  const [bubble, setBubble] = useState<{ top: number; left: number } | null>(null);
  const step = steps[i];

  const markDone = useCallback(() => {
    void fetch("/api/walkthrough/done", { method: "POST" }).catch(() => { /* */ });
  }, []);

  const finish = useCallback(() => {
    markDone();
    setMode("power");
    onClose();
  }, [markDone, onClose]);

  // Reset index when reopening
  useEffect(() => {
    if (open) setI(0);
  }, [open]);

  // Esc exits
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        finish();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, finish]);

  // Enter step actions
  useEffect(() => {
    if (!open || !step) return;
    let cancelled = false;
    (async () => {
      if (step.requireMode === "zen" && ctx.uiMode !== "zen") setMode("zen");
      if (step.requireMode === "power" && ctx.uiMode !== "power") setMode("power");
      await step.enter?.(ctx);
      if (cancelled) return;
      // remeasure a few times as layout settles
      for (const delay of [0, 80, 200, 400]) {
        await sleep(delay);
        if (cancelled) return;
        const h = measure(step.target);
        setHole(h);
        setExtras(
          (step.targets ?? [])
            .map((s) => measure(s))
            .filter((x): x is Rect => x !== null),
        );
      }
    })();
    return () => {
      cancelled = true;
      void step.leave?.(ctx);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, i, step?.id]);

  // Keep hole updated on resize
  useLayoutEffect(() => {
    if (!open || !step) return;
    const tick = () => {
      setHole(measure(step.target));
      setExtras(
        (step.targets ?? [])
          .map((s) => measure(s))
          .filter((x): x is Rect => x !== null),
      );
    };
    window.addEventListener("resize", tick);
    return () => window.removeEventListener("resize", tick);
  }, [open, step]);

  // Position bubble near hole (or center)
  useLayoutEffect(() => {
    if (!open) return;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const bw = 340;
    const bh = 180;
    if (!hole) {
      setBubble({ top: Math.max(24, (vh - bh) / 2), left: Math.max(16, (vw - bw) / 2) });
      return;
    }
    let top = hole.top + hole.height + 12;
    let left = hole.left;
    if (top + bh > vh - 16) top = Math.max(16, hole.top - bh - 12);
    if (left + bw > vw - 16) left = Math.max(16, vw - bw - 16);
    if (left < 16) left = 16;
    setBubble({ top, left });
  }, [open, hole, i]);

  if (!open || !step) return null;

  const isLast = i >= steps.length - 1;
  const next = () => {
    // step.leave runs via the effect cleanup when `i` changes
    if (isLast) {
      finish();
      return;
    }
    setI((n) => n + 1);
  };

  const vw = typeof window !== "undefined" ? window.innerWidth : 0;
  const vh = typeof window !== "undefined" ? window.innerHeight : 0;

  return (
    <div className="sy-walk" role="dialog" aria-modal="true" aria-labelledby="sy-walk-title">
      <svg className="sy-walk-mask" width={vw} height={vh} viewBox={`0 0 ${vw} ${vh}`}>
        <defs>
          <mask id="sy-walk-cut">
            <rect x="0" y="0" width={vw} height={vh} fill="white" />
            {hole && (
              <rect
                x={hole.left}
                y={hole.top}
                width={hole.width}
                height={hole.height}
                rx="6"
                fill="black"
              />
            )}
            {extras.map((r, idx) => (
              <rect
                key={idx}
                x={r.left}
                y={r.top}
                width={r.width}
                height={r.height}
                rx="4"
                fill="black"
              />
            ))}
          </mask>
        </defs>
        <rect
          x="0" y="0" width={vw} height={vh}
          fill="rgba(8, 6, 10, 0.62)"
          mask="url(#sy-walk-cut)"
        />
      </svg>
      {hole && (
        <div
          className="sy-walk-ring"
          style={{
            top: hole.top,
            left: hole.left,
            width: hole.width,
            height: hole.height,
          }}
        />
      )}
      {bubble && (
        <div
          className="sy-walk-bubble"
          style={{ top: bubble.top, left: bubble.left }}
        >
          <div className="sy-walk-bubble-head">
            <span id="sy-walk-title" className="sy-walk-title">{step.title}</span>
            <span className="sy-walk-progress">{i + 1}/{steps.length}</span>
            <button
              type="button"
              className="sy-walk-x"
              onClick={finish}
              title="Exit tour"
              aria-label="Exit tour"
            >
              ✕
            </button>
          </div>
          <p className="sy-walk-body">{step.body}</p>
          <div className="sy-walk-actions">
            <button type="button" className="sy-walk-btn" onClick={finish}>
              Skip tour
            </button>
            <button
              type="button"
              className="sy-walk-btn sy-walk-btn--primary"
              onClick={next}
            >
              {isLast ? "Done" : "Next"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Call once after the shell is ready — starts the tour if never done. */
export async function maybeAutoStartWalkthrough(
  start: () => void,
): Promise<void> {
  try {
    const r = await fetch("/api/walkthrough/status");
    if (!r.ok) return;
    const body = (await r.json()) as { done?: boolean };
    if (body.done) return;
    // Let FirstRunWizard / layout settle.
    window.setTimeout(start, 1400);
  } catch {
    /* older daemon */
  }
}
