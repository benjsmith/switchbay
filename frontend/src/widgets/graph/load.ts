/**
 * Side-effect imports for the forked CE wiki-view used by the VS Code
 * graph webview (src/webview-graph.ts). The PWA does not import this —
 * its Graph tab is Curiosity Engine's own viewer through /embed/ce.
 *
 * Importing this file once ensures:
 *   1. d3 + Fuse are exposed on window before CE IIFEs evaluate.
 *   2. palette.css + ce-graph.css are injected.
 *   3. window.Subgraph / Modal / Graph are populated.
 *
 * ES module spec guarantees side-effect imports run in declaration
 * order within a file, so init-globals runs before the IIFEs.
 */

import "./init-globals";
import "../../palette.css";
import "./ce-graph.css";
import "./static/subgraph.js";
import "./static/modal.js";
import "./static/graph.js";
import "./static/vendor/knowledge-atlas.js";
