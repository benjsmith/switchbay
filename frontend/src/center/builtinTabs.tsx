import { lazy } from "react";
import SketchErrorBoundary from "../widgets/sketch/ErrorBoundary";
import { registerTabKind, type TabComponent } from "./tabRegistry";

/**
 * Wire each built-in tab kind into the registry. Called once from
 * the App boot path before <TabStrip /> renders. Pack-loaded tab
 * kinds register themselves later via the same `registerTabKind`
 * API.
 *
 * Tab components are React.lazy so a cold PWA start doesn't pull every
 * tab's module (graph/d3, editor/marked, report, …) into the initial
 * chunk — each loads when its tab first opens. (The heavy LIBS inside
 * them — Excalidraw, Univer, vega, duckdb-wasm — were already split via
 * dynamic import; this splits the component modules too.) The render
 * sites (TabStrip, ZenSurfaceHost) wrap in <Suspense>.
 *
 * Some built-ins ignore most of their TabContext (no graph data, no
 * tab spec details) — we wrap those in tiny shims so the registry
 * entries can keep a uniform `(ctx) => JSX` shape.
 */

const GraphTab = lazy(() => import("../widgets/graph/GraphTab"));
const EditorTab = lazy(() => import("../widgets/editor/EditorTab"));
const DuckDBTab = lazy(() => import("../widgets/duckdb/DuckDBTab"));
const SheetTab = lazy(() => import("../widgets/sheet/SheetTab"));
const VegaTab = lazy(() => import("../widgets/vega/VegaTab"));
const SketchTab = lazy(() => import("../widgets/sketch/SketchTab"));
const AgentDashboardTab = lazy(() => import("../widgets/agents/AgentDashboardTab"));
const ProjectsTab = lazy(() => import("../widgets/projects/ProjectsTab"));
const PackFileListTab = lazy(() => import("../widgets/packtabs/PackFileListTab"));
const TerminalTab = lazy(() => import("../widgets/terminal/TerminalTab"));
const ReportTab = lazy(() => import("../widgets/report/ReportTab"));
const IntroTab = lazy(() => import("../widgets/intro/IntroTab"));
const HtmlDeckTab = lazy(() => import("../widgets/htmldeck/HtmlDeckTab"));
const LibraryTab = lazy(() => import("../widgets/library/LibraryTab"));
const ReportDocTab = lazy(() => import("../widgets/library/ReportDocTab"));
const ThrustersTab = lazy(() => import("../widgets/thrusters/ThrustersTab"));
const OwidTab = lazy(() => import("../widgets/owid/OwidTab"));

const GraphAdapter: TabComponent = ({ graphData, graphError }) => (
  <GraphTab data={graphData} error={graphError} />
);
const EditorAdapter: TabComponent = () => <EditorTab />;
const DuckDBAdapter: TabComponent = () => <DuckDBTab />;
const SheetAdapter: TabComponent = () => <SheetTab />;
const VegaAdapter: TabComponent = () => <VegaTab />;
const SketchAdapter: TabComponent = () => (
  <SketchErrorBoundary><SketchTab /></SketchErrorBoundary>
);
const AgentsAdapter: TabComponent = () => <AgentDashboardTab />;
const ProjectsAdapter: TabComponent = () => <ProjectsTab />;
const PackFileListAdapter: TabComponent = ({ tab }) => <PackFileListTab tab={tab} />;


let installed = false;


export function registerBuiltinTabs(): void {
  if (installed) return;
  installed = true;
  registerTabKind("graph", GraphAdapter, { bare: true });
  registerTabKind("markdown", EditorAdapter, { bare: true });
  registerTabKind("duckdb", DuckDBAdapter, { bare: true });
  registerTabKind("univer", SheetAdapter, { bare: true });
  registerTabKind("vega", VegaAdapter, { bare: true });
  // Sketch tab merges Excalidraw + drawio under one kind. The
  // per-sketch sub-kind (`excalidraw` vs `drawio`) lives inside
  // each sketch's record, not the tab's kind.
  registerTabKind("sketch", SketchAdapter, { bare: true });
  registerTabKind("library", (() => <LibraryTab />) as TabComponent, {
    bare: true,
  });
  registerTabKind("projects", ProjectsAdapter);
  registerTabKind("agents", AgentsAdapter);
  // Rich HTML report (create_report) in a sandboxed iframe.
  registerTabKind("report", (() => <ReportTab />) as TabComponent, { bare: true });
  // Durable report package (reports/<slug>/).
  registerTabKind("report-doc", (() => <ReportDocTab />) as TabComponent, {
    bare: true,
  });
  // Intro deck (intro_and_bench.html) in a sandboxed iframe. Seeded
  // pinned-first on first install; reopen with /intro.
  registerTabKind("intro", (() => <IntroTab />) as TabComponent, { bare: true });
  // Workspace HTML presentation decks (slideshows/<slug>/) — sandboxed iframe.
  registerTabKind("html-deck", (() => <HtmlDeckTab />) as TabComponent, {
    bare: true,
  });
  // Mars Hopper easter egg (Settings → "fire thrusters?"). Vendored
  // static game in a sandboxed iframe — not an external page.
  registerTabKind("thrusters", (() => <ThrustersTab />) as TabComponent, {
    bare: true,
  });
  // OWID pack browse tab (Our World in Data → import → plot).
  registerTabKind("owid", (() => <OwidTab />) as TabComponent, { bare: true });
  // Generic pack-supplied file-browser tab kind. Packs (e.g.
  // libreoffice → Slides / Docs / Sheets) declare `kind:
  // "pack.file-list"` with a payload of extensions + a route
  // action; the component lists matching workspace files and runs
  // the route on click.
  registerTabKind("pack.file-list", PackFileListAdapter, { bare: true });
  // Popped-out terminals (user tabs created by the rail's ⇱ button;
  // never in DEFAULT_MODE). Needs the full ctx for termWs.
  registerTabKind("terminal", TerminalTab, { bare: true });
}
