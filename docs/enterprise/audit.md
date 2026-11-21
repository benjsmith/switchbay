# Audit

`<state directory>/audit/<16 hex chars of the workspace path>/audit.jsonl`

One JSON object per line. Fields are ids and reasons. Page bodies, source payloads, prompts, and model replies are not in this file. The capture file under `captures/` holds the source payload. Sharing the workspace does not share either file.

Every line has `ts` (UTC), `event`, and `workspace` (full path). The directory is mode `0700` and the file mode `0600` on POSIX, best-effort. The file is not signed, not shipped, and not rotated. A person who can write it can edit it.

| Event | When | Extra fields |
|---|---|---|
| `confidential_read` | A read at `confidential` or `restricted` | `session`, `label`, `source` |
| `declassify` | A person lowers a page or a session label | `path` or `session`, `before`, `after`, `reason` |
| `refused_write` | A write, mount, import, snapshot, source call, Presidio hit, or exclusion rule refused | `why`, and where relevant `path`, `mount`, `source`, `tool`, `entities` |
| `mount_add` | A mount was saved | `mount`, `kind`, `graph_id` |
| `remote_proposal` | A remote change was queued or sent | `mount`, `change_id`, `state`, `path` |
| `source_call` | A source tool returned | `source`, `tool`, `policy_outcome`, `capture_id` when captured |
| `snapshot` | A capture or remote page was copied into `vault/ext` | `capture_id` or `path`, `mount`, `rev` |
| `import_apply` | An import passed the scrub | `path` |
| `quarantine` | An import was quarantined | `path`, `findings` |
| `capture_prune` | Old captures were deleted | `removed`, `days` |
| `presidio` | The workspace Presidio toggle changed | `enabled`, `user` |
| `public_write_allow` | OK, or Always allow | `scope` (`once`, `global`, `workspace`), `mount` or `rule_id` |

The overlap warning on declassification is returned to the caller. It is not its own event. Ordinary local edits that are not a declassification or a remote proposal are not in this log. Shell commands and editor opens are not in this log.

The daemon log is separate: `~/Library/Logs/switchbay-daemon.log` on macOS, `%LOCALAPPDATA%\switchbay\logs\daemon.log` on Windows, `$XDG_STATE_HOME/switchbay/daemon.log` on Linux. `SWITCHBAY_DAEMON_LOG` overrides it. It rotates at 100 MB and keeps one previous file. Successful polls of `/api/health` and `/api/runs/active` are omitted.
