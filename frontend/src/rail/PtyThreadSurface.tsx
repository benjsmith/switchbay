import { useCallback, useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebglAddon } from "@xterm/addon-webgl";
import "@xterm/xterm/css/xterm.css";

/**
 * The rail surface for an `interactive-pty` thread (Foundation B).
 * When the focused thread's kind is interactive-pty, <Rail> renders
 * this xterm surface in place of the transcript + composer — the
 * thread IS a terminal.
 *
 * Wire-up (term.* channel on the shared rail WS):
 *   · Mount → `term.attach {thread_id}` — the daemon reuses the
 *     thread's live PTY session (reply carries the replay buffer so
 *     scrollback survives switches/reconnects) or respawns a fresh
 *     shell into the thread when the old one exited. PTY threads are
 *     durable; sessions aren't.
 *   · Daemon broadcasts `term.output` (base64) → xterm.write.
 *   · Keystrokes round-trip via `term.input`; fit-addon resizes via
 *     `term.resize` so vim/less redraw correctly.
 *
 * The component is keyed by threadId in Rail, so switching threads
 * remounts a fresh xterm and re-attaches — no cross-thread bleed.
 */

export type TerminalWsApi = {
  send: (msg: Record<string, unknown>) => void;
  onMessage: (handler: (msg: Record<string, unknown>) => void) => () => void;
};

function _isDarkTheme(): boolean {
  return document.documentElement.getAttribute("data-theme") !== "light";
}

/** xterm theme per app theme. Dark: a slightly-elevated surface (so the
 *  terminal reads distinct from the graph bg `--bg` and the chrome) with
 *  the Catppuccin Mocha text palette. Light: Catppuccin Latte (dark text
 *  on a light surface) so it's not a black box in light mode. */
function _xtermTheme(dark: boolean): Record<string, string> {
  if (dark) {
    return {
      background: "#181c24",   // lighter than --bg (#0f1115); a panel surface
      foreground: "#cdd6f4", cursor: "#f5e0dc", cursorAccent: "#181c24",
      selectionBackground: "#3a3f4b",
      black: "#45475a", red: "#f38ba8", green: "#a6e3a1", yellow: "#f9e2af",
      blue: "#89b4fa", magenta: "#f5c2e7", cyan: "#94e2d5", white: "#bac2de",
      brightBlack: "#585b70", brightRed: "#f38ba8", brightGreen: "#a6e3a1",
      brightYellow: "#f9e2af", brightBlue: "#89b4fa", brightMagenta: "#f5c2e7",
      brightCyan: "#94e2d5", brightWhite: "#a6adc8",
    };
  }
  return {
    background: "#eef1f6",     // light surface, distinct from --bg (#f8f9fb)
    foreground: "#4c4f69", cursor: "#dc8a78", cursorAccent: "#eef1f6",
    selectionBackground: "#ccd0da",
    black: "#5c5f77", red: "#d20f39", green: "#40a02b", yellow: "#df8e1d",
    blue: "#1e66f5", magenta: "#ea76cb", cyan: "#179299", white: "#acb0be",
    brightBlack: "#6c6f85", brightRed: "#d20f39", brightGreen: "#40a02b",
    brightYellow: "#df8e1d", brightBlue: "#1e66f5", brightMagenta: "#ea76cb",
    brightCyan: "#179299", brightWhite: "#bcc0cc",
  };
}

/** Decode a base64 string from the daemon into a Uint8Array so
 *  xterm's parser does real UTF-8 decoding (a raw atob() "binary
 *  string" breaks every TUI's box drawing). */
function b64ToBytes(s: string): Uint8Array {
  const raw = atob(s);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i) & 0xff;
  return out;
}

type SessionMeta = {
  id: string;
  name: string;
  exited: boolean;
  exit_code: number | null;
};

type Props = {
  threadId: string;
  ws: TerminalWsApi | null;
  /** Which host this surface lives in — only "rail" attaches feed
   *  the daemon's pre-surface spawn-size hint (a wide tab would
   *  poison `!cmd` spawn widths). */
  surface?: "rail" | "tab";
  /** Rail surface only: pop this terminal out into a center tab
   *  (multi-terminal setups; room for coding-agent TUIs). */
  onPopOut?: () => void;
  /** Tab surface only: close the tab and use the rail again. */
  onPopIn?: () => void;
  /** Override the pop-out/pop-in button labels+titles (Zen promotes
   *  to the right pane, not a tab — the wording must say so). */
  popOutLabel?: { label: string; title: string };
  popInLabel?: { label: string; title: string };
};

export default function PtyThreadSurface({
  threadId, ws, surface = "rail", onPopOut, onPopIn, popOutLabel, popInLabel,
}: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<{ term: Terminal; fit: FitAddon } | null>(null);
  // The live PTY session id — keystrokes/resize address it. A ref
  // (not just state) because xterm's onData closure must always see
  // the current id, including after a respawn re-attach.
  const sessionIdRef = useRef<string | null>(null);
  const [session, setSession] = useState<SessionMeta | null>(null);
  const [error, setError] = useState<string | null>(null);

  const attach = useCallback(() => {
    if (!ws) return;
    setError(null);
    // Carry the fitted size so a fresh spawn's first prompt paint is
    // already the right width — the daemon otherwise spawns 80-col
    // and a powerline prompt wraps in the ~45-col rail before the
    // post-adopt resize can reach the shell.
    const inst = termRef.current;
    ws.send({
      type: "term.attach",
      thread_id: threadId,
      rows: inst?.term.rows ?? 0,
      cols: inst?.term.cols ?? 0,
      surface,
    });
  }, [ws, threadId, surface]);

  // Build the xterm once per mount (Rail keys this component by
  // threadId, so a thread switch remounts cleanly).
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      // Powerline/Nerd-Font crispness — same setup the old docked
      // panel used: WebGL custom-draws powerline separators
      // edge-to-edge; rescale keeps oversized Nerd-Font icons in-cell.
      customGlyphs: true,
      rescaleOverlappingGlyphs: true,
      fontFamily:
        '"MesloLGS Nerd Font Mono", "MesloLGS NF", '
        + 'ui-monospace, SFMono-Regular, Menlo, monospace',
      theme: _xtermTheme(_isDarkTheme()),
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(host);
    // WebGL renderer with DOM fall-through — a missing GPU context
    // must never break the terminal.
    try {
      const webgl = new WebglAddon();
      webgl.onContextLoss(() => webgl.dispose());
      term.loadAddon(webgl);
    } catch { /* DOM renderer stays active */ }
    term.onData((data) => {
      const sid = sessionIdRef.current;
      if (!sid) return;
      ws?.send({
        type: "term.input",
        id: sid,
        data: btoa(unescape(encodeURIComponent(data))),
      });
    });
    term.onResize(({ rows, cols }) => {
      const sid = sessionIdRef.current;
      if (!sid) return;
      ws?.send({ type: "term.resize", id: sid, rows, cols });
    });
    termRef.current = { term, fit };
    try { fit.fit(); } catch { /* not laid out yet */ }
    // Nerd-Font metric drift: if "MesloLGS Nerd Font Mono" finishes
    // loading after the first fit, cols were measured against the
    // fallback font and the PTY is a few columns off — the classic
    // "powerline prompt wraps by one segment". Re-fit once fonts
    // settle; the onResize hook pushes the corrected size to the PTY.
    void document.fonts?.ready?.then(() => {
      if (termRef.current?.term === term) {
        try { fit.fit(); } catch { /* not laid out */ }
      }
    });
    const ro = new ResizeObserver(() => {
      try { fit.fit(); } catch { /* swallow */ }
    });
    ro.observe(host);
    // Re-theme on app theme toggle.
    const obs = new MutationObserver(() => {
      try { term.options.theme = _xtermTheme(_isDarkTheme()); } catch { /* ignore */ }
    });
    obs.observe(document.documentElement, {
      attributes: true, attributeFilter: ["data-theme"],
    });
    return () => {
      ro.disconnect();
      obs.disconnect();
      try { term.dispose(); } catch { /* already disposed */ }
      termRef.current = null;
    };
    // ws is stable for the app's lifetime (adapter over the singleton
    // RailSocket); threadId remounts via key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Attach on mount + whenever the WS API becomes ready.
  useEffect(() => { attach(); }, [attach]);

  // term.* message routing for THIS thread's session.
  useEffect(() => {
    if (!ws) return;
    return ws.onMessage((msg) => {
      const type = String(msg.type ?? "");
      if (type === "term.opened") {
        // Only adopt sessions attached for our thread — `!cmd` spawns
        // for other threads broadcast nothing here (attach replies are
        // targeted), but be defensive anyway.
        if (String(msg.thread_id ?? "") !== threadId) return;
        const s = msg.session as SessionMeta & { rows?: number };
        if (!s) return;
        sessionIdRef.current = s.id;
        setSession({ id: s.id, name: s.name, exited: false, exit_code: null });
        const inst = termRef.current;
        if (inst) {
          inst.term.reset();
          try { inst.fit.fit(); } catch { /* swallow */ }
          // ALWAYS push the fitted size to the PTY on adopt, and do
          // it BEFORE painting the replay. fit() only fires onResize
          // when the xterm's dims CHANGE — after the mount-time fit
          // they usually don't, so without this the shell stays at
          // the spawn default (80×24) while xterm renders narrower/
          // wider: powerline prompt bars overflowing the rail,
          // zsh-autosuggestion smear. With the size agreed first,
          // replay bytes recorded at another width WRAP instead of
          // bleeding, and the SIGWINCH makes the shell redraw its
          // prompt fitted to the real width (starship/p10k then
          // front-truncate long folder names themselves).
          ws?.send({
            type: "term.resize", id: s.id,
            rows: inst.term.rows, cols: inst.term.cols,
          });
          const replay = String(msg.replay ?? "");
          if (replay) {
            try { inst.term.write(b64ToBytes(replay)); } catch { /* ignore */ }
          }
          inst.term.focus();
        }
      } else if (type === "term.output") {
        if (String(msg.id ?? "") !== sessionIdRef.current) return;
        const data = String(msg.data ?? "");
        if (!data) return;
        try { termRef.current?.term.write(b64ToBytes(data)); } catch { /* ignore */ }
      } else if (type === "term.exit") {
        if (String(msg.id ?? "") !== sessionIdRef.current) return;
        const code = (msg.exit_code as number | null) ?? null;
        termRef.current?.term.write(
          `\r\n\x1b[2m[process exited code=${code ?? "?"} — ⏎ respawn]\x1b[0m\r\n`,
        );
        setSession((cur) => (cur ? { ...cur, exited: true, exit_code: code } : cur));
      } else if (type === "term.error") {
        setError(String(msg.message ?? "terminal error"));
      } else if (type === "term.reset") {
        // Daemon restarted: our session id is stale. Re-attach — the
        // daemon respawns a fresh shell into this (durable) thread.
        sessionIdRef.current = null;
        setSession(null);
        attach();
      }
    });
  }, [ws, threadId, attach]);

  const respawn = useCallback(() => {
    sessionIdRef.current = null;
    attach();
  }, [attach]);

  const kill = useCallback(() => {
    const sid = sessionIdRef.current;
    if (sid) ws?.send({ type: "term.kill", id: sid });
  }, [ws]);

  return (
    <div className="sy-rail-pty">
      <div className="sy-rail-pty-head">
        <span className="sy-rail-pty-name" title={session?.id ?? ""}>
          {session?.name ?? "shell"}
        </span>
        {onPopOut && (
          <button
            type="button"
            className="sy-rail-pty-btn"
            onClick={onPopOut}
            title={popOutLabel?.title
              ?? "Open this terminal as a center tab — more room, and it stays one tab-switch away"}
          >
            {popOutLabel?.label ?? "⇱ tab"}
          </button>
        )}
        {onPopIn && (
          <button
            type="button"
            className="sy-rail-pty-btn"
            onClick={onPopIn}
            title={popInLabel?.title
              ?? "Close this tab — the terminal moves back to the rail (thread and session keep running)"}
          >
            {popInLabel?.label ?? "⇲ sidebar"}
          </button>
        )}
        {session?.exited ? (
          <>
            <span className="sy-rail-pty-exit">
              exited {session.exit_code ?? "?"}
            </span>
            <button
              type="button"
              className="sy-rail-pty-btn"
              onClick={respawn}
              title="Start a fresh shell in this thread"
            >
              ↺ respawn
            </button>
            <button
              type="button"
              className="sy-rail-pty-btn"
              onClick={() => {
                // Archive the thread — the daemon refocuses the most
                // recent surviving thread and broadcasts, so the dead
                // terminal leaves the rail without a trip to the
                // thread switcher.
                void fetch(
                  `/api/threads/${encodeURIComponent(threadId)}/archive`,
                  { method: "POST" },
                ).catch(() => { /* daemon down */ });
              }}
              title="Close this shell thread (archives it — history stays searchable)"
            >
              ✕ close
            </button>
          </>
        ) : (
          <button
            type="button"
            className="sy-rail-pty-btn"
            onClick={kill}
            title="SIGTERM this shell (the thread stays; refocusing respawns)"
          >
            ✕ kill
          </button>
        )}
      </div>
      {error && <div className="sy-rail-pty-error">{error}</div>}
      <div ref={hostRef} className="sy-rail-pty-host" />
    </div>
  );
}
