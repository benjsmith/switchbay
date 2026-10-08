/**
 * CE sidebar header: Switch Bay's sidebar shell (ceSidebarShell.html)
 * carries a literal `{{WORKSPACE}}` in `.workspace-name` — the same
 * placeholder CE's own index.html uses. Substitute it from data.json's
 * `workspace` (last path segment) before the markup reaches the DOM so
 * the header never shows the raw placeholder.
 */

export const WORKSPACE_PLACEHOLDER = /\{\{WORKSPACE\}\}/g;

export function workspaceLabel(data: unknown): string {
  if (data && typeof data === "object" && "workspace" in data) {
    const w = (data as { workspace?: unknown }).workspace;
    if (typeof w === "string" && w.trim()) {
      const parts = w.split(/[\\/]/).filter(Boolean);
      return parts[parts.length - 1] || w;
    }
  }
  return "workspace";
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Sidebar shell markup with the workspace name filled in. */
export function renderSidebarShell(html: string, data: unknown): string {
  const label = escapeHtml(workspaceLabel(data));
  return html.replace(WORKSPACE_PLACEHOLDER, () => label);
}
