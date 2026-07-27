"""The exact tool-call shapes the curiosity-engine (CE) and
curiosity-merge (CM) skills need, in one provider-neutral place.

Why this module exists
----------------------
CE and CM do real work by *shelling out* — `uv run python3
<skill>/scripts/sweep.py`, `bash <skill>/scripts/viewer.sh`, `git -C
<ws>/wiki commit`. A provider that cannot run those commands cannot
curate; it can only *propose* edits back to the user. That was the
2026-07-24 curator bug: `/curate` was routed to a provider spawned
with `--deny Bash(*)`, so every change came back as a proposal.

The fix is not "give the agent a shell" — it is "give the agent
exactly the calls CE and CM need, and card everything else". Both
halves live here so the CLI providers stay in sync:

  · `claude_code_settings.py` renders these into
    `<ws>/.workbench/state/claude-code-settings.json`.
  · `llmgateway/grok_build.py` renders them into `--allow` flags.

Both CLIs speak the same Claude-compat rule syntax (`Bash(prefix:*)`,
`Edit(glob)`), so one vocabulary serves both. Anything NOT matched
here falls through to the provider's PreToolUse hook → switchbay's
rail approval card (`permissions.request`), which is the intended
escape hatch rather than a hard failure.

Scoping strategy
----------------
CE's own `setup.sh` enumerates ~30 script names by hand and carries a
list of "canaries" to detect when that enumeration went stale — the
list drifts every time CE ships a script. We do not copy that
maintenance burden. Instead we scope by **skill root**:

  1. Every `*.py` / `*.sh` actually present under `<root>/scripts/`
     is emitted explicitly (tight, and self-updating on CE upgrade).
  2. A pinned-root wildcard (`uv run python3 <root>/scripts/*:*`)
     catches scripts added between daemon restarts.

Either way the interpreter is pinned to a *known skill root* — this
never allows running python or bash from an arbitrary path, which is
what switchbay's previous blanket `Bash(uv run python3 *:*)` did.

Symlinked installs emit BOTH the logical and the physical path: the
first-party skills install as `~/.claude/skills/curiosity-engine →
~/.agents/skills/curiosity-engine`, and a rule matches the literal
string the agent typed. CE hit this same problem (setup.sh's
`SKILL_ROOTS`) — if only one form is listed, the other cards.
"""

from __future__ import annotations

import logging
from pathlib import Path

from . import cebridge

log = logging.getLogger("switchbay.ce_toolscope")

# Skills whose scripts get scoped shell access. First-party only —
# these two ship with the product (charter: bundled as first-party
# system-level skills at service install). A third-party pack skill
# does NOT get shell by dropping a scripts/ dir here; it goes through
# the rail approval card like anything else.
SCOPED_SKILLS = ("curiosity-engine", "curiosity-merge")

# git subcommands CE runs against the wiki repo. Read-only inspection
# plus the write verbs its crystallization/rollback path needs. NOT
# `git push` / `git remote` — publishing is a deliberate user action
# through the share flow (D3), never a curator side effect.
_GIT_VERBS = (
    "add", "commit", "status", "log", "diff", "show",
    "rev-parse", "ls-files", "checkout", "revert",
)


def _dedup(items: list[str]) -> list[str]:
    """Order-preserving dedup — the same root can surface twice via
    both a logical and a physical path that resolve identically."""
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _root_forms(root: Path) -> list[Path]:
    """A skill root as the agent might spell it: the path itself and
    its symlink-resolved target when they differ."""
    forms = [root]
    try:
        real = root.resolve()
    except OSError:
        return forms
    if real != root:
        forms.append(real)
    return forms


def skill_roots(workspace: Path) -> list[Path]:
    """Every directory whose `scripts/` we grant scoped shell access.

    Resolved live (not hardcoded) so a machine that installed CE via
    the bundled global-skill path, a legacy checkout, or the
    `CSWY_CE_ROOT` env override all work — `cebridge.ce_root()` owns
    that resolution. Roots without a `scripts/` dir are dropped: CM
    ships SKILL.md only on some installs, and emitting rules for a
    non-existent path is noise.
    """
    from . import skillkit  # local: skillkit imports packstore → cebridge

    cands: list[Path] = []

    # CE resolves through cebridge (env override → bundled → legacy).
    try:
        cands.extend(_root_forms(cebridge.ce_root()))
    except Exception:  # noqa: BLE001 — never let scope-building fail a spawn
        log.exception("ce_root() failed; CE scripts will card instead")

    # CM (and CE again, if discovery finds a different install) via the
    # normal skill discovery roots.
    try:
        for sk in skillkit.list_skills(workspace):
            if sk.name in SCOPED_SKILLS:
                cands.extend(_root_forms(Path(sk.path).parent))
    except Exception:  # noqa: BLE001
        log.exception("skill discovery failed; CM scripts will card instead")

    out: list[Path] = []
    seen: set[str] = set()
    for c in cands:
        if not (c / "scripts").is_dir():
            continue
        key = str(c)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _script_rules(root: Path) -> list[str]:
    """Rules for one skill root: every script on disk, plus a
    pinned-root wildcard for ones added later."""
    rules: list[str] = []
    scripts = root / "scripts"

    # Pinned-root wildcards — forward-compatible catch.
    rules.append(f"Bash(uv run python3 {scripts}/*:*)")
    rules.append(f"Bash(uv run python {scripts}/*:*)")
    rules.append(f"Bash(python3 {scripts}/*:*)")
    rules.append(f"Bash(bash {scripts}/*:*)")

    # Explicit per-script rules for what's actually installed. Tighter
    # than the wildcard for the common case, and a provider whose
    # matcher does not support mid-pattern `*` still gets full CE
    # coverage from these.
    try:
        entries = sorted(scripts.iterdir())
    except OSError:
        return rules
    for f in entries:
        if not f.is_file():
            continue
        if f.suffix == ".py":
            rules.append(f"Bash(uv run python3 {f}:*)")
            rules.append(f"Bash(python3 {f}:*)")
        elif f.suffix == ".sh":
            rules.append(f"Bash(bash {f}:*)")
            rules.append(f"Bash({f}:*)")
    return rules


def bash_rules(workspace: Path) -> list[str]:
    """Scoped shell rules for CE + CM against `workspace`."""
    rules: list[str] = []
    for root in skill_roots(workspace):
        rules.extend(_script_rules(root))

    # git, scoped to the wiki repo and the workspace root only. CE
    # commits crystallized pages; `git -C <anything>` (switchbay's old
    # rule) let the agent drive git in any repo on the machine.
    ws = workspace.resolve()
    for base in (ws / "wiki", ws):
        for verb in _GIT_VERBS:
            rules.append(f"Bash(git -C {base} {verb}:*)")

    # CE reads its preset from the environment and stamps activity
    # entries with the date.
    rules.append("Bash(printenv CURATOR_PRESET:*)")
    rules.append("Bash(date:*)")
    return _dedup(rules)


def fs_rules(workspace: Path) -> list[str]:
    """File-scope rules CE + CM need: write inside the workspace, read
    the skill roots (so the agent can read its own scripts/reference
    docs), and a scratch dir. Mirrors CE's generated allowlist."""
    ws = workspace.resolve()
    rules = [
        f"Edit({ws}/**)",
        f"Write({ws}/**)",
        f"Read({ws}/**)",
        "Edit(./**)",
        "Write(./**)",
        "Read(./**)",
        "Write(/tmp/**)",
        "Edit(/tmp/**)",
        "Read(/tmp/**)",
    ]
    for root in skill_roots(workspace):
        rules.append(f"Read({root}/**)")
    return _dedup(rules)


def all_rules(workspace: Path) -> list[str]:
    """Everything CE + CM need, in Claude-compat rule syntax. Consumed
    by claude_code_settings (settings.json `permissions.allow`) and
    grok_build (`--allow` flags)."""
    return _dedup([*fs_rules(workspace), *bash_rules(workspace)])


# ── Literal command matching (the rail approval floor) ─────────────
#
# The rules above are for the CLIs' own allowlists. Switch Bay's rail
# gate is separate and coarser: `permissions.pattern_for` reduces a
# Bash call to its first TWO tokens, so `uv run python3 <CE>/scripts/
# sweep.py` and `uv run python3 ~/evil.py` both become `Bash(uv run*)`
# — indistinguishable. Pre-approving at that granularity would grant
# every `uv run` on the machine.
#
# So the rail floor matches the FULL command text against literal
# prefixes instead. That is what makes "scoped to the exact shape of
# calls needed" true at the gate the user actually sees.

# Shell metacharacters that chain, redirect, or substitute. A command
# containing any of them is never auto-approved even if its prefix
# matches — `bash <CE>/scripts/viewer.sh; rm -rf ~` starts with an
# allowed prefix but is not an allowed call. These fall through to the
# rail card, where the user reads the whole command before approving.
_UNSAFE_SHELL_CHARS = (";", "&", "|", "`", "$(", ">", "<", "\n", "\r")


def command_prefixes(workspace: Path) -> list[str]:
    """Literal command prefixes CE + CM are allowed to run without a
    card. Compared against the whole command string, not a pattern."""
    out: list[str] = []
    for root in skill_roots(workspace):
        scripts = root / "scripts"
        out.extend([
            f"uv run python3 {scripts}/",
            f"uv run python {scripts}/",
            f"python3 {scripts}/",
            f"bash {scripts}/",
            f"sh {scripts}/",
            f"{scripts}/",
        ])
    ws = workspace.resolve()
    for base in (ws / "wiki", ws):
        for verb in _GIT_VERBS:
            out.append(f"git -C {base} {verb}")
    out.append("printenv CURATOR_PRESET")
    return _dedup(out)


def allows_command(workspace: Path, command: str) -> bool:
    """True iff `command` is one of the CE/CM call shapes, in a form
    safe to auto-approve (single command, no chaining or redirect)."""
    cmd = " ".join((command or "").split())
    if not cmd:
        return False
    if any(ch in cmd for ch in _UNSAFE_SHELL_CHARS):
        return False
    return any(cmd.startswith(p) for p in command_prefixes(workspace))


def write_globs(workspace: Path) -> list[str]:
    """Directories CE + CM legitimately write while curating: the wiki
    itself, CE's metadata dir, and the vault. Deliberately NOT the
    whole workspace — `.workbench/` holds switchbay's own config,
    permission store, and session state, which curation never edits
    and which an agent should not be able to rewrite uncarded.
    Mirrors the Edit/Write scope in CE's own generated allowlist."""
    ws = workspace.resolve()
    return [f"{ws}/wiki", f"{ws}/.curator", f"{ws}/vault"]


def allows_write(workspace: Path, path: str) -> bool:
    """True iff `path` is inside a directory curation may write."""
    if not path:
        return False
    try:
        target = Path(path).resolve()
    except OSError:
        return False
    for base in write_globs(workspace):
        try:
            target.relative_to(Path(base))
        except ValueError:
            continue
        return True
    return False
