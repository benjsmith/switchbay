/**
 * App-level side-effect imports for the forked CE wiki-view.
 *
 * Importing this file once (from App.tsx) ensures:
 *   1. d3 + Fuse are exposed on window before CE IIFEs evaluate.
 *   2. ce-graph.css is injected (sidebar + modal styling).
 *   3. window.Sidebar / Subgraph / Modal / Graph are populated.
 *
 * The Sidebar lives in the Browser column (Sidebar.tsx) and is
 * initialised as soon as the graph data arrives; the modal/graph live
 * in the graph tab and are initialised on tab mount (mountGraph in
 * init.ts).
 *
 * ES module spec guarantees side-effect imports run in declaration
 * order within a file, so init-globals runs before the IIFEs.
 */

import "./init-globals";
import "./ce-graph.css";
import "./static/sidebar.js";
import "./static/subgraph.js";
import "./static/modal.js";
import "./static/edit.js";
import "./static/graph.js";
import "./static/vendor/knowledge-atlas.js";
