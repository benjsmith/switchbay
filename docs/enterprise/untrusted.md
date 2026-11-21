# Untrusted content

[Enterprise security](index.md)

Material that did not start in this workspace is marked, and a
remote change is a proposal. The markers are text. They do not stop
the model from reading the material.

## vault/ext

Two tools copy remote material into the workspace, under `vault/ext`,
and do not turn it into a wiki page.

**A remote page** (`import_graph_page`) is written to
`vault/ext/graphs/<mount>/<path>.md`. The frontmatter sets
`type: source`, `untrusted: true`, the page's classification, and
`source_url` as `<graph id>@<revision>`. The body is wrapped in
`<!-- BEGIN FETCHED CONTENT graph-import -->` … `<!-- END FETCHED CONTENT -->`.

**A source capture** (`call_source` with `snapshot: true`) is written
to `vault/ext/<kind>/<YYYY-MM-DD>/<capture id>.md`, with the same
`untrusted: true` line, the capture's classification, the tool name,
and a SHA-256 of the normalised result. The body is wrapped in
`<!-- BEGIN FETCHED CONTENT source-capture -->` … `<!-- END FETCHED CONTENT -->`.

Both writes are refused when admin policy forbids snapshots
(`sources.snapshot` set to `forbid`; the default is `allowed`, and
the admin section is not loaded, so the default stands) or when the
workspace folder itself sits in a synced directory and
`paths.allow_synced_workspaces` is false. Enterprise defaults that
flag to false. The refusal is audited.

The capture that has not been snapshotted stays under the per-user
state directory, not in the workspace. See [Audit log](audit.md).

## Framing on a read

A page read from a mount whose trust is `org` or `external` is
returned with this wrapper, using the graph id and the revision:

```
UNTRUSTED REMOTE CONTENT — graph:<graph id>@<revision>
…page text…
END UNTRUSTED REMOTE CONTENT
```

A mount with trust `own` is returned without the wrapper. The local
wiki is `own`. Search hits from any non-own mount set
`untrusted: true` on the hit. The hit's snippet is the source text,
not the wrapper.

## Scrub

`ce_scrub_check` is an agent tool. It runs curiosity-engine's
`scrub_check.py` on a wiki or vault path (`--mode wiki` by default).
The chat instructions tell the agent to run a score check, then this
scrub, then commit a wiki page. Importing a page or snapshotting a
capture does not run the scrub. If curiosity-engine is not
installed, the tool fails the way other curiosity-engine tools fail.

## Workspace merge

Merging two workspaces is a separate path. Switch Bay runs
curiosity-merge's `merge.py` (stage, then apply) when that skill is
installed. The skill's own pipeline includes trust gates, a
quarantine step, and an unmerge manifest. Switch Bay does not
reimplement those steps. Graph imports and source snapshots are not
sent through `merge.py`, and there is no federation quarantine
directory.

If the skill is missing, the merge stops with an error that names
the expected `scripts/merge.py` path. Ontology comparison for a
remote write has a smaller fallback, described below.

## Remote writes

`propose_graph_write` sends a page to a remote mount. `mode` is
`remote` (the proposal only) or `both` (the proposal, plus a local
proposal in the Reviews queue). The local wiki is not a target of
this tool.

The change is a proposal unless every one of these is true: the
mount's `write` is `direct`, the live server reports
`rights.direct_granted`, the workspace file has `direct_writes`
true, and policy `graph_mounts.remote_write` is something other than
`propose` or `none`. Both profiles default `remote_write` to
`propose`. The admin file section that would change it is not
loaded, so a direct remote write does not happen. Enterprise and
open behave the same on this point: the change stays a proposal.
`remote_write: none` would forbid the write entirely, and that value
is also unreachable from the admin file today.

Before the proposal is sent:

- The page is adapted to the local ontology when a mapping file
  exists for that mount. If curiosity-merge's `ontology_align.py` is
  installed it does the adapt. Otherwise a type rename is applied,
  and a type that is not in the built-in set becomes `concept`.
- The page is refused when its effective label is above the mount
  ceiling. A confidential page cannot be proposed onto a public
  snapshot. The refusal is audited.
- A public page on a public mount goes through the public-write gate
  in [Controls](controls.md#presidio-and-public-writes).

The proposal id is the SHA-256 of the graph id, the path, the base
revision, and the normalised content. Sending the same change again
returns the existing row and does not create a second one. Rows are
appended to `<workspace>/.workbench/state/graph-outbox.jsonl`.

A live server that answers `conflict` asks curiosity-merge to merge
when the ancestor text and the other side's text are both known.
When they are not, neither copy is written over the other, and a
conflict card is added to the proposal list: "Both copies of this
page changed. Neither was overwritten." A snapshot mount does not
receive a live propose call; the outbox row is still recorded with
state `queued`.

## What the model is told

The chat instructions say: cite a remote page as
`(graph:<mount>/<path>@<revision>)` using the revision the tool
returned, and do not copy a page above a mount's ceiling into that
mount. The ceiling check above is what actually refuses the write.
The instruction is in addition to that check.
