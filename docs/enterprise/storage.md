# Storage

Switch Bay has no hosted region. Files sit on the machine. A sync client uploads a workspace only when the folder is inside that client. GitHub publish is a separate action and is off in the enterprise profile.

| Data | Location | In a GitHub publish? |
|---|---|---|
| Wiki, vault, figures, sketches, plots | The workspace folder | Yes, except files the export cap blocks. `vault/` is included only when the person includes it |
| Mount file, exclusion rules, Presidio flag, Review queue, outbox, default chat database | `<workspace>/.workbench/` | No. The managed gitignore always excludes `.workbench/` |
| Chat history when local history is on | State directory `workspaces/<slug>-<hash>/state/conversations.db` | No |
| Audit log, session labels, captures, live-page cache, snapshot copies, graph-token files, managed llama.cpp weights | Per-user state directory | No |
| API keys and graph tokens | OS keychain, service `switchbay` | No |
| Admin policy | The MDM path or `SWITCHBAY_ADMIN_POLICY` | No |
| Daemon log | See [Audit](audit.md) | No |

State directory:

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/switchbay` |
| Windows | `%LOCALAPPDATA%\switchbay` |
| Linux | `$XDG_STATE_HOME/switchbay` or `~/.local/state/switchbay` |

`SWITCHBAY_STATE_DIR` overrides it. The directory is per OS user. Two people on one machine do not share it. A workspace hash keeps two folders with the same name apart.

`vault/ext/` is inside the workspace. It is part of a vault publish when the file's effective label is `public`. Quarantined imports are under `vault/ext/.quarantine/`.

A snapshot is a second copy of a remote wiki, under `mounts/`, pinned at a revision. Deleting the mount row does not delete that copy. A live mount keeps one JSON file per page per revision under `graph-cache/`. Both trees are mode `0700` / `0600`.

Enterprise refuses a serve path, an add, a switch, and the default home when the detector in [Controls](controls.md) says the folder is synced, unless `paths.trust_boundary` or `allow_synced_workspaces` says otherwise. Those checks do not disable the sync client.

A slideshow PDF defaults to `<workspace>/vault/exports/<slug>.pdf`. A chosen path is written there instead. A path the sync detector names, outside `paths.trust_boundary`, needs the destination dialog unless `exports.forbid_outside_boundary` is true, in which case it is refused. Certificate encryption also writes `<pdf path>.wrap.json` next to the PDF, mode `0600`, holding the RSA-OAEP wrapped password. The PDF password itself is not written to disk. The audit log records the export. It does not contain the PDF bytes or the password.
