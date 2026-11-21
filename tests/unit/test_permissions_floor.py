"""The zero-friction builtin-allow floor: provably-safe reads are
pre-approved, but shell keeps its card."""

from __future__ import annotations

import pytest

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


def test_grok_read_file_under_uploads_pre_approved(tmp_path):
    upload = tmp_path / ".workbench" / "uploads" / "abc" / "pasted-image.png"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"png")
    rel = ".workbench/uploads/abc/pasted-image.png"
    for tool in ("read_file", "hashline_read"):
        for key, value in (
            ("target_file", rel),
            ("path", str(upload)),
            ("file_path", str(upload)),
        ):
            ti = {key: value}
            assert permissions.is_pre_approved(
                tmp_path, permissions.pattern_for(tool, ti),
                tool=tool, tool_input=ti,
            ), (tool, key)


def test_grok_read_file_outside_workspace_still_cards(tmp_path):
    outside = {"target_file": "/etc/passwd"}
    assert not permissions.is_pre_approved(
        tmp_path, permissions.pattern_for("read_file", outside),
        tool="read_file", tool_input=outside,
    )
    escape = {"path": "../outside.txt"}
    assert not permissions.is_pre_approved(
        tmp_path, permissions.pattern_for("read_file", escape),
        tool="read_file", tool_input=escape,
    )
    mixed = {
        "target_file": ".workbench/uploads/pasted-image.png",
        "path": "/etc/passwd",
    }
    assert not permissions.is_pre_approved(
        tmp_path, permissions.pattern_for("read_file", mixed),
        tool="read_file", tool_input=mixed,
    )
    empty = {}
    assert not permissions.is_pre_approved(
        tmp_path, permissions.pattern_for("read_file", empty),
        tool="read_file", tool_input=empty,
    )


def test_grok_read_file_symlink_escape_still_cards(tmp_path):
    outside = tmp_path.parent / "outside-read-target"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("x", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available")
    ti = {"target_file": "link/secret.txt"}
    assert not permissions.is_pre_approved(
        tmp_path, permissions.pattern_for("read_file", ti),
        tool="read_file", tool_input=ti,
    )


def test_grok_write_aliases_inside_workspace_still_card(tmp_path):
    upload = {"target_file": ".workbench/uploads/pasted-image.png"}
    assert not permissions.is_pre_approved(
        tmp_path, permissions.pattern_for("write_file", upload),
        tool="write_file", tool_input=upload,
    )
    edit = {"path": str(tmp_path / "wiki" / "a.md")}
    assert not permissions.is_pre_approved(
        tmp_path, permissions.pattern_for("search_replace", edit),
        tool="search_replace", tool_input=edit,
    )


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


def test_web_search_keeps_the_card(tmp_path):
    pat = permissions.pattern_for("WebSearch", {"query": "qwen"})
    assert not permissions.is_pre_approved(
        tmp_path, pat, tool="WebSearch", tool_input={"query": "qwen"},
    )


def test_orchestration_pattern_is_action_scoped(tmp_path):
    start = permissions.pattern_for(
        "Orchestration",
        {"action": "start-local-server", "summary": "Start MLX"},
    )
    byok = permissions.pattern_for(
        "Orchestration",
        {"action": "use-api-credits", "summary": "Spend keys"},
    )
    assert start == "Orchestration(start-local-server)"
    assert byok == "Orchestration(use-api-credits)"
    assert not permissions.is_pre_approved(
        tmp_path, start, tool="Orchestration",
        tool_input={"action": "start-local-server"},
    )
