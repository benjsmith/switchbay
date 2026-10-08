import { useEffect, useState } from "react";

/**
 * Two shell switches read from `/api/settings`:
 *
 * - `proxied_skill_embeds`: when true, the Agents tab shows okstratr's own
 *   observer through `/embed/okstratr`; when false, Switch Bay's built-in
 *   Agents dashboard. (Graph no longer depends on it — Graph is always
 *   CE's viewer through `/embed/ce`.)
 * - `ce_graph`: whether a Curiosity Engine install with its viewer exists
 *   (`installed`) and whether this workspace has a `wiki/` (`has_wiki`).
 *   The shell hides Graph when CE isn't installed.
 *
 * Both hooks return `null` until settings resolve so adapters don't flash
 * the wrong surface. Module-level caches keep tab switches instant; each
 * mount still refetches so a workspace switch picks up the new wiki state.
 */

export type CeGraphAvailability = { installed: boolean; hasWiki: boolean };

let cachedProxied: boolean | null = null;
let cachedCeGraph: CeGraphAvailability | null = null;
const listeners = new Set<() => void>();

function notify(): void {
  for (const fn of listeners) fn();
}

function applySettings(j: unknown): void {
  const body = (j && typeof j === "object" ? j : {}) as {
    proxied_skill_embeds?: unknown;
    ce_graph?: { installed?: unknown; has_wiki?: unknown };
  };
  cachedProxied = typeof body.proxied_skill_embeds === "boolean"
    ? body.proxied_skill_embeds
    : false;
  const cg = body.ce_graph;
  cachedCeGraph = cg && typeof cg === "object"
    ? { installed: cg.installed === true, hasWiki: cg.has_wiki === true }
    : { installed: false, hasWiki: false };
  notify();
}

let inflight: Promise<void> | null = null;

/** Refetch `/api/settings` (deduped while one is in flight). */
export function refreshEmbedSettings(): Promise<void> {
  if (inflight) return inflight;
  inflight = fetch("/api/settings")
    .then((r) => (r.ok ? r.json() : null))
    .then((j) => {
      if (j) applySettings(j);
      else if (cachedProxied === null) applySettings({});
    })
    .catch(() => {
      // Keep the last known values on a transient error; first visit
      // falls back to "off / not installed".
      if (cachedProxied === null) applySettings({});
    })
    .finally(() => { inflight = null; });
  return inflight;
}

function useSettingsValue<T>(read: () => T): T {
  const [value, setValue] = useState<T>(read);
  useEffect(() => {
    const sync = () => setValue(read());
    listeners.add(sync);
    void refreshEmbedSettings();
    const onProxied = (ev: Event) => {
      const detail = (ev as CustomEvent<{ enabled?: boolean }>).detail;
      if (detail && typeof detail.enabled === "boolean") {
        cachedProxied = detail.enabled;
        notify();
      }
    };
    window.addEventListener("sy:proxied-skill-embeds", onProxied);
    return () => {
      listeners.delete(sync);
      window.removeEventListener("sy:proxied-skill-embeds", onProxied);
    };
    // `read` is a stable module accessor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return value;
}

/** Agents tab: okstratr embed (true) vs built-in dashboard (false). */
export function useProxiedSkillEmbeds(): boolean | null {
  return useSettingsValue(() => cachedProxied);
}

/** Graph tab availability (CE installed / workspace has a wiki). */
export function useCeGraph(): CeGraphAvailability | null {
  return useSettingsValue(() => cachedCeGraph);
}
