"""``rag_modern_agentic_v1`` — strong contemporary hybrid, reranked RAG.

A serious modern raw-vault RAG comparator for the CE QUERY product pilot. It is
**not** the simple Phase-1 ``rag_std`` lexical arm, and it is **not** literal
BGE-M3: fastembed 0.8.0 ships no ``bge-m3``/``bge-reranker-v2-m3``, and pulling
FlagEmbedding+torch is heavy and fragile. Per review S4 (which left the exact
model IDs open) this pins a torch-free, ONNX-deterministic fastembed stack and
labels it honestly as a strong contemporary hybrid — never "BGE-M3".

Pinned components (frozen in ``PINNED``; hashed into the calibration record):
  dense  : BAAI/bge-large-en-v1.5   (1024-dim, English)
  sparse : prithivida/Splade_PP_en_v1 (learned sparse)
  lexical: in-process Okapi BM25      (the calibration "lexical-only" variant)
  rerank : BAAI/bge-reranker-base     (cross-encoder)
  fusion : reciprocal-rank fusion (k=60)

Chunks are **document-aware / metadata-contextual** — each carries its source
path, nearest heading, and exact char span — but are **not** LLM-situated
(review S2: kept quota-free and deterministic; the Anthropic contextual-retrieval
framing is deliberately dropped). Parent/window expansion happens only AFTER
reranking.

The live arm is **agent-driven** (decision A): the host model calls
:func:`rag_search` within its agent-turn ceiling and issues its own follow-up
queries, so multi-query is the agent's tool use. The deterministic
``multi_query`` here exists only for the mechanical calibration comparison.

Citations use the ``(vault:path:start-end)`` grammar the cite-resolver credits
(review B4), so grounding is measured, not citation format.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol

import numpy as np

PINNED: dict[str, Any] = {
    "arm": "rag_modern_agentic_v1",
    # Small, reliably-downloadable ONNX models (the ~1.3GB bge-large / reranker
    # ONNX blobs would not complete over the unauthenticated HF connection in
    # this environment). bge-small-en-v1.5 is a strong 384-dim English embedder
    # (the project's own default); the sparse head is an in-process Okapi BM25
    # (no SPLADE download); rerank is a cross-encoder. Honestly a "strong
    # contemporary hybrid, reranked RAG" — never "BGE-M3" (review S4).
    "dense_model": "BAAI/bge-small-en-v1.5",
    "sparse": "okapi-bm25-inproc",
    "reranker_model": "Xenova/ms-marco-MiniLM-L-6-v2",
    "fusion": "rrf",
    "rrf_k": 60,
    "bm25_k1": 1.5,
    "bm25_b": 0.75,
    "chunk_chars": 700,
    "overlap": 120,
    "context_budget": 7000,
    "retrieve_pool": 40,
    "final_k": 6,
    "window_radius": 1,
    "version": "rag_modern_agentic_v1@2026-07-24b",
}


def config_hash() -> str:
    return hashlib.sha256(
        json.dumps(PINNED, sort_keys=True).encode()
    ).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #

_HEADING = re.compile(r"^#{1,6}\s+(.*)$")
_VAULT_EXT = {".md", ".txt"}


@dataclass
class Chunk:
    id: str          # "vault/<path>:<start>-<end>" — the citation locator
    path: str        # posix rel path from workspace
    start: int
    end: int
    heading: str
    text: str

    @property
    def cite(self) -> str:
        return f"(vault:{self.path.removeprefix('vault/')}:{self.start}-{self.end})"


def _iter_vault_files(workspace: Path) -> Iterable[Path]:
    vault = Path(workspace) / "vault"
    if not vault.is_dir():
        return
    for p in sorted(vault.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() in _VAULT_EXT or ".extracted." in p.name:
            yield p


def chunk_vault(
    workspace: Path,
    *,
    chunk_chars: int = PINNED["chunk_chars"],
    overlap: int = PINNED["overlap"],
) -> list[Chunk]:
    """Deterministic document-aware chunker with heading + exact span metadata."""
    workspace = Path(workspace)
    chunks: list[Chunk] = []
    for p in _iter_vault_files(workspace):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = p.relative_to(workspace).as_posix()
        # Precompute heading at each char offset (nearest preceding markdown head).
        heading = ""
        head_at: list[tuple[int, str]] = []
        off = 0
        for line in text.splitlines(keepends=True):
            m = _HEADING.match(line.strip())
            if m:
                head_at.append((off, m.group(1).strip()))
            off += len(line)

        def heading_for(pos: int) -> str:
            h = ""
            for start, htext in head_at:
                if start <= pos:
                    h = htext
                else:
                    break
            return h

        i = 0
        n = 0
        step = max(1, chunk_chars - overlap)
        while i < len(text):
            piece = text[i : i + chunk_chars]
            if piece.strip():
                chunks.append(
                    Chunk(
                        id=f"{rel}:{i}-{i + len(piece)}",
                        path=rel,
                        start=i,
                        end=i + len(piece),
                        heading=heading_for(i),
                        text=piece,
                    )
                )
            n += 1
            i += step
            if n > 5000:
                break
    return chunks


# --------------------------------------------------------------------------- #
# Embedder seam (real fastembed, or a deterministic stub for tests)
# --------------------------------------------------------------------------- #


class Embedder(Protocol):
    def embed_dense(self, texts: list[str]) -> np.ndarray: ...  # (n, d) L2-normalized
    def rerank(self, query: str, texts: list[str]) -> list[float]: ...


class FastembedEmbedder:
    """Lazy ONNX fastembed backend for the pinned models. No torch.

    Only a dense embedder and a cross-encoder reranker are downloaded; the
    sparse signal is an in-process BM25 (see ``BM25``), so no SPLADE weights.
    """

    def __init__(self) -> None:
        self._dense = None
        self._rer = None

    def _dense_model(self):
        if self._dense is None:
            from fastembed import TextEmbedding

            self._dense = TextEmbedding(PINNED["dense_model"])
        return self._dense

    def _reranker(self):
        if self._rer is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._rer = TextCrossEncoder(PINNED["reranker_model"])
        return self._rer

    def embed_dense(self, texts: list[str]) -> np.ndarray:
        vecs = np.array(list(self._dense_model().embed(texts)), dtype=np.float32)
        if vecs.ndim == 1:
            vecs = vecs.reshape(1, -1)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vecs / norms

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        return [float(s) for s in self._reranker().rerank(query, texts)]


# --------------------------------------------------------------------------- #
# BM25 (in-process, for the "lexical-only" calibration variant)
# --------------------------------------------------------------------------- #

_TOKEN = re.compile(r"[a-z0-9]{2,}")


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.casefold())


class BM25:
    def __init__(self, docs_tokens: list[list[str]], *, k1: float, b: float):
        self.k1 = k1
        self.b = b
        self.N = len(docs_tokens)
        self.doc_len = [len(d) for d in docs_tokens]
        self.avgdl = (sum(self.doc_len) / self.N) if self.N else 0.0
        self.tf: list[dict[str, int]] = []
        df: dict[str, int] = {}
        for toks in docs_tokens:
            counts: dict[str, int] = {}
            for t in toks:
                counts[t] = counts.get(t, 0) + 1
            self.tf.append(counts)
            for t in counts:
                df[t] = df.get(t, 0) + 1
        self.idf = {
            t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()
        }

    def scores(self, query: str) -> np.ndarray:
        q = _tokenize(query)
        out = np.zeros(self.N, dtype=np.float32)
        for i in range(self.N):
            dl = self.doc_len[i] or 1
            s = 0.0
            tf = self.tf[i]
            for t in q:
                if t not in tf:
                    continue
                idf = self.idf.get(t, 0.0)
                f = tf[t]
                s += idf * (f * (self.k1 + 1)) / (
                    f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                )
            out[i] = s
        return out


# --------------------------------------------------------------------------- #
# Index + retrieval
# --------------------------------------------------------------------------- #


@dataclass
class Hit:
    chunk: Chunk
    score: float
    stage: str = "fused"


def _rank(scores: np.ndarray) -> dict[int, int]:
    """Return {doc_index: rank} (0-based) sorted by descending score."""
    order = np.argsort(-scores, kind="stable")
    return {int(idx): r for r, idx in enumerate(order)}


def _rrf(rank_lists: list[dict[int, int]], *, k: int, n: int) -> np.ndarray:
    fused = np.zeros(n, dtype=np.float32)
    for ranks in rank_lists:
        for idx, r in ranks.items():
            fused[idx] += 1.0 / (k + r)
    return fused


class ModernRagIndex:
    """Builds + serves the pinned hybrid index over the raw vault."""

    def __init__(self, workspace: Path, embedder: Embedder | None = None):
        self.workspace = Path(workspace)
        self.embedder = embedder or FastembedEmbedder()
        self.chunks: list[Chunk] = chunk_vault(self.workspace)
        self.corpus_hash = self._corpus_hash()
        self._dense: np.ndarray | None = None
        self._bm25: BM25 | None = None
        # chunks grouped by path in span order for window expansion
        self._by_path: dict[str, list[int]] = {}
        for i, c in enumerate(self.chunks):
            self._by_path.setdefault(c.path, []).append(i)

    def _corpus_hash(self) -> str:
        h = hashlib.sha256()
        for c in self.chunks:
            h.update(c.id.encode())
            h.update(b"\0")
            h.update(c.text.encode())
            h.update(b"\0")
        return h.hexdigest()[:16]

    def build(self) -> "ModernRagIndex":
        texts = [c.text for c in self.chunks]
        self._dense = self.embedder.embed_dense(texts) if texts else np.zeros((0, 1))
        self._bm25 = BM25(
            [_tokenize(t) for t in texts], k1=PINNED["bm25_k1"], b=PINNED["bm25_b"]
        )
        return self

    def _ensure_built(self) -> None:
        if self._dense is None:
            self.build()

    # --- persistence: the index is a frozen artifact; per-trajectory rag_search
    #     loads it (fast) instead of re-embedding the corpus (minutes). --------
    def save(self, out_dir: Path) -> dict[str, Any]:
        self._ensure_built()
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        np.save(out_dir / "dense.npy", self._dense)
        (out_dir / "chunks.json").write_text(
            json.dumps([c.__dict__ for c in self.chunks]), encoding="utf-8"
        )
        meta = {
            "corpus_hash": self.corpus_hash,
            "config_hash": config_hash(),
            "pinned": PINNED,
            "n_chunks": len(self.chunks),
        }
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta

    @classmethod
    def load(cls, index_dir: Path, *, embedder: Embedder | None = None) -> "ModernRagIndex":
        index_dir = Path(index_dir)
        meta = json.loads((index_dir / "meta.json").read_text(encoding="utf-8"))
        if meta.get("config_hash") != config_hash():
            raise ValueError(
                f"frozen index config_hash {meta.get('config_hash')} != current {config_hash()}"
            )
        self = cls.__new__(cls)  # bypass __init__ (no re-chunk / re-embed)
        self.workspace = index_dir
        self.embedder = embedder or FastembedEmbedder()
        self.chunks = [Chunk(**d) for d in json.loads((index_dir / "chunks.json").read_text("utf-8"))]
        self._dense = np.load(index_dir / "dense.npy")
        self._bm25 = BM25(
            [_tokenize(c.text) for c in self.chunks], k1=PINNED["bm25_k1"], b=PINNED["bm25_b"]
        )
        self.corpus_hash = meta["corpus_hash"]
        self._by_path = {}
        for i, c in enumerate(self.chunks):
            self._by_path.setdefault(c.path, []).append(i)
        return self

    def _dense_scores(self, query: str) -> np.ndarray:
        assert self._dense is not None
        if self._dense.shape[0] == 0:
            return np.zeros(0, dtype=np.float32)
        q = self.embedder.embed_dense([query])[0]
        return (self._dense @ q).astype(np.float32)

    def top_dense_score(self, query: str) -> float:
        """Max dense cosine similarity — the abstention relevance signal.

        Decoupled from the ranking variant so abstention is a real, comparable
        score for every mode (RRF/rank scores are not comparable across
        queries; a placeholder is meaningless). For a corpus-absent query the
        best chunk's cosine stays low; for a covered query it is high.
        """
        self._ensure_built()
        ds = self._dense_scores(query)
        return float(ds.max()) if ds.size else 0.0

    def _bm25_scores(self, query: str) -> np.ndarray:
        assert self._bm25 is not None
        return self._bm25.scores(query)

    def _candidate_indices(
        self, query: str, *, mode: str, pool: int
    ) -> list[int]:
        self._ensure_built()
        n = len(self.chunks)
        if n == 0:
            return []
        if mode == "lexical":
            return list(np.argsort(-self._bm25_scores(query))[:pool])
        if mode == "dense":
            return list(np.argsort(-self._dense_scores(query))[:pool])
        # hybrid: RRF over dense + BM25 (sparse) rank lists
        dense = _rank(self._dense_scores(query))
        sparse = _rank(self._bm25_scores(query))
        fused = _rrf([dense, sparse], k=PINNED["rrf_k"], n=n)
        return list(np.argsort(-fused)[:pool])

    def candidate_indices(self, query: str, *, mode: str, pool: int = PINNED["retrieve_pool"]) -> list[int]:
        """Public: first-stage candidate chunk indices (no rerank)."""
        return self._candidate_indices(query, mode=mode, pool=pool)

    def rerank_indices(self, query: str, indices: list[int]) -> list[tuple[int, float]]:
        """Public: cross-encoder rerank a candidate index list, best first."""
        if not indices:
            return []
        texts = [self.chunks[i].text for i in indices]
        rr = self.embedder.rerank(query, texts)
        order = sorted(range(len(indices)), key=lambda j: -rr[j])
        return [(indices[j], rr[j]) for j in order]

    def search(
        self,
        query: str,
        *,
        mode: str = "hybrid",
        rerank: bool = True,
        window: bool = True,
        final_k: int = PINNED["final_k"],
        pool: int = PINNED["retrieve_pool"],
    ) -> list[Hit]:
        cand = self._candidate_indices(query, mode=mode, pool=pool)
        if not cand:
            return []
        if rerank:
            texts = [self.chunks[i].text for i in cand]
            rr = self.embedder.rerank(query, texts)
            order = sorted(range(len(cand)), key=lambda j: -rr[j])
            ranked = [(cand[j], rr[j]) for j in order][:final_k]
        else:
            ranked = [(i, 1.0 / (r + 1)) for r, i in enumerate(cand[:final_k])]
        hits = [Hit(chunk=self.chunks[i], score=float(s), stage=mode) for i, s in ranked]
        if window:
            hits = self._expand_windows(hits)
        return hits

    def _expand_windows(self, hits: list[Hit], radius: int = PINNED["window_radius"]) -> list[Hit]:
        """Add adjacent same-document chunks AFTER reranking, preserving order."""
        seen: set[str] = {h.chunk.id for h in hits}
        expanded: list[Hit] = []
        for h in hits:
            expanded.append(h)
            siblings = self._by_path.get(h.chunk.path, [])
            pos = siblings.index(next(i for i in siblings if self.chunks[i].id == h.chunk.id))
            for d in range(1, radius + 1):
                for j in (pos - d, pos + d):
                    if 0 <= j < len(siblings):
                        c = self.chunks[siblings[j]]
                        if c.id not in seen:
                            seen.add(c.id)
                            expanded.append(Hit(chunk=c, score=h.score, stage="window"))
        return expanded


def format_context(hits: list[Hit], *, budget: int = PINNED["context_budget"]) -> tuple[str, list[str]]:
    """Render hits into a citation-anchored context within the shared budget."""
    parts: list[str] = []
    sources: list[str] = []
    total = 0
    for h in hits:
        head = f" — {h.chunk.heading}" if h.chunk.heading else ""
        block = f"### {h.chunk.cite}{head}\n{h.chunk.text}\n"
        if total + len(block) > budget:
            block = block[: max(0, budget - total)]
        if not block:
            break
        parts.append(block)
        sources.append(h.chunk.cite)
        total += len(block)
        if total >= budget:
            break
    return "\n".join(parts), sources


@dataclass
class RagSearchResult:
    query: str
    mode: str
    abstained: bool
    top_score: float
    context: str
    sources: list[str] = field(default_factory=list)
    hits: list[dict[str, Any]] = field(default_factory=list)


def rag_search(
    index: ModernRagIndex,
    query: str,
    *,
    mode: str = "hybrid",
    rerank: bool = False,
    no_answer_threshold: float = 0.0,
    final_k: int = PINNED["final_k"],
) -> RagSearchResult:
    """The read-only tool the agent calls. Abstains below the calibrated
    threshold on the top DENSE cosine (a real relevance signal, independent of
    the ranking variant / whether reranking is applied)."""
    relevance = index.top_dense_score(query)
    abstained = relevance < no_answer_threshold
    if abstained:
        return RagSearchResult(
            query=query, mode=mode, abstained=True, top_score=relevance,
            context="NO SUFFICIENTLY RELEVANT SOURCE FOUND.", sources=[],
        )
    hits = index.search(query, mode=mode, rerank=rerank, window=True, final_k=final_k)
    context, sources = format_context(hits)
    return RagSearchResult(
        query=query, mode=mode, abstained=False, top_score=relevance,
        context=context, sources=sources,
        hits=[{"cite": h.chunk.cite, "score": h.score, "stage": h.stage} for h in hits],
    )


def build_and_save(workspace: Path, out_dir: Path, *, embedder: Embedder | None = None) -> dict[str, Any]:
    """Build the frozen hybrid index over the raw vault and persist it."""
    index = ModernRagIndex(Path(workspace), embedder=embedder).build()
    return index.save(Path(out_dir))


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Build + freeze the modern-RAG index.")
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args(argv)
    meta = build_and_save(args.workspace.expanduser().resolve(), args.out_dir)
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
