/**
 * Last-wins queues for agent/rail commands that target a center tab
 * which may not be mounted yet (only the active tab is rendered).
 *
 * App.tsx stashes on WS arrival + re-dispatches; each tab drains on
 * mount / boot-ready so cold Sheet/Table no longer drop !fn / !sql.
 *
 * When `command_id` is set, the target tab POSTs /api/ui/command-ack
 * (or /api/sheet/command-ack) after apply so the agent tool does not
 * silently false-succeed.
 */

export type PendingFormula = {
  formula?: string;
  cell?: string;
  writes?: { cell: string; formula: string }[];
  /** When set, Sheet tab POSTs command-ack after apply+save. */
  command_id?: string;
};

export type PendingSql = {
  query: string;
  command_id?: string;
};

export type PendingSheetValues = {
  values: (string | number | boolean | null)[][];
  origin?: string;
  command_id?: string;
};

export type PendingPlotShow = {
  id: string;
  name?: string;
  command_id?: string;
};

export type PendingSketchShow = {
  sketch_id?: string | null;
  slide_index?: number | null;
  name?: string | null;
  command_id?: string;
};

type Pending = {
  formula: PendingFormula | null;
  sheetSelect: string | null;
  sheetValues: PendingSheetValues | null;
  sql: PendingSql | null;
  sketchShow: PendingSketchShow | null;
  plotShow: PendingPlotShow | null;
};

const pending: Pending = {
  formula: null,
  sheetSelect: null,
  sheetValues: null,
  sql: null,
  sketchShow: null,
  plotShow: null,
};

export function stashFormula(detail: PendingFormula): void {
  pending.formula = detail;
}
export function takeFormula(): PendingFormula | null {
  const v = pending.formula;
  pending.formula = null;
  return v;
}

export function stashSheetSelect(range: string): void {
  pending.sheetSelect = range;
}
export function takeSheetSelect(): string | null {
  const v = pending.sheetSelect;
  pending.sheetSelect = null;
  return v;
}

export function stashSheetValues(detail: PendingSheetValues): void {
  pending.sheetValues = detail;
}
export function takeSheetValues(): PendingSheetValues | null {
  const v = pending.sheetValues;
  pending.sheetValues = null;
  return v;
}

export function stashSql(detail: string | PendingSql): void {
  if (typeof detail === "string") {
    pending.sql = { query: detail };
  } else {
    pending.sql = detail;
  }
}
export function takeSql(): PendingSql | null {
  const v = pending.sql;
  pending.sql = null;
  return v;
}

export function stashSketchShow(detail: PendingSketchShow): void {
  pending.sketchShow = detail;
}
export function takeSketchShow(): PendingSketchShow | null {
  const v = pending.sketchShow;
  pending.sketchShow = null;
  return v;
}

export function stashPlotShow(detail: PendingPlotShow): void {
  pending.plotShow = detail;
}
export function takePlotShow(): PendingPlotShow | null {
  const v = pending.plotShow;
  pending.plotShow = null;
  return v;
}

/** Report agent wait_ack result (all live-tab surfaces). */
export async function ackUiCommand(body: {
  command_id: string;
  ok: boolean;
  error?: string;
  label?: string;
  durable?: boolean;
  applied?: boolean;
  surface?: string;
  result?: unknown;
}): Promise<void> {
  if (!body.command_id) return;
  try {
    await fetch("/api/ui/command-ack", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    /* daemon times out the waiter */
  }
}
