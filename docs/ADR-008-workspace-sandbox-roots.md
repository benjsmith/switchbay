# ADR-008: Workspace sandbox roots (stage-5 home rule + box `/workspace`)

**Status:** Accepted  
**Date:** 2026-09-20  
**Context:** Stage-5 restricted workspace paths to `$HOME` so file-ops /
cebridge never get a cwd of `/`, `/etc`, etc. On the Grok Bot box,
corpora live under `/workspace` (e.g. `/workspace/ce-cb-biocure`).
`Path.resolve()` follows symlinks, so a `~/Workspaces/...` symlink still
failed `is_within_home`; E2E had to `unshare`+bind-mount under home.

**Decision:** Keep the stage-5 sandbox, but allow a small explicit set of
roots via `allowed_workspace_roots()`:

1. Always `Path.home()`.
2. `/workspace` when that directory exists (agent-box scratch).
3. Extra dirs from `SWITCHBAY_WORKSPACE_ROOTS` (`os.pathsep`-separated;
   expanduser + resolve; skip missing / non-dirs).

`is_within_home(path)` (name retained for call sites) returns true iff
the resolved path is under any of those roots. Error copy uses
`home_label()` → e.g. `must live inside /home/box or /workspace`.

**Consequences:** Box corpora register without bind-mount workarounds.
`/etc`, `/tmp`, `/`, and `..` escapes remain refused unless an operator
deliberately adds a root via the env var.
