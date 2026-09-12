"""Dedicated user markdown tabs for vault extracted sources.

Opening a vault cite should add (or focus) one user tab per file —
idempotent by payload.path — rather than handing the file to the OS
default app.
"""

from __future__ import annotations

import json
from pathlib import Path

from switchbay import tabstore


def _tabs(ws: Path) -> list[dict]:
    data = json.loads((ws / ".workbench" / "mode.json").read_text())
    return [t for t in data["tabs"] if isinstance(t, dict)]


def test_normalize_accepts_scheme_basename_and_prefixed() -> None:
    assert tabstore.normalize_vault_source_path(
        "vault:foo.extracted.md",
    ) == "vault/foo.extracted.md"
    assert tabstore.normalize_vault_source_path(
        "foo.extracted.md",
    ) == "vault/foo.extracted.md"
    assert tabstore.normalize_vault_source_path(
        "vault/foo.extracted.md",
    ) == "vault/foo.extracted.md"
    assert tabstore.normalize_vault_source_path(
        "./vault/sub/bar.md",
    ) == "vault/sub/bar.md"


def test_normalize_rejects_escapes_and_non_markdown() -> None:
    assert tabstore.normalize_vault_source_path("") is None
    assert tabstore.normalize_vault_source_path("../etc/passwd.md") is None
    assert tabstore.normalize_vault_source_path("vault/../secret.md") is None
    assert tabstore.normalize_vault_source_path("/tmp/x.extracted.md") is None
    assert tabstore.normalize_vault_source_path("vault/foo.pdf") is None
    assert tabstore.normalize_vault_source_path("https://example.com/x.md") is None


def test_add_vault_doc_tab_is_idempotent_by_path(tmp_path: Path) -> None:
    tab = tabstore.add_vault_doc_tab(
        tmp_path, "vault:paper.pdf.extracted.md", "paper.pdf.extracted.md",
    )
    assert tab is not None
    assert tab["kind"] == "markdown"
    assert tab["source"] == "user"
    assert tab["title"] == "paper.pdf.extracted.md"
    assert tab["payload"] == {"path": "vault/paper.pdf.extracted.md"}
    assert tab["id"].startswith("vault-")

    again = tabstore.add_vault_doc_tab(tmp_path, "vault/paper.pdf.extracted.md")
    assert again == tab
    vault_tabs = [
        t for t in _tabs(tmp_path)
        if t.get("source") == "user" and t.get("kind") == "markdown"
    ]
    assert len(vault_tabs) == 1


def test_add_creates_one_tab_per_file(tmp_path: Path) -> None:
    a = tabstore.add_vault_doc_tab(tmp_path, "a.extracted.md")
    b = tabstore.add_vault_doc_tab(tmp_path, "b.extracted.md")
    assert a is not None and b is not None
    assert a["id"] != b["id"]
    vault_tabs = [
        t for t in _tabs(tmp_path)
        if t.get("source") == "user" and t.get("kind") == "markdown"
    ]
    assert {t["payload"]["path"] for t in vault_tabs} == {
        "vault/a.extracted.md",
        "vault/b.extracted.md",
    }


def test_does_not_reuse_core_editor_tab(tmp_path: Path) -> None:
    tabstore.add_vault_doc_tab(tmp_path, "vault/src.extracted.md")
    kinds = [t.get("kind") for t in _tabs(tmp_path)]
    # DEFAULT_MODE already has a core markdown Editor; the vault tab
    # is an extra user tab, not a rewrite of that one.
    assert kinds.count("markdown") == 2
    core = next(t for t in _tabs(tmp_path) if t.get("id") == "editor")
    assert core.get("source") in (None, "", "core")
    assert "path" not in (core.get("payload") or {})


def test_remove_vault_doc_tab(tmp_path: Path) -> None:
    tab = tabstore.add_vault_doc_tab(tmp_path, "vault/x.extracted.md")
    assert tab is not None
    assert tabstore.remove_vault_doc_tab(tmp_path, tab["id"]) is True
    assert tabstore.remove_vault_doc_tab(tmp_path, tab["id"]) is False
    # Core Editor is untouched.
    assert any(t.get("id") == "editor" for t in _tabs(tmp_path))


def test_refuse_non_vault_path(tmp_path: Path) -> None:
    assert tabstore.add_vault_doc_tab(tmp_path, "wiki/page.md") is None
    assert tabstore.add_vault_doc_tab(tmp_path, "vault/foo.pdf") is None
