"""Workspace HTML deck path helpers."""

from __future__ import annotations

from pathlib import Path

from switchbay import html_decks


def test_list_and_resolve(tmp_path: Path):
    d = html_decks.ensure_deck(
        tmp_path, "demo-show", title="Demo", wiki_topics=["transformer"],
    )
    assert "slideshows" in str(d)
    (d / "index.html").write_text("<html><body>hi</body></html>", encoding="utf-8")
    (d / "clip.mp4").write_bytes(b"fake")
    decks = html_decks.list_decks(tmp_path)
    assert len(decks) == 1
    assert decks[0]["slug"] == "demo-show"
    assert decks[0]["title"] == "Demo"
    assert decks[0]["has_media"] is True

    entry = html_decks.resolve_file(tmp_path, "demo-show", "index.html")
    assert entry is not None and entry.is_file()
    media = html_decks.resolve_file(tmp_path, "demo-show", "clip.mp4")
    assert media is not None
    assert html_decks.resolve_file(tmp_path, "demo-show", "../etc/passwd") is None
    assert html_decks.resolve_file(tmp_path, "../nope", "x") is None


def test_wiki_link_markdown():
    link = html_decks.wiki_link_markdown("foo", "Foo")
    assert "slideshow:foo" in link
    assert "deck:foo" not in link  # reserved language for Sketch decks


def test_migrate_legacy_decks_moves_and_removes_root(tmp_path: Path):
    legacy = tmp_path / "decks" / "old-show"
    legacy.mkdir(parents=True)
    (legacy / "index.html").write_text("<html>old</html>", encoding="utf-8")
    (legacy / "clip.mp4").write_bytes(b"vid")

    res = html_decks.migrate_legacy_decks(tmp_path)
    assert res is not None
    assert res["moved"] == 1
    assert res["removed_root"] is True
    assert not (tmp_path / "decks").exists()
    dest = tmp_path / "slideshows" / "old-show"
    assert (dest / "index.html").is_file()
    assert (dest / "clip.mp4").is_file()
    # idempotent
    assert html_decks.migrate_legacy_decks(tmp_path) is None


def test_migrate_legacy_decks_prefers_slideshows_copy(tmp_path: Path):
    legacy = tmp_path / "decks" / "demo"
    legacy.mkdir(parents=True)
    (legacy / "index.html").write_text("legacy", encoding="utf-8")
    keep = tmp_path / "slideshows" / "demo"
    keep.mkdir(parents=True)
    (keep / "index.html").write_text("canonical", encoding="utf-8")

    res = html_decks.migrate_legacy_decks(tmp_path)
    assert res is not None
    assert res["removed_dupes"] == 1
    assert (keep / "index.html").read_text(encoding="utf-8") == "canonical"
    assert not (tmp_path / "decks").exists()
