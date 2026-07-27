/**
 * Fire a transient toast from anywhere in the tree without threading a
 * callback down. App listens for `sy:toast` and renders it through its
 * existing toast stack. Use for user-initiated actions that would
 * otherwise fail silently (a POST that 500s, a clipboard write that
 * throws) — a swallowed error is indistinguishable from a frozen UI.
 *
 * Don't use it for best-effort background polls (active-runs, graph
 * prefetch); those stay quiet by design.
 */
export function toast(text: string, opts: { err?: boolean } = {}): void {
  window.dispatchEvent(
    new CustomEvent("sy:toast", { detail: { text, err: opts.err ?? false } }),
  );
}
