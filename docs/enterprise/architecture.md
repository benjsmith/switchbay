# Architecture and data flow

Switch Bay is one Python daemon and a browser app on the same machine, one OS user. The daemon listens on `127.0.0.1:8765` (or `network.bind_port`). The browser uses HTTP and `ws://127.0.0.1:8765/ws`. Graph and Agents panels load from the same origin under `/embed/ce/` and `/embed/okstratr/`, proxied to `127.0.0.1:8766` and `127.0.0.1:8767`.

A workspace is a folder: `wiki/` for pages, `vault/` for sources, `.workbench/` for local configuration. The daemon also keeps per-user state outside that folder. See [Storage](storage.md).

## Request boundary

Every request is checked:

- An `Origin` header, when present, must be `127.0.0.1`, `localhost`, or `::1`.
- The `Host` hostname must be one of those names.
- A request with no `Origin` and a loopback `Host` is accepted. That is how local tools and the permission callback reach the daemon.

In the enterprise profile a bind address other than `127.0.0.1` or `::1` is refused at startup. `aiohttp` and `urllib` are wrapped so an enterprise process can open a URL only when [Network](network.md) allows the host. `git`, `gh`, `npx`, and Playwright are separate processes and are not inside that wrap.

## Two profiles

`open` is the default. `enterprise` is selected by `SWITCHBAY_PROFILE=enterprise` or `"profile": "enterprise"` in the admin file. The daemon never writes that file. Search order and defaults are in [Configuration](configuration.md).

Enterprise turns off hosted API providers other than GitHub Copilot, and turns off open-web search, GitHub publish, media APIs, comms, Hugging Face downloads, and the local browser until an admin enables the flag. Copilot, llama.cpp, MLX, and Ollama stay on.

## A chat turn

The turn records a session id (the thread id, else the run id, else `rail`) on disk for that workspace. Search and page reads consult the mounts in `.workbench/graph-mounts.json`. A confidential or restricted read raises that session's label. The chat badge and export checks read the same id. The finished reply is stamped `classification: <label>`.

Tool calls are checked against exclusion rules before they run. A remote write is a proposal unless every direct-write condition in [Controls](controls.md) holds.

## Mounts and sources

`local` is the workspace wiki. A snapshot is a pinned copy under the state directory. A live graph is queried at `/ce-graph/1/…`. Work IQ, Databricks Genie, AWS Context, AWS Quick, and Unity Catalog are sources: `call_source` POSTs MCP `tools/call` to the configured URL. Captures stay in the state directory until someone snapshots one into `vault/ext`.

## Labels

`public` < `internal` < `confidential` < `restricted`. An unrecognised label counts as `restricted`. A page with no `classification:` line is `public`. The effective label is the highest of the page and the pages it cites with `(vault:…)`, `(table:…)`, `(figure:…)`, `(graph:…)`, or `(capture:…)`. A capture with no stored label counts as `confidential`.
