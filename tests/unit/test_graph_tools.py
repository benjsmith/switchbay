"""In-process multi-hop graph tools over the wiki (the fix that gives the
agent real graph retrieval instead of degenerate 1-hop lookup)."""

from __future__ import annotations

from switchbay import tools


def _wiki(tmp_path, pages: dict[str, str]):
    root = tmp_path / "wiki"
    for rel, body in pages.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp_path


def _page(title, typ, body):
    return f"---\ntitle: {title}\ntype: {typ}\n---\n\n{body}\n"


def test_multi_hop_neighbors(tmp_path):
    # a -> b -> c ; a -> d
    ws = _wiki(tmp_path, {
        "concepts/a.md": _page("A", "concept", "links [[b]] and [[d]]"),
        "concepts/b.md": _page("B", "concept", "links [[c]]"),
        "concepts/c.md": _page("C", "concept", "leaf"),
        "concepts/d.md": _page("D", "concept", "leaf"),
    })
    one = tools._wiki_neighbors(ws, {"page": "a", "hops": 1})
    assert {n["page"] for n in one["neighbors"]} == {"wiki/concepts/b.md", "wiki/concepts/d.md"}
    two = tools._wiki_neighbors(ws, {"page": "a", "hops": 2})
    names = {n["page"]: n["distance"] for n in two["neighbors"]}
    assert names["wiki/concepts/c.md"] == 2  # reached only at hop 2
    assert names["wiki/concepts/b.md"] == 1


def test_shortest_path(tmp_path):
    ws = _wiki(tmp_path, {
        "concepts/a.md": _page("A", "concept", "[[b]]"),
        "concepts/b.md": _page("B", "concept", "[[c]]"),
        "concepts/c.md": _page("C", "concept", "leaf"),
    })
    r = tools._wiki_path(ws, {"from": "a", "to": "c"})
    assert r["hops"] == 2
    assert r["path"] == ["wiki/concepts/a.md", "wiki/concepts/b.md", "wiki/concepts/c.md"]


def test_shared_sources_and_bridges(tmp_path):
    # x and y both cite src1 but don't link each other → a bridge.
    ws = _wiki(tmp_path, {
        "concepts/x.md": _page("X", "concept", "cites (vault:src1.md) and (vault:src2.md)"),
        "concepts/y.md": _page("Y", "concept", "cites (vault:src1.md)"),
        "concepts/z.md": _page("Z", "concept", "unrelated"),
    })
    shared = tools._wiki_shared_sources(ws, {"page_a": "x", "page_b": "y"})
    assert shared["shared_sources"] == ["src1.md"]

    bridges = tools._wiki_related_by_sources(ws, {"page": "x"})
    rel = {b["page"]: b["shared_sources"] for b in bridges["related"]}
    assert rel.get("wiki/concepts/y.md") == 1   # co-cites src1, not linked
    assert "wiki/concepts/z.md" not in rel       # no shared source


def test_index_is_cached_until_pages_change(tmp_path):
    ws = _wiki(tmp_path, {"concepts/a.md": _page("A", "concept", "[[b]]"),
                          "concepts/b.md": _page("B", "concept", "x")})
    i1 = tools._graph_index(ws)
    i2 = tools._graph_index(ws)
    assert i1 is i2  # same object → cache hit


def test_neighbors_follow_typed_edges(tmp_path):
    ws = _wiki(tmp_path, {
        "evidence/cpu.md": (
            "---\ntitle: CPU\ntype: evidence\nsupports:\n  - hypotheses/queue\n---\n\nThe series moved.\n"
        ),
        "hypotheses/queue.md": (
            "---\ntitle: Queue\ntype: hypothesis\n---\n\nThe queue grows.\n"
        ),
    })
    (ws / ".curator").mkdir()
    (ws / ".curator" / "meta-ontology.yaml").write_text(
        """
version: 1
nodes:
  - type: evidence
    label: Evidence
    description: An observation.
  - type: hypothesis
    label: Hypothesis
    description: A claim.
edges:
  - type: supports
    label: supports
    source: [evidence]
    target: [hypothesis]
    description: When the result matches a prediction.
""",
        encoding="utf-8",
    )
    one = tools._wiki_neighbors(ws, {"page": "cpu", "hops": 1, "direction": "out"})
    pages = {n["page"] for n in one["neighbors"]}
    assert "wiki/hypotheses/queue.md" in pages


def test_ce_graph_neighbors_passes_edge_filter(tmp_path, monkeypatch):
    (tmp_path / "wiki" / "hypotheses").mkdir(parents=True)
    (tmp_path / "wiki" / "hypotheses" / "queue.md").write_text(
        "---\ntitle: Queue\ntype: hypothesis\n---\n\nThe queue grows.\n",
        encoding="utf-8",
    )
    seen: list[list[str]] = []

    def fake_run(script, args, **kwargs):
        seen.append([script, *args])
        return {"ok": True}

    monkeypatch.setattr("switchbay.cebridge.run_script", fake_run)
    tools._ce_graph_neighbors(
        tmp_path, {"page": "queue", "hops": 2, "direction": "in", "edge": "supports"},
    )
    assert seen, "graph.py was not called"
    assert seen[0][0] == "graph.py"
    assert "--edge" in seen[0]
    assert seen[0][seen[0].index("--edge") + 1] == "supports"
