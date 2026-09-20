# Skill-shell rationalization gates — Switchbay v0.12.19

**Charter position:** Switchbay v0.12.19 is a **behavior/performance gate under
the import charter**, not a source-parity, source-merge, or implementation
plan. Switchbay and okbay import and invoke the CE, curiosity-merge (CM), and
okstratr skills through their public skill contracts. They must **not vendor
their servers, merge their source, copy their internals, or re-implement them
for either shell**. The shell owns its adapter/UI policy; the skills remain
the owners of their behavior and services.

This document records the v0.12.19 release behavior matrix and the additional
gates for imported skills. Passing it means observable behavior and measured
performance are compatible at the import boundary; it does not certify a
particular internal implementation.

Release notes: [v0.12.19](../releases/v0.12.19.md)

## Pinned inputs

- **CE skill:** `5d2b967558dd052c62b23fbc03217b1ac2a18d5a` (short
  `5d2b967`), the exact CE skill commit for this gate.
- **BioCure wiki fixture:** `biocure-confirm-v1-query-5b9711895`, freeze tip
  `5b9711895` (full SHA unavailable in this checkout). This is a wiki/corpus
  fixture pin, **not** the CE skill SHA.
- **Switchbay release:** tag `v0.12.19`, commit
  `bbc94062b209653178b97613876bd2c59c9e4783`.

CM and okstratr versions must be recorded from their imported skill artifacts
when those integrations are exercised; do not infer them from the Switchbay
release SHA.

## Behavior and performance gate

**Body retrieval** = full message content beyond headers/labels. Allowed only
after explicit per-workspace approval **and** a fresh classification gate.
Revoke halts future body updates.

The v0.12.19 release evidence is the behavior baseline. The import gate must
exercise the same observable contracts through the imported skills and record
cold/warm startup, readiness, CE ingest/query, CM preview/import/rollback, and
okstratr desk lifecycle timings plus resource context. A gate result is
**pass**, **fail**, or **not run** with the pinned skill and BioCure fixture
identified; do not call an unmeasured integration “parity.” Unexplained
behavioral or performance regressions fail the gate.

**Verified paid Curate baseline:** 18.87s, 10,811 tokens, 237-word committed
page. **Fake stress (distinct):**
`test_curate_scheduler.py::test_thousand_productive_waves_unique_ids_resume`
(≥1005 `execute()` completions).

**Limitations:** live iCloud placeholder not tested; Comms fixtures are not an
enterprise-tenant certification. Integration coverage depends on installed CE
and the optional PDF/XLSX extractor environment; report skips.

| Behavior | Evidence / tests |
|---|---|
| Runtime + slideshow PDF/Playwright | `test_runtime.py`; `test_service_stop.py`; `test_slideshow_pdf.py` (`test_pdf_renderer_script_exists_and_prints_16x9`, `test_pdf_handler_writes_vault_export`) |
| CE read-only fallback; workspace allowlist; Auto Research | `test_ce_global_fallback.py`; `test_fresh_install_sandbox.py`; `test_research_desk.py` (`test_auto_web_ingest_hires_research_package`, `test_research_hire_honours_workspace_denylist`); `test_curate_lifecycle.py::test_resume_respects_workspace_model_allowlist`; `test_cebridge_setup.py` |
| Web default-off; once/deny never persisted; Codex native search off | `test_web_policy.py`; `test_web_egress_policy.py` (`test_protected_never_pre_approved_even_with_mcp_wildcard`, `test_resolve_ignores_remember_for_protected`, `test_codex_native_search_always_disabled`, `test_codex_override_beats_preexisting_live`); `test_web_consent.py`; `test_web_search_approval.py`; `frontend/tests/webPolicy.race.test.ts`; `frontend/tests/e2e/zen-web-policy.spec.ts` |
| Docked Zen / floating Chat / 377px Rail | `zen-web-policy.spec.ts` (`zen floating chat is two columns…`, `zen docked chat pins composer…`, `377px Rail has one header Web control…`) |
| Comms metadata-only, no auto-add; enterprise fail-closed pre-body; approve/revoke/races; Teams/Slack bodies blocked | `test_comms_desks_review.py` (`test_gmail_discovery_requests_no_snippet_or_body`, `test_imap_discovery_never_fetches_text`); `test_comms_gate.py` (`test_secret_blocked_before_approval`, `test_unknown_label_enterprise_not_public`, `test_approve_respects_allowlist_and_revoke_wins`, `test_unapproved_gmail_never_fetches_body`, `test_revocation_during_body_request_skips_parser`, `test_teams_pages_later_channels_without_top`); `test_release_acceptance.py` (`test_teams_metadata_queries_use_supported_parameters_only` — no `/messages`; `test_approved_email_unknown_fresh_classification_never_fetches_body`; `test_inflight_comms_authorization_change_prevents_body_parse`). Teams/Slack listing sets `content_capability=fail_closed` in `streams.py`; approval does not retrieve chat bodies. |
| Live cap floor 4 / default and hard 8, chief counted, admin tightens; continuous waves; no early stop; retired workers absent from live DAG | `test_desk_admission.py` (`test_cap_floor_and_admin_tightening`, `test_baked_tightens_not_raises`, `test_chief_counted_and_nested_share_desk`, `test_continuous_progress_after_compaction`); `test_admin_policy.py` (`test_max_live_workers_*`); `test_curate_lifecycle.py` (`test_curate_continue_is_package_wave_not_generic`, `test_continuous_second_wave_then_stop`); `test_comms_desks_review.py::test_retired_thousand_workers_do_not_remain_live_roster`; `test_release_acceptance.py::test_completed_single_use_worker_leaves_actual_parent_graph` |
| Real content receipts; partial-result preservation; idle no LLM spin | `test_curate_content_receipts.py`; `test_curate_evidence.py`; `test_curate_scheduler.py` (`test_noop_curate_waits_without_llm`, `test_noop_curate_deadline_stops_idle_wait`); `test_comms_desks_review.py::test_real_transport_failure_keeps_partial_output` |
| PPTX fallback preserving workspace PDF/XLSX; cloud single-file hydrate/retry/auth | `test_pptx_ingest.py` (`test_host_python_has_pptx_and_workspace_venv_can_lack_it`, `test_xlsx_pdf_prefer_workspace_venv_that_has_extractors`, mixed/corrupt); `test_icloud_download.py`; `test_watchfolders.py` (`test_hydration_pending_then_ready_exactly_once`, `test_dispatch_uses_workspace_captured_at_scan`); `test_watch_review.py` |
| Skills missing/present/read-only; versioned integration; registry ownership; no duplicate server implementation | `test_skillkit_authoring.py` (`test_symlinked_bundled_skill_is_not_writable`, `test_discovers_agents_skills_without_claude_dir`); `test_ce_global_fallback.py`; `test_updater.py` (`test_local_skill_version_from_changelog_when_not_git`, `test_find_skill_dir_uses_global_roots`, `test_match_skill_release_walks_older_tags`); `test_admin_policy.py` (`test_skills_allowlist`, `test_list_providers_hides_disabled`); `test_kernel_hire.py::test_denied_model_is_not_proposed` |

## Import-boundary acceptance

For each imported skill, record its artifact/version and verify discovery,
missing-skill errors, public API behavior, and unchanged installed files.
Exercise CE ingest/query, CM preview/import/rollback, and okstratr desk
lifecycle through the shell, using the pinned CE skill and BioCure fixture.
Check workspace/model policy at those boundaries and keep one registry. These
are **additional import-boundary acceptance gates**; the v0.12.19 release
tests above do not certify the three-skill integration.

Do not use this matrix as permission to merge CE/CM/okstratr source into
Switchbay or okbay, vendor their servers, or grow shell-specific rewrites.
Any retirement of pre-import duplicate shell behavior is a separate decision
after the imported-skill behavior/performance gate passes.
