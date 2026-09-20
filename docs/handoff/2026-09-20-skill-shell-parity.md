# Skill-shell parity gates — v0.12.19 release baseline

**Not a claim that skill-shell rework already has parity.** This is the
released contract for later work that **imports** curiosity-engine,
curiosity-merge, and okstratr instead of vendoring or duplicating their
servers. ADR-004 vocabulary (same-origin `/embed/ce` + `/embed/okstratr`,
no iframes, okstratr owns harness/model registry) describes that shell,
not this tag.

Release notes: [v0.12.19](../releases/v0.12.19.md)

**Body retrieval** = full message content beyond headers/labels. Allowed
only after explicit per-workspace approval **and** a fresh classification
gate. Revoke halts future body updates.

**Verified paid Curate:** 18.87s, 10,811 tokens, 237-word
committed page. **Fake stress (distinct):**
`test_curate_scheduler.py::test_thousand_productive_waves_unique_ids_resume`
(≥1005 `execute()` completions).

**Limitations:** live iCloud placeholder not tested; Comms fixtures are
not an enterprise-tenant certification. Integration coverage depends on
installed CE and the optional PDF/XLSX extractor environment; report skips.

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
| Skills missing/present/read-only; versioned integration; registry ownership; no duplicate server impl | `test_skillkit_authoring.py` (`test_symlinked_bundled_skill_is_not_writable`, `test_discovers_agents_skills_without_claude_dir`); `test_ce_global_fallback.py`; `test_updater.py` (`test_local_skill_version_from_changelog_when_not_git`, `test_find_skill_dir_uses_global_roots`, `test_match_skill_release_walks_older_tags`); `test_admin_policy.py` (`test_skills_allowlist`, `test_list_providers_hides_disabled`); `test_kernel_hire.py::test_denied_model_is_not_proposed`. Rework gate: import CE/merge/okstratr; do not vendor their HTTP servers or grow a second model allowlist. |

Keep these tests green (or replace with equivalent external-skill contracts)
before deleting built-in Graph/Agents duplicates. Do not copy pre-0.12.19
architecture.

For each imported skill, record its version and verify discovery, missing-skill
errors, its public API, and unchanged installed files. Exercise CE ingest/query,
curiosity-merge preview/import/rollback, and okstratr desk lifecycle through the
shell. Check workspace/model policy at those boundaries and keep a single
registry. These are **additional rework acceptance gates**; the release tests
above do not certify the three-skill integration.
