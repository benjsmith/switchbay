# Integrations

Mounts and sources are `<workspace>/.workbench/graph-mounts.json` (schema `switchbay-graph-mounts/1`). The file holds no tokens. Agent seats see it because they call Switch Bay's tools.

Saving a remote mount checks the admin allowlist, `allow_public` for trust `external`, the trust ceiling, enterprise egress for an `http` URL, and `remote_write`. With the enterprise template's empty allowlist, a remote mount does not save until an admin adds its graph id or URL. Local mounts save in both profiles.

## Snapshot and live

A snapshot `url` that is a directory is copied. `https://`, `http://`, `git@`, and `file://` are `git clone --depth 1`. A branch name is `--branch`. A 12- or 40-character hex `ref` is fetched and checked out. The copy lives at `<state>/mounts/<hash>/` and is reused while the revision matches. `refresh` other than `manual` is stored. Nothing polls it.

A live URL ending in `/mcp` is stripped. Calls then go to `/ce-graph/1/info` (GET), and POST `/search`, `/page`, `/neighbors`, `/path`, `/propose`. Timeout 4 seconds, no retry. The client does not send MCP `tools/call` for these operations. `/mcp` is used for OAuth discovery.

A citation is `(graph:<mount>/<path>@<revision>)`. Claim lint accepts it when the snapshot pin equals that revision and the page is in the copy, or when a live cache file exists for that revision. A missing cache is stale. Lint does not fetch.

Search scores are merged with reciprocal rank fusion (k = 60), weighted `own` 1.0, `org` 0.8, `external` 0.5. A path stays inside one graph. A path across a snapshot is not implemented. The tool says so.

Reads from trust `org` or `external` are wrapped:

```
UNTRUSTED REMOTE CONTENT — graph:<graph id>@<revision>
…
END UNTRUSTED REMOTE CONTENT
```

Trust `own`, including `local`, is not wrapped.

## Sources

`call_source` POSTs MCP `tools/call` to the source `url` with a 4-second timeout. The bearer token is the keychain entry for that source id, when one exists. Tests pass an in-memory transport. A source with no `http` URL is refused. Enterprise refuses a kind or URL that is not on `sources.allowlist`. The open profile's allowlist is `*`.

| Kind | Read tools | Act tools |
|---|---|---|
| `workiq` | `fetch`, `retrieve`, `ask`, `get_schema`, `search_paths` | `create_entity`, `update_entity`, `delete_entity`, `do_action`, `call_function` |
| `databricks-genie` | `genie_ask`, `genie_poll_response`, `genie_get_query_result` | none |
| `aws-context` | `agentic_search` | none |
| `aws-quick` | `search_entities`, `get_entity` | none |
| `unity-catalog` | `get_permissions` | none |

Act tools stay hidden unless `sources.allow_act_tools` is true. The default is false.

The label is the source row's `classification` if it is one of the four labels, replaced by a `classification` field on the result, and only raised by sensitivity tags (`restricted` / `highly confidential`, or `confidential` / `secret`). An empty label is queued for Review. `policy_outcome: denied` is audited and not captured.

`list_sources` includes `real_service_testing: "pending"`. The tools above are the names the broker sends. A deployment still has to point `url` at a server that implements them. Switch Bay does not ship tenant credentials.

AWS Context rows are candidates. The adapter does not create wiki pages. AWS Quick's graph stays in the AWS Quick account. This client searches it. It does not store a copy of that graph except the capture, and a snapshot the user takes.

User MCP servers in Settings are a different list. They are handed to coding CLIs. Those CLIs are off in the enterprise profile until a provider is enabled. A personal server with no `allowed_workspaces` is omitted from a workspace that has `.workbench/share.json`. Grok records an HTTP MCP URL, including headers, under `<workspace>/.grok/`, which publish excludes.
