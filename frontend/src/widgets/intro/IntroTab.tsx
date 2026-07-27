import { useState } from "react";

/**
 * Intro tab — hosts the bundled intro-and-benchmark deck
 * (`intro_and_bench.html`, served at `/api/intro`) in a SANDBOXED
 * iframe (scripts allowed, but no `allow-same-origin`, so the deck runs
 * at an opaque origin and can't touch the app or reach `/api/*`). The
 * deck is fully self-contained — inline scripts + base64 images, no
 * network — so the sandbox costs it nothing.
 *
 * Seeded pinned-first on first install; closable via the ✕ (the server
 * drops the tab and moves focus to the Graph). Reopen anytime with the
 * `/intro` slash command.
 */
export default function IntroTab() {
  const [closing, setClosing] = useState(false);

  const close = async () => {
    setClosing(true);
    try {
      // Server broadcasts the new tab set (drops this tab) + a nav to
      // the Graph, so the pane doesn't blank after we unmount.
      await fetch("/api/intro/close", { method: "POST" });
    } catch {
      setClosing(false);
    }
  };

  return (
    <div className="sy-report-host">
      <div className="sy-report-bar">
        <span className="sy-report-title">Intro to Switch Bay</span>
        <a
          className="sy-report-pop"
          href="/api/intro"
          target="_blank"
          rel="noreferrer"
          title="Open the deck fullscreen in a new browser tab"
        >
          ⤢ fullscreen
        </a>
        <button
          className="sy-report-pop"
          type="button"
          style={{ marginLeft: 0, cursor: "pointer" }}
          onClick={close}
          disabled={closing}
          title="Close the Intro tab — reopen anytime with /intro"
        >
          ✕ close
        </button>
      </div>
      <iframe
        className="sy-report-frame"
        title="Intro to Switch Bay"
        sandbox="allow-scripts"
        src="/api/intro"
      />
    </div>
  );
}
