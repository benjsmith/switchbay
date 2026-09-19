import { useCallback, useEffect, useState } from "react";

/**
 * Phase 4a same-origin skill panel (NO iframe).
 *
 * Loads CE or okstratr through the daemon reverse-proxy under
 * `/embed/ce/*` or `/embed/okstratr/*`. In-app path navigation uses
 * fetch + a same-document panel — never a nested frame.
 *
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

  const load = useCallback(
    async (p: string) => {
      setState({ status: "loading" });
      const url = prefix + (p.startsWith("/") ? p : `/${p}`);
      try {
        const r = await fetch(url, {
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
      }
    },
    [prefix],
  );

  useEffect(() => {
    void load(path);
  }, [load, path]);

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
              void load(path);
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
