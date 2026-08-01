"""Minimal stdio MCP server exposing `rag_search` over the frozen modern-RAG
index — the agentic-RAG arm's single tool.

Mirrors ``switchbay.mcp_server``'s just-enough JSON-RPC-over-stdio protocol
(initialize / notifications/initialized / tools/list / tools/call). The index is
loaded ONCE at startup (kept warm for the whole trajectory) so per-call latency
is a query embed + optional rerank, not a full index rebuild.

Config via env (baked into the --mcp-config the runner writes):
  RAG_INDEX_DIR            path to the frozen index dir (required)
  RAG_MODE                 lexical | dense | hybrid   (default hybrid)
  RAG_RERANK               "1"/"true" to cross-encoder rerank (default off)
  RAG_NO_ANSWER_THRESHOLD  abstention cutoff on top dense cosine (default 0)

Runs under the switchbay venv python (numpy + fastembed available); stdout is the
JSON-RPC channel, logs go to stderr.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "rag"
SERVER_VERSION = "0.1.0"

log = logging.getLogger("rag_mcp")

_TOOL = {
    "name": "rag_search",
    "description": (
        "Retrieve supporting passages from the raw source corpus. Returns cited "
        "spans tagged (vault:path:start-end). Issue several searches with reworded "
        "queries. If it abstains, the corpus does not cover the request."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "search query"}},
        "required": ["query"],
    },
}


def _send(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _ok(msg_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _err(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _load_index():
    from bench.agentic_query_bench.rag_modern import ModernRagIndex

    index_dir = os.environ.get("RAG_INDEX_DIR", "")
    if not index_dir:
        raise RuntimeError("RAG_INDEX_DIR not set")
    return ModernRagIndex.load(index_dir)


def _call(index, args: dict[str, Any]) -> dict[str, Any]:
    from bench.agentic_query_bench.rag_modern import rag_search

    query = str((args or {}).get("query") or "").strip()
    if not query:
        return {"content": [{"type": "text", "text": "empty query"}], "isError": True}
    mode = os.environ.get("RAG_MODE", "hybrid")
    rerank = os.environ.get("RAG_RERANK", "").lower() in {"1", "true", "yes"}
    thresh = float(os.environ.get("RAG_NO_ANSWER_THRESHOLD", "0") or 0)
    res = rag_search(index, query, mode=mode, rerank=rerank, no_answer_threshold=thresh)
    payload = {
        "query": res.query,
        "abstained": res.abstained,
        "context": res.context,
        "sources": res.sources,
    }
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}], "isError": False}


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s rag_mcp %(levelname)s %(message)s")
    try:
        index = _load_index()
    except Exception as e:  # noqa: BLE001
        log.error("failed to load index: %s", e)
        return 2
    log.info("rag mcp up: %d chunks", len(index.chunks))

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            log.warning("malformed JSON: %s", line[:200])
            continue
        method = msg.get("method")
        msg_id = msg.get("id")
        if method == "initialize":
            _send(_ok(msg_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }))
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            _send(_ok(msg_id, {"tools": [_TOOL]}))
        elif method == "tools/call":
            params = msg.get("params") or {}
            if str(params.get("name") or "") != "rag_search":
                _send(_ok(msg_id, {"content": [{"type": "text", "text": "unknown tool"}], "isError": True}))
                continue
            try:
                _send(_ok(msg_id, _call(index, params.get("arguments") or {})))
            except Exception as e:  # noqa: BLE001
                log.exception("rag_search crashed")
                _send(_ok(msg_id, {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}))
        elif msg_id is not None:
            _send(_err(msg_id, -32601, f"method not found: {method}"))
    log.info("rag mcp: stdin closed; exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
