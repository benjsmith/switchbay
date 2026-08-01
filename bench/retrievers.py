"""Retrieval arms for CE-vs-RAG measurement. Each returns
(context_text, source_ids). Shared char budget keeps arms comparable.

  A0  keyword wiki search
  A1  vector seed + multi-hop graph expand
  B   vault hybrid (raw sources)
  B'  wiki vector (curated pages)
  H / HA / R  hybrids and routed variants
  T2  two-stage study-sim (v0.9.2 track): needle → vault/sources/facts
      first; synthesis → wiki with analyses demoted so they cannot crowd
      out primary evidence

Note (charter Session 35): production knowledge retrieval belongs to CE.
These arms are a measurement scaffold; two-stage demotion is the prototype
routing policy to promote into CE's query path once validated.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from switchbay import tools

CTX_BUDGET = 6000          # chars of context per arm (comparable)
PER_PAGE_CAP = 1800        # chars read per page/source

# Wiki path prefixes → priority for study-sim assembly (lower = preferred).
# Analyses are last so long synthesis pages do not monopolise the budget
# on quote/caption/factoid queries.
_TYPE_PRIORITY = {
    "sources": 0,
    "facts": 1,
    "figures": 1,
    "tables": 1,
    "evidence": 2,
    "entities": 3,
    "concepts": 4,
    "notes": 5,
    "analyses": 9,
    "todos": 8,
}

_QUOTEISH = re.compile(
    r"""(?ix)
    (?:passage|caption|figure\s*\d|fig\.?\s*\d|table\s*\d|
       \"[^\"]{12,}\"|“[^”]{12,}”|
       head-section|middle-section|verbatim|exact\s+text|
       what\s+key\s+claim|the\s+following\s+passage)
    """
)


def _page_type(page: str) -> str:
    p = page.replace("\\", "/").lstrip("./")
    if p.startswith("wiki/"):
        p = p[5:]
    top = p.split("/", 1)[0] if "/" in p else p
    if top.endswith(".md"):
        top = "(root)"
    return top


def _type_rank(page: str) -> int:
    return _TYPE_PRIORITY.get(_page_type(page), 5)


def query_is_needle(query: str) -> bool:
    """Heuristic: quote / caption / extractive factoid (not free synthesis)."""
    q = (query or "").strip()
    if not q:
        return False
    if _QUOTEISH.search(q):
        return True
    # Long quoted fragment often pasted from a lecture.
    if q.count('"') >= 2 or q.count("“") >= 1:
        return True
    return False


def demote_analyses(pages: list[str], *, needle: bool = True) -> list[str]:
    """Stable reorder: prefer sources/facts/figures over analyses.

    When ``needle`` is True, analyses sort last. When False (synthesis
    queries), analyses stay mid-pack so multi-lecture themes can surface
    after entities/concepts.
    """
    if not pages:
        return []
    if needle:
        return sorted(pages, key=lambda p: (_type_rank(p), pages.index(p)))
    # Synthesis: slightly prefer analyses over pure notes/todos, but still
    # after sources/facts/entities/concepts.
    synth_rank = dict(_TYPE_PRIORITY)
    synth_rank["analyses"] = 4
    synth_rank["concepts"] = 3
    return sorted(pages, key=lambda p: (synth_rank.get(_page_type(p), 5), pages.index(p)))


def _read_page_text(workspace: Path, page: str) -> tuple[str, str]:
    r = tools._read_wiki_page(workspace, {"page": page})
    if "error" in r:
        return page, ""
    return r.get("page", page), (r.get("content") or "")[:PER_PAGE_CAP]


def _assemble(workspace: Path, pages: list[str], budget: int = CTX_BUDGET) -> tuple[str, list[str]]:
    out, used, total = [], [], 0
    for pg in pages:
        rel, txt = _read_page_text(workspace, pg)
        if not txt or rel in used:
            continue
        if total + len(txt) > budget:
            txt = txt[: max(0, budget - total)]
        out.append(f"### {rel}\n{txt}")
        used.append(rel)
        total += len(txt)
        if total >= budget:
            break
    return "\n\n".join(out), used


# ── A0: switchbay as shipped (keyword only) ─────────────────────────
def retrieve_a0(workspace: Path, query: str, k: int = 5, **_) -> tuple[str, list[str]]:
    res = tools._search_wiki(workspace, {"query": query, "limit": k})
    pages = [r["page"] for r in res.get("results", [])[:k]]
    return _assemble(workspace, pages)


# ── A1: CE full graph (multi-hop expansion) ──────────────────────────
_WORD = re.compile(r"\w{3,}")


def _semantic_seed_pages(workspace: Path, query: str, n: int) -> list[str]:
    """Top-n wiki pages by embedding similarity (same encoder as B'), so
    the graph arm starts from a GOOD entry point — CE's QUERY workflow
    likewise enters semantically/lexically, then traverses. Falls back to
    keyword search if no embedder."""
    index = _wiki_vector_index(workspace)
    if not index:
        res = tools._search_wiki(workspace, {"query": query, "limit": n})
        return [r["page"] for r in res.get("results", [])[:n]]
    from switchbay import conversations
    q = conversations._load_embedder().embed_query(query)
    scored = sorted(index, key=lambda row: -sum(a * b for a, b in zip(q, row[2])))
    seeds: list[str] = []
    for page, _c, _v in scored:
        if page not in seeds:
            seeds.append(page)
        if len(seeds) >= n:
            break
    return seeds


def retrieve_a1(workspace: Path, query: str, seeds: int = 2, k: int = 6, **_) -> tuple[str, list[str]]:
    # Vector-seeded graph traversal (GraphRAG): a semantic seed, then
    # expand over the knowledge graph. Isolates the graph's *contribution*
    # on top of the same retrieval B' uses.
    seed_pages = _semantic_seed_pages(workspace, query, seeds)
    if not seed_pages:
        return "", []
    idx = tools._graph_index(workspace)
    qterms = {t.casefold() for t in _WORD.findall(query)}
    # Candidates = seeds + their multi-hop neighbours, ranked by
    # (graph distance asc, then query-term overlap desc) so the graph
    # pulls in linked pages that keyword search alone would miss.
    cand: dict[str, tuple[int, int]] = {}
    for s in seed_pages:
        nb = tools._wiki_neighbors(workspace, {"page": s, "hops": 2})
        for n in nb.get("neighbors", []):
            pg = n["page"]
            overlap = sum(1 for t in qterms if t in (n.get("title", "") + " " + pg).casefold())
            d = n.get("distance", 3)
            if pg not in cand or (d, -overlap) < cand[pg]:
                cand[pg] = (d, -overlap)
    ranked = sorted(cand, key=lambda p: cand[p])
    pages = seed_pages + [p for p in ranked if p not in seed_pages]
    return _assemble(workspace, pages[:k])


# ── B: vector RAG over the vault raw sources (CE vault_search) ────────
_VS = Path.home() / ".claude" / "skills" / "curiosity-engine" / "scripts" / "vault_search.py"


def retrieve_b(workspace: Path, query: str, k: int = 5, budget: int = CTX_BUDGET, **_) -> tuple[str, list[str]]:
    if not _VS.is_file():
        return "", []
    # Sanitize: FTS5 MATCH treats ? " * : etc. as operators and errors on
    # a raw natural-language question, which would zero out the hybrid
    # result. Strip punctuation to bare terms (semantic still embeds the
    # words) — standard RAG query preprocessing, not a handicap.
    clean = re.sub(r"[^\w\s]", " ", query).strip() or query
    env = {k2: v for k2, v in os.environ.items()
           if k2 not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH")}
    try:
        p = subprocess.run(
            ["uv", "run", "--no-project", "python3", str(_VS), clean,
             "--mode", "hybrid", "--limit", str(k)],
            cwd=str(workspace), env=env, capture_output=True, text=True, timeout=120,
        )
        data = json.loads(p.stdout or "[]")
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return "", []
    out, used, total = [], [], 0
    vault = workspace / "vault"
    for hit in data:
        rel = hit.get("path", "")
        # Read the extracted source (the RAG "chunk"); fall back to snippet.
        txt = ""
        fp = vault / rel
        if fp.is_file():
            try:
                txt = fp.read_text(encoding="utf-8", errors="replace")[:PER_PAGE_CAP]
            except OSError:
                txt = ""
        if not txt:
            txt = (hit.get("snippet") or "").replace(">>>", "").replace("<<<", "")[:PER_PAGE_CAP]
        if not txt:
            continue
        if total + len(txt) > budget:
            txt = txt[: max(0, budget - total)]
        out.append(f"### vault/{rel}\n{txt}")
        used.append(f"vault/{rel}")
        total += len(txt)
        if total >= budget:
            break
    return "\n\n".join(out), used


# ── B': vector RAG over the curated wiki pages (fastembed) ────────────
_WIKI_INDEX: dict[str, tuple[tuple[int, float], list[tuple[str, str, list[float]]]]] = {}


def _chunk(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size])
        i += size - overlap
    return out


def _wiki_vector_index(workspace: Path):
    from switchbay import conversations
    key = str(workspace)
    sig = tools._graph_signature(workspace)
    cached = _WIKI_INDEX.get(key)
    if cached is not None and cached[0] == sig:
        return cached[1]
    emb = conversations._load_embedder()
    if emb is None:
        return []
    chunks: list[tuple[str, str]] = []  # (page, chunk_text)
    for rel, p in tools._iter_wiki_pages(workspace):
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for c in _chunk(txt):
            chunks.append((rel, c))
    vecs = emb.embed_passages([c for _, c in chunks])
    index = [(chunks[i][0], chunks[i][1], vecs[i]) for i in range(len(chunks))]
    _WIKI_INDEX[key] = (sig, index)
    return index


def retrieve_bprime(workspace: Path, query: str, k: int = 6, **_) -> tuple[str, list[str]]:
    from switchbay import conversations
    index = _wiki_vector_index(workspace)
    if not index:
        return "", []
    emb = conversations._load_embedder()
    q = emb.embed_query(query)
    scored = sorted(index, key=lambda row: -sum(a * b for a, b in zip(q, row[2])))
    out, used, total = [], [], 0
    for page, chunk, _v in scored[: k * 2]:
        if page in used:
            continue
        t = chunk[:PER_PAGE_CAP]
        if total + len(t) > CTX_BUDGET:
            t = t[: max(0, CTX_BUDGET - total)]
        out.append(f"### {page}\n{t}")
        used.append(page)
        total += len(t)
        if len(used) >= k or total >= CTX_BUDGET:
            break
    return "\n\n".join(out), used


# ── Personalized PageRank over the CE graph (replaces BFS expansion) ──
_PPR_ADJ: dict[str, tuple[tuple[int, float], dict]] = {}


def _ppr_adjacency(workspace: Path):
    """Undirected weighted adjacency: wikilinks (w=1) + co-citation edges
    (pages sharing a vault source, downweighted by source fan-out). Cached
    by the graph signature."""
    key = str(workspace)
    sig = tools._graph_signature(workspace)
    cached = _PPR_ADJ.get(key)
    if cached is not None and cached[0] == sig:
        return cached[1]
    idx = tools._graph_index(workspace)
    from collections import defaultdict
    adj: dict[str, dict[str, float]] = defaultdict(dict)
    for u in idx.out:
        for v in idx.out[u] | idx.inc.get(u, set()):
            adj[u][v] = adj[u].get(v, 0.0) + 1.0
            adj[v][u] = adj[v].get(u, 0.0) + 1.0
    src_pages: dict[str, list[str]] = defaultdict(list)
    for p, srcs in idx.cites.items():
        for s in srcs:
            src_pages[s].append(p)
    for _s, pages in src_pages.items():
        if len(pages) < 2:
            continue
        w = 0.5 / len(pages)                     # big shared sources → weak edges
        for i, a in enumerate(pages):
            for b in pages[i + 1:]:
                adj[a][b] = adj[a].get(b, 0.0) + w
                adj[b][a] = adj[b].get(a, 0.0) + w
    adj = dict(adj)
    _PPR_ADJ[key] = (sig, adj)
    return adj


def _ppr(workspace: Path, seeds: list[str], alpha: float = 0.15, iters: int = 40) -> dict[str, float]:
    """Personalized PageRank restarting to `seeds` — single-shot multi-hop
    propagation (HippoRAG's ranker) over CE's curated graph."""
    adj = _ppr_adjacency(workspace)
    seeds = [s for s in seeds if s in adj]
    if not seeds:
        return {}
    s = {sd: 1.0 / len(seeds) for sd in seeds}
    pi = dict(s)
    outw = {u: sum(adj[u].values()) for u in adj}
    for _ in range(iters):
        nxt: dict[str, float] = {}
        for sd, sv in s.items():
            nxt[sd] = alpha * sv
        for u, pu in pi.items():
            w = outw.get(u, 0.0)
            if pu == 0.0 or w == 0.0:
                continue
            share = (1 - alpha) * pu / w
            for v, ew in adj[u].items():
                nxt[v] = nxt.get(v, 0.0) + share * ew
        pi = nxt
    return pi


def _graph_pages_ppr(workspace: Path, query: str, seeds: int, k: int) -> list[str]:
    """Semantic seed → PPR ranking → top-k pages (seeds first)."""
    seed_pages = _semantic_seed_pages(workspace, query, seeds)
    if not seed_pages:
        return []
    pi = _ppr(workspace, seed_pages)
    ranked = sorted((p for p in pi if p not in seed_pages), key=lambda p: -pi[p])
    return (seed_pages + ranked)[:k]


def retrieve_a1_ppr(workspace: Path, query: str, seeds: int = 2, k: int = 6, **_) -> tuple[str, list[str]]:
    """A1 with Personalized PageRank instead of fixed-hop BFS."""
    return _assemble(workspace, _graph_pages_ppr(workspace, query, seeds, k))


# ── H: hybrid (graph/curated synthesis + vault-vector recall) ────────
def retrieve_hybrid(workspace: Path, query: str, k: int = 6, **_) -> tuple[str, list[str]]:
    """The 'best of both' the H1–H4 results pointed at: A1-style curated-wiki
    context (vector seed + graph expansion — best answer quality) taking ~65%
    of the budget, plus raw-vault vector recall (B — best evidence coverage)
    filling the rest. Total context stays within the same CTX_BUDGET so it's
    apples-to-apples with the other arms."""
    wbudget = int(CTX_BUDGET * 0.65)
    seeds = _semantic_seed_pages(workspace, query, 2)
    pages = list(seeds)
    if seeds:
        idx = tools._graph_index(workspace)
        qterms = {t.casefold() for t in _WORD.findall(query)}
        cand: dict[str, tuple[int, int]] = {}
        for s in seeds:
            nb = tools._wiki_neighbors(workspace, {"page": s, "hops": 2})
            for n in nb.get("neighbors", []):
                pg = n["page"]
                overlap = sum(1 for t in qterms if t in (n.get("title", "") + " " + pg).casefold())
                d = n.get("distance", 3)
                if pg not in cand or (d, -overlap) < cand[pg]:
                    cand[pg] = (d, -overlap)
        pages += [p for p in sorted(cand, key=lambda p: cand[p]) if p not in seeds]
    # breadth: a few more pure-semantic wiki pages (B'-style)
    pages += [p for p in _semantic_seed_pages(workspace, query, 4) if p not in pages]
    ctx_w, used_w = _assemble(workspace, pages[:k], budget=wbudget)
    # fill the rest with raw-vault evidence (recall)
    ctx_v, used_v = retrieve_b(workspace, query, k=3, budget=max(0, CTX_BUDGET - len(ctx_w)))
    parts = [x for x in (ctx_w, ctx_v) if x]
    return "\n\n".join(parts), used_w + used_v


def retrieve_hybrid_adaptive(workspace: Path, query: str, k: int = 6,
                             category: str | None = None, **_) -> tuple[str, list[str]]:
    """Adaptive, PPR-based hybrid (the design the H1–H4 + hybrid results
    pointed at). Routes by question type:
      · global/sensemaking → curated graph ONLY (PPR over CE's graph, full
        budget) — raw-vault chunks were shown to DILUTE comprehensiveness.
      · factoid / multi-hop → PPR-curated context (~65%) + raw-vault vector
        recall (rest) — where recall matters most.
    In production the route comes from a lightweight query classifier; here
    we use the known category as the routing upper bound."""
    if category == "global":
        return _assemble(workspace, _graph_pages_ppr(workspace, query, 2, k))
    # factoid / multi-hop: PPR-curated + vault recall
    wbudget = int(CTX_BUDGET * 0.65)
    pages = _graph_pages_ppr(workspace, query, 2, k)
    ctx_w, used_w = _assemble(workspace, pages, budget=wbudget)
    ctx_v, used_v = retrieve_b(workspace, query, k=3, budget=max(0, CTX_BUDGET - len(ctx_w)))
    parts = [x for x in (ctx_w, ctx_v) if x]
    return "\n\n".join(parts), used_w + used_v


def retrieve_routed(workspace: Path, query: str, k: int = 6,
                    category: str | None = None, **_) -> tuple[str, list[str]]:
    """Adaptive routing over BFS (the correction to HA, which routed over the
    weaker PPR). Sends each question type to the retriever the benchmark shows
    is best for it — no exotic machinery, just per-type routing:
      · single-hop / factoid → curated-wiki vector (B′) — top factoid correctness
      · multi-hop            → hybrid graph+vault (H)   — best correctness+recall balance
      · global / sensemaking → graph-only, BFS (A1)     — best comprehensiveness, no vault dilution
    In production the route comes from a lightweight query classifier; here the
    known category is the routing upper bound."""
    if category == "global":
        return retrieve_a1(workspace, query, k=k)        # BFS graph-only
    if category == "single_hop":
        return retrieve_bprime(workspace, query, k=k)    # curated-wiki vector
    return retrieve_hybrid(workspace, query, k=k)        # multi-hop → hybrid


# ── T2: two-stage study-sim retrieval (v0.9.2 track) ─────────────────
def retrieve_two_stage(
    workspace: Path,
    query: str,
    k: int = 6,
    category: str | None = None,
    **_,
) -> tuple[str, list[str]]:
    """Needle-aware two-stage assembly.

    Stage 1 — primary evidence (always filled first):
      · vault hybrid hits (raw lecture text / captions)
      · wiki sources / facts / figures / tables / evidence

    Stage 2 — work-network scaffolding (remaining budget only):
      · entities / concepts / (analyses only when not needle)

    Analyses are demoted so multi-lecture essays cannot crowd out a figure
    caption or atomic fact on extractive queries. For free synthesis
    (non-needle global/exam themes), analyses re-enter mid-pack after
    concepts.

    Production intent: promote this policy into CE's query path; keep here
    as the measurement prototype until CE owns adaptive routing.
    """
    needle = query_is_needle(query) or category in ("single_hop", "multi_hop")
    # Stage-1 budget: most of the window for needles; half for synthesis.
    stage1_frac = 0.72 if needle else 0.50
    b1 = int(CTX_BUDGET * stage1_frac)
    b2 = max(0, CTX_BUDGET - b1)

    # --- Stage 1a: vault / raw sources ---
    ctx_v, used_v = retrieve_b(workspace, query, k=max(3, k // 2), budget=b1)

    # --- Stage 1b: wiki primary types (vector, then demote) ---
    wiki_seeds = _semantic_seed_pages(workspace, query, max(k, 8))
    # Keyword catches exact caption digits keyword search may surface.
    try:
        kw = tools._search_wiki(workspace, {"query": query, "limit": k})
        for r in kw.get("results") or []:
            pg = r.get("page")
            if pg and pg not in wiki_seeds:
                wiki_seeds.append(pg)
    except Exception:  # noqa: BLE001
        pass

    primary_types = {"sources", "facts", "figures", "tables", "evidence"}
    secondary_types = {"entities", "concepts", "analyses", "notes"}
    if not needle:
        # Synthesis may pull analyses earlier.
        primary_types |= {"entities", "concepts"}
        secondary_types = {"analyses", "notes"}

    primary = [p for p in wiki_seeds if _page_type(p) in primary_types]
    primary = demote_analyses(primary, needle=True)
    # Fill residual stage-1 budget with wiki primary pages.
    remain1 = max(0, b1 - len(ctx_v))
    ctx_p, used_p = _assemble(workspace, primary[:k], budget=remain1)

    # --- Stage 2: work network ---
    secondary = [p for p in wiki_seeds if _page_type(p) in secondary_types]
    if not secondary:
        # Graph expand from primary for related concepts/entities.
        seeds = (used_p or primary)[:2]
        if seeds:
            for s in seeds:
                try:
                    nb = tools._wiki_neighbors(workspace, {"page": s, "hops": 1})
                    for n in nb.get("neighbors") or []:
                        pg = n.get("page")
                        if pg and _page_type(pg) in secondary_types and pg not in secondary:
                            secondary.append(pg)
                except Exception:  # noqa: BLE001
                    pass
    secondary = demote_analyses(secondary, needle=needle)
    # Drop anything already used.
    used_set = set(used_v) | set(used_p)
    secondary = [p for p in secondary if p not in used_set and f"wiki/{p}" not in used_set]
    ctx_s, used_s = _assemble(workspace, secondary[:k], budget=b2)

    parts = [x for x in (ctx_v, ctx_p, ctx_s) if x]
    return "\n\n".join(parts), used_v + used_p + used_s


def retrieve_wiki_type_aware(workspace: Path, query: str, k: int = 6, **_) -> tuple[str, list[str]]:
    """B' with analysis demotion (wiki-only two-stage without vault)."""
    needle = query_is_needle(query)
    pages = _semantic_seed_pages(workspace, query, max(k * 2, 8))
    pages = demote_analyses(pages, needle=needle)
    return _assemble(workspace, pages[:k])


ARMS = {
    "A0": retrieve_a0,
    "A1": retrieve_a1,
    "B": retrieve_b,
    "Bp": retrieve_bprime,
    "H": retrieve_hybrid,
    "A1P": retrieve_a1_ppr,          # graph, PPR instead of BFS
    "HA": retrieve_hybrid_adaptive,  # adaptive PPR-hybrid (query-routed)
    "R": retrieve_routed,            # adaptive routing over BFS (per-type best)
    "T2": retrieve_two_stage,        # v0.9.2 study-sim two-stage
    "BpT": retrieve_wiki_type_aware, # B' + type demotion
}

# Wiki-embedding granularity experiment arms (chunk vs whole-page vs descriptor).
# Late import: wiki_gran imports from this module, so register after ARMS exists.
try:
    from bench.wiki_gran import (
        retrieve_wiki_chunk, retrieve_wiki_whole, retrieve_wiki_desc,
    )
    ARMS.update({
        "Bwc": retrieve_wiki_chunk,   # rank pages by best 900-char chunk (CE current)
        "Bww": retrieve_wiki_whole,   # rank by one whole-page vector (truncates)
        "Bwd": retrieve_wiki_desc,    # rank over-window pages by compressed descriptor
    })
except Exception:  # noqa: BLE001 — experiment arms are optional
    pass
