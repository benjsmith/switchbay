# Enterprise security

This section is for the people who have to decide whether Switch Bay
can run in an organisation: IT, cybersecurity, cloud, network, and
IP or legal. It describes the controls that are in the product today,
the configuration that changes them, and the controls that are only
partly built.

Switch Bay is a local, single-user workbench. One daemon on the
person's machine serves a browser app, reads and writes a workspace
folder, and calls whatever models the profile allows. The
[packaging and install guide](../enterprise.md) covers how an admin
file is delivered. This section covers what that install actually
enforces.

## Read this first

Several settings in the enterprise template look like controls and
are not applied. The policy loader copies `profile`, `features`,
`providers`, `copilot`, `network`, `mcp`, `skills`, `paths`,
`updates`, `comms`, and `orchestration`. It does not copy
`graph_mounts`, `sources`, `public_writes`, or
`classification_review`. Editing those four sections in `admin.json`
changes nothing. The enterprise profile then runs its built-in
defaults: remote mounts and external sources are refused, remote
writes stay proposals, declassification is forbidden, public writes
are off, and Review is mandatory.

Other limits are called out on the page they belong to. The short
list:

- Page access checks against Work IQ or Unity Catalog are a stub.
  A reference that starts with `deny:` is refused. A reference that
  starts with `readonly:` can be read and not edited. Any other
  reference is allowed. No live catalog is called.
- Work IQ, Databricks Genie, AWS Context, and AWS Quick are named
  and tested with in-memory fakes. The source tool uses that fake.
  It does not call the real services.
- Exclusion rules are added to the hidden prompt. A text check
  exists and is not run before a tool executes. A classifier can be
  plugged in later; none is shipped.
- Presidio is not bundled and does not scan text. If the Python
  package happens to import, a public write is marked scanned
  without analysis. Enterprise refuses public writes before that
  point, because public writes are off.
- The public-write dialog (OK, Always allow, Cancel) is in the app.
  No write path opens it. Always allow would be stored as a global
  rule, which Settings can narrow to the workspace.
- The setting that would take the Presidio toggle away, and leave
  scanning on only for named OS users, is one of the four sections
  the loader drops. The toggle stays available to every user.
- A confidential read raises a session label. The chat badge and
  GitHub publish read a different session id (`default`) from the
  one a chat turn uses, so they do not follow that read.
- JWT checks (RS256 and ES256, issuer, audience, expiry, not-before,
  one JWKS refresh) are implemented and tested. Nothing calls them
  on a graph or source connection. RFC 7662 token introspection is
  not implemented.
- Sign-in for a live graph is OAuth 2.1 with PKCE, and it completes
  only when the server redirects immediately. A login page is not
  completed.

## Pages

- [Security posture](posture.md) — what the product is, the trust
  boundary of the daemon, and what it does not claim to be.
- [Controls](controls.md) — synced folders, models, labels, the chat
  badge, export, permissions, search, exclusion rules,
  declassification, Review, Presidio, and per-user caches.
- [Audit log](audit.md) — what is recorded, what is not, and where
  the file lives.
- [Untrusted content](untrusted.md) — imports, framing, scrub,
  merge, and remote writes.
- [Mounted graphs](graphs.md) — snapshots, live graphs, citations,
  trust weights, and sign-in.
- [External sources](sources.md) — Work IQ, Genie, AWS Context, and
  AWS Quick, and how a source is configured.
- [Network](network.md) — listeners, loopback services, and what
  leaves the machine.
- [Cloud and storage](cloud.md) — where data sits and what can sync.
- [IP and legal](legal.md) — residency, licences, and Presidio.
- [Configuration reference](configuration.md) — every admin and
  workspace setting, with the default and whether it is applied.

## Who should read what

| Team | Start here | Then |
|---|---|---|
| Cybersecurity | [Posture](posture.md), [Controls](controls.md) | [Audit](audit.md), [Untrusted content](untrusted.md), [Graphs](graphs.md), [Network](network.md) |
| Enterprise IT | [Configuration](configuration.md), [Packaging](../enterprise.md) | [Controls](controls.md), [Cloud](cloud.md) |
| Cloud | [Cloud and storage](cloud.md) | [Network](network.md), [Configuration](configuration.md) |
| Network | [Network](network.md) | [Graphs](graphs.md), [Sources](sources.md) |
| IP and legal | [IP and legal](legal.md) | [Controls](controls.md) (labels, Presidio, publish), [Cloud](cloud.md) |

The open profile (a normal git checkout, no admin file) is the
consumer product: every provider on, remote mounts allowed, public
writes allowed, declassification allowed. The enterprise profile is
what an MDM file or `SWITCHBAY_PROFILE=enterprise` selects. Where the
two differ, the page says so.
