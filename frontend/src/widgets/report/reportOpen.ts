/** Pending open for the ephemeral Report tab (proposal preview / create_report).

The tab is lazy-mounted. `open_report` used to fire `sy:open-report`
before the listener existed, so View opened an empty Reports tab.
*/
export type ReportShow = { id: string; title: string };

let last: ReportShow | null = null;

export function notifyReportOpen(id: string, title?: string): void {
  const rid = (id || "").trim();
  if (!rid) return;
  last = { id: rid, title: (title || "Report").trim() || "Report" };
  window.dispatchEvent(
    new CustomEvent("sy:open-report", {
      detail: { report_id: last.id, title: last.title },
    }),
  );
}

export function getLastReportOpen(): ReportShow | null {
  return last;
}

export function clearReportOpen(): void {
  last = null;
}
