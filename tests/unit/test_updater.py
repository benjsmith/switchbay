"""Settings → Update: GitHub release compare + apply, no live network."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from aiohttp.test_utils import make_mocked_request

from switchbay import admin_policy, daemon, updater

_REAL_PYTHON_INSTALL = updater.python_install


@pytest.fixture(autouse=True)
def _no_real_okstratr(monkeypatch):
    """Keep tests off whatever okstratr the test machine has installed."""
    monkeypatch.setattr(updater, "python_install", lambda _comp: None)


def test_parse_version_strips_v_and_trailing_text():
    assert updater.parse_version("v0.9.10") == (0, 9, 10)
    assert updater.parse_version("0.9.10") == (0, 9, 10)
    assert updater.parse_version("1.3") == (1, 3)
    assert updater.parse_version("v1.3.0 — atlas") == (1, 3, 0)
    assert updater.parse_version("") is None
    assert updater.parse_version("main") is None


def test_version_less_pads_shorter_tuples():
    assert updater.version_less("0.9.10", "0.9.11")
    assert updater.version_less("v0.9.10", "v1.0.0")
    assert updater.version_less("1.3", "1.3.1")
    assert not updater.version_less("0.9.10", "0.9.10")
    assert not updater.version_less("1.3.0", "0.9.10")
    assert not updater.version_less("unknown", "1.0.0")


def test_display_tag_adds_v_for_numeric():
    assert updater.display_tag("0.9.10") == "v0.9.10"
    assert updater.display_tag("v0.9.10") == "v0.9.10"
    assert updater.display_tag("") == ""


def test_changelog_version_reads_first_heading(tmp_path):
    p = tmp_path / "CHANGELOG.md"
    p.write_text(
        "# Changelog\n\n## v0.7.0 — 2026-07-05\n\nnotes\n\n## v0.6.0\n",
        encoding="utf-8",
    )
    assert updater._changelog_version(p) == "0.7.0"
    p.write_text("## 2026-08-18 — v0.9.10 — title\n", encoding="utf-8")
    assert updater._changelog_version(p) == "0.9.10"


def test_local_skill_version_from_changelog_when_not_git(tmp_path):
    skill = tmp_path / "curiosity-merge"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: curiosity-merge\n---\n", encoding="utf-8")
    (skill / "CHANGELOG.md").write_text("## v0.7.0\n", encoding="utf-8")
    assert updater.local_skill_version(skill) == "0.7.0"


def test_installed_components_local_only(tmp_path, monkeypatch):
    skill = tmp_path / "curiosity-merge"
    skill.mkdir()
    (skill / "SKILL.md").write_text("x", encoding="utf-8")
    (skill / "CHANGELOG.md").write_text("## v0.7.0\n", encoding="utf-8")

    monkeypatch.setattr(updater, "local_switchbay_version", lambda: "0.9.12")
    monkeypatch.setattr(updater.skillkit, "_global_skill_roots", lambda: [tmp_path])
    monkeypatch.setattr(updater.cebridge, "ce_root", lambda: tmp_path / "no-ce")
    monkeypatch.setattr(updater, "_skill_git_repo", lambda _p: None)

    rows = {r["id"]: r for r in updater.installed_components()}
    assert rows["switchbay"]["current"] == "v0.9.12"
    assert rows["curiosity-engine"]["installed"] is False
    assert rows["curiosity-engine"]["current"] is None
    assert rows["curiosity-merge"]["current"] == "v0.7.0"


def test_installed_components_never_invents_a_version(tmp_path, monkeypatch):
    """An install with no git tag and no CHANGELOG has no local version.

    This used to fall back to a `related_version` constant compiled into
    Switch Bay, so Help reported whatever the skill's version was when
    someone last edited that line. Silence is the honest answer; the
    number is filled in from GitHub by resolve_unknown_versions.
    """
    skill = tmp_path / "curiosity-engine"
    skill.mkdir()
    (skill / "SKILL.md").write_text("x", encoding="utf-8")

    monkeypatch.setattr(updater, "local_switchbay_version", lambda: "0.9.12")
    monkeypatch.setattr(updater.skillkit, "_global_skill_roots", lambda: [tmp_path])
    monkeypatch.setattr(updater.cebridge, "ce_root", lambda: skill)
    monkeypatch.setattr(updater, "_skill_git_repo", lambda _p: None)

    rows = {r["id"]: r for r in updater.installed_components()}
    assert rows["curiosity-engine"]["installed"] is True
    assert rows["curiosity-engine"]["current"] is None
    assert rows["curiosity-engine"]["source"] == "unknown"


def test_resolve_unknown_versions_fingerprints_the_install(tmp_path, monkeypatch):
    skill = tmp_path / "curiosity-engine"
    skill.mkdir()
    (skill / "SKILL.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(updater, "local_switchbay_version", lambda: "0.9.12")
    monkeypatch.setattr(updater.skillkit, "_global_skill_roots", lambda: [tmp_path])
    monkeypatch.setattr(updater.cebridge, "ce_root", lambda: skill)
    monkeypatch.setattr(updater, "_skill_git_repo", lambda _p: None)
    monkeypatch.setattr(
        updater, "match_skill_release", lambda comp, d: "v1.5.0"
        if comp.id == "curiosity-engine" else None,
    )

    rows = updater.resolve_unknown_versions(updater.installed_components())
    row = {r["id"]: r for r in rows}["curiosity-engine"]
    assert row["current"] == "v1.5.0"
    assert row["source"] == "release-match"


def test_resolve_unknown_versions_stays_quiet_offline(tmp_path, monkeypatch):
    skill = tmp_path / "curiosity-engine"
    skill.mkdir()
    (skill / "SKILL.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(updater, "local_switchbay_version", lambda: "0.9.12")
    monkeypatch.setattr(updater.skillkit, "_global_skill_roots", lambda: [tmp_path])
    monkeypatch.setattr(updater.cebridge, "ce_root", lambda: skill)
    monkeypatch.setattr(updater, "_skill_git_repo", lambda _p: None)

    def _boom(comp, d):
        raise updater.UpdateError("network error")

    monkeypatch.setattr(updater, "match_skill_release", _boom)
    rows = updater.resolve_unknown_versions(updater.installed_components())
    row = {r["id"]: r for r in rows}["curiosity-engine"]
    assert row["current"] is None          # no number beats a wrong number
    assert row["installed"] is True


def test_match_skill_release_walks_older_tags(tmp_path, monkeypatch):
    updater._FP_CACHE.clear()
    skill = tmp_path / "curiosity-engine"
    skill.mkdir()
    body = b"ce skill v1.2.0"
    (skill / "SKILL.md").write_bytes(body)

    monkeypatch.setattr(
        updater, "fetch_release_tags",
        lambda _repo, **_k: ["v1.3.0", "v1.2.0"],
    )

    def fake_remote(_comp, tag):
        if tag == "v1.3.0":
            return hashlib.sha256(b"newer").hexdigest()
        if tag == "v1.2.0":
            return hashlib.sha256(body).hexdigest()
        return None

    monkeypatch.setattr(updater, "_remote_skill_fingerprint", fake_remote)
    assert updater.match_skill_release(updater.COMPONENTS[1], skill) == "v1.2.0"
    # Second call hits the cache — a boom here means we re-walked.
    monkeypatch.setattr(
        updater, "fetch_release_tags",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("uncached")),
    )
    assert updater.match_skill_release(updater.COMPONENTS[1], skill) == "v1.2.0"


@pytest.mark.asyncio
async def test_versions_endpoint(monkeypatch):
    monkeypatch.setattr(updater, "installed_components", lambda: [
        {"id": "switchbay", "label": "Switch Bay", "kind": "app",
         "installed": True, "current": "v0.9.12"},
    ])
    req = make_mocked_request("GET", "/api/versions", app={})
    resp = await daemon.handle_versions(req)
    assert resp.status == 200
    import json
    body = json.loads(resp.body)
    assert body["ok"] is True
    assert body["components"][0]["current"] == "v0.9.12"


def test_find_skill_dir_uses_global_roots(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    skill = root / "curiosity-merge"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(updater.skillkit, "_global_skill_roots", lambda: [root])
    monkeypatch.setattr(updater.cebridge, "ce_root", lambda: tmp_path / "no-ce")
    assert updater.find_skill_dir("curiosity-merge") == skill
    assert updater.find_skill_dir("curiosity-engine") is None


def test_check_marks_older_switchbay(monkeypatch):
    monkeypatch.setattr(updater, "fetch_latest_tag", lambda repo: {
        "benjsmith/switchbay": "v0.9.11",
        "benjsmith/curiosity-engine": "v1.3.0",
        "benjsmith/curiosity-merge": "v0.7.0",
        "benjsmith/okstratr": "v0.2.0",
    }[repo])
    monkeypatch.setattr(updater, "local_switchbay_version", lambda: "0.9.10")
    monkeypatch.setattr(updater, "find_skill_dir", lambda _name: None)

    report = updater.check()
    by_id = {c["id"]: c for c in report["components"]}
    assert by_id["switchbay"]["update_available"] is True
    assert by_id["switchbay"]["latest"] == "v0.9.11"
    assert by_id["curiosity-engine"]["installed"] is False
    assert by_id["curiosity-engine"]["update_available"] is False
    assert report["update_available"] is True


def test_check_hash_match_means_current(tmp_path, monkeypatch):
    skill = tmp_path / "curiosity-engine"
    skill.mkdir()
    body = b"---\nname: curiosity-engine\n---\n"
    (skill / "SKILL.md").write_bytes(body)

    monkeypatch.setattr(updater, "fetch_latest_tag", lambda repo: {
        "benjsmith/switchbay": "v0.9.10",
        "benjsmith/curiosity-engine": "v1.3.0",
        "benjsmith/curiosity-merge": "v0.7.0",
        "benjsmith/okstratr": "v0.2.0",
    }[repo])
    monkeypatch.setattr(updater, "local_switchbay_version", lambda: "0.9.10")

    def _find(name: str) -> Path | None:
        return skill if name == "curiosity-engine" else None

    monkeypatch.setattr(updater, "find_skill_dir", _find)
    monkeypatch.setattr(updater, "_skill_git_repo", lambda _p: None)
    monkeypatch.setattr(updater, "local_skill_version", lambda _p: None)
    monkeypatch.setattr(
        updater, "fetch_remote_bytes",
        lambda repo, tag, rel: body if "SKILL.md" in rel else None,
    )

    report = updater.check()
    ce = next(c for c in report["components"] if c["id"] == "curiosity-engine")
    assert ce["update_available"] is False
    assert ce["current"] == "v1.3.0"


def test_check_hash_mismatch_offers_update(tmp_path, monkeypatch):
    skill = tmp_path / "curiosity-engine"
    skill.mkdir()
    (skill / "SKILL.md").write_bytes(b"old skill")

    monkeypatch.setattr(updater, "fetch_latest_tag", lambda repo: {
        "benjsmith/switchbay": "v0.9.10",
        "benjsmith/curiosity-engine": "v1.3.0",
        "benjsmith/curiosity-merge": "v0.7.0",
        "benjsmith/okstratr": "v0.2.0",
    }[repo])
    monkeypatch.setattr(updater, "local_switchbay_version", lambda: "0.9.10")
    monkeypatch.setattr(
        updater, "find_skill_dir",
        lambda name: skill if name == "curiosity-engine" else None,
    )
    monkeypatch.setattr(updater, "_skill_git_repo", lambda _p: None)
    monkeypatch.setattr(updater, "local_skill_version", lambda _p: None)
    monkeypatch.setattr(updater, "fetch_remote_bytes", lambda *_a, **_k: b"new skill")

    report = updater.check()
    ce = next(c for c in report["components"] if c["id"] == "curiosity-engine")
    assert ce["update_available"] is True
    assert ce["current"] == "unknown"


def test_apply_skips_when_everything_current(monkeypatch):
    monkeypatch.setattr(updater, "check", lambda: {
        "ok": True,
        "error": None,
        "update_available": False,
        "components": [
            {
                "id": "switchbay",
                "label": "Switch Bay",
                "latest": "v0.9.10",
                "current": "v0.9.10",
                "installed": True,
                "update_available": False,
                "error": None,
            },
            {
                "id": "curiosity-engine",
                "label": "Curiosity Engine",
                "latest": "v1.3.0",
                "current": "v1.3.0",
                "installed": True,
                "update_available": False,
                "error": None,
            },
            {
                "id": "curiosity-merge",
                "label": "Curiosity Merge",
                "latest": "v0.7.0",
                "current": None,
                "installed": False,
                "update_available": False,
                "error": None,
            },
        ],
    })
    applied = []
    monkeypatch.setattr(updater, "_apply_switchbay", lambda *a, **k: applied.append("sb"))
    monkeypatch.setattr(updater, "_apply_skill", lambda *a, **k: applied.append("sk"))

    result = updater.apply()
    assert result["ok"] is True
    assert result["updated"] is False
    assert applied == []
    assert result["components"][0]["status"] == "unchanged"
    assert all(c["status"] == "unchanged" for c in result["components"])
    assert result["summary"] == "Already up to date."


def test_apply_updates_only_older_then_reports(monkeypatch):
    monkeypatch.setattr(updater, "check", lambda: {
        "ok": True,
        "error": None,
        "update_available": True,
        "components": [
            {
                "id": "switchbay",
                "label": "Switch Bay",
                "latest": "v0.9.11",
                "current": "v0.9.10",
                "installed": True,
                "update_available": True,
                "error": None,
            },
            {
                "id": "curiosity-engine",
                "label": "Curiosity Engine",
                "latest": "v1.3.0",
                "current": "v1.3.0",
                "installed": True,
                "update_available": False,
                "error": None,
            },
            {
                "id": "curiosity-merge",
                "label": "Curiosity Merge",
                "latest": "v0.7.0",
                "current": "v0.6.0",
                "installed": True,
                "update_available": True,
                "error": None,
            },
        ],
    })
    monkeypatch.setattr(updater, "_apply_switchbay", lambda _c, latest: {
        "id": "switchbay", "label": "Switch Bay", "status": "updated",
        "from": "v0.9.10", "to": latest, "detail": "checked out",
    })
    monkeypatch.setattr(updater, "_apply_skill", lambda _c, latest: {
        "id": "curiosity-merge", "label": "Curiosity Merge", "status": "updated",
        "from": "v0.6.0", "to": latest, "detail": "npx",
    })

    result = updater.apply()
    assert result["ok"] is True
    assert result["updated"] is True
    assert "Switch Bay" in result["summary"]
    assert "Curiosity Merge" in result["summary"]


def test_apply_switchbay_skips_dirty_tree(tmp_path, monkeypatch):
    repo = tmp_path / "switchbay"
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setattr(updater.service, "_repo_root", lambda: repo)
    monkeypatch.setattr(updater, "_git_dirty", lambda _p: True)
    fetched = []
    monkeypatch.setattr(updater, "_git", lambda *a, **k: fetched.append(a) or type(
        "R", (), {"returncode": 0, "stdout": "", "stderr": ""}
    )())

    row = updater._apply_switchbay(updater.COMPONENTS[0], "v0.9.11")
    assert row["status"] == "skipped"
    assert "local changes" in row["detail"]
    assert fetched == []


def test_apply_skill_npx_rolls_back_partial(tmp_path, monkeypatch):
    skill = tmp_path / "curiosity-merge"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("ok", encoding="utf-8")
    (skill / "scripts" / "setup.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    def fake_run(argv, **_k):
        # Simulate the root-layout brick: wipe scripts/.
        setup = skill / "scripts" / "setup.sh"
        if setup.is_file():
            setup.unlink()
        return type("R", (), {"returncode": 0, "stdout": "updated", "stderr": ""})()

    monkeypatch.setattr(updater, "_run", fake_run)
    monkeypatch.setattr(updater, "_npx", lambda: "/usr/bin/npx")
    monkeypatch.setattr(updater, "local_skill_version", lambda _p: "0.6.0")

    row = updater._apply_skill_npx(updater.COMPONENTS[2], skill, "v0.7.0")
    assert row["status"] == "failed"
    assert "partial" in row["detail"]
    assert (skill / "scripts" / "setup.sh").is_file()


def test_apply_skill_npx_succeeds_when_sentinel_stays(tmp_path, monkeypatch):
    skill = tmp_path / "curiosity-engine"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("ok", encoding="utf-8")
    (skill / "scripts" / "setup.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    ran = []

    def fake_run(argv, **_k):
        ran.append(argv)
        return type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr(updater, "_run", fake_run)
    monkeypatch.setattr(updater, "_npx", lambda: "/usr/bin/npx")
    monkeypatch.setattr(updater, "local_skill_version", lambda _p: None)

    row = updater._apply_skill_npx(updater.COMPONENTS[1], skill, "v1.3.0")
    assert row["status"] == "updated"
    assert ran and "update" in ran[0]


@pytest.mark.asyncio
async def test_update_check_endpoint(monkeypatch):
    monkeypatch.setattr(updater, "check", lambda: {
        "ok": True, "update_available": False, "components": [], "error": None,
    })
    req = make_mocked_request("GET", "/api/update/check", app={})
    resp = await daemon.handle_update_check(req)
    assert resp.status == 200


@pytest.mark.asyncio
async def test_update_endpoint_restarts_when_managed(monkeypatch):
    spawned = []
    monkeypatch.setattr(updater, "apply", lambda: {
        "ok": True,
        "updated": True,
        "summary": "Updated Switch Bay (v0.9.10 → v0.9.11).",
        "components": [],
        "error": None,
    })
    monkeypatch.setattr(daemon.service, "spawn_restart", lambda: spawned.append(True))

    req = make_mocked_request("POST", "/api/update", app={"service_managed": True})
    resp = await daemon.handle_update(req)
    assert resp.status == 200
    assert spawned == [True]
    import json
    body = json.loads(resp.body)
    assert body["restarted"] is True


@pytest.mark.asyncio
async def test_update_endpoint_reexecs_unmanaged_after_apply(monkeypatch):
    spawned: list[str] = []
    monkeypatch.setattr(updater, "apply", lambda: {
        "ok": True,
        "updated": True,
        "summary": "Updated Curiosity Engine (v1.2 → v1.3.0).",
        "components": [],
        "error": None,
    })
    monkeypatch.setattr(daemon.service, "spawn_restart", lambda: spawned.append("svc"))
    monkeypatch.setattr(daemon.service, "spawn_self_reexec", lambda: spawned.append("self"))
    monkeypatch.setattr(daemon, "_schedule_daemon_exit", lambda app, **kw: spawned.append("exit"))

    req = make_mocked_request("POST", "/api/update", app={"service_managed": False})
    resp = await daemon.handle_update(req)
    assert resp.status == 200
    assert spawned == ["self", "exit"]
    import json
    body = json.loads(resp.body)
    assert body["restarted"] is True


@pytest.mark.asyncio
async def test_update_endpoint_no_restart_when_already_current(monkeypatch):
    spawned = []
    monkeypatch.setattr(updater, "apply", lambda: {
        "ok": True,
        "updated": False,
        "summary": "Already up to date.",
        "components": [],
        "error": None,
    })
    monkeypatch.setattr(daemon.service, "spawn_restart", lambda: spawned.append(True))

    req = make_mocked_request("POST", "/api/update", app={"service_managed": True})
    resp = await daemon.handle_update(req)
    assert resp.status == 200
    assert spawned == []
    import json
    assert json.loads(resp.body)["restarted"] is False


def test_file_sha256_roundtrip(tmp_path):
    p = tmp_path / "SKILL.md"
    data = b"hello"
    p.write_bytes(data)
    assert updater._file_sha256(p) == hashlib.sha256(data).hexdigest()


def test_git_dirty_ignores_policy_keep(tmp_path, monkeypatch):
    def policy_only(_args, *, cwd, timeout=0):
        return type("R", (), {
            "returncode": 0,
            "stdout": "?? admin.json\n?? SWITCHBAY_PROFILE\n M admin.baked.json\n",
            "stderr": "",
        })()

    monkeypatch.setattr(updater, "_git", policy_only)
    assert updater._git_dirty(tmp_path) is False

    def with_src(_args, *, cwd, timeout=0):
        return type("R", (), {
            "returncode": 0,
            "stdout": " M src/switchbay/updater.py\n?? admin.json\n",
            "stderr": "",
        })()

    monkeypatch.setattr(updater, "_git", with_src)
    assert updater._git_dirty(tmp_path) is True


def test_apply_switchbay_skips_non_git(tmp_path, monkeypatch):
    repo = tmp_path / "payload"
    repo.mkdir()
    monkeypatch.setattr(updater.service, "_repo_root", lambda: repo)
    row = updater._apply_switchbay(updater.COMPONENTS[0], "v0.11.1")
    assert row["status"] == "skipped"
    assert "package" in row["detail"] or "git" in row["detail"]


def test_apply_switchbay_restores_baked_policy(tmp_path, monkeypatch):
    repo = tmp_path / "switchbay"
    repo.mkdir()
    (repo / ".git").mkdir()
    baked = repo / "admin.baked.json"
    baked.write_text(
        '{"profile":"enterprise","features":{"in_app_update":true}}',
        encoding="utf-8",
    )
    marker = repo / "SWITCHBAY_PROFILE"
    marker.write_text("enterprise\n", encoding="utf-8")
    overlay = repo / "admin.json"
    overlay.write_text('{"features":{"hf_model_download":true}}', encoding="utf-8")

    monkeypatch.setattr(updater.service, "_repo_root", lambda: repo)
    monkeypatch.setattr(updater, "_git_dirty", lambda _p: False)
    monkeypatch.setattr(updater, "_git_detached", lambda _p: True)
    monkeypatch.setattr(updater, "_sync_and_build", lambda _p: None)

    def fake_git(args, *, cwd, timeout=0):
        if args[:2] == ["fetch", "--tags"]:
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if args[:3] == ["rev-parse", "-q", "--verify"]:
            return type("R", (), {"returncode": 0, "stdout": "abc", "stderr": ""})()
        if args[:2] == ["rev-parse", "HEAD"]:
            return type("R", (), {"returncode": 0, "stdout": "old\n", "stderr": ""})()
        if args[0] == "rev-parse" and "^{commit}" in str(args[1]):
            return type("R", (), {"returncode": 0, "stdout": "new\n", "stderr": ""})()
        if args[0] == "checkout":
            baked.unlink(missing_ok=True)
            marker.unlink(missing_ok=True)
            overlay.unlink(missing_ok=True)
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(updater, "_git", fake_git)
    row = updater._apply_switchbay(updater.COMPONENTS[0], "v0.11.1")
    assert row["status"] == "updated"
    assert baked.is_file()
    assert "in_app_update" in baked.read_text(encoding="utf-8")
    assert marker.read_text(encoding="utf-8") == "enterprise\n"
    assert overlay.is_file()


def test_check_skips_skills_on_enterprise(monkeypatch, tmp_path):
    p = tmp_path / "admin.json"
    p.write_text(json.dumps({"profile": "enterprise"}), encoding="utf-8")
    monkeypatch.setenv("SWITCHBAY_ADMIN_POLICY", str(p))
    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    monkeypatch.setenv("SWITCHBAY_INSTALL_ROOT", str(tmp_path / "no-install"))
    admin_policy.reset_cache()
    fetched: list[str] = []

    def fake_latest(repo):
        fetched.append(repo)
        return "v0.11.1"

    monkeypatch.setattr(updater, "fetch_latest_tag", fake_latest)
    monkeypatch.setattr(updater, "local_switchbay_version", lambda: "0.11.0")
    report = updater.check()
    assert fetched == [admin_policy.update_repo()]
    skills = [c for c in report["components"] if c["kind"] == "skill"]
    assert skills and all(not c["update_available"] for c in skills)
    admin_policy.reset_cache()


def test_apply_skips_npx_skills_when_locked(tmp_path, monkeypatch):
    p = tmp_path / "admin.json"
    p.write_text(json.dumps({
        "profile": "enterprise",
        "features": {"in_app_update": True, "install_skills_npx": False},
        "updates": {"include_skills": True},
    }), encoding="utf-8")
    monkeypatch.setenv("SWITCHBAY_ADMIN_POLICY", str(p))
    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    admin_policy.reset_cache()
    monkeypatch.setattr(updater, "check", lambda: {
        "ok": True,
        "update_available": True,
        "error": None,
        "components": [{
            "id": "curiosity-merge",
            "label": "Curiosity Merge",
            "kind": "skill",
            "update_available": True,
            "latest": "v0.7.0",
            "installed": True,
            "current": "v0.6.0",
            "channel": "npx",
            "error": None,
        }],
    })
    applied: list[str] = []
    monkeypatch.setattr(
        updater, "_apply_skill",
        lambda *a, **k: applied.append("sk") or {
            "id": "curiosity-merge", "status": "updated",
        },
    )
    result = updater.apply()
    assert applied == []
    assert result["components"][0]["status"] == "skipped"
    assert "install_skills_npx" in result["components"][0]["detail"]
    admin_policy.reset_cache()


def _git_init(path, env):
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True, env=env)


def _commit(path, text, env):
    (path / "f.txt").write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", text], check=True, env=env)
    out = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, env=env,
    )
    return out.stdout.strip()


def test_fetch_tags_survives_a_rewritten_release_tag(tmp_path):
    """A rewritten upstream tag must not brick the in-app updater.

    `git fetch --tags` refuses to move a local tag that points elsewhere
    and fails the WHOLE fetch with "would clobber existing tag" — so one
    force-pushed release tag upstream left Update permanently failing
    until someone deleted tags by hand in a terminal.
    """
    env = {**os.environ, "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
           "GIT_CONFIG_SYSTEM": str(tmp_path / "gitconfig-sys")}
    origin = tmp_path / "origin"
    origin.mkdir()
    _git_init(origin, env)
    _commit(origin, "one", env)
    subprocess.run(["git", "-C", str(origin), "tag", "v1.0.0"], check=True, env=env)

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(origin), str(clone)], check=True, env=env,
    )

    # Upstream rewrites history and re-points the release tag.
    rewritten = _commit(origin, "one-rewritten", env)
    subprocess.run(["git", "-C", str(origin), "tag", "-f", "v1.0.0"], check=True, env=env)

    plain = subprocess.run(
        ["git", "-C", str(clone), "fetch", "--tags", "origin"],
        capture_output=True, text=True, env=env,
    )
    assert plain.returncode != 0
    assert "would clobber existing tag" in (plain.stderr + plain.stdout)

    forced = updater._fetch_tags(clone)
    assert forced.returncode == 0, forced.stderr
    local = subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "v1.0.0^{commit}"],
        capture_output=True, text=True, check=True, env=env,
    )
    assert local.stdout.strip() == rewritten     # remote's tag won


def test_fetch_failure_names_the_clobber_cause():
    proc = subprocess.CompletedProcess(
        args=[], returncode=1,
        stdout="", stderr="! [rejected] v1.0.0 -> v1.0.0 (would clobber existing tag)",
    )
    detail = updater._fetch_failure_detail(proc)
    assert "points elsewhere" in detail
    assert "--force" in detail

    other = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="fatal: could not read from remote",
    )
    assert "could not read from remote" in updater._fetch_failure_detail(other)


# ── okstratr + per-install-mode coverage ────────────────────────────

OKS = next(c for c in updater.COMPONENTS if c.id == "okstratr")
CE = next(c for c in updater.COMPONENTS if c.id == "curiosity-engine")
CM = next(c for c in updater.COMPONENTS if c.id == "curiosity-merge")


def _R(rc=0, out="", err=""):
    return type("R", (), {"returncode": rc, "stdout": out, "stderr": err})()


def _latest(repo):
    return {
        "benjsmith/switchbay": "v0.13.2",
        "benjsmith/curiosity-engine": "v1.9.1",
        "benjsmith/curiosity-merge": "v0.8.4",
        "benjsmith/okstratr": "v0.2.0",
    }[repo]


def test_components_cover_switchbay_and_three_main_skills():
    assert [c.id for c in updater.COMPONENTS] == [
        "switchbay", "curiosity-engine", "curiosity-merge", "okstratr",
    ]
    assert OKS.repo == "benjsmith/okstratr"
    assert OKS.python_package == "okstratr"


def test_cli_python_reads_plain_shebang(tmp_path):
    exe = tmp_path / "okstratr"
    exe.write_text("#!/home/u/.local/share/uv/tools/okstratr/bin/python\nimport x\n")
    py, repo = updater._cli_python([str(exe)])
    assert py == "/home/u/.local/share/uv/tools/okstratr/bin/python"
    assert repo is None


def test_cli_python_reads_sh_exec_form(tmp_path):
    exe = tmp_path / "okstratr"
    exe.write_text(
        "#!/bin/sh\n'''exec' \"/opt/long path/venv/bin/python\" \"$0\" \"$@\"\n' '''\n"
    )
    py, repo = updater._cli_python([str(exe)])
    assert py == "/opt/long path/venv/bin/python"
    assert repo is None


def test_cli_python_reads_okstratr_setup_wrapper(tmp_path):
    exe = tmp_path / "okstratr"
    exe.write_text(
        "#!/usr/bin/env bash\n"
        'export PYTHONPATH="/src/okstratr/src:${PYTHONPATH:-}"\n'
        'exec /usr/bin/python3.12 -m okstratr "$@"\n'
    )
    py, repo = updater._cli_python([str(exe)])
    assert py == "/usr/bin/python3.12"
    assert repo == Path("/src/okstratr")


def test_cli_python_module_form():
    assert updater._cli_python(["/venv/bin/python", "-m", "okstratr"]) == (
        "/venv/bin/python", None,
    )


def test_is_uv_tool_python(monkeypatch):
    monkeypatch.delenv("UV_TOOL_DIR", raising=False)
    assert updater._is_uv_tool_python("/home/u/.local/share/uv/tools/okstratr/bin/python")
    assert not updater._is_uv_tool_python("/home/u/venvs/work/bin/python")
    monkeypatch.setenv("UV_TOOL_DIR", "/custom/tools")
    assert updater._is_uv_tool_python("/custom/tools/okstratr/bin/python")


def _use_real_python_install(monkeypatch, *, python, probe, wrapper_repo=None):
    monkeypatch.setattr(updater, "python_install", _REAL_PYTHON_INSTALL)
    monkeypatch.setattr(updater, "_cli_argv", lambda _c: ["/bin/okstratr"])
    monkeypatch.setattr(updater, "_cli_python", lambda _a: (python, wrapper_repo))
    monkeypatch.setattr(updater, "_probe_python", lambda _py, _pkg: probe)


def test_python_install_editable_git_checkout(tmp_path, monkeypatch):
    repo = tmp_path / "okstratr"
    _use_real_python_install(monkeypatch, python="/r/.venv/bin/python", probe={
        "version": "0.1.0",
        "direct_url": {"url": repo.as_uri(), "dir_info": {"editable": True}},
    })
    monkeypatch.setattr(updater, "_package_git_repo", lambda src, pkg: repo)
    monkeypatch.setattr(updater, "_git_describe_tag", lambda _r: "v0.1.0")
    inst = updater.python_install(OKS)
    assert inst.channel == "git"
    assert inst.repo == repo
    assert inst.version == "v0.1.0"


def test_python_install_setup_wrapper_is_git(tmp_path, monkeypatch):
    repo = tmp_path / "okstratr"
    _use_real_python_install(monkeypatch, python=None, probe=None, wrapper_repo=repo)
    monkeypatch.setattr(updater, "_package_git_repo", lambda src, pkg: src)
    monkeypatch.setattr(updater, "_git_describe_tag", lambda _r: "v0.1.0")
    inst = updater.python_install(OKS)
    assert inst.channel == "git" and inst.repo == repo


def test_python_install_uv_tool(monkeypatch):
    monkeypatch.delenv("UV_TOOL_DIR", raising=False)
    py = "/home/u/.local/share/uv/tools/okstratr/bin/python"
    _use_real_python_install(monkeypatch, python=py, probe={
        "version": "0.1.0",
        "direct_url": {
            "url": "https://github.com/benjsmith/okstratr",
            "vcs_info": {"vcs": "git", "requested_revision": "v0.1.0"},
        },
    })
    inst = updater.python_install(OKS)
    assert inst.channel == "uv-tool"
    assert inst.python == py
    assert inst.version == "0.1.0"


def test_python_install_pip(monkeypatch):
    monkeypatch.delenv("UV_TOOL_DIR", raising=False)
    _use_real_python_install(
        monkeypatch, python="/home/u/venvs/work/bin/python",
        probe={"version": "0.1.0", "direct_url": None},
    )
    inst = updater.python_install(OKS)
    assert inst.channel == "pip"


def test_python_install_editable_outside_git_is_unknown(tmp_path, monkeypatch):
    _use_real_python_install(monkeypatch, python="/x/bin/python", probe={
        "version": "0.1.0",
        "direct_url": {"url": tmp_path.as_uri(), "dir_info": {"editable": True}},
    })
    monkeypatch.setattr(updater, "_package_git_repo", lambda src, pkg: None)
    assert updater.python_install(OKS).channel == "unknown"


def test_python_install_falls_back_to_skill_git_checkout(tmp_path, monkeypatch):
    skill = tmp_path / "okstratr" / "skills" / "okstratr"
    skill.mkdir(parents=True)
    _use_real_python_install(monkeypatch, python="/venv/bin/python", probe=None)
    monkeypatch.setattr(updater, "find_skill_dir", lambda name: skill)
    monkeypatch.setattr(updater, "_skill_git_repo", lambda d: tmp_path / "okstratr")
    monkeypatch.setattr(updater, "local_skill_version", lambda d: "v0.1.0")
    inst = updater.python_install(OKS)
    assert inst.channel == "git" and inst.repo == tmp_path / "okstratr"


def test_python_install_skill_text_only_is_unknown(tmp_path, monkeypatch):
    _use_real_python_install(monkeypatch, python="/venv/bin/python", probe=None)
    monkeypatch.setattr(updater, "find_skill_dir", lambda name: tmp_path)
    monkeypatch.setattr(updater, "_skill_git_repo", lambda d: None)
    assert updater.python_install(OKS).channel == "unknown"


def test_python_install_absent(monkeypatch):
    _use_real_python_install(monkeypatch, python="/venv/bin/python", probe=None)
    monkeypatch.setattr(updater, "find_skill_dir", lambda name: None)
    assert updater.python_install(OKS) is None


def test_check_reports_every_skill_by_install_mode(tmp_path, monkeypatch):
    """CE from git, CM from npx, okstratr as a uv tool — current vs latest each."""
    ce_dir, cm_dir = tmp_path / "curiosity-engine", tmp_path / "curiosity-merge"
    for d in (ce_dir, cm_dir):
        d.mkdir()
        (d / "SKILL.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(updater, "fetch_latest_tag", _latest)
    monkeypatch.setattr(updater, "local_switchbay_version", lambda: "0.13.1")
    monkeypatch.setattr(updater, "find_skill_dir", lambda name: {
        "curiosity-engine": ce_dir, "curiosity-merge": cm_dir,
    }.get(name))
    monkeypatch.setattr(
        updater, "_skill_git_repo", lambda d: d if d == ce_dir else None,
    )
    monkeypatch.setattr(updater, "local_skill_version", lambda d: {
        ce_dir: "v1.9.0", cm_dir: "0.8.4",
    }.get(d))
    monkeypatch.setattr(updater, "python_install", lambda comp: updater.PyInstall(
        "uv-tool", "/t/okstratr", python="/t/bin/python", version="0.1.0",
    ))

    report = updater.check()
    by = {c["id"]: c for c in report["components"]}
    assert (by["switchbay"]["current"], by["switchbay"]["latest"]) == ("v0.13.1", "v0.13.2")
    assert by["curiosity-engine"]["channel"] == "git"
    assert (by["curiosity-engine"]["current"], by["curiosity-engine"]["latest"]) == (
        "v1.9.0", "v1.9.1",
    )
    assert by["curiosity-engine"]["update_available"] is True
    assert by["curiosity-merge"]["channel"] == "npx"
    assert by["curiosity-merge"]["update_available"] is False
    assert by["okstratr"]["channel"] == "uv-tool"
    assert (by["okstratr"]["current"], by["okstratr"]["latest"]) == ("v0.1.0", "v0.2.0")
    assert by["okstratr"]["update_available"] is True
    assert by["okstratr"]["tag"] == "v0.2.0"


def test_check_skips_okstratr_when_not_installed(monkeypatch):
    monkeypatch.setattr(updater, "fetch_latest_tag", _latest)
    monkeypatch.setattr(updater, "local_switchbay_version", lambda: "0.13.2")
    monkeypatch.setattr(updater, "find_skill_dir", lambda _n: None)
    report = updater.check()
    oks = next(c for c in report["components"] if c["id"] == "okstratr")
    assert oks["installed"] is False
    assert oks["update_available"] is False
    assert report["update_available"] is False


def test_check_unknown_source_is_reported_not_guessed(monkeypatch):
    monkeypatch.setattr(updater, "fetch_latest_tag", _latest)
    monkeypatch.setattr(updater, "local_switchbay_version", lambda: "0.13.2")
    monkeypatch.setattr(updater, "find_skill_dir", lambda _n: None)
    monkeypatch.setattr(updater, "python_install", lambda c: updater.PyInstall(
        "unknown", "/somewhere", version="0.1.0",
    ))
    oks = next(c for c in updater.check()["components"] if c["id"] == "okstratr")
    assert oks["channel"] == "unknown"
    assert "terminal" in oks["detail"]


def test_apply_okstratr_uv_tool_reinstalls_at_release_tag(monkeypatch):
    inst = updater.PyInstall("uv-tool", "/t", python="/t/bin/python", version="0.1.0")
    monkeypatch.setattr(updater, "python_install", lambda c: inst)
    monkeypatch.setattr(updater, "_uv", lambda: "/usr/bin/uv")
    ran = []
    monkeypatch.setattr(updater, "_run", lambda argv, **k: ran.append(argv) or _R())
    monkeypatch.setattr(updater, "_probe_python", lambda py, pkg: {"version": "0.2.0"})
    row = updater._apply_skill(OKS, "v0.2.0")
    assert row["status"] == "updated", row
    assert ran == [[
        "/usr/bin/uv", "tool", "install", "--force",
        "okstratr @ git+https://github.com/benjsmith/okstratr@v0.2.0",
    ]]
    assert row["from"] == "v0.1.0" and row["to"] == "v0.2.0"


def test_apply_okstratr_uv_tool_without_uv_fails_cleanly(monkeypatch):
    inst = updater.PyInstall("uv-tool", "/t", python="/t/bin/python", version="0.1.0")
    monkeypatch.setattr(updater, "python_install", lambda c: inst)
    monkeypatch.setattr(updater, "_uv", lambda: None)
    monkeypatch.setattr(updater, "_run", lambda *a, **k: pytest.fail("must not run"))
    row = updater._apply_skill(OKS, "v0.2.0")
    assert row["status"] == "failed" and "uv" in row["detail"]


def test_apply_okstratr_pip_upgrade(monkeypatch):
    inst = updater.PyInstall("pip", "/v", python="/v/bin/python", version="0.1.0")
    monkeypatch.setattr(updater, "python_install", lambda c: inst)
    ran = []
    monkeypatch.setattr(updater, "_run", lambda argv, **k: ran.append(argv) or _R())
    monkeypatch.setattr(updater, "_probe_python", lambda py, pkg: {"version": "0.2.0"})
    row = updater._apply_skill(OKS, "v0.2.0")
    assert row["status"] == "updated"
    assert ran[0][:5] == ["/v/bin/python", "-m", "pip", "install", "--upgrade"]


def test_apply_okstratr_pip_falls_back_to_uv_pip(monkeypatch):
    inst = updater.PyInstall("pip", "/v", python="/v/bin/python", version="0.1.0")
    monkeypatch.setattr(updater, "python_install", lambda c: inst)
    monkeypatch.setattr(updater, "_uv", lambda: "/usr/bin/uv")
    ran = []

    def fake_run(argv, **_k):
        ran.append(argv)
        if argv[1:3] == ["-m", "pip"]:
            return _R(1, err="/v/bin/python: No module named pip")
        return _R()

    monkeypatch.setattr(updater, "_run", fake_run)
    monkeypatch.setattr(updater, "_probe_python", lambda py, pkg: {"version": "0.2.0"})
    row = updater._apply_skill(OKS, "v0.2.0")
    assert row["status"] == "updated"
    assert ran[1][:5] == ["/usr/bin/uv", "pip", "install", "--python", "/v/bin/python"]


def test_apply_okstratr_fails_when_version_did_not_move(monkeypatch):
    inst = updater.PyInstall("pip", "/v", python="/v/bin/python", version="0.1.0")
    monkeypatch.setattr(updater, "python_install", lambda c: inst)
    monkeypatch.setattr(updater, "_run", lambda argv, **k: _R())
    monkeypatch.setattr(updater, "_probe_python", lambda py, pkg: {"version": "0.1.0"})
    row = updater._apply_skill(OKS, "v0.2.0")
    assert row["status"] == "failed" and "still reports" in row["detail"]


def test_apply_okstratr_git_checkout_uses_tag(tmp_path, monkeypatch):
    inst = updater.PyInstall("git", str(tmp_path), repo=tmp_path, version="v0.1.0")
    monkeypatch.setattr(updater, "python_install", lambda c: inst)
    seen = []
    monkeypatch.setattr(updater, "_apply_skill_git", lambda comp, repo, latest: seen.append(
        (comp.id, repo, latest),
    ) or {"id": comp.id, "label": comp.label, "status": "updated",
          "from": "", "to": latest, "detail": f"checked out {latest}"})
    row = updater._apply_skill(OKS, "v0.2.0")
    assert seen == [("okstratr", tmp_path, "v0.2.0")]
    assert row["status"] == "updated" and row["from"] == "v0.1.0"
    assert row["channel"] == "git"


def test_apply_okstratr_unknown_or_absent_is_skipped(monkeypatch):
    monkeypatch.setattr(updater, "_run", lambda *a, **k: pytest.fail("must not run"))
    monkeypatch.setattr(updater, "python_install", lambda c: None)
    assert updater._apply_skill(OKS, "v0.2.0")["status"] == "skipped"
    monkeypatch.setattr(updater, "python_install", lambda c: updater.PyInstall(
        "unknown", "/x", version="0.1.0",
    ))
    row = updater._apply_skill(OKS, "v0.2.0")
    assert row["status"] == "skipped" and "terminal" in row["detail"]


def test_apply_skill_git_checks_out_release_tag(tmp_path, monkeypatch):
    """CE / CM git checkouts: fetch, then fast-forward to the tag."""
    monkeypatch.setattr(updater, "_git_dirty", lambda _p: False)
    monkeypatch.setattr(updater, "_git_detached", lambda _p: False)
    monkeypatch.setattr(updater, "_is_ancestor", lambda r, a, b: True)
    monkeypatch.setattr(updater, "local_skill_version", lambda _p: "v1.9.0")
    calls = []

    def fake_git(args, *, cwd, timeout=0):
        calls.append(args)
        if args[:2] == ["rev-parse", "HEAD"]:
            return _R(out="old\n")
        if args[0] == "rev-parse" and "^{commit}" in str(args[1]):
            return _R(out="new\n")
        return _R()

    monkeypatch.setattr(updater, "_git", fake_git)
    row = updater._apply_skill_git(CE, tmp_path, "v1.9.1")
    assert row["status"] == "updated"
    assert ["merge", "--ff-only", "v1.9.1"] in calls


def test_apply_routes_ce_and_cm_by_install_source(tmp_path, monkeypatch):
    ce_dir, cm_dir = tmp_path / "ce", tmp_path / "cm"
    monkeypatch.setattr(updater, "find_skill_dir", lambda name: {
        "curiosity-engine": ce_dir, "curiosity-merge": cm_dir,
    }[name])
    monkeypatch.setattr(updater, "_skill_git_repo", lambda d: d if d == ce_dir else None)
    routed = []
    monkeypatch.setattr(updater, "_apply_skill_git", lambda c, r, l: routed.append(
        ("git", c.id)) or {"status": "updated"})
    monkeypatch.setattr(updater, "_apply_skill_npx", lambda c, d, l: routed.append(
        ("npx", c.id)) or {"status": "updated"})
    updater._apply_skill(CE, "v1.9.1")
    updater._apply_skill(CM, "v0.8.4")
    assert routed == [("git", "curiosity-engine"), ("npx", "curiosity-merge")]


def _behind_report():
    def row(cid, label, cur, latest, channel, installed=True, behind=True):
        return {
            "id": cid, "label": label, "kind": "skill" if cid != "switchbay" else "app",
            "current": cur, "latest": latest, "tag": latest, "installed": installed,
            "update_available": behind, "error": None, "channel": channel,
        }
    return {
        "ok": True, "error": None, "update_available": True,
        "components": [
            row("switchbay", "Switch Bay", "v0.13.2", "v0.13.2", "git", behind=False),
            row("curiosity-engine", "Curiosity Engine", "v1.9.0", "v1.9.1", "git"),
            row("curiosity-merge", "Curiosity Merge", None, "v0.8.4", None,
                installed=False, behind=False),
            row("okstratr", "okstratr", "v0.1.0", "v0.2.0", "uv-tool"),
        ],
    }


def test_apply_updates_behind_skills_and_restarts_their_processes(tmp_path, monkeypatch):
    from switchbay import ce_viewer_supervisor, okstratr_supervisor

    monkeypatch.setattr(updater, "check", _behind_report)
    monkeypatch.setattr(updater, "_apply_switchbay", lambda *a: pytest.fail("current"))
    applied = []
    monkeypatch.setattr(updater, "_apply_skill", lambda comp, latest: applied.append(
        (comp.id, latest)) or {
            "id": comp.id, "label": comp.label, "status": "updated",
            "from": "old", "to": latest, "detail": "done",
        })
    events = []
    monkeypatch.setattr(ce_viewer_supervisor, "bound_workspace", lambda: tmp_path)
    monkeypatch.setattr(ce_viewer_supervisor, "rebuild_bundle",
                        lambda ws: events.append(("rebuild", ws)) or {"ok": True})
    monkeypatch.setattr(ce_viewer_supervisor, "stop",
                        lambda: events.append(("stop", "ce")) or {"ok": True})
    monkeypatch.setattr(okstratr_supervisor, "stop",
                        lambda: events.append(("stop", "okstratr")) or {"ok": True})

    result = updater.apply()
    assert applied == [("curiosity-engine", "v1.9.1"), ("okstratr", "v0.2.0")]
    assert events == [("rebuild", tmp_path), ("stop", "ce"), ("stop", "okstratr")]
    by = {r["id"]: r for r in result["components"]}
    assert by["curiosity-merge"]["status"] == "unchanged"
    assert by["curiosity-merge"]["detail"] == "not installed"
    assert "viewer rebuilt" in by["curiosity-engine"]["detail"]
    assert "okstratr restarts" in by["okstratr"]["detail"]
    assert result["updated"] is True and result["ok"] is True
    assert "Curiosity Engine (old → v1.9.1)" in result["summary"]
    assert "okstratr (old → v0.2.0)" in result["summary"]


def test_failed_skill_update_does_not_touch_its_process(monkeypatch):
    from switchbay import ce_viewer_supervisor, okstratr_supervisor

    monkeypatch.setattr(updater, "check", _behind_report)
    monkeypatch.setattr(updater, "_apply_skill", lambda comp, latest: {
        "id": comp.id, "label": comp.label, "status": "failed",
        "from": "old", "to": latest, "detail": "boom",
    })
    monkeypatch.setattr(ce_viewer_supervisor, "stop", lambda: pytest.fail("no stop"))
    monkeypatch.setattr(okstratr_supervisor, "stop", lambda: pytest.fail("no stop"))
    result = updater.apply()
    assert result["ok"] is False and result["updated"] is False


def test_skill_include_policy_blocks_okstratr_too(monkeypatch, tmp_path):
    p = tmp_path / "admin.json"
    p.write_text(json.dumps({
        "profile": "enterprise",
        "features": {"in_app_update": True},
        "updates": {"include_skills": False},
    }), encoding="utf-8")
    monkeypatch.setenv("SWITCHBAY_ADMIN_POLICY", str(p))
    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    admin_policy.reset_cache()
    try:
        monkeypatch.setattr(updater, "check", _behind_report)
        monkeypatch.setattr(updater, "_apply_skill", lambda *a: pytest.fail("blocked"))
        result = updater.apply()
        by = {r["id"]: r for r in result["components"]}
        assert by["okstratr"]["status"] == "skipped"
        assert "include_skills" in by["okstratr"]["detail"]
        assert by["curiosity-engine"]["status"] == "skipped"
    finally:
        admin_policy.reset_cache()


@pytest.mark.asyncio
@pytest.mark.parametrize("handler,method,path", [
    ("handle_update", "POST", "/api/update"),
    ("handle_update_check", "GET", "/api/update/check"),
])
async def test_in_app_update_false_blocks_check_and_apply(
    monkeypatch, tmp_path, handler, method, path,
):
    p = tmp_path / "admin.json"
    p.write_text(json.dumps({
        "profile": "enterprise",
        "features": {"in_app_update": False},
        "updates": {"include_skills": True},
    }), encoding="utf-8")
    monkeypatch.setenv("SWITCHBAY_ADMIN_POLICY", str(p))
    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    admin_policy.reset_cache()
    try:
        monkeypatch.setattr(updater, "apply", lambda: pytest.fail("must not apply"))
        monkeypatch.setattr(updater, "check", lambda: pytest.fail("must not check"))
        req = make_mocked_request(method, path, app={"service_managed": True})
        resp = await getattr(daemon, handler)(req)
        assert resp.status == 403
    finally:
        admin_policy.reset_cache()


def test_probe_python_reads_a_real_interpreter():
    import sys
    info = updater._probe_python(sys.executable, "pytest")
    assert info and info["version"]
    assert updater._probe_python(sys.executable, "sb_no_such_pkg_xyz") is None
