"""Tool-result size caps and wiki citation extraction.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from typing import Any
import json
from switchbay import skillkit
from switchbay import tools

from switchbay.httpapi._ns import _daemon_ns

def _cap_tool_output(name: str, output: Any, *, local: bool = False) -> Any:
    """Bound a tool result before it re-enters the agent message list.

    Local models get a tighter cap. `load_skill` of a huge skill
    becomes a frontmatter peek + section hint (progressive load).
    Wiki reads keep ``page`` / ``title`` / ``wikilink`` and clip
    ``content`` in place — smashing the JSON into a preview string
    made a 4B summarise a stub and drop the clickable cite.
    """
    cap = _daemon_ns._LOCAL_TOOL_RESULT_CAP if local else _daemon_ns._TOOL_RESULT_CAP
    if isinstance(output, dict) and name == "read_wiki_page" and "content" in output:
        return _cap_wiki_page_output(output, cap)
    if isinstance(output, dict) and name == "search_wiki":
        return _cap_wiki_search_output(output, cap)
    try:
        s = output if isinstance(output, str) else json.dumps(output)
    except (TypeError, ValueError):
        return output
    if len(s) <= cap:
        return output
    if name == "load_skill":
        peek: dict[str, Any] = {}
        if isinstance(output, dict) and isinstance(output.get("skill"), dict):
            peek = skillkit.peek_from_payload(output["skill"])
        return {
            "ok": True,
            "truncated": True,
            "skill": peek,
            "note": (
                "Skill body exceeds this context window. Use covered_by "
                "tools, or load_skill with detail='frontmatter' then "
                "section='Heading' (progressive). Not a ban on skills."
            ),
        }
    return {
        "ok": True, "truncated": True,
        "preview": s[:cap] + " …[truncated for context]",
    }

def _cap_wiki_page_output(output: dict[str, Any], cap: int) -> dict[str, Any]:
    out = dict(output)
    page = str(out.get("page") or "")
    if page and not out.get("wikilink"):
        cite = tools.wiki_cite_target(page)
        if cite:
            out["wikilink"] = f"[[{cite}]]"
    body = str(out.get("content") or "")
    body_cap = max(1200, cap)
    if len(body) > body_cap:
        out["content"] = body[:body_cap] + " …[truncated for context]"
        out["truncated"] = True
    return out

def _cap_wiki_search_output(output: dict[str, Any], cap: int) -> dict[str, Any]:
    try:
        blob = json.dumps(output)
    except (TypeError, ValueError):
        return output
    if len(blob) <= cap:
        return output
    hits = [
        dict(h) for h in (output.get("results") or []) if isinstance(h, dict)
    ]
    for h in hits:
        page = str(h.get("page") or "")
        if page and not h.get("wikilink"):
            cite = tools.wiki_cite_target(page)
            if cite:
                h["wikilink"] = f"[[{cite}]]"
        snip = str(h.get("snippet") or "")
        if len(snip) > 120:
            h["snippet"] = snip[:120] + "…"
    kept = hits
    while kept and len(json.dumps({"results": kept})) > cap:
        kept = kept[:-1]
    out = dict(output)
    out["results"] = kept
    out["truncated"] = True
    return out

def _wiki_cites_from_tool(name: str, output: Any) -> list[str]:
    """[[wikilink]] strings the rail can turn into clicks."""
    if not isinstance(output, dict):
        return []
    links: list[str] = []
    if name == "read_wiki_page":
        raw = output.get("wikilink") or tools.wiki_cite_target(
            str(output.get("page") or ""),
        )
        if raw:
            links.append(str(raw))
    elif name == "search_wiki":
        for hit in (output.get("results") or [])[:3]:
            if not isinstance(hit, dict):
                continue
            raw = hit.get("wikilink") or tools.wiki_cite_target(
                str(hit.get("page") or ""),
            )
            if raw:
                links.append(str(raw))
    out: list[str] = []
    for raw in links:
        link = str(raw).strip()
        if not link:
            continue
        if not link.startswith("[["):
            link = f"[[{link}]]"
        if link not in out:
            out.append(link)
    return out

def _with_wiki_cites(text: str, cites: list[str]) -> str:
    """Append clickable [[wikilinks]] when the model forgot to cite."""
    if not cites or "[[" in (text or ""):
        return text
    extra = " ".join(cites[:3])
    return f"{text.rstrip()}\n\n{extra}" if (text or "").strip() else extra

def _cap_local_tool_output(name: str, output: Any) -> Any:
    return _cap_tool_output(name, output, local=True)
