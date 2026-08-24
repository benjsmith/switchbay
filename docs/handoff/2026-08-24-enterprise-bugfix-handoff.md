# Switch Bay v0.10 enterprise bugfix handoff

Date: 2026-08-24

Baseline: `a2e1cf7` (`main`, `origin/main`, and `v0.10.0`)

Repository: `/Users/benj/Dev/switchbay` / `git@github.com:benjsmith/switchbay.git`

## Why this handoff exists

The v0.10.0 release is the latest Switchbay release. Its README already documents multi-agent, multi-model/provider auto-orchestration. A later local commit was accidentally made in the separate Switchyard benchmarking checkout and was never pushed or released. This document relocates the actionable product findings to Switchbay without importing stale architecture or benchmark artifacts.

The companion `switchyard-cf6886f-reference.patch.gz` contains selected changes from that mistaken commit. Inspect it with `gzip -dc`; it is reference material only: **do not apply it wholesale**. Switchbay v0.10.0 has a newer adaptive orchestration stack (`agents/orchestration.py` and `orchestration_policy.py`) that must remain authoritative.

## What the audit found

### 1. pnpm 11 build approval — open

`frontend/package.json` already names `esbuild` and `@tailwindcss/oxide` in `onlyBuiltDependencies` and `protobufjs` in `ignoredBuiltDependencies`, but supported pnpm 11 behavior still needs a clean-install test and, if required, checked-in workspace-level `allowBuilds`. `scripts/install.sh` and the Makefile run install without a frozen lock; CI still selects pnpm 10.

Required fix: use pnpm's current explicit per-package approval mechanism, permit only dependencies proven to require install scripts, use frozen-lock installs in normal/CI paths, and never enable all scripts silently.

### 2. `uv sync` dirties `uv.lock` — open

The Makefile, installer, and CI call plain `uv sync`. Change normal consumer paths to `uv sync --locked` (including optional groups). Document `uv lock` as an intentional maintainer operation. Test every install entry point with a before/after clean-tree assertion.

### 3. Curate did not orchestrate — open

`handle_ce_action_run` builds a curation prompt and calls `_dispatch_chat` directly. The adaptive entry point is `_dispatch_auto`; v0.10.0's curation route therefore does not automatically exercise the richer policy/DAG path even at maximum preference.

Required fix: integrate CE curation into the existing orchestration policy, including curation-safe tools and worker responsibilities. Do not port Switchyard's older `auto_orchestrator.py`/`fanout.py` as a second scheduler. A complex curation run at maximum must produce a visible multi-node DAG; a single node remains valid only when the policy explains why the task does not benefit from delegation or the execution environment constrains it.

### 4. Copilot-only model diversity — implemented in principle, verify visibly

v0.10.0 release notes and orchestration code include same-provider model diversity. The reported enterprise run did not visibly show a chief-of-staff transition or distinct worker models.

Required fix/test: with GitHub Copilot as the only permitted provider, run a suitably complex maximum-preference task and assert that the plan records distinct available Copilot models where possible. Display provider and model on chief/worker nodes and in diagnostics. If inventory has only one usable model, show that constraint rather than implying diversity.

### 5. Agent DAG visibility, persistence, animation, and paging — partial

The Agent dashboard already computes a persisted `standing` organization and prefers a live/recent `featured` organization. This supports the intended idle persistence, but the reported UI hid the DAG during both curation and complex rail work. There is no clear concurrent-root DAG pager in `AgentDashboardTab.tsx`.

Required behavior:

- make Agent Space/DAG discoverable and visible when a qualifying run starts;
- animate node/edge transitions without losing the final state;
- retain the last effective DAG through completion, tab switching, reload, and daemon restart until a new qualifying run replaces the default;
- keep simultaneous runs separate and add previous/next navigation or a run picker showing objective, time, status, and model roster;
- opening a rail run jumps to the correct root DAG, not merely the newest one.

### 6. Enterprise Add Workspace blocks CE setup — open

`config/admin.enterprise.json` sets `features.ce_auto_setup` to false, and `cebridge.setup()` refuses before resolving the known setup script. The policy protects against arbitrary workspace shell execution but is too coarse for the shipped Curiosity Engine setup path.

Required fix: introduce a narrow, auditable trust decision for the resolved bundled CE `scripts/setup.sh`, invoked non-interactively with a scrubbed environment and exact argv. Keep arbitrary workspace scripts, hooks, and globbed shell permissions blocked. Test path resolution/tampering, admin denial, timeout, error messaging, and successful clean workspace creation. Update `docs/enterprise.md` to explain the distinction.

### 7. Atlas first frame shows deprecated grouped boundaries — verify/fix

`mountAtlas()` requests hybrid layout and supplies `corpusSize`, which is meant to render individual rim nodes immediately. The enterprise test still showed grouped boundaries until a full zoom-out/in cycle, suggesting an initialization/resize or vendored-engine first-frame defect.

Required test: load Atlas fresh at representative viewport sizes and assert the stable first frame uses individual nodes without any wheel input. Repeat after tab switch, workspace switch, resize, and reload. Fix initialization ordering or force the post-layout scale/state once dimensions and corpus data are available; do not rely on a synthetic user zoom.

### 8. Replace sketch decks with HTML slideshows — open migration

Switchbay already has a sandboxed `HtmlDeckTab` and `slideshows/<slug>/` packages, but it also retains extensive sketch deck/analysis workflow in `SketchTab.tsx`, App bridges, tools, routes, and documentation. This duplicate model caused wrong slide counts, processing races, and tab switching back to Graph/Editor.

Required product migration:

- all slide/deck creation produces an HTML slideshow package and opens it in a new/temporary Slideshow tab;
- add **Save as PDF** into the vault, with one 16:9 page per slide, backgrounds/fonts/media fully resolved, and no clipped content;
- retain Excalidraw/drawio sketch authoring and multiple sketches;
- reuse the current sketch picker as a browser over the entire workspace sketch collection;
- remove sketch-deck navigation, deck analysis/population/export tools, bridges, routes, and stale docs;
- make existing legacy deck workspaces degrade safely rather than destroying assets.

Update `CLAUDE.md`, whose current deck rule states the opposite product decision. Add renderer/print CSS tests plus a real browser/PDF visual pass.

### 9. Reviews still appear in the rail — partial/open

The daemon creates a transient Reviews surface, but `App.tsx` still converts `page_proposal_review` events into rail entries, rehydrates them on workspace load, and the rail still renders `ProposalCard`. `_vet_proposal` also emits a rail notice. Current semantics wait for review rather than accepting low-confidence proposals provisionally by default.

Required fix:

- never add, rehydrate, or announce page-review cards in the rail;
- provisionally apply low-confidence proposals and retain an exact rollback;
- ensure a closable transient Reviews tab exists without stealing focus;
- ignoring or closing accepts/finalizes the provisional result;
- reject restores the exact prior file or removes a newly created one;
- a user comment keeps/finalizes the result and records feedback for injection into the next curation cycle;
- preserve pending reviews across restart and workspace switching.

The old patch includes a possible state-machine sketch, but it needs reconciliation with Switchbay's current Reviews/Report naming and production persistence.

### 10. Source references should reveal files — open

Frontmatter source arrays render as plain grey text in `CollapsibleSources`. The provenance chip can open originals, but no general citation click reveals the exact File Browser row.

Required fix: render local source items/citations as accessible buttons/links. On click, switch the sidebar lower pane to Files, expand ancestor directories, scroll to and pulse/select the exact row, and preserve context-menu access. Keep HTTP(S) references as normal external links. Normalize `wiki/`, vault-relative, and safe workspace-relative paths and refuse escapes. Add a component/browser test.

## Recommended implementation order

1. pnpm/uv locking and clean-install tests.
2. Narrow enterprise setup trust.
3. Curation integration with the existing adaptive orchestrator, then Copilot-only verification.
4. DAG visibility/persistence/concurrent-run paging.
5. Atlas first-frame regression.
6. HTML slideshow migration and PDF export.
7. Reviews-only proposal flow.
8. Citation-to-file reveal.
9. Full test/build/install/browser acceptance, docs, and release preparation.

## Release guidance

Do not manufacture a v0.10.1 release merely to replace the mistaken Switchyard work. These fixes include material product behavior (DAG navigation and removal of sketch decks), so `v0.11.0` is the likely next pre-1.0 version once all acceptance criteria pass. Do not bump, tag, push, or publish from this handoff alone.

## Completion gate

- A clean pnpm 11 install and frontend build pass with a narrow script allowlist.
- All normal uv sync paths leave the committed lock untouched.
- Enterprise Add Workspace completes through the trusted CE setup path.
- Complex curation and Copilot-only tasks visibly exercise the intended orchestration/model roster.
- DAG state persists and concurrent DAGs are navigable.
- Atlas first frame is correct without zoom interaction.
- HTML slideshow creation/tab/PDF behavior is stable; ordinary sketch handling remains.
- Review actions never enter the rail and rollback/feedback semantics pass.
- Local source clicks reveal the exact file-browser row.
- `make check` passes and the release diff contains no demo, benchmark, generated, cache, or private planning artifacts.

## Implementation checkpoint — 2026-08-24

Acceptance items 1–7 have been implemented on the Switchbay branch before beginning the slideshow migration:

- normal Python and frontend installs consume immutable lockfiles, with pnpm 11 build scripts governed by the checked-in narrow allowlist;
- enterprise setup trusts only the resolved bundled Curiosity Engine setup script with exact argv, scrubbed environment, and timeout enforcement;
- broad curation now uses the adaptive orchestrator, including single-writer curation plans and visible reasons for conservative single-agent dispatch;
- Copilot-only plans retain distinct available model assignments and the Agent Space UI displays provider/model data;
- live, recent, and persisted Agent Space roots are isolated and navigable with previous/next and an explicit picker;
- Atlas receives an individual-node, zero-aggregate budget before its first engine frame.

Focused backend tests and the pnpm 11 production build pass. Browser acceptance for the UI portions remains part of the final completion gate. This checkpoint deliberately precedes the riskier HTML-slideshow-only migration and does not constitute a release.
