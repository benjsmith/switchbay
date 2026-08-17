import { useEffect, useRef, useState } from "react";
import { getDB, registerWorkspaceFile } from "../duckdb/duckdb-init";
import { useSelection } from "../../selection/SelectionContext";
import { useTabs } from "../../center/TabsContext";
import {
  cellToA1,
  parseA1Cell,
  parseA1Range,
  rangeToA1,
} from "./a1";
import {
  ackUiCommand,
  takeFormula,
  takeSheetSelect,
  takeSheetValues,
  type PendingFormula,
  type PendingSheetValues,
} from "../../lib/pendingUiCommands";

/**
 * Univer-backed spreadsheet tab. Today:
 *   - Lazy-loads Univer on first activation.
 *   - Restores the saved workbook from /api/sheet on mount; saves
 *     periodically while edits are in flight.
 *   - When a CSV selection arrives (Table tab → Data card → ↗ Sheet),
 *     queries DuckDB-WASM for the rows and writes them into the
 *     active sheet via Facade API.
 *   - Tab-swap button "↗ Table" routes the current CSV selection back
 *     to the DuckDB tab.
 *   - Publishes live cell focus + value preview for the rail agent
 *     (`sheet_context` / `sheet_set_formula`); accepts `!fn` and
 *     agent formula/select events.
 *
 * Univer is large; the lazy import keeps it out of the main chunk
 * for users who never open the tab.
 */

const HOST_ID = "sy-sheet-host";
const AUTOSAVE_MS = 1500;
const FOCUS_POLL_MS = 400;
/** Univer's default workbook is 1000×20; writes past that throw
 *  "Range is out of bounds". CSV / query dumps are clipped to this. */
const SHEET_ROW_CAP = 1000;
const SHEET_COL_CAP = 20;
const PREVIEW_ROWS = 30;
const PREVIEW_COLS = 12;
const CELL_CHARS = 80;

// Minimal type for the bits of the Univer Facade we touch. Kept local
// (rather than importing Univer's types) to keep build coupling loose.
type UniverRange = {
  setValues: (vals: unknown[][]) => unknown;
  getValues: () => unknown[][];
  setFormula?: (formula: string) => unknown;
  getRow?: () => number;
  getColumn?: () => number;
  getRowCount?: () => number;
  getColumnCount?: () => number;
  activate?: () => unknown;
};

type UniverSheet = {
  getRange: (
    row: number,
    col: number,
    rowCount: number,
    colCount: number,
  ) => UniverRange;
  getDataRange: () => { getValues: () => unknown[][] };
  getLastRow: () => number;
  getLastColumn: () => number;
  getActiveRange?: () => UniverRange | null;
  getSheetName?: () => string;
};

type UniverWorkbook = {
  save: () => unknown;
  getActiveSheet: () => UniverSheet;
  create: (
    name: string, rows: number, cols: number,
  ) => UniverSheet;
  setActiveSheet: (sheet: UniverSheet | string) => UniverSheet;
  getSheetByName?: (name: string) => UniverSheet | null;
  getSheets?: () => UniverSheet[];
};

type UniverHandle = {
  univer: { dispose: () => void };
  univerAPI: {
    createWorkbook: (snap: unknown) => unknown;
    getActiveWorkbook: () => UniverWorkbook | null;
  };
};

type FormulaRunDetail = PendingFormula;

function normaliseFormula(raw: string): string {
  const s = raw.trim();
  if (!s) return s;
  return s.startsWith("=") ? s : `=${s}`;
}

function truncCell(v: unknown): unknown {
  if (v == null || typeof v === "number" || typeof v === "boolean") return v;
  const s = String(v);
  return s.length > CELL_CHARS ? s.slice(0, CELL_CHARS - 1) + "…" : s;
}

function applyFormulaToRange(range: UniverRange, formula: string): void {
  if (typeof range.setFormula === "function") {
    range.setFormula(formula);
  } else {
    range.setValues([[formula]]);
  }
}

function applyFormulaWrites(ws: UniverSheet, detail: FormulaRunDetail): string {
  if (detail.writes && detail.writes.length > 0) {
    const labels: string[] = [];
    for (const w of detail.writes) {
      const formula = normaliseFormula(w.formula);
      if (!formula) continue;
      const { row, col } = parseA1Cell(w.cell);
      const range = ws.getRange(row, col, 1, 1);
      try { range.activate?.(); } catch { /* optional */ }
      applyFormulaToRange(range, formula);
      labels.push(`${w.cell.toUpperCase()}: ${formula}`);
    }
    return labels.join("; ") || "no writes";
  }
  const raw = (detail.formula ?? "").trim();
  if (!raw) return "empty formula";
  const formula = normaliseFormula(raw);
  let range: UniverRange;
  if (detail.cell) {
    const { row, col } = parseA1Cell(detail.cell);
    range = ws.getRange(row, col, 1, 1);
    try { range.activate?.(); } catch { /* optional */ }
  } else {
    range =
      (ws.getActiveRange && ws.getActiveRange()) || ws.getRange(0, 0, 1, 1);
  }
  applyFormulaToRange(range, formula);
  const a1 = detail.cell
    ? detail.cell.toUpperCase()
    : (typeof range.getRow === "function" && typeof range.getColumn === "function"
      ? cellToA1(range.getRow()!, range.getColumn()!)
      : "?");
  return `${a1}: ${formula}`;
}

/** Persist workbook then report apply result for agent wait_ack path. */
async function ackFormulaCommand(
  handle: UniverHandle | null,
  detail: FormulaRunDetail,
  result: { ok: boolean; label?: string; error?: string },
): Promise<void> {
  const commandId = detail.command_id;
  if (!commandId) return;
  let durable = false;
  if (result.ok && handle) {
    try {
      const wb = handle.univerAPI.getActiveWorkbook();
      if (wb) {
        const snapshot = wb.save();
        const r = await fetch("/api/sheet", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ snapshot }),
        });
        durable = r.ok;
      }
    } catch {
      durable = false;
    }
  }
  await ackUiCommand({
    command_id: commandId,
    ok: result.ok,
    error: result.error,
    label: result.label,
    durable,
    applied: result.ok,
    surface: "sheet",
  });
}

function applySheetSelect(ws: UniverSheet, rangeSpec: string): string {
  const { row, col, rowCount, colCount } = parseA1Range(rangeSpec);
  const range = ws.getRange(row, col, rowCount, colCount);
  try { range.activate?.(); } catch { /* optional */ }
  return rangeToA1(row, col, rowCount, colCount);
}

function collectFocusPayload(ws: UniverSheet): Record<string, unknown> | null {
  try {
    const active =
      (ws.getActiveRange && ws.getActiveRange()) || null;
    let row = 0;
    let col = 0;
    let rowCount = 1;
    let colCount = 1;
    let value: unknown = "";
    if (active && typeof active.getRow === "function"
        && typeof active.getColumn === "function") {
      row = active.getRow() ?? 0;
      col = active.getColumn() ?? 0;
      rowCount = active.getRowCount?.() ?? 1;
      colCount = active.getColumnCount?.() ?? 1;
      try {
        const vals = active.getValues();
        value = vals?.[0]?.[0] ?? "";
      } catch { /* ignore */ }
    }
    const a1 = cellToA1(row, col);
    const range = rangeToA1(row, col, rowCount, colCount);

    let data: unknown[][] = [];
    try {
      data = ws.getDataRange().getValues() || [];
    } catch {
      data = [];
    }
    const nRows = Math.min(data.length, PREVIEW_ROWS);
    const nCols = Math.min(
      data.reduce((m, r) => Math.max(m, Array.isArray(r) ? r.length : 0), 0),
      PREVIEW_COLS,
    );
    const headers = (data[0] || []).slice(0, nCols).map((c) => String(truncCell(c) ?? ""));
    const preview = data.slice(0, nRows).map((r) =>
      (Array.isArray(r) ? r : []).slice(0, nCols).map(truncCell),
    );
    const lastR = Math.max(0, data.length - 1);
    const lastC = Math.max(0, nCols - 1);
    const used_range = data.length
      ? rangeToA1(0, 0, lastR + 1, lastC + 1)
      : a1;

    return {
      a1,
      range,
      sheet_name: ws.getSheetName?.() || undefined,
      value: truncCell(value),
      used_range,
      headers,
      preview,
    };
  } catch {
    return null;
  }
}

export default function SheetTab() {
  const { selection } = useSelection();
  const { switchToKind, tabs } = useTabs();
  const hostRef = useRef<HTMLDivElement>(null);
  const handleRef = useRef<UniverHandle | null>(null);
  const lastSnapshotRef = useRef<string>("");
  const lastFocusSerialRef = useRef<string>("");
  const pendingFormulaRef = useRef<FormulaRunDetail | null>(null);
  const pendingSelectRef = useRef<string | null>(null);
  const pendingValuesRef = useRef<PendingSheetValues | null>(null);
  const csvSelectionRef = useRef<string | null>(null);
  const [boot, setBoot] = useState<"loading" | "ready" | string>("loading");
  const [csvStatus, setCsvStatus] = useState<string | null>(null);

  const hasTableTab = tabs.some((t) => t.kind === "duckdb");
  const hasPlotTab = tabs.some((t) => t.kind === "vega");

  // Boot Univer once.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Boot Univer on the GRANULAR, Apache-2.0 packages only. We
        // deliberately do NOT import `@univerjs/presets` — that
        // metapackage lists every preset (incl. the *advanced* /
        // *collaboration* ones) as dependencies, which drag in the
        // proprietary `@univerjs-pro/*` tree. `createUniver` itself only
        // needs `@univerjs/core`, so it's inlined below (its ~15-line
        // Apache-2.0 body, see docs/THIRD-PARTY-NOTICES.md). We use only
        // `@univerjs/preset-sheets-core` (Apache-2.0, no Pro deps).
        const core = await import("@univerjs/core");
        const { FUniver } = await import("@univerjs/core/lib/facade");
        const sheetsCore = await import("@univerjs/preset-sheets-core");
        const locale = await import("@univerjs/preset-sheets-core/locales/en-US");
        await import("@univerjs/preset-sheets-core/lib/index.css");

        if (cancelled || !hostRef.current) return;
        hostRef.current.id = HOST_ID;

        // Inlined from @univerjs/presets `createUniver` (Apache-2.0):
        // instantiate Univer from core, register each preset's plugins,
        // wrap in the Facade API. Collaboration override handling is
        // dropped (we never enable it).
        const createUniver = (opts: {
          locale?: unknown;
          locales?: unknown;
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          presets?: any[];
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          plugins?: any[];
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          override?: any[];
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          [k: string]: any;
        }): UniverHandle => {
          const { presets = [], plugins = [], override = [], ...rest } = opts;
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const univer = new (core as any).Univer({
            logLevel: (core as { LogLevel: { WARN: number } }).LogLevel.WARN,
            ...rest,
            override,
          });
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const registry = new Map<string, { plugin: any; options: unknown }>();
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const add = (entry: any) => {
            const [ctor, plopts] = Array.isArray(entry) ? [entry[0], entry[1]] : [entry, undefined];
            registry.set(ctor.pluginName, { plugin: ctor, options: plopts });
          };
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          for (const preset of presets) (Array.isArray(preset) ? preset[0] : preset).plugins.forEach(add);
          for (const plug of plugins) add(plug);
          registry.forEach(({ plugin, options }) => univer.registerPlugin(plugin, options));
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const univerAPI = (FUniver as any).newAPI(univer);
          return { univer, univerAPI } as UniverHandle;
        };

        const localeData = (locale.default ?? locale) as object;
        const handle = createUniver({
          locale: core.LocaleType.EN_US,
          locales: {
            [core.LocaleType.EN_US]: core.merge({}, localeData),
          },
          presets: [
            sheetsCore.UniverSheetsCorePreset({ container: HOST_ID }),
          ],
        });
        handleRef.current = handle;

        // Try to restore a saved workbook; fall back to a blank one.
        let snap: unknown = null;
        try {
          const r = await fetch("/api/sheet");
          if (r.ok) {
            const body = (await r.json()) as { snapshot: unknown };
            snap = body.snapshot;
          }
        } catch { /* offline; use blank */ }

        if (snap && typeof snap === "object") {
          handle.univerAPI.createWorkbook(snap);
        } else {
          handle.univerAPI.createWorkbook({ name: "Switch Bay sheet" });
        }
        if (!cancelled) setBoot("ready");
      } catch (e) {
        if (!cancelled) setBoot((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
      if (handleRef.current) {
        try { handleRef.current.univer.dispose(); } catch { /* swallow */ }
        handleRef.current = null;
      }
    };
  }, []);

  // Autosave loop: poll the workbook snapshot, POST when it changes.
  // We don't have an "is dirty" hook from Univer's Facade so we
  // serialise + compare strings. Cheap for typical sheets.
  useEffect(() => {
    if (boot !== "ready") return;
    let cancelled = false;
    let saveInFlight: Promise<void> | null = null;

    const tick = async () => {
      const handle = handleRef.current;
      if (!handle) return;
      const wb = handle.univerAPI.getActiveWorkbook();
      if (!wb) return;
      const snapshot = wb.save();
      const serialised = JSON.stringify(snapshot);
      if (serialised === lastSnapshotRef.current) return;
      lastSnapshotRef.current = serialised;
      if (saveInFlight) return;
      saveInFlight = (async () => {
        try {
          await fetch("/api/sheet", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ snapshot }),
          });
        } catch { /* retry next tick */ }
        saveInFlight = null;
      })();
    };

    const id = window.setInterval(() => {
      if (!cancelled) void tick();
    }, AUTOSAVE_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
      // Final flush on unmount so an interim edit survives the close.
      void tick();
    };
  }, [boot]);

  // CSV selection → load into the active sheet via DuckDB-WASM. Only
  // imports each path once per selection event so flipping back and
  // forth doesn't repeatedly clobber edits.
  useEffect(() => {
    if (boot !== "ready") return;
    if (selection?.kind !== "csv") return;
    if (csvSelectionRef.current === selection.path) return;
    csvSelectionRef.current = selection.path;
    void loadCsvIntoActiveSheet(handleRef.current, selection.path, setCsvStatus);
  }, [selection, boot]);

  // Named worksheet open (Library / sealed package / slash).
  useEffect(() => {
    const onOpen = (ev: Event) => {
      const d = (ev as CustomEvent).detail as {
        slug?: string; title?: string; snapshot?: unknown;
      };
      if (!d?.snapshot || typeof d.snapshot !== "object") return;
      const handle = handleRef.current;
      if (!handle) return;
      try {
        // Dispose previous workbook by creating a new one from snapshot.
        handle.univerAPI.createWorkbook(d.snapshot);
        lastSnapshotRef.current = JSON.stringify(d.snapshot);
        setActiveWsSlug(d.slug || null);
        setCsvStatus(d.title ? `opened worksheet: ${d.title}` : "opened worksheet");
        window.setTimeout(() => setCsvStatus(null), 3000);
      } catch (e) {
        setCsvStatus(`open worksheet failed: ${(e as Error).message}`);
      }
    };
    window.addEventListener("sy:open-worksheet", onOpen);
    return () => window.removeEventListener("sy:open-worksheet", onOpen);
  }, []);

  // Inline table-data selection (e.g. ↗ Sheet button on a markdown
  // table inside the Editor). Same setValues path as CSV loading but
  // skips DuckDB — values are already a 2D array. The dedupe key is
  // origin+row-count since values arrays can be huge.
  const lastTableKeyRef = useRef<string | null>(null);
  useEffect(() => {
    if (boot !== "ready") return;
    if (selection?.kind !== "table-data") return;
    const key = `${selection.origin}|${selection.values.length}`;
    if (lastTableKeyRef.current === key) return;
    lastTableKeyRef.current = key;
    void loadValuesIntoActiveSheet(
      handleRef.current, selection.values, selection.origin, setCsvStatus,
    );
  }, [selection, boot]);

  // `!fn <formula>` / agent sheet_set_formula — App.tsx bridges WS
  // into this custom event. Supports active-cell writes, explicit
  // cell=, and batch writes[]. Queue if Univer isn't ready yet.
  // When command_id is set, ACK apply + durable save so the agent
  // never gets a silent false-success.
  useEffect(() => {
    const runFormula = (detail: FormulaRunDetail) => {
      const handle = handleRef.current;
      if (!handle || boot !== "ready") {
        pendingFormulaRef.current = detail;
        return;
      }
      const wb = handle.univerAPI.getActiveWorkbook();
      if (!wb) {
        pendingFormulaRef.current = detail;
        return;
      }
      try {
        const label = applyFormulaWrites(wb.getActiveSheet(), detail);
        setCsvStatus(`formula → ${label}`);
        window.setTimeout(() => setCsvStatus(null), 4000);
        void ackFormulaCommand(handle, detail, { ok: true, label });
      } catch (e) {
        const err = (e as Error).message;
        setCsvStatus(`formula failed: ${err}`);
        void ackFormulaCommand(handle, detail, { ok: false, error: err });
      }
    };
    const onFormula = (ev: Event) => {
      const detail = (ev as CustomEvent<FormulaRunDetail>).detail || {};
      runFormula(detail);
    };
    const onSelect = (ev: Event) => {
      const range = String(
        (ev as CustomEvent<{ range?: string }>).detail?.range ?? "",
      ).trim();
      if (!range) return;
      const handle = handleRef.current;
      if (!handle || boot !== "ready") {
        pendingSelectRef.current = range;
        return;
      }
      const wb = handle.univerAPI.getActiveWorkbook();
      if (!wb) {
        pendingSelectRef.current = range;
        return;
      }
      try {
        const label = applySheetSelect(wb.getActiveSheet(), range);
        setCsvStatus(`select → ${label}`);
        window.setTimeout(() => setCsvStatus(null), 2500);
      } catch (e) {
        setCsvStatus(`select failed: ${(e as Error).message}`);
      }
    };
    const onValues = (ev: Event) => {
      const detail = (ev as CustomEvent<PendingSheetValues>).detail;
      if (!detail?.values?.length) return;
      const handle = handleRef.current;
      if (!handle || boot !== "ready") {
        pendingValuesRef.current = detail;
        return;
      }
      void applySheetValues(handle, detail, setCsvStatus);
    };
    window.addEventListener("sy:formula-run", onFormula);
    window.addEventListener("sy:sheet-select", onSelect);
    window.addEventListener("sy:sheet-values", onValues);
    return () => {
      window.removeEventListener("sy:formula-run", onFormula);
      window.removeEventListener("sy:sheet-select", onSelect);
      window.removeEventListener("sy:sheet-values", onValues);
    };
  }, [boot]);

  // Drain in-tab queues + module-level stashes once Univer is ready
  // (covers cold mount after App switched to Sheet for !fn / agent).
  useEffect(() => {
    if (boot !== "ready") return;
    const handle = handleRef.current;
    if (!handle) return;
    const wb = handle.univerAPI.getActiveWorkbook();
    if (!wb) return;
    const sel = pendingSelectRef.current || takeSheetSelect();
    pendingSelectRef.current = null;
    if (sel) {
      try {
        applySheetSelect(wb.getActiveSheet(), sel);
      } catch { /* status already shown on next user action */ }
    }
    const values = pendingValuesRef.current || takeSheetValues();
    pendingValuesRef.current = null;
    if (values?.values?.length) {
      void applySheetValues(handle, values, setCsvStatus);
    }
    const formula = pendingFormulaRef.current || takeFormula();
    pendingFormulaRef.current = null;
    if (formula) {
      try {
        const label = applyFormulaWrites(wb.getActiveSheet(), formula);
        setCsvStatus(`formula → ${label}`);
        window.setTimeout(() => setCsvStatus(null), 4000);
        void ackFormulaCommand(handle, formula, { ok: true, label });
      } catch (e) {
        const err = (e as Error).message;
        setCsvStatus(`formula failed: ${err}`);
        void ackFormulaCommand(handle, formula, { ok: false, error: err });
      }
    }
  }, [boot]);

  // Publish active cell + compact value preview so the rail agent
  // can call sheet_context without parsing opaque workbook JSON.
  useEffect(() => {
    if (boot !== "ready") return;
    let cancelled = false;
    const tick = async () => {
      const handle = handleRef.current;
      if (!handle || cancelled) return;
      const wb = handle.univerAPI.getActiveWorkbook();
      if (!wb) return;
      const payload = collectFocusPayload(wb.getActiveSheet());
      if (!payload) return;
      const serialised = JSON.stringify(payload);
      if (serialised === lastFocusSerialRef.current) return;
      lastFocusSerialRef.current = serialised;
      try {
        await fetch("/api/sheet/focus", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: serialised,
        });
      } catch { /* retry next tick */ }
    };
    const id = window.setInterval(() => {
      if (!cancelled) void tick();
    }, FOCUS_POLL_MS);
    void tick();
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [boot]);

  const csvPath = selection?.kind === "csv" ? selection.path : null;
  const [saveCsvDraft, setSaveCsvDraft] = useState<string | null>(null);
  const [saveCsvDir, setSaveCsvDir] = useState<string>("vault/tables");
  const [saveCsvStatus, setSaveCsvStatus] = useState<string | null>(null);
  const [saveWsDraft, setSaveWsDraft] = useState<string | null>(null);
  const [saveWsStatus, setSaveWsStatus] = useState<string | null>(null);
  const [activeWsSlug, setActiveWsSlug] = useState<string | null>(null);
  // Cached active-workspace path so the file-browser-picked
  // absolute path can be turned into a workspace-relative one for
  // the save endpoint (which only accepts in-workspace dirs).
  const [workspaceRoot, setWorkspaceRoot] = useState<string | null>(null);
  useEffect(() => {
    fetch("/api/workspaces").then(async (r) => {
      if (!r.ok) return;
      const body = (await r.json()) as { active?: string | null };
      if (body.active) setWorkspaceRoot(body.active);
    }).catch(() => { /* offline; defaults are fine */ });
  }, []);

  const onPickFolder = async () => {
    try {
      const r = await fetch("/api/workspaces/pick", { method: "POST" });
      if (!r.ok) return;
      const body = (await r.json()) as { path?: string | null };
      if (!body.path || !workspaceRoot) return;
      // Constrain to inside the workspace; show an error toast if
      // the user picks somewhere else.
      if (!body.path.startsWith(workspaceRoot + "/") && body.path !== workspaceRoot) {
        setSaveCsvStatus("destination must be inside the workspace");
        return;
      }
      const rel = body.path === workspaceRoot ? "." : body.path.slice(workspaceRoot.length + 1);
      setSaveCsvDir(rel);
      setSaveCsvStatus(null);
    } catch (e) {
      setSaveCsvStatus(`pick failed: ${(e as Error).message}`);
    }
  };

  const [plotStatus, setPlotStatus] = useState<string | null>(null);
  const onToPlot = async () => {
    const handle = handleRef.current;
    if (!handle) return;
    const wb = handle.univerAPI.getActiveWorkbook();
    if (!wb) { setPlotStatus("no workbook"); return; }
    const ws = wb.getActiveSheet();
    let values: unknown[][];
    try {
      values = ws.getDataRange().getValues();
    } catch (e) {
      setPlotStatus(`could not read sheet: ${(e as Error).message}`);
      return;
    }
    if (!values || values.length < 2) {
      setPlotStatus("sheet needs at least 2 rows (header + 1 data)");
      window.setTimeout(() => setPlotStatus(null), 3000);
      return;
    }
    const origin = csvPath ? csvPath : "current sheet";
    // Existence check — skip the agent run if this table has
    // already been plotted. The Plot tab's right-click menu has a
    // "Regenerate with edits…" item the user can reach if they
    // want different plots.
    try {
      const list = await fetch("/api/plots").then((r) => r.ok ? r.json() : null);
      const matches = (list?.plots ?? []).filter(
        (p: { origin?: string }) => p.origin === origin,
      );
      if (matches.length > 0) {
        setPlotStatus(`${matches.length} plot${matches.length === 1 ? "" : "s"} already exist for this table`);
        switchToKind("vega");
        window.setTimeout(() => setPlotStatus(null), 4000);
        return;
      }
    } catch {
      // Network failed — fall through and try to generate anyway.
    }
    setPlotStatus("generating plots…");
    try {
      const r = await fetch("/api/plots/from-table", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values, origin }),
      });
      const body = await r.json();
      if (!r.ok) {
        setPlotStatus(body.error ?? `HTTP ${r.status}`);
        return;
      }
      window.dispatchEvent(new CustomEvent("sy:rail-system-tip", {
        detail: {
          text:
            `Plotting from \`${origin}\` — the agent is authoring 2-4 `
            + `Vega-Lite plots from the table data. Watch them land in `
            + `the Plot tab as save_plot fires, or open the Agents tab `
            + `to follow the live transcript (run \`${body.run_id}\`).`,
          focus: false,
        },
      }));
      setPlotStatus(`agent run ${body.run_id} — switching to Plot tab`);
      switchToKind("vega");
      window.setTimeout(() => setPlotStatus(null), 4000);
    } catch (e) {
      setPlotStatus(`plot failed: ${(e as Error).message}`);
    }
  };

  const onSaveWorksheet = async () => {
    const name = (saveWsDraft || "").trim();
    if (!name) {
      setSaveWsStatus("name required");
      return;
    }
    const handle = handleRef.current;
    const wb = handle?.univerAPI.getActiveWorkbook();
    if (!wb) {
      setSaveWsStatus("no workbook");
      return;
    }
    const snapshot = wb.save() as Record<string, unknown>;
    setSaveWsStatus("saving…");
    try {
      const r = await fetch("/api/worksheets/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: name, snapshot }),
      });
      const body = (await r.json().catch(() => ({}))) as {
        error?: string; slug?: string; wikilink?: string;
      };
      if (!r.ok) {
        setSaveWsStatus(body.error ?? `HTTP ${r.status}`);
        return;
      }
      setActiveWsSlug(body.slug || null);
      setSaveWsStatus(`saved → worksheets/${body.slug}/`);
      setSaveWsDraft(null);
      window.setTimeout(() => setSaveWsStatus(null), 4000);
    } catch (e) {
      setSaveWsStatus(`save failed: ${(e as Error).message}`);
    }
  };

  const onSaveCsv = async () => {
    if (saveCsvDraft === null) return;
    const handle = handleRef.current;
    if (!handle) return;
    const wb = handle.univerAPI.getActiveWorkbook();
    if (!wb) { setSaveCsvStatus("no workbook"); return; }
    const ws = wb.getActiveSheet();
    let values: unknown[][];
    try {
      values = ws.getDataRange().getValues();
    } catch (e) {
      setSaveCsvStatus(`could not read sheet: ${(e as Error).message}`);
      return;
    }
    if (!values || values.length === 0) {
      setSaveCsvStatus("sheet is empty");
      return;
    }
    setSaveCsvStatus("saving…");
    try {
      const r = await fetch("/api/sheet/save-csv", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: saveCsvDraft,
          values,
          dir: saveCsvDir,
        }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        setSaveCsvStatus(body.error ?? `HTTP ${r.status}`);
        return;
      }
      setSaveCsvStatus(`saved → ${body.path}`);
      setSaveCsvDraft(null);
      window.setTimeout(() => setSaveCsvStatus(null), 4000);
    } catch (e) {
      setSaveCsvStatus(`save failed: ${(e as Error).message}`);
    }
  };

  return (
    <div className="sy-sheet">
      <div className="sy-sheet-toolbar">
        <span
          className="sy-tab-engine"
          title="Spreadsheet engine powering this tab"
        >
          Univer
        </span>
        {csvPath && (
          <>
            <span className="sy-sheet-toolbar-label">CSV:</span>
            <span className="sy-sheet-toolbar-path" title={csvPath}>{csvPath}</span>
          </>
        )}
        {csvStatus && (
          <span
            className={
              "sy-sheet-toolbar-status"
              + (csvStatus.startsWith("showing first") ? " sy-sheet-toolbar-status--warn" : "")
            }
            title={csvStatus}
          >
            {csvStatus}
          </span>
        )}
        {plotStatus && <span className="sy-sheet-toolbar-status">{plotStatus}</span>}
        <span className="sy-spacer" />
        {activeWsSlug && (
          <span className="sy-sheet-toolbar-status" title="Named library worksheet">
            worksheet:{activeWsSlug}
          </span>
        )}
        {saveWsStatus && <span className="sy-sheet-toolbar-status">{saveWsStatus}</span>}
        <button
          type="button"
          className="sy-sheet-toolbar-btn"
          onClick={() => {
            setSaveWsDraft(activeWsSlug || "");
            setSaveWsStatus(null);
          }}
          title="Save a durable named worksheet under worksheets/<slug>/"
          disabled={boot !== "ready"}
        >
          ↓ Save as worksheet
        </button>
        <button
          type="button"
          className="sy-sheet-toolbar-btn"
          onClick={() => { setSaveCsvDraft(""); setSaveCsvStatus(null); }}
          title="Save the active sheet as a CSV under vault/tables/"
          disabled={boot !== "ready"}
        >
          ↓ Save as CSV
        </button>
        {hasPlotTab && (
          <button
            type="button"
            className="sy-sheet-toolbar-btn"
            onClick={() => { void onToPlot(); }}
            disabled={boot !== "ready" || plotStatus === "generating plots…"}
            title="Ask the agent to author Vega-Lite plots from this table; lands in the Plot tab"
          >
            ↗ Plot
          </button>
        )}
        {csvPath && hasTableTab && (
          <button
            type="button"
            className="sy-sheet-toolbar-btn"
            onClick={() => switchToKind("duckdb")}
            title="Inspect this CSV in the Table tab"
          >
            ↗ Table
          </button>
        )}
      </div>
      {boot === "loading" && <div className="sy-sheet-banner">Loading Univer…</div>}
      {boot !== "loading" && boot !== "ready" && (
        <div className="sy-sheet-banner sy-sheet-banner--err">
          Univer failed to initialise: {boot}
        </div>
      )}
      <div ref={hostRef} className="sy-sheet-host" />
      {saveWsDraft !== null && (
        <div
          className="sy-confirm-backdrop"
          onClick={() => setSaveWsDraft(null)}
        >
          <div
            className="sy-confirm"
            role="dialog"
            aria-labelledby="sy-sheet-save-ws-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div id="sy-sheet-save-ws-title" className="sy-confirm-title">
              Save as worksheet
            </div>
            <div className="sy-confirm-body">
              <p>
                Stores a durable Univer snapshot under{" "}
                <code>worksheets/&lt;slug&gt;/</code> (Library · sealed package).
                Scratch autosave still writes to{" "}
                <code>.workbench/state/sheet.json</code>.
              </p>
              <label>
                Title
                <input
                  type="text"
                  value={saveWsDraft}
                  onChange={(e) => setSaveWsDraft(e.target.value)}
                  autoFocus
                  placeholder="Financial model"
                />
              </label>
              {saveWsStatus && <p>{saveWsStatus}</p>}
            </div>
            <div className="sy-confirm-actions">
              <button
                type="button"
                className="sy-confirm-btn"
                onClick={() => setSaveWsDraft(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="sy-confirm-btn"
                onClick={() => { void onSaveWorksheet(); }}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
      {saveCsvDraft !== null && (
        <div
          className="sy-confirm-backdrop"
          onClick={() => setSaveCsvDraft(null)}
        >
          <div
            className="sy-confirm"
            role="dialog"
            aria-labelledby="sy-sheet-save-csv-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div id="sy-sheet-save-csv-title" className="sy-confirm-title">
              Save sheet as CSV
            </div>
            <div className="sy-confirm-body">
              <p>
                The active sheet's data range is written to{" "}
                <code>{saveCsvDir}/&lt;name&gt;.csv</code> in this workspace.
              </p>
              <div className="sy-sheet-dest-chips">
                {["vault/tables", "vault/raw"].map((d) => (
                  <button
                    key={d}
                    type="button"
                    className={
                      "sy-sheet-dest-chip" +
                      (saveCsvDir === d ? " sy-sheet-dest-chip--active" : "")
                    }
                    onClick={() => setSaveCsvDir(d)}
                  >
                    {d}
                  </button>
                ))}
                <button
                  type="button"
                  className="sy-sheet-dest-chip sy-sheet-dest-chip--browse"
                  onClick={() => void onPickFolder()}
                  title="Pick another folder inside the workspace"
                >
                  Browse…
                </button>
              </div>
              <input
                type="text"
                className="sy-ws-input"
                autoFocus
                placeholder="filename (no extension)"
                value={saveCsvDraft}
                onChange={(e) => setSaveCsvDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") { e.preventDefault(); void onSaveCsv(); }
                  if (e.key === "Escape") { e.preventDefault(); setSaveCsvDraft(null); }
                }}
              />
              {saveCsvStatus && (
                <p className="sy-sheet-toolbar-status" style={{ marginTop: 8 }}>
                  {saveCsvStatus}
                </p>
              )}
            </div>
            <div className="sy-confirm-actions">
              <button
                type="button"
                className="sy-confirm-btn"
                onClick={() => setSaveCsvDraft(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="sy-confirm-btn sy-confirm-btn--primary"
                disabled={!saveCsvDraft.trim()}
                onClick={() => void onSaveCsv()}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

async function applySheetValues(
  handle: UniverHandle,
  detail: PendingSheetValues,
  setStatus: (s: string | null) => void,
): Promise<void> {
  const ok = await loadValuesIntoActiveSheet(
    handle, detail.values, detail.origin || "agent", setStatus,
  );
  if (detail.command_id) {
    await ackUiCommand({
      command_id: detail.command_id,
      ok,
      surface: "sheet",
      applied: ok,
      durable: ok,
      label: ok ? (detail.origin || "values") : undefined,
      error: ok ? undefined : "Sheet did not accept the grid",
    });
  }
}

async function loadValuesIntoActiveSheet(
  handle: UniverHandle | null,
  values: (string | number | boolean | null)[][],
  origin: string,
  setStatus: (s: string | null) => void,
) {
  if (!handle || values.length === 0) return false;
  setStatus("loading…");
  try {
    const wb = handle.univerAPI.getActiveWorkbook();
    if (!wb) { setStatus("no workbook"); return false; }
    const cols = Math.max(...values.map((r) => r.length));
    const padded = values.map((r) =>
      r.length === cols ? r : [...r, ...Array(cols - r.length).fill("")],
    );
    const { grid, status } = clipToSheet(padded, padded.length - 1, cols);
    const ws = openImportSheet(wb, origin, grid.length, grid[0]?.length ?? 1);
    const range = ws.getRange(0, 0, grid.length, grid[0]!.length);
    range.setValues(grid as unknown as unknown[][]);
    setStatus(`${status} · from ${origin}`);
    return true;
  } catch (e) {
    setStatus(`error: ${(e as Error).message.slice(0, 100)}`);
    return false;
  }
}


/** Clip a value grid to Univer's default workbook (1000×20) and
 *  describe what was dropped so the toolbar can warn. `totalRows` /
 *  `totalCols` are the full source size (may exceed `values`). */
function clipToSheet(
  values: unknown[][],
  totalRows: number,
  totalCols: number,
): { grid: unknown[][]; status: string } {
  const grid = values.slice(0, SHEET_ROW_CAP).map((r) => {
    const row = (Array.isArray(r) ? r : []).slice(0, SHEET_COL_CAP);
    while (row.length < Math.min(totalCols, SHEET_COL_CAP)) row.push("");
    return row;
  });
  const shownData = Math.max(0, grid.length - 1);
  const shownCols = grid[0]?.length ?? 0;
  const rowTrunc = totalRows > shownData;
  const colTrunc = totalCols > shownCols;
  const rowsBit = rowTrunc
    ? `first ${shownData.toLocaleString()} of ${totalRows.toLocaleString()} rows`
    : `${shownData.toLocaleString()} rows`;
  const colsBit = colTrunc
    ? `first ${shownCols} of ${totalCols} cols`
    : `${shownCols} cols`;
  const hint = (rowTrunc || colTrunc)
    ? " · ask the rail for a subset if you need a different slice"
    : "";
  const lead = (rowTrunc || colTrunc) ? "showing " : "loaded ";
  return { grid, status: `${lead}${rowsBit} · ${colsBit}${hint}` };
}

/** New sheet sized to the write, so a 1000×20 dump doesn't overflow
 *  the default workbook and doesn't clobber earlier edits. */
function openImportSheet(
  wb: UniverWorkbook,
  origin: string,
  rows: number,
  cols: number,
): UniverSheet {
  const h = Math.max(rows, 1);
  const w = Math.max(cols, 1);
  const sheetName = deriveSheetName(origin);
  const existing = wb.getSheetByName?.(sheetName)
    ?? wb.getSheets?.().find((s) => s.getSheetName?.() === sheetName)
    ?? null;
  if (existing) {
    wb.setActiveSheet(existing);
    return existing;
  }
  try {
    const fresh = wb.create(sheetName, h, w);
    wb.setActiveSheet(fresh);
    return fresh;
  } catch {
    try {
      const fresh = wb.create(
        `${sheetName} ${Math.floor(Math.random() * 9000 + 1000)}`,
        h, w,
      );
      wb.setActiveSheet(fresh);
      return fresh;
    } catch {
      return wb.getActiveSheet();
    }
  }
}

/** Derive a short, Univer-tab-friendly sheet name from an origin
 *  breadcrumb like `wiki/projects/foo.md#table-2` or
 *  `duckdb-query`. Univer caps sheet names around 31 chars (Excel
 *  convention) and rejects a small set of punctuation. */
function deriveSheetName(origin: string): string {
  let name = origin.replace(/[\\/:*?[\]]/g, " ").trim();
  if (name.length > 28) name = name.slice(0, 28).trim() + "…";
  return name || "Imported";
}


async function loadCsvIntoActiveSheet(
  handle: UniverHandle | null,
  path: string,
  setStatus: (s: string | null) => void,
) {
  if (!handle) return;
  setStatus("loading…");
  try {
    const { db, conn } = await getDB();
    const vfs = await registerWorkspaceFile(db, path);
    const escaped = vfs.replace(/'/g, "''");
    let totalRows = 0;
    try {
      const countRes = await conn.query(
        `SELECT COUNT(*)::BIGINT AS n FROM read_csv_auto('${escaped}')`,
      );
      const raw = (countRes.toArray()[0] as Record<string, unknown> | undefined)?.n;
      totalRows = typeof raw === "bigint" ? Number(raw) : Number(raw ?? 0);
    } catch { /* COUNT may fail on messy CSVs; fall through */ }
    const dataCap = SHEET_ROW_CAP - 1;
    const res = await conn.query(
      `SELECT * FROM read_csv_auto('${escaped}') LIMIT ${dataCap};`,
    );
    const cols = res.schema.fields.map((f) => f.name);
    const arrowRows = res.toArray();
    if (cols.length === 0) {
      setStatus("no columns");
      return;
    }
    const values: unknown[][] = [cols];
    for (const r of arrowRows) {
      const row: unknown[] = cols.map((c) => {
        const v = (r as Record<string, unknown>)[c];
        if (typeof v === "bigint") return Number(v);
        if (v && typeof v === "object" && "valueOf" in v) return (v as { valueOf: () => unknown }).valueOf();
        return v ?? "";
      });
      values.push(row);
    }
    const wb = handle.univerAPI.getActiveWorkbook();
    if (!wb) { setStatus("no workbook"); return; }
    const knownRows = Math.max(totalRows, arrowRows.length);
    const { grid, status } = clipToSheet(values, knownRows, cols.length);
    const ws = openImportSheet(wb, path, grid.length, grid[0]?.length ?? 1);
    const range = ws.getRange(0, 0, grid.length, grid[0]!.length);
    range.setValues(grid as unknown as unknown[][]);
    setStatus(status);
  } catch (e) {
    setStatus(`error: ${(e as Error).message.slice(0, 100)}`);
  }
}
