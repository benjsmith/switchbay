"""Fast /api/graph/data path: serve data.json without FS enrich."""

from __future__ import annotations

import json
from pathlib import Path

from switchbay import cebridge, protocol


def test_read_cached_default_skips_enrich(tmp_path: Path, monkeypatch) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "a.md").write_text("---\ntitle: A\ntype: note\n---\n\nHi.\n", encoding="utf-8")
    out = tmp_path / "cache-out"
    out.mkdir()
    (out / "data.json").write_text(
        json.dumps({
            "nodes": [{"id": "a", "type": "unclassified", "title": "A", "path": "a.md"}],
            "edges": [],
            "pages": {"a": {"id": "a", "type": "unclassified", "title": "A", "path": "a.md"}},
            "palette": {"note": "#000"},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(cebridge, "has_wiki", lambda _ws: True)
    monkeypatch.setattr(cebridge, "output_dir", lambda _ws: out)

    called: list[str] = []
    monkeypatch.setattr(
        cebridge, "resync_types_from_disk",
        lambda *_a, **_k: called.append("types") or 0,
    )
    monkeypatch.setattr(
        cebridge, "inject_deck_nodes",
        lambda *_a, **_k: called.append("decks") or 0,
    )
    monkeypatch.setattr(
        "switchbay.wiki_sync.inject_on_disk_pages",
        lambda *_a, **_k: called.append("pages") or 0,
    )

    data = cebridge.read_cached(tmp_path)  # enrich=False default
    assert data is not None
    assert called == []
    assert "a" in data["pages"]

    data2 = cebridge.read_cached(tmp_path, enrich=True)
    assert data2 is not None
    assert called == ["types", "decks", "pages"]


def test_enrich_from_disk_returns_counts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cebridge, "resync_types_from_disk", lambda *_a, **_k: 3)
    monkeypatch.setattr(cebridge, "inject_deck_nodes", lambda *_a, **_k: 1)
    monkeypatch.setattr(
        "switchbay.wiki_sync.inject_on_disk_pages", lambda *_a, **_k: 5,
    )
    monkeypatch.setattr(cebridge, "_override_palette", lambda *_a, **_k: None)
    counts = cebridge.enrich_from_disk(tmp_path, {"pages": {}, "nodes": [], "edges": []})
    assert counts == {"types": 3, "decks": 1, "pages": 5}


def test_graph_progress_payload_shape() -> None:
    msg = protocol.graph_progress(
        "types", "Syncing page types…",
        workspace="/tmp/ws", current=2, total=10, done=False,
    )
    assert msg["type"] == "CUSTOM"
    assert msg["name"] == "graph_progress"
    val = msg["value"]
    assert val["type"] == "graph_progress"
    assert val["stage"] == "types"
    assert val["message"] == "Syncing page types…"
    assert val["workspace"] == "/tmp/ws"
    assert val["current"] == 2
    assert val["total"] == 10
    assert val["done"] is False

    done = protocol.graph_progress("ready", "Graph ready", done=True)
    assert done["value"]["done"] is True
