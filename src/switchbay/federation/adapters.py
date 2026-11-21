"""Broker adapters for external sources.

The tool names below are the documented ones for Work IQ and Databricks
Genie. AWS Context's agentic-search schema is not public, and AWS Quick
does not publish a local graph protocol: its knowledge graph stays in
the AWS Quick account, and the desktop app is a client of that account.
Those two adapters speak the shape described in the vendor's own
pages and are exercised with fakes. Calling the real services is
pending: there are no accounts here, and Genie usage is billed.

None of these functions open a network connection by themselves. The
broker passes a transport.
"""

from __future__ import annotations

from typing import Any, Protocol


class Transport(Protocol):
    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        ...


class FakeTransport:
    """In-memory stand-in. Tests load ``responses`` keyed by tool name."""

    def __init__(self, responses: dict[str, dict[str, Any]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, dict]] = []

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, arguments))
        if tool not in self.responses:
            return {"error": f"no fake response for {tool}", "policy_outcome": "denied"}
        return dict(self.responses[tool])


class HttpMcpTransport:
    """Streamable-HTTP MCP tools/call. Not used by tests."""

    def __init__(self, url: str, token: str = "") -> None:
        self.url = url
        self.token = token

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        import json
        import urllib.request
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.url, data=payload, headers=headers, method="POST")
        # Real services are not called from tests. A 4 second cap matches
        # the live-graph client; this is not a retry.
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return unwrap_mcp(data)


def unwrap_mcp(data: dict) -> dict:
    """Tool payload from either a raw dict or a JSON-RPC ``tools/call`` result."""
    import json
    if not isinstance(data, dict):
        return {"text": str(data)}
    result = data.get("result") if "result" in data and "jsonrpc" in data else data
    if not isinstance(result, dict):
        return {"text": str(result)}
    content = result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        text = first.get("text") if isinstance(first, dict) else None
        if isinstance(text, str) and text.strip():
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
            if isinstance(parsed, dict):
                return parsed
            return {"text": text}
    return result


# Real-service testing pending: Work IQ needs an M365 tenant and admin
# consent. Read tools only unless policy enables act tools.
WORKIQ_READ = ("fetch", "retrieve", "ask", "get_schema", "search_paths")
WORKIQ_ACT = ("create_entity", "update_entity", "delete_entity", "do_action", "call_function")

# Real-service testing pending: Genie is billed. Do not point this at
# a live workspace without an explicit account.
GENIE_READ = ("genie_ask", "genie_poll_response", "genie_get_query_result")

# Real-service testing pending: the public agentic-search schema was
# not available. ``agentic_search`` is the documented capability name.
AWS_CONTEXT_READ = ("agentic_search",)

# Real-service testing pending: no local Quick graph endpoint was found.
# ``search_entities`` matches the documented entity graph (people,
# projects, documents, and the edges between them). Quick itself stores
# that graph in the AWS Quick account, not on disk.
QUICK_READ = ("search_entities", "get_entity")

# Unity Catalog over the same HTTP MCP transport. ``get_permissions``
# returns the privileges on one securable. There is no local catalog.
UNITY_READ = ("get_permissions",)


def tools_for(kind: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if kind == "workiq":
        return WORKIQ_READ, WORKIQ_ACT
    if kind == "databricks-genie":
        return GENIE_READ, ()
    if kind == "aws-context":
        return AWS_CONTEXT_READ, ()
    if kind == "aws-quick":
        return QUICK_READ, ()
    if kind == "unity-catalog":
        return UNITY_READ, ()
    return (), ()


def access_arguments(kind: str, source_ref: str, *, write: bool) -> tuple[str, dict]:
    """Tool name and arguments for an on-behalf-of access check."""
    intent = "write" if write else "read"
    if kind == "workiq":
        return "fetch", {"source_ref": source_ref, "intent": intent}
    if kind == "unity-catalog":
        return "get_permissions", {"securable": source_ref, "intent": intent}
    return "check_access", {"source_ref": source_ref, "intent": intent}


def default_classification(kind: str) -> str:
    if kind in ("workiq", "databricks-genie", "aws-context", "aws-quick"):
        return "confidential"
    return "internal"


def inherited_label(source_label: str, result: dict) -> str:
    """Use the source's own label. A sensitivity tag can only raise it.

    An empty result means the source did not classify the item. The
    caller sends that item to review instead of inventing a label.
    """
    explicit = str(result.get("classification") or "").strip().lower()
    base = explicit if explicit in ("public", "internal", "confidential", "restricted") else ""
    if not base:
        base = (source_label or "").strip().lower()
        if base not in ("public", "internal", "confidential", "restricted"):
            base = ""
    labels = result.get("labels") or result.get("sensitivity") or []
    if isinstance(labels, str):
        labels = [labels]
    text = " ".join(str(item).lower() for item in labels)
    if any(word in text for word in ("restricted", "highly confidential")):
        return "restricted"
    if "confidential" in text or "secret" in text:
        if not base or _rank(base) <= _rank("confidential"):
            return "confidential"
    return base


def _rank(label: str) -> int:
    return {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}.get(label, 3)


def normalise(kind: str, tool: str, result: dict) -> dict:
    """A common shape on top of whatever the source returned."""
    if result.get("policy_outcome") == "denied" or result.get("error") == "policy_denied":
        return {
            "policy_outcome": "denied",
            "message": result.get("message") or "the source policy blocked this read",
            "deep_links": [],
            "rows": [],
            "text": "",
        }
    deep = result.get("deep_links") or result.get("links") or []
    rows = result.get("rows") or result.get("entities") or result.get("results") or []
    text = result.get("text") or result.get("answer") or ""
    if kind == "aws-context" and isinstance(rows, list):
        # Candidates only. Curation, not this adapter, creates wiki pages.
        text = text or "AWS Context returned graph candidates."
    return {
        "policy_outcome": result.get("policy_outcome") or "allowed",
        "message": result.get("message") or "",
        "deep_links": list(deep) if isinstance(deep, list) else [],
        "rows": list(rows) if isinstance(rows, list) else [],
        "text": str(text),
        "tool": tool,
    }
