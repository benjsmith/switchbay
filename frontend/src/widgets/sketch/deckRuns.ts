/**
 * Tracks active autopopulate runs per analysis/deck path so the
 * Sketch tab can show a spinner next to the deck title while an
 * agent is filling in the placeholder slides.
 *
 * The store is intentionally module-level (not React state) so the
 * Editor's `→ Slides` button can register a run and the Sketch tab
 * can read it immediately on deck-mode entry, without prop drilling
 * or App-level lifting. A subscriber list lets components re-render
 * on changes.
 *
 * The run_id maps to a row in the daemon's `app["runs"]` registry;
 * the Sketch tab polls `/api/runs/active` to see whether the run is
 * still alive and clears the local entry when it isn't.
 */

const runs = new Map<string, string>();  // analysis path → run_id
const listeners = new Set<() => void>();


export function setDeckRun(analysisPath: string, runId: string): void {
  runs.set(analysisPath, runId);
  listeners.forEach((fn) => fn());
}


export function clearDeckRun(analysisPath: string): void {
  runs.delete(analysisPath);
  listeners.forEach((fn) => fn());
}


export function getDeckRun(analysisPath: string): string | undefined {
  return runs.get(analysisPath);
}


export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}


/* ── Primed analysis records ─────────────────────────────────────
 * Lets the modal's "↗ Slides" / "↗ Sketch" path hand a freshly-
 * loaded analysis record straight to the Sketch tab so the deck
 * badge appears instantly on switch-in, without the SketchTab
 * needing to round-trip /api/analysis. Keyed by path. Cleared once
 * consumed (one-shot priming, not a long-lived cache). */
type PrimedAnalysis = Record<string, unknown> & { path: string };
const primed = new Map<string, PrimedAnalysis>();

export function primeAnalysis(rec: PrimedAnalysis): void {
  if (!rec || !rec.path) return;
  primed.set(String(rec.path), rec);
}

/* Returns a primed analysis record if one exists for the path. Does
 * NOT delete on read — StrictMode mounts the consuming effect twice
 * in dev, and a single-use cache would be empty on the second pass
 * and lose the badge. Entries get overwritten naturally when a new
 * prime arrives for the same path; stale primes are harmless because
 * the SketchTab's selection.path key matches at most one. */
export function takePrimedAnalysis(path: string): PrimedAnalysis | undefined {
  return primed.get(path);
}
