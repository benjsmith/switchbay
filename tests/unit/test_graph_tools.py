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
