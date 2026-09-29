"""vault.db fallback for missing vault/*.extracted.md files."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from switchbay import fileops


def _init_fts(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE VIRTUAL TABLE sources USING fts5(
            path, title, body, date, source_path,
            tokenize='porter unicode61'
        )
        """
    )
    conn.execute(
        "INSERT INTO sources(path, title, body, date, source_path) "
        "VALUES(?,?,?,?,?)",
        (
            "20260101-000000-local-demo.txt.extracted.md",
            "demo",
            "---\ntitle: demo\n---\nhello from fts\n",
            "2026-01-01",
            "/tmp/demo.txt",
        ),
    )
    conn.commit()
    conn.close()


def test_vault_extracted_basename():
    assert fileops.vault_extracted_basename(
        "vault/foo.txt.extracted.md"
    ) == "foo.txt.extracted.md"
    assert fileops.vault_extracted_basename(
        "vault:bar.md.extracted.md"
    ) == "bar.md.extracted.md"
    assert fileops.vault_extracted_basename("wiki/page.md") is None
    assert fileops.vault_extracted_basename("../escape.extracted.md") is None


def test_vault_db_read_body_hits_fts(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = vault / "vault.db"
    _init_fts(db)
    # No on-disk extract — body still available via FTS
    body = fileops.vault_db_read_body(
        tmp_path, "vault/20260101-000000-local-demo.txt.extracted.md",
    )
    assert body is not None
    assert "hello from fts" in body


def test_vault_db_read_body_missing_row(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _init_fts(vault / "vault.db")
    assert fileops.vault_db_read_body(
        tmp_path, "vault/nope.txt.extracted.md",
    ) is None


def test_vault_db_read_body_empty_stub_db(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "vault.db").write_bytes(b"x" * 100)  # tiny stub
    assert fileops.vault_db_read_body(
        tmp_path, "vault/foo.txt.extracted.md",
    ) is None
