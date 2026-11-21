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

## Declassification

`declassify_page` sets the page to `public` and `declassified: true`. The only check is edit access on that page. A `readonly:` or `deny:` `source_ref` refuses the call. There is no reason field, no second approver, and no enterprise admin switch. The audit row has `user`, `ts`, `path`, `before`, and `after`. The overlap warning is unchanged: it names shared numbers or phrases and does not undo the write.

## Export

GitHub publish refuses when the active session label is above `public`: `this chat is <label>; export is capped at that label`. It also refuses any `.md`, `.txt`, `.yaml`, or `.yml` file under `wiki/` or `vault/` whose effective label is above `public`.

Slideshow PDF export does not use that cap. The file label is the higher of the session floor and the labels on the included slides, citations, and `data-classification` attributes. A confidential session writes a confidential PDF in one click. The call is refused when:

- that label is above `exports.clearance` for the OS user (`exports.clearance_by_user` when set for that user) or above `exports.max_ceiling`, whichever is lower. An unknown value in either setting is treated as `public`.
- a slide `source_ref` is `deny:`, the catalog returns `export: false` or denies the read, or the catalog call errors. `readonly:` may be exported. Work IQ uses `fetch`. Unity Catalog uses `get_permissions`.
- an exclusion rule's decision is Deny and its text occurs in the export action (slug, label, source refs, slide headings and bodies). Ask does not stop the export.

The default destination is `vault/exports/<slug>.pdf`. A destination the sync detector names (iCloud, OneDrive, Dropbox, Google Drive), and that is not under `paths.trust_boundary`, is `outside`. The response is `needs_dialog` with choices `ok`, `always`, and `cancel` — the same three choices as the public-write dialog. OK writes this file. Always allow stores a global rule in the config dir (`export-destination-rules.json`) and later outside destinations skip the dialog. Cancel writes `refused_write` and no file. A path inside the workspace or under `paths.trust_boundary` is `inside` and is not asked. `exports.forbid_outside_boundary` true refuses outside destinations with no dialog, including after Always allow.

A label above `public` is drawn as a header band and a footer band on every page (`SWITCHBAY` plus the label). `public` has no band. Info-dict and XMP metadata are written for every label: label, workspace path, OS user, UTC timestamp, and Switchbay version. The XMP namespace is `urn:switchbay:classification:1.0`. The same values are `pdfx:Switchbay*` custom properties.

`exports.purview.labels` maps a Switchbay label to a Purview label GUID. When the GUID is set, the Info dict and XMP also carry `MSIP_Label_<guid>_Enabled`, `Method` (`Privileged`), `Name`, `SetDate`, `ContentBits`, `ActionId`, and `SiteId` when `exports.purview.site_id` is set. `ContentBits` is 3 when the bands are drawn (header and footer) and adds 8 when local AES-256 encryption is applied. This metadata does not encrypt the file.

`exports.purview.endpoint`, when non-empty, receives the labelled PDF and the stored file is only the PDF it returns. `transport` `http` (the default unless the URL ends in `/mcp`) is a POST of the PDF bytes with `X-Switchbay-Label`, `X-Switchbay-Label-Id`, `X-Switchbay-Site-Id`, `X-Switchbay-User`, `X-Switchbay-Workspace`, and `X-Switchbay-Version`. `transport` `mcp` calls `apply_sensitivity_label` with `pdf_base64` and reads `pdf_base64` from the tool result. The bearer token is the keychain entry for `exports.purview.source_id` when that id is set. The timeout is 4 seconds, the same as a catalog call, with no retry. Enterprise egress applies. A non-PDF body, a non-2xx status, a timeout, a transport error, or an egress refusal is `refused_write` and no file is written. Local password or certificate encryption is not applied when the endpoint is set.

With no endpoint, the save request may include `encrypt.mode` `password` or `certificate`. Neither is required. Password mode is PDF standard security, revision 6, AES-256 (`/CFM /AESV3`, key length 256). Certificate mode generates a random password, encrypts the PDF the same way, and writes `<file>.wrap.json` (mode `0600`) containing the password wrapped with RSA-OAEP-SHA256 to the recipient RSA public key or certificate (2048 bits or more). That is not Adobe PubSec and not RMS. The password is not stored and is not in the audit log.

## Caches

Audit rows, session labels, and captures are mode `0700` directories and `0600` files. Snapshot trees and the live-page cache (`graph-cache/`) use the same bits. `chmod` is best-effort. On Windows the privacy check does not read ACLs. Nothing in these directories is encrypted.

`sources.capture_retention_days` greater than 0 deletes capture files older than that many days, on the next source call. `0` keeps them.
