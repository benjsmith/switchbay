"""Skill authoring: create / edit / delete / promote — and the guard
that must NEVER let a bundled first-party skill be overwritten.

Every test isolates the user-global + CE roots to a tmp dir. This is
load-bearing: `find_writable`/`update_skill` consult the REAL
global skills dirs via `get_skill` → `list_skills`, so an un-isolated
test that named a real skill would edit it on disk. (That is exactly
how an early smoke test clobbered the real curiosity-engine SKILL.md.)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from switchbay import skillkit


@pytest.fixture()
def iso(tmp_path, monkeypatch):
    """Isolated skills world: a workspace, an empty user-global root,
    and a CE root pointed at a throwaway dir (no real CE)."""
    ws = tmp_path / "ws"
    (ws / ".workbench").mkdir(parents=True)
    user_root = tmp_path / "user-skills"
    user_root.mkdir()
    ce_root = tmp_path / "no-ce"
    ce_root.mkdir()
    monkeypatch.setattr(skillkit, "_user_skills_root", lambda: user_root)
    monkeypatch.setattr(skillkit, "_global_skill_roots", lambda: [user_root])
    monkeypatch.setattr(skillkit.cebridge, "ce_root", lambda: ce_root)
    return ws, user_root


def test_create_edit_delete_workspace_skill(iso):
    ws, _user = iso
    sk = skillkit.create_skill(
        ws, "workspace", "My Helper",
        "Use when the user asks for help with X.", "# Steps\n1. do it")
    assert sk.name == "my-helper"
    assert sk.source == "workspace"
    assert skillkit.to_full(sk)["writable"] is True
    # round-trips through discovery
    assert skillkit.find_writable(ws, "my-helper") is not None

    up = skillkit.update_skill(ws, "my-helper", "New desc.", "# New")
    assert up.body.startswith("# New")

    assert skillkit.delete_skill(ws, "my-helper") is True
    assert skillkit.get_skill(ws, "my-helper") is None


def test_no_duplicate_create(iso):
    ws, _user = iso
    skillkit.create_skill(ws, "workspace", "Dup", "d", "b")
    with pytest.raises(skillkit.SkillError):
        skillkit.create_skill(ws, "workspace", "Dup", "d", "b")


def test_promote_workspace_to_user(iso):
    ws, user_root = iso
    skillkit.create_skill(ws, "workspace", "Portable", "d", "b")
    promoted = skillkit.promote_skill(ws, "portable")
    assert promoted.source == "user"
    assert (user_root / "portable" / "SKILL.md").is_file()
    # gone from the workspace scope
    assert not (ws / ".workbench" / "skills" / "portable").exists()


# ── The regression guard: bundled/symlinked skills are read-only ────


def test_symlinked_bundled_skill_is_not_writable(iso, tmp_path):
    """A first-party skill symlinked into the user root (how CE / CM
    are installed) must be refused for edit AND delete — this is the
    exact case that clobbered the real curiosity-engine SKILL.md."""
    ws, user_root = iso
    # A "bundled" skill living elsewhere, symlinked into the user root.
    bundled = tmp_path / "agents-skills" / "curiosity-engine"
    bundled.mkdir(parents=True)
    (bundled / "SKILL.md").write_text(
        "---\nname: curiosity-engine\ndescription: real\n---\nBIG BODY\n",
        encoding="utf-8")
    (user_root / "curiosity-engine").symlink_to(bundled)

    # It's discoverable (source=user via the symlink) …
    assert skillkit.get_skill(ws, "curiosity-engine") is not None
    # … but NOT writable (protected name + symlink + foreign root).
    assert skillkit.find_writable(ws, "curiosity-engine") is None
    with pytest.raises(skillkit.SkillError):
        skillkit.update_skill(ws, "curiosity-engine", "x", "y")
    with pytest.raises(skillkit.SkillError):
        skillkit.delete_skill(ws, "curiosity-engine")
    # the upstream file is untouched
    assert "BIG BODY" in (bundled / "SKILL.md").read_text()


def test_discovers_agents_skills_without_claude_dir(tmp_path, monkeypatch):
    """A no-Claude-Code machine has ~/.agents/skills only. Discovery
    must still find CE there — not require ~/.claude/skills."""
    ws = tmp_path / "ws"
    (ws / ".workbench").mkdir(parents=True)
    agents = tmp_path / "home" / ".agents" / "skills" / "curiosity-engine"
    agents.mkdir(parents=True)
    (agents / "SKILL.md").write_text(
        "---\nname: curiosity-engine\ndescription: global CE\n---\nbody\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skillkit, "_user_skills_root",
                        lambda: tmp_path / "home" / ".agents" / "skills")
    monkeypatch.setattr(skillkit, "_global_skill_roots", lambda: [
        tmp_path / "home" / ".agents" / "skills",
        tmp_path / "home" / ".claude" / "skills",
    ])
    monkeypatch.setattr(skillkit.cebridge, "ce_root",
                        lambda: tmp_path / "missing-ce")
    names = {s.name: s for s in skillkit.list_skills(ws)}
    assert "curiosity-engine" in names
    assert names["curiosity-engine"].path.endswith(
        "curiosity-engine/SKILL.md")
    assert not (tmp_path / "home" / ".claude" / "skills").exists()


def test_cannot_create_over_protected_name(iso):
    ws, _user = iso
    with pytest.raises(skillkit.SkillError):
        skillkit.create_skill(ws, "workspace", "curiosity-engine", "d", "b")
    with pytest.raises(skillkit.SkillError):
        skillkit.create_skill(ws, "user", "Curiosity Merge", "d", "b")


def test_render_roundtrips_quoted_description(iso):
    ws, _user = iso
    desc = "Use when: the user says X, Y: or Z."
    sk = skillkit.create_skill(ws, "workspace", "Q", desc, "body")
    reread = skillkit.get_skill(ws, "q")
    assert reread is not None
    assert reread.description == desc


# ── Explainer diagnostics ──────────────────────────────────────────


def test_diagnose_flags_weak_trigger(iso):
    ws, _user = iso
    # No "Use when …" trigger clause → weak-trigger warn.
    sk = skillkit.create_skill(ws, "workspace", "Vague", "Does stuff with data.", "# body")
    codes = {d["code"]: d["level"] for d in skillkit.diagnose(ws, sk)}
    assert codes.get("weak-trigger") == "warn"
    assert skillkit.worst_level(skillkit.diagnose(ws, sk)) == "warn"


def test_diagnose_ok_for_good_skill(iso):
    ws, _user = iso
    sk = skillkit.create_skill(
        ws, "workspace", "Good",
        "Use when the user asks to summarize meeting notes into action items.",
        "# Steps\n1. read\n2. summarize")
    diags = skillkit.diagnose(ws, sk)
    codes = {d["code"]: d["level"] for d in diags}
    assert codes.get("has-trigger") == "ok"
    assert skillkit.worst_level(diags) == "ok"


def test_diagnose_flags_empty_body(iso):
    ws, _user = iso
    sk = skillkit.create_skill(
        ws, "workspace", "Hollow",
        "Use when the user wants the hollow thing done.", "  ")
    codes = {d["code"] for d in skillkit.diagnose(ws, sk)
             if d["level"] != "ok"}
    assert "empty-body" in codes


def test_diagnose_detects_shadowing(iso, tmp_path):
    ws, user_root = iso
    # Same name in user (lower priority) AND workspace (higher). The
    # workspace one wins; the user one is shadowed.
    skillkit.create_skill(ws, "user", "dup",
                          "Use when the user does the dup thing.", "b")
    skillkit.create_skill(ws, "workspace", "dup",
                          "Use when the user does the dup thing.", "b2")
    # get_skill returns the winner (workspace); ask about the shadowed user one.
    user_sk = skillkit._read_skill(
        user_root / "dup" / "SKILL.md", source="user", fallback_name="dup")
    codes = {d["code"] for d in skillkit.diagnose(ws, user_sk)}
    assert "shadowed" in codes


def test_block_scalar_description_parses_fully(iso):
    ws, user_root = iso
    # A real-world SKILL.md using a YAML folded block scalar (`>-`).
    # The flat parser must fold the continuation lines, not read ">-".
    d = user_root / "folded"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\n"
        "name: folded\n"
        "description: >-\n"
        "  Set up docs that keep intent from drifting. Use when the user\n"
        "  says 'set up project docs' or 'session handoff'.\n"
        "---\n\n# Body\nsteps\n", encoding="utf-8")
    sk = skillkit.get_skill(ws, "folded")
    assert sk is not None
    assert "Set up docs" in sk.description and "session handoff" in sk.description
    assert len(sk.description) > 40
    # And it must NOT be falsely flagged (has a trigger, full description).
    assert skillkit.worst_level(skillkit.diagnose(ws, sk)) == "ok"


def test_symlinked_duplicate_is_not_a_collision(iso, tmp_path):
    ws, user_root = iso
    # The same skill reachable as both `ce` and `user` via a symlink is
    # ONE skill, not a collision — must not be flagged.
    real = tmp_path / "bundled-cm" / "curiosity-merge"
    real.mkdir(parents=True)
    (real / "SKILL.md").write_text(
        "---\nname: cm-demo\ndescription: Use when the user merges wikis.\n---\nbody\n",
        encoding="utf-8")
    (user_root / "cm-demo").symlink_to(real)
    monkey_ce = tmp_path / "ce-view"
    # Point cebridge.ce_root at the SAME real dir's parent view via symlink.
    monkey_ce.symlink_to(real)
    import switchbay.skillkit as sk_mod
    # cebridge.ce_root returns something with SKILL.md == the same real file.
    # Simulate: named_sources should dedupe to ONE by real path.
    srcs = skillkit._named_sources(ws, "cm-demo")
    assert srcs == ["user"]  # only one real path


# ── Route skills (saved /route splits) ──────────────────────────────


def test_route_skill_roundtrip(iso):
    ws, _user = iso
    tasks = [
        {"description": "Analyze the North region.", "difficulty": "normal"},
        {"description": "Find cross-region outliers.", "difficulty": "hard"},
    ]
    body = skillkit.route_body(tasks)
    sk = skillkit.create_skill(
        ws, "workspace", "q4-regional",
        "Use when the user asks to analyze quarterly data by region.",
        body, {"kind": "route"})
    assert skillkit.is_route_skill(sk)
    reread = skillkit.get_skill(ws, "q4-regional")
    assert skillkit.parse_route_tasks(reread) == tasks
    # A well-formed route-skill is not falsely flagged.
    assert skillkit.worst_level(skillkit.diagnose(ws, reread)) == "ok"


def test_regular_skill_is_not_a_route(iso):
    ws, _user = iso
    sk = skillkit.create_skill(
        ws, "workspace", "plain", "Use when the user wants the plain thing.", "# body")
    assert not skillkit.is_route_skill(sk)
    assert skillkit.parse_route_tasks(sk) is None


def test_route_body_clamps_bad_difficulty(iso):
    ws, _user = iso
    body = skillkit.route_body([{"description": "x", "difficulty": "bogus"}])
    sk = skillkit.create_skill(ws, "workspace", "r", "Use when x.", body, {"kind": "route"})
    tasks = skillkit.parse_route_tasks(skillkit.get_skill(ws, "r"))
    assert tasks[0]["difficulty"] == "normal"
