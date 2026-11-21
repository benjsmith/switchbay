# Licensing and IP

This page states what the software does. It does not conclude that a deployment meets a statute.

## This product

Switch Bay is offered under the Functional Source License, Version 1.1, with an Apache 2.0 future licence (`FSL-1.1-ALv2`). The text is `LICENSE`. The grant allows any purpose other than a Competing Use. A Competing Use is offering the software to others as a commercial product or service that substitutes for Switch Bay, or for another product the licensor offers using it. Internal use is a permitted purpose. Third-party notices are in [THIRD-PARTY-NOTICES](../THIRD-PARTY-NOTICES.md).

## Imported material

Switch Bay does not read or enforce a licence file on a mounted graph, a git remote, or a source result. A snapshot is a copy under the state directory. An import writes a further copy into `vault/ext`, or into `vault/ext/.quarantine/` when the scrub hits. The operator who configures the mount or takes the snapshot is the one who needs the right to make that copy.

The classification line is a handling mark inside Switch Bay. It is not a licence and it is not sent to the remote system as a rights statement. A proposal is the operator's text, submitted as a proposal. The remote server decides whether to accept it.

## Personal data

Public writes are the path scanned for personal data before text goes onto a public mount.

In the enterprise profile that path is off unless `public_writes.allowed` is true or the mount id is listed in `connections`. A refused write does not show the responsibility notice.

When the scan runs, Presidio's `analyze` reports entity types. A hit refuses the write. A clean analysis is recorded as scanned. If Presidio is not installed, or `AnalyzerEngine` fails to load, the text is not marked scanned. The dialog then says Presidio is not scanning the write, and that the person should continue only if the text has no personal data. **OK** allows that write. **Always allow** stores a global rule, which Settings can narrow to the workspace. **Cancel** refuses it.

Turning the workspace toggle off stores this sentence with the audit event, and shows it in Settings:

> Presidio is off in this workspace, so public writes are not scanned for personal data. You are responsible for complying with the policies and regulations that apply.

`public_writes.user_control` false removes that toggle. `enabled_users` names the OS users who still have scanning on. Both keys are read from the admin file.

Publish preview also flags secret-shaped strings (a private-key block, a few vendor token prefixes, and a generic assignment of `api key`, `secret`, `token`, or `password`). The preview does not redact the file.

## Where copies sit

Workspace files stay in the folder the operator chose. Machine-local records stay under that OS user's state directory. Residency of a prompt is the residency of the model endpoint that receives it, described in [Role of the AI](ai.md). Residency of a synced folder is the sync client's. Residency of a GitHub publish is GitHub's. Switch Bay does not offer a region of its own.
