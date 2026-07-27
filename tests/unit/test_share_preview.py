"""Publish preview + secret scan: what leaves the machine, and the
warning before it does."""

from __future__ import annotations

from switchbay import share


def test_is_published_scope():
    assert share._is_published("wiki/a.md", include_vault=True)
    assert not share._is_published(".workbench/secrets.json", include_vault=True)
    assert not share._is_published(".DS_Store", include_vault=True)
    # .curator ships only its two shareable files.
    assert share._is_published(".curator/profile.md", include_vault=True)
    assert not share._is_published(".curator/kuzu/graph.db", include_vault=True)
    # vault opt-out.
    assert share._is_published("vault/raw.txt", include_vault=True)
    assert not share._is_published("vault/raw.txt", include_vault=False)


def _mk(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / ".workbench").mkdir()
    (tmp_path / "vault").mkdir()
    (tmp_path / "wiki" / "note.md").write_text("plain notes, nothing secret\n")
    return tmp_path


def test_preview_counts_and_excludes_workbench(tmp_path):
    _mk(tmp_path)
    (tmp_path / ".workbench" / "state.json").write_text("{}")
    r = share.preview(tmp_path, include_vault=True)
    assert r["file_count"] == 1  # only wiki/note.md
    dirs = {d["dir"] for d in r["top_dirs"]}
    assert "wiki" in dirs
    assert ".workbench" not in dirs


def test_preview_vault_opt_out(tmp_path):
    _mk(tmp_path)
    (tmp_path / "vault" / "raw.txt").write_text("hi")
    assert share.preview(tmp_path, include_vault=True)["file_count"] == 2
    assert share.preview(tmp_path, include_vault=False)["file_count"] == 1


def test_preview_flags_secrets(tmp_path):
    _mk(tmp_path)
    (tmp_path / "wiki" / "leak.md").write_text(
        "here is my key: sk-ant-abcdefghijklmnop0123456789\n"
        "and an aws one AKIAABCDEFGHIJKLMNOP\n"
    )
    # A secret in the EXCLUDED .workbench must NOT be scanned.
    (tmp_path / ".workbench" / "secrets.json").write_text("ghp_" + "x" * 36)
    r = share.preview(tmp_path, include_vault=True)
    hits = {(h["path"], h["kind"]) for h in r["secret_hits"]}
    assert ("wiki/leak.md", "anthropic key") in hits
    assert ("wiki/leak.md", "aws access key") in hits
    assert not any(h["path"].startswith(".workbench") for h in r["secret_hits"])


def test_preview_clean_workspace_has_no_hits(tmp_path):
    _mk(tmp_path)
    assert share.preview(tmp_path, include_vault=True)["secret_hits"] == []
