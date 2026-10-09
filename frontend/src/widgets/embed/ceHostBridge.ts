/**
 * Switch Bay-side shims around Curiosity Engine's embedded viewer.
 *
 * The Graph tab is CE's own viewer (window.CEEmbed via /embed/ce). CE's
 * modal renders `page.body_html` with innerHTML and knows nothing about
 * the rest of the shell, so the host adds back what the shell needs:
 *
 *  - guardCeModal: page HTML is agent/user-authored and CE emits raw
 *    HTML through. The viewer runs on the daemon's origin (which has
 *    filesystem + shell authority), so each page body goes through
 *    DOMPurify (same policy as the Editor) before CE's modal shows it.
 *  - enhanceCeModalBody: KaTeX math, and "↗ Sheet" / "↗ Plot" buttons
 *    above each table (bridged to React via `sy:open-as-sheet` etc.).
 *  - bindSlideshowButton: "Make HTML slideshow" in the page modal.
 *  - routeCeSplit: CE's split panel POSTs /api/split to CE's own server,
 *    which only partitions files. Switch Bay's split also registers the
 *    new workspace, rebuilds both graphs, heals cross-boundary links and
 *    toasts when it's ready — so the panel's request goes there instead.
 */

import { sanitizeHtml } from "../../lib/sanitizeHtml.ts";

type CePage = { id?: string; path?: string; type?: string; body_html?: unknown };
type CeData = { pages?: Record<string, CePage> | null };

type CeModalApi = {
  init?: (data: unknown, ...rest: unknown[]) => unknown;
  refresh?: (data: unknown, ...rest: unknown[]) => unknown;
  open?: (pageId: string, ...rest: unknown[]) => unknown;
  __syGuarded?: boolean;
};

/**
 * Sanitize page HTML right before CE's modal renders it. CE keeps the
 * `pages` object it was given by init/refresh and reads
 * `pages[id].body_html` on open, so wrapping those three calls covers
 * every path (fresh fetch, revalidate, atlas cache) at one choke point,
 * lazily — one page per open, not the whole wiki up front.
 */
export function guardCeModal(clean: (html: string) => string = sanitizeHtml): boolean {
  const w = window as unknown as { Modal?: CeModalApi };
  const modal = w.Modal;
  if (!modal || modal.__syGuarded) return !!modal;
  let pages: Record<string, CePage & { __sySafe?: boolean }> = {};
  const remember = (data: unknown) => {
    const p = (data as CeData | null)?.pages;
    pages = p && typeof p === "object" ? p : {};
  };
  const origInit = modal.init;
  const origRefresh = modal.refresh;
  const origOpen = modal.open;
  if (typeof origInit === "function") {
    modal.init = (data, ...rest) => {
      remember(data);
      return origInit.call(modal, data, ...rest);
    };
  }
  if (typeof origRefresh === "function") {
    modal.refresh = (data, ...rest) => {
      remember(data);
      return origRefresh.call(modal, data, ...rest);
    };
  }
  if (typeof origOpen === "function") {
    modal.open = (pageId, ...rest) => {
      const page = pages[pageId];
      if (page && !page.__sySafe && typeof page.body_html === "string") {
        page.body_html = clean(page.body_html);
        page.__sySafe = true;
      }
      return origOpen.call(modal, pageId, ...rest);
    };
  }
  modal.__syGuarded = true;
  return true;
}

/**
 * CE's page list helpers assume the list is mounted. In Zen (or before
 * the sidebar mounts) CE still calls `Sidebar.setActive` on every
 * `#page=` change and throws, which skips the node focus after it.
 * Make those two calls safe no-ops when the list isn't there.
 */
export function guardCeSidebar(): boolean {
  type SidebarApi = {
    setActive?: (...a: unknown[]) => unknown;
    setSearchHits?: (...a: unknown[]) => unknown;
    __syGuarded?: boolean;
  };
  const sb = (window as unknown as { Sidebar?: SidebarApi }).Sidebar;
  if (!sb || sb.__syGuarded) return !!sb;
  for (const key of ["setActive", "setSearchHits"] as const) {
    const orig = sb[key];
    if (typeof orig !== "function") continue;
    sb[key] = (...args: unknown[]) => {
      try {
        return orig.apply(sb, args);
      } catch {
        return undefined;
      }
    };
  }
  sb.__syGuarded = true;
  return true;
}

// ── Split: CE panel → Switch Bay workspace split ────────────────────

/** True for CE's split POST (raw, or already rewritten onto /embed/ce). */
export function isCeSplitUrl(url: string, publicBase = "/embed/ce"): boolean {
  let path = url;
  try {
    path = new URL(url, "http://sy.local").pathname;
  } catch {
    /* keep raw */
  }
  const base = publicBase.replace(/\/$/, "");
  return path === "/api/split" || path === `${base}/api/split`;
}

/** Map CE's split body onto Switch Bay's `/api/workspaces/split` body. */
export function toSwitchbaySplitBody(raw: unknown): { name: string; move: string[]; copy: string[] } {
  const b = (raw && typeof raw === "object" ? raw : {}) as {
    name?: unknown; target?: unknown; move?: unknown; copy?: unknown;
  };
  const list = (v: unknown) => (Array.isArray(v) ? v.map((x) => String(x)).filter(Boolean) : []);
  let name = typeof b.name === "string" ? b.name.trim() : "";
  if (!name && typeof b.target === "string") {
    name = b.target.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "";
  }
  return { name, move: list(b.move), copy: list(b.copy) };
}

/**
 * Route CE's split panel to Switch Bay's split. Install after the embed
 * fetch shim; the shim's release restores the original fetch (dropping
 * this wrapper with it).
 */
export function routeCeSplit(publicBase = "/embed/ce"): void {
  const w = window as unknown as { fetch: typeof fetch };
  if ((w.fetch as unknown as { __sySplit?: boolean }).__sySplit) return;
  const inner = w.fetch.bind(window);
  const wrapped = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string"
      ? input
      : input instanceof URL ? input.href : (input as Request).url;
    const method = (init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
    if (method !== "POST" || !isCeSplitUrl(url, publicBase)) return inner(input as RequestInfo, init);
    let raw: unknown = {};
    try {
      raw = JSON.parse(typeof init?.body === "string" ? init.body : "{}");
    } catch { /* empty body → validation error below */ }
    const body = toSwitchbaySplitBody(raw);
    const res = await inner("/api/workspaces/split", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const out = await res.json().catch(() => ({} as Record<string, unknown>));
    const payload = res.ok
      ? {
        ...out,
        // CE's panel reports "Done → target (n moved, m copied)"; Switch Bay
        // builds in the background and toasts when the workspace is ready.
        target: `${out.target ?? body.name} — building in the background`,
        moved: body.move.length,
        copied: body.copy.length,
      }
      : out;
    return new Response(JSON.stringify(payload), {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  };
  (wrapped as unknown as { __sySplit?: boolean }).__sySplit = true;
  w.fetch = wrapped as typeof fetch;
}

// ── Modal body enhancements ─────────────────────────────────────────

type MathRenderer = (el: HTMLElement, opts: unknown) => void;
let mathRenderer: MathRenderer | null = null;
let mathLoading: Promise<MathRenderer | null> | null = null;

function loadMath(): Promise<MathRenderer | null> {
  if (mathRenderer) return Promise.resolve(mathRenderer);
  if (!mathLoading) {
    mathLoading = Promise.all([
      // @ts-expect-error — KaTeX's auto-render ships without types.
      import("katex/contrib/auto-render"),
      import("katex/dist/katex.min.css"),
    ])
      .then(([mod]) => {
        mathRenderer = ((mod as { default?: MathRenderer }).default
          ?? (mod as unknown as MathRenderer));
        return mathRenderer;
      })
      .catch(() => null);
  }
  return mathLoading;
}

const MATH_HINT = /\$|\\\(|\\\[/;

export function renderMath(body: HTMLElement): void {
  if (!MATH_HINT.test(body.textContent || "")) return;
  void loadMath().then((render) => {
    if (!render || !body.isConnected) return;
    try {
      render(body, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "\\[", right: "\\]", display: true },
          { left: "$", right: "$", display: false },
          { left: "\\(", right: "\\)", display: false },
        ],
        throwOnError: false,
        ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"],
      });
    } catch (e) {
      console.warn("[ce-modal] KaTeX render failed", e);
    }
  });
}

export function parseTableValues(table: HTMLTableElement): (string | number | null)[][] {
  const rows: (string | number | null)[][] = [];
  const cellValue = (c: HTMLTableCellElement): string | number | null => {
    const raw = (c.textContent || "").trim();
    if (raw === "") return null;
    const n = Number(raw.replace(/,/g, ""));
    return Number.isFinite(n) && /^-?[\d,.]+(e-?\d+)?$/i.test(raw) ? n : raw;
  };
  for (const tr of Array.from(table.rows)) {
    rows.push(Array.from(tr.cells).map(cellValue));
  }
  return rows.filter((r) => r.some((v) => v !== null));
}

function tableButton(label: string, title: string, onClick: (btn: HTMLButtonElement) => void) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "sy-mdview-table-linkout";
  b.textContent = label;
  b.title = title;
  b.addEventListener("click", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    onClick(b);
  });
  return b;
}

async function plotFromTable(origin: string, values: (string | number | null)[][], btn: HTMLButtonElement) {
  btn.disabled = true;
  const toPlots = () =>
    window.dispatchEvent(new CustomEvent("sy:switch-tab-kind", { detail: { kind: "vega" } }));
  try {
    // Re-click on a table that already has plots just opens them.
    try {
      const list = await fetch("/api/plots").then((r) => (r.ok ? r.json() : null));
      const plots = (list && Array.isArray(list.plots) ? list.plots : []) as Array<{ origin?: string }>;
      if (plots.some((p) => p && p.origin === origin)) {
        toPlots();
        return;
      }
    } catch { /* fall through */ }
    const body = await fetch("/api/plots/from-table", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ origin, values }),
    }).then((r) => r.json());
    if (body && body.run_id) {
      window.dispatchEvent(new CustomEvent("sy:rail-system-tip", {
        detail: {
          text:
            "Plotting from `" + origin + "` — the agent is authoring 2-4 "
            + "Vega-Lite plots from the table. Watch them land in the Plot "
            + "tab, or open the Agents tab to follow the transcript (run `"
            + body.run_id + "`).",
          focus: false,
        },
      }));
      toPlots();
    }
  } catch (e) {
    console.warn("[ce-modal] plot from table failed", e);
  } finally {
    btn.disabled = false;
  }
}

function attachTableLinkouts(body: HTMLElement, originHint: string): void {
  body.querySelectorAll(".sy-mdview-table-linkout-row").forEach((n) => n.remove());
  body.querySelectorAll("table").forEach((table, i) => {
    const origin = `${originHint || "graph-modal"}#table-${i + 1}`;
    const row = document.createElement("div");
    row.className = "sy-mdview-table-linkout-row";
    row.appendChild(tableButton("↗ Sheet", "Open this table in the Sheet tab for editing", () => {
      const values = parseTableValues(table);
      if (!values.length) return;
      window.dispatchEvent(new CustomEvent("sy:open-as-sheet", { detail: { origin, values } }));
    }));
    row.appendChild(tableButton("↗ Plot", "Ask the agent to author Vega-Lite plots from this table", (btn) => {
      const values = parseTableValues(table);
      if (values.length) void plotFromTable(origin, values, btn);
    }));
    table.parentNode?.insertBefore(row, table);
  });
}

/**
 * CE's Edit module forgets its "Saved" toast when it is re-initialised
 * (every canvas remount), so a remount while the toast shows leaves it
 * stuck on screen and its hide timer throws. Remount after it hides.
 */
export async function waitForCeToast(maxMs = 3000): Promise<void> {
  const t0 = Date.now();
  while (Date.now() - t0 < maxMs) {
    const el = document.getElementById("edit-toast");
    if (!el || !el.classList.contains("visible")) return;
    await new Promise((r) => setTimeout(r, 150));
  }
}

/**
 * CE's embed mounts the canvas but leaves the "replay" control unwired
 * (only CE's standalone main.js calls CurationReplay.init). Wire it once
 * per rendered toggle.
 */
export function bindCeReplay(root: ParentNode, data: unknown): boolean {
  const btn = root.querySelector<HTMLElement>("#replay-toggle");
  const replay = (window as { CurationReplay?: { init?: (d: unknown) => void } }).CurationReplay;
  if (!btn || btn.dataset.syReplay === "1" || typeof replay?.init !== "function") return false;
  btn.dataset.syReplay = "1";
  try {
    replay.init(data);
  } catch (e) {
    console.warn("[ce-replay] init failed", e);
    return false;
  }
  return true;
}

/** Page id currently shown in CE's modal (from the URL hash CE keeps). */
export function currentModalPageId(): string | null {
  const m = window.location.hash.match(/^#page=([^&]+)$/);
  return m ? decodeURIComponent(m[1]) : null;
}

/** Decorate a freshly rendered CE modal body (idempotent per render). */
export function enhanceCeModalBody(body: HTMLElement, originHint: string): void {
  renderMath(body);
  attachTableLinkouts(body, originHint);
}

const SLIDES_HIDDEN_TYPES = new Set(["figure", "table", "source", "sources"]);

/**
 * "Make HTML slideshow" in CE's modal. The button lives in Switch Bay's
 * canvas shell markup (ceEmbedShell.html); bind it once, then show it
 * for every page type except figure/table/source stubs.
 */
export function bindSlideshowButton(
  modal: HTMLElement,
  pagePath: () => string | null,
  pageType: () => string,
): void {
  const btn = modal.querySelector<HTMLButtonElement>("#modal-slides");
  if (!btn) return;
  if (btn.dataset.syBound !== "1") {
    btn.dataset.syBound = "1";
    btn.addEventListener("click", async () => {
      let path = pagePath();
      if (!path) return;
      if (!path.startsWith("wiki/")) path = `wiki/${path}`;
      btn.disabled = true;
      try {
        const r = await fetch("/api/slideshows/from-md", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path, open: true, generate_media: false }),
        });
        const out = r.ok ? await r.json() : null;
        if (out && out.slug) {
          window.dispatchEvent(new CustomEvent("sy:open-as-slideshow", {
            detail: { slug: out.slug, title: out.title || out.slug },
          }));
        }
      } catch (e) {
        console.warn("[ce-modal] slideshow failed", e);
      } finally {
        btn.disabled = false;
      }
    });
  }
  btn.style.display = SLIDES_HIDDEN_TYPES.has(pageType()) ? "none" : "";
}
