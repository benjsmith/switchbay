"""Curation history timeline — replayable build sequence for the
opening graph animation.

The Sketch/Graph tabs need something to render while `/api/graph/data`
warms up on a cold workspace switch (one viewer.sh build can take a
few seconds on a large wiki). Instead of a static spinner we play
back the workspace's curation history: an empty canvas, then sources
pop in, then ontology docs are created and wired up, in roughly the
order they actually were.

Source of truth: the wiki/ git log. Walks `git log` in reverse
chronological order for files under wiki/, records when each .md
first appeared, then derives edges from the current wikilinks +
frontmatter `relates_to:`. An edge is only emitted once BOTH
endpoints have appeared, preserving the "ontology grows from
sources" feel.

Why git over `.curator/log.md`: the curator log is rich prose
(`hygiene-pass 2026-04-30T22:20Z` etc.) but parsing it for which
file appeared when is fragile. Git gives us a clean
`(commit_time, added_file)` stream with no string-fishing. We
compared the two on a real workspace (~150 commits vs ~3500 log
lines) and concluded the cost asymmetry isn't close — the log adds
narrative depth we don't need for an opening animation.

The resulting timeline is cached at
`<workspace>/.workbench/curation-history.json` and invalidated on
`files_changed` so a new wiki commit refreshes it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


CACHE_NAME = "curation-history.json"
# Bumped whenever the on-disk JSON shape changes. read_or_build
# treats a cache with a lower (or missing) `version` as stale and
# rebuilds — no manual cache-bust step required.
SCHEMA_VERSION = 4
DEFAULT_DURATION_S = 15.0
# Bigger cap so the picture reaches near-real-graph density before
# the tail-settle. With ~500 nodes + ~2000 edges typical for a
# curated workspace, we want most of the edge budget to come along
# for the ride. Browser handles a few thousand SVG ops fine.
MAX_EVENTS = 2500


def cache_path(workspace: Path) -> Path:
    # Derived/regenerable cache — lives in the machine-local state root,
    # never on a cloud-sync service (a cold rebuild here once blocked
    # the event loop ~10 s on an iCloud-evicted file). See statedir.py.
    from . import statedir

    return statedir.curation_cache(workspace, CACHE_NAME)


_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
_FRONTMATTER_RELATES_RE = re.compile(
    r"^relates_to:\s*(?:\[([^\]]*)\]|\n((?:\s*-\s+\S+\s*\n)+))",
    re.MULTILINE,
)


def _is_wiki_md(rel: str) -> bool:
    """Filter to the `.md` files we want to plot — wiki content only,
    excluding figure assets, helper files, and CE bookkeeping."""
    if not rel.endswith(".md"):
        return False
    if not rel.startswith("wiki/"):
        return False
    if "/figures/" in rel:
        return False
    if "/_assets/" in rel:
        return False
    # CE drops a handful of template hubs at wiki/ root that aren't
    # interesting to animate (notes.md, todos.md, etc.). Filter the
    # ones we know about; everything else under wiki/ is genuine
    # ontology content.
    stem = rel[len("wiki/") :]
    if stem in {
        "notes.md", "todos.md", "index.md", "for-attention.md",
    }:
        return False
    return True


def _wiki_dir(workspace: Path) -> Path:
    return workspace / "wiki"


async def _run_git(
    workspace: Path, *args: str, timeout_s: float = 10.0,
) -> tuple[int, str, str, str]:
    """Run a git command inside the wiki git repo. CE keeps the
    wiki as its own git repo (`<workspace>/wiki/.git`); falls back
    to the workspace root if the user has a single top-level repo.

    Returns (rc, stdout, stderr, prefix) where `prefix` is the
    string to prepend to repo-relative paths so they resolve to
    workspace-relative paths (`wiki/` when the repo is wiki/-local,
    empty when the repo is at workspace root).
    """
    wiki = _wiki_dir(workspace)
    if (wiki / ".git").exists():
        cwd = wiki
        prefix = "wiki/"
    elif (workspace / ".git").exists():
        cwd = workspace
        prefix = ""
    else:
        return 1, "", "no git repo", ""
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        proc.kill()
        return 1, "", "git timeout", prefix
    return (
        proc.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
        prefix,
    )


async def _first_seen_times(workspace: Path) -> dict[str, int]:
    """Walk the wiki git history and record the FIRST commit
    timestamp every wiki/*.md was seen at. Reverse-chronological
    walk so we naturally keep the earliest entry per file (later
    overwrites lose). Returns {rel_path: unix_ts}.

    Uses `--diff-filter=A` to consider only adds; renames don't
    count as "new node appeared" — the entity already existed under
    its old name. Falls back to file mtime if the wiki isn't a git
    repo.
    """
    rc, out, _err, prefix = await _run_git(
        workspace,
        "log",
        "--reverse",                     # oldest first
        "--name-status",
        "--format=%H%x09%ct",            # SHA \t commit_time
        "--diff-filter=AR",              # adds + renames (rename gets a new name)
    )
    if rc != 0:
        return _fallback_mtimes(workspace)
    seen: dict[str, int] = {}
    current_ts: int | None = None
    for line in out.splitlines():
        if not line.strip():
            # `git log --name-status` separates the commit header
            # from its file list with a blank line. Don't reset
            # current_ts here — the file lines below still belong
            # to this commit.
            continue
        # Header line is "<sha>\t<ts>" with no leading status letter.
        # Distinguish from a file-status line ("A\tpath") by looking
        # for a tab AND a leading hex sha (40-char hex).
        first = line.split("\t", 1)[0]
        if (
            len(first) >= 7
            and all(c in "0123456789abcdef" for c in first[:7])
        ):
            try:
                current_ts = int(line.split("\t", 1)[1])
            except (ValueError, IndexError):
                current_ts = None
            continue
        if current_ts is None:
            continue
        # File line: "A\tpath" or "R100\told\tnew"
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("A") and len(parts) >= 2:
            repo_path = parts[1]
        elif status.startswith("R") and len(parts) >= 3:
            repo_path = parts[2]
        else:
            continue
        path = prefix + repo_path  # wiki/-prefixed workspace-relative path
        if not _is_wiki_md(path):
            continue
        if path not in seen:
            seen[path] = current_ts
    return seen


def _fallback_mtimes(workspace: Path) -> dict[str, int]:
    """No git available — derive first-seen times from filesystem
    mtimes. Less faithful (mtimes get reset on edits) but keeps the
    animation working in non-git workspaces."""
    seen: dict[str, int] = {}
    wiki = _wiki_dir(workspace)
    if not wiki.is_dir():
        return seen
    for p in wiki.rglob("*.md"):
        rel = p.relative_to(workspace).as_posix()
        if not _is_wiki_md(rel):
            continue
        try:
            seen[rel] = int(p.stat().st_mtime)
        except OSError:
            continue
    return seen


def _read_frontmatter_and_body(path: Path) -> tuple[dict[str, Any], str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}, ""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    head = text[4:end]
    body = text[end + 5:]
    fm: dict[str, Any] = {}
    # Minimal YAML-ish parser — enough for CE's frontmatter shape.
    cur_key: str | None = None
    cur_list: list[str] | None = None
    for raw in head.splitlines():
        if raw.startswith("  - ") and cur_list is not None:
            cur_list.append(raw[4:].strip())
            continue
        if ":" in raw and not raw.startswith(" "):
            cur_key = raw.split(":", 1)[0].strip()
            val = raw.split(":", 1)[1].strip()
            if val.startswith("[") and val.endswith("]"):
                items = [x.strip().strip('"').strip("'") for x in val[1:-1].split(",")]
                fm[cur_key] = [i for i in items if i]
                cur_list = None
            elif val == "":
                cur_list = []
                fm[cur_key] = cur_list
            else:
                fm[cur_key] = val.strip('"').strip("'")
                cur_list = None
    return fm, body


def _doc_type(rel: str, fm: dict[str, Any]) -> str:
    """Map a wiki file to its CE type for the animation palette.
    Mirrors the type taxonomy the graph viewer uses."""
    explicit = str(fm.get("type") or "").strip().lower()
    if explicit:
        return explicit
    kind = str(fm.get("kind") or "").strip().lower()
    if kind == "deck":
        return "analysis"
    if kind in {"analysis", "project", "concept", "entity", "source", "note"}:
        return kind
    # Path-based fallback: wiki/<bucket>/foo.md → bucket-derived type.
    bucket_to_type = {
        "concepts": "concept",
        "entities": "entity",
        "evidence": "evidence",   # already singular
        "facts": "fact",
        "figures": "figure",
        "tables": "table",
        "sources": "source",
        "notes": "note",
        "projects": "project",
        "analyses": "analysis",
        "todos": "todo-list",
    }
    parts = rel.split("/")
    if len(parts) >= 3:
        return bucket_to_type.get(parts[1], "unclassified")
    return "unclassified"


def _doc_title(rel: str, fm: dict[str, Any]) -> str:
    t = str(fm.get("title") or "").strip()
    if t:
        return t
    return Path(rel).stem


def _doc_id(rel: str) -> str:
    """Canonical id matching CE's wiki_render: wiki-relative path
    without the .md extension."""
    stem = rel
    if stem.startswith("wiki/"):
        stem = stem[len("wiki/") :]
    if stem.endswith(".md"):
        stem = stem[: -3]
    return stem


def _resolve_wikilinks(body: str, all_ids: set[str], stem_to_id: dict[str, str]) -> list[str]:
    """Walk `[[link]]` references in `body` and resolve to canonical
    ids. Drops links that don't match any existing wiki file —
    matches CE's "resolved-only" edge model."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _WIKILINK_RE.finditer(body):
        target = m.group(1).strip()
        if not target:
            continue
        # Strip optional path/asset prefixes.
        if target.startswith("./"):
            target = target[2:]
        # Direct id match (full path)
        if target in all_ids:
            cand = target
        else:
            # Stem match — CE allows [[foo]] to resolve to
            # `<bucket>/foo.md` if there's a unique hit.
            cand = stem_to_id.get(target)
            if cand is None:
                continue
        if cand in seen:
            continue
        seen.add(cand)
        out.append(cand)
    return out


def _resolve_frontmatter_refs(
    fm: dict[str, Any],
    all_ids: set[str],
    stem_to_id: dict[str, str],
) -> list[str]:
    """CE links analyses to their sources (`sources: [...]`), figures
    to their entities/concepts (`relates_to: [...]`), evidence to its
    backing facts/sources, etc. via frontmatter lists. Without
    walking these, a source page that nobody body-cites stays a
    visual orphan even though it's clearly part of the graph. Walk
    the union of CE's known relation fields and resolve each to a
    canonical id."""
    out: list[str] = []
    seen: set[str] = set()
    fields = (
        "sources", "relates_to", "facts", "evidence",
        "figures", "tables", "concepts", "entities",
        "projects",
    )
    for key in fields:
        raw = fm.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            target = str(item or "").strip()
            if not target:
                continue
            # Strip leading wiki/, trailing .md so the lookup works
            # whether the value was a slug, a wiki-relative path, or
            # a workspace-relative path.
            stripped = target
            if stripped.startswith("wiki/"):
                stripped = stripped[len("wiki/"):]
            if stripped.endswith(".md"):
                stripped = stripped[:-3]
            # First try the full id form (e.g. `sources/foo`); then
            # try the bare stem.
            cand: str | None = None
            if stripped in all_ids:
                cand = stripped
            else:
                bare = stripped.rsplit("/", 1)[-1]
                cand = stem_to_id.get(bare)
            if cand is None or cand in seen:
                continue
            seen.add(cand)
            out.append(cand)
    return out


async def build_history(
    workspace: Path, *, duration_s: float = DEFAULT_DURATION_S,
) -> dict[str, Any]:
    """Produce the replayable event timeline. Returns
    `{duration, events: [{t, op, ...}, …]}` where `t` is the fraction
    of `duration_s` at which the event fires.

    Edge source of truth: CE's `data.json` (whatever the real graph
    viewer renders) loaded via cebridge.read_cached. That gives us
    authoritative, already-resolved edges including the ones that
    come from frontmatter relation fields, citations, and any other
    CE-specific harvesting. Re-resolving wikilinks here would always
    drift from CE because some sources have stale filename refs that
    CE's index matches fuzzily — the animation would show "orphan"
    sources that aren't orphans in the real graph.

    Node ordering still comes from git first-seen so the visual
    chronology reads as a real curation timeline.
    """
    first_seen = await _first_seen_times(workspace)
    if not first_seen:
        return {"duration": duration_s, "events": [], "source": "empty"}
    # Everything below is pure CPU + synchronous file I/O: it reads
    # data.json via read_cached (which itself rglob's the wiki) plus
    # every unmatched node's frontmatter. On a cold workspace that
    # blocks the event loop for seconds and wedges the WHOLE daemon —
    # the watchdog caught exactly this on curiosity-multidomain-test
    # (read_or_build -> build_history -> _read_frontmatter_and_body).
    # Run it off-thread so a cold curation-history build can't freeze
    # tab switches.
    return await asyncio.to_thread(
        _assemble_history, workspace, duration_s, first_seen,
    )


def _assemble_history(
    workspace: Path, duration_s: float, first_seen: dict[str, int],
) -> dict[str, Any]:
    # Pull node + edge truth from the cached data.json. If the
    # workspace hasn't been built yet, fall back to body-wikilink
    # resolution so we still produce *some* animation.
    from . import cebridge
    ce_data = cebridge.read_cached(workspace)

    nodes: dict[str, dict[str, Any]] = {}
    by_first_seen: list[tuple[int, str]] = []
    ce_node_ids: set[str] = set()
    ce_node_meta: dict[str, dict[str, Any]] = {}
    if ce_data is not None:
        for n in ce_data.get("nodes") or []:
            nid = str(n.get("id") or "")
            if not nid:
                continue
            ce_node_ids.add(nid)
            ce_node_meta[nid] = {
                "title": str(n.get("title") or nid),
                "type": str(n.get("type") or "unclassified"),
            }
    # Walk first_seen and keep only ids CE knows about — sketches,
    # plots, etc. live elsewhere and don't belong on the canvas.
    # Build the canonical id from the filesystem path; if CE has it
    # under that id, include it.
    for rel, ts in first_seen.items():
        node_id = _doc_id(rel)
        if ce_data is not None and node_id not in ce_node_ids:
            # Try a /-stripped alternative: CE sometimes drops the
            # bucket prefix on root-level pages.
            alt = node_id.rsplit("/", 1)[-1]
            if alt in ce_node_ids:
                node_id = alt
            else:
                continue
        # Title + type from CE if we have it, else fall back to a
        # filesystem parse.
        if node_id in ce_node_meta:
            meta = ce_node_meta[node_id]
            title = meta["title"]
            ntype = meta["type"]
        else:
            full = workspace / rel
            fm, _body = _read_frontmatter_and_body(full)
            title = _doc_title(rel, fm)
            ntype = _doc_type(rel, fm)
        nodes[node_id] = {
            "id": node_id, "title": title, "type": ntype, "ts": ts,
        }
        by_first_seen.append((ts, node_id))

    # For any CE node we couldn't match by path (the wiki repo
    # rewrites paths over time), append at the latest-known ts so
    # they still appear in the animation. This keeps the closing
    # frame node-set identical to the real graph.
    max_ts = max((ts for ts, _ in by_first_seen), default=int(time.time()))
    for nid in ce_node_ids - set(nodes.keys()):
        meta = ce_node_meta[nid]
        nodes[nid] = {
            "id": nid, "title": meta["title"], "type": meta["type"],
            "ts": max_ts,
        }
        by_first_seen.append((max_ts, nid))

    by_first_seen.sort()

    ts_min = by_first_seen[0][0]
    ts_max = by_first_seen[-1][0]
    span = max(1, ts_max - ts_min)

    def t_of(ts: int) -> float:
        return (ts - ts_min) / span * duration_s

    # Edge table from CE (authoritative) if available, else body
    # wikilinks as a fallback. Normalise to `{source: id, target: id}`.
    edges_raw: list[tuple[str, str]] = []
    if ce_data is not None:
        for e in ce_data.get("edges") or []:
            s_raw = e.get("source")
            t_raw = e.get("target")
            s = s_raw.get("id") if isinstance(s_raw, dict) else s_raw
            t = t_raw.get("id") if isinstance(t_raw, dict) else t_raw
            if isinstance(s, str) and isinstance(t, str) and s in nodes and t in nodes and s != t:
                edges_raw.append((s, t))
    # Index edges by the LATER endpoint's appearance time so an
    # edge fires the moment both endpoints exist. This naturally
    # weaves edges into the animation as the second node appears.
    ts_by_id = {nid: ts for ts, nid in by_first_seen}
    events: list[dict[str, Any]] = []
    for ts, node_id in by_first_seen:
        events.append({
            "t": round(t_of(ts), 3),
            "op": "node",
            "id": node_id,
            "type": nodes[node_id]["type"],
            "title": nodes[node_id]["title"],
        })
    # Dedup edges (a→b and b→a count once for animation purposes).
    seen_pairs: set[tuple[str, str]] = set()
    for s, t in edges_raw:
        pair = (s, t) if s < t else (t, s)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        later_ts = max(ts_by_id[s], ts_by_id[t])
        events.append({
            "t": round(t_of(later_ts), 3),
            "op": "edge",
            "source": s,
            "target": t,
        })

    # Stable sort by t so the player can stream in order.
    events.sort(key=lambda e: (e["t"], 0 if e["op"] == "node" else 1))
    if len(events) > MAX_EVENTS:
        # Down-sample by dropping interior edges; keep all nodes so
        # the structure is intact, then sprinkle edges from the
        # remainder evenly.
        node_events = [e for e in events if e["op"] == "node"]
        edge_events = [e for e in events if e["op"] == "edge"]
        keep_n = max(0, MAX_EVENTS - len(node_events))
        if keep_n < len(edge_events):
            step = len(edge_events) / max(1, keep_n)
            edge_events = [
                edge_events[int(i * step)] for i in range(keep_n)
            ]
        events = sorted(
            node_events + edge_events,
            key=lambda e: (e["t"], 0 if e["op"] == "node" else 1),
        )

    # Final degree per node, computed from the EMITTED edges (not
    # the resolved wikilinks pre-down-sample) so the frontend can
    # size each circle exactly like the real graph viewer does
    # without re-counting. Both endpoints get a tick per edge.
    degree: dict[str, int] = {}
    for ev in events:
        if ev["op"] == "edge":
            degree[ev["source"]] = degree.get(ev["source"], 0) + 1
            degree[ev["target"]] = degree.get(ev["target"], 0) + 1

    return {
        "version": SCHEMA_VERSION,
        "duration": duration_s,
        "events": events,
        "source": "git+ce" if ce_data is not None else "git",
        "generated_at": int(time.time()),
        "node_count": len(nodes),
        "degree": degree,
    }


def _wiki_newest_mtime(workspace: Path) -> float:
    """Highest mtime of any wiki/*.md file. Used as a staleness
    signal — if the cache predates this, rebuild. Cheap (one
    rglob, no contents read)."""
    wiki = _wiki_dir(workspace)
    if not wiki.is_dir():
        return 0.0
    newest = 0.0
    for p in wiki.rglob("*.md"):
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        if m > newest:
            newest = m
    return newest


# In-flight background rebuilds, keyed by workspace path. Prevents
# stacking N concurrent `git log` walks when the frontend polls
# /api/curation/history while a rebuild is already running.
_REBUILDS: dict[str, asyncio.Task] = {}


async def read_or_build(
    workspace: Path, *, duration_s: float = DEFAULT_DURATION_S,
) -> dict[str, Any] | None:
    """Stale-while-revalidate: return the cached history immediately
    when one exists, kick off a fresh rebuild in the background if
    it's stale. The rebuild's heavy git walk has been known to peg
    the event loop for ~10s on big repos — blocking it inside the
    request handler made every other endpoint time out. Better to
    serve a slightly old animation now and refresh in the
    background.

    Only block on `build_history` when there's no cache at all
    (first run after a workspace add, or after explicit invalidate).
    Single-flight: only one background rebuild per workspace at a
    time; duplicate calls reuse the in-flight task.
    """
    if not workspace.is_dir():
        return None
    cp = cache_path(workspace)

    def _load() -> tuple[dict[str, Any] | None, bool]:
        # Reads the cache JSON and rglob-walks the wiki for the newest
        # mtime. Both are blocking FS work, so this runs off-thread —
        # the cache-hit path is on the Graph tab's animation surface.
        c: dict[str, Any] | None = None
        fresh = True
        if cp.is_file():
            try:
                obj = json.loads(cp.read_text(encoding="utf-8"))
                if (
                    isinstance(obj, dict)
                    and "events" in obj
                    and int(obj.get("version") or 0) >= SCHEMA_VERSION
                ):
                    c = obj
                    gen_at = float(obj.get("generated_at") or 0)
                    fresh = gen_at >= _wiki_newest_mtime(workspace)
            except (OSError, json.JSONDecodeError):
                pass
        return c, fresh

    cached, cached_fresh = await asyncio.to_thread(_load)
    if cached is not None:
        if not cached_fresh:
            # Background refresh; don't block the response on it.
            # Single-flight via _REBUILDS so a polling client can't
            # spawn N parallel `git log` walks (each takes seconds
            # and they all compete on the same event loop).
            key = str(workspace.resolve())
            existing = _REBUILDS.get(key)
            if existing is None or existing.done():
                _REBUILDS[key] = asyncio.create_task(
                    _rebuild_in_background(workspace, duration_s, key)
                )
        return cached
    # No cache at all — block on build so the first replay isn't empty.
    fresh = await build_history(workspace, duration_s=duration_s)
    try:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(fresh), encoding="utf-8")
    except OSError as e:
        log.warning("curation-history cache write failed: %s", e)
    return fresh


async def _rebuild_in_background(
    workspace: Path, duration_s: float, key: str,
) -> None:
    """Background companion to read_or_build's stale-while-revalidate
    path. Builds and writes the cache; swallows errors since this is
    a refresh, not a user-visible request. Clears the single-flight
    entry on completion (success or failure) so subsequent stale
    reads can schedule a new rebuild."""
    try:
        fresh = await build_history(workspace, duration_s=duration_s)
        cp = cache_path(workspace)
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(fresh), encoding="utf-8")
        log.info("curation-history refreshed in background for %s", workspace)
    except Exception as e:  # noqa: BLE001
        log.warning("curation-history background rebuild failed: %s", e)
    finally:
        _REBUILDS.pop(key, None)


def invalidate(workspace: Path) -> None:
    """Drop the cache so the next read rebuilds. Cheap — just an
    unlink. Wired into `files_changed` so a new commit / file write
    refreshes the animation without a daemon restart."""
    cp = cache_path(workspace)
    try:
        cp.unlink(missing_ok=True)
    except OSError:
        pass
