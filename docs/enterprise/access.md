# Identity and access

There is no Switch Bay account and no permission server. The OS user is the person. Keys and graph tokens use the OS keychain (service `switchbay`) when one is available.

## Session label

A chat turn stores its session id for the workspace (`sessions/<hash>/labels.json`, key `_active`). Federated reads, local wiki reads, the chat badge (`GET /api/session/label`), GitHub publish, and PDF export all use that id.

`note_read` raises the stored label when the material is `confidential` or `restricted`, and writes `confidential_read` to the audit log. `internal` and `public` do not raise it. The badge hides `public` and shows any higher label. The finished reply is appended with `classification: <label>`.

`POST /api/session/label` lowers the active session to `public`. It requires `human_confirmed: true` and a reason of at least 8 characters, and it is audited as `declassify`.

## Page permissions

`source_ref` in frontmatter is checked before a search hit is returned and before a page is edited or declassified.

| Reference | Result |
|---|---|
| empty | Whole-graph read and write |
| `deny:…` | No read, no write |
| `readonly:…` | Read, no write |
| `workiq:…` | HTTP MCP `fetch` on the configured `workiq` source, arguments `source_ref` and `intent` (`read` or `write`) |
| `uc:…`, `unity:…`, `unity-catalog:…` | HTTP MCP `get_permissions` on the configured `unity-catalog` source, argument `securable` |

A `read` / `write` boolean in the tool result is used as returned. A Unity-style `privileges` list treats `SELECT`, `USE_CATALOG`, `USE_SCHEMA`, `READ`, and `BROWSE` as read, and `MODIFY`, `ALL_PRIVILEGES`, `OWNERSHIP`, and `WRITE` as write. `policy_outcome: denied` is a refusal. No configured source, a source without an `http` URL, or a transport error is a refusal for those prefixes.

Slideshow PDF export uses the same call. `export: false` in the tool result refuses the export even when read is allowed. `deny:` refuses it. `readonly:` does not. A catalog error refuses the export.

Search merges the same item from more than one graph onto an `also` list. An `also` entry whose `source_ref` fails the read check is dropped.

Any other `source_ref` prefix is the whole-graph right. Switch Bay does not invent a catalog for it.

## Declassification

`declassify_page` sets `classification: public` and `declassified: true`. Edit access on the page is the only requirement. There is no second approver, no reason, and no admin switch. Enterprise does not forbid it. A caller without edit access is refused. The audit row records the OS user, the time, the page, and the old and new labels.

After the write, a warning is attached when the new text still shares a number of two or more digits, or a phrase of three or more words of four or more letters, with a wiki page whose own frontmatter is `confidential` or `restricted`. Up to four shared items are named. The warning does not undo the write. Publish still applies the citation rule.

## Exclusion rules

Settings → Permissions stores rules in `.workbench/exclusion-rules.json`. Each rule is a sentence and **Allow**, **Ask**, or **Deny**.

On a chat turn the rules are appended to the hidden system prompt, including the line that "ignore previous instructions" does not change them.

Before every registry tool runs, the same matcher runs on `tool-name` plus the JSON arguments. It strips an "ignore … previous/prior/above/all … instructions" phrase, then looks for each rule sentence as a case-insensitive substring. Deny wins over ask. Ask wins over allow. No matching rule is allow.

Deny returns `denied by an exclusion rule` and audits `refused_write`. Ask opens the existing permission card (`POST /api/permission/request`, tool name `exclusion`). Approve runs the tool. Anything else, including a daemon that is not reachable, denies the call. `set_classifier` replaces the matcher. An unknown verdict from that hook becomes ask.

## Remote graph tokens

Live mounts with `auth: anonymous` send no token. `auth: dev` sends the stored token and does not validate it. That is the loopback development server used by `scripts/enterprise_graph_demo.py`.

`auth: oauth` (the default for a live mount) checks the token on every connection:

- `token_check: jwt` (the default) requires a JWT. RS256 and ES256 only. `none` and `HS*` are rejected. `iss`, `aud`, `exp`, and `nbf` when present are checked, with 60 seconds of skew. An unknown `kid` refreshes the JWKS once. The JWKS URL and issuer come from the mount (`jwks_url`, `issuer`, `audience`) or from OAuth discovery (`jwks_uri`, `issuer`, resource).
- `token_check: introspection` POSTs the token to `introspection_url`, or to the discovered `introspection_endpoint`, as `application/x-www-form-urlencoded` with `token` and `token_type_hint=access_token` (RFC 7662). `active` must be true.

## Sign-in

PKCE is the authorisation-code flow, S256, client id `switchbay`, scope `ce-graph.read ce-graph.propose`. The redirect is `http://127.0.0.1:<ephemeral>/switchbay-oauth`, and that port is listening.

An immediate 302, 303, or 307 is consumed as the code. A 200 login page is opened in the system browser. The browser's redirect to the loopback port delivers the code. Tests pass `open_browser` instead of launching a browser. The access token is stored in the keychain under `graph-mount:<mount id>`, or in `graph-tokens/<mount id>.json` at mode `0600`. The mount file does not contain it.
