import PtyThreadSurface from "../../rail/PtyThreadSurface";
import type { TabContext } from "../../center/tabRegistry";

/**
 * A popped-out terminal: a user tab (kind "terminal") hosting one
 * `interactive-pty` thread's xterm surface full-width in the center
 * column. Tabs of this kind exist only by deliberate pop-out from the
 * rail (⇱ tab) — there is no standing Terminal tab. Several can
 * coexist (one per thread), replicating the classic multi-terminal-tab
 * setup; other shells stay in the sidebar.
 *
 * "⇲ sidebar" removes the tab and refocuses the thread so the
 * terminal reappears in the rail — the thread and its live session
 * are untouched either way; only the surface moves.
 */
export default function TerminalTab({ tab, termWs }: TabContext) {
  const threadId = String(
    (tab.payload as { thread_id?: unknown } | undefined)?.thread_id ?? "",
  );

  const popIn = async () => {
    try {
      await fetch("/api/tabs/terminal/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tab_id: tab.id }),
      });
      // Refocus the thread so the terminal is immediately visible in
      // the rail rather than silently vanishing with the tab.
      if (threadId) {
        await fetch("/api/threads/focus", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ thread_id: threadId }),
        });
      }
    } catch { /* daemon down — tab stays; retry is a click away */ }
  };

  if (!threadId) {
    // Hand-edited / corrupted mode.json entry.
    return (
      <div className="sy-term-tab sy-term-tab--broken">
        <p>This terminal tab has no thread bound.</p>
        <button type="button" className="sy-rail-pty-btn" onClick={popIn}>
          remove tab
        </button>
      </div>
    );
  }
  return (
    <div className="sy-term-tab">
      <PtyThreadSurface
        key={threadId}
        threadId={threadId}
        ws={termWs}
        surface="tab"
        onPopIn={popIn}
      />
    </div>
  );
}
