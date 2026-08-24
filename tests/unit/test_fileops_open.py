"""open_external locates vault/wiki basenames from frontmatter sources."""

from __future__ import annotations

from pathlib import Path

import pytest

from switchbay import fileops


def test_locate_basename_in_vault(tmp_path: Path):
    (tmp_path / "vault").mkdir()
    f = tmp_path / "vault" / "foo.html.extracted.md"
    f.write_text("x", encoding="utf-8")
    assert fileops.locate(tmp_path, "foo.html.extracted.md") == f.resolve()
    assert fileops.locate(tmp_path, "vault/foo.html.extracted.md") == f.resolve()


def test_locate_basename_in_wiki(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    f = tmp_path / "wiki" / "note.md"
    f.write_text("x", encoding="utf-8")
    assert fileops.locate(tmp_path, "note.md") == f.resolve()


def test_locate_prefers_explicit_path(tmp_path: Path):
    (tmp_path / "vault").mkdir()
    (tmp_path / "wiki").mkdir()
    vault = tmp_path / "vault" / "same.md"
    wiki = tmp_path / "wiki" / "same.md"
    vault.write_text("v", encoding="utf-8")
    wiki.write_text("w", encoding="utf-8")
    assert fileops.locate(tmp_path, "wiki/same.md") == wiki.resolve()
    assert fileops.locate(tmp_path, "same.md") == vault.resolve()


def test_locate_strips_vault_prefix(tmp_path: Path):
    (tmp_path / "vault").mkdir()
    f = tmp_path / "vault" / "doc.md"
    f.write_text("x", encoding="utf-8")
    assert fileops.locate(tmp_path, "vault:doc.md") == f.resolve()


def test_locate_rejects_escape(tmp_path: Path):
    with pytest.raises(fileops.FileOpError):
        fileops.locate(tmp_path, "../secret")
    with pytest.raises(fileops.FileOpError):
        fileops.locate(tmp_path, "/etc/passwd")


def test_locate_missing(tmp_path: Path):
    with pytest.raises(fileops.FileOpError, match="not found"):
        fileops.locate(tmp_path, "ghost.md")


@pytest.mark.asyncio
async def test_open_external_uses_located_path(tmp_path: Path, monkeypatch):
    (tmp_path / "vault").mkdir()
    f = tmp_path / "vault" / "a.json.extracted.md"
    f.write_text("x", encoding="utf-8")
    ran: list[list[str]] = []

    class Proc:
        async def wait(self) -> int:
            return 0

    async def fake_exec(*argv: str, **_k):
        ran.append(list(argv))
        return Proc()

    monkeypatch.setattr(fileops.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(fileops.sys, "platform", "darwin")
    await fileops.open_external(tmp_path, "a.json.extracted.md")
    assert ran == [["open", str(f.resolve())]]
