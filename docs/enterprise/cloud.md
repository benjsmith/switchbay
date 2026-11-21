# Cloud and storage

[Enterprise security](index.md)

Switch Bay has no Switch Bay cloud. Data sits in folders on the
machine. Something reaches another service only when a feature in
[Network](network.md) sends it, or when the workspace folder itself
is inside a sync client the person (or the company) already runs.

## Where data is stored

| Data | Where | Syncs with the workspace folder? |
|---|---|---|
| Wiki pages, vault files, figures, sketches, plots | The workspace directory the person chose | Yes, if that directory is inside iCloud, OneDrive, Dropbox, Google Drive, or a similar client |
| Mount list, exclusion rules, Presidio flag, Review queue, chat history (default), proposals, outbox | `<workspace>/.workbench/` | Yes, same condition. Omitted from a GitHub publish |
| Chat history when "local history" is on | Per-user state directory, `workspaces/<slug>-<hash>/state/conversations.db` | No |
| Audit log, session labels, source captures, live-page cache, snapshot copies, graph tokens (file fallback), managed model weights | Per-user state directory. See [Controls](controls.md) | No |
| Provider API keys, graph tokens when a keychain exists | OS keychain, service name `switchbay` | No |
| Admin policy | The MDM path or `SWITCHBAY_ADMIN_POLICY`. The daemon never writes it | No, unless an admin placed the file in a synced folder |
| Daemon log | `~/Library/Logs` on macOS, `%LOCALAPPDATA%\switchbay\logs` on Windows, the XDG state dir on Linux | No |

The per-user state directory is:

- macOS: `~/Library/Application Support/switchbay`
- Windows: `%LOCALAPPDATA%\switchbay`
- Linux: `$XDG_STATE_HOME/switchbay` or `~/.local/state/switchbay`

`SWITCHBAY_STATE_DIR` overrides it. It is one directory per OS user.
Workspaces are not a shared store: two people on one machine have
two homes, two state directories, and two keychains. A published
workspace does not include `.workbench/`, and a personal MCP server
is not offered inside a workspace that has been published.

## What the enterprise profile does about sync

Enterprise will not create the default home (`~/SwitchBay`, or
`paths.workspaces_home`) when that path looks synced, unless
`paths.allow_synced_workspaces` is true. On macOS, `~/Desktop` and
`~/Documents` count as iCloud for this home check.

Enterprise also refuses the workspace path passed to `switchbay serve`
when that path looks like iCloud (`Mobile Documents` or
`/Library/CloudStorage/iCloud`), OneDrive, Dropbox, or Google Drive,
unless it is under `paths.trust_boundary`. `~/Desktop` and
`~/Documents` are not caught by this check.

Adding a folder from the app does not repeat the trust-boundary
check. Importing a remote page or snapshotting a source into a
workspace whose path looks synced is refused in enterprise, because
`allow_synced_workspaces` defaults to false. The aim of that refusal
is to keep a copy of external data from being uploaded by the sync
client that owns the folder.

None of these checks disable the sync client. They refuse to use a
folder the sync client would upload. A workspace on a normal local
disk is not uploaded by Switch Bay.

## What a sync client would upload

If a workspace is on a local disk, the sync client does not see it.

If a workspace is inside a synced folder and the checks above were
not applied (open profile, or an allowlisted path, or a folder added
from the app), the sync client uploads the workspace the way it
uploads any other folder. That includes `wiki/`, `vault/` (including
`vault/ext` imports), and `.workbench/` (chat history, mount config,
exclusion rules, Review queue). It does not include the state
directory, so audit logs, captures, graph caches, snapshot copies,
and tokens stay on the machine.

GitHub publish is a separate, explicit action. Enterprise turns it
off. The open profile publishes only when the person asks, after a
preview, and refuses pages above `public`.

## Copies that are not the workspace

A snapshot mount is a git clone or a directory copy under the state
directory. It is a second copy of someone else's wiki, on this
machine, pinned at a revision. It is not inside the workspace and
not in a GitHub publish. Deleting the mount file does not by itself
delete that copy.

A live mount does not keep a full wiki. It keeps the pages that were
read, one JSON file per page per revision, under `graph-cache/`.
Those files are also outside the workspace.

Model weights downloaded for llama.cpp land in the state directory
`models/` folder. MLX and Ollama keep their own caches. Enterprise
does not download Hugging Face weights unless
`hf_model_download` is turned on. Weights already on disk still load.
