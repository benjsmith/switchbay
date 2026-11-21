# Configuration

The daemon never writes the admin file. Search order, first file that exists:

1. `$SWITCHBAY_ADMIN_POLICY`
2. `%ProgramData%\SwitchBay\admin.json` (Windows)
3. `/Library/Application Support/SwitchBay/admin.json` (macOS)
4. `/etc/switchbay/admin.json`
5. `<checkout>/admin.json` (`service install --enterprise-user` writes this)

Template: [`config/admin.enterprise.json`](../../config/admin.enterprise.json). MDM copies should be root-owned, mode `0644`. Do not put the policy in `~/.config/switchbay`. The daemon writes there.

`SWITCHBAY_PROFILE=open` or `enterprise` selects the profile when no baked file has locked it. A baked `admin.baked.json` makes a later overlay tighten-only for feature flags and providers. The tester file from `--enterprise-user` has no baked file, so it is not tighten-only.

The loader copies `profile`, `features`, `providers`, `copilot`, `network`, `mcp`, `skills`, `paths`, `updates`, `comms`, `orchestration`, and, when the file contains them, `graph_mounts`, `sources`, `public_writes`, and `classification_review`. A missing federation section leaves the profile default in place. Baked and overlay dictionaries are merged, overlay last.

## Profile defaults that matter here

| Key | Open | Enterprise |
|---|---|---|
| `graph_mounts.enabled` | true | true |
| `graph_mounts.allowlist` | `["*"]` | `[]` |
| `graph_mounts.allow_public` | true | false |
| `graph_mounts.remote_write` | `propose` | `propose` |
| `graph_mounts.max_ceiling_by_trust` | external `public`, org `confidential`, own `restricted` | same |
| `sources.enabled` | true | true |
| `sources.allowlist` | `["*"]` | `[]` |
| `sources.allow_act_tools` | false | false |
| `sources.snapshot` | `allowed` | `allowed` |
| `sources.declassify` | `allow` | `forbid` |
| `sources.capture_retention_days` | 0 | 0 |
| `public_writes.allowed` | true | false |
| `public_writes.connections` | `[]` | `[]` |
| `public_writes.presidio_required` | false | true |
| `public_writes.user_control` | true | true |
| `public_writes.enabled_users` | `[]` | `[]` |
| `classification_review.mandatory` | false, unless the workspace file turns it on | true |

`remote_write` values: `propose` keeps every remote change a proposal. `none` forbids the write. Any other value, including `direct`, allows a direct write only when the mount, the live server, and `direct_writes` also allow it. `max_ceiling_by_trust` is enforced on save and on write. `capture_retention_days` above 0 deletes old captures. `snapshot: forbid` blocks copies into `vault/ext`.

`presidio_required` is stored. The running rule is: if Presidio analyzes the text, the result is used; if it does not, the dialog is required unless Always allow is stored or the user toggle is off. Enterprise `allowed: false` refuses public writes before that, except mount ids in `connections`.

Allowlists accept a string, a list, or `*`. Matching is `fnmatch`, or a prefix when the pattern ends in `*`.

## Providers and features

Missing provider ids are on in the open profile. In enterprise they are on only for `github_copilot`, `llamacpp`, `mlx`, and `ollama`. MLX is off when the OS is not macOS. Ids: `github_copilot`, `llamacpp`, `mlx`, `ollama`, `claude-code`, `grok-build`, `muse-code`, `openai-codex`, `anthropic`, `xai`, `meta`, `openai`, `gemini`.

`copilot.host` defaults to `github.com`. `copilot.lock_host` defaults to true in enterprise.

| Feature | Open | Enterprise |
|---|---|---|
| `in_app_update` | on | off |
| `install_skills_npx` | on | on |
| `ce_auto_setup` | on | off |
| `ce_bundled_setup` | on | on |
| `uv_python_install` | on | off |
| `scan_other_app_caches` | on | off |
| `hf_model_download` | on | off |
| `comms_streams` | on | off |
| `github_share` | on | off |
| `media_generation` | on | off |
| `user_mcp_servers` | on | on |
| `watch_folders` | on | on |
| `interactive_terminal` | on | on |
| `agent_run_command` | on | on |
| `demo_workspace` | on | off |
| `pi_harness` | on | off |
| `browser_use` | on | off |
| `web_egress` | on | off |

`network.bind_host` defaults to `127.0.0.1`. `network.bind_port` unset means `8765`. `network.egress_allowlist` defaults to empty and is consulted only in the enterprise profile.

`mcp.allowlist` and `skills.allowlist` default to `*`.

`paths.workspaces_home` unset means `~/SwitchBay`. `paths.allow_synced_workspaces` defaults to false in enterprise and true in the open profile. `paths.trust_boundary` defaults to empty and is applied.

`updates.repo` defaults to `benjsmith/switchbay`. `updates.include_skills` defaults to false in enterprise.

`orchestration.max_live_workers`, when a positive integer, caps live seats. A baked value can only be lowered by an overlay. The floor is 4 and the hard maximum is 8.

`comms` is applied when `comms_streams` is on. `require_classification` defaults to on in enterprise. A baked enterprise file forces it on. Headers, secret names, and tenant label ids are in the [packaging guide](../enterprise.md#comms-classification-and-tenant-labels).

## Workspace file

| Field | Default |
|---|---|
| `read_default` | `["local"]` |
| `default_write` | `local` (`local`, `remote`, `both`). Stored. The write tool takes its own `mode` |
| `direct_writes` | false |
| `mounts[].id` | `^[a-z][a-z0-9_-]{0,40}$`, not `local` |
| `mounts[].kind` | `snapshot` or `live` |
| `mounts[].write` | `none`, `propose`, or `direct` |
| `mounts[].trust` | `own`, `org`, or `external` (default `external`) |
| `mounts[].ceiling` | default `public` |
| `mounts[].auth` | `anonymous`, `oauth`, or `dev` |
| `mounts[].token_check` | empty means `jwt` for `oauth` |
| `mounts[].jwks_url`, `issuer`, `audience`, `introspection_url` | empty; discovery fills JWT and introspection when the mount omits them |
| `sources[].kind` | `workiq`, `databricks-genie`, `aws-context`, `aws-quick`, `unity-catalog` |
| `sources[].classification` | empty sends the capture to Review |

Other workspace files: `.workbench/exclusion-rules.json`, `.workbench/presidio.json` (missing means on), `.workbench/public-write-rules.json`, `<config dir>/public-write-rules.json` (global Always allow), `.workbench/classification-review.json`, `.workbench/state/classification_queue.json`, `.workbench/state/graph-outbox.jsonl`, `.workbench/state/import-quarantine.jsonl`, `.workbench/share.json`.

The config dir is `~/.config/switchbay`, or `%LOCALAPPDATA%\switchbay\config` on Windows. `XDG_CONFIG_HOME` overrides the non-Windows path.

Presidio is the optional dependency group `presidio`: `presidio-analyzer==2.2.366` and `presidio-anonymizer==2.2.366` (released 2026-10-27, not yanked, no published advisory), plus pins so the group does not take spaCy, phonenumbers, pydantic, or smart-open releases younger than 14 days. A normal `uv sync` does not install the group.
