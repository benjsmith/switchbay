import { useCallback, useEffect, useMemo, useState } from "react";
import type { TabSpec } from "../../ws";
import { useSelection } from "../../selection/SelectionContext";
import { useTabs } from "../../center/TabsContext";

/**
 * Generic pack-supplied tab that lists workspace files matching a
 * set of extensions and runs a pack-declared file route when the
 * user clicks one. The LibreOffice pack contributes three of
 * these — Slides / Docs / Sheets — by pinning `kind:
 * "pack.file-list"` with a `payload` shape:
 *
 *   { extensions: [".csv", ".parquet"],
 *     action: "mypack.summarise",
 *     subtitle: "Data files…",
 *     empty: "No matching files in this workspace." }
 *
 * The action id lines up with the pack's `file_routes[].action`
 * field; we look up the matching route at click time so the
 * component stays uncoupled from any specific endpoint.
 */

type Payload = {
  extensions?: string[];
  action?: string;
  subtitle?: string;
  empty?: string;
};

type FileRoute = {
  ext: string;
  action: string;
  label?: string;
  description?: string;
  endpoint?: string;
  tab_kind?: string;
  selection_kind?: string;
  pack?: string;
};

export default function PackFileListTab(props: { tab: TabSpec }) {
  const { tab } = props;
  const payload = (tab.payload ?? {}) as Payload;
  const exts = useMemo(
    () => new Set((payload.extensions ?? []).map((e) => e.toLowerCase())),
    [payload.extensions],
  );
  const action = payload.action ?? "";

  const [files, setFiles] = useState<string[] | null>(null);
  const [routes, setRoutes] = useState<FileRoute[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const { setSelection } = useSelection();
  const { switchToKind } = useTabs();

  useEffect(() => {
    let cancelled = false;
    fetch("/api/tree")
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => {
        if (cancelled || !b) return;
        const all = (b.files as string[]) ?? [];
        const filtered = all.filter((p) => {
          const dot = p.lastIndexOf(".");
          if (dot < 0) return false;
          return exts.has(p.slice(dot).toLowerCase());
        });
        filtered.sort((a, b) => a.localeCompare(b));
        setFiles(filtered);
      })
      .catch(() => { /* leave files null — empty state renders */ });
    return () => { cancelled = true; };
  }, [exts]);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/file-routes")
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => {
        if (cancelled || !b) return;
        setRoutes((b.routes as FileRoute[]) ?? []);
      })
      .catch(() => { /* no pack routes — clicks become no-ops */ });
    return () => { cancelled = true; };
  }, []);

  const routeForExt = useCallback((path: string): FileRoute | null => {
    const dot = path.lastIndexOf(".");
    if (dot < 0) return null;
    const ext = path.slice(dot).toLowerCase();
    // Prefer a route whose action matches the tab's declared
    // action AND whose ext matches the file — that's the canonical
    // match. Fall back to any route for this ext as the secondary
    // choice (e.g. another pack overrode the action).
    const primary = routes.find((r) => r.action === action && r.ext === ext);
    if (primary) return primary;
    return routes.find((r) => r.ext === ext) ?? null;
  }, [routes, action]);

  const onOpen = useCallback(async (path: string) => {
    const route = routeForExt(path);
    if (!route) {
      setStatus(`no handler for ${path}`);
      return;
    }
    setStatus(`${route.label ?? route.action}…`);
    try {
      let body: Record<string, unknown> | null = null;
      if (route.endpoint) {
        // Same GET-then-POST shape as FileBrowser.runFileRoute.
        const r = await fetch(
          `${route.endpoint}?path=${encodeURIComponent(path)}`,
        );
        if (r.ok) {
          body = await r.json();
        } else if (r.status === 404 || r.status === 405) {
          const r2 = await fetch(route.endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path }),
          });
          if (!r2.ok) {
            const eb = await r2.json().catch(() => ({} as Record<string, unknown>));
            setStatus(`failed: ${eb.error ?? eb.detail ?? r2.status}`);
            return;
          }
          body = await r2.json();
        } else {
          const eb = await r.json().catch(() => ({} as Record<string, unknown>));
          setStatus(`failed: ${eb.error ?? eb.detail ?? r.status}`);
          return;
        }
      }
      // Async pack action (background agent) — route to the Agent
      // Dashboard to watch it instead of opening an empty tab.
      if (body?.run_id) {
        setStatus(`${route.label ?? route.action} started — see Agents`);
        window.dispatchEvent(new CustomEvent("sy:open-agents-run", {
          detail: { run_id: String(body.run_id) },
        }));
        return;
      }
      // Same selection plumbing as the FileBrowser path.
      if (route.selection_kind === "csv") {
        // CSV route has no endpoint — the Sheet tab loads from
        // selection.path directly. Same pattern as core CSV
        // clicks in the file browser.
        setSelection({ kind: "csv", path });
      } else if (route.selection_kind === "page" && body?.page_path) {
        const pagePath = String(body.page_path);
        const id = pagePath.startsWith("wiki/")
          ? pagePath.slice("wiki/".length, -".md".length)
          : pagePath;
        setSelection({ kind: "page", id, path: pagePath });
      }
      if (route.tab_kind) switchToKind(route.tab_kind);
      setStatus(null);
    } catch (e) {
      setStatus(`failed: ${(e as Error).message}`);
    }
  }, [routeForExt, setSelection, switchToKind]);

  return (
    <div className="sy-pack-filelist">
      <header className="sy-pack-filelist-head">
        <h2>{tab.title}</h2>
        {payload.subtitle && (
          <p className="sy-pack-filelist-sub">{payload.subtitle}</p>
        )}
        {tab.pack && (
          <p className="sy-pack-filelist-attribution">
            From the <code>{tab.pack}</code> pack.
          </p>
        )}
        {status && <p className="sy-pack-filelist-status">{status}</p>}
      </header>
      {files === null ? (
        <p className="sy-pack-filelist-empty">Loading…</p>
      ) : files.length === 0 ? (
        <p className="sy-pack-filelist-empty">
          {payload.empty ?? "No matching files in this workspace."}
        </p>
      ) : (
        <ul className="sy-pack-filelist-list">
          {files.map((path) => {
            const name = path.split("/").pop() ?? path;
            const dir = path.slice(0, path.length - name.length).replace(/\/$/, "");
            return (
              <li key={path}>
                <button
                  type="button"
                  className="sy-pack-filelist-row"
                  onClick={() => { void onOpen(path); }}
                  title={path}
                >
                  <span className="sy-pack-filelist-name">{name}</span>
                  {dir && <span className="sy-pack-filelist-dir">{dir}</span>}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
