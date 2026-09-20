"""Global CE remains readable/executable when bundled tree is absent."""

from __future__ import annotations

from pathlib import Path

from switchbay import cebridge, skillkit


def test_ce_root_falls_back_to_global_skill(tmp_path: Path, monkeypatch):
    bundled = tmp_path / "missing-vendor" / "curiosity-engine"
    global_ce = tmp_path / ".agents" / "skills" / "curiosity-engine"
    (global_ce / "scripts").mkdir(parents=True)
    (global_ce / "SKILL.md").write_text("# curiosity-engine\n", encoding="utf-8")
    (global_ce / "scripts" / "planner.py").write_text("print('{}')\n", encoding="utf-8")
    monkeypatch.setenv("SWITCHBAY_CE_ROOT", str(bundled))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        cebridge, "_ce_root_candidates",
        lambda: [bundled, global_ce],
    )
    root = cebridge.ce_root()
    assert root == global_ce
    assert cebridge.ce_scripts_available() is True


def test_enterprise_setup_flag_does_not_hide_scripts(tmp_path: Path, monkeypatch):
    from switchbay import admin_policy
    ce = tmp_path / "ce"
    (ce / "scripts").mkdir(parents=True)
    (ce / "scripts" / "sweep.py").write_text("print('{}')\n", encoding="utf-8")
    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    monkeypatch.delenv("SWITCHBAY_ADMIN_POLICY", raising=False)
    admin_policy.reset_cache()
    monkeypatch.setattr(cebridge, "ce_root", lambda: ce)
    assert not admin_policy.feature_enabled("ce_auto_setup")
    assert cebridge.ce_scripts_available() is True
    listed = cebridge.ce_root() / "scripts" / "sweep.py"
    assert listed.is_file()
    admin_policy.reset_cache()


def test_skillkit_lists_global_ce(tmp_path: Path, monkeypatch):
    ce = tmp_path / ".agents" / "skills" / "curiosity-engine"
    ce.mkdir(parents=True)
    (ce / "SKILL.md").write_text(
        "---\nname: curiosity-engine\ndescription: wiki\n---\n# CE\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cebridge, "ce_root", lambda: ce)
    ws = tmp_path / "ws"
    ws.mkdir()
    skills = skillkit.list_skills(ws)
    names = {s.name for s in skills}
    assert "curiosity-engine" in names
