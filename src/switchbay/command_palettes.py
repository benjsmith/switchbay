"""Slash-command tool palettes for local models.

A local run that came from a slash (or an internal command like deck
populate) gets a *command* desk instead of the RAM chat/curate list.
Shipped maps cover the agent-backed slashes; user ``.md`` commands
inherit a shipped map by alias or by mentioning tool names. Workspace
overrides live in ``.workbench/state/command_palettes.json`` and are
edited from the Agent Dashboard.

The RAM rung still clips the compiled specs to ``prompt_budget``.
Command palettes may opt back in tools the default local desk bans
(decks, plots, sheets) — that is the point of a task-specific desk.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import commands, tools
from .agents.local_rungs import LocalRung
from .agents.rail_default import (
    LOCAL_SYSTEM_PROMPT,
    LOCAL_SYSTEM_PROMPT_LARGE,
    _STRONG_ONLY_TOOLS,
    clip_tools_to_budget,
    compile_tool_specs,
    prompt_token_breakdown,
)

_WIKI_READ: tuple[str, ...] = (
    "search_wiki",
    "read_wiki_page",
    "list_wiki_pages",
)

# None = use the RAM-scaled curate desk (unless the user overrode it).
SHIPPED: dict[str, tuple[str, ...] | None] = {
    "curate": None,
    "ingest": _WIKI_READ + (
        "ce_ingest",
        "ce_vault_search",
        "propose_wiki_page",
    ),
    "add-source": _WIKI_READ + (
        "ce_ingest",
        "ce_vault_search",
        "propose_wiki_page",
    ),
    "deck": _WIKI_READ + (
        "make_slides_from_doc",
        "make_slides_from_docs",
        "compose_analysis",
        "author_slide",
        "sketch_context",
        "sketch_show",
    ),
    "plot": (
        "save_plot",
        "plot_context",
        "plot_update",
        "plot_show",
        "table_context",
        "table_run_sql",
        "search_wiki",
    ),
    "lint": _WIKI_READ + (
        "ce_lint",
        "ce_epoch_summary",
        "ce_naming",
        "propose_page_edit",
    ),
    "report": _WIKI_READ + (
        "create_report",
        "wiki_neighbors",
    ),
}

ALIASES: dict[str, str] = {
    "curator": "curate",
    "drain": "ingest",
    "addsource": "add-source",
    "source-add": "add-source",
    "create-deck": "deck",
    "create_deck": "deck",
    "make-deck": "deck",
    "make-slides": "deck",
    "make_slides": "deck",
    "slides": "deck",
    "slideshow-author": "deck",
}

DESCRIPTIONS: dict[str, str] = {
    "curate": "Wiki curator — RAM-scaled tools unless you override",
    "ingest": "Drain vault/raw/ into wiki/sources/",
    "add-source": "Copy or paste into the vault, then ingest",
    "deck": "Sketch deck authoring (populate / create-deck)",
    "plot": "Vega-Lite plots (Plot-from-table, or a user command)",
    "lint": "CE lint, naming, small page edits",
    "report": "Rich HTML report (dropped on small local rungs)",
}

# Keyword → shipped palette when a user command doesn't name tools.
_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(author_slide|make_slides|excalidraw|slide deck)\b", re.I), "deck"),
    (re.compile(r"\b(slides?|deck)\b", re.I), "deck"),
    (re.compile(r"\b(save_plot|vega-?lite|histogram|scatterplot)\b", re.I), "plot"),
    (re.compile(r"\b(ce_lint|lint the wiki)\b", re.I), "lint"),
    (re.compile(r"\b(create_report|html report)\b", re.I), "report"),
    (re.compile(r"\b(vault/raw|local_ingest|ce_ingest)\b", re.I), "ingest"),
    (re.compile(r"\b(curate|curator)\b", re.I), "curate"),
)

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True)
class ResolvedPalette:
    """Tools a local run should load for one command."""

    name: str
    tools: tuple[str, ...]
    source: str  # shipped | override | inferred
    kind: str  # curate | command


def _path(workspace: Path) -> Path:
    return workspace / ".workbench" / "state" / "command_palettes.json"


def load_overrides(workspace: Path) -> dict[str, list[str]]:
    p = _path(workspace)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    raw = data.get("overrides") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, val in raw.items():
        name = canonical(str(key))
        if not name or not isinstance(val, list):
            continue
        out[name] = [str(x) for x in val]
    return out


def save_overrides(workspace: Path, overrides: dict[str, list[str]]) -> None:
    p = _path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"overrides": overrides}, indent=2) + "\n",
        encoding="utf-8",
    )


def set_override(workspace: Path, name: str, tool_names: Iterable[str]) -> list[str]:
    key = canonical(name)
    if not key or not _NAME_RE.fullmatch(key):
        raise ValueError(f"invalid command name: {name!r}")
    cleaned = list(sanitize(tool_names))
    if not cleaned:
        clear_override(workspace, key)
        return []
    ov = load_overrides(workspace)
    ov[key] = cleaned
    save_overrides(workspace, ov)
    return cleaned


def clear_override(workspace: Path, name: str) -> bool:
    key = canonical(name)
    ov = load_overrides(workspace)
    if key not in ov:
        return False
    del ov[key]
    save_overrides(workspace, ov)
    return True


def canonical(name: str | None) -> str:
    n = (name or "").strip().lower()
    if not n:
        return ""
    return ALIASES.get(n, n)


def aliases_of(name: str) -> tuple[str, ...]:
    key = canonical(name)
    return tuple(sorted(a for a, t in ALIASES.items() if t == key))


def sanitize(names: Iterable[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for raw in names:
        n = str(raw or "").strip()
        if not n or n in seen:
            continue
        if n not in tools.REGISTRY:
            continue
        seen.append(n)
    return tuple(seen)


def infer_tool_names(text: str) -> tuple[str, ...]:
    """Registry names mentioned as identifiers in a command template."""
    if not text:
        return ()
    found: list[str] = []
    for name in sorted(tools.REGISTRY, key=len, reverse=True):
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text):
            found.append(name)
    return tuple(found)


def hint_shipped(text: str) -> str | None:
    if not text:
        return None
    for pat, key in _HINTS:
        if pat.search(text):
            return key
    return None


def shipped_tools(name: str, rung: LocalRung) -> tuple[str, ...] | None:
    key = canonical(name)
    if key not in SHIPPED:
        return None
    raw = SHIPPED[key]
    if raw is None:
        return tuple(rung.curate_tools)
    return raw


def _drop_strong_if_needed(
    names: tuple[str, ...], *, rung: LocalRung, keep_strong: bool,
) -> tuple[str, ...]:
    if keep_strong or not rung.force_scaffold:
        return names
    return tuple(n for n in names if n not in _STRONG_ONLY_TOOLS)


def resolve(
    workspace: Path | None,
    command: str | None,
    *,
    rung: LocalRung,
    template: str | None = None,
) -> ResolvedPalette | None:
    """Pick the command desk, or None to keep the RAM chat/curate palette."""
    key = canonical(command)
    if not key:
        return None
    overrides = load_overrides(workspace) if workspace is not None else {}
    if key in overrides:
        names = sanitize(overrides[key])
        names = _drop_strong_if_needed(names, rung=rung, keep_strong=True)
        if not names:
            return None
        return ResolvedPalette(key, names, "override", _kind(key))

    shipped = shipped_tools(key, rung)
    if shipped is not None:
        names = sanitize(shipped)
        names = _drop_strong_if_needed(names, rung=rung, keep_strong=False)
        if not names:
            return None
        return ResolvedPalette(key, names, "shipped", _kind(key))

    inferred = infer_tool_names(template or "")
    if inferred:
        names = sanitize(inferred)
        names = _drop_strong_if_needed(names, rung=rung, keep_strong=False)
        if names:
            return ResolvedPalette(key, names, "inferred", "command")

    hinted = hint_shipped(template or "")
    if hinted:
        raw = shipped_tools(hinted, rung)
        if raw:
            names = sanitize(raw)
            names = _drop_strong_if_needed(names, rung=rung, keep_strong=False)
            if names:
                return ResolvedPalette(key, names, "inferred", _kind(hinted))
    return None


def _kind(name: str) -> str:
    return "curate" if canonical(name) == "curate" else "command"


def _system_for(rung: LocalRung) -> str:
    return LOCAL_SYSTEM_PROMPT if rung.force_scaffold else LOCAL_SYSTEM_PROMPT_LARGE


def _token_view(
    names: tuple[str, ...], rung: LocalRung,
) -> tuple[list[str], list[str], int, bool]:
    specs = compile_tool_specs(names, local=True, rung=rung, skip_strong=False)
    system = _system_for(rung)
    clipped, dropped = clip_tools_to_budget(
        system, specs, None, rung.prompt_budget,
    )
    kept = [str(s.get("name") or "") for s in clipped]
    tokens = prompt_token_breakdown(system, clipped, None)["total"]
    fits = tokens <= rung.prompt_budget
    return kept, dropped, tokens, fits


def describe_all(workspace: Path, rung: LocalRung) -> dict[str, Any]:
    """Dashboard payload: shipped + user-command palettes + tool catalog."""
    overrides = load_overrides(workspace)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for key in SHIPPED:
        seen.add(key)
        default = sanitize(shipped_tools(key, rung) or ())
        default = _drop_strong_if_needed(
            default, rung=rung, keep_strong=False,
        )
        resolved = resolve(workspace, key, rung=rung)
        tools_now = resolved.tools if resolved else default
        kept, dropped, tokens, fits = _token_view(tools_now, rung)
        rows.append({
            "name": key,
            "aliases": list(aliases_of(key)),
            "description": DESCRIPTIONS.get(key, ""),
            "source": resolved.source if resolved else "shipped",
            "kind": _kind(key),
            "scope": "shipped",
            "default_tools": list(default),
            "tools": kept,
            "overridden": key in overrides,
            "tokens": tokens,
            "clipped": dropped,
            "fits": fits,
        })

    for rec in commands.list_commands(workspace):
        name = str(rec.get("name") or "")
        key = canonical(name)
        if not key or key in seen:
            continue
        body = commands.resolve(workspace, name) or ""
        resolved = resolve(workspace, name, rung=rung, template=body)
        if resolved is None and key not in overrides:
            continue
        seen.add(key)
        tools_now = resolved.tools if resolved else ()
        kept, dropped, tokens, fits = _token_view(tools_now, rung)
        rows.append({
            "name": key,
            "aliases": list(aliases_of(key)),
            "description": rec.get("description") or f"user command ({rec.get('scope')})",
            "source": resolved.source if resolved else "override",
            "kind": "command",
            "scope": rec.get("scope") or "workspace",
            "default_tools": list(infer_tool_names(body) or (
                sanitize(shipped_tools(hint_shipped(body) or "", rung) or ())
            )),
            "tools": kept,
            "overridden": key in overrides,
            "tokens": tokens,
            "clipped": dropped,
            "fits": fits,
        })

    catalog = []
    for name in sorted(tools.REGISTRY):
        t = tools.REGISTRY[name]
        catalog.append({
            "name": name,
            "description": (t.description or "").split("\n", 1)[0][:120],
        })
    return {
        "rung": rung.to_public(),
        "commands": rows,
        "catalog": catalog,
    }
