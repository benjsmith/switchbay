import { useEffect, useState } from "react";
import {
  clearReportDocOpen,
  getLastReportDocOpen,
  type ReportDocShow,
} from "./reportDocOpen";

/**
 * Durable report package viewer (`reports/<slug>/`). Distinct from the
 * ephemeral agent Report tab (statedir create_report).
 */
export default function ReportDocTab() {
  const [show, setShow] = useState<ReportDocShow | null>(() => getLastReportDocOpen());
  const [closing, setClosing] = useState(false);

  useEffect(() => {
    const pending = getLastReportDocOpen();
    if (pending) setShow(pending);
    const onOpen = (ev: Event) => {
      const d = (ev as CustomEvent).detail as { slug?: string; title?: string };
      if (d?.slug) setShow({ slug: d.slug, title: d.title || d.slug });
    };
    window.addEventListener("sy:open-report-doc", onOpen);
    return () => window.removeEventListener("sy:open-report-doc", onOpen);
  }, []);

  const close = async () => {
    setClosing(true);
    try {
      clearReportDocOpen();
      await fetch("/api/report-packages/close", { method: "POST" }).catch(() => {});
      // Tab drop is optional; prefer graph nav if server supports close later
    } catch {
      setClosing(false);
    }
  };

  if (!show) {
    return (
      <div className="sy-report-host">
        <div className="sy-report-bar">
          <span className="sy-report-title">Report doc</span>
          <button
            className="sy-report-pop"
            type="button"
            style={{ marginLeft: 0, cursor: "pointer" }}
            onClick={close}
            disabled={closing}
          >
            ✕ close
          </button>
        </div>
        <div className="sy-report-empty">
          <div className="sy-report-empty-inner">
            <div className="sy-report-glyph">☰</div>
            <p>
              Durable <strong>reports</strong> live in{" "}
              <code>reports/&lt;slug&gt;/</code>. Open from the Library tab
              or a <code>[[report:slug|title]]</code> link. (Ephemeral agent
              answers still use the Report tab.)
            </p>
          </div>
        </div>
      </div>
    );
  }

  const src = `/api/report-packages/${encodeURIComponent(show.slug)}/`;

  return (
    <div className="sy-report-host">
      <div className="sy-report-bar">
        <span className="sy-report-title">{show.title}</span>
        <span className="sy-report-meta" style={{ opacity: 0.65, fontSize: 12 }}>
          reports/{show.slug}/
        </span>
        <a
          className="sy-report-pop"
          href={src}
          target="_blank"
          rel="noreferrer"
          title="Open fullscreen"
        >
          ⤢ fullscreen
        </a>
        <button
          className="sy-report-pop"
          type="button"
          style={{ marginLeft: 0, cursor: "pointer" }}
          onClick={close}
          disabled={closing}
        >
          ✕ close
        </button>
      </div>
      <iframe
        className="sy-report-frame"
        title={show.title}
        sandbox="allow-scripts"
        src={src}
      />
    </div>
  );
}
