"""The zero-friction builtin-allow floor: provably-safe reads are
pre-approved, but shell keeps its card."""

from __future__ import annotations

from switchbay import permissions


def test_bash_keeps_the_card(tmp_path):
    pat = permissions.pattern_for("Bash", {"command": "rm -rf /"})
    assert not permissions.is_pre_approved(tmp_path, pat)


def test_read_under_workspace_pre_approved(tmp_path):
    pat = permissions.pattern_for("Read", {"file_path": str(tmp_path / "wiki" / "a.md")})
    assert permissions.is_pre_approved(tmp_path, pat)


def test_read_global_skill_pre_approved(tmp_path, monkeypatch):
    root = tmp_path / "agents" / "skills"
    skill = root / "curiosity-engine"
    skill.mkdir(parents=True)
    md = skill / "SKILL.md"
    md.write_text("# x\n", encoding="utf-8")
    monkeypatch.setattr(
        "switchbay.skillkit.skill_read_roots", lambda: [root.resolve()])
    pat = permissions.pattern_for("Read", {"file_path": str(md)})
    assert permissions.is_pre_approved(
        tmp_path, pat, tool="Read", tool_input={"file_path": str(md)},
    )
    bash = {"command": f"cat {md}"}
    assert permissions.is_pre_approved(
        tmp_path, permissions.pattern_for("Bash", bash),
        tool="Bash", tool_input=bash,
    )


def test_read_outside_workspace_not_pre_approved(tmp_path):
    pat = permissions.pattern_for("Read", {"file_path": "/etc/passwd"})
    assert not permissions.is_pre_approved(tmp_path, pat)


def test_mcp_switchbay_tools_pre_approved(tmp_path):
    assert permissions.is_pre_approved(tmp_path, "mcp__switchbay__search_wiki")


def test_grep_glob_pre_approved(tmp_path):
    assert permissions.is_pre_approved(tmp_path, permissions.pattern_for("Grep", {"pattern": "x"}))
    assert permissions.is_pre_approved(tmp_path, permissions.pattern_for("Glob", {"pattern": "*.md"}))


def test_wiki_write_pre_approved_as_ce_scope(tmp_path):
    # 2026-07-24: curation writes into the wiki are part of the CE
    # execution scope, so they no longer card (else a curate run is
    # death-by-a-thousand-approval-cards). Matched on the full path,
    # not the coarse two-token pattern.
    ti = {"file_path": str(tmp_path / "wiki" / "a.md")}
    pat = permissions.pattern_for("Write", ti)
    assert permissions.is_pre_approved(tmp_path, pat, tool="Write", tool_input=ti)


def test_workbench_write_still_cards(tmp_path):
    # switchbay's own config / permission store / session state is NOT
    # curation's to rewrite uncarded, even though it's inside the
    # workspace.
    ti = {"file_path": str(tmp_path / ".workbench" / "mode.json")}
    pat = permissions.pattern_for("Write", ti)
    assert not permissions.is_pre_approved(tmp_path, pat, tool="Write", tool_input=ti)


def test_outside_workspace_write_still_cards(tmp_path):
    ti = {"file_path": "/Users/somebody/.zshrc"}
    pat = permissions.pattern_for("Write", ti)
    assert not permissions.is_pre_approved(tmp_path, pat, tool="Write", tool_input=ti)
