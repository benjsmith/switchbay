/**
 * Embed v2 same-document mount helpers (no iframe).
 *
 * Mount algorithm (see docs/ADR-004b-embed-v2-same-document-mount.md):
 * 1. Tear down prior mount (clear panel root + remove injected <script> nodes).
 * 2. fetch(`/embed/{ce|okstratr}/…`) for proxied HTML.
 * 3. rewriteHtmlUrls → absolute `/embed/…` asset paths.
 * 4. extractScripts → markup without <script>; script descriptors for execution.
 * 5. Inject markup into the panel root (innerHTML).
 * 6. Recreate each <script> via createElement + append so the browser executes
 *    classic and module scripts (innerHTML never runs scripts).
 * Soft-reload / unmount repeats step 1 first to avoid duplicate roots/listeners.
 */

export type EmbedScript = {
  type: "classic" | "module";
  src?: string;
  content?: string;
  async?: boolean;
  defer?: boolean;
  crossOrigin?: string | null;
  integrity?: string | null;
  referrerPolicy?: string | null;
  noModule?: boolean;
};

export type PrepareResult = {
  /** Body (+ head stylesheet/style) markup with scripts removed and URLs rewritten. */
  markup: string;
  scripts: EmbedScript[];
};

/** Directory URL (trailing slash) for resolving relative asset paths. */
export function documentDir(publicBase: string, pagePath: string): string {
  const base = publicBase.replace(/\/$/, "") || "";
  let path = pagePath.startsWith("/") ? pagePath : `/${pagePath}`;
  if (!path) path = "/";
  const full = `${base}${path}`;
  if (full.endsWith("/")) return full;
  const idx = full.lastIndexOf("/");
  return idx >= 0 ? full.slice(0, idx + 1) : `${base}/`;
}

function joinResolved(docDir: string, relative: string): string {
  // docDir always ends with /
  const parts = docDir.replace(/\/$/, "").split("/");
  for (const seg of relative.split("/")) {
    if (!seg || seg === ".") continue;
    if (seg === "..") {
      if (parts.length > 1) parts.pop();
      continue;
    }
    parts.push(seg);
  }
  // parts[0] is "" for absolute paths like ["", "embed", "ce", ...]
  return parts.join("/") || "/";
}

/**
 * Rewrite a single URL attribute value under publicBase.
 * Leaves fragments, data:, blob:, javascript:, and external http(s) hosts alone.
 * Maps loopback absolute URLs and root-relative paths onto publicBase.
 */
export function rewriteAssetUrl(
  raw: string,
  publicBase: string,
  pagePath: string,
): string {
  const u = (raw || "").trim();
  if (!u) return u;
  if (
    u.startsWith("#") ||
    u.startsWith("data:") ||
    u.startsWith("blob:") ||
    u.startsWith("javascript:") ||
    u.startsWith("mailto:")
  ) {
    return u;
  }

  const base = publicBase.replace(/\/$/, "") || "";

  // Protocol-relative — leave (external CDN etc.)
  if (u.startsWith("//")) return u;

  // Absolute with scheme
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(u)) {
    try {
      const parsed = new URL(u);
      const host = parsed.hostname.toLowerCase();
      if (host === "127.0.0.1" || host === "localhost" || host === "::1") {
        const path = parsed.pathname || "/";
        return `${base}${path}${parsed.search}${parsed.hash}`;
      }
    } catch {
      /* keep */
    }
    return u;
  }

  // Already under public base
  if (base && (u === base || u.startsWith(`${base}/`))) return u;

  // Root-relative → prefix public base
  if (u.startsWith("/")) return `${base}${u}`;

  // Relative → resolve against document directory
  const dir = documentDir(publicBase, pagePath);
  return joinResolved(dir, u);
}

function rewriteSrcset(
  value: string,
  publicBase: string,
  pagePath: string,
): string {
  return value
    .split(",")
    .map((part) => {
      const trimmed = part.trim();
      if (!trimmed) return trimmed;
      const m = trimmed.match(/^(\S+)(\s+.*)?$/);
      if (!m) return trimmed;
      const rewritten = rewriteAssetUrl(m[1], publicBase, pagePath);
      return m[2] ? `${rewritten}${m[2]}` : rewritten;
    })
    .join(", ");
}

function rewriteCssUrls(
  css: string,
  publicBase: string,
  pagePath: string,
): string {
  return css.replace(/url\(\s*(['"]?)([^'")]+)\1\s*\)/gi, (_all, quote: string, ref: string) => {
    const next = rewriteAssetUrl(ref.trim(), publicBase, pagePath);
    const q = quote || "";
    return `url(${q}${next}${q})`;
  });
}

const ATTR_URL_RE =
  /\b(src|href|poster|action|formaction|data-src|data-href)\s*=\s*(["'])([^"']*)\2/gi;
const SRCSET_RE = /\bsrcset\s*=\s*(["'])([^"']*)\1/gi;
/** Rewrite asset URLs in an HTML string for same-origin `/embed/*` serving. */
export function rewriteHtmlUrls(
  html: string,
  publicBase: string,
  pagePath: string,
): string {
  let out = html.replace(ATTR_URL_RE, (_all, attr: string, quote: string, val: string) => {
    const next = rewriteAssetUrl(val, publicBase, pagePath);
    return `${attr}=${quote}${next}${quote}`;
  });
  out = out.replace(SRCSET_RE, (_all, quote: string, val: string) => {
    return `srcset=${quote}${rewriteSrcset(val, publicBase, pagePath)}${quote}`;
  });
  // Double- and single-quoted style attrs separately so nested quotes in url() work.
  out = out.replace(/\bstyle\s*=\s*"([^"]*)"/gi, (_all, val: string) => {
    return `style="${rewriteCssUrls(val, publicBase, pagePath)}"`;
  });
  out = out.replace(/\bstyle\s*=\s*'([^']*)'/gi, (_all, val: string) => {
    return `style='${rewriteCssUrls(val, publicBase, pagePath)}'`;
  });
  out = out.replace(
    /<style\b([^>]*)>([\s\S]*?)<\/style>/gi,
    (_all, attrs: string, body: string) =>
      `<style${attrs}>${rewriteCssUrls(body, publicBase, pagePath)}</style>`,
  );
  return out;
}

function parseScriptOpeningAttrs(attrText: string): EmbedScript {
  const lower = attrText.toLowerCase();
  const typeMatch = attrText.match(/\btype\s*=\s*(["'])([^"']*)\1/i);
  const typeVal = (typeMatch?.[2] || "").trim().toLowerCase();
  const isModule = typeVal === "module" || /\btype\s*=\s*module\b/i.test(attrText);
  const srcMatch = attrText.match(/\bsrc\s*=\s*(["'])([^"']*)\1/i);
  const crossMatch = attrText.match(/\bcrossorigin\s*=\s*(["'])([^"']*)\1/i);
  const integrityMatch = attrText.match(/\bintegrity\s*=\s*(["'])([^"']*)\1/i);
  const referrerMatch = attrText.match(/\breferrerpolicy\s*=\s*(["'])([^"']*)\1/i);
  return {
    type: isModule ? "module" : "classic",
    src: srcMatch?.[2],
    async: /\basync\b/i.test(lower),
    defer: /\bdefer\b/i.test(lower),
    noModule: /\bnomodule\b/i.test(lower),
    crossOrigin: crossMatch ? crossMatch[2] : /\bcrossorigin\b/i.test(lower) ? "" : null,
    integrity: integrityMatch?.[2] ?? null,
    referrerPolicy: referrerMatch?.[2] ?? null,
  };
}

/**
 * Pull `<script>` tags out of HTML (order preserved) and return markup without them.
 * Script `src` values should already be rewritten (call rewriteHtmlUrls first).
 */
export function extractScripts(html: string): {
  htmlWithoutScripts: string;
  scripts: EmbedScript[];
} {
  const scripts: EmbedScript[] = [];
  const htmlWithoutScripts = html.replace(
    /<script\b([^>]*)>([\s\S]*?)<\/script>/gi,
    (_all, attrs: string, body: string) => {
      const desc = parseScriptOpeningAttrs(attrs || "");
      if (desc.src) {
        scripts.push({ ...desc, content: undefined });
      } else {
        scripts.push({ ...desc, content: body, src: undefined });
      }
      return "";
    },
  );
  return { htmlWithoutScripts, scripts };
}

/** Collect head stylesheets/styles + body inner HTML for panel injection. */
export function extractMountMarkup(html: string): string {
  const headMatch = html.match(/<head\b[^>]*>([\s\S]*?)<\/head>/i);
  const bodyMatch = html.match(/<body\b[^>]*>([\s\S]*)<\/body>/i);
  const head = headMatch ? headMatch[1] : "";
  const body = bodyMatch ? bodyMatch[1] : html;

  const headAssets: string[] = [];
  const linkRe = /<link\b[^>]*>/gi;
  let m: RegExpExecArray | null;
  while ((m = linkRe.exec(head)) !== null) {
    const tag = m[0];
    if (/\brel\s*=\s*(["'])stylesheet\1/i.test(tag) || /\brel\s*=\s*stylesheet\b/i.test(tag)) {
      headAssets.push(tag);
    }
  }
  const styleRe = /<style\b[^>]*>[\s\S]*?<\/style>/gi;
  while ((m = styleRe.exec(head)) !== null) {
    headAssets.push(m[0]);
  }

  return `${headAssets.join("\n")}\n${body}`.trim();
}

/** Full prepare pipeline: rewrite → extract scripts → mount markup. */
export function prepareEmbedHtml(
  html: string,
  publicBase: string,
  pagePath: string,
): PrepareResult {
  const rewritten = rewriteHtmlUrls(html, publicBase, pagePath);
  const { htmlWithoutScripts, scripts } = extractScripts(rewritten);
  // Rewrite script.src again is already done via ATTR_URL_RE on the full doc.
  const markup = extractMountMarkup(htmlWithoutScripts);
  return { markup, scripts };
}

// ── Status banner mapping (C1 status shape) ──────────────────────────

export type SkillHealthState = "starting" | "healthy" | "unhealthy" | "stopped";
export type WikiBuildState = "idle" | "building" | "failed";

export type CoreSkillsStatus = {
  ce?: { state?: string; url?: string; detail?: string };
  okstratr?: { state?: string; url?: string; detail?: string };
  wiki_build?: { state?: string; pages?: number | null; detail?: string };
};

export type BannerKind = "starting" | "unhealthy" | "building_wiki" | "live" | "unknown";

export type StatusBanner = {
  kind: BannerKind;
  label: string;
  /** True when it is safe to fetch+mount the proxied HTML. */
  allowMount: boolean;
  /** True while supervisor is coming up — suppress full 502 error chrome. */
  suppressFetchError: boolean;
};

const LABELS: Record<"ce" | "okstratr", string> = {
  ce: "CE",
  okstratr: "okstratr",
};

export function mapStatusBanner(
  kind: "ce" | "okstratr",
  status: CoreSkillsStatus | null | undefined,
): StatusBanner {
  const slice = kind === "ce" ? status?.ce : status?.okstratr;
  const state = (slice?.state || "").toLowerCase() as SkillHealthState | "";
  const wiki = (status?.wiki_build?.state || "").toLowerCase() as WikiBuildState | "";
  const name = LABELS[kind];

  if (!status || !state) {
    return {
      kind: "unknown",
      label: `Checking ${name} status…`,
      allowMount: false,
      suppressFetchError: true,
    };
  }

  if (state === "starting" || state === "stopped") {
    return {
      kind: "starting",
      label:
        state === "stopped"
          ? `${name} stopped — auto-start pending…`
          : `${name} starting…`,
      allowMount: false,
      suppressFetchError: true,
    };
  }

  if (state === "unhealthy") {
    const detail = slice?.detail ? ` — ${slice.detail}` : "";
    return {
      kind: "unhealthy",
      label: `${name} unhealthy${detail}`,
      allowMount: false,
      suppressFetchError: false,
    };
  }

  if (state === "healthy") {
    if (wiki === "building") {
      return {
        kind: "building_wiki",
        label: "Building wiki…",
        allowMount: true,
        suppressFetchError: false,
      };
    }
    return {
      kind: "live",
      label: `${name} live`,
      allowMount: true,
      suppressFetchError: false,
    };
  }

  return {
    kind: "unknown",
    label: `${name}: ${state || "unknown"}`,
    allowMount: false,
    suppressFetchError: true,
  };
}
