/**
 * Tiny singleton tracking which project the current editor page was
 * opened from. The Editor tab uses this to render a "← Project"
 * back-link beside the existing ↗ Graph and → Slides buttons; the
 * Projects tab uses it to scroll the matching row into view.
 *
 * A page can belong to multiple projects, so the breadcrumb is keyed
 * on (path, project) and scoped to the *click* that opened the doc —
 * i.e., we always remember which card the user clicked from, not
 * just the first project that contains the page.
 *
 * Lives outside the React tree so the Editor and Projects tabs can
 * share it without lifting state into App.tsx. A subscriber list
 * lets components re-render when the breadcrumb changes.
 */

export type ProjectBreadcrumb = {
  /** Workspace-relative wiki path the user clicked, e.g.
   * `wiki/sources/wang-2024-codeact.md`. Matched verbatim against
   * the editor's current selection.path. */
  path: string;
  /** Project name as it appears in the registry, or the
   * synthetic `_general` bucket. */
  project: string;
};


let current: ProjectBreadcrumb | null = null;
const listeners = new Set<(b: ProjectBreadcrumb | null) => void>();


export function getBreadcrumb(): ProjectBreadcrumb | null {
  return current;
}


export function setBreadcrumb(b: ProjectBreadcrumb | null): void {
  current = b;
  listeners.forEach((fn) => fn(b));
}


export function subscribe(
  fn: (b: ProjectBreadcrumb | null) => void,
): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}
