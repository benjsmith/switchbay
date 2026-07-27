/** Top-bar affordance for the always-on-daemon model: shows how many
 *  agent/curation runs are active and lets the user stop them all.
 *  Closing the app window leaves runs going (the daemon stays up under
 *  launchd) — this is the explicit "terminate the work too" choice.
 *  Hidden when nothing's running. */

import { useEffect, useRef, useState } from "react";

export default function RunningTasksButton() {
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const r = await fetch("/api/runs/active");
        if (!r.ok) return;
        const body = (await r.json()) as { runs?: { status?: string }[] };
        // Only genuinely-streaming runs count — dormant shells (status
        // "idle": a pty at its prompt / a TUI waiting for input) and
        // lingering finished rows are not running work.
        const live = Array.isArray(body.runs)
          ? body.runs.filter(
              (x) => !x.status || ["running", "planning", "merging"].includes(x.status),
            ).length
          : 0;
        if (!cancelled) setCount(live);
      } catch {
        /* daemon momentarily unreachable — leave last count */
      }
    };
    void poll();
    const id = setInterval(poll, 2500);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  if (count === 0) return null;

  const stopAll = async () => {
    setBusy(true);
    try {
      await fetch("/api/runs/stop-all", { method: "POST" });
      setOpen(false);
    } catch {
      /* swallow — the next poll reflects reality */
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sy-runtasks" ref={ref}>
      <button
        type="button"
        className="sy-icon-btn sy-runtasks-btn"
        title={`${count} task${count === 1 ? "" : "s"} running`}
        aria-label={`${count} running tasks`}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="sy-runtasks-dot" />
        <span className="sy-runtasks-count">{count}</span>
      </button>
      {open && (
        <div className="sy-runtasks-pop" role="dialog">
          <p className="sy-runtasks-poptitle">
            {count} task{count === 1 ? "" : "s"} running
          </p>
          <p className="sy-runtasks-note">
            These keep running in the background if you close this window —
            the daemon stays up. Stop them only if you want the work
            cancelled now.
          </p>
          <div className="sy-runtasks-actions">
            <button
              type="button"
              className="sy-confirm-btn"
              onClick={() => {
                setOpen(false);
                window.dispatchEvent(
                  new CustomEvent("sy:agents-panel", { detail: { state: "expanded" } }),
                );
              }}
            >
              Open Agents panel →
            </button>
            <button
              type="button"
              className="sy-confirm-btn"
              disabled={busy}
              onClick={() => void stopAll()}
            >
              {busy ? "Stopping…" : "Stop all running tasks"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
