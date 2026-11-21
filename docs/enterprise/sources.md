# External sources

[Enterprise security](index.md)

Work IQ, Databricks Genie, AWS Context, and AWS Quick are sources,
not graphs. A source is a row in the same file as mounts,
`<workspace>/.workbench/graph-mounts.json`, under `sources`. A call
is captured on this machine. Nothing from the call becomes a page
the wiki can cite unless someone snapshots it into `vault/ext`.
That file carries the classification. See
[Untrusted content](untrusted.md).

## What is implemented

The broker knows a tool list per kind, normalises a JSON result into
text, rows, and links, and writes a capture. The transport used by
`call_source` is an in-memory fake: if the test did not load a
canned response for that tool name, the call returns a denial. The
rail tool does not pass a network transport.

An HTTP class that would POST MCP `tools/call` at the source URL,
with a bearer token and a 4 second timeout, exists in the source
tree. No tool, route, or setting constructs it. Calling a real Work
IQ, Genie, AWS Context, or AWS Quick endpoint is not available.

The unit tests and the leakage tests drive the broker with the fake.
They do not prove a tenant, a warehouse, or an AWS account.

In the enterprise profile `sources.allowlist` is empty, and the
admin section that would fill it is not loaded, so every source call
is refused with "source is not on the admin allowlist" before the
fake runs. The open profile's allowlist is `*`.

Act tools (the Work IQ writes) are hidden unless
`sources.allow_act_tools` is true. The default in both profiles is
false. That key is also in the unloaded admin section, so act tools
stay hidden.

## Kinds and tool names

These are the names the broker accepts. They match the vendor's
documented tools where Switch Bay could read them. They are not a
live client.

**Work IQ** (`workiq`). Read: `fetch`, `retrieve`, `ask`,
`get_schema`, `search_paths`. Act, hidden by default:
`create_entity`, `update_entity`, `delete_entity`, `do_action`,
`call_function`. A live tenant and admin consent are not part of
this product. The access checker that would ask Work IQ about a
`source_ref` is the stub in [Controls](controls.md#permissions-on-a-page).

**Databricks Genie** (`databricks-genie`). Read: `genie_ask`,
`genie_poll_response`, `genie_get_query_result`. No act tools. Genie
usage is billed; nothing here points at a live workspace.

**AWS Context** (`aws-context`). Read: `agentic_search`. The public
agentic-search schema was not available when this adapter was
written. The adapter treats returned rows as graph candidates. It
does not create wiki pages. Curation would do that later, from a
snapshot, the same way other vault files are curated.

**AWS Quick** (`aws-quick`). Read: `search_entities`, `get_entity`.
No local Quick graph endpoint was found. The names match the
documented entity graph (people, projects, documents, and the edges
between them). Quick stores that graph in the AWS Quick account.
Switch Bay does not.

A `kind` outside this list has no tools, so a call fails with "has
no tool".

## Classification of a result

The label comes from the source row's `classification` field, if it
is one of the four labels. A `classification` field on the result
can replace it. Sensitivity tags on the result can only raise the
label: `restricted` or `highly confidential` becomes `restricted`;
`confidential` or `secret` becomes at least `confidential`.

If neither the source row nor the result carries a label, the
capture is unlabelled. It is queued for Review and, when Review is
mandatory, marked not usable. The text is still in the tool result.
See [Controls](controls.md#review). A helper that would default Work
IQ, Genie, AWS Context, and AWS Quick to `confidential` is not
called. An unlabelled source stays unlabelled.

A result with `policy_outcome: denied` (or `error: policy_denied`)
is returned as denied, audited as a denied source call, and not
captured.

## How to configure a source

In the open profile, add a row to `sources` in the mount file and
restart is not required; the file is read on each call. Example
shape:

```json
{
  "id": "genie",
  "kind": "databricks-genie",
  "url": "https://example.invalid/mcp",
  "auth": "oauth",
  "classification": "confidential"
}
```

`id` must match `^[a-z][a-z0-9_-]{0,40}$`. `url` is recorded on the
capture and would be the MCP endpoint if a network transport were
wired. `auth` is stored and is not used by the fake transport.
`classification` is the floor described above.

`list_sources` returns each row with its read tools, its act tools
(empty unless the policy flag is on), and
`real_service_testing: "pending"`.

Snapshotting (`snapshot: true` on `call_source`) copies one capture
into `vault/ext` when policy allows it. The citation for the capture
itself, with or without a snapshot, is `(capture:<id>)`.

## MCP servers are a different list

User MCP servers (Settings, the `mcp` allowlist) are the servers
handed to Claude Code, Grok, and Codex. They are not this source
broker. In the enterprise profile those coding CLIs are off by
default, so the fan-out does not run until a provider is enabled.
A personal server is withheld from a workspace that has been
published. See [Controls](controls.md#caches-and-what-a-publish-ships).

Grok's project config can record an HTTP MCP URL, including
headers, under `<workspace>/.grok/`. That file is excluded from
publish. Headers are not copied into `graph-mounts.json`.
