import { useEffect, useState } from "react";
import {
  clearHtmlDeckOpen,
  getLastHtmlDeckOpen,
  type HtmlDeckShow,
} from "./htmlDeckOpen";

/**
 * Workspace HTML slideshows live in `slideshows/<slug>/` (outside the
 * wiki; NOT Sketch kind:deck). Sandboxed iframe at
 * `/api/slideshows/<slug>/index.html` so relative media resolve.
 *
 * Open via: File browser · `[[slideshow:slug|title]]` · `/slideshow <slug>`.
 * Closable via ✕ (same pattern as Intro) — reopen anytime with those entry points.
 *
 * First-open race: the daemon hello + open event can arrive before this
 * lazy tab mounts. We seed from `getLastHtmlDeckOpen()` so a plain click
 * on a sealed package still shows the deck (not only right-click when
 * the tab is already up).
 */
export default function HtmlDeckTab() {
  const [show, setShow] = useState<HtmlDeckShow | null>(() => getLastHtmlDeckOpen());
  const [closing, setClosing] = useState(false);

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
              decks). They live in <code>slideshows/&lt;slug&gt;/</code> and link
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
          style={{ marginLeft: 0, cursor: "pointer" }}
          onClick={close}
          disabled={closing}
          title="Close the Slideshow tab — reopen with /slideshow &lt;slug&gt; or a [[slideshow:…]] link"
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
