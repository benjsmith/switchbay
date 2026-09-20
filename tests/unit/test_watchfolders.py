"""Watch-folder scan, hydration pending, retry, races, no shell injection."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from switchbay import icloud_download, statedir, watchfolders
from switchbay.icloud_download import HydrateResult


def _watch_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("switchbay.workspaces.is_within_home", lambda _p: True)
    monkeypatch.setattr(watchfolders, "SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(watchfolders, "_backoff", lambda _n: 0.0)
    ws = tmp_path / "ws"
    (ws / "vault").mkdir(parents=True)
    (ws / ".workbench").mkdir()
    folder = tmp_path / "watch"
    folder.mkdir()
    rec = watchfolders.add_folder(ws, str(folder))
    assert isinstance(rec, dict)
    return ws, folder


def test_baseline_ignores_preexisting_and_picks_new(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("switchbay.workspaces.is_within_home", lambda _p: True)
    monkeypatch.setattr(watchfolders, "SETTLE_SECONDS", 0.0)
    ws = tmp_path / "ws"
    ws.mkdir()
    folder = tmp_path / "watch"
    folder.mkdir()
    old = folder / "old.md"
    old.write_text("old", encoding="utf-8")
    watchfolders.add_folder(ws, str(folder))
    picked, _ = watchfolders.scan_candidates(ws)
    assert picked == []
    new = folder / "new.md"
    new.write_text("hello", encoding="utf-8")
    picked, _ = watchfolders.scan_candidates(ws)
    assert [c.logical for c in picked] == [str(new.resolve())]
    seen = watchfolders._load_seen(ws)
    assert str(new.resolve()) not in seen
    assert str(old.resolve()) in seen


def test_size0_and_icloud_stub_are_pending_not_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    ws, folder = _watch_ws(tmp_path, monkeypatch)
    empty = folder / "empty.md"
    empty.write_bytes(b"")
    stub = folder / ".Deck.pptx.icloud"
    stub.write_bytes(b"")
    picked, _ = watchfolders.scan_candidates(ws)
    kinds = {Path(c.logical).name: c.hydrate for c in picked}
    assert kinds.get("empty.md") == "size0"
    assert kinds.get("Deck.pptx") == "icloud_stub"
    seen = watchfolders._load_seen(ws)
    assert str(empty.resolve()) not in seen
    logical_stub = str((folder / "Deck.pptx").resolve())
    assert logical_stub not in seen


def test_hydration_pending_then_ready_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    ws, folder = _watch_ws(tmp_path, monkeypatch)
    src = folder / "cloud.md"
    src.write_text("payload-once", encoding="utf-8")
    calls = {"hydrate": 0, "ingest": 0}
    dataless = {"on": True}

    def hydrate(path: Path, *, timeout: float = 8.0) -> HydrateResult:
        del timeout
        calls["hydrate"] += 1
        if calls["hydrate"] < 2:
            return HydrateResult(
                ok=False, ready=False, path=str(path),
                error="timeout", retryable=True, detail="timeout",
            )
        dataless["on"] = False
        return HydrateResult(ok=True, ready=True, path=str(path), retryable=False)

    def ingest(workspace: Path, rel: str, timeout: float):
        del workspace, timeout
        calls["ingest"] += 1
        dest = ws / rel
        assert dest.is_file() and dest.stat().st_size > 0
        extracted = ws / "vault" / "cloud.md.extracted.md"
        extracted.write_text("payload-once\n", encoding="utf-8")
        return {
            "ok": 1,
            "results": [{
                "ok": True,
                "extracted": str(extracted),
                "extraction_method": "utf8",
                "extraction_quality": "good",
            }],
        }

    monkeypatch.setattr(
        statedir, "is_dataless",
        lambda p: Path(p).name == "cloud.md" and dataless["on"],
    )
    picked, _ = watchfolders.scan_candidates(ws)
    assert len(picked) == 1
    first = watchfolders.handoff(
        ws, picked[0], hydrate=hydrate, ingest=ingest,
    )
    assert first.status == "pending"
    assert calls["ingest"] == 0
    assert str(src.resolve()) not in watchfolders._load_seen(ws)

    # Backoff is 0; file is due again.
    picked2, _ = watchfolders.scan_candidates(ws)
    assert len(picked2) == 1
    second = watchfolders.handoff(
        ws, picked2[0], hydrate=hydrate, ingest=ingest,
    )
    assert second.status == "success", second
    assert calls["ingest"] == 1
    assert str(src.resolve()) in watchfolders._load_seen(ws)
    picked3, _ = watchfolders.scan_candidates(ws)
    assert picked3 == []
    assert calls["ingest"] == 1
    assert calls["hydrate"] == 2


def test_timeout_failure_retries_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    ws, folder = _watch_ws(tmp_path, monkeypatch)
    src = folder / "note.md"
    src.write_text("ok-body", encoding="utf-8")
    ingest_calls = {"n": 0}

    def ingest(workspace: Path, rel: str, timeout: float):
        del workspace, timeout
        ingest_calls["n"] += 1
        if ingest_calls["n"] == 1:
            return {"ok": False, "error": "boom", "retryable": True}
        extracted = ws / "vault" / "note.md.extracted.md"
        extracted.write_text("ok-body\n", encoding="utf-8")
        return {
            "ok": 1,
            "results": [{
                "ok": True, "extracted": str(extracted),
                "extraction_method": "utf8", "extraction_quality": "good",
            }],
        }

    picked, _ = watchfolders.scan_candidates(ws)
    r1 = watchfolders.handoff(ws, picked[0], ingest=ingest)
    assert r1.status == "error" and r1.retryable
    assert str(src.resolve()) not in watchfolders._load_seen(ws)
    picked2, _ = watchfolders.scan_candidates(ws)
    r2 = watchfolders.handoff(ws, picked2[0], ingest=ingest)
    assert r2.status == "success"
    assert ingest_calls["n"] == 2
    assert str(src.resolve()) in watchfolders._load_seen(ws)


def test_pause_during_hydrate_does_not_mark_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    ws, folder = _watch_ws(tmp_path, monkeypatch)
    src = folder / "x.md"
    src.write_text("x", encoding="utf-8")
    dataless = {"on": True}

    def hydrate(path: Path, *, timeout: float = 8.0) -> HydrateResult:
        del timeout
        watchfolders.set_enabled(ws, str(folder.resolve()), False)
        dataless["on"] = False
        return HydrateResult(ok=True, ready=True, path=str(path))

    monkeypatch.setattr(
        statedir, "is_dataless",
        lambda p: Path(p).name == "x.md" and dataless["on"],
    )
    picked, _ = watchfolders.scan_candidates(ws)
    result = watchfolders.handoff(ws, picked[0], hydrate=hydrate, ingest=lambda *_a: {"ok": 1})
    assert result.status == "skipped"
    assert str(src.resolve()) not in watchfolders._load_seen(ws)


def test_remove_during_stage_does_not_mark_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    ws, folder = _watch_ws(tmp_path, monkeypatch)
    src = folder / "y.md"
    src.write_text("yyyy", encoding="utf-8")
    orig_stage = watchfolders.stage_file

    def stage_and_remove(workspace, src_path, *, timeout=30.0):
        rel, size = orig_stage(workspace, src_path, timeout=timeout)
        watchfolders.remove_folder(workspace, str(folder.resolve()))
        return rel, size

    monkeypatch.setattr(watchfolders, "stage_file", stage_and_remove)
    picked, _ = watchfolders.scan_candidates(ws)
    result = watchfolders.handoff(
        ws, picked[0], ingest=lambda *_a: {"ok": 1, "results": [{"ok": True, "extracted": "x"}]},
    )
    assert result.status == "skipped"
    assert str(src.resolve()) not in watchfolders._load_seen(ws)


def test_symlink_does_not_escape_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    ws, folder = _watch_ws(tmp_path, monkeypatch)
    outside = tmp_path / "secret"
    outside.mkdir()
    target = outside / "leak.md"
    target.write_text("nope", encoding="utf-8")
    link = folder / "leak.md"
    link.symlink_to(target)
    picked, _ = watchfolders.scan_candidates(ws)
    assert picked == []


def test_ready_files_not_starved_by_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    ws, folder = _watch_ws(tmp_path, monkeypatch)
    monkeypatch.setattr(watchfolders, "MAX_PER_BEAT", 2)
    for i in range(3):
        p = folder / f"pend{i}.md"
        p.write_bytes(b"")
    ready_a = folder / "ready-a.md"
    ready_b = folder / "ready-b.md"
    ready_a.write_text("a", encoding="utf-8")
    ready_b.write_text("b", encoding="utf-8")
    # Make pending older so FIFO would prefer them if we didn't prioritize ready.
    older = time.time() - 100
    for i in range(3):
        os.utime(folder / f"pend{i}.md", (older, older))
    picked, backlog = watchfolders.scan_candidates(ws)
    names = [Path(c.logical).name for c in picked]
    assert any(n.startswith("ready-") for n in names)
    assert any(n.startswith("pend") for n in names)
    assert backlog >= 1


def test_inflight_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ws, folder = _watch_ws(tmp_path, monkeypatch)
    src = folder / "z.md"
    src.write_text("z", encoding="utf-8")
    picked, _ = watchfolders.scan_candidates(
        ws, inflight={str(src.resolve())},
    )
    assert picked == []


def test_unsupported_extension_marked_seen_not_ingested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    ws, folder = _watch_ws(tmp_path, monkeypatch)
    dmg = folder / "Installer.dmg"
    dmg.write_bytes(b"not-ingestible")
    picked, _ = watchfolders.scan_candidates(ws)
    assert picked == []
    assert str(dmg.resolve()) in watchfolders._load_seen(ws)


def test_helper_argv_has_no_shell_interpolation():
    nasty = Path("/tmp/foo; rm -rf /; echo.pptx")
    argv = icloud_download.helper_argv("start", nasty)
    assert argv[0] == "/usr/bin/osascript"
    assert argv[1] == "-l"
    assert argv[2] == "JavaScript"
    assert argv[4] == "start"
    assert argv[5] == str(nasty)
    joined = " ".join(argv[:-1])
    assert "rm -rf" not in joined
    assert "; rm" not in joined


def test_normal_local_txt_handoff_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    ws, folder = _watch_ws(tmp_path, monkeypatch)
    src = folder / "local.md"
    src.write_text("local-body", encoding="utf-8")
    ingest_calls = {"n": 0}

    def ingest(workspace, rel, timeout):
        del workspace, timeout
        ingest_calls["n"] += 1
        extracted = ws / "vault" / "local.md.extracted.md"
        extracted.write_text("local-body\n", encoding="utf-8")
        return {
            "ok": 1,
            "results": [{
                "ok": True, "extracted": str(extracted),
                "extraction_method": "utf8", "extraction_quality": "good",
            }],
        }

    picked, _ = watchfolders.scan_candidates(ws)
    result = watchfolders.handoff(ws, picked[0], ingest=ingest)
    assert result.status == "success"
    assert ingest_calls["n"] == 1
    assert (ws / result.vault_rel).is_file()
    assert (ws / result.vault_rel).stat().st_size > 0


def test_fair_pick_gives_due_retries_a_slot_when_ready_fills_cap():
    def cand(name: str, hydrate: str = "") -> watchfolders.Candidate:
        return watchfolders.Candidate(
            path=f"/tmp/{name}", logical=f"/tmp/{name}",
            folder="/tmp", size=10, mtime=1.0, hydrate=hydrate, ext=".md",
        )
    ready = [cand(f"r{i}.md") for i in range(10)]
    due = [cand(f"d{i}.md", hydrate="dataless") for i in range(10)]
    picked = watchfolders._fair_pick(ready, due, 5)
    names = [Path(c.logical).name for c in picked]
    assert any(n.startswith("r") for n in names)
    assert any(n.startswith("d") for n in names)
    assert len(picked) == 5


def test_backoff_exponent_is_capped():
    a = watchfolders._backoff(1)
    huge = watchfolders._backoff(10_000)
    assert huge == watchfolders.MAX_BACKOFF
    assert huge >= a
    # Must not overflow to inf / raise.
    assert huge < float("inf")


@pytest.mark.asyncio
async def test_dispatch_uses_workspace_captured_at_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from switchbay import daemon
    monkeypatch.setattr("switchbay.workspaces.is_within_home", lambda _p: True)
    ws_a = tmp_path / "ws-a"
    ws_b = tmp_path / "ws-b"
    ws_a.mkdir()
    ws_b.mkdir()
    seen: list[Path] = []

    def fake_handoff(workspace, cand, **_k):
        seen.append(Path(workspace))
        return watchfolders.HandoffResult(status="success", logical=cand.logical)

    monkeypatch.setattr(watchfolders, "handoff", fake_handoff)
    monkeypatch.setattr(daemon, "_log_event", lambda *_a, **_k: None)
    monkeypatch.setattr(daemon, "_broadcast_files_changed_soon", lambda *_a, **_k: None)
    app = {"workspace": ws_b, "watch_inflight": set()}
    cand = watchfolders.Candidate(
        path="/tmp/x.md", logical="/tmp/x.md", folder="/tmp",
        size=1, mtime=1.0, ext=".md",
    )
    await daemon._dispatch_watch_ingest(app, cand, workspace=ws_a)
    assert seen == [ws_a]
    assert app["workspace"] == ws_b
