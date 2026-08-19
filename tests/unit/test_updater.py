"""Settings → Update: GitHub release compare + apply, no live network."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from aiohttp.test_utils import make_mocked_request

from switchbay import daemon, updater


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
async def test_update_endpoint_applies_but_does_not_restart_dev_daemon(monkeypatch):
    spawned = []
    monkeypatch.setattr(updater, "apply", lambda: {
        "ok": True,
        "updated": True,
        "summary": "Updated Curiosity Engine (v1.2 → v1.3.0).",
        "components": [],
        "error": None,
    })
    monkeypatch.setattr(daemon.service, "spawn_restart", lambda: spawned.append(True))
    monkeypatch.setattr(daemon.service, "is_installed", lambda: True)

    req = make_mocked_request("POST", "/api/update", app={"service_managed": False})
    resp = await daemon.handle_update(req)
    assert resp.status == 200
    assert spawned == []
    import json
    body = json.loads(resp.body)
    assert body["restarted"] is False
    assert "development daemon" in body["restart_error"]


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
