import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Cost/performance preference for Auto orchestration.
 * Economy ← Balanced → Maximum.
 *
 * This control sets how much independent fan-out Auto may buy and how
 * readily it recruits the strongest/most expensive allowed models.
 * Agent count is still an *output* of the policy, not a direct N.
 * Explicit N still exists as `/route` / `n≥2` on the wire.
 */

const STORAGE_KEY = "sy.orchestration.preference";

export type OrchOpts = { n: number; preference: number };

function readPref(): number {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw == null) return 0.5;
    const n = Number(raw);
    if (!Number.isFinite(n)) return 0.5;
    return Math.max(0, Math.min(1, n));
  } catch {
    return 0.5;
  }
}

function labelFor(pref: number): string {
  if (pref <= 0.2) return "Economy";
  if (pref >= 0.8) return "Maximum";
  return "Balanced";
}

export function useOrchestrationControl(): { node: ReactNode; opts: OrchOpts } {
  const [pref, setPref] = useState(readPref);
  const persistTimer = useRef(0);

  useEffect(() => {
    void fetch("/api/settings")
      .then((r) => (r.ok ? r.json() : null))
      .then((b: { orchestration_preference?: number } | null) => {
        if (typeof b?.orchestration_preference !== "number") return;
        if (window.localStorage.getItem(STORAGE_KEY) != null) return;
        setPref(Math.max(0, Math.min(1, b.orchestration_preference)));
      })
      .catch(() => { /* older daemon */ });
  }, []);

  const commitPref = useCallback((v: number) => {
    const clamped = Math.max(0, Math.min(1, v));
    setPref(clamped);
    try { window.localStorage.setItem(STORAGE_KEY, String(clamped)); } catch { /* */ }
    window.clearTimeout(persistTimer.current);
    persistTimer.current = window.setTimeout(() => {
      void fetch("/api/settings", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ orchestration_preference: clamped }),
      }).catch(() => { /* */ });
    }, 400);
  }, []);

  const node = (
    <div
      className="sy-orch"
      title="How much fan-out Auto may buy, and how easily it recruits the strongest allowed models."
    >
      <span className="sy-orch-end">Economy</span>
      <input
        type="range"
        className="sy-orch-range"
        min={0}
        max={100}
        step={5}
        value={Math.round(pref * 100)}
        aria-label="Cost versus performance"
        onChange={(e) => commitPref(Number(e.target.value) / 100)}
      />
      <span className="sy-orch-end">Maximum</span>
      {labelFor(pref) === "Balanced" && (
        <span className="sy-orch-label">Balanced</span>
      )}
    </div>
  );

  return { node, opts: { n: 0, preference: pref } };
}
