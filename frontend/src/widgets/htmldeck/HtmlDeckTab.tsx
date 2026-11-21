import { useEffect, useState } from "react";
import {
  clearHtmlDeckOpen,
  getLastHtmlDeckOpen,
  type HtmlDeckShow,
} from "./htmlDeckOpen";

/**
 * Workspace HTML slideshows live in `slideshows/<slug>/` (outside the
 * wiki and independent of the Sketch collection). Sandboxed iframe at
 * `/api/slideshows/<slug>/index.html` so relative media resolve.
 *
 * Open via: File browser · `[[slideshow:slug|title]]` · `/slideshow <slug>`.
 * Closable via ✕ (same pattern as Intro) — reopen anytime with those entry points.
 *
 * First-open race: the daemon hello + open event can arrive before this
 * lazy tab mounts. We seed from `getLastHtmlDeckOpen()` so a plain click
 * on a sealed package still shows the deck (not only right-click when
 * the tab is already up).
 *
 * Save PDF writes at the session label with one click. A destination
 * outside the trust boundary uses the OK / Always allow / Cancel dialog.
 * AES-256 is an optional toggle, and it is hidden when a Purview
 * labeling endpoint is configured.
 */
export default function HtmlDeckTab() {
  const [show, setShow] = useState<HtmlDeckShow | null>(() => getLastHtmlDeckOpen());
  const [closing, setClosing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [destination, setDestination] = useState("");
  const [encrypt, setEncrypt] = useState(false);
  const [encryptMode, setEncryptMode] = useState<"password" | "certificate">("password");
  const [secret, setSecret] = useState("");
  const [purview, setPurview] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [boundary, setBoundary] = useState<{ path: string; service: string } | null>(null);

  useEffect(() => {
    // Re-read in case notify landed between first render and effect.
    const pending = getLastHtmlDeckOpen();
    if (pending) setShow(pending);

    const onOpen = (ev: Event) => {
      const d = (ev as CustomEvent).detail as { slug?: string; title?: string };
      if (d?.slug) {
        setShow({ slug: d.slug, title: d.title || d.slug });
      }
    };
    window.addEventListener("sy:open-html-deck", onOpen);
    return () => window.removeEventListener("sy:open-html-deck", onOpen);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void fetch("/api/exports/policy")
      .then((response) => (response.ok ? response.json() : {}))
      .then((body: { purview_endpoint?: boolean }) => {
        if (!cancelled) setPurview(body.purview_endpoint === true);
      })
      .catch(() => { /* encryption stays available when the route is absent */ });
    return () => { cancelled = true; };
  }, [show?.slug]);

  const close = async () => {
    setClosing(true);
    try {
      // Server drops the tab from mode.json, broadcasts hello + nav to Graph.
      clearHtmlDeckOpen();
      await fetch("/api/slideshows/close", { method: "POST" });
    } catch {
      setClosing(false);
    }
  };

  if (!show) {
    return (
      <div className="sy-report-host">
        <div className="sy-report-bar">
          <span className="sy-report-title">Slideshow</span>
          <button
            className="sy-report-pop"
            type="button"
            style={{ marginLeft: 0, cursor: "pointer" }}
            onClick={close}
            disabled={closing}
            title="Close the Slideshow tab — reopen with /slideshow &lt;slug&gt;"
          >
            ✕ close
          </button>
        </div>
        <div className="sy-report-empty">
          <div className="sy-report-empty-inner">
            <div className="sy-report-glyph">▦</div>
            <p>
              HTML <strong>slideshows</strong> land here (separate from Sketch
              files). They live in <code>slideshows/&lt;slug&gt;/</code> and link
              from wiki pages with{" "}
              <code>[[slideshow:slug|title]]</code>. List with{" "}
              <code>/slideshows</code>; open with{" "}
              <code>/slideshow &lt;slug&gt;</code>.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const src = `/api/slideshows/${encodeURIComponent(show.slug)}/index.html`;

  const savePdf = async (confirm?: string) => {
    if (encrypt && !purview && !secret.trim()) {
      setError("Enter a password or recipient certificate, or turn encryption off.");
      return;
    }
    setExporting(true);
    setError("");
    try {
      const payload: Record<string, unknown> = { slug: show.slug };
      if (destination.trim()) payload.destination = destination.trim();
      if (confirm) payload.confirm = confirm;
      if (encrypt && !purview && secret) {
        payload.encrypt = encryptMode === "password"
          ? { mode: "password", password: secret }
          : { mode: "certificate", certificate: secret };
      }
      const response = await fetch("/api/slideshows/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await response.json().catch(() => ({})) as {
        path?: string; error?: string; detail?: string;
        needs_dialog?: boolean; service?: string; label?: string;
      };
      if (body.needs_dialog) {
        setBoundary({ path: body.path || destination, service: body.service || "a synced folder" });
        return;
      }
      if (confirm === "cancel") {
        setBoundary(null);
        setStatus("Export cancelled.");
        return;
      }
      if (!response.ok) {
        throw new Error(body.detail || body.error || `HTTP ${response.status}`);
      }
      setBoundary(null);
      setSecret("");
      setStatus(`Saved ${body.path}`);
      window.dispatchEvent(new CustomEvent("sy:rail-system-tip", {
        detail: { text: `Saved slideshow PDF to \`${body.path}\`.`, focus: false },
      }));
    } catch (err) {
      setBoundary(null);
      setError(`PDF export failed: ${(err as Error).message}`);
    } finally {
      setExporting(false);
    }
  };

  const encryptFields = !purview ? (
    <>
      <label>
        <input
          type="checkbox"
          data-testid="export-encrypt-toggle"
          checked={encrypt}
          onChange={(event) => setEncrypt(event.target.checked)}
        />
        {" "}Encrypt (AES-256)
      </label>
      {encrypt && (
        <>
          <select
            aria-label="Encryption mode"
            value={encryptMode}
            onChange={(event) => setEncryptMode(event.target.value as "password" | "certificate")}
          >
            <option value="password">Password</option>
            <option value="certificate">Recipient certificate</option>
          </select>
          {encryptMode === "password" ? (
            <input
              type="password"
              aria-label="PDF password"
              value={secret}
              onChange={(event) => setSecret(event.target.value)}
            />
          ) : (
            <textarea
              aria-label="Recipient certificate"
              value={secret}
              rows={3}
              onChange={(event) => setSecret(event.target.value)}
              placeholder="PEM certificate or public key"
            />
          )}
        </>
      )}
    </>
  ) : null;

  return (
    <div className="sy-report-host">
      <div className="sy-report-bar">
        <span className="sy-report-title">{show.title}</span>
        <span className="sy-report-meta" style={{ opacity: 0.65, fontSize: 12 }}>
          slideshows/{show.slug}/
        </span>
        <a
          className="sy-report-pop"
          href={src}
          target="_blank"
          rel="noreferrer"
          title="Open fullscreen in a new browser tab"
        >
          ⤢ fullscreen
        </a>
        <button
          className="sy-report-pop"
          type="button"
          data-testid="save-pdf"
          style={{ marginLeft: 0, cursor: "pointer" }}
          onClick={() => void savePdf()}
          disabled={exporting || boundary !== null}
          title="Save one 16:9 PDF page per slide. The file label is the session label."
          aria-label="Save PDF"
        >
          {exporting ? "rendering…" : "↓ save PDF"}
        </button>
        <button
          className="sy-report-pop"
          type="button"
          style={{ marginLeft: 0, cursor: "pointer" }}
          onClick={close}
          disabled={closing}
          title="Close the Slideshow tab — reopen with /slideshow &lt;slug&gt; or a [[slideshow:…]] link"
        >
          ✕ close
        </button>
      </div>
      {status && <p className="sy-pdf-status" data-testid="pdf-export-status">{status}</p>}
      {error && <p className="sy-pdf-error" data-testid="pdf-export-error" role="alert">{error}</p>}
      <details className="sy-pdf-options" data-testid="pdf-export-options">
        <summary>PDF options</summary>
        <label>
          Destination{" "}
          <input
            aria-label="PDF destination"
            value={destination}
            onChange={(event) => setDestination(event.target.value)}
            placeholder="vault/exports"
          />
        </label>
        {boundary ? null : encryptFields}
      </details>
      {boundary && (
        <div className="sy-confirm-backdrop" data-testid="export-destination-dialog">
          <div className="sy-confirm" role="dialog" aria-labelledby="sy-export-dest-title">
            <div id="sy-export-dest-title" className="sy-confirm-title">Outside the trust boundary</div>
            <div className="sy-confirm-body">
              <p>
                <span className="sy-confirm-path">{boundary.path}</span>
                {" "}is in {boundary.service}. Saving copies the PDF into that folder.
              </p>
              {encryptFields}
            </div>
            <div className="sy-confirm-actions">
              <button type="button" className="sy-confirm-btn sy-confirm-btn--primary" onClick={() => void savePdf("ok")}>OK</button>
              <button type="button" className="sy-confirm-btn" onClick={() => void savePdf("always")}>Always allow</button>
              <button type="button" className="sy-confirm-btn" onClick={() => void savePdf("cancel")}>Cancel</button>
            </div>
          </div>
        </div>
      )}
      <iframe
        className="sy-report-frame"
        title={show.title}
        sandbox="allow-scripts"
        src={src}
      />
    </div>
  );
}
