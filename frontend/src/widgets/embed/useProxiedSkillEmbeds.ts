import { useEffect, useState } from "react";

/**
 * Phase 4a feature flag: when true, Graph/Agents use `/embed/*` panels.
 * Returns `null` until `/api/settings` resolves so adapters do not flash the
 * built-in (lazy) tabs — that flash caused "Importing a module script failed"
 * when Agents opened while proxied was actually on.
 *
 * Module-level cache: tab switches remount adapters; without a cache each
 * remount starts at `null` and shows "Loading…" until settings returns
 * (and a stale CE fetch shim could strand that request).
 */
let cachedProxied: boolean | null = null;

export function useProxiedSkillEmbeds(): boolean | null {
  const [on, setOn] = useState<boolean | null>(() => cachedProxied);

  useEffect(() => {
    let cancelled = false;
    void fetch("/api/settings")
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (cancelled) return;
        if (j && typeof j.proxied_skill_embeds === "boolean") {
          cachedProxied = j.proxied_skill_embeds;
          setOn(j.proxied_skill_embeds);
        } else {
          cachedProxied = false;
          setOn(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          // Prefer last known cache over forcing false on transient errors
          // (e.g. brief network blip). First visit still falls back to off.
          if (cachedProxied === null) {
            cachedProxied = false;
            setOn(false);
          }
        }
      });

    const onEvt = (ev: Event) => {
      const detail = (ev as CustomEvent<{ enabled?: boolean }>).detail;
      if (detail && typeof detail.enabled === "boolean") {
        cachedProxied = detail.enabled;
        setOn(detail.enabled);
      }
    };
    window.addEventListener("sy:proxied-skill-embeds", onEvt);
    return () => {
      cancelled = true;
      window.removeEventListener("sy:proxied-skill-embeds", onEvt);
    };
  }, []);

  return on;
}
