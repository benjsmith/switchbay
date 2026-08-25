import { useCallback, useEffect, useMemo, useState, type MouseEvent } from "react";
import { marked } from "marked";
import { sanitizeHtml } from "../../lib/sanitizeHtml";
import { openWorkspaceFile } from "../../lib/localPath";
import { expandWikilinks, parseFrontmatter } from "../editor/mdview";
import { PropertyValue } from "../editor/SourceCite";
import { clearReportOpen, getLastReportOpen } from "./reportOpen";

type Review = {
  verdict?: string;
  confidence?: number;
  issues?: string[];
  one_line?: string;
};

type Proposal = {
  id: string;
  op: string;
  kind: string;
  title: string;
  path: string;
  body: string;
  comments?: string;
  review: Review | null;
  scaffold?: boolean;
};

/**
 * Reviews tab — proposed wiki pages + optional rich HTML reports.
 * Multi-page queue with accept / reject / comments so review is a
 * backlog, not a rail blocker.
 */
export default function ReportTab() {
  const [queue, setQueue] = useState<Proposal[]>([]);
  const [idx, setIdx] = useState(0);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [report, setReport] = useState<{ id: string; title: string } | null>(
    () => {
      const pending = getLastReportOpen();
      return pending ? { id: pending.id, title: pending.title } : null;
    },
  );
  const [html, setHtml] = useState<string | null>(null);

  const loadQueue = useCallback(async () => {
    try {
      const r = await fetch("/api/proposals/pending");
      if (!r.ok) return;
      const body = (await r.json()) as { proposals?: Proposal[] };
      const next = body.proposals ?? [];
      setQueue(next);
      setIdx((i) => Math.min(i, Math.max(0, next.length - 1)));
    } catch { /* best-effort */ }
  }, []);

  useEffect(() => {
    void loadQueue();
    const onOpen = (ev: Event) => {
      const d = (ev as CustomEvent).detail as { report_id?: string; title?: string };
      if (d?.report_id) setReport({ id: d.report_id, title: d.title || "Review" });
    };
    const onResolved = () => { void loadQueue(); };
    window.addEventListener("sy:open-report", onOpen);
    window.addEventListener("sy:proposal-resolved", onResolved);
    window.addEventListener("sy:proposal-queued", onResolved);
    const iv = window.setInterval(() => void loadQueue(), 8000);
    return () => {
      window.removeEventListener("sy:open-report", onOpen);
      window.removeEventListener("sy:proposal-resolved", onResolved);
      window.removeEventListener("sy:proposal-queued", onResolved);
      window.clearInterval(iv);
    };
  }, [loadQueue]);

  useEffect(() => {
    const pending = getLastReportOpen();
    if (pending) setReport({ id: pending.id, title: pending.title });
  }, []);

  useEffect(() => {
    if (!report) return;
    let live = true;
    setHtml(null);
    fetch(`/api/report/${encodeURIComponent(report.id)}`)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((t) => { if (live) setHtml(t); })
      .catch((e) => { if (live) setErr(String(e.message || e)); });
    return () => { live = false; };
  }, [report]);

  const current = queue[idx] ?? null;
  useEffect(() => {
    setComment(current?.comments || "");
  }, [current?.id]);

  const decide = async (decision: "accept" | "reject" | "comment") => {
    if (!current) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch("/api/proposals/decide", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: current.id, decision, comments: comment,
        }),
      });
      const b = await r.json().catch(() => ({} as { error?: string }));
      if (!r.ok) { setErr(b.error || `HTTP ${r.status}`); return; }
      window.dispatchEvent(new CustomEvent("sy:proposal-resolved"));
      await loadQueue();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const curate = async (stop: boolean) => {
    setBusy(true);
    try {
      const r = await fetch("/api/ce-action/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "curate",
          args: stop ? "stop" : "",
        }),
      });
      const b = await r.json().catch(() => ({} as { error?: string; cancelled?: number }));
      if (!r.ok) { setErr(b.error || `HTTP ${r.status}`); return; }
      if (stop) {
        window.dispatchEvent(new CustomEvent("sy:toast", {
          detail: { text: `Stopped ${b.cancelled ?? 0} curation run(s).` },
        }));
      } else {
        window.dispatchEvent(new CustomEvent("sy:toast", {
          detail: { text: "Curation running in the background." },
        }));
      }
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const closePreview = () => {
    setReport(null);
    setHtml(null);
    clearReportOpen();
  };

  const closeTab = async () => {
    closePreview();
    try {
      await fetch("/api/reviews/close", { method: "POST" });
    } catch { /* hello broadcast will drop the tab */ }
  };

  if (!current && !report) {
    return (
      <div className="sy-report-empty">
        <div className="sy-report-empty-inner">
          <div className="sy-report-glyph">↗</div>
          <p>
            Reviews land here — proposed wiki pages and rich reports.
            Kick off a background curate when you want the wiki to
            grow; this queue is a backlog, not a gate.
          </p>
          <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 12 }}>
            <button type="button" className="sy-confirm-btn sy-confirm-btn--primary" disabled={busy}
              onClick={() => void curate(false)}>
              Start curate
            </button>
            <button type="button" className="sy-confirm-btn" disabled={busy}
              onClick={() => void curate(true)}>
              Stop curate
            </button>
            <button type="button" className="sy-confirm-btn" onClick={() => void closeTab()}>
              ✕ close
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="sy-report-host">
      <div className="sy-report-bar">
        <span className="sy-report-title">
          {current
            ? `${current.title || current.path}`
            : (report?.title || "Review")}
        </span>
        {queue.length > 0 && (
          <span className="sy-report-count">
            {idx + 1} / {queue.length}
          </span>
        )}
        <div className="sy-report-bar-actions">
          {queue.length > 1 && (
            <>
              <button type="button" className="sy-report-pop" disabled={idx <= 0}
                onClick={() => setIdx((i) => Math.max(0, i - 1))}>
                ← prev
              </button>
              <button type="button" className="sy-report-pop" disabled={idx >= queue.length - 1}
                onClick={() => setIdx((i) => Math.min(queue.length - 1, i + 1))}>
                next →
              </button>
            </>
          )}
          <button type="button" className="sy-report-pop" disabled={busy}
            onClick={() => void curate(false)}>Start curate</button>
          <button type="button" className="sy-report-pop" disabled={busy}
            onClick={() => void curate(true)}>Stop</button>
          {report && current && (
            <button type="button" className="sy-report-pop" onClick={closePreview}
              title="Close this HTML preview">
              dismiss preview
            </button>
          )}
          <button type="button" className="sy-report-pop" onClick={() => void closeTab()}
            title="Close Reviews — remaining drafts stay on disk (accepted)">
            ✕ close
          </button>
        </div>
      </div>
      {err && <div className="sy-report-error">{err}</div>}
      {current && (
        <div className="sy-review-body">
          <div className="sy-review-meta">
            <code>{current.op} · {current.kind}{current.scaffold ? " · scaffold" : ""}</code>
            <span>{current.path}</span>
            {current.scaffold && (
              <p className="sy-review-oneline">
                Light outline from the local model — expand from sources
                before treating this as wiki canon.
              </p>
            )}
            {current.review?.one_line && (
              <p className="sy-review-oneline">{current.review.one_line}</p>
            )}
          </div>
          <ReviewPreview markdown={current.body} />
          <div className="sy-review-actions">
            <textarea
              className="sy-review-comment"
              placeholder="Comments keep the page and feed the next curation wave; reject still reverts"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              rows={3}
            />
            <div className="sy-review-btns">
              <button type="button" className="sy-confirm-btn" disabled={busy}
                onClick={() => void decide("comment")}>Comment & keep</button>
              <button type="button" className="sy-confirm-btn sy-confirm-btn--primary" disabled={busy}
                onClick={() => void decide("accept")}>Accept</button>
              <button type="button" className="sy-confirm-btn" disabled={busy}
                onClick={() => void decide("reject")}>Reject</button>
            </div>
          </div>
        </div>
      )}
      {!current && html !== null && (
        <iframe
          className="sy-report-frame"
          title={report?.title || "Review"}
          sandbox="allow-scripts"
          srcDoc={html}
        />
      )}
      {!current && html === null && report && !err && (
        <div className="sy-report-loading">Rendering…</div>
      )}
    </div>
  );
}

function ReviewPreview({ markdown }: { markdown: string }) {
  const { properties, body } = useMemo(() => parseFrontmatter(markdown), [markdown]);
  const previewHtml = useMemo(
    () => (body
      ? sanitizeHtml(marked.parse(expandWikilinks(body), { async: false }) as string)
      : ""),
    [body],
  );
  const propRows = Object.entries(properties);
  const title = typeof properties.title === "string" ? properties.title : "";

  const onPreviewClick = (ev: MouseEvent<HTMLDivElement>) => {
    const t = ev.target as HTMLElement;
    const cite = t.closest?.("a[data-reveal-path]") as HTMLElement | null;
    if (cite) {
      ev.preventDefault();
      ev.stopPropagation();
      void openWorkspaceFile(cite.getAttribute("data-reveal-path") || "");
      return;
    }
    const wiki = t.closest?.("a.wikilink") as HTMLAnchorElement | null;
    if (wiki) {
      ev.preventDefault();
      const href = wiki.getAttribute("href") || "";
      const m = href.match(/^#page=(.+)$/);
      const target = m ? decodeURIComponent(m[1]) : (wiki.textContent || "");
      if (target) {
        window.dispatchEvent(new CustomEvent("sy:open-wiki-page", { detail: { target } }));
      }
    }
  };

  return (
    <div className="sy-review-doc" onClick={onPreviewClick}>
      {title && <h1 className="sy-mdview-title">{title}</h1>}
      {propRows.length > 0 && (
        <section className="properties">
          <div className="properties-head">Properties</div>
          <table className="sy-mdview-properties">
            <tbody>
              {propRows.map(([k, v]) => (
                <tr key={k}>
                  <td className="prop-key">{k}</td>
                  <td className="prop-val"><PropertyValue name={k} value={v} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <article className="sy-mdview" dangerouslySetInnerHTML={{ __html: previewHtml }} />
    </div>
  );
}
