# Controls

## Synced folders

One detector names iCloud (`Mobile Documents`, `/Library/CloudStorage/iCloud`, and on macOS `~/Desktop` and `~/Documents`), OneDrive, Dropbox, and Google Drive. The boot-time sync hint and the trust-boundary check use that detector.

In the enterprise profile:

- `switchbay serve` refuses the workspace path when it is in one of those folders unless the path is under `paths.trust_boundary`.
- Adding or switching a workspace in the app runs the same check. `workspaces.register` does too.
- The default home (`paths.workspaces_home`, or `~/SwitchBay`) is not created when it looks synced, unless `paths.allow_synced_workspaces` is true.
- Importing a remote page or snapshotting a source into a synced workspace is refused when `allow_synced_workspaces` is false.

The open profile does not apply the trust-boundary check. It defaults `allow_synced_workspaces` to true.

The default chat database is `<workspace>/.workbench/state/conversations.db`, so refusing the workspace keeps it unopened. The optional local-history setting stores it under the state directory.

## Classification ceiling

A mount's effective ceiling is the lower of its `ceiling` and `graph_mounts.max_ceiling_by_trust` for its trust (`external` → `public`, `org` → `confidential`, `own` → `restricted`, unless the admin file sets other values). Saving a mount above that maximum fails. A write whose effective label is above the effective ceiling is refused and audited.

## Public writes and Presidio

A write is public when the page's effective label and the mount ceiling are both `public`.

`public_writes.allowed` false (the enterprise default) permits a public write only when the mount id is in `public_writes.connections`. Otherwise the write is refused before any scan.

When the user is in scope for Presidio (`public_writes.user_control`, or `enabled_users` when an admin has taken the toggle away):

- If Presidio is installed and `AnalyzerEngine` loads, `analyze` runs on the text. Entity types are recorded. A hit refuses the write. A clean result is `presidio: scanned`. The text is not marked scanned unless `analyze` returned.
- If the package is missing, or the analyzer fails to load, the result is `needs_dialog` with choices `ok`, `always`, and `cancel`, unless an Always-allow rule is already stored.
- The daemon broadcasts `public_write`. The app opens the dialog: **OK** (one write, audited), **Always allow** (a global rule), **Cancel** (audited refusal). Settings can move a global rule to `.workbench/public-write-rules.json`.

Turning the workspace toggle off (`user_control` true) skips the scan and returns the guidance string in [Licensing and IP](legal.md). `user_control` false rejects the toggle. `enabled_users` is the list of OS user names who still have scanning on.

Presidio 2.2.366 is an optional dependency group, not part of a normal install. The spaCy model it needs is not downloaded by that group. Without the model, the analyzer fails to load and the dialog is used.

## Review

A source result with no classification is queued in `.workbench/state/classification_queue.json`. In the enterprise profile the queue is mandatory unless `classification_review.mandatory` is false. A mandatory item is returned without `text` or `rows` (`withheld: true`, `usable: false`). Setting a label on the Reviews tab writes that label onto the capture file. A later `(capture:…)` citation reads it.

The open profile leaves Review off until `.workbench/classification-review.json` sets `mandatory`. The enterprise API refuses to let the workspace file change that.

## Imports

`import_graph_page` and a source snapshot stage the file, run the scrub, and either write `vault/ext/…` or quarantine.

The built-in scrub flags "ignore … previous/prior/above/all … instructions", a `<script` tag, and `javascript:`. When curiosity-engine's `scripts/scrub_check.py` is installed, that script runs as well. A hit is moved to `vault/ext/.quarantine/`, the import path is removed, a line is appended to `.workbench/state/import-quarantine.jsonl`, and the audit event is `quarantine`. A clean file is the one a page can cite. It is marked `untrusted: true` and wrapped in `BEGIN FETCHED CONTENT` / `END FETCHED CONTENT`.

A remote proposal whose body contains `untrusted: true`, `UNTRUSTED REMOTE CONTENT`, or `vault/ext/` is stored with `provenance: untrusted-import`. Other proposals are `provenance: workspace`.

## Remote writes

`propose_graph_write` sends `mode: remote` or `mode: both` (remote proposal plus a local Reviews proposal). The change id is the SHA-256 of the graph id, path, base revision, and content. A repeat returns the existing outbox row.

The write is direct only when all of these hold: the mount's `write` is `direct`, the live server reports `rights.direct_granted`, the workspace file has `direct_writes` true, and `graph_mounts.remote_write` is neither `propose` nor `none`. Both profiles default `remote_write` to `propose`, so the change stays a proposal. `none` forbids it. Enterprise and open both read this from the admin file when the section is present.

A live `conflict` response asks curiosity-merge's `page_merge.py` when the ancestor text and the other side are both known. Otherwise neither copy is overwritten, and a conflict card is added.

## Export cap

GitHub publish and slideshow PDF export call the same check. If the active session label is above `public`, the export is refused: `this chat is <label>; export is capped at that label`. Publish also refuses any `.md`, `.txt`, `.yaml`, or `.yml` file under `wiki/` or `vault/` whose effective label is above `public`.

## Caches

Audit rows, session labels, and captures are mode `0700` directories and `0600` files. Snapshot trees and the live-page cache (`graph-cache/`) use the same bits. `chmod` is best-effort. On Windows the privacy check does not read ACLs. Nothing in these directories is encrypted.

`sources.capture_retention_days` greater than 0 deletes capture files older than that many days, on the next source call. `0` keeps them.
