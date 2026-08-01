"""Shared QUERY orchestration with swappable retrieval backends.

The real and simulated CE arms deliberately share this module.  Only the
retrieval backend changes, which makes a real-vs-sim comparison interpretable.
The production backend invokes an installed curiosity-engine copy against an
isolated workspace snapshot; it never imports or edits the CE repository.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

try:
    from bench import retrievers as R
except Exception:  # noqa: BLE001
    R = None  # type: ignore

GenerateFn = Callable[[str, str], str]


@dataclass
class Retrieval:
    context: str
    sources: list[str]
    calls: int = 1
    trace: dict[str, Any] = field(default_factory=dict)


class QueryBackend(Protocol):
    backend_id: str
    corpus_hash: str

    def retrieve(self, query: str, *, k: int) -> Retrieval:
        ...

    def close(self) -> None:
        ...


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if (
            rel.startswith(".git/")
            or "__pycache__" in path.parts
            or path.suffix == ".pyc"
        ):
            continue
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _script_hashes(scripts_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in ("graph.py", "query_router.py", "entity_gate.py", "vault_search.py"):
        path = scripts_dir / name
        if path.is_file():
            out[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


class SimulatedCeBackend:
    backend_id = "bench_sim_v2"

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.corpus_hash = _tree_hash(self.workspace)

    def retrieve(self, query: str, *, k: int) -> Retrieval:
        if R is None:
            raise RuntimeError("bench.retrievers unavailable")
        try:
            context, sources = R.retrieve_two_stage(self.workspace, query, k=k)
            method = "retrieve_two_stage"
        except Exception:  # noqa: BLE001
            context, sources = R.retrieve_wiki_type_aware(self.workspace, query, k=k)
            method = "retrieve_wiki_type_aware"
        return Retrieval(
            context=context or "",
            sources=list(sources or []),
            trace={"method": method, "query": query},
        )

    def close(self) -> None:
        return None


class ProductionCeBackend:
    """Read-only adapter around installed CE scripts on an isolated copy."""

    backend_id = "curiosity_engine_cli_v1"

    def __init__(
        self,
        workspace: Path,
        *,
        scripts_dir: Path | None = None,
        timeout_s: int = 180,
    ):
        configured = os.environ.get("CURIOSITY_ENGINE_SCRIPTS_DIR")
        self.scripts_dir = Path(
            scripts_dir
            or configured
            or Path.home() / ".agents/skills/curiosity-engine/scripts"
        ).expanduser().resolve()
        required = [self.scripts_dir / "graph.py", self.scripts_dir / "query_router.py"]
        missing = [str(p) for p in required if not p.is_file()]
        if missing:
            raise FileNotFoundError(f"missing CE scripts: {missing}")
        self.script_hashes = _script_hashes(self.scripts_dir)
        self.timeout_s = timeout_s
        self._tmp = tempfile.TemporaryDirectory(prefix="real-ce-query-")
        self.workspace = Path(self._tmp.name) / "workspace"
        shutil.copytree(
            Path(workspace).expanduser().resolve(),
            self.workspace,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        )
        self.initial_workspace_hash = _tree_hash(self.workspace)
        self.corpus_hash = self.initial_workspace_hash
        self.trace: list[dict[str, Any]] = []

    def _run_json(self, script: str, args: list[str]) -> dict[str, Any]:
        before = _tree_hash(self.workspace)
        script_path = self.scripts_dir / script
        command = ["uv", "run", "python3", str(script_path), *args]
        proc = subprocess.run(
            command,
            cwd=self.workspace,
            text=True,
            capture_output=True,
            timeout=self.timeout_s,
            check=False,
        )
        after = _tree_hash(self.workspace)
        entry = {
            "command": command[3:],
            "returncode": proc.returncode,
            "stdout_sha256": hashlib.sha256(proc.stdout.encode()).hexdigest(),
            "stderr": proc.stderr[-2000:],
            "workspace_hash_before": before,
            "workspace_hash_after": after,
        }
        self.trace.append(entry)
        if before != after:
            raise RuntimeError(
                f"CE command mutated isolated workspace: {script} "
                f"{before[:12]} -> {after[:12]}"
            )
        if proc.returncode != 0:
            raise RuntimeError(
                f"CE command failed ({proc.returncode}): {script}: {proc.stderr[-1000:]}"
            )
        try:
            value = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"CE command returned non-JSON: {script}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"CE command returned unexpected JSON: {script}")
        return value

    def _assemble_context(self, result: dict[str, Any], budget: int = 7000) -> tuple[str, list[str]]:
        parts: list[str] = []
        sources: list[str] = []
        remaining = budget
        gate = result.get("entity_gate") or {}
        if result.get("abstain"):
            directive = str(gate.get("directive") or result.get("note") or "")
            return f"ENTITY GATE: ABSTAIN\n{directive}", []

        for page in result.get("pages") or []:
            rel = str(page.get("page") or "")
            if not rel:
                continue
            path = self.workspace / "wiki" / rel
            if not path.is_file() and rel.startswith("wiki/"):
                path = self.workspace / rel
            if not path.is_file():
                continue
            body = path.read_text(encoding="utf-8", errors="replace")
            block = f"### wiki/{rel.removeprefix('wiki/')}\n{body}\n"
            block = block[:remaining]
            parts.append(block)
            sources.append(f"wiki/{rel.removeprefix('wiki/')}")
            remaining -= len(block)
            if remaining <= 0:
                break

        # Graph retrieval already ranks wiki first. Fill remaining budget with
        # vault records, preserving the production 2:1 wiki/vault preference.
        vault_budget = min(remaining, budget // 3)
        for item in result.get("vault") or []:
            if vault_budget <= 0:
                break
            rel = str(
                item.get("path")
                or item.get("source")
                or item.get("file")
                or item.get("id")
                or ""
            )
            text = str(
                item.get("text")
                or item.get("body")
                or item.get("snippet")
                or item.get("content")
                or ""
            )
            candidate = self.workspace / rel
            if not text and rel and candidate.is_file():
                text = candidate.read_text(encoding="utf-8", errors="replace")
            if not text:
                continue
            block = f"### {rel or 'vault-result'}\n{text}\n"[:vault_budget]
            parts.append(block)
            if rel:
                sources.append(rel)
            vault_budget -= len(block)
        return "\n".join(parts), sources

    def retrieve(self, query: str, *, k: int) -> Retrieval:
        classified = self._run_json(
            "query_router.py", ["classify", query, "--wiki", "wiki"]
        )
        result = self._run_json(
            "graph.py",
            [
                "retrieve",
                "wiki",
                query,
                "--seeds",
                "5",
                "--limit",
                str(k),
                "--hops",
                "2",
                "--route",
                "auto",
                "--vault-k",
                "4",
            ],
        )
        context, sources = self._assemble_context(result)
        return Retrieval(
            context=context,
            sources=sources,
            calls=2,
            trace={
                "query": query,
                "classifier": classified,
                "retrieve": result,
                "commands": self.trace[-2:],
                "script_hashes": self.script_hashes,
                "snapshot_initial_hash": self.initial_workspace_hash,
            },
        )

    def close(self) -> None:
        self._tmp.cleanup()


class QueryOrchestrator:
    """One propose-only QUERY policy shared by both CE backends."""

    def __init__(
        self,
        backend: QueryBackend,
        generate: GenerateFn,
        *,
        max_tool_calls: int = 8,
        k: int = 6,
        context_budget: int = 7000,
    ):
        self.backend = backend
        self.generate = generate
        self.max_tool_calls = max_tool_calls
        self.k = k
        self.context_budget = context_budget

    def respond(
        self,
        question: str,
        *,
        intent: str = "compose_analysis",
    ) -> tuple[str, list[str], int, int, dict[str, Any]]:
        policy = {
            "needle": "N",
            "locate": "L",
            "compare": "C",
            "matched_analysis": "M",
            "compose_analysis": "S",
            "explore": "X",
        }.get(intent, "S")
        calls = 0
        retrievals: list[Retrieval] = []
        primary = self.backend.retrieve(question, k=self.k)
        retrievals.append(primary)
        calls += primary.calls

        if primary.context.startswith("ENTITY GATE: ABSTAIN"):
            directive = primary.context.partition("\n")[2].strip()
            answer = directive or "This topic or entity is absent from the workspace."
            return answer, [], len(primary.context), calls, {
                "orchestrator": "shared_query_v1",
                "backend": self.backend.backend_id,
                "corpus_hash": self.backend.corpus_hash,
                "expected_intent": intent,
                "intent_policy": policy,
                "entity_gate_abstain": True,
                "subqueries": [],
                "retrieval_trace": [primary.trace],
            }

        plan = ""
        if policy not in {"N", "L"}:
            plan = self.generate(
                "Emit up to 2 short search queries, one per line, needed to "
                "answer the request through multi-hop corpus synthesis. For "
                "matched analysis, include a source-verification query. "
                "Queries only.",
                question,
            )
            calls += 1
        subqueries: list[str] = []
        for line in plan.splitlines():
            query = line.strip().lstrip("-*0123456789. ")
            if len(query) < 4 or query in subqueries:
                continue
            # Reserve one call for final generation. Production retrieval uses
            # classify+retrieve; simulated retrieval reports its actual cost.
            expected = 2 if self.backend.backend_id == "curiosity_engine_cli_v1" else 1
            if calls + expected >= self.max_tool_calls:
                break
            subqueries.append(query)
            hit = self.backend.retrieve(query, k=max(3, self.k // 2))
            retrievals.append(hit)
            calls += hit.calls
            max_subqueries = 1 if policy in {"C", "M"} else 2
            if len(subqueries) >= max_subqueries:
                break

        contexts: list[str] = []
        remaining = self.context_budget
        sources: list[str] = []
        for hit in retrievals:
            piece = hit.context[:remaining]
            contexts.append(piece)
            remaining -= len(piece)
            sources.extend(hit.sources)
            if remaining <= 0:
                break
        context = "\n\n".join(contexts)
        final_prompt = (
            f"{question}\n\n"
            "Operate in propose-only QUERY mode. Use only retrieved context for "
            "corpus claims. If the entity gate says ABSTAIN, report that the "
            "topic/entity is absent and do not substitute nearby material. "
            "Return a structured plan, supported claims with exact citations, "
            "explicit gaps, next questions, and only card-relevant optional "
            "directions labeled **Side path:**. Include a fenced ```proposal "
            "draft analysis body; do not write to the workspace."
        )
        answer = self.generate(final_prompt, context)
        calls += 1
        unique_sources = list(dict.fromkeys(sources))
        meta = {
            "orchestrator": "shared_query_v1",
            "backend": self.backend.backend_id,
            "corpus_hash": self.backend.corpus_hash,
            "expected_intent": intent,
            "intent_policy": policy,
            "subqueries": subqueries,
            "retrieval_trace": [r.trace for r in retrievals],
        }
        return answer, unique_sources, len(context), calls, meta

    def close(self) -> None:
        self.backend.close()
