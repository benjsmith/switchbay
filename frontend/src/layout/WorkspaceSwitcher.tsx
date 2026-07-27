import { useEffect, useRef, useState } from "react";
import type { Workspaces } from "../ws";
import { toast } from "../lib/toast";

type Props = {
  workspaces: Workspaces;
  modeName: string;
  /** "zen" renders the faint floating-chrome brand trigger (top-left
   *  of Zen mode) instead of Power's top-bar pill; the dropdown menu
   *  and every dialog below are shared verbatim. */
  variant?: "power" | "zen";
  /** Zen only: label to fall back to when the running workspace isn't
   *  in the registered list (the daemon's CLI cwd is a separate
   *  runtime fact) — keeps the brand showing the LIVE workspace name
   *  rather than "—". */
  fallbackLabel?: string;
};

type AddState =
  | { kind: "closed" }
  | { kind: "open"; path: string; submitting: boolean; error: string | null };

function basename(p: string): string {
  return p.split("/").filter(Boolean).pop() ?? p;
}

/** Disambiguate workspaces that share a basename (e.g. after moving one
 *  into the home and re-adding the original). The first keeps the plain
 *  name; later ones get an auto-incremented " (2)", " (3)" … like file
 *  duplicates. Everything underneath is keyed by absolute PATH — this
 *  is display only. Returns path → shown name. */
function disambiguatedNames(paths: string[]): Map<string, string> {
  const seen = new Map<string, number>();
  const out = new Map<string, string>();
  for (const p of paths) {
    const b = basename(p);
    const n = (seen.get(b) ?? 0) + 1;
    seen.set(b, n);
    out.set(p, n === 1 ? b : `${b} (${n})`);
  }
  return out;
}

// ── Merge dialog (D2) ──────────────────────────────────────────────
// Multi-check → name → background deterministic merge (merging.py —
// curiosity-merge's stage/apply scripts; no agent). Originals stay on
// disk and leave the registry; completion = toast with Open.

function MergeDialog({ paths, onClose }: { paths: string[]; onClose: () => void }) {
  const [checked, setChecked] = useState<Set<string>>(() => new Set());
  const [name, setName] = useState("");
  const [homeExpanded, setHomeExpanded] = useState<string | null>(null);
  const [started, setStarted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void fetch("/api/workspaces/home")
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => { if (b) setHomeExpanded((b as { expanded: string }).expanded); })
      .catch(() => { /* older daemon */ });
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-name from the picks ("alpha+beta") until the user types
  // their own; clearing the field re-arms the auto-name.
  const nameEdited = useRef(false);
  const toggle = (p: string) => {
    setChecked((cur) => {
      const next = new Set(cur);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      if (!nameEdited.current) {
        setName(paths.filter((x) => next.has(x)).map(basename).join("+"));
      }
      return next;
    });
  };

  const submit = async () => {
    if (busy || checked.size < 2 || !name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const sources = paths.filter((p) => checked.has(p));  // stable order
      const r = await fetch("/api/workspaces/merge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sources, name: name.trim() }),
      });
      const b = await r.json().catch(() => ({} as { error?: string }));
      if (!r.ok) {
        setError(b.error ?? `HTTP ${r.status}`);
        return;
      }
      setStarted(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sy-confirm-backdrop" onClick={onClose}>
      <div
        className="sy-confirm sy-ws-dialog"
        role="dialog"
        aria-labelledby="sy-merge-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div id="sy-merge-title" className="sy-confirm-title">Merge workspaces</div>
        <div className="sy-confirm-body">
          {started ? (
            <p>
              Building <b>{name}</b> in the background — the first source
              seeds it, then each other source is staged, audited, and
              applied (curiosity-merge's trust pipeline). A toast with an
              Open button lands when it's ready. Originals stay on disk
              and leave the workspace list — re-Add them any time.
            </p>
          ) : (
            <>
              <p>
                Pick two or more. A <b>new</b> workspace is built
                {homeExpanded ? <> in <code>{homeExpanded}/</code></> : null}
                {" "}— the originals are never modified; they just leave
                the list (reversible via + Add).
              </p>
              {paths.map((p) => (
                <label key={p} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, marginBottom: 4 }}>
                  <input
                    type="checkbox"
                    checked={checked.has(p)}
                    onChange={() => toggle(p)}
                  />
                  <span style={{ fontWeight: 600 }}>{basename(p)}</span>
                  <span style={{ color: "var(--text-faint)", fontSize: 10.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p}</span>
                </label>
              ))}
              <div className="sy-ws-input-row" style={{ marginTop: 8 }}>
                <input
                  type="text"
                  className="sy-ws-input"
                  placeholder="merged workspace name"
                  value={name}
                  onChange={(e) => {
                    nameEdited.current = e.target.value !== "";
                    setName(e.target.value);
                  }}
                  spellCheck={false}
                />
              </div>
              {checked.size === 1 && (
                <p style={{ fontSize: 11, color: "var(--text-faint)" }}>pick at least one more…</p>
              )}
              {error && <pre className="sy-ws-error">{error}</pre>}
            </>
          )}
        </div>
        <div className="sy-confirm-actions">
          <button type="button" className="sy-confirm-btn" onClick={onClose}>
            {started ? "Close" : "Cancel"}
          </button>
          {!started && (
            <button
              type="button"
              className="sy-confirm-btn sy-confirm-btn--primary"
              onClick={() => void submit()}
              disabled={busy || checked.size < 2 || !name.trim()}
            >
              {busy ? "Starting…" : `Merge ${checked.size || ""}`.trim()}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}


// ── Share dialog (D3: gh publish) ──────────────────────────────────

type ShareStatus = {
  gh: boolean;
  authed: boolean;
  has_remote: boolean;
  repo_url: string | null;
  workspace_name: string;
  last?: { state: string; url?: string | null; error?: string | null; name?: string };
};

type SharePreview = {
  file_count: number;
  truncated: boolean;
  top_dirs: { dir: string; files: number }[];
  largest: { path: string; bytes: number }[];
  secret_hits: { path: string; line: number; kind: string }[];
};

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function ShareDialog({ onClose }: { onClose: () => void }) {
  const [st, setSt] = useState<ShareStatus | null>(null);
  const [name, setName] = useState("");
  const [priv, setPriv] = useState(true);
  const [vault, setVault] = useState(true);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<SharePreview | null>(null);
  const [ackSecrets, setAckSecrets] = useState(false);

  const refresh = async (): Promise<ShareStatus | null> => {
    try {
      const r = await fetch("/api/share/status");
      if (!r.ok) return null;
      const b = (await r.json()) as ShareStatus;
      setSt(b);
      return b;
    } catch {
      return null;
    }
  };

  useEffect(() => {
    void (async () => {
      const b = await refresh();
      if (b) {
        setName((cur) => cur || b.workspace_name);
        if (b.last?.state === "running") setPublishing(true);
      }
    })();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll while a publish runs (it's a background task server-side).
  useEffect(() => {
    if (!publishing) return;
    const iv = window.setInterval(async () => {
      const b = await refresh();
      const state = b?.last?.state;
      if (state && state !== "running") {
        setPublishing(false);
        if (state === "error") setError(b?.last?.error ?? "publish failed");
      }
    }, 2500);
    return () => window.clearInterval(iv);
  }, [publishing]);

  // Preview what would ship (file set + secret scan). Re-runs when the
  // vault opt-out changes, since that changes the file set. Reset the
  // secret acknowledgement whenever the preview changes.
  useEffect(() => {
    if (!st?.authed) return;
    let live = true;
    setPreview(null);
    setAckSecrets(false);
    void (async () => {
      try {
        const r = await fetch(`/api/share/preview?include_vault=${vault ? 1 : 0}`);
        if (!r.ok || !live) return;
        setPreview((await r.json()) as SharePreview);
      } catch {
        /* preview is best-effort; publish still works without it */
      }
    })();
    return () => { live = false; };
  }, [st?.authed, vault]);

  const hasSecrets = (preview?.secret_hits.length ?? 0) > 0;
  const publishBlocked = hasSecrets && !ackSecrets;

  const publish = async () => {
    if (publishing || publishBlocked) return;
    setError(null);
    setPublishing(true);
    try {
      const r = await fetch("/api/share/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, private: priv, include_vault: vault }),
      });
      if (!r.ok) {
        const b = await r.json().catch(() => ({} as { error?: string }));
        setError(b.error ?? `HTTP ${r.status}`);
        setPublishing(false);
      }
    } catch (e) {
      setError((e as Error).message);
      setPublishing(false);
    }
  };

  const authInRail = () => {
    onClose();
    window.dispatchEvent(new CustomEvent("sy:rail-system-tip", {
      detail: { text: "!gh auth login", focus: true },
    }));
  };

  const doneUrl = st?.last?.state === "done" ? st.last.url : null;

  return (
    <div className="sy-confirm-backdrop" onClick={() => !publishing && onClose()}>
      <div
        className="sy-confirm sy-ws-dialog"
        role="dialog"
        aria-labelledby="sy-share-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div id="sy-share-title" className="sy-confirm-title">Share workspace</div>
        <div className="sy-confirm-body">
          {st === null && <p>checking gh…</p>}
          {st && !st.gh && (
            <p>
              The GitHub CLI isn't installed. Install it
              (<code>brew install gh</code>), sign in with{" "}
              <code>gh auth login</code>, then reopen this dialog.
            </p>
          )}
          {st && st.gh && !st.authed && (
            <>
              <p>
                <code>gh</code> is installed but not signed in. Run the
                login flow in a shell thread — it walks you through the
                browser handshake — then reopen this dialog.
              </p>
              <button type="button" className="sy-confirm-btn" onClick={authInRail}>
                Put “!gh auth login” in the rail
              </button>
            </>
          )}
          {st && st.gh && st.authed && (
            <>
              <p>
                Publishes this workspace to GitHub tagged{" "}
                <code>curiosity-workspace</code>: wiki, figures, sketches,
                curator profile{vault ? ", and vault originals" : ""}.
                Rail history and <code>.workbench/</code> config never
                leave this machine.
                {st.has_remote && st.repo_url && (
                  <> Already published at <a href={st.repo_url} target="_blank" rel="noreferrer">{st.repo_url}</a> — this pushes an update.</>
                )}
              </p>
              <div className="sy-ws-input-row">
                <input
                  type="text"
                  className="sy-ws-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  disabled={publishing || st.has_remote}
                  spellCheck={false}
                  title={st.has_remote ? "Repo name is fixed after first publish" : "GitHub repository name"}
                />
              </div>
              <label style={{ display: "block", fontSize: 12, marginTop: 8 }}>
                <input
                  type="checkbox"
                  checked={priv}
                  onChange={(e) => setPriv(e.target.checked)}
                  disabled={publishing || st.has_remote}
                /> private repository
              </label>
              <label style={{ display: "block", fontSize: 12, marginTop: 4 }}>
                <input
                  type="checkbox"
                  checked={vault}
                  onChange={(e) => setVault(e.target.checked)}
                  disabled={publishing}
                /> include vault/ originals (uncheck for privacy/size — recipients lose provenance targets)
              </label>
              {preview && (
                <div className="sy-share-preview" style={{ marginTop: 10, fontSize: 12 }}>
                  <p style={{ margin: "0 0 4px" }}>
                    <strong>{preview.file_count}</strong> file
                    {preview.file_count === 1 ? "" : "s"} would be published
                    {priv ? "" : " publicly"}
                    {preview.truncated ? " (scan capped)" : ""}
                    {preview.top_dirs.length > 0 && (
                      <>
                        {" — "}
                        {preview.top_dirs
                          .map((d) => `${d.dir} (${d.files})`)
                          .join(", ")}
                      </>
                    )}
                    .
                  </p>
                  {preview.largest.length > 0 && (
                    <p style={{ margin: "0 0 4px", opacity: 0.75 }}>
                      Largest: {preview.largest
                        .slice(0, 4)
                        .map((f) => `${f.path} (${fmtBytes(f.bytes)})`)
                        .join(", ")}
                    </p>
                  )}
                  {hasSecrets && (
                    <div
                      className="sy-share-secret-warn"
                      style={{
                        marginTop: 6, padding: "6px 8px",
                        border: "1px solid var(--sy-danger, #c0392b)",
                        borderRadius: 6,
                      }}
                    >
                      <p style={{ margin: "0 0 4px", fontWeight: 600 }}>
                        ⚠ {preview.secret_hits.length} possible secret
                        {preview.secret_hits.length === 1 ? "" : "s"} found —
                        review before publishing{priv ? "" : " publicly"}:
                      </p>
                      <ul style={{ margin: "0 0 4px", paddingLeft: 18 }}>
                        {preview.secret_hits.slice(0, 6).map((h, i) => (
                          <li key={i}>
                            <code>{h.path}:{h.line}</code> — {h.kind}
                          </li>
                        ))}
                        {preview.secret_hits.length > 6 && (
                          <li>…and {preview.secret_hits.length - 6} more</li>
                        )}
                      </ul>
                      <label style={{ display: "block" }}>
                        <input
                          type="checkbox"
                          checked={ackSecrets}
                          onChange={(e) => setAckSecrets(e.target.checked)}
                          disabled={publishing}
                        /> I've reviewed these — publish anyway
                      </label>
                    </div>
                  )}
                </div>
              )}
              {publishing && <p style={{ marginTop: 10 }}>publishing in the background — safe to close; a rail notice lands when it's done.</p>}
              {doneUrl && (
                <p style={{ marginTop: 10 }}>
                  ✓ published: <a href={doneUrl} target="_blank" rel="noreferrer">{doneUrl}</a>
                </p>
              )}
              {error && <pre className="sy-ws-error">{error}</pre>}
            </>
          )}
        </div>
        <div className="sy-confirm-actions">
          <button type="button" className="sy-confirm-btn" onClick={onClose}>
            Close
          </button>
          {st?.gh && st.authed && (
            <button
              type="button"
              className="sy-confirm-btn sy-confirm-btn--primary"
              onClick={() => void publish()}
              disabled={publishing || !name.trim() || publishBlocked}
              title={publishBlocked ? "Review the flagged secrets and confirm first" : undefined}
            >
              {publishing ? "Publishing…" : st.has_remote ? "Push update" : "Publish"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function WorkspaceSwitcher({
  workspaces, modeName, variant = "power", fallbackLabel,
}: Props) {
  const [open, setOpen] = useState(false);
  const [add, setAdd] = useState<AddState>({ kind: "closed" });
  const [shareOpen, setShareOpen] = useState(false);
  const [mergeOpen, setMergeOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  // ⌘K → W (central keybinding registry, via App) opens the switcher.
  useEffect(() => {
    const onOpen = () => setOpen(true);
    window.addEventListener("sy:open-workspace-switcher", onOpen);
    return () => window.removeEventListener("sy:open-workspace-switcher", onOpen);
  }, []);

  // Click-outside / ESC dismiss for the dropdown.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("mousedown", onClick);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onClick);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const switchTo = async (path: string) => {
    setOpen(false);
    if (path === workspaces.active) return;
    try {
      const r = await fetch("/api/workspaces/switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        toast(`workspace switch failed: ${body.error ?? r.status}`, { err: true });
        return;
      }
    } catch (e) {
      // Network throw (daemon down / restarting) — surface instead of a
      // silent no-op that looks like a frozen switcher.
      toast(`workspace switch failed: ${(e as Error).message}`, { err: true });
      return;
    }
    // No reload — daemon broadcasts a fresh `hello` to every
    // connected WS client; App.tsx + GraphTab + Sidebar all
    // re-init from the new workspace's data when graphData
    // updates. Reloading just made everything blank for 3–5
    // seconds during the bundle re-parse.
  };

  // On hover, warm the daemon's per-workspace cache AND the
  // frontend's per-workspace GraphData cache for the row under the
  // cursor. The backend's /api/graph/data?workspace=<path> reads
  // (or cold-builds) that workspace's data.json without changing
  // app["workspace"]; we then dispatch sy:graph-prefetched so
  // App.tsx can seed its in-memory Map. By the time the user
  // clicks, both halves are hot and the graph paints instantly.
  const prefetched = useRef<Set<string>>(new Set());
  const prefetchWorkspace = (path: string) => {
    if (path === workspaces.active) return;
    if (prefetched.current.has(path)) return;
    prefetched.current.add(path);
    void fetch(
      `/api/graph/data?workspace=${encodeURIComponent(path)}`,
      { cache: "force-cache" },
    )
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (!data) return;
        window.dispatchEvent(new CustomEvent("sy:graph-prefetched", {
          detail: { workspace: path, data },
        }));
      })
      .catch(() => { /* prefetch is best-effort */ });
  };

  const browse = async () => {
    if (add.kind !== "open") return;
    const r = await fetch("/api/workspaces/pick", { method: "POST" });
    const body = (await r.json().catch(() => ({}))) as { path?: string | null };
    if (body.path) setAdd({ ...add, path: body.path, error: null });
  };

  const submitAdd = async () => {
    if (add.kind !== "open") return;
    setAdd({ ...add, submitting: true, error: null });
    const r = await fetch("/api/workspaces/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: add.path }),
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      const detail = body.detail ? `\n\n${String(body.detail).slice(-600)}` : "";
      setAdd({ ...add, submitting: false, error: `${body.error ?? r.status}${detail}` });
      return;
    }
    setAdd({ kind: "closed" });
    setOpen(false);
    // Daemon broadcasts a fresh hello after the add → switch on
    // its side; in-place re-init follows. Same as switchTo, no
    // reload needed.
  };

  const active = workspaces.active;
  // Only treat `active` as a real selection if it's in the
  // registered list. The daemon's `app["workspace"]` (CLI cwd) is
  // a separate runtime fact — the switcher is purely for paths the
  // user has explicitly added via `+ Add workspace…`.
  const activeIsRegistered = !!active && workspaces.paths.includes(active);
  // Display names, disambiguated when two registered workspaces share a
  // basename (path is the real identity; this is just what's shown).
  const nameFor = disambiguatedNames(workspaces.paths);
  const dispName = (p: string) => nameFor.get(p) ?? basename(p);
  const activeLabel = activeIsRegistered ? dispName(active!) : "—";

  // Issue 15 — per-row archive + delete affordances.
  const archiveWorkspace = async (path: string) => {
    if (!window.confirm(
      `Archive "${basename(path)}"?\n\n` +
      `Removes it from the workspace list, but PRESERVES the\n` +
      `.workbench/ settings under the workspace dir. You can\n` +
      `restore it later from the "Archived" section in this menu.`
    )) return;
    const r = await fetch("/api/workspaces/archive", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    if (!r.ok) {
      window.alert(`archive failed: ${r.status}`);
      return;
    }
    if (path === active) window.location.reload();
    else window.location.reload();  // simple: reload to refetch
  };

  const deleteWorkspace = async (path: string) => {
    if (!window.confirm(
      `DELETE "${basename(path)}"?\n\n` +
      `Removes it from the workspace list AND deletes the\n` +
      `.workbench/ settings under the workspace dir. Your\n` +
      `wiki / vault / figures / source files stay untouched.\n\n` +
      `This is irreversible. Use "Archive" instead if you\n` +
      `might come back to this workspace later.`
    )) return;
    const r = await fetch("/api/workspaces/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    if (!r.ok) {
      window.alert(`delete failed: ${r.status}`);
      return;
    }
    window.location.reload();
  };

  const restoreWorkspace = async (path: string) => {
    const r = await fetch("/api/workspaces/restore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    if (!r.ok) {
      window.alert(`restore failed: ${r.status}`);
      return;
    }
    window.location.reload();
  };

  const archived = workspaces.archived ?? [];

  // Zen brand shows the live workspace name even when it isn't a
  // registered path (unregistered CLI cwd → fall back, never "—").
  const zenLabel = activeIsRegistered ? activeLabel : (fallbackLabel || "—");

  return (
    <div
      className={"sy-ws-wrap" + (variant === "zen" ? " sy-ws-wrap--zen" : "")}
      ref={wrapRef}
    >
      {variant === "zen" ? (
        <button
          type="button"
          className={"sy-zen-chrome sy-zen-brand-btn" + (open ? " sy-zen-brand-btn--open" : "")}
          onClick={() => setOpen((o) => !o)}
          title={
            activeIsRegistered
              ? `workspace: ${active}\nclick to switch`
              : "click to add or switch workspaces"
          }
        >
          <span className="sy-zen-brand">Switch Bay</span>
          {zenLabel !== "—" && <span className="sy-zen-wsname">{zenLabel}</span>}
          <span className="chev">▾</span>
        </button>
      ) : (
        <button
          type="button"
          className="sy-mode-switcher sy-ws-trigger"
          onClick={() => setOpen((o) => !o)}
          title={activeIsRegistered ? `workspace: ${active}\nmode: ${modeName}` : "no workspace selected"}
        >
          <span>{activeLabel}</span>
          <span className="sy-mode-sep">·</span>
          <span>{modeName}</span>
          <span className="chev">▾</span>
        </button>
      )}
      {open && (
        <div className="sy-ws-menu" role="menu">
          {workspaces.paths.length === 0 && (
            <div className="sy-ws-empty">no workspaces registered</div>
          )}
          {workspaces.paths.map((p) => (
            <div
              key={p}
              className={"sy-ws-row" + (p === active ? " sy-ws-row--active" : "")}
              onMouseEnter={() => prefetchWorkspace(p)}
            >
              <button
                type="button"
                className="sy-ws-item"
                onClick={() => switchTo(p)}
                title={p}
              >
                <span className="sy-ws-name">{dispName(p)}</span>
                <span className="sy-ws-path">{p}</span>
              </button>
              <button
                type="button"
                className="sy-ws-row-action"
                onClick={(e) => { e.stopPropagation(); void archiveWorkspace(p); }}
                title="Archive (keep settings, hide from list)"
                aria-label="Archive workspace"
              >
                {/* archive box icon */}
                <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="2" y="3" width="12" height="3" rx="0.5" />
                  <path d="M3 6 V13 a1 1 0 0 0 1 1 H12 a1 1 0 0 0 1-1 V6" />
                  <line x1="6.5" y1="9" x2="9.5" y2="9" />
                </svg>
              </button>
              <button
                type="button"
                className="sy-ws-row-action sy-ws-row-action--danger"
                onClick={(e) => { e.stopPropagation(); void deleteWorkspace(p); }}
                title="Delete (remove settings, irreversible)"
                aria-label="Delete workspace"
              >
                {/* trash can icon */}
                <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="2.5" y1="4" x2="13.5" y2="4" />
                  <path d="M4 4 L4.7 13 a1 1 0 0 0 1 1 H10.3 a1 1 0 0 0 1-1 L12 4" />
                  <path d="M6 4 V2.5 a0.5 0.5 0 0 1 0.5-0.5 H9.5 a0.5 0.5 0 0 1 0.5 0.5 V4" />
                </svg>
              </button>
            </div>
          ))}
          <div className="sy-ws-divider" />
          <button
            type="button"
            className="sy-ws-item sy-ws-add"
            onClick={() => setAdd({ kind: "open", path: "", submitting: false, error: null })}
          >
            + Add workspace…
          </button>
          {activeIsRegistered && (
            <button
              type="button"
              className="sy-ws-item sy-ws-add"
              onClick={() => { setOpen(false); setShareOpen(true); }}
              title="Publish the active workspace to GitHub (gh CLI; tagged curiosity-workspace)"
            >
              ↗ Share workspace…
            </button>
          )}
          {workspaces.paths.length >= 2 && (
            <button
              type="button"
              className="sy-ws-item sy-ws-add"
              onClick={() => { setOpen(false); setMergeOpen(true); }}
              title="Combine two or more workspaces into a NEW one (originals stay on disk, leave this list)"
            >
              ⇄ Merge workspaces…
            </button>
          )}
          {/* Archived section — always-shown header so the
              affordance is discoverable. Empty-state copy
              explains how to populate it. */}
          <div className="sy-ws-divider" />
          <div className="sy-ws-section-label">
            Archived
            {archived.length > 0 && (
              <span className="sy-ws-section-count">{archived.length}</span>
            )}
          </div>
          {archived.length === 0 ? (
            <div className="sy-ws-archived-empty">
              No archived workspaces. Hover any row above and click
              the box icon to archive it.
            </div>
          ) : (
            archived.map((a) => (
              <div key={a.path} className="sy-ws-row sy-ws-row--archived">
                <button
                  type="button"
                  className="sy-ws-item"
                  onClick={() => void restoreWorkspace(a.path)}
                  title={`Restore ${a.path}`}
                >
                  <span className="sy-ws-name">↺ {basename(a.path)}</span>
                  <span className="sy-ws-path">{a.path}</span>
                </button>
                <button
                  type="button"
                  className="sy-ws-row-action sy-ws-row-action--danger"
                  onClick={(e) => { e.stopPropagation(); void deleteWorkspace(a.path); }}
                  title="Delete archived workspace permanently"
                  aria-label="Delete archived workspace"
                >
                  <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="2.5" y1="4" x2="13.5" y2="4" />
                    <path d="M4 4 L4.7 13 a1 1 0 0 0 1 1 H10.3 a1 1 0 0 0 1-1 L12 4" />
                    <path d="M6 4 V2.5 a0.5 0.5 0 0 1 0.5-0.5 H9.5 a0.5 0.5 0 0 1 0.5 0.5 V4" />
                  </svg>
                </button>
              </div>
            ))
          )}
        </div>
      )}
      {shareOpen && <ShareDialog onClose={() => setShareOpen(false)} />}
      {mergeOpen && (
        <MergeDialog
          paths={workspaces.paths}
          onClose={() => setMergeOpen(false)}
        />
      )}
      {add.kind === "open" && (
        <div
          className="sy-confirm-backdrop"
          onClick={() => !add.submitting && setAdd({ kind: "closed" })}
        >
          <div
            className="sy-confirm sy-ws-dialog"
            role="dialog"
            aria-labelledby="sy-ws-dialog-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div id="sy-ws-dialog-title" className="sy-confirm-title">Add workspace</div>
            <div className="sy-confirm-body">
              <p>
                Absolute path to a directory — or a <b>GitHub URL</b> /{" "}
                <code>owner/repo</code> to install a shared{" "}
                <code>curiosity-workspace</code> (clones into your workspaces
                home). Local folders without <code>wiki/</code> get
                curiosity-engine's <code>setup.sh</code> run first (this can
                take a moment).
              </p>
              <div className="sy-ws-input-row">
                <input
                  type="text"
                  className="sy-ws-input"
                  placeholder="/Users/you/Documents/my-knowledge-base"
                  autoFocus
                  value={add.path}
                  onChange={(e) => setAdd({ ...add, path: e.target.value, error: null })}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && add.path.trim() && !add.submitting) {
                      e.preventDefault();
                      submitAdd();
                    }
                  }}
                  disabled={add.submitting}
                  spellCheck={false}
                />
                <button
                  type="button"
                  className="sy-ws-browse"
                  onClick={browse}
                  disabled={add.submitting}
                  title="Open the OS folder picker"
                >
                  Browse…
                </button>
              </div>
              {add.error && <pre className="sy-ws-error">{add.error}</pre>}
            </div>
            <div className="sy-confirm-actions">
              <button
                type="button"
                className="sy-confirm-btn"
                onClick={() => setAdd({ kind: "closed" })}
                disabled={add.submitting}
              >
                Cancel
              </button>
              <button
                type="button"
                className="sy-confirm-btn sy-confirm-btn--primary"
                onClick={submitAdd}
                disabled={add.submitting || !add.path.trim()}
              >
                {add.submitting ? "Setting up…" : "Add"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
