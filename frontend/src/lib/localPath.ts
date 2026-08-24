/** Classify a rendered source/citation string as an HTTP URL or a
 *  workspace-relative file path. Refuse escapes and home/absolute paths. */

const HTTP_RE = /^https?:\/\//i;
const WORKSPACE_PREFIX = /^(wiki|vault|slideshows|reports|worksheets|\.workbench|data|figures)\//;

export type LocalPathKind = "url" | "local" | null;

export function classifySourceRef(raw: string): LocalPathKind {
  const t = (raw || "").trim();
  if (!t) return null;
  if (HTTP_RE.test(t)) return "url";
  const n = normalizeWorkspacePath(t);
  if (!n) return null;
  if (WORKSPACE_PREFIX.test(n) || n.includes("/") || /^vault:/i.test(t)) {
    return "local";
  }
  if (/\.(md|txt|pdf|png|jpe?g|webp|gif|svg|csv|json|html|py)$/i.test(n)) {
    return "local";
  }
  return null;
}

export function normalizeWorkspacePath(raw: string): string | null {
  let p = (raw || "").trim();
  if (!p) return null;
  if (HTTP_RE.test(p) || p.includes("://")) return null;
  p = p.replace(/^vault:/i, "");
  p = p.replace(/\\/g, "/");
  p = p.replace(/^\.\//, "");
  if (p.startsWith("/") || p.startsWith("~") || /^[A-Za-z]:\//.test(p)) {
    return null;
  }
  const parts = p.split("/").filter((seg) => seg && seg !== ".");
  if (parts.some((seg) => seg === "..")) return null;
  if (parts.length === 0) return null;
  return parts.join("/");
}

export function resolveInFileTree(
  raw: string,
  files: string[] | null | undefined,
): string | null {
  const n = normalizeWorkspacePath(raw);
  if (!n) return null;
  const list = files ?? [];
  if (list.includes(n)) return n;
  if (list.includes(`wiki/${n}`)) return `wiki/${n}`;
  if (list.includes(`vault/${n}`)) return `vault/${n}`;
  if (WORKSPACE_PREFIX.test(n) || n.includes("/")) return n;
  return n;
}

export function revealWorkspaceFile(path: string): void {
  const n = normalizeWorkspacePath(path);
  if (!n) return;
  lastReveal = n;
  window.dispatchEvent(new CustomEvent("sy:reveal-file", { detail: { path: n } }));
}

/** Open a local source with the OS default app, or a URL in a tab. */
export async function openWorkspaceFile(raw: string): Promise<void> {
  const kind = classifySourceRef(raw);
  if (kind === "url") {
    window.open(raw.trim(), "_blank", "noopener");
    return;
  }
  const n = normalizeWorkspacePath(raw);
  if (!n) {
    window.alert("Couldn't open: not a workspace path");
    return;
  }
  try {
    const r = await fetch("/api/fs/open-external", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: n }),
    });
    if (!r.ok) {
      const b = await r.json().catch(() => ({} as { error?: string }));
      window.alert(`Couldn't open: ${b.error ?? r.status}`);
    }
  } catch (e) {
    window.alert(`Couldn't open: ${(e as Error).message}`);
  }
}

let lastReveal: string | null = null;

export function getLastRevealPath(): string | null {
  return lastReveal;
}
