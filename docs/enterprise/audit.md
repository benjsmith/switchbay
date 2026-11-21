# Audit log

[Enterprise security](index.md)

Mounts, source calls, refusals, declassification, and Presidio
toggles append one JSON line per event. The file stores ids and
reasons. It does not store page bodies, source payloads, prompts, or
model replies.

## Where it lives

```
<state directory>/audit/<16 hex chars of the workspace path>/audit.jsonl
```

The state directory is the per-user directory in
[Controls](controls.md#caches-and-what-a-publish-ships). The 16
characters are the start of the SHA-256 of the workspace's resolved
path. Two workspaces do not share a file. A second OS user does not
see this user's file.

The directory is created mode `0700` and the file mode `0600` on
POSIX, best-effort. The file is not encrypted, not signed, and not
copied anywhere. A person who can write the file can edit history.
Publish skips a path named `audit`, and the file is not inside the
workspace, so a GitHub publish does not ship it.

Lines are appended. There is no rotation and no retention setting
that this file honours. `sources.capture_retention_days` is in the
policy object (default `0`) and is not read.

## What a line contains

Every line has `ts` (UTC, `YYYY-MM-DDTHH:MM:SSZ`), `event`, and
`workspace` (the full path). Other fields are added per event and
omitted when they are empty.

| Event | When | Extra fields |
|---|---|---|
| `confidential_read` | A federated search hit or remote page read at `confidential` or `restricted` | `session`, `label`, `source` (mount id or `search`) |
| `declassify` | A person lowers a page, or lowers a session label | `path` or `session`, `before`, `after` (`public`), `reason` |
| `refused_write` | A write, mount, import, snapshot, or source call was refused | `why`, and where relevant `path`, `mount`, `source`, `tool`, `capture_id` |
| `mount_add` | A mount was saved | `mount`, `kind`, `graph_id` |
| `remote_proposal` | A remote change was queued or sent | `mount`, `change_id`, `state`, `path` |
| `source_call` | A source tool returned, allowed or denied by the source payload | `source`, `tool`, `policy_outcome`, and `capture_id` when allowed |
| `snapshot` | A capture or a remote page was copied into `vault/ext` | `capture_id` or `path`, `mount`, `rev` |
| `presidio` | The workspace Presidio toggle changed | `enabled`, `user` (OS user name) |
| `public_write_allow` | OK, or Always allow, on a public write | `scope` (`once`, `global`, or `workspace`), `mount` or `rule_id` |

The overlap warning on declassification is returned to the caller.
It is not its own audit event. The `declassify` line still has the
reason the person typed.

## What is not recorded

- Ordinary local wiki reads, including a local page marked
  confidential.
- Chat prompts, tool arguments (except source-call arguments, which
  are in the capture file, not in this log), and model replies.
- The text of exclusion rules. Those live in the workspace file.
- Whether a JWT was valid. JWT validation is not on the connection
  path. See [Mounted graphs](graphs.md).
- Page views in the editor, file opens, and shell commands. Those
  follow the daemon log and the existing permission cards, not this
  file.
- A successful local page edit that is not a declassification or a
  remote proposal.

The capture file for a source call is separate. It lives under
`<state directory>/captures/<workspace-hash>/` and does hold the
returned text, rows, and arguments. That is the record of what was
fetched. The audit line for the same call holds the ids only.
Sharing the workspace does not share the capture file.

## The daemon log is a different file

Process logging goes to `switchbay-daemon.log`:

| OS | Path |
|---|---|
| macOS | `~/Library/Logs/switchbay-daemon.log` |
| Windows | `%LOCALAPPDATA%\switchbay\logs\daemon.log` |
| Linux | `$XDG_STATE_HOME/switchbay/daemon.log` or `~/.local/state/switchbay/daemon.log` |

`SWITCHBAY_DAEMON_LOG` overrides it. The file rotates at 100 MB and
keeps one previous file. Successful polls of `/api/health` and
`/api/runs/active` are not written. This log is for diagnosing the
daemon. It is not the audit log above.
