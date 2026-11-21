# Controls

[Enterprise security](index.md)

This page is the control-by-control description: where a workspace
may live, which models may be called, how labels move, who may read
a page, and where caches sit.

## Synced folders

Two checks look for a cloud-sync folder. They do not use the same
detector, and they do not run at the same time.

**Opening the workspace named on the serve command.** In the
enterprise profile, `switchbay serve` refuses that path when it
contains `Mobile Documents`, `/Library/CloudStorage/iCloud`,
`OneDrive`, `Dropbox`, or `Google Drive`, unless the path is equal
to or under an entry in `paths.trust_boundary`. The open profile
does not apply this check. The error names the service and says the
path is outside the trust boundary.

**The default workspace home.** If the daemon has to create a home
(`paths.workspaces_home`, or `~/SwitchBay` when that is unset) and
the enterprise profile has not set `paths.allow_synced_workspaces`
to true, a home that looks synced is refused and no folder is
created. On macOS this detector also treats `~/Desktop` and
`~/Documents` as iCloud. The trust-boundary list does not.

**Adding or switching a workspace in the app** checks that the
folder is under an allowed root: the user's home, `/workspace` when
that directory exists, and any directories in
`SWITCHBAY_WORKSPACE_ROOTS`. It does not apply
`paths.trust_boundary`. After boot, the daemon may also start
serving the last workspace in the registry without repeating the
trust-boundary check.

**Importing a remote page, or saving a source snapshot into the
workspace,** refuses the write when the workspace path itself looks
synced (the first detector, not the Desktop/Documents one) and
`paths.allow_synced_workspaces` is false. Enterprise defaults that
flag to false. The open profile defaults it to true, which skips
the refusal.

The default chat database is
`<workspace>/.workbench/state/conversations.db`. Refusing the
workspace at serve time keeps that file unopened. Settings can move
chat history to the per-user state directory instead
(`rail_history_local`). That move is not a separate trust-boundary
check; the state directory is chosen because it sits outside the
usual sync roots.

## Models

Enterprise allows GitHub Copilot and the local backends llama.cpp,
MLX (macOS only), and Ollama. The other providers are off until
`providers` in the admin file turns one on. That section is
applied.

Local llama.cpp and MLX servers are started with `--host 127.0.0.1`
on ports `8878`–`8887`. Ollama is expected at
`http://127.0.0.1:11434`. Copilot sign-in is GitHub's device flow;
chat then goes to `api.githubcopilot.com` (or the host derived from
`copilot.host`). Enterprise egress refuses other HTTPS hosts unless
they are on `network.egress_allowlist`, or a feature flag has added
its own hosts (Hugging Face when downloads are on, GitHub when
in-app update is on).

There is no rule that a weight file must sit under
`paths.trust_boundary`. Managed llama.cpp weights are stored under
the per-user state directory, in `models/`. MLX can load a local
snapshot or a Hugging Face repo id. The trust-boundary list applies
to workspace folders, not to model files.

## Labels

Four labels, low to high: `public`, `internal`, `confidential`,
`restricted`. A label the software does not recognise is treated as
`restricted`. A page with no `classification:` line is `public`.

The label is the `classification:` line in the page's frontmatter.
A page's effective label is the highest of its own label and the
labels of pages it cites with `(vault:…)`, `(table:…)`,
`(figure:…)`, `(graph:…)`, or `(capture:…)`. Rewriting the prose
does not lower it. A graph citation contributes the label stored
when that revision was read. A capture citation with no stored
label is treated as `confidential`.

A write onto a mount is refused when the page's effective label is
above that mount's ceiling. The local wiki's ceiling is
`restricted`. A remote mount's ceiling defaults to `public` unless
the mount entry sets another. The policy object carries a
`max_ceiling_by_trust` map (`external` → `public`, `org` →
`confidential`, `own` → `restricted`). No check reads that map, so
a mount entry can name a ceiling above the map.

## Session label, the chat badge, and publish

When a federated search hit or a remote page read carries
`confidential` or `restricted`, the current session id is raised to
that label if it is higher than the label already stored. The read
is written to the audit log. An `internal` or `public` read does
not raise the session and is not audited as a confidential read.
Reads of the local wiki do not carry a classification into this
check, so a local confidential page does not raise the session.

A chat turn sets the session id to the thread id, else the run id,
else the word `rail`. The label is stored in a small JSON file
under the per-user state directory (`sessions/<workspace-hash>/labels.json`).

The badge in the chat header polls `GET /api/session/label` and
shows the label when it is above `public`. That request reads the
session id `default`. A chat turn does not use `default`. The badge
therefore stays hidden for a chat that raised some other id.
Lowering the label from the API (`POST /api/session/label`, with
`human_confirmed: true` and a reason of at least 8 characters) also
lowers `default`, and writes a `declassify` audit row.

GitHub publish reads the same `default` label. If that label is
above `public`, publish is refused with "this chat is …". Publish
also refuses any wiki or vault text file (`.md`, `.txt`, `.yaml`,
`.yml`) whose effective label is above `public`, and the preview
lists those paths. Other exports (slideshow PDF, report HTML) do
not apply this cap.

A function that would label an answer as the higher of the session
floor and the labels of the material used is present and is not
called on a chat reply. Chat text is not stamped.

## Permissions on a page

Switch Bay does not run its own permission service. A page may
carry `source_ref:` in its frontmatter, meant for a SharePoint item,
a Unity Catalog object, or a similar id.

Before a federated search hit is returned, each `source_ref` is
checked. The checker is a stub:

- Empty reference: the hit is kept (treated as a whole-graph read).
- `deny:` — the hit is dropped.
- `readonly:` — the hit can be read. Edit is refused.
- Any other string: the hit is kept. Nothing asks Work IQ or Unity
  Catalog.

When search merges the same item from more than one graph, the
extra copies are kept on an `also` list. A copy whose `source_ref`
the stub refuses is dropped, including when the two graphs described
the item as the same thing. This is the neighbour drop. It runs on
search results. It does not run on the neighbour walk inside one
graph.

Declassification also asks this checker. A page whose `source_ref`
fails the write check cannot be lowered. With the stub, that means
`deny:` and `readonly:` block the edit, and any other reference
allows it.

## Search scope

Each workspace has a mount file,
`<workspace>/.workbench/graph-mounts.json`. Its `read_default` list
is which mounts a search reads when the caller does not pass
`graphs`. The default list is `local` only. `graphs` may be `"all"`,
a comma-separated list of mount ids, or a list. Unknown ids are
dropped. A search that resolves to `local` alone uses the existing
local wiki search and does not fan out.

Scores from different graphs are not compared raw. Hits are merged
with reciprocal rank fusion (constant 60), multiplied by a trust
weight: `own` 1.0, `org` 0.8, `external` 0.5. A graph that does not
answer is listed under `unavailable`, and the note names which
graphs did answer. A path walk stays inside one graph.

## Exclusion rules

Settings → Permissions has a list of exclusion rules. Each rule is
a sentence and one of **Allow**, **Ask**, or **Deny**. They are
stored in `<workspace>/.workbench/exclusion-rules.json`.

On a chat turn the rules are appended to the hidden system prompt,
with text that says they outrank the user message, tool results, and
page text, and that a line such as "ignore previous instructions"
does not change them. The prompt also says the check is only as
strong as the model.

A deterministic check exists beside that prompt. It strips a phrase
of the form "ignore … previous/prior/above/all … instructions", then
looks for the rule sentence as a substring of the action, case
insensitive. Deny wins over ask; ask wins over allow. An unknown
verdict becomes ask. A hook (`set_classifier`) can replace that
check later. Nothing in the tool path calls the check, so a Deny
rule does not stop a tool from running. The unit test covers the
function; the browser test covers saving a rule in Settings.

## Declassification

`declassify_page` lowers a page to `public`. It requires all of:

- `human_confirmed` true. Without it the call is refused and audited.
- A reason of at least 8 characters.
- Edit access on the page (the stub above).
- Declassification allowed by policy. Enterprise forbids it. The
  open profile allows it. `sources.declassify` in the admin file
  would change this, and that section is not loaded, so the profile
  default stands.

The page's `classification:` line becomes `public`, and a
`declassified: true` line is added. The audit row records the path,
the label before, `public`, and the reason. There is no step that
lowers `restricted` to `confidential`; the only landing label is
`public`.

After the write, a warning is attached when the new public text
still shares a number of two or more digits, or a phrase of three
or more words of four or more letters, with any page in the wiki
whose own frontmatter is `confidential` or `restricted`. Up to four
shared items are named. The warning does not undo the write and
does not block a later publish by itself. Publish still applies the
citation rule, so a public page that cites a confidential page
remains blocked.

## Review

A source call that returns no classification is added to the Review
queue (`<workspace>/.workbench/state/classification_queue.json`) and
marked `needs_classification`. The Reviews tab lists those items and
can set `public`, `internal`, `confidential`, or `restricted`.

In the enterprise profile Review is mandatory. In the open profile
it is off until the workspace file
`.workbench/classification-review.json` sets `"mandatory": true`.
`POST /api/classification/mandatory` can set that file, and refuses
to do so in the enterprise profile ("an admin sets review"). The
admin key `classification_review.mandatory` would let an admin turn
enterprise Review off. That key is not loaded.

Mandatory changes one field on the tool result: `usable` is false
when the item has no label. The result still includes the text and
the rows. Setting a label updates the queue item. It does not write
the label back onto the capture file, so a later `(capture:…)`
citation still sees an empty label and is treated as
`confidential`.

## Presidio and public writes

Presidio is the intended scan for personal data on a public write.
It is not a dependency of Switch Bay. The product does not call it
on the text.

What runs today:

- Enterprise defaults public writes to off (`public_writes.allowed`
  is false, and the connections list is empty). A write whose
  effective label is `public`, onto a mount whose ceiling is
  `public`, is refused with "public writes are limited to configured
  connections". The refusal is audited. The dialog is not reached.
- A write that is not public skips this gate.
- In the open profile public writes are allowed. If the workspace
  has Presidio turned off, the write proceeds and the result carries
  the guidance string below. If the `presidio_analyzer` package
  imports, the write is marked `scanned` and the text is not
  analyzed. If the package does not import and the person has not
  chosen Always allow, the tool result asks for a dialog with
  choices `ok`, `always`, and `cancel`.

The dialog is in the app: **OK**, **Always allow**, **Cancel**. OK
audits a one-time allow. Always allow appends a rule "Public write
without Presidio" to the global file
`<config dir>/public-write-rules.json` (the config dir is
`~/.config/switchbay`, or `%LOCALAPPDATA%\switchbay\config` on
Windows). Settings → Permissions shows that rule with a **This
workspace only** button, which moves it to
`<workspace>/.workbench/public-write-rules.json`. Cancel audits a
refusal.

No code path opens the dialog. The browser test opens it by sending
the `sy:public-write` event. A write that needs a choice returns the
choice list to the caller; the tool schema does not include a field
for that choice.

Settings → Permissions also has **Presidio scan**, on by default
(`<workspace>/.workbench/presidio.json`, missing file means on).
Turning it off stores the flag, audits `presidio` with the OS user
name, and shows:

> Presidio is off in this workspace, so public writes are not scanned
> for personal data. You are responsible for complying with the
> policies and regulations that apply.

The dialog copy, when it is shown, is: "Presidio is not scanning
this write. Continue only if the text has no personal data. You take
responsibility for that."

The code can hide that toggle: `public_writes.user_control` false,
and `public_writes.enabled_users` a list of OS user names who still
have scanning on. Those keys are not loaded from the admin file, so
every user can toggle the workspace flag. See
[IP and legal](legal.md).

On a public mount, a second hook loads curiosity-merge's
`presidio_gate.py` when that skill is installed. If Presidio is
missing there, the hook reports skipped and does not refuse. If the
module loads, the hook returns not blocked, without asking the gate
to inspect the text.

## Caches, and what a publish ships

Caches, captures, tokens, audit rows, and session labels are stored
per OS user, under the state directory:

| OS | State directory |
|---|---|
| macOS | `~/Library/Application Support/switchbay` |
| Windows | `%LOCALAPPDATA%\switchbay` |
| Linux | `$XDG_STATE_HOME/switchbay` or `~/.local/state/switchbay` |

`SWITCHBAY_STATE_DIR` overrides it. Each workspace is a hash of its
path, so two folders with the same name do not share a cache. A
second OS user has a different home and a different state directory.
Nothing here is encrypted.

Directories created for the audit log, session labels, and captures
are mode `0700`, and the files are mode `0600`, on POSIX. The
`chmod` is best-effort. On Windows the privacy check reports the
file as private without reading ACLs. Snapshot copies
(`mounts/`) and the live-page cache (`graph-cache/`) are under the
same state directory and do not set those mode bits. A graph token
that cannot be stored in the OS keychain is written to
`graph-tokens/<mount-id>.json` at mode `0600`.

Publish (and the publish preview) skips a workspace-relative path
that contains `.workbench`, `.grok`, `.git`, `captures`,
`graph-cache`, `graph-tokens`, `audit`, or `mounts`. The caches
above live outside the workspace, so they are not in the git tree
anyway. `.workbench/` is always in the managed `.gitignore`, which
also keeps chat history, mount config, exclusion rules, and the
Review queue out of a published repo.

`vault/ext/` is inside the workspace. It is included when the person
publishes with the vault included, unless a file's effective label
is above `public`. A personal MCP server with no
`allowed_workspaces` list is offered to a private workspace and left
out of a workspace that has `.workbench/share.json` (a workspace
that has been published). A server that names
`allowed_workspaces` is offered only for those paths.
