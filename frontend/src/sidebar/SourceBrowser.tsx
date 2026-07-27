import { useEffect, useMemo, useState } from "react";
import { useSelection } from "../selection/SelectionContext";
import { useTabs } from "../center/TabsContext";

/**
 * Sources view (D1) — the Browser column's second pane mode. A
 * provenance view over `extracted_from` frontmatter paths, NOT a
 * second file browser: it shows only the EXTERNAL files/URLs this
 * wiki's pages were extracted from, path-compressed to the
 * directories that actually contain sources (with a toggle to show
 * the real hierarchy). In-vault provenance folds into the FILES
 * tree, so a workspace whose material all lives in the vault gets an
 * honest empty state instead of a mirrored tree.
 */

type SourcePage = { page: string; title: string };
type SourceRec = {
  path: string;
  kind: "file" | "url";
  exists: boolean | null;
  pages: SourcePage[];
};
type SourcesBody = {
  sources: SourceRec[];
  internal_pages: number;
  pages_scanned: number;
};

type DirNode = {
  label: string;
  path: string;
  children: DirNode[];
  leaves: SourceRec[];
};

function buildDirTree(recs: SourceRec[], compress: boolean): DirNode[] {
  const root: DirNode = { label: "", path: "", children: [], leaves: [] };
  for (const rec of recs) {
    const parts = rec.path.split("/").filter(Boolean);
    const dirs = parts.slice(0, -1);
    let node = root;
    let acc = "";
    for (const d of dirs) {
      acc += "/" + d;
      let child = node.children.find((c) => c.path === acc);
      if (!child) {
        child = { label: d, path: acc, children: [], leaves: [] };
        node.children.push(child);
      }
      node = child;
    }
    node.leaves.push(rec);
  }
  const sortRec = (n: DirNode) => {
    n.children.sort((a, b) => a.label.localeCompare(b.label));
    n.leaves.sort((a, b) => a.path.localeCompare(b.path));
    n.children.forEach(sortRec);
  };
  sortRec(root);
  if (compress) {
    // Path-compress: a chain of single-child directories with no
    // sources of their own collapses into one labelled row, so two
    // sources three-up-two-down apart show just their two parent
    // dirs, not the whole ancestry.
    const compressRec = (n: DirNode): DirNode => {
      let cur = n;
      while (cur.children.length === 1 && cur.leaves.length === 0) {
        const child = cur.children[0];
        cur = { ...child, label: cur.label ? `${cur.label}/${child.label}` : child.label };
      }
      return { ...cur, children: cur.children.map(compressRec) };
    };
    return root.children.map(compressRec);
  }
  return root.children;
}

/** Display an absolute dir label with the home dir as ~. */
function tildify(label: string): string {
  return label.replace(/^Users\/([^/]+)/, "~ ($1)").replace(/^home\/([^/]+)/, "~ ($1)");
}

function urlLabel(u: string): string {
  try {
    const p = new URL(u);
    const tail = p.pathname.length > 1 ? p.pathname : "";
    return p.hostname + (tail.length > 28 ? tail.slice(0, 25) + "…" : tail);
  } catch {
    return u;
  }
}

export default function SourceBrowser({
  refreshKey,
  headExtra,
}: {
  refreshKey: number;
  /** Rendered in place of the head label — the Sidebar passes the
   *  Files|Sources segmented toggle so it stays reachable in every
   *  state (loading, empty, error). */
  headExtra?: React.ReactNode;
}) {
  const [body, setBody] = useState<SourcesBody | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [compress, setCompress] = useState(true);
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  // Sources whose page list is expanded (multi-page sources).
  const [openPages, setOpenPages] = useState<Set<string>>(() => new Set());
  const { setSelection } = useSelection();
  const { switchToKind } = useTabs();

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetch("/api/sources")
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return (await r.json()) as SourcesBody;
      })
      .then((b) => { if (!cancelled) setBody(b); })
      .catch((e: Error) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [refreshKey]);

  const files = useMemo(
    () => (body?.sources ?? []).filter((s) => s.kind === "file"),
    [body],
  );
  const urls = useMemo(
    () => (body?.sources ?? []).filter((s) => s.kind === "url"),
    [body],
  );
  const tree = useMemo(() => buildDirTree(files, compress), [files, compress]);

  const openPage = (pg: SourcePage) => {
    const rel = pg.page.startsWith("wiki/") ? pg.page.slice("wiki/".length) : pg.page;
    const slug = rel.endsWith(".md") ? rel.slice(0, -".md".length) : rel;
    setSelection({ kind: "page", id: slug, path: rel });
    switchToKind("markdown");
  };

  const onSourceClick = (rec: SourceRec) => {
    if (rec.pages.length === 1) {
      openPage(rec.pages[0]);
      return;
    }
    setOpenPages((cur) => {
      const next = new Set(cur);
      if (next.has(rec.path)) next.delete(rec.path);
      else next.add(rec.path);
      return next;
    });
  };

  const reveal = async (path: string) => {
    try {
      await fetch("/api/sources/reveal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
    } catch { /* daemon down */ }
  };

  const toggleDir = (path: string) => {
    setCollapsed((cur) => {
      const next = new Set(cur);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const renderSource = (rec: SourceRec, depth: number) => {
    const name = rec.kind === "url"
      ? urlLabel(rec.path)
      : rec.path.split("/").pop() ?? rec.path;
    const pagesOpen = openPages.has(rec.path);
    return (
      <div key={rec.path}>
        <div
          className="sy-src-row"
          style={{ paddingLeft: 8 + depth * 12 }}
          title={rec.path}
        >
          <button
            type="button"
            className="sy-src-name"
            onClick={() => onSourceClick(rec)}
            title={
              rec.pages.length === 1
                ? `Open the page extracted from this source (${rec.pages[0].page})`
                : `${rec.pages.length} pages came from this source — click to list`
            }
          >
            <span className="sy-src-glyph">{rec.kind === "url" ? "⌁" : "▪"}</span>
            {name}
            {rec.pages.length > 1 && (
              <span className="sy-src-count">{rec.pages.length}</span>
            )}
            {rec.kind === "file" && rec.exists === false && (
              <span className="sy-src-missing" title="The original no longer exists at this path">
                gone
              </span>
            )}
          </button>
          {rec.kind === "file" && rec.exists !== false && (
            <button
              type="button"
              className="sy-src-act"
              onClick={() => void reveal(rec.path)}
              title="Reveal the original in the file manager"
            >
              ⊙
            </button>
          )}
          {rec.kind === "url" && (
            <button
              type="button"
              className="sy-src-act"
              onClick={() => window.open(rec.path, "_blank", "noopener")}
              title="Open the source link"
            >
              ↗
            </button>
          )}
        </div>
        {pagesOpen && rec.pages.map((pg) => (
          <button
            key={pg.page}
            type="button"
            className="sy-src-row sy-src-page"
            style={{ paddingLeft: 8 + (depth + 1) * 12 }}
            onClick={() => openPage(pg)}
            title={pg.page}
          >
            <span className="sy-src-glyph">·</span>
            {pg.title || pg.page.split("/").pop()}
          </button>
        ))}
      </div>
    );
  };

  const renderDir = (node: DirNode, depth: number): React.ReactNode => {
    const isCollapsed = collapsed.has(node.path);
    return (
      <div key={node.path}>
        <button
          type="button"
          className="sy-src-row sy-src-dir"
          style={{ paddingLeft: 8 + depth * 12 }}
          onClick={() => toggleDir(node.path)}
          title={node.path}
        >
          <span className="sy-src-glyph">{isCollapsed ? "▸" : "▾"}</span>
          {tildify(node.label)}
        </button>
        {!isCollapsed && (
          <>
            {node.children.map((c) => renderDir(c, depth + 1))}
            {node.leaves.map((rec) => renderSource(rec, depth + 1))}
          </>
        )}
      </div>
    );
  };

  // The head (with the Files|Sources toggle) renders in EVERY state —
  // a loading or empty Sources view must still let the user flip back.
  const head = (
    <div className="sy-src-head">
      {headExtra ?? <span>SOURCES</span>}
      {body && body.sources.length > 0 && (
        <span>
          {body.sources.length} source{body.sources.length === 1 ? "" : "s"}
        </span>
      )}
      <span style={{ flex: 1 }} />
      {files.length > 0 && (
        <button
          type="button"
          className={"sy-src-ctrl" + (compress ? "" : " sy-src-ctrl--on")}
          onClick={() => setCompress((c) => !c)}
          title={
            compress
              ? "Showing compressed paths (only dirs that contain sources) — click for the real hierarchy"
              : "Showing the real directory hierarchy — click to compress"
          }
        >
          {compress ? "⇥ compressed" : "⇤ full paths"}
        </button>
      )}
    </div>
  );

  let content: React.ReactNode;
  if (error) {
    content = <div className="sy-src-empty">sources unavailable: {error}</div>;
  } else if (!body) {
    content = <div className="sy-src-empty">scanning provenance…</div>;
  } else if (body.sources.length === 0) {
    content = (
      <div className="sy-src-empty">
        <p>No external sources — everything lives in the vault.</p>
        {body.internal_pages > 0 && (
          <p className="sy-src-empty-sub">
            {body.internal_pages} page{body.internal_pages === 1 ? " was" : "s were"}{" "}
            extracted from vault uploads — browse those in the Files view.
          </p>
        )}
        <p className="sy-src-empty-sub">
          This view fills in when pages carry <code>extracted_from</code>{" "}
          provenance pointing outside the workspace (ingested local files,
          comms-stream deep links).
        </p>
      </div>
    );
  } else {
    content = (
      <>
        {tree.map((n) => renderDir(n, 0))}
        {urls.length > 0 && (
          <>
            <div className="sy-src-divider">web</div>
            {urls.map((rec) => renderSource(rec, 0))}
          </>
        )}
      </>
    );
  }

  return (
    <div className="sy-src">
      {head}
      {content}
    </div>
  );
}
