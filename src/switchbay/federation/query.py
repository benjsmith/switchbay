"""Fan a read out to the selected mounts and merge the lists.

Scores from different graphs are not compared directly. Lists are
merged with reciprocal rank fusion, weighted by trust. A walk stays
inside one graph.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pathlib import Path

from . import live, snapshot
from .live import GraphError
from .mounts import Mount, load, selected_ids, split_ref

_TRUST = {"own": 1.0, "org": 0.8, "external": 0.5}
_RRF_K = 60


def frame(body: str, mount: Mount, rev: str) -> str:
    if mount.trust == "own":
        return body
    return (
        f"UNTRUSTED REMOTE CONTENT — graph:{mount.graph_id}@{rev}\n"
        f"{body.rstrip()}\n"
        "END UNTRUSTED REMOTE CONTENT\n"
    )


def _weight(mount: Mount) -> float:
    return _TRUST.get(mount.trust, 0.5)


def _fuse(groups: list[tuple[Mount, list[dict]]]) -> list[dict]:
    scores: dict[tuple, float] = {}
    best: dict[tuple, dict] = {}
    for mount, rows in groups:
        weight = _weight(mount)
        for rank, row in enumerate(rows, start=1):
            iri = str(row.get("iri") or "")
            key = (iri, "") if iri else (mount.id, str(row.get("path") or row.get("page") or ""))
            scores[key] = scores.get(key, 0.0) + weight / (_RRF_K + rank)
            page = str(row.get("path") or row.get("page") or "")
            ref = page if mount.id == "local" else f"{mount.id}:{page}"
            item = {
                "page": ref,
                "title": row.get("title") or "",
                "type": row.get("type") or "",
                "snippet": row.get("snippet") or "",
                "score": round(scores[key], 6),
                "graph": mount.id,
                "trust": mount.trust,
                "rev": row.get("rev") or "",
                "classification": row.get("classification") or ("public" if mount.trust != "own" else ""),
                "untrusted": mount.trust != "own",
                "graph_id": mount.graph_id,
                "wikilink": f"[[{ref}]]",
            }
            if key not in best or scores[key] >= best[key]["score"]:
                if key in best and best[key]["graph"] != mount.id:
                    cites = list(best[key].get("also") or [])
                    cites.append({"graph": best[key]["graph"], "page": best[key]["page"], "rev": best[key]["rev"]})
                    item["also"] = cites
                best[key] = item
            else:
                best[key].setdefault("also", []).append(
                    {"graph": mount.id, "page": ref, "rev": row.get("rev") or ""}
                )
                best[key]["score"] = round(scores[key], 6)
    return sorted(best.values(), key=lambda row: (-row["score"], row["page"]))


def _local_rows(workspace: Path, payload: dict) -> list[dict]:
    from ..tools import _search_wiki
    result = _search_wiki(workspace, {**payload, "_local_only": True})
    rows = []
    for row in result.get("results") or []:
        rows.append({
            "path": row.get("page"),
            "title": row.get("title"),
            "type": row.get("type"),
            "snippet": row.get("snippet"),
            "score": row.get("score"),
            "rev": "",
            "classification": "",
        })
    return rows


def _remote_search(workspace: Path, mount: Mount, query: str, limit: int) -> list[dict]:
    if mount.kind == "snapshot":
        snap = snapshot.ensure(workspace, mount)
        return snapshot.search(snap, query, limit)
    if mount.kind == "live":
        return live.search(workspace, mount, query, limit)
    return []


def federated_search(workspace: Path, payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("_local_only"):
        return None
    ids = selected_ids(workspace, payload)
    if ids is None:
        return None
    cfg = load(workspace)
    query = str(payload.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    limit = max(1, min(int(payload.get("limit") or 8), 25))
    mounts = [cfg.get(mid) for mid in ids]
    mounts = [m for m in mounts if m is not None]
    groups: list[tuple[Mount, list[dict]]] = []
    unavailable: list[dict[str, str]] = []

    def one(mount: Mount) -> tuple[Mount, list[dict] | str]:
        try:
            if mount.kind == "local":
                return mount, _local_rows(workspace, payload)
            return mount, _remote_search(workspace, mount, query, limit)
        except (GraphError, ValueError, OSError) as exc:
            return mount, str(exc)

    with ThreadPoolExecutor(max_workers=max(1, len(mounts))) as pool:
        for mount, result in pool.map(one, mounts):
            if isinstance(result, str):
                unavailable.append({"graph": mount.id, "error": result})
            else:
                groups.append((mount, result))
    results = _fuse(groups)[:limit]
    out: dict[str, Any] = {
        "results": results,
        "total_matches": len(results),
        "graphs": [mount.id for mount, _ in groups],
    }
    if unavailable:
        names = ", ".join(item["graph"] for item in unavailable)
        answered = ", ".join(out["graphs"]) or "nowhere"
        out["unavailable"] = unavailable
        out["note"] = f"{names} unreachable, answered from {answered}"
    return out


def federated_read(workspace: Path, payload: dict[str, Any]) -> dict[str, Any] | None:
    cfg = load(workspace)
    mount_id, path = split_ref(str(payload.get("page") or ""), cfg)
    if mount_id == "local":
        return None
    mount = cfg.get(mount_id)
    if mount is None:
        return {"error": f"unknown mount {mount_id}"}
    try:
        if mount.kind == "snapshot":
            snap = snapshot.ensure(workspace, mount)
            page = snapshot.read_page(snap, path)
            if page is None:
                return {"error": f"no page {path} on {mount_id}"}
        elif mount.kind == "live":
            fetched = live.read_page(workspace, mount, path, str(payload.get("rev") or ""))
            page = {
                "path": fetched.get("path"),
                "title": fetched.get("title"),
                "type": fetched.get("type"),
                "content": _render(fetched),
                "classification": fetched.get("classification") or "",
                "rev": fetched.get("rev") or "",
                "graph_id": fetched.get("graph_id") or mount.graph_id,
            }
        else:
            return None
    except (GraphError, ValueError, OSError) as exc:
        return {"error": f"{mount_id} unreachable: {exc}", "unavailable": True}
    rev = str(page.get("rev") or "")
    content = frame(str(page.get("content") or ""), mount, rev)
    return {
        "page": f"{mount.id}:{page.get('path')}",
        "title": page.get("title") or "",
        "type": page.get("type") or "",
        "content": content[:12000],
        "truncated": len(content) > 12000,
        "graph": mount.id,
        "trust": mount.trust,
        "rev": rev,
        "classification": page.get("classification") or "",
        "untrusted": mount.trust != "own",
        "graph_id": mount.graph_id,
        "wikilink": f"[[{mount.id}:{page.get('path')}]]",
        "citation": f"(graph:{mount.id}/{page.get('path')}@{rev})",
    }


def _render(page: dict) -> str:
    fm = page.get("frontmatter") or {}
    lines = ["---"]
    if isinstance(fm, dict):
        for key, value in fm.items():
            lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    lines.append(str(page.get("body") or ""))
    return "\n".join(lines)


def federated_neighbors(workspace: Path, payload: dict[str, Any]) -> dict[str, Any] | None:
    cfg = load(workspace)
    mount_id, path = split_ref(str(payload.get("page") or ""), cfg)
    if mount_id == "local":
        return None
    mount = cfg.get(mount_id)
    if mount is None or mount.kind not in ("snapshot", "live"):
        return {"error": f"unknown mount {mount_id}"}
    hops = max(1, min(int(payload.get("hops") or 2), 4))
    try:
        if mount.kind == "live":
            block = live.neighbors(workspace, mount, path, hops)
            neighbors = [
                {"page": f"{mount.id}:{item.get('path')}", "title": item.get("title") or "",
                 "distance": item.get("distance"), "rev": item.get("rev") or block.get("rev")}
                for item in block.get("neighbors") or []
            ]
            rev = str(block.get("rev") or "")
        else:
            snap = snapshot.ensure(workspace, mount)
            neighbors = _snapshot_neighbors(snap, mount.id, path, hops)
            rev = snap.rev
    except (GraphError, ValueError, OSError) as exc:
        return {"error": f"{mount_id} unreachable: {exc}", "unavailable": True}
    return {
        "page": f"{mount.id}:{path}", "hops": hops, "count": len(neighbors),
        "neighbors": neighbors[:120], "graph": mount.id, "rev": rev,
        "trust": mount.trust, "untrusted": mount.trust != "own",
    }


def _snapshot_neighbors(snap, mount_id: str, path: str, hops: int) -> list[dict]:
    import re
    from collections import deque
    link = re.compile(r"\[\[([^\]\n]+)\]\]")
    files = {}
    for file in snap.wiki.rglob("*.md"):
        rel = file.relative_to(snap.wiki).as_posix()[:-3]
        files[rel] = file.read_text(encoding="utf-8", errors="replace")
    by_stem = {Path(rel).stem.casefold(): rel for rel in files}
    out: dict[str, set[str]] = {rel: set() for rel in files}
    inc: dict[str, set[str]] = {rel: set() for rel in files}
    for rel, text in files.items():
        for match in link.findall(text):
            dest = by_stem.get(Path(match.split("|", 1)[0].strip()).name.casefold())
            if dest and dest != rel:
                out[rel].add(dest)
                inc[dest].add(rel)
    if path not in files:
        stem = Path(path).name.casefold()
        path = by_stem.get(stem, path)
    dist = {path: 0}
    queue: deque[str] = deque([path])
    while queue:
        cur = queue.popleft()
        if dist[cur] >= hops:
            continue
        for nb in out.get(cur, set()) | inc.get(cur, set()):
            if nb not in dist:
                dist[nb] = dist[cur] + 1
                queue.append(nb)
    return [
        {"page": f"{mount_id}:{rel}", "distance": d, "rev": snap.rev}
        for rel, d in sorted(dist.items()) if rel != path
    ]


def federated_path(workspace: Path, payload: dict[str, Any]) -> dict[str, Any] | None:
    cfg = load(workspace)
    a_mount, a_path = split_ref(str(payload.get("from") or ""), cfg)
    b_mount, b_path = split_ref(str(payload.get("to") or ""), cfg)
    if a_mount == "local" and b_mount == "local":
        return None
    if a_mount != b_mount:
        return {"error": "a path stays inside one graph; these pages are on different mounts"}
    mount = cfg.get(a_mount)
    if mount is None or mount.kind != "live":
        return {"error": "path across a snapshot is not wired; read the pages"}
    try:
        block = live.path_between(workspace, mount, a_path, b_path)
    except (GraphError, ValueError, OSError) as exc:
        return {"error": f"{mount.id} unreachable: {exc}", "unavailable": True}
    if "path" in block:
        block["path"] = [f"{mount.id}:{p}" for p in block["path"]]
    block["graph"] = mount.id
    block["trust"] = mount.trust
    return block
