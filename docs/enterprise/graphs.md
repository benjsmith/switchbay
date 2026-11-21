# Mounted graphs

[Enterprise security](index.md)

A workspace always has its own wiki, mount id `local`. It can also
name other graphs in `<workspace>/.workbench/graph-mounts.json`.
Okstratr and the other agent seats see the same list, because they
call Switch Bay's tools and those tools read this file. The file
holds no tokens.

## Snapshot and live

**Local.** The workspace wiki. Trust `own`, ceiling `restricted`,
write `direct`. This entry is added in memory even when the file is
missing. It is not written back as a mount row.

**Snapshot.** A copy of a wiki, pinned at one revision, stored
outside the workspace under
`<state directory>/mounts/<hash of the graph id or URL>/`. A `url`
that is a local directory is copied. A `url` that starts with
`https://`, `http://`, `git@`, or `file://` is cloned with
`git clone --depth 1`. A `ref` that is a branch name is passed as
`--branch`. A `ref` that is a 12- or 40-character hex revision is
fetched and checked out. The copy is reused while the revision file
matches. `refresh` other than `manual` is stored; fetches happen
when the snapshot is missing or the caller refreshes, not on a timer.

**Live.** A server Switch Bay queries over HTTP. The mount `url` is
the server. If it ends in `/mcp`, that suffix is stripped and the
JSON API below is called on what remains. Each read of a page is
cached under
`<state directory>/graph-cache/<workspace-hash>/<mount>/<revision>/`.

Saving a remote mount runs the admin check. In the enterprise
profile the allowlist is empty and public mounts are off, and the
admin section that would change either is not loaded. A remote mount
therefore fails to save: an `external` mount with "public mounts are
disabled by admin policy", any other remote mount with "graph is not
on the admin allowlist". The open profile's allowlist is `*` and
public mounts are allowed, so a remote mount saves. Local mounts
save in both profiles.

An `http` or `https` mount URL is also checked against the enterprise
egress allowlist. A host that is not allowed fails the save.

## The wire protocol

Live reads and proposals use a JSON HTTP API, `ce-graph/1`:

| Call | Method | Path |
|---|---|---|
| Info | GET | `/ce-graph/1/info` |
| Search | POST | `/ce-graph/1/search` |
| Page | POST | `/ce-graph/1/page` |
| Neighbours | POST | `/ce-graph/1/neighbors` |
| Path | POST | `/ce-graph/1/path` |
| Propose | POST | `/ce-graph/1/propose` |

A bearer token is sent when the mount's `auth` is `oauth` or `dev`.
`anonymous` sends none. The timeout is 4 seconds. There is no retry.

The client does not send MCP `tools/call` for these operations. The
`/mcp` suffix is used to find the OAuth metadata
(`/.well-known/oauth-protected-resource`, then the authorisation
server metadata). A curiosity-engine `graph_serve.py` speaks this
API; `scripts/enterprise_graph_demo.py` runs against that server
when the skill is on the machine. The unit tests use a small local
stand-in, not that server.

A path between two pages is implemented for a live mount. For a
snapshot the tool answers that a path across a snapshot is not
wired, and that the pages should be read instead. A path that starts
on one mount and ends on another is refused: a walk stays inside one
graph.

## Citations

A remote page is cited as `(graph:<mount>/<path>@<revision>)`. Claim
lint accepts it only when it resolves:

- The mount id, path, and revision are all present.
- The mount exists.
- For a snapshot, the pinned revision equals the cited revision, and
  the page file is in the pinned copy. A missing pin is reported as
  stale and unverifiable.
- For a live mount, a cache file for that revision and path exists.
  A citation of a revision that was never read, or whose cache file
  is gone, is stale and unverifiable. The client does not fetch
  during lint.

The search and read tools return that citation string, plus
`wikilink` of the form `[[mount:path]]`. A bare page path is local.

Trust weights used when merging search lists are in
[Controls](controls.md#search-scope).

## Sign-in

`auth` on a live mount is `anonymous`, `oauth`, or `dev`. Anything
else is stored as `oauth`.

OAuth is the authorisation-code flow with PKCE (S256), client id
`switchbay`, scope `ce-graph.read ce-graph.propose`, redirect
`http://127.0.0.1:9/switchbay-oauth`. The client asks the
authorisation endpoint itself and expects an immediate redirect
(HTTP 302, 303, or 307) back to that URI, with a matching `state`
and a `code`. It then posts the code and the verifier to the token
endpoint. A loopback server that auto-approves, including
curiosity-engine's `--auth dev`, completes this way. The client
does not open a browser. A provider that returns a login page fails
with "organisation sign-in needs a browser and is not completed
here".

The access token is stored in the OS keychain under the service
`switchbay`, account `graph-mount:<mount id>`, when a keychain is
available. Otherwise it is written to
`<state directory>/graph-tokens/<mount id>.json` at mode `0600`.
The mount file never contains the token.

### JWT validation

A validator can check a JWT against a JWKS document:

- Algorithms RS256 and ES256 only. `none` and any `HS*` algorithm
  are rejected.
- The `kid` header must name a key. An unknown `kid` refreshes the
  JWKS once and tries again. The cache also refreshes when it is
  older than 300 seconds.
- `iss` must equal the expected issuer. `aud` (a string or a list)
  must include the expected audience.
- `exp` is required. `nbf` is checked when present. Clock skew is
  60 seconds.

That function is covered by a unit test against a local JWKS. No
graph connection, source connection, or HTTP route calls it. A live
mount sends the opaque bearer token from the PKCE exchange and does
not inspect it.

RFC 7662 token introspection is not implemented. The validator's
comment records it as a separate option that this code does not use.
