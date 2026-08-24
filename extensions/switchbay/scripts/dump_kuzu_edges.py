#!/usr/bin/env python3
"""Dump WikiPage→WikiPage edges from CE's ``.curator/graph.kuzu``.

Mirrors curiosity-engine ``wiki_render._build_graph``: WikiLink + Depicts
only. Cites (page→vault) and ProvisionalLink stay out of the classic
force graph. Prints a JSON array of ``{source, target, type}``.
"""
from __future__ import annotations

import json
import sys


def nid(path: str) -> str:
    return path[:-3] if path.endswith(".md") else path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: dump_kuzu_edges.py <graph.kuzu>", file=sys.stderr)
        return 2
    try:
        import kuzu  # type: ignore
    except ImportError as e:
        print(f"kuzu import failed: {e}", file=sys.stderr)
        return 1
    db = kuzu.Database(sys.argv[1], read_only=True)
    conn = kuzu.Connection(db)
    edges: list[dict[str, str]] = []
    for rel, kind in (("WikiLink", "wikilink"), ("Depicts", "depicts")):
        rs = conn.execute(
            f"MATCH (a:WikiPage)-[:{rel}]->(b:WikiPage) RETURN a.path, b.path"
        )
        while rs.has_next():
            src, dst = rs.get_next()
            if not src or not dst:
                continue
            edges.append({"source": nid(str(src)), "target": nid(str(dst)), "type": kind})
    json.dump(edges, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
