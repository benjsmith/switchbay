"""User-defined slash commands: markdown prompt templates.

Net-new surface (control-surface phase, decided 2026-07-03 — see log
Session 16): before this, only built-in verbs + action buttons existed.
A command is a plain `.md` file whose body is the prompt the rail
agent receives when the user types `/<name> [args]`:

  · workspace scope:  `<workspace>/.workbench/commands/<name>.md`
  · global scope:     `~/.config/switchbay/commands/<name>.md`

Workspace shadows global on a name collision. The name is the
filename stem, matched case-insensitively. `$ARGUMENTS` (or
`${ARGUMENTS}`) in the body is replaced with everything the user
typed after the name; a template with no placeholder gets the args
appended on a fresh paragraph — so a bare prompt file "does the
right thing" without documentation.

Resolution order in the slash dispatch keeps built-ins first
(special-cased handlers → CE actions → verb registry → THESE →
unknown), so a user file can never break `/view` et al.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("switchbay.commands")

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _global_dir() -> Path:
    from .workspaces import config_dir

    return config_dir() / "commands"


def _workspace_dir(workspace: Path) -> Path:
    return workspace / ".workbench" / "commands"


def _scan(d: Path, scope: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    try:
        entries = sorted(d.glob("*.md"))
    except OSError:
        return out
    for p in entries:
        name = p.stem.strip().lower()
        if not _NAME_RE.fullmatch(name):
            continue
        out[name] = {"name": name, "path": p, "scope": scope}
    return out


def _describe(path: Path) -> str:
    """First non-empty line, stripped of markdown heading/comment
    syntax — the autocomplete row's description."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:100]
    return ""


def list_commands(workspace: Path) -> list[dict[str, Any]]:
    """All available commands (workspace shadowing global), for the
    slash autocomplete. Reads every file's head — call off-loop."""
    merged = _scan(_global_dir(), "global")
    merged.update(_scan(_workspace_dir(workspace), "workspace"))
    return [
        {
            "name": rec["name"],
            "description": _describe(rec["path"]),
            "scope": rec["scope"],
        }
        for rec in sorted(merged.values(), key=lambda r: r["name"])
    ]


def resolve(workspace: Path, name: str) -> str | None:
    """The template body for `name`, or None. Call off-loop."""
    name = name.strip().lower()
    if not _NAME_RE.fullmatch(name):
        return None
    for d in (_workspace_dir(workspace), _global_dir()):
        p = d / f"{name}.md"
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8")
        except OSError:
            continue
    return None


def render(template: str, args: str) -> str:
    """Substitute `$ARGUMENTS`/`${ARGUMENTS}`; append args on a fresh
    paragraph when the template has no placeholder (and args exist)."""
    args = args.strip()
    if "$ARGUMENTS" in template or "${ARGUMENTS}" in template:
        return template.replace("${ARGUMENTS}", args).replace("$ARGUMENTS", args)
    if args:
        return template.rstrip() + "\n\n" + args
    return template
