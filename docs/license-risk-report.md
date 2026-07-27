# Third-party license risk report

Generated 2026-07-11 (pre-release audit); updated same day after
remediation; own-license note updated 2026-07-27 (FSL-1.1-ALv2 selected). Read-only audit of every vendored/third-party
dependency — frontend npm, Python, and forked/copied source. Scope:
obligations and risks the third-party code imposes on switchbay.
(Switch Bay's OWN license — FSL-1.1-ALv2 — is separate from the
third-party obligations audited here; see the bottom note.)

**Best-effort review.** A careful, good-faith pass over every vendored
dependency's license and obligations; it maps where things stand and
what was remediated.

## TL;DR — all four remediated

| Risk | Item | Status |
|------|------|--------|
| Proprietary code in the dependency tree | `@univerjs-pro/*` (Univer commercial tier) | ✅ **RESOLVED** — dropped `@univerjs/presets`; built on granular Apache-2.0 packages; Pro tree fully removed (0 in lockfile/bundle); Sheet tab verified working |
| No aggregated attribution file | ~460 MIT/BSD/Apache/ISC deps require notice preservation | ✅ **RESOLVED** — `docs/THIRD-PARTY-NOTICES.md` generated |
| Forked MIT code without its notice | graph static JS forked from curiosity-engine (MIT) | ✅ **RESOLVED** — MIT attribution header added to the 5 forked files + NOTICES entry |
| Undocumented dual-license elections | jszip, dompurify, certifi, tqdm | ✅ **RESOLVED** — recorded in NOTICES |

**No GPL / AGPL / LGPL / SSPL anywhere** in either dependency tree — the
dangerous network-copyleft classes are absent. The overwhelming majority
is permissive (MIT / BSD / Apache-2.0 / ISC / PSF).

---

## 1. ✅ RESOLVED — Univer "Pro" packages removed from the tree

**Remediation (Session 34):** `SheetTab.tsx` no longer imports
`@univerjs/presets` (the metapackage that dragged in the proprietary
`@univerjs-pro/*` tier via its advanced/collaboration presets).
`createUniver` — a ~15-line wrapper that only needs `@univerjs/core` —
was inlined (it's Apache-2.0; attributed in NOTICES), and the tab now
builds on `@univerjs/core` + `@univerjs/preset-sheets-core`
(both Apache-2.0, no Pro deps). Result: `@univerjs-pro/*` is gone from
`pnpm-lock.yaml` (0 refs), from `node_modules` (0 dirs after prune), and
from the built bundle (0 refs). The Sheet tab was verified end-to-end
with Playwright against a live daemon — Univer boots and renders a
workbook canvas with zero console errors. Original analysis retained
below for context.

---

### Original finding (HIGH — now resolved)

**What.** The Sheet tab uses [Univer](https://univer.ai). Its free core
(`@univerjs/*`) is **Apache-2.0** — no issue. But the dependency
`@univerjs/presets` (a convenience metapackage we import in
`SheetTab.tsx` for `createUniver`) declares the *advanced* and
*collaboration* presets as dependencies:

- `@univerjs/preset-sheets-advanced`, `preset-sheets-collaboration`,
  `preset-docs-advanced`, `preset-docs-collaboration`

…which in turn depend on ~25 **`@univerjs-pro/*`** packages
(collaboration, print, charts, pivot, exchange, sheets-shape,
sparkline, `@univerjs-pro/license`, …). These packages have **no
`license` field at all** (`license: None`) and ship a *License
Management Library* — they are Univer's **commercially-licensed** tier,
requiring a paid license key for production use.

**Exposure — mitigated, not clean:**
- ✅ The **shipped bundle is clean**: `frontend/dist` has **0
  references** to `@univerjs-pro`. We only instantiate
  `UniverSheetsCorePreset` (from the separate, Apache-2.0
  `@univerjs/preset-sheets-core`, which has **no** Pro deps), so Vite
  tree-shakes all Pro code out. You are **not currently distributing**
  the proprietary code.
- ⚠️ But the Pro packages **are** downloaded into `node_modules` and
  pinned in `pnpm-lock.yaml`. Risks: (a) a future import of a Pro/
  advanced preset from the `@univerjs/presets` barrel would silently
  ship proprietary code; (b) anyone building from the lockfile fetches
  it; (c) it muddies a clean "all-permissive" claim.

**Recommendation.** Either:
1. **Remove the proprietary tree** — drop `@univerjs/presets` and build
   the sheet on the granular Apache-2.0 packages
   (`@univerjs/core` + `@univerjs/sheets` + `@univerjs/preset-sheets-core`)
   so `@univerjs-pro/*` leaves the graph entirely; **or**
2. **Document + gate** — keep the current setup (bundle is provably
   clean), add a note that Pro features are never imported, and add a CI
   check that fails if `univerjs-pro` ever appears in `frontend/dist`.

Option 1 is the conservative choice for a commercial or public release.

## 2. MEDIUM — No aggregated third-party attribution (NOTICES) file

Every permissive license in use (MIT, BSD-2/3-Clause, ISC, Apache-2.0,
PSF, 0BSD, Zlib, CC0) permits redistribution but **requires preserving
the copyright + license notice** in distributions. A built PWA ships
minified JS derived from ~500 npm packages; the Python daemon bundles
its deps at install. There is currently **no `THIRD-PARTY-NOTICES`
file**.

Apache-2.0 deps additionally: if any ship a `NOTICE` file, its contents
must be reproduced. Univer core, apache-arrow, grpc, chevrotain, swc are
Apache-2.0.

**Recommendation.** Generate a bundled-notices file at build time
(e.g. a license-collector over the prod dependency set for the frontend,
plus the Python venv) and ship it with the app / in the repo. Low effort,
closes the standard attribution obligation.

## 3. MEDIUM-LOW — Forked curiosity-engine code lacks its MIT notice

`frontend/src/widgets/graph/static/{graph,sidebar,modal,edit,subgraph}.js`
is a **fork of curiosity-engine's wiki-view** (charter says so). CE is
**MIT licensed** (`~/.claude/skills/curiosity-engine/LICENSE`,
"Copyright (c) 2026"). MIT requires the copyright + permission notice to
travel with "copies or substantial portions" — these forked files are a
substantial portion and currently carry **no license/copyright header**,
and Switch Bay has **no NOTICE** crediting CE.

**Practical risk is low** — curiosity-engine and Switch Bay appear to
share an author (same owner), so there's no adverse party. But for a
clean public release, add CE's MIT copyright + license text (a header in
the forked files or a NOTICES entry).

*(Related, no action: the LLM gateway is "patterned on" read-really-fast
and reuses its `ProviderError` **code vocabulary** — this is API/
vocabulary reuse, not copied code, and short identifier strings aren't
copyrightable. No obligation unless actual source was copied, which it
was not.)*

## 4. LOW — Dual-license / weak-copyleft elections to record

- **jszip** — `MIT OR GPL-3.0-or-later`. Elect **MIT**; no GPL
  obligation. (Pulled transitively for zip handling.)
- **dompurify** (added this session) — `MPL-2.0 OR Apache-2.0`. Elect
  **Apache-2.0**; avoids MPL file-level copyleft entirely.
- **certifi** (Python) — **MPL-2.0**. Weak, file-level copyleft: no
  obligation unless you modify certifi's own files (we don't).
- **tqdm** (Python) — `MPL-2.0 AND MIT`. Same — fine as a consumer.
- **khroma** — pnpm reports "Unknown"; it is in fact **MIT** (upstream
  metadata gap). No action beyond noting it.

**Recommendation.** Record the elections (MIT for jszip, Apache-2.0 for
dompurify) in the NOTICES file from §2.

## 5. Baseline — everything else is permissive

- **Frontend prod deps (~500):** 309 MIT · 91 Apache-2.0 · 57 BSD-3 ·
  49 ISC · 5 BSD-2 · plus single 0BSD, Zlib, CC0, Unlicense. Big libs
  verified: Excalidraw **MIT**, d3 **ISC**, vega/vega-lite/vega-embed
  **BSD-3**, mammoth **BSD-2**, katex **MIT**, turndown **MIT**, marked
  **MIT**, react **MIT**, apache-arrow **Apache-2.0**, xterm **MIT**,
  duckdb-wasm **MIT**.
- **Python venv:** all **BSD / MIT / Apache-2.0 / PSF / ISC / MPL**.
  numpy BSD-3 (+ bundled 0BSD/MIT/Zlib/CC0), scikit-learn/scipy/joblib
  BSD-3, pillow MIT-CMU, keyring MIT, sentence-transformers &
  torch-ecosystem Apache-2.0/BSD. (A raw scan flagged "GPL" inside
  **scipy** — a false positive: it's scipy's notice listing third-party
  component terms; scipy itself is BSD-3-Clause.)

No copyleft (GPL/AGPL/LGPL) or source-available-restrictive (SSPL, BUSL,
PolyForm, CC-NC) licenses were found in either tree.

---

## Note: Switch Bay's own license

Distinct from the vendored code above: **Switch Bay is released under the
Functional Source License 1.1 (FSL-1.1-ALv2)** — source-available for any
use except a Competing Use, converting to Apache-2.0 two years after each
version's release. See `LICENSE`. This is switchbay's own licensing
choice, separate from the third-party obligations audited here.

## Actions before a public/commercial ship

1. ✅ Univer Pro exposure resolved (§1) — dropped `@univerjs/presets`,
   built on granular Apache-2.0 packages, Sheet tab verified.
2. ✅ `docs/THIRD-PARTY-NOTICES.md` generated + dual-license elections
   recorded (§2, §4).
3. ✅ CE MIT attribution added to the forked graph code (§3).
4. ✅ **Switch Bay's own license chosen** — FSL-1.1-ALv2 (source-available;
   converts to Apache-2.0 after the change date). See `LICENSE`.
