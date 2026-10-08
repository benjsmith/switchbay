"""CE wiki-view bundle freshness: a workspace edited while another one was
active must not come back with a stale Graph after a switch."""

from __future__ import annotations

import os
from pathlib import Path

from switchbay import ce_viewer_supervisor as ce


def _setup(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    ws = tmp_path / "ws"
    (ws / "wiki" / "concepts").mkdir(parents=True)
    page = ws / "wiki" / "concepts" / "a.md"
    page.write_text("# A\n")
    out = tmp_path / "cache" / "ws"
    out.mkdir(parents=True)
    (out / "index.html").write_text("<html></html>")
    (out / "data.json").write_text("{}")
    monkeypatch.setattr(ce.cebridge, "output_dir", lambda _w: out)
    return ws, out


def _age(path: Path, seconds: float) -> None:
    t = path.stat().st_mtime - seconds
    os.utime(path, (t, t))


def _age_wiki(ws: Path, seconds: float) -> None:
    for p in [ws / "wiki", *(ws / "wiki").rglob("*")]:
        _age(p, seconds)


def test_bundle_newer_than_wiki_is_ready(tmp_path: Path, monkeypatch) -> None:
    ws, _out = _setup(tmp_path, monkeypatch)
    _age_wiki(ws, 100)
    assert ce.bundle_ready(ws) is True


def test_page_edited_after_build_is_stale(tmp_path: Path, monkeypatch) -> None:
    ws, out = _setup(tmp_path, monkeypatch)
    _age(out / "data.json", 100)
    assert ce.bundle_ready(ws) is False


def test_deleted_page_marks_bundle_stale(tmp_path: Path, monkeypatch) -> None:
    ws, out = _setup(tmp_path, monkeypatch)
    _age_wiki(ws, 200)
    _age(out / "data.json", 100)
    assert ce.bundle_ready(ws) is True
    # Deleting a page only bumps its folder's mtime.
    (ws / "wiki" / "concepts" / "a.md").unlink()
    assert ce.bundle_ready(ws) is False


def test_missing_bundle_is_not_ready(tmp_path: Path, monkeypatch) -> None:
    ws, out = _setup(tmp_path, monkeypatch)
    (out / "data.json").unlink()
    assert ce.bundle_ready(ws) is False
