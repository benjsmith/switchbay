"""Home / filesystem-wide shell scans are hard-denied (macOS TCC)."""

from __future__ import annotations

import json
from pathlib import Path

from switchbay import permissions


def _deny(cmd: str, tool: str = "Bash") -> str | None:
    return permissions.hard_deny_reason(tool, {"command": cmd})


def _ok(cmd: str, tool: str = "Bash") -> None:
    assert _deny(cmd, tool) is None, f"expected allow for: {cmd!r}"


def _blocked(cmd: str, tool: str = "Bash") -> None:
    reason = _deny(cmd, tool)
    assert reason is not None, f"expected hard-deny for: {cmd!r}"
    assert "home" in reason.lower() or "filesystem" in reason.lower()


# ── blocked: the TCC-tripping patterns agents keep trying ──────────


def test_find_users_blocked():
    _blocked("find /Users -name '*.py' 2>/dev/null | head")
    _blocked("find /Users/someone -type f -name grok")
    _blocked("/usr/bin/find /Users -name x")


def test_find_home_tilde_blocked():
    _blocked("find ~ -name node")
    _blocked("find ~/Library -name '*.app'")
    _blocked("find $HOME -type d")
    _blocked("find ${HOME}/Documents -name x")


def test_find_root_and_volumes_blocked():
    _blocked("find /")
    _blocked("find / -name passwd")
    _blocked("find /Volumes -name x")
    _blocked("find /home -name x")
    _blocked("find /System/Library -name x")


def test_mdfind_locate_fd_blocked():
    _blocked("mdfind 'kMDItemDisplayName == foo'")
    _blocked("locate /Users/bin")
    _blocked("fd pattern /Users")
    _blocked("fd -H foo ~")


def test_ls_tree_du_home_blocked():
    _blocked("ls ~")
    _blocked("ls ~/Downloads")
    _blocked("ls /Users/someone")
    _blocked("tree $HOME")
    _blocked("du -sh ~")


def test_piped_and_chained_find_blocked():
    _blocked("cd /tmp && find /Users -name x | head")
    _blocked("find /Users -name x | xargs cat")
    _blocked("sudo find ~ -name secret")


def test_shell_alias_names_blocked():
    _blocked("find ~ -name x", tool="Shell")
    _blocked("find /Users -name x", tool="bash")
    _blocked("find ~ -name x", tool="command_execution")


# ── allowed: workspace-local discovery ─────────────────────────────


def test_find_dot_allowed():
    _ok("find . -name '*.md'")
    _ok("find ./wiki -type f")
    _ok("find wiki sources -name '*.pdf'")


def test_ls_workspace_allowed():
    _ok("ls")
    _ok("ls -la")
    _ok("ls wiki")
    _ok("ls ./sources")
    _ok("tree .")
    _ok("du -sh .")


def test_grep_rg_workspace_allowed():
    _ok("rg pattern wiki")
    _ok("grep -r foo .")
    _ok("cat wiki/foo.md")
    _ok("head -n 20 README.md")


def test_non_shell_tools_not_hard_denied():
    assert permissions.hard_deny_reason(
        "Read", {"file_path": "/Users/someone/secret.md"},
    ) is None
    assert permissions.hard_deny_reason(
        "Grep", {"pattern": "x", "path": "/Users"},
    ) is None
    assert permissions.hard_deny_reason("Bash", {}) is None
    assert permissions.hard_deny_reason("Bash", {"command": ""}) is None


# ── remembered Bash(find*) cannot override hard-deny ───────────────


def test_remembered_find_star_cannot_pre_approve(tmp_path: Path):
    state = tmp_path / ".workbench" / "state"
    state.mkdir(parents=True)
    (state / permissions.ALLOW_FILE).write_text(
        json.dumps(["Bash(find*)", "Bash(find /Users*)"]),
        encoding="utf-8",
    )
    cmd = "find /Users -name x"
    pat = permissions.pattern_for("Bash", {"command": cmd})
    # Without tool/input, pattern alone might still match the store —
    # with tool+input, hard-deny wins.
    assert not permissions.is_pre_approved(
        tmp_path, pat, tool="Bash", tool_input={"command": cmd},
    )
    assert permissions.hard_deny_reason("Bash", {"command": cmd})


def test_workspace_find_still_can_pre_approve_via_pattern(tmp_path: Path):
    """`find .` is not hard-denied; a remembered allow may still apply."""
    state = tmp_path / ".workbench" / "state"
    state.mkdir(parents=True)
    (state / permissions.ALLOW_FILE).write_text(
        json.dumps(["Bash(find*)"]),
        encoding="utf-8",
    )
    cmd = "find . -name '*.md'"
    pat = permissions.pattern_for("Bash", {"command": cmd})
    assert permissions.hard_deny_reason("Bash", {"command": cmd}) is None
    assert permissions.is_pre_approved(
        tmp_path, pat, tool="Bash", tool_input={"command": cmd},
    )
