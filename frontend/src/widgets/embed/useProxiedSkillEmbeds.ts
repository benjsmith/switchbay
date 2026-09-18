import { useEffect, useState } from "react";

/**
 * Phase 4a feature flag: when true, Graph/Agents use `/embed/*` panels.
 * Default false (built-in tabs). Reads `/api/settings` once; listens for
 * `sy:proxied-skill-embeds` so Settings can flip without reload.
 */
export function useProxiedSkillEmbeds(): boolean {
  const [on, setOn] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void fetch("/api/settings")
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (!cancelled && j && typeof j.proxied_skill_embeds === "boolean") {
          setOn(j.proxied_skill_embeds);
        }
      })
      .catch(() => {
        /* older daemon — leave off */
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
