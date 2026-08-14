# Third-party notices

Switch Bay bundles and builds on the open-source software listed below.
Each package remains under its own license; this file reproduces the
required attributions. Generated from the frontend production dependency
tree (`pnpm licenses list --prod`) and the Python runtime environment.
Regenerate after dependency changes.

See also **[`docs/license-risk-report.md`](license-risk-report.md)** for the
risk analysis behind these notices.

## License elections (dual-licensed dependencies)

Where a dependency offers a choice of license, Switch Bay elects the
permissive option:

| Package | Offered | Switch Bay elects |
|---------|---------|-------------------|
| `dompurify` | MPL-2.0 OR Apache-2.0 | **Apache-2.0** |
| `jszip` | MIT OR GPL-3.0-or-later | **MIT** |
| `packaging` (Python) | Apache-2.0 OR BSD-2-Clause | **Apache-2.0** |

`certifi` and `tqdm` (Python) are MPL-2.0 (file-level weak copyleft); no
obligation arises as we do not modify their files.

## First-party code derived from open source

- **Graph / wiki-view** (`frontend/src/widgets/graph/static/*.js`) is a
  fork of **curiosity-engine**'s wiki-view, used under the **MIT License**
  (Copyright (c) 2026, curiosity-engine authors). Full MIT text below.
- **Knowledge Atlas** (`frontend/src/widgets/graph/static/vendor/knowledge-atlas.js`)
  is the first-party IIFE from curiosity-engine's `packages/knowledge-atlas`,
  same MIT license.
- **`createUniver`** in `frontend/src/widgets/sheet/SheetTab.tsx` is a
  ~15-line reimplementation of the same function from **@univerjs/presets**
  (**Apache-2.0**, Copyright (c) DreamNum Inc.), inlined so Switch Bay
  depends only on the granular Apache-2.0 Univer packages and never pulls
  the proprietary `@univerjs-pro/*` tier. Full Apache-2.0 notice below.

## Frontend dependencies (production)

461 packages. Grouped by SPDX license.

### MIT (305)

- `@antfu/install-pkg`@1.1.0 — Anthony Fu
- `@babel/runtime`@7.29.2 — The Babel Team
- `@braintree/sanitize-url`@6.0.2,7.1.2
- `@codemirror/autocomplete`@6.20.2 — Marijn Haverbeke
- `@codemirror/commands`@6.10.3 — Marijn Haverbeke
- `@codemirror/lang-css`@6.3.1 — Marijn Haverbeke
- `@codemirror/lang-go`@6.0.1 — Marijn Haverbeke
- `@codemirror/lang-html`@6.4.11 — Marijn Haverbeke
- `@codemirror/lang-javascript`@6.2.5 — Marijn Haverbeke
- `@codemirror/lang-json`@6.0.2 — Marijn Haverbeke
- `@codemirror/lang-python`@6.2.1 — Marijn Haverbeke
- `@codemirror/lang-rust`@6.0.2 — Marijn Haverbeke
- `@codemirror/language`@6.12.3 — Marijn Haverbeke
- `@codemirror/legacy-modes`@6.5.2 — Marijn Haverbeke
- `@codemirror/lint`@6.9.6 — Marijn Haverbeke
- `@codemirror/search`@6.7.0 — Marijn Haverbeke
- `@codemirror/state`@6.6.0 — Marijn Haverbeke
- `@codemirror/view`@6.42.1 — Marijn Haverbeke
- `@duckdb/duckdb-wasm`@1.33.1-dev45.0
- `@excalidraw/excalidraw`@0.18.1
- `@excalidraw/laser-pointer`@1.3.1
- `@excalidraw/markdown-to-text`@0.1.2 — Daniel Esteves
- `@excalidraw/mermaid-to-excalidraw`@2.2.2
- `@excalidraw/random-username`@1.1.0 — dwelle
- `@flatten-js/interval-tree`@1.1.3 — Alex Bol
- `@floating-ui/core`@1.7.5 — atomiks
- `@floating-ui/dom`@1.7.6 — atomiks
- `@floating-ui/react-dom`@2.1.8 — atomiks
- `@floating-ui/utils`@0.2.11 — atomiks
- `@iconify/types`@2.0.0 — Vjacheslav Trushkin
- `@iconify/utils`@3.1.1 — Vjacheslav Trushkin
- `@js-sdsl/ordered-map`@4.4.2 — ZLY201
- `@lezer/common`@1.5.2 — Marijn Haverbeke
- `@lezer/css`@1.3.3 — Marijn Haverbeke
- `@lezer/go`@1.0.1 — Marijn Haverbeke
- `@lezer/highlight`@1.2.3 — Marijn Haverbeke
- `@lezer/html`@1.3.13 — Marijn Haverbeke
- `@lezer/javascript`@1.5.4 — Marijn Haverbeke
- `@lezer/json`@1.0.3 — Arun Srinivasan
- `@lezer/lr`@1.4.10 — Marijn Haverbeke
- `@lezer/python`@1.1.18 — Marijn Haverbeke
- `@lezer/rust`@1.0.2 — Marijn Haverbeke
- `@marijn/find-cluster-break`@1.0.2 — Marijn Haverbeke
- `@mermaid-js/parser`@0.6.3,1.1.0 — Yokozuna59
- `@radix-ui/primitive`@1.0.0,1.1.1,1.1.3
- `@radix-ui/react-arrow`@1.1.2,1.1.7
- `@radix-ui/react-collection`@1.0.1,1.1.7
- `@radix-ui/react-compose-refs`@1.0.0,1.1.1,1.1.2
- `@radix-ui/react-context`@1.0.0,1.1.1,1.1.2
- `@radix-ui/react-dialog`@1.1.15
- `@radix-ui/react-direction`@1.0.0,1.1.1
- `@radix-ui/react-dismissable-layer`@1.1.5,1.1.11
- `@radix-ui/react-dropdown-menu`@2.1.16
- `@radix-ui/react-focus-guards`@1.1.1,1.1.3
- `@radix-ui/react-focus-scope`@1.1.2,1.1.7
- `@radix-ui/react-hover-card`@1.1.15
- `@radix-ui/react-id`@1.0.0,1.1.0,1.1.1
- `@radix-ui/react-menu`@2.1.16
- `@radix-ui/react-popover`@1.1.6,1.1.15
- `@radix-ui/react-popper`@1.2.2,1.2.8
- `@radix-ui/react-portal`@1.1.4,1.1.9
- `@radix-ui/react-presence`@1.0.0,1.1.2,1.1.5
- `@radix-ui/react-primitive`@1.0.1,2.0.2,2.1.3,2.1.4
- `@radix-ui/react-roving-focus`@1.0.2,1.1.11
- `@radix-ui/react-separator`@1.1.8
- `@radix-ui/react-slot`@1.0.1,1.1.2,1.2.3,1.2.4
- `@radix-ui/react-tabs`@1.0.2
- `@radix-ui/react-use-callback-ref`@1.0.0,1.1.0,1.1.1
- `@radix-ui/react-use-controllable-state`@1.0.0,1.1.0,1.2.2
- `@radix-ui/react-use-effect-event`@0.0.2
- `@radix-ui/react-use-escape-keydown`@1.1.0,1.1.1
- `@radix-ui/react-use-layout-effect`@1.0.0,1.1.0,1.1.1
- `@radix-ui/react-use-rect`@1.1.0,1.1.1
- `@radix-ui/react-use-size`@1.1.0,1.1.1
- `@radix-ui/rect`@1.1.0,1.1.1
- `@types/command-line-args`@5.2.3
- `@types/command-line-usage`@5.0.4
- `@types/d3`@7.4.3
- `@types/d3-array`@3.2.2
- `@types/d3-axis`@3.0.6
- `@types/d3-brush`@3.0.6
- `@types/d3-chord`@3.0.6
- `@types/d3-color`@3.1.3
- `@types/d3-contour`@3.0.6
- `@types/d3-delaunay`@6.0.4
- `@types/d3-dispatch`@3.0.7
- `@types/d3-drag`@3.0.7
- `@types/d3-dsv`@3.0.7
- `@types/d3-ease`@3.0.2
- `@types/d3-fetch`@3.0.7
- `@types/d3-force`@3.0.10
- `@types/d3-format`@3.0.4
- `@types/d3-geo`@3.1.0
- `@types/d3-hierarchy`@3.1.7
- `@types/d3-interpolate`@3.0.4
- `@types/d3-path`@3.1.1
- `@types/d3-polygon`@3.0.2
- `@types/d3-quadtree`@3.0.6
- `@types/d3-random`@3.0.3
- `@types/d3-scale`@4.0.9
- `@types/d3-scale-chromatic`@3.1.0
- `@types/d3-selection`@3.0.11
- `@types/d3-shape`@3.1.8
- `@types/d3-time`@3.0.4
- `@types/d3-time-format`@4.0.3
- `@types/d3-timer`@3.0.2
- `@types/d3-transition`@3.0.9
- `@types/d3-zoom`@3.0.8
- `@types/estree`@1.0.8
- `@types/geojson`@7946.0.16
- `@types/node`@20.19.39,24.12.2
- `@types/prop-types`@15.7.15
- `@types/react`@18.3.28
- `@types/react-dom`@18.3.7
- `@types/trusted-types`@2.0.7
- `@univerjs/icons`@1.1.1 — DreamNum Co., Ltd.
- `@upsetjs/venn.js`@2.0.0 — Ben Frederickson
- `@wendellhu/redi`@1.1.1 — Evan
- `@xmldom/xmldom`@0.8.13
- `@xterm/addon-fit`@0.11.0 — The xterm.js authors
- `@xterm/addon-webgl`@0.19.0 — The xterm.js authors
- `@xterm/xterm`@6.0.0
- `acorn`@8.16.0
- `ansi-regex`@5.0.1,6.2.2 — Sindre Sorhus
- `ansi-styles`@4.3.0,6.2.3 — Sindre Sorhus
- `argparse`@1.0.10
- `aria-hidden`@1.2.6 — Anton Korzunov
- `array-back`@3.1.0,6.2.3 — Lloyd Brookes
- `async-lock`@1.4.1 — Rogier Schouten
- `base64-js`@1.5.1 — T. Jameson Little
- `binary-extensions`@2.3.0 — Sindre Sorhus
- `bluebird`@3.4.7 — Petka Antonov
- `braces`@3.0.3 — Jon Schlinkert
- `call-bind-apply-helpers`@1.0.2 — Jordan Harband
- `call-bound`@1.0.4 — Jordan Harband
- `canvas-roundrect-polyfill`@0.0.1
- `chalk`@4.1.2
- `chalk-template`@0.4.0
- `chevrotain-allstar`@0.3.1,0.4.3 — TypeFox
- `chokidar`@3.6.0 — Paul Miller
- `cjk-regex`@3.4.0 — Ika
- `clsx`@1.1.1,2.1.1 — Luke Edwards
- `codemirror`@6.0.2 — Marijn Haverbeke
- `collapse-white-space`@2.1.0 — Titus Wormer
- `color-convert`@2.0.1 — Heather Arthur
- `color-name`@1.1.4 — DY
- `command-line-args`@5.2.1,6.0.2 — Lloyd Brookes
- `command-line-usage`@7.0.4 — Lloyd Brookes
- `commander`@2.20.3,7.2.0,8.3.0 — TJ Holowaychuk
- `confbox`@0.1.8
- `core-util-is`@1.0.3 — Isaac Z. Schlueter
- `cose-base`@1.0.3,2.2.0
- `crelt`@1.0.6 — Marijn Haverbeke
- `cross-env`@7.0.3 — Kent C. Dodds
- `cross-spawn`@7.0.6 — André Cruz
- `csstype`@3.2.3 — Fredrik Nicol
- `cytoscape`@3.33.3
- `cytoscape-cose-bilkent`@4.1.0
- `cytoscape-fcose`@2.2.0 — iVis-at-Bilkent
- `dagre-d3-es`@7.0.14
- `dayjs`@1.11.20 — iamkun
- `decimal.js`@10.6.0 — Michael Mclaughlin
- `detect-node-es`@1.1.0 — Ilya Kantor
- `dom-helpers`@5.2.1 — Jason Quense
- `dunder-proto`@1.0.1 — Jordan Harband
- `emoji-regex`@8.0.0,10.6.0 — Mathias Bynens
- `es-define-property`@1.0.1 — Jordan Harband
- `es-errors`@1.3.0 — Jordan Harband
- `es-object-atoms`@1.1.1 — Jordan Harband
- `es6-promise-pool`@2.5.0 — Tim De Pauw
- `escalade`@3.2.0 — Luke Edwards
- `fast-json-patch`@3.1.1 — Joachim Wester
- `fill-range`@7.1.1 — Jon Schlinkert
- `find-replace`@3.0.0,5.0.2 — Lloyd Brookes
- `franc-min`@6.2.0 — Titus Wormer
- `fsevents`@2.3.3
- `function-bind`@1.1.2 — Raynos
- `fuzzy`@0.1.3 — Matt York
- `get-east-asian-width`@1.5.0 — Sindre Sorhus
- `get-intrinsic`@1.3.0 — Jordan Harband
- `get-nonce`@1.0.1 — Anton Korzunov
- `get-proto`@1.0.1 — Jordan Harband
- `glur`@1.1.2
- `gopd`@1.2.0 — Jordan Harband
- `hachure-fill`@0.5.2 — Preet Shihn
- `has-flag`@4.0.0 — Sindre Sorhus
- `has-symbols`@1.1.0 — Jordan Harband
- `hasown`@2.0.3 — Jordan Harband
- `iconv-lite`@0.6.3 — Alexander Shtuchkin
- `image-blob-reduce`@3.0.1
- `immediate`@3.0.6
- `immutable`@4.3.8 — Lee Byron
- `is-binary-path`@2.1.0 — Sindre Sorhus
- `is-extglob`@2.1.1 — Jon Schlinkert
- `is-fullwidth-code-point`@3.0.0 — Sindre Sorhus
- `is-glob`@4.0.3 — Jon Schlinkert
- `is-number`@7.0.0 — Jon Schlinkert
- `isarray`@1.0.0 — Julian Gruber
- `jotai`@2.11.0 — Daishi Kato
- `jotai-scope`@0.7.2 — Daishi Kato
- `js-tokens`@4.0.0 — Simon Lydell
- `json-bignum`@0.0.3 — Datalanche, Inc.
- `json-stringify-pretty-compact`@4.0.0 — Simon Lydell
- `katex`@0.16.46
- `langium`@3.3.1,4.2.3 — TypeFox
- `layout-base`@1.0.2,2.0.1
- `lie`@3.1.1,3.3.0
- `lodash-es`@4.17.21,4.18.1 — John-David Dalton
- `lodash.camelcase`@4.3.0 — John-David Dalton
- `lodash.debounce`@4.0.8 — John-David Dalton
- `lodash.throttle`@4.1.1 — John-David Dalton
- `loose-envify`@1.4.0 — Andres Suarez
- `marked`@16.4.2,18.0.2 — Christopher Jeffrey
- `math-intrinsics`@1.1.0 — Jordan Harband
- `mermaid`@11.14.0 — Knut Sveidqvist
- `mlly`@1.8.2
- `multimath`@2.0.0
- `n-gram`@2.0.2 — Titus Wormer
- `nanoid`@3.3.3,4.0.2,5.1.9 — Andrey Sitnik
- `normalize-path`@3.0.0 — Jon Schlinkert
- `numfmt`@3.2.6 — Borgar Þorsteinsson
- `object-assign`@4.1.1 — Sindre Sorhus
- `object-inspect`@1.13.4 — James Halliday
- `open-color`@1.9.1 — Jeong Heeyeun
- `opentype.js`@1.3.4 — Frederik De Bleser
- `package-manager-detector`@1.6.0 — Anthony Fu
- `path-data-parser`@0.1.0 — Preet Shihn
- `path-is-absolute`@1.0.1 — Sindre Sorhus
- `path-key`@3.1.1 — Sindre Sorhus
- `pathe`@2.0.3
- `perfect-freehand`@1.2.0 — Steve Ruiz
- `pica`@7.1.1
- `picomatch`@2.3.2 — Jon Schlinkert
- `pkg-types`@1.3.1
- `png-chunk-text`@1.0.0 — Hugh Kennedy
- `png-chunks-encode`@1.0.0 — Hugh Kennedy
- `png-chunks-extract`@1.0.0 — Hugh Kennedy
- `points-on-curve`@0.2.0,1.0.1 — Preet Shihn
- `points-on-path`@0.2.1 — Preet Shihn
- `process-nextick-args`@2.0.1
- `prop-types`@15.8.1
- `rbush`@4.0.1 — Volodymyr Agafonkin
- `react`@18.3.1
- `react-dom`@18.3.1
- `react-is`@16.13.1
- `react-remove-scroll`@2.7.2 — Anton Korzunov
- `react-remove-scroll-bar`@2.3.8 — Anton Korzunov
- `react-style-singleton`@2.2.3 — Anton Korzunov
- `readable-stream`@2.3.8
- `readdirp`@3.6.0 — Thorsten Lorenz
- `regexp-util`@2.0.3 — Ika
- `require-directory`@2.1.1 — Troy Goode
- `roughjs`@4.6.4,4.6.6 — Preet Shihn
- `safe-buffer`@5.1.2 — Feross Aboukhadijeh
- `safer-buffer`@2.1.2 — Nikita Skovoroda
- `sass`@1.51.0 — Natalie Weizenbaum
- `scheduler`@0.23.2
- `setimmediate`@1.0.5 — YuzuJS
- `shebang-command`@2.0.0 — Kevin Mårtensson
- `shebang-regex`@3.0.0 — Sindre Sorhus
- `side-channel`@1.1.0 — Jordan Harband
- `side-channel-list`@1.0.1 — Jordan Harband
- `side-channel-map`@1.0.1 — Jordan Harband
- `side-channel-weakmap`@1.0.2 — Jordan Harband
- `sliced`@1.0.1 — Aaron Heckmann
- `sonner`@2.0.7 — Emil Kowalski
- `string-width`@4.2.3,7.2.0 — Sindre Sorhus
- `string.prototype.codepointat`@0.2.1 — Mathias Bynens
- `string_decoder`@1.1.1
- `strip-ansi`@6.0.1,7.2.0 — Sindre Sorhus
- `style-mod`@4.1.3 — Marijn Haverbeke
- `stylis`@4.4.0 — Sultan Tarimo
- `supports-color`@7.2.0 — Sindre Sorhus
- `table-layout`@4.1.1 — Lloyd Brookes
- `tailwind-merge`@2.6.0 — Dany Castillo
- `tiny-inflate`@1.0.3 — Devon Govett
- `tinyexec`@1.1.2 — James Garbutt
- `to-regex-range`@5.0.1 — Jon Schlinkert
- `trigram-utils`@2.0.1 — Titus Wormer
- `ts-dedent`@2.2.0 — Tamino Martinius
- `tunnel-rat`@0.1.2 — Paul Henschel
- `turndown`@7.2.3 — Dom Christie
- `typical`@4.0.0,7.3.0 — Lloyd Brookes
- `ufo`@1.6.4
- `underscore`@1.13.8 — Jeremy Ashkenas
- `undici-types`@6.21.0,7.16.0
- `unicode-regex`@4.2.0 — Ika
- `use-callback-ref`@1.3.3 — theKashey
- `use-sidecar`@1.1.3 — theKashey
- `use-sync-external-store`@1.6.0
- `util-deprecate`@1.0.2 — Nathan Rajlich
- `uuid`@11.1.1
- `vscode-jsonrpc`@8.2.0 — Microsoft Corporation
- `vscode-languageserver`@9.0.1 — Microsoft Corporation
- `vscode-languageserver-protocol`@3.17.5 — Microsoft Corporation
- `vscode-languageserver-textdocument`@1.0.12 — Microsoft Corporation
- `vscode-languageserver-types`@3.17.5 — Microsoft Corporation
- `vscode-uri`@3.0.8,3.1.0 — Microsoft
- `w3c-keyname`@2.2.8 — Marijn Haverbeke
- `webworkify`@1.5.0 — James Halliday
- `wordwrapjs`@5.1.1 — Lloyd Brookes
- `wrap-ansi`@7.0.0,9.0.2 — Sindre Sorhus
- `xmlbuilder`@10.1.1 — Ozgur Ozcitak
- `yargs`@17.7.2,18.0.0
- `zustand`@4.5.7 — Paul Henschel

### BSD-3-Clause (57)

- `@protobufjs/aspromise`@1.1.2 — Daniel Wirtz
- `@protobufjs/base64`@1.1.2 — Daniel Wirtz
- `@protobufjs/codegen`@2.0.5 — Daniel Wirtz
- `@protobufjs/eventemitter`@1.1.0 — Daniel Wirtz
- `@protobufjs/fetch`@1.1.0 — Daniel Wirtz
- `@protobufjs/float`@1.0.2 — Daniel Wirtz
- `@protobufjs/inquire`@1.1.1 — Daniel Wirtz
- `@protobufjs/path`@1.1.2 — Daniel Wirtz
- `@protobufjs/pool`@1.1.0 — Daniel Wirtz
- `@protobufjs/utf8`@1.1.1 — Daniel Wirtz
- `d3-array`@2.12.1 — Mike Bostock
- `d3-ease`@3.0.1 — Mike Bostock
- `d3-path`@1.0.9 — Mike Bostock
- `d3-sankey`@0.12.3 — Mike Bostock
- `d3-shape`@1.3.7 — Mike Bostock
- `protobufjs`@7.5.6 — Daniel Wirtz
- `qs`@6.15.1
- `react-transition-group`@4.4.5
- `rw`@1.3.3 — Mike Bostock
- `source-map-js`@1.2.1 — Valentin 7rulnik Semirulnik
- `sprintf-js`@1.0.3 — Alexandru Marasteanu
- `vega`@6.2.0 — Vega
- `vega-canvas`@2.0.0 — Vega
- `vega-crossfilter`@5.1.0 — Vega
- `vega-dataflow`@6.1.0 — Vega
- `vega-embed`@7.1.0 — Vega
- `vega-encode`@5.1.0 — Vega
- `vega-event-selector`@4.0.0 — Vega
- `vega-expression`@6.1.0 — Vega
- `vega-force`@5.1.0 — Vega
- `vega-format`@2.1.0 — Vega
- `vega-functions`@6.1.1 — Vega
- `vega-geo`@5.1.0 — Vega
- `vega-hierarchy`@5.1.0 — Vega
- `vega-interpreter`@2.2.1 — Vega
- `vega-label`@2.1.0 — UW Interactive Data Lab
- `vega-lite`@6.4.3 — Vega
- `vega-loader`@5.1.0 — Vega
- `vega-parser`@7.1.0 — Vega
- `vega-projection`@2.1.0 — Vega
- `vega-regression`@2.1.0 — Vega
- `vega-runtime`@7.1.0 — Vega
- `vega-scale`@8.1.0 — Vega
- `vega-scenegraph`@5.1.0 — Vega
- `vega-schema-url-parser`@3.0.2 — Dominik Moritz
- `vega-selections`@6.1.2 — Arvind Satyanarayan
- `vega-statistics`@2.0.0 — Vega
- `vega-themes`@3.0.0 — Vega
- `vega-time`@3.1.0 — Vega
- `vega-tooltip`@1.0.0 — Vega
- `vega-transforms`@5.1.0 — Vega
- `vega-typings`@2.1.0 — Vega
- `vega-util`@2.1.1 — Vega
- `vega-view`@6.1.0 — Vega
- `vega-view-transforms`@5.1.0 — Vega
- `vega-voronoi`@5.1.0 — Vega
- `vega-wordcloud`@5.1.0 — Vega

### ISC (46)

- `anymatch`@3.1.3 — Elan Shanker
- `cliui`@8.0.1,9.0.1 — Ben Coe
- `d3`@7.9.0 — Mike Bostock
- `d3-axis`@3.0.0 — Mike Bostock
- `d3-brush`@3.0.0 — Mike Bostock
- `d3-chord`@3.0.1 — Mike Bostock
- `d3-color`@3.1.0 — Mike Bostock
- `d3-contour`@4.0.2 — Mike Bostock
- `d3-delaunay`@6.0.4 — Mike Bostock
- `d3-dispatch`@3.0.1 — Mike Bostock
- `d3-drag`@3.0.0 — Mike Bostock
- `d3-dsv`@3.0.1 — Mike Bostock
- `d3-fetch`@3.0.1 — Mike Bostock
- `d3-force`@3.0.0 — Mike Bostock
- `d3-format`@3.1.2 — Mike Bostock
- `d3-geo`@3.1.1 — Mike Bostock
- `d3-geo-projection`@4.0.0 — Mike Bostock
- `d3-hierarchy`@3.1.2 — Mike Bostock
- `d3-interpolate`@3.0.1 — Mike Bostock
- `d3-polygon`@3.0.1 — Mike Bostock
- `d3-quadtree`@3.0.1 — Mike Bostock
- `d3-random`@3.0.1 — Mike Bostock
- `d3-scale`@4.0.2 — Mike Bostock
- `d3-scale-chromatic`@3.1.0 — Mike Bostock
- `d3-selection`@3.0.0 — Mike Bostock
- `d3-time`@3.1.0 — Mike Bostock
- `d3-time-format`@4.1.0 — Mike Bostock
- `d3-timer`@3.0.1 — Mike Bostock
- `d3-transition`@3.0.1 — Mike Bostock
- `d3-zoom`@3.0.0 — Mike Bostock
- `delaunator`@5.1.0 — Vladimir Agafonkin
- `get-caller-file`@2.0.5 — Stefan Penner
- `glob-parent`@5.1.2 — Gulp Team
- `inherits`@2.0.4
- `internmap`@1.0.1,2.0.3 — Mike Bostock
- `isexe`@2.0.0 — Isaac Z. Schlueter
- `kdbush`@4.0.2 — Vladimir Agafonkin
- `ot-json1`@1.0.2 — Joseph Gentle
- `ot-text-unicode`@4.0.0 — Joseph Gentle
- `quickselect`@3.0.0 — Vladimir Agafonkin
- `semver`@7.7.4 — GitHub Inc.
- `topojson-client`@3.1.0 — Mike Bostock
- `unicount`@1.1.0 — Joseph Gentle
- `which`@2.0.2 — Isaac Z. Schlueter
- `y18n`@5.0.8 — Ben Coe
- `yargs-parser`@21.1.1,22.0.0 — Ben Coe

### Apache-2.0 (39)

- `@chevrotain/cst-dts-gen`@11.0.3,12.0.0
- `@chevrotain/gast`@11.0.3,12.0.0
- `@chevrotain/regexp-to-ast`@11.0.3,12.0.0
- `@chevrotain/types`@11.0.3,12.0.0 — Shahar Soel
- `@chevrotain/utils`@11.0.3,12.0.0 — Shahar Soel
- `@grpc/grpc-js`@1.14.3 — Google Inc.
- `@grpc/proto-loader`@0.8.0 — Google Inc.
- `@swc/helpers`@0.5.21 — 강동윤
- `@univerjs/core`@0.21.1 — DreamNum
- `@univerjs/design`@0.21.1 — DreamNum
- `@univerjs/docs`@0.21.1 — DreamNum
- `@univerjs/docs-ui`@0.21.1 — DreamNum
- `@univerjs/drawing`@0.21.1 — DreamNum
- `@univerjs/engine-formula`@0.21.1 — DreamNum
- `@univerjs/engine-render`@0.21.1 — DreamNum
- `@univerjs/network`@0.21.1 — DreamNum
- `@univerjs/preset-sheets-core`@0.21.1 — DreamNum Co., Ltd.
- `@univerjs/protocol`@0.21.1 — DreamNum
- `@univerjs/rpc`@0.21.1 — DreamNum
- `@univerjs/sheets`@0.21.1 — DreamNum
- `@univerjs/sheets-formula`@0.21.1 — DreamNum
- `@univerjs/sheets-formula-ui`@0.21.1 — DreamNum
- `@univerjs/sheets-numfmt`@0.21.1 — DreamNum
- `@univerjs/sheets-numfmt-ui`@0.21.1 — DreamNum
- `@univerjs/sheets-ui`@0.21.1 — DreamNum
- `@univerjs/themes`@0.21.1 — DreamNum
- `@univerjs/ui`@0.21.1 — DreamNum
- `apache-arrow`@17.0.0,21.1.0 — Apache Software Foundation
- `browser-fs-access`@0.29.1 — Thomas Steiner
- `chevrotain`@11.0.3,12.0.0 — Shahar Soel
- `class-variance-authority`@0.7.1 — Joe Bell
- `crc-32`@0.3.0 — sheetjs
- `fast-diff`@1.3.0 — Jason Chen
- `flatbuffers`@24.12.23,25.9.23 — The FlatBuffers project
- `fuse.js`@7.3.0 — Kiro Risk
- `localforage`@1.10.0 — Mozilla
- `long`@5.3.2 — Daniel Wirtz
- `pwacompat`@2.0.17 — The Chromium Authors
- `rxjs`@7.8.2 — Ben Lesh

### BSD-2-Clause (5)

- `@mixmark-io/domino`@2.2.0 — Felix Gnass
- `dingbat-to-unicode`@1.0.1 — Michael Williamson
- `lop`@0.4.2 — Michael Williamson
- `mammoth`@1.12.0 — Michael Williamson
- `option`@0.2.4 — Michael Williamson

### Unknown (2) — resolved manually (npm metadata gaps)

- `@univerjs/telemetry`@0.21.1 — DreamNum — **Apache-2.0** (Univer
  monorepo package; the whole non-Pro monorepo is Apache-2.0)
- `khroma`@2.1.0 — **MIT** (upstream declares MIT; the registry metadata
  omits the field)

### (MIT AND Zlib) (1)

- `pako`@1.0.11,2.0.3

### (MIT OR GPL-3.0-or-later) (1)

- `jszip`@3.10.1 — Stuart Knightley

### (MPL-2.0 OR Apache-2.0) (1)

- `dompurify`@3.4.11 — Dr.-Ing. Mario Heiderich, Cure53

### 0BSD (1)

- `tslib`@2.8.1 — Microsoft Corp.

### BSD (1)

- `duck`@0.1.12 — Michael Williamson

### CC0-1.0 (1)

- `fractional-indexing`@3.2.0 — arv@rocicorp.dev

### Unlicense (1)

- `robust-predicates`@3.0.3 — Vladimir Agafonkin

## Optional Python dependencies (semantic embeddings)

Installed only with the opt-in `semantic` / `semantic-torch` dependency
groups (Tier-3 recall); the base install ships none of these. All
permissive:

- **fastembed** (`semantic`) — **Apache-2.0** (its PyPI *classifier*
  reads "Other/Proprietary" but the package's `License` field and
  bundled LICENSE file are Apache-2.0). Pulls **onnxruntime** (MIT),
  **tokenizers** (Apache-2.0), **huggingface-hub** (Apache-2.0),
  **loguru** (MIT), **mmh3** (MIT), **protobuf** (BSD-3-Clause),
  **flatbuffers** (Apache-2.0), **ml_dtypes** (Apache-2.0).
- **sentence-transformers** + **torch** (`semantic-torch`) — Apache-2.0
  / BSD-3-Clause and the usual PyTorch ML stack (all permissive:
  BSD/Apache/MIT). Only installed if you choose the byte-exact CE-interop
  backend.

Embedding **model weights** are downloaded at first use from Hugging Face
under their own licenses (e.g. `BAAI/bge-small-en-v1.5` — MIT;
`sentence-transformers/all-MiniLM-L6-v2` — Apache-2.0) and are not
redistributed by switchbay.

## Python runtime dependencies

45 packages in the daemon environment. Grouped by license.

### BSD-3-Clause (9)

- `MarkupSafe`@3.0.3
- `click`@8.3.2
- `fsspec`@2026.3.0
- `httpcore`@1.0.9
- `idna`@3.12
- `joblib`@1.5.3
- `networkx`@3.6.1
- `scikit-learn`@1.8.0
- `torch`@2.11.0

### MIT (8)

- `annotated-doc`@0.0.4
- `anyio`@4.13.0
- `filelock`@3.29.0
- `pip`@26.0.1
- `pysqlite3`@0.6.0
- `setuptools`@81.0.0
- `typer`@0.24.1
- `wheel`@0.46.3

### BSD License (6)

- `Jinja2`@3.1.6
- `httpx`@0.28.1
- `mpmath`@1.3.0
- `scipy`@1.17.1
- `sympy`@1.14.0
- `threadpoolctl`@3.6.0

### MIT License (5)

- `PyYAML`@6.0.3
- `h11`@0.16.0
- `markdown-it-py`@4.0.0
- `mdurl`@0.1.2
- `rich`@15.0.0

### Apache Software License (4)

- `huggingface_hub`@1.11.0
- `safetensors`@0.7.0
- `sentence-transformers`@5.4.1
- `tokenizers`@0.22.2

### Apache 2.0 License (1)

- `transformers`@5.5.4

### Apache-2.0 (1)

- `hf-xet`@1.4.3

### Apache-2.0 AND CNRI-Python (1)

- `regex`@2026.4.4

### Apache-2.0 OR BSD-2-Clause (1)

- `packaging`@26.1

### BSD-2-Clause (1)

- `Pygments`@2.20.0

### BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 (1)

- `numpy`@2.4.4

### BSD-3-Clause, Apache-2.0, dependency lic (1)

- `pypdfium2`@5.7.1

### ISC License (ISCL) (1)

- `shellingham`@1.5.4

### MIT License, Apache License, Version 2.0 (1)

- `sqlite-vec`@0.1.9

### MIT-CMU (1)

- `pillow`@12.2.0

### MPL-2.0 AND MIT (1)

- `tqdm`@4.67.3

### Mozilla Public License 2.0 (MPL 2.0) (1)

- `certifi`@2026.2.25

### PSF-2.0 (1)

- `typing_extensions`@4.15.0

---

## License texts

### MIT License

```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Apache License 2.0

The full text is at <https://www.apache.org/licenses/LICENSE-2.0>. Apache-2.0
dependencies (incl. `@univerjs/*`, `apache-arrow`, `@grpc/*`, `@chevrotain/*`,
`regex`, and others above) are used under its terms; any `NOTICE` files they
ship are reproduced by their inclusion in the distributed package.

### BSD (2-Clause / 3-Clause), ISC, 0BSD, Zlib, CC0, PSF, Unlicense

Standard permissive texts, reproduced with each package. These permit use,
modification, and redistribution provided the copyright notice and license
are retained (0BSD / CC0 / Unlicense waive even that).

### MPL-2.0

`certifi`, `tqdm`, and (as an alternative, not elected) `dompurify` are
available under the Mozilla Public License 2.0 — <https://mozilla.org/MPL/2.0/>.
File-level copyleft: obligations attach only to modified MPL-covered files.

