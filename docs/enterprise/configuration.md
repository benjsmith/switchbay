# Configuration reference

[Enterprise security](index.md)

The daemon never writes the admin file. An MDM or a company portal
drops it. Search order, first file that exists:

1. `$SWITCHBAY_ADMIN_POLICY` (absolute path)
2. `%ProgramData%\SwitchBay\admin.json` (Windows)
3. `/Library/Application Support/SwitchBay/admin.json` (macOS)
4. `/etc/switchbay/admin.json`
5. `<checkout>/admin.json` (optional; `service install --enterprise-user` writes this)

A template is [`config/admin.enterprise.json`](../../config/admin.enterprise.json).
MDM copies should be root-owned, mode `0644`. Do not put the policy
in `~/.config/switchbay`: that tree is user-writable, and the daemon
does write there.

`SWITCHBAY_PROFILE=open` or `enterprise` selects the profile when no
baked file has locked it. A baked `admin.baked.json` next to an
install root (or `SWITCHBAY_INSTALL_ROOT`) is the company package.
With a baked file, overlay feature flags and providers can only
tighten, unless the baked file sets `allow_profile_override` and the
environment variable is set. The tester file from
`--enterprise-user` is an overlay with no baked file, so it is not
tighten-only.

## Sections the loader does not apply

The loader copies `profile`, `features`, `providers`, `copilot`,
`network`, `mcp`, `skills`, `paths`, `updates`, `comms`, and
`orchestration`. It drops every other top-level key.

These four sections are in the template and in the federation code,
and editing them in `admin.json` has no effect. The profile default
is what runs.

| Section | Enterprise default that actually runs | Open default | What an edit would have done |
|---|---|---|---|
| `graph_mounts.enabled` | `true` | `true` | Turn mounts off |
| `graph_mounts.allowlist` | `[]` (no remote mount matches) | `["*"]` | Name graph ids or URLs that may be saved. `*` allows any. Globs work |
| `graph_mounts.allow_public` | `false` | `true` | Allow mounts with trust `external` |
| `graph_mounts.remote_write` | `propose` | `propose` | `propose` keeps every remote change a proposal. `none` forbids the write. Any other value, including `direct`, allows a direct write only when the mount's `write` is `direct`, the live server reports `direct_granted`, and the workspace sets `direct_writes` |
| `graph_mounts.max_ceiling_by_trust` | `external`→`public`, `org`→`confidential`, `own`→`restricted` | same | Nothing. No check reads this map |
| `sources.enabled` | `true` | `true` | Turn the source broker off |
| `sources.allowlist` | `[]` (every call refused) | `["*"]` | Allow a kind, a URL, or `kind url` |
| `sources.allow_act_tools` | `false` | `false` | Show Work IQ act tools |
| `sources.snapshot` | `allowed` | `allowed` | `forbid` blocks copies into `vault/ext` |
| `sources.declassify` | `forbid` | `allow` | `forbid` blocks lowering a page |
| `sources.capture_retention_days` | `0` | `0` | Nothing. No job reads it |
| `public_writes.allowed` | `false` | `true` | `false` limits public writes to `connections` |
| `public_writes.connections` | `[]` | `[]` | Mount ids that may receive a public write when `allowed` is false |
| `public_writes.presidio_required` | `true` | `false` | Read, then ignored. The branch does not change the result. Enterprise never reaches it, because public writes are refused first. In the open profile a missing Presidio package asks for the dialog either way |
| `public_writes.user_control` | `true` | `true` | `false` removes the Settings toggle in enterprise |
| `public_writes.enabled_users` | `[]` | `[]` | OS user names who still have scanning on when `user_control` is false |
| `classification_review.mandatory` | `true` (because the key is absent and the profile is enterprise) | `false`, unless the workspace file turns it on | `false` would make enterprise Review optional |

Until the loader copies these sections, an enterprise install cannot
be given an allowlisted remote graph or an allowlisted source by
editing `admin.json`. Remote mounts fail to save. Source calls are
refused. Declassification stays forbidden. Public writes stay off.
Review stays mandatory. The Presidio toggle stays available.

## Profile, providers, Copilot

`profile`: `open` (default) or `enterprise`.

`providers` is a map of provider id to boolean. A missing id in the
enterprise profile is on only for `github_copilot`, `llamacpp`,
`mlx`, and `ollama`. MLX is always off when the OS is not macOS. In
the open profile a missing id is on. Ids:
`github_copilot`, `llamacpp`, `mlx`, `ollama`, `claude-code`,
`grok-build`, `muse-code`, `openai-codex`, `anthropic`, `xai`,
`meta`, `openai`, `gemini`.

`copilot.host` defaults to `github.com`. `copilot.sso_slug` defaults
to empty. `copilot.lock_host` defaults to true in enterprise and
false in the open profile, unless the file sets it.

## Features

Missing keys take the profile default. Enterprise differs from open
only where the enterprise column says off.

| Feature | Open | Enterprise | Effect when off |
|---|---|---|---|
| `in_app_update` | on | off | Settings → Update is the IT-package control. `POST /api/update` returns 403 |
| `install_skills_npx` | on | on | `npx` / `uvx skills add` |
| `ce_auto_setup` | on | off | curiosity-engine `scripts/setup.sh` and a venv per workspace |
| `ce_bundled_setup` | on | on | Only the vendored setup script under the install root, after the path is checked |
| `uv_python_install` | on | off | `uv python install` |
| `scan_other_app_caches` | on | off | Walking other apps' Hugging Face caches |
| `hf_model_download` | on | off | Hugging Face and Ollama pulls from Settings. Files already on disk still load |
| `comms_streams` | on | off | Mail, Slack, and Teams as sources |
| `github_share` | on | off | `gh` publish of a workspace |
| `media_generation` | on | off | External image and video APIs |
| `user_mcp_servers` | on | on | User MCP entries |
| `watch_folders` | on | on | Local directory poll. New files only |
| `interactive_terminal` | on | on | The rail shell |
| `agent_run_command` | on | on | Agents may run workspace commands, still subject to approval |
| `demo_workspace` | on | off | Seeding the bundled demo on first run |
| `pi_harness` | on | off | Optional PATH harness for hired packages |
| `browser_use` | on | off | Local Playwright browser for agents |
| `web_egress` | on | off | Whether the person may enable per-workspace web search. The workspace default stays off either way |

## Network, MCP, skills, paths, updates

`network.bind_host` defaults to `127.0.0.1`. `network.bind_port`
defaults to unset, and the process then uses `8765` (or `--port`).
`network.egress_allowlist` defaults to empty. It is a list of host
names added to the enterprise egress set. The open profile does not
consult it (`egress_allowed` returns true for every URL).

`mcp.allowlist` and `skills.allowlist` default to `*`. `false` or
`[]` allows nothing. A list of strings is matched as a glob, or as
a prefix when the pattern ends in `*`.

`paths.workspaces_home` is the directory under which the default
`workspace` folder is created. Unset means `~/SwitchBay`.
`paths.allow_synced_workspaces` defaults to false in enterprise and
true in the open profile.
`paths.trust_boundary` defaults to empty. It is a list of directory
prefixes. Enterprise serve-time refusal of a synced workspace path
uses this list. The key is applied.

`updates.repo` defaults to `benjsmith/switchbay` (an `owner/name`
string). `updates.include_skills` defaults to false in enterprise
and true in the open profile.

`orchestration.max_live_workers` is optional. When set to a positive
integer it caps live seats. A baked value can only be lowered by an
overlay. The floor is 4 and the hard maximum is 8, applied by the
orchestration code on top of this number.

`comms` is applied. It matters only when `comms_streams` is on.
Fields used by that feature: `require_classification` (unset means
on in enterprise; a baked enterprise file forces it on),
`classification_headers`, `secret_names`, `tenant_label_ids`.
Defaults and the tenant-fixture warning are in the
[packaging guide](../enterprise.md#comms-classification-and-tenant-labels).

## Workspace file: mounts and sources

`<workspace>/.workbench/graph-mounts.json`, schema
`switchbay-graph-mounts/1`. This file is applied. Saving it re-runs
the admin mount check, which is why an enterprise remote mount does
not save.

| Field | Default | Values |
|---|---|---|
| `read_default` | `["local"]` | Mount ids searched when the caller omits `graphs` |
| `default_write` | `local` | `local`, `remote`, or `both`. Stored and listed. The write tool takes its own `mode` argument (`remote` or `both`) |
| `direct_writes` | `false` | Workspace half of a direct remote write. Policy still forces `propose` |
| `mounts[].id` | | `^[a-z][a-z0-9_-]{0,40}$`, not `local` |
| `mounts[].kind` | | `snapshot` or `live` |
| `mounts[].graph_id` | empty | A `ceg://` id is the convention used by the demo. Any string is stored |
| `mounts[].url` | empty | Directory, or `https://`, `http://`, `git@`, `file://` for a snapshot. Server URL for a live mount |
| `mounts[].ref` | empty | Snapshot branch, or a 12- or 40-character hex revision |
| `mounts[].read` | `true` | Included when `graphs` is `all` |
| `mounts[].write` | `none` | `none`, `propose`, `direct` |
| `mounts[].trust` | `external` | `own`, `org`, `external` |
| `mounts[].ceiling` | `public` | `public`, `internal`, `confidential`, `restricted` |
| `mounts[].auth` | `oauth` for live, `anonymous` otherwise | `anonymous`, `oauth`, `dev` |
| `mounts[].refresh` | `manual` | Stored when set to something else. No scheduler reads it |
| `sources[].id` | | Same id pattern |
| `sources[].kind` | | `workiq`, `databricks-genie`, `aws-context`, `aws-quick` |
| `sources[].url` | empty | Recorded on the capture. Not dialled |
| `sources[].auth` | `oauth` | Stored. The fake transport ignores it |
| `sources[].classification` | empty | One of the four labels, or empty to mean "unlabelled, send to Review" |

## Other workspace files

| File | Purpose | Default when missing |
|---|---|---|
| `.workbench/exclusion-rules.json` | Allow / Ask / Deny sentences | No rules |
| `.workbench/presidio.json` | `{"enabled": true\|false}` | On |
| `.workbench/public-write-rules.json` | Always-allow rules scoped to this workspace | None |
| `<config dir>/public-write-rules.json` | Always-allow rules scoped to every workspace of this OS user | None |
| `.workbench/classification-review.json` | `{"mandatory": true\|false}` in the open profile | Off. Ignored in enterprise, where Review is mandatory |
| `.workbench/state/classification_queue.json` | Items waiting for a label | Empty |
| `.workbench/state/graph-outbox.jsonl` | Remote proposals | Empty |
| `.workbench/share.json` | Present after a publish. Personal MCP servers are withheld | Absent means a private workspace |
| `.curator/meta-ontology.yaml` | Local types for ontology compare | Created empty when a compare runs |
| `.curator/ontology-map/<mount>.yaml` | Recorded compare result | Absent means no rename on propose |

The config dir is `~/.config/switchbay`, or
`%LOCALAPPDATA%\switchbay\config` on Windows. `XDG_CONFIG_HOME`
overrides the non-Windows path.
