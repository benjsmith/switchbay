/**
 * Expose d3 + Fuse on `window` so the forked CE modules (which expect
 * them as globals from `<script>` tags in the original viewer) can find
 * them when their IIFEs run.
 *
 * This file is imported BEFORE any `./static/*.js` to guarantee load
 * order — see init.ts.
 */

import * as d3 from "d3";
import Fuse from "fuse.js";
import katex from "katex";
import "katex/dist/katex.min.css";
// KaTeX's auto-render module ships without TS types; declare it
// inline so the import is callable. Signature is `(elem, opts)`.
// @ts-expect-error — missing .d.ts; module exports a function
import renderMathInElement from "katex/contrib/auto-render";

// CE modules access `d3.forceSimulation(...)`, `d3.zoom()`, etc.
(window as unknown as { d3: typeof d3 }).d3 = d3;
(window as unknown as { Fuse: typeof Fuse }).Fuse = Fuse;
// KaTeX needs to be reachable from the vanilla-JS modal so it can
// render math in the doc body after CE's wiki_render hands us
// plain HTML. The CE renderer doesn't emit MathML / SVG — the math
// arrives as raw `$...$` text. We post-process the DOM.
(window as unknown as { katex: typeof katex }).katex = katex;
(window as unknown as {
  renderMathInElement: typeof renderMathInElement;
}).renderMathInElement = renderMathInElement;
