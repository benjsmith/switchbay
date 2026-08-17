import { useEffect, useState } from "react";
import { getLastReportOpen } from "./reportOpen";

/**
 * Report tab — renders a capable model's `create_report` HTML in a
 * SANDBOXED iframe (scripts allowed, but no `allow-same-origin`, so the
 * document can't touch the parent app; self-contained, no external
 * loads — same posture as Claude Artifacts). One reusable tab: it shows
 * whichever report the latest `open_report` pointed at, delivered here
 * via the `sy:open-report` window event.
 */
export default function ReportTab() {
  const [report, setReport] = useState<{ id: string; title: string } | null>(
    () => {
      const pending = getLastReportOpen();
      return pending ? { id: pending.id, title: pending.title } : null;
    },
  );
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const pending = getLastReportOpen();
    if (pending) setReport({ id: pending.id, title: pending.title });
    const onOpen = (ev: Event) => {
      const d = (ev as CustomEvent).detail as { report_id?: string; title?: string };
      if (d?.report_id) setReport({ id: d.report_id, title: d.title || "Report" });
    };
    window.addEventListener("sy:open-report", onOpen);
    return () => window.removeEventListener("sy:open-report", onOpen);
  }, []);

  useEffect(() => {
    if (!report) return;
    let live = true;
    setHtml(null);
    setError(null);
    fetch(`/api/report/${encodeURIComponent(report.id)}`)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((t) => { if (live) setHtml(t); })
      .catch((e) => { if (live) setError(String(e.message || e)); });
    return () => { live = false; };
  }, [report]);

  if (!report) {
    return (
      <div className="sy-report-empty">
        <div className="sy-report-empty-inner">
          <div className="sy-report-glyph">↗</div>
          <p>Rich answers land here. Ask for an analysis, comparison, or a
            structured breakdown and a capable model will build it as a
            document — the chat keeps just a one-line summary.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="sy-report-host">
      <div className="sy-report-bar">
        <span className="sy-report-title">{report.title}</span>
        <a
          className="sy-report-pop"
          href={`/api/report/${encodeURIComponent(report.id)}`}
          target="_blank"
          rel="noreferrer"
          title="Open in a new browser tab"
        >
          ⤢ open
        </a>
      </div>
      {error && <div className="sy-report-error">Couldn't load this report: {error}</div>}
      {html !== null && (
        <iframe
          className="sy-report-frame"
          title={report.title}
          sandbox="allow-scripts"
          srcDoc={html}
        />
      )}
      {html === null && !error && <div className="sy-report-loading">Rendering…</div>}
    </div>
  );
}
