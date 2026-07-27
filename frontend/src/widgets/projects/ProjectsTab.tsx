import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSelection } from "../../selection/SelectionContext";
import { useTabs } from "../../center/TabsContext";
import { setBreadcrumb } from "./breadcrumb";

/**
 * Project Dashboard tab — surfaces CE's multi-project state for the
 * active workspace.
 *
 * Each project card shows the registry meta + a notes/todos rollup
 * pulled from the wiki frontmatter scan. Untagged notes/todos roll
 * up under a synthetic "General" card so they're never invisible.
 *
 * Click a card to expand it inline with the full member list,
 * bucketed into Notes / Todos / Other. Clicking a page row opens
 * that page in the editor (sets selection → editor tab).
 */

type Kinds = { notes: number; todos: number; other: number };

type ProjectSummary = {
  name: string;
  title?: string;
  description: string;
  home_page: string | null;
  created_at: string | null;
  deleted_at: string | null;
  archived: boolean;
  member_count: number;
  kinds: Kinds;
  synthetic: boolean;
};

type Page = {
  path: string;
  title: string;
  type: string;
  mtime: number;
};

type DetailResponse = {
  project: ProjectSummary;
  pages: Page[];
  kinds: { notes: Page[]; todos: Page[]; other: Page[] };
  log: string[];
};

const GENERAL = "_general";


export default function ProjectsTab() {
  const [items, setItems] = useState<ProjectSummary[]>([]);
  const [registryPresent, setRegistryPresent] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, DetailResponse>>({});
  // After a `sy:focus-project` event fires (rail/back-link from
  // editor), we want to scroll a specific page row into view AND
  // briefly highlight it. The Editor tab fires the event before the
  // detail fetch completes, so we stash the request and consume it
  // when the matching detail lands + the row mounts.
  const [highlightPath, setHighlightPath] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const { setSelection } = useSelection();
  const { switchToKind } = useTabs();

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch("/api/projects");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json() as { projects: ProjectSummary[]; registry_present: boolean };
      setItems(body.projects);
      setRegistryPresent(body.registry_present);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void reload(); }, [reload]);

  const loadDetail = useCallback(async (name: string) => {
    if (details[name]) return;
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(name)}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json() as DetailResponse;
      setDetails((prev) => ({ ...prev, [name]: body }));
    } catch {
      // Detail failures are non-fatal — the row stays expanded
      // showing the rollup counts but no page list. Refresh
      // recovers it next time.
    }
  }, [details]);

  const onToggleExpand = (name: string) => {
    if (expanded === name) {
      setExpanded(null);
      return;
    }
    setExpanded(name);
    void loadDetail(name);
  };

  const openPage = (page: Page, fromProject: string) => {
    // Use path as both id + path. The editor's data.json lookup
    // benefits from the canonical id, but it falls back to the
    // raw path which is what we want here — the projects scan
    // doesn't carry CE's slug-based ids.
    setBreadcrumb({ path: page.path, project: fromProject });
    setSelection({ kind: "page", id: page.path, path: page.path });
    switchToKind("markdown");
  };

  const openHomePage = (proj: ProjectSummary) => {
    if (!proj.home_page) return;
    const wikiPath = proj.home_page.startsWith("wiki/")
      ? proj.home_page
      : `wiki/${proj.home_page}`;
    setBreadcrumb({ path: wikiPath, project: proj.name });
    setSelection({ kind: "page", id: wikiPath, path: wikiPath });
    switchToKind("markdown");
  };

  // ── External focus: editor "← Project" back-link or any other
  // surface dispatches `sy:focus-project` with `{project, path}` to
  // expand that project + scroll the row into view. We expand the
  // card immediately (and trigger the detail fetch); the highlight
  // path waits until the detail renders before scrolling.
  useEffect(() => {
    const onFocus = (ev: Event) => {
      const detail = (ev as CustomEvent).detail as { project?: string; path?: string } | undefined;
      const project = detail?.project;
      if (!project) return;
      setExpanded(project);
      void loadDetail(project);
      if (detail?.path) setHighlightPath(detail.path);
    };
    window.addEventListener("sy:focus-project", onFocus);
    return () => window.removeEventListener("sy:focus-project", onFocus);
  }, [loadDetail]);

  // Scroll-into-view + brief highlight, run after the matching row
  // is in the DOM (i.e. after the detail fetch completes and the
  // expand animation settles). Reset the highlight after it fires so
  // re-clicking the same back-link still triggers a new pulse.
  useEffect(() => {
    if (!highlightPath) return;
    if (!expanded || !details[expanded]) return;
    // Defer one frame so the just-rendered card body is laid out.
    const timer = window.setTimeout(() => {
      const root = rootRef.current;
      if (!root) return;
      const sel = `[data-project-page-path="${cssEscape(highlightPath)}"]`;
      const row = root.querySelector<HTMLElement>(sel);
      if (!row) return;
      row.scrollIntoView({ behavior: "smooth", block: "center" });
      row.classList.add("sy-projects-page-link--pulse");
      window.setTimeout(() => row.classList.remove("sy-projects-page-link--pulse"), 1600);
      setHighlightPath(null);
    }, 80);
    return () => window.clearTimeout(timer);
  }, [highlightPath, expanded, details]);

  const empty = !loading && items.length === 0;

  return (
    <div className="sy-projects-tab" ref={rootRef}>
      <header className="sy-projects-header">
        <h2>Projects</h2>
        <button
          type="button"
          className="sy-projects-refresh"
          onClick={() => void reload()}
          title="Refresh — re-scans wiki/ frontmatter and the .curator/projects.json registry"
        >
          ↻ refresh
        </button>
      </header>

      {error && (
        <div className="sy-projects-error">Failed to load projects: {error}</div>
      )}

      {!registryPresent && !empty && (
        <div className="sy-projects-hint">
          No <code>.curator/projects.json</code> in this workspace —
          the General card below holds untagged notes and todos.
          Run <code>projects.py create &lt;name&gt;</code> in CE
          (or the <code>/curate</code> button) to start tagging.
        </div>
      )}

      {empty && (
        <div className="sy-projects-empty">
          <p>No projects, no notes, and no todos in this workspace yet.</p>
          <p>
            Multi-project mode activates the moment you run{" "}
            <code>projects.py create &lt;name&gt;</code> in CE.
            Until then, the General card here will appear as soon as
            you add notes or todos to the wiki.
          </p>
        </div>
      )}

      <div className="sy-projects-grid">
        {items.map((p) => (
          <ProjectCard
            key={p.name}
            project={p}
            isOpen={expanded === p.name}
            detail={details[p.name]}
            onToggle={() => onToggleExpand(p.name)}
            onOpenHome={() => openHomePage(p)}
            onOpenPage={(page) => openPage(page, p.name)}
          />
        ))}
      </div>
    </div>
  );
}


type CardProps = {
  project: ProjectSummary;
  isOpen: boolean;
  detail: DetailResponse | undefined;
  onToggle: () => void;
  onOpenHome: () => void;
  onOpenPage: (p: Page) => void;
};

function ProjectCard({
  project, isOpen, detail, onToggle, onOpenHome, onOpenPage,
}: CardProps) {
  const heading = project.title ?? project.name;
  const archivedClass = project.archived ? " sy-projects-card--archived" : "";
  const syntheticClass = project.synthetic ? " sy-projects-card--synthetic" : "";

  // Compose a one-liner subtitle from the kinds rollup so the card
  // tells the story without needing the user to expand it.
  const stats = useMemo(() => {
    const parts: string[] = [];
    if (project.kinds.notes) parts.push(`${project.kinds.notes} note${project.kinds.notes === 1 ? "" : "s"}`);
    if (project.kinds.todos) parts.push(`${project.kinds.todos} todo${project.kinds.todos === 1 ? "" : "s"}`);
    if (project.kinds.other) parts.push(`${project.kinds.other} other`);
    return parts.join(" · ") || "no pages yet";
  }, [project.kinds]);

  return (
    <div className={`sy-projects-card${archivedClass}${syntheticClass}`}>
      <div
        className="sy-projects-card-head"
        role="button"
        tabIndex={0}
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggle();
          }
        }}
      >
        <div className="sy-projects-card-title">
          <span className="sy-projects-card-name">{heading}</span>
          {project.archived && (
            <span className="sy-projects-chip sy-projects-chip--archived">archived</span>
          )}
          {project.synthetic && (
            <span className="sy-projects-chip sy-projects-chip--synthetic">untagged</span>
          )}
        </div>
        <span className="sy-projects-card-stats">{stats}</span>
      </div>

      {project.description && (
        <p className="sy-projects-card-desc">{project.description}</p>
      )}

      <div className="sy-projects-card-actions">
        {project.home_page && (
          <button
            type="button"
            className="sy-projects-action"
            onClick={(e) => { e.stopPropagation(); onOpenHome(); }}
            title="Open this project's home page in the Editor"
          >
            ↗ home
          </button>
        )}
        <button
          type="button"
          className="sy-projects-action"
          onClick={onToggle}
        >
          {isOpen ? "− collapse" : `+ expand (${project.member_count})`}
        </button>
      </div>

      {isOpen && (
        <div className="sy-projects-card-body">
          {!detail ? (
            <p className="sy-projects-loading">loading…</p>
          ) : (
            <>
              <PageBucket label="Notes" pages={detail.kinds.notes} onOpen={onOpenPage} />
              <PageBucket label="Todos" pages={detail.kinds.todos} onOpen={onOpenPage} />
              <PageBucket label="Other" pages={detail.kinds.other} onOpen={onOpenPage} />
              {detail.log.length > 0 && (
                <details className="sy-projects-log">
                  <summary>Curator log ({detail.log.length})</summary>
                  <ul>
                    {detail.log.map((line, i) => (
                      <li key={i}><code>{line}</code></li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}


function PageBucket({ label, pages, onOpen }: {
  label: string;
  pages: Page[];
  onOpen: (p: Page) => void;
}) {
  if (pages.length === 0) return null;
  return (
    <div className="sy-projects-bucket">
      <h4>{label} <span className="sy-projects-bucket-count">{pages.length}</span></h4>
      <ul className="sy-projects-bucket-list">
        {pages.map((p) => (
          <li key={p.path}>
            <button
              type="button"
              className="sy-projects-page-link"
              data-project-page-path={p.path}
              onClick={() => onOpen(p)}
              title={p.path}
            >
              <span className={`sy-projects-page-type sy-projects-page-type--${p.type}`}>{p.type}</span>
              <span className="sy-projects-page-title">{p.title}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Suppress unused imports
void GENERAL;


/**
 * Tiny CSS-attribute-value escaper. Workspace paths can contain
 * characters CSS selectors don't tolerate raw (quotes, backslashes).
 * `CSS.escape` exists in modern browsers but only handles
 * identifiers — for attribute-VALUE escaping we just neutralise the
 * two characters that break a `[attr="…"]` selector.
 */
function cssEscape(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}
