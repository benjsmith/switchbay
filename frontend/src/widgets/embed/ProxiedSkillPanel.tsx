import { useCallback, useEffect, useRef, useState } from "react";
import {
  type CoreSkillsStatus,
  type EmbedScript,
  type StatusBanner,
  mapStatusBanner,
  prepareEmbedHtml,
} from "./embedMount.ts";

/**
 * Embed v2 same-origin skill panel (NO iframe).
 *
 * Mount algorithm (happy path — scripts execute):
 * 1. Poll `/api/core-skills/status` while open; show wait chrome until healthy.
 * 2. fetch proxied HTML from `/embed/ce|okstratr/…`.
 * 3. Rewrite asset URLs to the public base; extract scripts.
 * 4. Inject markup into the panel root; createElement+append each script
 *    (module + classic) so the browser runs them (innerHTML never does).
 * 5. Tear down (clear root + remove injected scripts) before soft-reload
 *    or unmount to avoid duplicate roots/listeners.
 *
 * JSON responses keep the pretty-print path. No nested frames (ADR-004 / 004b).
 */

export type SkillEmbedKind = "ce" | "okstratr";

const PREFIX: Record<SkillEmbedKind, string> = {
  ce: "/embed/ce",
  okstratr: "/embed/okstratr",
};

const LABEL: Record<SkillEmbedKind, string> = {
  ce: "Curiosity Engine",
  okstratr: "okstratr",
};

const DEFAULT_PATH: Record<SkillEmbedKind, string> = {
  ce: "/",
  okstratr: "/observer/",
};

const STATUS_POLL_MS = 2000;

type Props = {
  kind: SkillEmbedKind;
};

type LoadState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ok-html" }
  | { status: "ok-json"; text: string }
  | { status: "ok-text"; text: string }
  | { status: "error"; message: string; httpStatus?: number };

async function executeScripts(
  scripts: EmbedScript[],
  container: HTMLElement,
  tracker: HTMLScriptElement[],
): Promise<void> {
  for (const desc of scripts) {
    if (desc.noModule) continue;
    const el = document.createElement("script");
    el.dataset.syEmbedScript = "1";
    if (desc.type === "module") el.type = "module";
    if (desc.async) el.async = true;
    if (desc.defer) el.defer = true;
    if (desc.crossOrigin != null) el.crossOrigin = desc.crossOrigin || "anonymous";
    if (desc.integrity) el.integrity = desc.integrity;
    if (desc.referrerPolicy) {
      el.referrerPolicy = desc.referrerPolicy as ReferrerPolicy;
    }

    if (desc.src) {
      await new Promise<void>((resolve, reject) => {
        el.onload = () => resolve();
        el.onerror = () =>
          reject(new Error(`Failed to load embed script: ${desc.src}`));
        el.src = desc.src!;
        container.appendChild(el);
        tracker.push(el);
      });
    } else {
      // Inline: textContent + append executes classic scripts synchronously.
      el.textContent = desc.content ?? "";
      container.appendChild(el);
      tracker.push(el);
    }
  }
}

export default function ProxiedSkillPanel({ kind }: Props) {
  const prefix = PREFIX[kind];
  const [path, setPath] = useState(DEFAULT_PATH[kind]);
  const [draft, setDraft] = useState(DEFAULT_PATH[kind]);
  const [state, setState] = useState<LoadState>({ status: "idle" });
  const [refreshing, setRefreshing] = useState(false);
  const [coreStatus, setCoreStatus] = useState<CoreSkillsStatus | null>(null);
  const pathRef = useRef(path);
  pathRef.current = path;
  const coreStatusRef = useRef<CoreSkillsStatus | null>(null);
  coreStatusRef.current = coreStatus;

  const mountRef = useRef<HTMLDivElement | null>(null);
  const injectedScriptsRef = useRef<HTMLScriptElement[]>([]);
  const loadGenRef = useRef(0);

  const banner: StatusBanner = mapStatusBanner(kind, coreStatus);

  const teardown = useCallback(() => {
    for (const el of injectedScriptsRef.current) {
      try {
        el.remove();
      } catch {
        /* already gone */
      }
    }
    injectedScriptsRef.current = [];
    const root = mountRef.current;
    if (root) root.innerHTML = "";
  }, []);

  // Status poll while panel is mounted (every 2s).
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      try {
        const r = await fetch("/api/core-skills/status", { cache: "no-store" });
        if (!r.ok) throw new Error(`status ${r.status}`);
        const j = (await r.json()) as CoreSkillsStatus;
        if (!cancelled) setCoreStatus(j);
      } catch {
        /* keep last known */
      } finally {
        if (!cancelled) {
          timer = setTimeout(tick, STATUS_POLL_MS);
        }
      }
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const load = useCallback(
    async (p: string, opts?: { soft?: boolean }) => {
      const soft = !!opts?.soft;
      const gen = ++loadGenRef.current;
      const liveBanner = mapStatusBanner(kind, coreStatusRef.current);

      if (!liveBanner.allowMount) {
        teardown();
        setState({ status: "idle" });
        return;
      }

      if (soft) {
        setRefreshing(true);
      } else {
        setState({ status: "loading" });
      }

      const base = prefix + (p.startsWith("/") ? p : `/${p}`);
      const sep = base.includes("?") ? "&" : "?";
      const url = `${base}${sep}_sb=${Date.now()}`;

      try {
        const r = await fetch(url, {
          cache: "no-store",
          headers: { Accept: "text/html, application/json;q=0.9, */*;q=0.8" },
        });
        if (gen !== loadGenRef.current) return;

        const ct = r.headers.get("content-type") || "";
        const text = await r.text();
        if (gen !== loadGenRef.current) return;

        if (!r.ok) {
          // While starting, status chrome already explains wait — skip 502 flash.
          if (mapStatusBanner(kind, coreStatusRef.current).suppressFetchError) {
            setState({ status: "idle" });
            return;
          }
          setState({
            status: "error",
            message: text.slice(0, 500) || r.statusText,
            httpStatus: r.status,
          });
          teardown();
          return;
        }

        if (ct.includes("application/json")) {
          teardown();
          let pretty = text;
          try {
            pretty = JSON.stringify(JSON.parse(text), null, 2);
          } catch {
            /* keep raw */
          }
          setState({ status: "ok-json", text: pretty });
          return;
        }

        if (ct.includes("text/html") || /^\s*</.test(text)) {
          teardown();
          const root = mountRef.current;
          if (!root) {
            setState({ status: "error", message: "mount root missing" });
            return;
          }
          const { markup, scripts } = prepareEmbedHtml(text, prefix, p);
          root.innerHTML = markup;
          try {
            await executeScripts(scripts, root, injectedScriptsRef.current);
          } catch (e) {
            if (gen !== loadGenRef.current) return;
            setState({
              status: "error",
              message: (e as Error).message || "script load failed",
            });
            return;
          }
          if (gen !== loadGenRef.current) return;
          setState({ status: "ok-html" });
          return;
        }

        teardown();
        setState({ status: "ok-text", text });
      } catch (e) {
        if (gen !== loadGenRef.current) return;
        if (mapStatusBanner(kind, coreStatusRef.current).suppressFetchError) {
          setState({ status: "idle" });
          return;
        }
        setState({
          status: "error",
          message: (e as Error).message || "fetch failed",
        });
      } finally {
        if (soft && gen === loadGenRef.current) setRefreshing(false);
      }
    },
    [prefix, kind, teardown],
  );

  // Mount when path changes or skill becomes healthy enough to allowMount.
  useEffect(() => {
    if (!banner.allowMount) {
      teardown();
      setState({ status: "idle" });
      return;
    }
    void load(path);
  }, [load, path, banner.allowMount, teardown]);

  // Live view: wiki / curator / rescan → daemon files_changed → soft remount.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const onFiles = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        void load(pathRef.current, { soft: true });
      }, 400);
    };
    window.addEventListener("sy:files-changed", onFiles);
    return () => {
      if (timer) clearTimeout(timer);
      window.removeEventListener("sy:files-changed", onFiles);
    };
  }, [load]);

  useEffect(() => () => teardown(), [teardown]);

  const onNavigate = (ev: React.FormEvent) => {
    ev.preventDefault();
    const next = draft.trim() || "/";
    setPath(next.startsWith("/") ? next : `/${next}`);
  };

  const showWaitChrome = !banner.allowMount;
  const showError =
    state.status === "error" && !banner.suppressFetchError && !showWaitChrome;

  return (
    <div className="sy-proxied-skill" data-kind={kind} data-embed-v2="1">
      <header className="sy-proxied-skill-bar">
        <strong>{LABEL[kind]}</strong>
        <span className="sy-proxied-skill-hint">
          same-origin via {prefix} (no iframe)
          {refreshing ? " · updating…" : ""}
        </span>
        <form className="sy-proxied-skill-nav" onSubmit={onNavigate}>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            aria-label="Proxied path"
            spellCheck={false}
          />
          <button type="submit">Go</button>
          <button
            type="button"
            onClick={() => {
              setDraft(path);
              void load(path, { soft: true });
            }}
          >
            Reload
          </button>
        </form>
      </header>

      <div
        className={`sy-proxied-skill-status sy-proxied-skill-status--${banner.kind}`}
        role="status"
        aria-live="polite"
      >
        {banner.label}
      </div>

      <div className="sy-proxied-skill-body">
        {showWaitChrome && (
          <p className="sy-proxied-skill-muted">
            Waiting for {LABEL[kind]} before mounting interactive UI…
          </p>
        )}
        {!showWaitChrome && state.status === "loading" && (
          <p className="sy-proxied-skill-muted">
            Loading {prefix}
            {path}…
          </p>
        )}
        {showError && state.status === "error" && (
          <div className="sy-proxied-skill-error" role="alert">
            <p>
              Upstream unreachable or proxy error
              {state.httpStatus != null ? ` (${state.httpStatus})` : ""}.
            </p>
            <pre>{state.message}</pre>
            <p className="sy-proxied-skill-muted">
              Start the skill upstream on loopback
              {kind === "ce"
                ? " (CE viewer — default :8766, or whatever SWITCHBAY_CE_UPSTREAM points at)"
                : " (okstratr :8767)"}
              , or turn off Settings → Storage → “Proxied skill embeds” for the
              built-in tab. A 502 almost always means that upstream process
              exited.
            </p>
          </div>
        )}
        {state.status === "ok-json" && (
          <pre className="sy-proxied-skill-json">{state.text}</pre>
        )}
        {state.status === "ok-text" && (
          <pre className="sy-proxied-skill-text">{state.text}</pre>
        )}
        <div
          ref={mountRef}
          className="sy-proxied-skill-html"
          data-sy-embed-root="1"
          hidden={state.status !== "ok-html"}
        />
      </div>
    </div>
  );
}
