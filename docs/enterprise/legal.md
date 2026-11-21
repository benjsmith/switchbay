# IP and legal

[Enterprise security](index.md)

This page states what the software does with other people's material
and with personal data, and what it does not decide. It is a
description of behaviour, not a legal opinion. Counsel should read
`LICENSE` for the product's own terms.

## Where data resides

Workspace files stay in the folder the operator chose. Machine-local
records (audit, captures, caches, snapshot copies, session labels)
stay under that OS user's state directory. Keys stay in the OS
keychain when one is available.

Switch Bay does not run a hosted region and does not offer a data
residency choice of its own. Residency is the residency of:

- the disk and any sync client that covers the workspace folder
  ([Cloud and storage](cloud.md));
- GitHub, if someone publishes a workspace or signs in to Copilot;
- the model endpoint that actually receives a prompt (Copilot, or a
  hosted API an admin has turned on);
- a live graph server, if a mount to one has been saved;
- a comms provider, if `comms_streams` has been turned on.

Enterprise defaults keep hosted model APIs, GitHub publish, open-web
search, media APIs, and comms off, and they refuse a serve-time
workspace path that sits in a consumer sync folder unless that path
is allowlisted. Those defaults are configuration, described in
[Configuration](configuration.md). They are not a contractual
residency commitment.

## Licence of this product

Switch Bay is offered under the Functional Source License, Version
1.1, with an Apache 2.0 future licence (`FSL-1.1-ALv2`). The grant
allows any purpose other than a Competing Use. A Competing Use is
making the software available to others as a commercial product or
service that substitutes for Switch Bay, or for another product the
licensor offers using it. Internal use inside an organisation is a
permitted purpose. The full text is `LICENSE` at the root of the
repository. Third-party notices are in
[THIRD-PARTY-NOTICES](../THIRD-PARTY-NOTICES.md).

## Licence of an imported graph or source

Switch Bay does not read a licence file on a mounted graph, a git
remote, or a source result, and it does not enforce one. A snapshot
is a copy of the remote wiki, kept under the state directory. An
import writes a further copy into `vault/ext`. A source snapshot
does the same for one captured result.

The operator who configures the mount or takes the snapshot is the
one who needs the right to make that copy. The classification label
on the copy is a handling mark inside Switch Bay. It is not a
licence, and it does not travel as a rights statement to the remote
system.

A proposal sent to a remote graph is the operator's text, submitted
as a proposal (see [Untrusted content](untrusted.md)). The remote
server decides whether to accept it. Switch Bay does not grant the
remote side a licence beyond whatever the operator's agreement with
that server already says.

## Personal data and Presidio

Public writes are the path that was meant to be scanned for personal
data before text went onto a public mount.

In the enterprise profile that path is off. A public page is refused
onto a public mount because public writes are limited to a
connection list, and the list is empty. Turning the Settings toggle
off does not open the path.

In the open profile, or if public writes are later turned on:

- The scan does not run. Presidio is not bundled. If the
  `presidio_analyzer` package happens to be installed, the write is
  marked scanned and the text is not analyzed. If it is not
  installed, the caller is asked to confirm.
- The confirmation dialog says Presidio is not scanning the write,
  and that the person should continue only if the text has no
  personal data. **OK** allows that one write. **Always allow**
  stores a global allow, which can be narrowed to the current
  workspace. **Cancel** refuses it. No write path opens this dialog
  yet; the choice comes back on the tool result.
- Turning the workspace toggle off shows this notice, and the same
  text is stored with the audit event: "Presidio is off in this
  workspace, so public writes are not scanned for personal data. You
  are responsible for complying with the policies and regulations
  that apply."

That sentence is the product's allocation of responsibility. It
appears when a person turns the toggle off. It does not appear when
the package is missing and the dialog has not been confirmed, and it
does not appear in the enterprise profile, because the public write
is refused first.

An admin file can, in the Presidio module, remove the toggle
(`public_writes.user_control` false) and name OS users who still have
scanning on (`enabled_users`). The policy loader does not read
`public_writes`, so an admin cannot do that with `admin.json` today.
Every user keeps the toggle. See
[Configuration](configuration.md#sections-the-loader-does-not-apply).

Classification labels are not a personal-data finding. Nothing in
the product detects a person's name, an identifier, or a similar
pattern except the secret-shaped strings in the GitHub publish
preview (private keys, a few vendor token prefixes, and a generic
"api key / secret / token / password" assignment). That preview is a
warning list. It does not redact the file.

## Comms and tenant labels

Mail and chat connectors are off until an admin sets
`features.comms_streams` to true. When they are on, a Secret or Top
Secret label is refused before a body is fetched, and in the
enterprise profile a missing or unknown classification is refused
the same way. Tenant label GUIDs belong in `comms.tenant_label_ids`.
The packaging guide explains the fixture-versus-tenant gap:
[Enterprise packaging](../enterprise.md#comms-classification-and-tenant-labels).
Those comms rules are separate from the page labels in
[Controls](controls.md).

## What a publish contains

A GitHub publish is an explicit copy to GitHub. Enterprise disables
it. When it runs, `.workbench/` (configuration, chat history, rules,
Review) stays behind, caches stay behind, and any wiki or vault text
file whose effective label is above `public` blocks the publish.
`vault/ext` is part of the vault: it is included only when the
person includes the vault, and only for files that are still
`public` after citations are taken into account.

Switch Bay does not add a licence header to published pages. The
pages go out as the files in the workspace.
