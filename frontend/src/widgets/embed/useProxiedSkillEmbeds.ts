import { useEffect, useState } from "react";

/**
 * Phase 4a feature flag: when true, Graph/Agents use `/embed/*` panels.
 * Returns `null` until `/api/settings` resolves so adapters do not flash the
 * built-in (lazy) tabs — that flash caused "Importing a module script failed"
 * when Agents opened while proxied was actually on.
 */
export function useProxiedSkillEmbeds(): boolean | null {
  const [on, setOn] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetch("/api/settings")
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (cancelled) return;
        if (j && typeof j.proxied_skill_embeds === "boolean") {
          setOn(j.proxied_skill_embeds);
        } else {
          setOn(false);
        }
      })
      .catch(() => {
        if (!cancelled) setOn(false);
      });

    const onEvt = (ev: Event) => {
      const detail = (ev as CustomEvent<{ enabled?: boolean }>).detail;
      if (detail && typeof detail.enabled === "boolean") {
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
