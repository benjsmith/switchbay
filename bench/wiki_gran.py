"""Wiki-embedding granularity experiment — chunk vs whole-page vs descriptor.

The question: for retrieving *curated wiki pages*, does the embedding SURFACE
matter — 900-char chunks (what CE ships), one whole-page vector (truncates the
34% of pages over the ~512-token window), or a compressed retrieval-descriptor
of the over-window pages (the "distill, don't split" idea)?

Fairness: all three arms rank the SAME page set and feed the SAME whole-page
context to the generator (`_assemble`). Only the vector used to *rank* differs.
So this isolates the granularity effect, holding the fed context constant.

  Bwc  wiki-chunk      rank pages by their best 900-char chunk score
  Bww  wiki-whole      rank pages by a single whole-page vector (model truncates)
  Bwd  wiki-descriptor rank over-window pages by a cached LLM descriptor; short
                       pages by the page itself
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from switchbay import conversations, tools

from bench import llm
from bench.retrievers import _assemble, _wiki_vector_index

WINDOW = 2000  # ~512-token window for the 384-dim bge-small model (chars)
_CACHE_DIR = Path(__file__).parent / "cache"
_DESC_CACHE = _CACHE_DIR / "wiki_descriptors.json"
_PAGE_IDX: dict[tuple[str, str], tuple[tuple[int, float], list[tuple[str, list[float]]]]] = {}
_DESC_PROVIDER: str | None = None
# fastembed/ONNX is not reliably thread-safe, and the harness answers with 8
# workers — serialize all embedder access + guard lazy index builds.
_EMB_LOCK = threading.Lock()
_IDX_LOCK = threading.Lock()


def _embed_passages(surfaces: list[str]) -> list[list[float]]:
    emb = conversations._load_embedder()
    with _EMB_LOCK:
        return emb.embed_passages(surfaces)


def _embed_query(query: str) -> list[float]:
    emb = conversations._load_embedder()
    with _EMB_LOCK:
        return emb.embed_query(query)


def _pages(workspace: Path) -> list[tuple[str, str]]:
    out = []
    for rel, p in tools._iter_wiki_pages(workspace):
        try:
            out.append((rel, p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            pass
    return out


# ── compressed retrieval descriptors (cached, deterministic temp=0) ──────
_DESC_SYS = (
    "You compress knowledge-wiki pages into RETRIEVAL DESCRIPTORS. A descriptor "
    "is what a search index embeds so the page is findable — not a summary for a "
    "human to read. Be dense and keyword-rich, never narrative."
)


def _desc_prompt(text: str) -> str:
    return (
        f"Compress the page below into a retrieval descriptor UNDER {WINDOW} "
        "characters. Include, densely: its key claims/results (keep distinctive "
        "specifics — numbers, dates, proper names), every entity involved and any "
        "alternative names / aliases / abbreviations, and the recurring themes. "
        "Preserve terms a searcher might use even if the page states them only "
        "once. No preamble, no prose paragraphs.\n\n=== PAGE ===\n" + text[:12000]
    )


def _load_desc_cache() -> dict:
    if _DESC_CACHE.is_file():
        try:
            return json.loads(_DESC_CACHE.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _provider() -> str:
    global _DESC_PROVIDER
    if _DESC_PROVIDER is None:
        avail = llm.available_providers(["anthropic", "openai", "xai", "gemini"])
        _DESC_PROVIDER = avail[0] if avail else "anthropic"
    return _DESC_PROVIDER


def build_descriptors(workspace: Path, verbose: bool = True) -> dict:
    """Generate + cache a descriptor for every over-window page. Idempotent:
    keyed by sha256(page text), so unchanged pages are never re-generated."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _load_desc_cache()
    pages = _pages(workspace)
    todo = [(rel, t) for rel, t in pages
            if len(t) > WINDOW and hashlib.sha256(t.encode()).hexdigest() not in cache]
    if verbose:
        over = sum(1 for _, t in pages if len(t) > WINDOW)
        print(f"pages={len(pages)} over-window={over} cached={over - len(todo)} to-generate={len(todo)}")
    prov = _provider() if todo else None
    for i, (rel, t) in enumerate(todo, 1):
        sha = hashlib.sha256(t.encode()).hexdigest()
        desc, ok = llm.llm_call(prov, _desc_prompt(t), system=_DESC_SYS,
                                max_tokens=600, temperature=0.0)
        cache[sha] = {"page": rel, "desc": desc if ok else t[:WINDOW],
                      "model": prov, "ok": ok, "in_chars": len(t), "out_chars": len(desc)}
        if verbose and (i % 10 == 0 or i == len(todo)):
            print(f"  descriptor {i}/{len(todo)}  {rel}  {len(t)}→{len(desc)} chars")
        _DESC_CACHE.write_text(json.dumps(cache, indent=1))  # checkpoint each
    return cache


def _surface(rel: str, text: str, mode: str, cache: dict) -> str:
    if mode == "whole":
        return text
    # descriptor mode: over-window → cached descriptor (capped to the window so
    # the whole descriptor is embedded, not model-truncated mid-way); short → page
    if len(text) > WINDOW:
        row = cache.get(hashlib.sha256(text.encode()).hexdigest())
        if row:
            return row["desc"][:WINDOW]
    return text


def _page_index(workspace: Path, mode: str) -> list[tuple[str, list[float]]]:
    key = (mode, str(workspace))
    sig = tools._graph_signature(workspace)
    cached = _PAGE_IDX.get(key)
    if cached is not None and cached[0] == sig:
        return cached[1]
    with _IDX_LOCK:  # double-checked: only one worker builds each index
        cached = _PAGE_IDX.get(key)
        if cached is not None and cached[0] == sig:
            return cached[1]
        if conversations._load_embedder() is None:
            return []
        pages = _pages(workspace)
        cache = _load_desc_cache() if mode == "desc" else {}
        surfaces = [_surface(rel, t, "whole" if mode == "whole" else "desc", cache) for rel, t in pages]
        vecs = _embed_passages(surfaces)
        idx = [(pages[i][0], vecs[i]) for i in range(len(pages))]
        _PAGE_IDX[key] = (sig, idx)
        return idx


def _rank_pages(workspace: Path, query: str, idx: list[tuple[str, list[float]]], k: int) -> list[str]:
    q = _embed_query(query)
    ranked = sorted(idx, key=lambda r: -sum(a * b for a, b in zip(q, r[1])))
    return [p for p, _ in ranked[:k]]


# ── the three arms (identical fed context; differ only in ranking surface) ──
def retrieve_wiki_chunk(workspace: Path, query: str, k: int = 6, **_) -> tuple[str, list[str]]:
    with _IDX_LOCK:
        index = _wiki_vector_index(workspace)  # (page, chunk, vec) — 900-char chunks
    if not index:
        return "", []
    q = _embed_query(query)
    best: dict[str, float] = {}
    for page, _chunk, v in index:
        s = sum(a * b for a, b in zip(q, v))
        if page not in best or s > best[page]:
            best[page] = s  # page score = its best chunk
    pages = sorted(best, key=lambda p: -best[p])[:k]
    return _assemble(workspace, pages)


def retrieve_wiki_whole(workspace: Path, query: str, k: int = 6, **_) -> tuple[str, list[str]]:
    idx = _page_index(workspace, "whole")
    return _assemble(workspace, _rank_pages(workspace, query, idx, k)) if idx else ("", [])


def retrieve_wiki_desc(workspace: Path, query: str, k: int = 6, **_) -> tuple[str, list[str]]:
    idx = _page_index(workspace, "desc")
    return _assemble(workspace, _rank_pages(workspace, query, idx, k)) if idx else ("", [])


if __name__ == "__main__":
    import sys
    ws = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / "Dev" / "curiosity-test"
    build_descriptors(ws)
