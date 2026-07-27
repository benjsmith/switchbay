import { useState } from "react";

/**
 * Hopper tab — hosts the bundled Mars Hopper game
 * (`static/mars-hopper/`, served at `/api/easter/mars-hopper/`) in a
 * SANDBOXED iframe (scripts allowed, no `allow-same-origin`, so the
 * game runs at an opaque origin and can't touch the app or `/api/*`).
 *
 * Armed via Settings → cryptic "fire thrusters?" toggle; closable via
 * the tab's own ✕ or by flipping the toggle off.
 */
export default function ThrustersTab() {
  const [closing, setClosing] = useState(false);

  const close = async () => {
    setClosing(true);
    try {
      await fetch("/api/easter/thrusters/close", { method: "POST" });
    } catch {
      setClosing(false);
    }
  };

  return (
    <div className="sy-report-host">
      <div className="sy-report-bar">
        <span className="sy-report-title">Mars Hopper</span>
        <a
          className="sy-report-pop"
          href="/api/easter/mars-hopper"
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
          onClick={() => void close()}
          disabled={closing}
          title="Cut thrusters — re-arm from Settings"
        >
          ✕ close
        </button>
      </div>
      <iframe
        className="sy-report-frame"
        title="Mars Hopper"
        sandbox="allow-scripts"
        src="/api/easter/mars-hopper"
      />
    </div>
  );
}
