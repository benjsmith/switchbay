"""Per-arm snapshot provisioning for the CE QUERY product pilot.

Each trajectory runs in a FRESH disposable snapshot of the frozen workspace.
The workspace is ~3.8 GB (the ``.curator`` graph + wiki/vault indexes CE needs
to function), so per-trajectory ``shutil.copytree`` is impractical. On APFS we
use copy-on-write clones (``cp -cR`` → ``clonefile``): near-instant, space-cheap,
and independent (a mutation in the clone does not touch the source). Non-APFS
falls back to copytree.

Arms:
  ce_product_e2e_v1     — clone + install the exact CE skill tree at
                          ``.claude/skills/curiosity-engine`` (hash-recorded).
  tool_matched_no_skill_v1 — clone + strip skill + neutral map + hash-verified
                          ``.bench-tools/ce-read`` copies (baseline_provision).
  rag_modern_agentic_v1 — clone (vault only matters) + install the frozen
                          modern-RAG index + a ``rag_search`` read-only tool +
                          a raw-vault neutral map; NO CE skill/wiki/graph.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


def force_rmtree(path: Path) -> None:
    """Remove a tree even when it contains read-only files/dirs (CE's `uv run`
    cache under .curator/uv-cache/ is read-only, which defeats plain rmtree and
    leaves partial trees that break the next clone). chmod-on-error, then a
    hard `chmod -R u+rwx` + `rm -rf` fallback for anything stubborn."""
    path = Path(path)
    if not path.exists():
        return

    def _onexc(func, p, _exc):
        try:
            os.chmod(p, stat.S_IRWXU)
            parent = os.path.dirname(p)
            if parent:
                os.chmod(parent, stat.S_IRWXU)
            func(p)
        except Exception:  # noqa: BLE001
            pass

    try:
        shutil.rmtree(path, onexc=_onexc)          # Python 3.12+
    except TypeError:
        shutil.rmtree(path, onerror=lambda f, p, e: _onexc(f, p, e))
    except Exception:  # noqa: BLE001
        pass
    if path.exists():
        subprocess.run(["chmod", "-R", "u+rwx", str(path)], capture_output=True)
        subprocess.run(["rm", "-rf", str(path)], capture_output=True)

from bench.agentic_query_bench import baseline_provision as BP

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]  # bench/agentic_query_bench -> repo root
CE_SKILL_REL = ".claude/skills/curiosity-engine"
RAG_TOOL_REL = ".bench-tools/rag"
RAG_MCP_CONFIG_REL = ".bench-tools/rag/mcp-config.json"


def product_skill_dir() -> Path:
    """Resolve the installed curiosity-engine skill root (contains scripts/)."""
    env = os.environ.get("CURIOSITY_ENGINE_SKILL_DIR")
    if env:
        return Path(env).expanduser().resolve()
    for cand in (
        Path.home() / ".agents/skills/curiosity-engine",
        Path.home() / ".claude/skills/curiosity-engine",
    ):
        if (cand / "scripts").is_dir():
            return cand.resolve()
    raise FileNotFoundError("curiosity-engine skill dir not found")


def product_scripts_dir() -> Path:
    return product_skill_dir() / "scripts"


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(x for x in Path(root).rglob("*") if x.is_file()):
        parts = p.relative_to(root).parts
        if ".git" in parts or "__pycache__" in parts or p.suffix == ".pyc":
            continue
        h.update(p.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def clone_snapshot(src: Path, dest: Path) -> Path:
    """APFS copy-on-write clone (near-instant); fallback to copytree."""
    src = Path(src).expanduser().resolve()
    dest = Path(dest).expanduser().resolve()
    force_rmtree(dest)  # robust: prior snapshot may hold read-only uv-cache files
    dest.parent.mkdir(parents=True, exist_ok=True)
    # `cp -cR` uses clonefile on APFS. -c fails on non-APFS; fall back.
    try:
        subprocess.run(["cp", "-cR", str(src), str(dest)], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    return dest


def install_ce_skill(snapshot: Path, *, skill_dir: Path | None = None) -> dict[str, Any]:
    """Copy the exact CE skill tree into the snapshot; record a manifest hash."""
    skill_dir = Path(skill_dir) if skill_dir else product_skill_dir()
    dest = Path(snapshot) / CE_SKILL_REL
    force_rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill_dir, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    installed = _tree_hash(dest)
    source = _tree_hash(skill_dir)
    return {
        "skill_dir_source": str(skill_dir),
        "installed_at": str(dest),
        "source_hash": source,
        "installed_hash": installed,
        "match": installed == source,
    }


# The chosen mode/rerank/threshold are baked in at provision time. The script
# needs the switchbay project env (numpy + fastembed + the bench package) on
# sys.path — supplied via AQB_REPO/AQB_SRC in the session env (live-integration
# detail; the deterministic index/search logic itself is fully tested).
RAG_SEARCH_SCRIPT = '''\
#!/usr/bin/env python3
"""Read-only rag_search over the frozen modern-RAG index. Prints JSON."""
import json, os, sys
from pathlib import Path
for var in ("AQB_REPO", "AQB_SRC"):
    p = os.environ.get(var)
    if p:
        sys.path.insert(0, p)
from bench.agentic_query_bench.rag_modern import ModernRagIndex, rag_search  # noqa: E402

INDEX_DIR = Path(__file__).resolve().parent / "index"
THRESH = __THRESHOLD__
MODE = "__MODE__"
RERANK = __RERANK__

def main():
    q = " ".join(sys.argv[1:]).strip()
    if not q:
        print(json.dumps({"error": "empty query"})); return
    idx = ModernRagIndex.load(INDEX_DIR)
    res = rag_search(idx, q, mode=MODE, rerank=RERANK, no_answer_threshold=THRESH)
    print(json.dumps({
        "query": res.query, "abstained": res.abstained,
        "context": res.context, "sources": res.sources,
    }, indent=2))

if __name__ == "__main__":
    main()
'''

RAG_NEUTRAL_MAP = """\
# Raw-vault RAG workspace

You are answering knowledge-work requests from a corpus of raw source documents.
You have exactly one retrieval tool and no wiki, graph, or knowledge pages.

Retrieve supporting passages by calling the **rag_search** tool (from the `rag`
MCP server) with a `query` argument. It returns JSON with `context` (cited
passages, each tagged `(vault:path:start-end)`) and `sources`. Issue several
searches with reworded queries when useful. Answer only from retrieved context;
cite the exact `(vault:...)` locators. If retrieval returns no sufficiently
relevant source (`abstained`), say the corpus does not cover the request rather
than inventing content. Do not edit or create files.
"""


def build_rag_mcp_config(
    snapshot: Path,
    *,
    index_dir: Path,
    mode: str,
    rerank: bool,
    no_answer_threshold: float,
    python_bin: str | None = None,
) -> Path:
    """Write the --mcp-config that spawns the rag_search stdio MCP server.

    Uses the switchbay venv python (numpy + fastembed available) with
    PYTHONPATH at the repo root so it imports `bench.agentic_query_bench`.
    The frozen index + retrieval config ride in the server's env.
    """
    spec = {
        "mcpServers": {
            "rag": {
                "command": python_bin or sys.executable,
                "args": ["-m", "bench.agentic_query_bench.rag_mcp_server"],
                "env": {
                    "PYTHONPATH": str(REPO_ROOT),
                    "PATH": os.environ.get("PATH", ""),
                    "RAG_INDEX_DIR": str(Path(index_dir).resolve()),
                    "RAG_MODE": str(mode),
                    "RAG_RERANK": "1" if rerank else "0",
                    "RAG_NO_ANSWER_THRESHOLD": repr(float(no_answer_threshold)),
                    "FASTEMBED_CACHE_PATH": os.environ.get(
                        "FASTEMBED_CACHE_PATH", str(Path.home() / ".cache/fastembed")
                    ),
                },
            }
        }
    }
    path = Path(snapshot) / RAG_MCP_CONFIG_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return path


def install_rag_arm(
    snapshot: Path,
    *,
    frozen_index_dir: Path,
    no_answer_threshold: float,
    mode: str = "hybrid",
    rerank: bool = False,
    src_dir: Path | None = None,
) -> dict[str, Any]:
    """Install the rag_search tool + a copy of the frozen index into the snapshot,
    remove any CE skill, and write the raw-vault neutral map as CLAUDE.md."""
    snapshot = Path(snapshot)
    # Raw-vault-only isolation (prereg): the RAG arm gets no CE skill, no wiki
    # pages, and no CE graph/index. Strip them from the clone so retrieval can
    # only go through rag_search over the frozen raw-vault index. force_rmtree:
    # .curator/uv-cache holds read-only files that defeat plain rmtree.
    for rel in (CE_SKILL_REL, "wiki", ".curator"):
        force_rmtree(snapshot / rel)
    tool_dir = snapshot / RAG_TOOL_REL
    tool_dir.mkdir(parents=True, exist_ok=True)
    script = (
        RAG_SEARCH_SCRIPT
        .replace("__THRESHOLD__", repr(float(no_answer_threshold)))
        .replace("__MODE__", str(mode))
        .replace("__RERANK__", "True" if rerank else "False")
    )
    (tool_dir / "rag_search.py").write_text(script, encoding="utf-8")
    # copy the frozen index into the snapshot so the tool is self-contained
    idx_dest = tool_dir / "index"
    if idx_dest.exists():
        shutil.rmtree(idx_dest)
    shutil.copytree(frozen_index_dir, idx_dest)
    (snapshot / "CLAUDE.md").write_text(RAG_NEUTRAL_MAP, encoding="utf-8")
    mcp_config = build_rag_mcp_config(
        snapshot, index_dir=idx_dest, mode=mode, rerank=rerank,
        no_answer_threshold=no_answer_threshold,
    )
    return {
        "tool": str(tool_dir / "rag_search.py"),
        "index": str(idx_dest),
        "mcp_config": str(mcp_config),
        "no_answer_threshold": no_answer_threshold,
        "mode": mode,
        "rerank": rerank,
        "src_dir": str(Path(src_dir).resolve()) if src_dir else None,
    }


def provision_tool_matched(snapshot: Path, *, skill_dir: Path | None = None) -> Any:
    """Clone must already carry the CE skill; strip it + provision the baseline."""
    scripts = (Path(skill_dir) / "scripts") if skill_dir else product_scripts_dir()
    return BP.provision_tool_matched_snapshot(
        Path(snapshot), product_scripts_dir=scripts, skill_rel=CE_SKILL_REL
    )
