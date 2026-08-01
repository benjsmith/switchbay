"""Systems under test for agentic_query_bench.

Mandatory: ce_query, rag_std, agentic_plain, closed_book, ce_retrieve_only
Pilot extra: long_ctx, rag_wiki_text
Optional: rag_graph (stub)

Agentic loops share max_tool_calls budget. Propose-only (no wiki commits).
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Optional local embedder / phase2 chunk helpers
try:
    from bench.phase2_chunked_rag import (  # type: ignore
        build_chunk_index,
        retrieve_chunks,
    )
except Exception:  # noqa: BLE001
    build_chunk_index = None  # type: ignore
    retrieve_chunks = None  # type: ignore

try:
    from bench import retrievers as R
except Exception:  # noqa: BLE001
    R = None  # type: ignore

GenerateFn = Callable[[str, str], str]  # (question, context) -> answer


def _with_history(user_message: str, history: list[dict[str, str]], limit: int = 4000) -> str:
    """Render prior turns into the question so every arm absorbs constraints.

    Multi-turn is the whole bench; an arm that answers turn N without turns
    1..N-1 cannot be scored on steer_efficiency/spine_fidelity (review RB1).
    Keeps the most recent `limit` chars.
    """
    if not history:
        return user_message
    lines = [
        f"{'USER' if m.get('role') == 'user' else 'ASSISTANT'}: {m.get('content', '')}"
        for m in history
    ]
    convo = "\n".join(lines)
    if len(convo) > limit:
        convo = convo[-limit:]
    return (
        "CONVERSATION SO FAR (absorb all prior constraints and build on your "
        f"previous answers):\n{convo}\n\nCURRENT USER TURN:\n{user_message}"
    )


@dataclass
class ArmResult:
    answer: str
    sources: list[str] = field(default_factory=list)
    context_chars: int = 0
    tool_calls: int = 0
    meta: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Arm(ABC):
    name: str
    max_tool_calls: int = 8

    @abstractmethod
    def respond(self, user_message: str, history: list[dict[str, str]]) -> ArmResult:
        ...

    def close(self) -> None:
        """Release per-trajectory resources (no-op for ordinary arms)."""
        return None


def _simple_chunk_vault(workspace: Path, chunk_chars: int = 900, overlap: int = 120) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    vault = workspace / "vault"
    if not vault.is_dir():
        return chunks
    for p in sorted(vault.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".md", ".txt", ".extracted.md"} and ".extracted." not in p.name:
            if p.suffix.lower() not in {".md", ".txt"}:
                continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = p.relative_to(workspace).as_posix()
        i = 0
        n = 0
        while i < len(text):
            piece = text[i : i + chunk_chars]
            chunks.append({
                "id": f"{rel}:{i}-{i + len(piece)}",
                "path": rel,
                "text": piece,
                "start": i,
            })
            n += 1
            i += max(1, chunk_chars - overlap)
            if n > 5000:
                break
    return chunks


def _lexical_retrieve(chunks: list[dict[str, Any]], query: str, k: int = 6) -> list[dict[str, Any]]:
    q_toks = set(re.findall(r"[a-z0-9]{3,}", query.casefold()))
    if not q_toks:
        return chunks[:k]
    scored: list[tuple[float, dict[str, Any]]] = []
    for c in chunks:
        t = c["text"].casefold()
        hit = sum(1 for tok in q_toks if tok in t)
        if hit:
            scored.append((hit / len(q_toks), c))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:k]] or chunks[:k]


def _format_chunks(chunks: list[dict[str, Any]], budget: int = 6000) -> tuple[str, list[str]]:
    parts: list[str] = []
    ids: list[str] = []
    total = 0
    for c in chunks:
        block = f"### {c['id']}\n{c['text']}\n"
        if total + len(block) > budget:
            block = block[: max(0, budget - total)]
        parts.append(block)
        ids.append(c["id"])
        total += len(block)
        if total >= budget:
            break
    return "\n".join(parts), ids


class ClosedBookArm(Arm):
    name = "closed_book"

    def __init__(self, generate: GenerateFn):
        self.generate = generate

    def respond(self, user_message: str, history: list[dict[str, str]]) -> ArmResult:
        ctx = (
            "You have NO access to the course corpus. Answer from parametric "
            "knowledge only. If unsure, say so. Do not invent lecture ids."
        )
        ans = self.generate(_with_history(user_message, history), ctx)
        return ArmResult(answer=ans, sources=[], context_chars=len(ctx), tool_calls=0)


class RagStdArm(Arm):
    name = "rag_std"

    def __init__(
        self,
        workspace: Path,
        generate: GenerateFn,
        *,
        k: int = 6,
        budget: int = 6000,
        include_wiki_text: bool = False,
    ):
        self.workspace = Path(workspace)
        self.generate = generate
        self.k = k
        self.budget = budget
        self.include_wiki_text = include_wiki_text
        self._chunks = _simple_chunk_vault(self.workspace)
        if include_wiki_text:
            wiki = self.workspace / "wiki"
            if wiki.is_dir():
                for p in wiki.rglob("*.md"):
                    try:
                        text = p.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    rel = p.relative_to(self.workspace).as_posix()
                    self._chunks.append({
                        "id": rel,
                        "path": rel,
                        "text": text[:2000],
                        "start": 0,
                    })

    def respond(self, user_message: str, history: list[dict[str, str]]) -> ArmResult:
        hits = _lexical_retrieve(self._chunks, user_message, k=self.k)
        ctx, ids = _format_chunks(hits, budget=self.budget)
        ans = self.generate(_with_history(user_message, history), ctx)
        return ArmResult(
            answer=ans,
            sources=ids,
            context_chars=len(ctx),
            tool_calls=1,
            meta={"arm": self.name, "k": self.k},
        )


class RagWikiTextArm(RagStdArm):
    name = "rag_wiki_text"

    def __init__(self, workspace: Path, generate: GenerateFn, **kw: Any):
        super().__init__(workspace, generate, include_wiki_text=True, **kw)


class LongCtxArm(Arm):
    """Stuff as much vault text as fits — no retrieval ranking."""

    name = "long_ctx"

    def __init__(self, workspace: Path, generate: GenerateFn, *, budget: int = 100_000):
        self.workspace = Path(workspace)
        self.generate = generate
        self.budget = budget

    def respond(self, user_message: str, history: list[dict[str, str]]) -> ArmResult:
        vault = self.workspace / "vault"
        parts: list[str] = []
        ids: list[str] = []
        total = 0
        if vault.is_dir():
            for p in sorted(vault.rglob("*")):
                if not p.is_file():
                    continue
                if p.suffix.lower() not in {".md", ".txt"} and ".extracted." not in p.name:
                    continue
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                rel = p.relative_to(self.workspace).as_posix()
                block = f"### {rel}\n{text}\n"
                if total + len(block) > self.budget:
                    block = block[: max(0, self.budget - total)]
                parts.append(block)
                ids.append(rel)
                total += len(block)
                if total >= self.budget:
                    break
        ctx = "\n".join(parts)
        ans = self.generate(_with_history(user_message, history), ctx)
        return ArmResult(answer=ans, sources=ids, context_chars=len(ctx), tool_calls=0)


class AgenticPlainArm(Arm):
    """Same multi-pass budget as CE-QUERY but vault chunks only (no wiki/graph)."""

    name = "agentic_plain"

    def __init__(
        self,
        workspace: Path,
        generate: GenerateFn,
        *,
        max_tool_calls: int = 8,
        k: int = 6,
        budget: int = 7000,
    ):
        self.workspace = Path(workspace)
        self.generate = generate
        self.max_tool_calls = max_tool_calls
        self.k = k
        self.budget = budget
        self._chunks = _simple_chunk_vault(self.workspace)

    def respond(self, user_message: str, history: list[dict[str, str]]) -> ArmResult:
        # Multi-pass: initial retrieve → generate follow-up queries → retrieve more → final answer
        tool_calls = 0
        collected: list[dict[str, Any]] = []
        queries = [user_message]
        hq = _with_history(user_message, history)
        # ask model for sub-queries (counts as tool-ish step via generate)
        plan_prompt = (
            "List up to 3 short search queries (one per line, no numbering) to gather "
            "course material for the user request. Queries only."
        )
        plan = self.generate(plan_prompt, hq)
        tool_calls += 1
        for line in plan.splitlines():
            q = line.strip().lstrip("-*0123456789. ")
            if 4 <= len(q) <= 120:
                queries.append(q)
            if len(queries) >= 4:
                break
        seen_ids: set[str] = set()
        for q in queries:
            if tool_calls >= self.max_tool_calls:
                break
            hits = _lexical_retrieve(self._chunks, q, k=self.k)
            tool_calls += 1
            for h in hits:
                if h["id"] not in seen_ids:
                    seen_ids.add(h["id"])
                    collected.append(h)
        ctx, ids = _format_chunks(collected, budget=self.budget)
        final_q = (
            f"{hq}\n\n"
            "Write a structured plan. Use only the context. Cite chunk ids. "
            "If offering an optional digression, label it **Side path:**. "
            "End with gaps and next questions."
        )
        ans = self.generate(final_q, ctx)
        tool_calls += 1
        return ArmResult(
            answer=ans,
            sources=ids,
            context_chars=len(ctx),
            tool_calls=tool_calls,
            meta={"queries": queries},
        )


class CeRetrieveOnlyArm(Arm):
    name = "ce_retrieve_only"

    def __init__(self, workspace: Path, generate: GenerateFn, *, k: int = 6):
        self.workspace = Path(workspace)
        self.generate = generate
        self.k = k

    def respond(self, user_message: str, history: list[dict[str, str]]) -> ArmResult:
        if R is None:
            return ArmResult(answer="", error="bench.retrievers unavailable")
        try:
            # type-aware wiki retrieve (needle demotion) — one-shot
            ctx, srcs = R.retrieve_wiki_type_aware(self.workspace, user_message, k=self.k)
        except Exception as e:  # noqa: BLE001
            return ArmResult(answer="", error=f"{type(e).__name__}: {e}")
        ans = self.generate(_with_history(user_message, history), ctx or "")
        return ArmResult(
            answer=ans,
            sources=list(srcs or []),
            context_chars=len(ctx or ""),
            tool_calls=1,
        )


class CeQueryArm(Arm):
    """Bench retrieval behind the same orchestrator as the production arm."""

    name = "ce_query"

    def __init__(
        self,
        workspace: Path,
        generate: GenerateFn,
        *,
        max_tool_calls: int = 8,
        k: int = 6,
    ):
        from bench.agentic_query_bench.query_orchestrator import (
            QueryOrchestrator,
            SimulatedCeBackend,
        )

        self.orchestrator = QueryOrchestrator(
            SimulatedCeBackend(Path(workspace)),
            generate,
            max_tool_calls=max_tool_calls,
            k=k,
        )

    def respond(self, user_message: str, history: list[dict[str, str]]) -> ArmResult:
        hq = _with_history(user_message, history)
        try:
            answer, sources, context_chars, calls, meta = self.orchestrator.respond(
                hq,
                intent=getattr(self, "expected_intent", "compose_analysis"),
            )
        except Exception as e:  # noqa: BLE001
            return ArmResult(answer="", error=f"{type(e).__name__}: {e}")
        return ArmResult(
            answer=answer,
            sources=sources,
            context_chars=context_chars,
            tool_calls=calls,
            meta={**meta, "propose_only": True, "impl": "ce_query_sim_v2"},
        )

    def close(self) -> None:
        self.orchestrator.close()


class CeQueryRealArm(CeQueryArm):
    """Installed CE router + graph retrieval, isolated inside bench code."""

    name = "ce_query_real"

    def __init__(
        self,
        workspace: Path,
        generate: GenerateFn,
        *,
        max_tool_calls: int = 8,
        k: int = 6,
        scripts_dir: Path | None = None,
    ):
        from bench.agentic_query_bench.query_orchestrator import (
            ProductionCeBackend,
            QueryOrchestrator,
        )

        self.orchestrator = QueryOrchestrator(
            ProductionCeBackend(Path(workspace), scripts_dir=scripts_dir),
            generate,
            max_tool_calls=max_tool_calls,
            k=k,
        )

    def respond(self, user_message: str, history: list[dict[str, str]]) -> ArmResult:
        result = super().respond(user_message, history)
        if not result.error:
            result.meta["impl"] = "ce_query_real_bench_v1"
        return result


class RagGraphStubArm(Arm):
    """Optional HippoRAG-class placeholder — fails soft until wired."""

    name = "rag_graph"

    def respond(self, user_message: str, history: list[dict[str, str]]) -> ArmResult:
        return ArmResult(
            answer="",
            error="rag_graph not configured (optional HippoRAG-class arm)",
        )


def build_arm(
    name: str,
    workspace: Path,
    generate: GenerateFn,
    *,
    max_tool_calls: int = 8,
    ce_scripts_dir: Path | None = None,
) -> Arm:
    n = name.strip().lower().replace("-", "_")
    if n in ("closed_book", "closedbook"):
        return ClosedBookArm(generate)
    if n in ("rag_std", "ragstd", "rag"):
        return RagStdArm(workspace, generate)
    if n in ("rag_wiki_text", "rag_wiki"):
        return RagWikiTextArm(workspace, generate)
    if n in ("long_ctx", "longctx"):
        return LongCtxArm(workspace, generate)
    if n in ("agentic_plain", "agenticplain"):
        return AgenticPlainArm(workspace, generate, max_tool_calls=max_tool_calls)
    if n in ("ce_retrieve_only", "ce_retrieve"):
        return CeRetrieveOnlyArm(workspace, generate)
    if n in ("ce_query", "ce"):
        return CeQueryArm(workspace, generate, max_tool_calls=max_tool_calls)
    if n in ("ce_query_real", "ce_real"):
        return CeQueryRealArm(
            workspace,
            generate,
            max_tool_calls=max_tool_calls,
            scripts_dir=ce_scripts_dir,
        )
    if n in ("rag_graph", "hipporag"):
        return RagGraphStubArm()
    raise KeyError(f"unknown arm: {name}")


def blind_code(arm_name: str, salt: str = "aqb-v1") -> str:
    h = hashlib.sha256(f"{salt}:{arm_name}".encode()).hexdigest()[:10]
    return f"blind-{h}"
