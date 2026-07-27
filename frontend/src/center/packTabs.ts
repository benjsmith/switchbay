import { registerTabKind, type TabComponent } from "./tabRegistry";

/**
 * Pack-supplied tab kinds — dynamic loader.
 *
 * Each installed pack with a `tabs: [{kind, title, module: "./tabs/foo.js"}]`
 * entry in its manifest gets its modules dynamically imported via the
 * daemon's static-file server (`/api/packs/<name>/files/<path>`).
 * Each module's default export must be a React component matching the
 * `TabComponent` shape; we register it with the tab registry so
 * TabStrip routes that kind to it.
 *
 * Vite tolerates dynamic imports against runtime URLs as long as we
 * `@vite-ignore` the static-analysis pass. Production bundles the
 * pack JS doesn't go through Vite's bundler — packs ship pre-built
 * ESM modules and the daemon serves them as plain static files.
 *
 * Failures (HTTP errors, modules without a default export, kinds
 * already registered) are logged and skipped so a single bad pack
 * doesn't break the whole tab strip.
 */

type PackInfo = {
  name: string;
  scope: string;
  tabs?: { kind?: string; title?: string; module?: string }[];
};


let started = false;


export async function loadPackTabs(): Promise<void> {
  if (started) return;
  started = true;
  let packs: PackInfo[] = [];
  try {
    const r = await fetch("/api/packs");
    if (!r.ok) return;
    const body = (await r.json()) as { packs: PackInfo[] };
    packs = body.packs ?? [];
  } catch {
    return;  // offline; nothing to load
  }
  for (const pack of packs) {
    for (const tab of pack.tabs ?? []) {
      const kind = String(tab?.kind ?? "").trim();
      const modulePath = String(tab?.module ?? "").trim();
      if (!kind || !modulePath) continue;
      // Resolve the module URL via the daemon's static path. Strip
      // any leading "./" or "/" so the join stays predictable.
      const safe = modulePath.replace(/^\.?\//, "");
      const url = `/api/packs/${encodeURIComponent(pack.name)}/files/${safe}`;
      try {
        const mod = await import(/* @vite-ignore */ url);
        const Comp = mod?.default;
        if (typeof Comp !== "function") {
          console.warn(`[packTabs] ${pack.name}/${kind}: module has no default export`);
          continue;
        }
        registerTabKind(kind, Comp as TabComponent);
        console.info(`[packTabs] registered ${kind} from ${pack.name}`);
      } catch (e) {
        console.warn(`[packTabs] ${pack.name}/${kind}: ${(e as Error).message}`);
      }
    }
  }
}
