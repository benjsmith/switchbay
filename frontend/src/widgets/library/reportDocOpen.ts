/** Pending open for durable report packages (same race fix as slideshows). */

export type ReportDocShow = { slug: string; title: string };

let last: ReportDocShow | null = null;

export function notifyReportDocOpen(slug: string, title?: string): void {
  const s = (slug || "").trim();
  if (!s) return;
  last = { slug: s, title: (title || s).trim() || s };
  window.dispatchEvent(
    new CustomEvent("sy:open-report-doc", {
      detail: { slug: last.slug, title: last.title },
    }),
  );
}

export function getLastReportDocOpen(): ReportDocShow | null {
  return last;
}

export function clearReportDocOpen(): void {
  last = null;
}
