"""Deck pages land in the graph cache without crashing the rebuild.

Run: make test
"""

from __future__ import annotations

from pathlib import Path

from switchbay import cebridge


def _page(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_inject_deck_nodes_promotes_kind_deck_and_ignores_notes(tmp_path: Path) -> None:
    _page(
        tmp_path / "wiki" / "analyses" / "deck-one.md",
        '---\nkind: "deck"\ntitle: Walkthrough\n---\n\nslides\n',
    )
    _page(
        tmp_path / "wiki" / "notes" / "plain.md",
        "---\nkind: note\ntitle: Plain\n---\n\nhi\n",
    )
    _page(tmp_path / "wiki" / "loose.md", "no frontmatter\n")
    data: dict = {"pages": {}, "nodes": []}
    added = cebridge.inject_deck_nodes(tmp_path, data)
    assert added == 2
    page = data["pages"]["analyses/deck-one"]
    assert page["type"] == "analysis"
    assert page["title"] == "[deck] Walkthrough"
    assert data["nodes"][0]["id"] == "analyses/deck-one"
    assert "notes/plain" not in data["pages"]
