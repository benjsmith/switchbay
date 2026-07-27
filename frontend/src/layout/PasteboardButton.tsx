import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Top-bar button + popover for the per-workspace pasteboard ring.
 *
 * The OS clipboard only holds one thing; the pasteboard holds N
 * (capped server-side at 30). Workflow: stash interesting bits as
 * you go via "+ Stash clipboard" (or Cmd/Ctrl+Shift+V), then click
 * any slot to copy it back to the OS clipboard for pasting
 * elsewhere.
 *
 * Persists across sessions via .workbench/state/pasteboard.json
 * — collected snippets survive restarts, workspace switches reset
 * (each workspace has its own pasteboard).
 */

type SlotMeta = {
  id: string;
  kind: "text" | "image" | string;
  captured_at: number;
  preview: string;
  truncated: boolean;
  size: number;
  image_filename?: string;
};

const POLL_MS = 4000;

export default function PasteboardButton() {
  const [open, setOpen] = useState(false);
  const [slots, setSlots] = useState<SlotMeta[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  const reload = useCallback(async () => {
    try {
      const r = await fetch("/api/pasteboard");
      if (!r.ok) { setError(`HTTP ${r.status}`); return; }
      const body = (await r.json()) as { slots: SlotMeta[] };
      setSlots(body.slots);
      setError(null);
    } catch (e) { setError((e as Error).message); }
  }, []);

  // Reload whenever the popover opens, plus a slow background poll
  // while it stays open so external edits to pasteboard.json
  // (other process / hand-edit / future MCP tool) surface promptly.
  useEffect(() => {
    if (!open) return;
    void reload();
    const id = window.setInterval(() => { void reload(); }, POLL_MS);
    return () => window.clearInterval(id);
  }, [open, reload]);

  // Outside-click + Escape close. Same pattern as ProviderPicker.
  useEffect(() => {
    if (!open) return;
    const onDoc = (ev: MouseEvent) => {
      const t = ev.target as Node | null;
      if (!t) return;
      if (popRef.current?.contains(t)) return;
      if (btnRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") { setOpen(false); }
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Cmd/Ctrl-Shift-V opens the popover. Reads the clipboard via the
  // shortcut handler (still a user-gesture context, so the browser
  // permission prompt fires once and then persists).
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if ((ev.metaKey || ev.ctrlKey) && ev.shiftKey && ev.key.toLowerCase() === "v") {
        ev.preventDefault();
        setOpen(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const stashClipboard = useCallback(async () => {
    setStatus(null);
    // Try `read()` first — it returns ClipboardItem[] which can carry
    // image MIME types alongside text. Fall back to `readText()` on
    // browsers that don't support `read()` or when the user denies
    // image permission.
    let imageBlob: Blob | null = null;
    let text = "";
    try {
      // Some browsers (Firefox) don't expose navigator.clipboard.read.
      const reader = (navigator.clipboard as unknown as {
        read?: () => Promise<ClipboardItem[]>;
      }).read;
      if (reader) {
        const items = await reader.call(navigator.clipboard);
        for (const item of items) {
          // Prefer PNG; fall back to JPEG. Skip text types here —
          // we'll fetch text via readText() below if no image.
          if (item.types.includes("image/png")) {
            imageBlob = await item.getType("image/png");
            break;
          }
          if (item.types.includes("image/jpeg")) {
            imageBlob = await item.getType("image/jpeg");
            break;
          }
        }
      }
      if (!imageBlob) {
        text = await navigator.clipboard.readText();
      }
    } catch (e) {
      // Permission denied OR the clipboard had nothing readable. Try
      // a plain readText as a safety net before giving up.
      try { text = await navigator.clipboard.readText(); }
      catch { setStatus(`clipboard read denied: ${(e as Error).message}`); return; }
    }

    if (imageBlob) {
      // Convert blob → base64 → POST as kind=image. The browser
      // FileReader path keeps memory in one round-trip rather than
      // staging a typed-array.
      try {
        const dataUrl = await new Promise<string>((resolve, reject) => {
          const r = new FileReader();
          r.onload = () => resolve(String(r.result));
          r.onerror = () => reject(r.error);
          r.readAsDataURL(imageBlob!);
        });
        const r = await fetch("/api/pasteboard", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: "image", image_b64: dataUrl }),
        });
        if (!r.ok) {
          setStatus(`save failed: HTTP ${r.status}`);
          return;
        }
        const sizeKb = Math.round(imageBlob.size / 1024);
        setStatus(`stashed image · ${sizeKb} KB`);
        await reload();
      } catch (e) { setStatus((e as Error).message); }
      return;
    }

    if (!text.trim()) {
      setStatus("clipboard is empty");
      return;
    }
    try {
      const r = await fetch("/api/pasteboard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: "text", content: text }),
      });
      if (!r.ok) { setStatus(`save failed: HTTP ${r.status}`); return; }
      setStatus(`stashed ${text.length} chars`);
      await reload();
    } catch (e) { setStatus((e as Error).message); }
  }, [reload]);

  const copySlot = useCallback(async (slot: SlotMeta) => {
    setStatus(null);
    try {
      if (slot.kind === "image") {
        // Image path: fetch the PNG bytes, write to clipboard via
        // ClipboardItem so the user can paste into image-aware apps.
        // Browsers without ClipboardItem support fall back to no-op
        // with an explanatory status.
        const has = typeof window.ClipboardItem !== "undefined";
        if (!has) {
          setStatus("browser doesn't support image clipboard write");
          return;
        }
        const r = await fetch(`/api/pasteboard/image?id=${encodeURIComponent(slot.id)}`);
        if (!r.ok) { setStatus("image bytes missing"); return; }
        const blob = await r.blob();
        await navigator.clipboard.write([
          new ClipboardItem({ "image/png": blob }),
        ]);
        setStatus(`copied image · ${Math.round(blob.size / 1024)} KB`);
      } else {
        const r = await fetch(`/api/pasteboard/slot?id=${encodeURIComponent(slot.id)}`);
        if (!r.ok) { setStatus("slot missing"); return; }
        const body = (await r.json()) as { slot: { content?: string } };
        const content = body.slot?.content;
        if (typeof content !== "string") { setStatus("empty slot"); return; }
        await navigator.clipboard.writeText(content);
        setStatus(`copied ${content.length} chars`);
      }
      // Auto-close after a successful copy — the user's next move
      // is almost always to paste elsewhere, so the popover would
      // just be in the way.
      window.setTimeout(() => setOpen(false), 400);
    } catch (e) { setStatus((e as Error).message); }
  }, []);

  const removeSlot = useCallback(async (slotId: string) => {
    // Clear the status banner — it confirms the most recent stash
    // action, which no longer applies once a slot is removed.
    setStatus(null);
    await fetch(`/api/pasteboard?id=${encodeURIComponent(slotId)}`, { method: "DELETE" });
    await reload();
  }, [reload]);

  const clearAll = useCallback(async () => {
    if (!window.confirm("Clear every pasteboard slot?")) return;
    setStatus(null);
    await fetch("/api/pasteboard/clear", { method: "POST" });
    await reload();
  }, [reload]);

  return (
    <div className="sy-pasteboard-wrap">
      <button
        ref={btnRef}
        type="button"
        className="sy-pasteboard-btn"
        onClick={() => setOpen((v) => !v)}
        title="Pasteboard ring (Cmd+Shift+V)"
        aria-label="Pasteboard"
      >
        <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3.5" y="2.5" width="9" height="11" rx="1"/>
          <rect x="5.5" y="1" width="5" height="2.5" rx="0.5"/>
          <line x1="5.5" y1="6.5" x2="10.5" y2="6.5"/>
          <line x1="5.5" y1="9" x2="10.5" y2="9"/>
        </svg>
      </button>
      {open && (
        <div ref={popRef} className="sy-pasteboard-pop" role="dialog" aria-label="Pasteboard">
          <div className="sy-pasteboard-head">
            <span className="sy-pasteboard-title">Pasteboard</span>
            <span className="sy-spacer" />
            <button
              type="button"
              className="sy-vega-toolbar-btn"
              onClick={stashClipboard}
              title="Read OS clipboard and add as a new slot"
            >
              + Stash clipboard
            </button>
            <button
              type="button"
              className="sy-vega-toolbar-btn"
              onClick={clearAll}
              disabled={!slots || slots.length === 0}
              title="Remove every slot"
            >
              Clear all
            </button>
          </div>
          {status && <div className="sy-pasteboard-status">{status}</div>}
          {error && <div className="sy-pasteboard-err">{error}</div>}
          {slots === null ? (
            <div className="sy-pasteboard-empty">Loading…</div>
          ) : slots.length === 0 ? (
            <div className="sy-pasteboard-empty">
              Nothing stashed yet. Copy something, then click <strong>+ Stash
              clipboard</strong>.
            </div>
          ) : (
            <ul className="sy-pasteboard-list">
              {slots.map((s) => (
                <li key={s.id} className="sy-pasteboard-slot">
                  <button
                    type="button"
                    className="sy-pasteboard-slot-body"
                    onClick={() => copySlot(s)}
                    title="Copy back to OS clipboard"
                  >
                    {s.kind === "image" ? (
                      <img
                        src={`/api/pasteboard/image?id=${encodeURIComponent(s.id)}`}
                        alt="stashed image"
                        className="sy-pasteboard-slot-thumb"
                      />
                    ) : (
                      <span className="sy-pasteboard-slot-preview">{s.preview}</span>
                    )}
                    <span className="sy-pasteboard-slot-meta">
                      {s.kind === "image"
                        ? `image · ${humanBytes(s.size)}`
                        : humanBytes(s.size) + (s.truncated ? " · truncated preview" : "")}
                      {" · "}{humanAge(s.captured_at)}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="sy-pasteboard-slot-rm"
                    onClick={() => removeSlot(s.id)}
                    title="Forget this slot"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}


function humanBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}


function humanAge(captured_at: number): string {
  const secs = Date.now() / 1000 - captured_at;
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}
