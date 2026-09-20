"""JXA iCloud helper: local fixture, argv isolation, bounded timeout."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from switchbay import icloud_download, statedir


def test_helper_exists_and_argv_is_literal():
    assert icloud_download.HELPER.is_file()
    path = Path("/tmp/Switch Bay test; rm -rf /secret.pptx")
    argv = icloud_download.helper_argv("probe", path)
    assert argv[:3] == ["/usr/bin/osascript", "-l", "JavaScript"]
    assert argv[3] == str(icloud_download.HELPER)
    assert argv[4] == "probe"
    assert argv[5] == str(path)
    assert "rm -rf" not in " ".join(argv[:5])


@pytest.mark.skipif(not icloud_download.supported(), reason="no osascript/JXA on this host")
def test_helper_probes_harmless_local_fixture(tmp_path: Path):
    fixture = tmp_path / "local-fixture.txt"
    fixture.write_text("not icloud", encoding="utf-8")
    out = icloud_download.run_helper("probe", fixture, timeout=10.0)
    assert out.get("ok") is True, out
    assert out.get("ubiquitous") in (False, None, 0)
    # start on a non-ubiquitous file must not hang and must not crash.
    start = icloud_download.run_helper("start", fixture, timeout=10.0)
    assert "started" in start or "ok" in start
    ready = icloud_download.hydrate_file(fixture, timeout=1.0)
    assert ready.ready is True
    assert Path(ready.path) == fixture.resolve() or Path(ready.path) == fixture


@pytest.mark.skipif(not icloud_download.supported(), reason="no osascript/JXA on this host")
def test_helper_rejects_unknown_action_without_path_interpolation(tmp_path: Path):
    fixture = tmp_path / "x.txt"
    fixture.write_text("x", encoding="utf-8")
    out = icloud_download.run_helper("not-an-action", fixture, timeout=5.0)
    assert out.get("ok") is False
    assert "unknown action" in str(out.get("error") or "")


def test_hydrate_timeout_is_bounded_when_dataless(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    target = tmp_path / "cloud.pptx"
    target.write_bytes(b"x")
    monkeypatch.setattr(statedir, "is_dataless", lambda p: Path(p) == target)
    monkeypatch.setattr(
        icloud_download, "run_helper",
        lambda *_a, **_k: {"ok": True, "ubiquitous": True, "started": True},
    )
    monkeypatch.setattr(icloud_download, "supported", lambda: True)
    t0 = time.monotonic()
    result = icloud_download.hydrate_file(target, timeout=0.3)
    elapsed = time.monotonic() - t0
    assert elapsed < 2.0
    assert result.ready is False
    assert result.retryable is True


def test_logical_path_strips_legacy_stub():
    stub = Path("/tmp/.Quarterly.pptx.icloud")
    assert icloud_download.is_icloud_stub(stub)
    assert icloud_download.logical_path(stub) == Path("/tmp/Quarterly.pptx")
    plain = Path("/tmp/Quarterly.pptx")
    assert not icloud_download.is_icloud_stub(plain)
    assert icloud_download.logical_path(plain) == plain


def test_non_icloud_cloud_hint_does_not_claim_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    target = tmp_path / "OneDrive" / "doc.pptx"
    target.parent.mkdir()
    target.write_bytes(b"x")
    monkeypatch.setattr(statedir, "is_dataless", lambda p: Path(p) == target)
    monkeypatch.setattr(
        statedir, "sync_service_hint", lambda _p: "OneDrive",
    )
    result = icloud_download.hydrate_file(target, timeout=0.2)
    assert result.ready is False
    assert result.retryable is True
    assert "iCloud-only" in (result.error or "")
