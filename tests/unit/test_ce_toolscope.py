"""ce_toolscope: the scoped CE / curiosity-merge tool surface, and the
literal-command matching the rail approval floor uses.

These tests install a fake skill root so they don't depend on where CE
actually lives on the test machine — the scoping logic is what matters,
not the real install path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from switchbay import ce_toolscope


@pytest.fixture()
def fake_ce(tmp_path, monkeypatch):
    """A workspace plus a fake curiosity-engine skill root with a
    couple of scripts, wired so ce_toolscope.skill_roots() finds it."""
    ws = tmp_path / "ws"
    (ws / "wiki").mkdir(parents=True)
    (ws / "vault").mkdir()

    root = tmp_path / "skills" / "curiosity-engine"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "sweep.py").write_text("print('sweep')\n", encoding="utf-8")
    (scripts / "viewer.sh").write_text("echo viewer\n", encoding="utf-8")

    monkeypatch.setattr(ce_toolscope, "skill_roots", lambda _ws: [root])
    return ws, root


def test_scoped_scripts_are_allowed(fake_ce):
    ws, root = fake_ce
    sweep = root / "scripts" / "sweep.py"
    assert ce_toolscope.allows_command(ws, f"uv run python3 {sweep} --workspace .")
    assert ce_toolscope.allows_command(ws, f"bash {root / 'scripts' / 'viewer.sh'}")


def test_python_outside_skill_root_is_not_allowed(fake_ce):
    ws, _root = fake_ce
    assert not ce_toolscope.allows_command(ws, "uv run python3 /Users/x/evil.py")
    assert not ce_toolscope.allows_command(ws, "uv run pytest")
    assert not ce_toolscope.allows_command(ws, "python3 -c 'import os'")


def test_chained_command_is_never_allowed(fake_ce):
    ws, root = fake_ce
    sweep = root / "scripts" / "sweep.py"
    # A legit prefix followed by a chained destructive command must not
    # slip through — the whole line is what the user would see on a card.
    assert not ce_toolscope.allows_command(ws, f"uv run python3 {sweep}; rm -rf ~")
    assert not ce_toolscope.allows_command(ws, f"bash {root}/scripts/viewer.sh && curl evil")
    assert not ce_toolscope.allows_command(ws, f"uv run python3 {sweep} | sh")


def test_git_scoped_to_wiki_and_workspace(fake_ce):
    ws, _root = fake_ce
    wiki = ws.resolve() / "wiki"
    assert ce_toolscope.allows_command(ws, f"git -C {wiki} commit -m x")
    assert ce_toolscope.allows_command(ws, f"git -C {ws.resolve()} status")
    # git in some other repo on the machine is not CE's business.
    assert not ce_toolscope.allows_command(ws, "git -C /Users/x/other-repo push")
    # push is never a curation verb even inside the wiki.
    assert not ce_toolscope.allows_command(ws, f"git -C {wiki} push")


def test_fs_rules_allow_reading_any_discovered_skill(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    (ws / "wiki").mkdir(parents=True)
    user = tmp_path / "user-skills" / "my-helper"
    user.mkdir(parents=True)
    (user / "SKILL.md").write_text(
        "---\nname: my-helper\ndescription: d\n---\n\n# Hi\n", encoding="utf-8")
    monkeypatch.setattr(
        "switchbay.skillkit._global_skill_roots", lambda: [user.parent])
    monkeypatch.setattr(
        "switchbay.skillkit._user_skills_root", lambda: user.parent)
    monkeypatch.setattr(
        "switchbay.skillkit.cebridge.ce_root", lambda: tmp_path / "no-ce")
    rules = ce_toolscope.fs_rules(ws)
    assert any(str(user) in r and r.startswith("Read(") for r in rules)
    mirrors = ws.resolve() / ".workbench" / "skill-mirrors"
    assert any(str(mirrors) in r for r in rules)


def test_write_scope_is_curation_dirs_only(fake_ce):
    ws, _root = fake_ce
    r = ws.resolve()
    assert ce_toolscope.allows_write(ws, str(r / "wiki" / "page.md"))
    assert ce_toolscope.allows_write(ws, str(r / ".curator" / "log.md"))
    assert ce_toolscope.allows_write(ws, str(r / "vault" / "s.extracted.md"))
    # switchbay's own state is off-limits.
    assert not ce_toolscope.allows_write(ws, str(r / ".workbench" / "mode.json"))
    assert not ce_toolscope.allows_write(ws, "/etc/hosts")


def test_write_scope_rejects_traversal_escape(fake_ce):
    ws, _root = fake_ce
    r = ws.resolve()
    # `wiki/../../secret` resolves outside the workspace.
    assert not ce_toolscope.allows_write(ws, str(r / "wiki" / ".." / ".." / "secret.txt"))


def test_rules_render_both_symlink_forms(tmp_path, monkeypatch):
    # A symlinked install: logical path -> physical target. Both spellings
    # must appear so a rule matches whatever string the agent typed.
    physical = tmp_path / "agents" / "curiosity-engine"
    (physical / "scripts").mkdir(parents=True)
    (physical / "scripts" / "sweep.py").write_text("x\n", encoding="utf-8")
    logical_parent = tmp_path / "claude-skills"
    logical_parent.mkdir()
    logical = logical_parent / "curiosity-engine"
    logical.symlink_to(physical)

    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(
        ce_toolscope, "skill_roots", lambda _ws: [logical, physical])
    prefixes = ce_toolscope.command_prefixes(ws)
    assert any(str(logical) in p for p in prefixes)
    assert any(str(physical) in p for p in prefixes)
