import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Phase 4a same-origin skill panel (NO iframe).
 *
 * Loads CE or okstratr through the daemon reverse-proxy under
 * `/embed/ce/*` or `/embed/okstratr/*`. In-app path navigation uses
 * fetch + a same-document panel — never a nested frame.
 *
 * Reloads automatically when the daemon broadcasts `files_changed`
 * (wiki edits, curator, rescan) so the proxied Graph feels live.
 * Full atlas/observer chrome lands as those skills grow hosted-mode
 * fragment/API UIs; this panel proves the proxy path and stays usable
 * when upstream is down.
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

type Props = {
  kind: SkillEmbedKind;
};

type LoadState =
  | { status: "loading" }
  | { status: "ok"; contentType: string; text: string; httpStatus: number }
  | { status: "error"; message: string; httpStatus?: number };

function stripScripts(html: string): string {
  return html
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, "")
    .replace(/\son\w+="[^"]*"/gi, "")
    .replace(/\son\w+='[^']*'/gi, "");
}

function extractBody(html: string): string {
  const m = html.match(/<body[^>]*>([\s\S]*)<\/body>/i);
  return m ? m[1] : html;
}

export default function ProxiedSkillPanel({ kind }: Props) {
  const prefix = PREFIX[kind];
  const [path, setPath] = useState(DEFAULT_PATH[kind]);
  const [draft, setDraft] = useState(DEFAULT_PATH[kind]);
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const pathRef = useRef(path);
  pathRef.current = path;

  const load = useCallback(
    async (p: string, opts?: { soft?: boolean }) => {
      const soft = !!opts?.soft;
      if (soft) {
        setRefreshing(true);
      } else {
        setState({ status: "loading" });
      }
      // Cache-bust so CE static bundle / proxy do not serve a stale shell.
      const base = prefix + (p.startsWith("/") ? p : `/${p}`);
      const sep = base.includes("?") ? "&" : "?";
      const url = `${base}${sep}_sb=${Date.now()}`;
      try {
        const r = await fetch(url, {
          cache: "no-store",
          headers: { Accept: "text/html, application/json;q=0.9, */*;q=0.8" },
        });
        const ct = r.headers.get("content-type") || "";
        const text = await r.text();
        if (!r.ok) {
          setState({
            status: "error",
            message: text.slice(0, 500) || r.statusText,
            httpStatus: r.status,
          });
          return;
        }
        setState({
          status: "ok",
          contentType: ct,
          text,
          httpStatus: r.status,
        });
      } catch (e) {
        setState({
          status: "error",
          message: (e as Error).message || "fetch failed",
        });
      } finally {
        if (soft) setRefreshing(false);
      }
    },
    [prefix],
  );

  useEffect(() => {
    void load(path);
  }, [load, path]);

  // Live view: wiki / curator / rescan → daemon files_changed → soft refetch.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const onFiles = () => {
      if (timer) clearTimeout(timer);
      // Debounce bursts (curator multi-write) into one refetch.
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

  const onNavigate = (ev: React.FormEvent) => {
    ev.preventDefault();
    const next = draft.trim() || "/";
    setPath(next.startsWith("/") ? next : `/${next}`);
  };

  return (
    <div className="sy-proxied-skill" data-kind={kind}>
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

      <div className="sy-proxied-skill-body">
        {state.status === "loading" && (
          <p className="sy-proxied-skill-muted">Loading {prefix}{path}…</p>
        )}
        {state.status === "error" && (
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
              , or turn off Settings → Storage → “Proxied skill embeds” for the built-in tab.
              A 502 almost always means that upstream process exited.
            </p>
          </div>
        )}
        {state.status === "ok" && (
          <ProxiedContent contentType={state.contentType} text={state.text} />
        )}
      </div>
    </div>
  );
}

function ProxiedContent({
  contentType,
  text,
}: {
  contentType: string;
  text: string;
}) {
  if (contentType.includes("application/json")) {
    let pretty = text;
    try {
      pretty = JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      /* keep raw */
    }
    return <pre className="sy-proxied-skill-json">{pretty}</pre>;
  }
  if (contentType.includes("text/html") || /^\s*</.test(text)) {
    // Same-document panel: script-stripped HTML body (not an iframe).
    const safe = stripScripts(extractBody(text));
    return (
      <div
        className="sy-proxied-skill-html"
        dangerouslySetInnerHTML={{ __html: safe }}
      />
    );
  }
  return <pre className="sy-proxied-skill-text">{text}</pre>;
}
