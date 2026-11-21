"""Local-harness autotune helpers.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import asyncio
import logging
from aiohttp import web
from switchbay import conversations
from switchbay import llmgateway
from switchbay import localllm
from switchbay import protocol

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

def _strong_provider_for_autotune() -> str | None:
    """A non-local, keyed provider to critique the local model's loop.
    Registry order is subscription → BYOK → local, so this picks the
    strongest available (Claude Code, Codex, …) and never the local
    model itself."""
    for pid, mod in llmgateway.PROVIDERS.items():
        if pid in ("llamacpp", "ollama"):
            continue
        try:
            if mod.PROVIDER.get("category") == "local":
                continue
            if mod.has_key():
                return pid
        except Exception:  # noqa: BLE001
            continue
    return None

async def _autotune_local_harness(
    app: web.Application, workspace: Path, run_id: str,
) -> None:
    """The local model looped this run — ask a STRONGER provider for one
    concise rule and append it to the (local-model-only) harness so it
    does better next time. Best-effort: silent no-op if no strong
    provider is configured, and the harness is deduped + size-capped."""
    try:
        strong = _strong_provider_for_autotune()
        if not strong:
            return
        events = await asyncio.to_thread(
            conversations.list_events, workspace,
            before_id=None, limit=40, run_id=run_id,
        )
        loop = "\n".join(
            f"- {e.get('actor')}: {str(e.get('summary') or '')[:80]}"
            for e in events if e.get("kind") in ("tool_use", "tool_result")
        )[:1500]
        if not loop:
            return
        prompt = (
            "A smaller local model got stuck repeating the same tool "
            "calls instead of making progress:\n\n" + loop + "\n\n"
            "Write ONE short imperative rule (max 25 words, no preamble, "
            "no quotes) to add to its operating guide so it avoids this "
            "next time. Output only the rule."
        )
        provider = llmgateway.get(strong)
        req = llmgateway.ChatRequest(
            messages=[{"role": "user", "content": prompt}],
            model=_daemon_ns._effective_model(strong),
            max_tokens=80,
            reasoning_effort=_daemon_ns._effort_for(
                strong, _daemon_ns._effective_model(strong), "ladder"),
        )
        rule = ""
        async for ev in provider.chat_stream(req):
            if isinstance(ev, llmgateway.TextChunk):
                rule += ev.text
        rule = rule.strip().splitlines()[0] if rule.strip() else ""
        if rule and await asyncio.to_thread(localllm.harness_append_rule, rule):
            await _daemon_ns._broadcast(app, protocol.notice(
                f"Local-model harness updated: {rule[:90]}", kind="chat",
            ))
        # Bounded growth: once the harness drifts past its line ceiling
        # (HARNESS_REFINE_LINES), have the strong model consolidate it
        # (pi-agent minimalism — fewer, sharper rules beat a long list).
        if await asyncio.to_thread(localllm.harness_line_count) > localllm.HARNESS_REFINE_LINES:
            await _refine_harness(app, strong)
    except Exception:  # noqa: BLE001
        log.exception("local-model harness auto-tune failed")

async def _refine_harness(app: web.Application, strong_pid: str) -> None:
    """Judge-refine: ask a strong model to consolidate the harness into a
    MINIMAL, high-signal set of rules — dedupe, merge overlaps, drop the
    stale/rarely-useful, keep it tight. Preserves the `applies_to`
    frontmatter. Backstop against unbounded, unoptimized drift."""
    try:
        cur = await asyncio.to_thread(localllm.load_harness)
        prompt = (
            "Below is an operating-rules harness that is appended to a "
            "small local model's system prompt. It has grown long and "
            "repetitive. Rewrite it as a MINIMAL, high-signal set of "
            "rules: merge overlaps, drop stale or rarely-useful ones, "
            "keep only what changes behavior. Fewer, sharper rules are "
            "better (aim well under 40 lines). Preserve the leading "
            "`---\\napplies_to: ...\\n---` frontmatter EXACTLY. Output "
            "only the rewritten harness.\n\n---\n" + cur
        )
        provider = llmgateway.get(strong_pid)
        req = llmgateway.ChatRequest(
            messages=[{"role": "user", "content": prompt}],
            model=_daemon_ns._effective_model(strong_pid),
            max_tokens=1200,
            reasoning_effort=_daemon_ns._effort_for(
                strong_pid, _daemon_ns._effective_model(strong_pid), "ladder"),
        )
        out = ""
        async for ev in provider.chat_stream(req):
            if isinstance(ev, llmgateway.TextChunk):
                out += ev.text
        out = out.strip()
        # Only accept a sane, shorter result that kept the frontmatter.
        if out.startswith("---") and "applies_to" in out and len(out) < len(cur):
            await asyncio.to_thread(localllm.save_harness, out)
            await _daemon_ns._broadcast(app, protocol.notice(
                "Local-model harness consolidated (judge refine).", kind="chat",
            ))
    except Exception:  # noqa: BLE001
        log.exception("harness refine failed")

def _summarise_input(input: dict[str, Any]) -> str:
    """Compact key=value preview of a tool input — same shape as the
    frontend's rail rendering, used in the persisted summary so
    recall_rail hits read like the rail entries the user remembers."""
    if not input:
        return ""
    parts: list[str] = []
    for k, v in list(input.items())[:3]:
        if isinstance(v, list):
            parts.append(f"{k}[{len(v)}]")
        elif isinstance(v, dict):
            parts.append(f"{k}{{…}}")
        else:
            s = str(v)
            parts.append(f"{k}={s[:30] + '…' if len(s) > 30 else s}")
    rest = f" +{len(input) - 3}" if len(input) > 3 else ""
    return ", ".join(parts) + rest

def _artifact_for_tool(
    name: str, tinput: dict[str, Any], output: dict[str, Any] | str | None,
) -> dict[str, Any] | None:
    """Map a completed agent tool call to a `protocol.artifact`
    broadcast (Zen's pulse badge — kind + label + a ready-to-apply
    selection so the jump lands on the exact artifact). Returns None
    for non-artifact tools.

    `output` is available on the daemon-executed (HTTP-provider)
    path; the CLI-provider stream only SEES the call (the MCP
    subprocess executes it), so every field must degrade gracefully
    to input-only. That path is optimistic — a tool that later fails
    yields one false pulse, which is acceptable noise."""
    out = output if isinstance(output, dict) else {}
    if out.get("ok") is False:
        return None
    if name in ("save_plot", "plot_show", "plot_update"):
        pid = out.get("id") or tinput.get("id")
        pname = str(out.get("name") or tinput.get("name") or "plot")
        sel = (
            {"kind": "plot", "id": str(pid), "name": pname}
            if isinstance(pid, str) and pid else None
        )
        return protocol.artifact("vega", f"plot · {pname}", sel)
    if name == "sheet_set_values":
        origin = str(out.get("origin") or tinput.get("origin") or "sheet")
        return protocol.artifact("univer", f"sheet · {origin}", None)
    if name == "create_slideshow":
        slug = str(out.get("slug") or tinput.get("slug") or "")
        title = str(out.get("title") or tinput.get("title") or slug or "slideshow")
        return protocol.artifact("html-deck", f"slideshow · {title}", None)
    if name == "author_sketch":
        sid = out.get("sketch_id") or tinput.get("sketch_id")
        sname = str(out.get("name") or tinput.get("name") or "sketch")
        sel = (
            {"kind": "sketch", "id": str(sid), "name": sname}
            if isinstance(sid, str) and sid else None
        )
        return protocol.artifact("sketch", f"sketch · {sname}", sel)
    if name == "read_wiki_page":
        rel = str(out.get("page") or tinput.get("page") or "").replace("\\", "/")
        if "wiki/" in rel:
            rel = rel[rel.find("wiki/"):]
        if rel.startswith("wiki/") and rel.endswith(".md"):
            page_id = rel[len("wiki/"):-len(".md")]
            label = str(out.get("title") or page_id)
            return protocol.artifact(
                "markdown", f"page · {label}",
                {"kind": "page", "id": page_id, "path": rel},
            )
    return None

def _wiki_artifact_for_write(workspace: Path, file_path: str) -> dict[str, Any] | None:
    """Provider-internal Write/Edit that touched a wiki page → a
    `markdown` artifact whose selection opens that page in the
    Editor. Paths from CLI tools are usually absolute; normalise to
    the workspace-relative `wiki/...` shape the selection layer and
    /api/page expect. None when the write isn't a wiki .md file."""
    fp = file_path.strip()
    if not fp:
        return None
    try:
        rel = str(Path(fp).resolve().relative_to(workspace.resolve()))
    except ValueError:
        rel = fp  # already relative (or outside the workspace — filtered next)
    if not (rel.startswith("wiki/") and rel.endswith(".md")):
        return None
    page_id = rel[len("wiki/"):-len(".md")]
    return protocol.artifact(
        "markdown", f"page · {page_id}",
        {"kind": "page", "id": page_id, "path": rel},
    )

def _summarise(output: dict | str) -> str:
    """Compact one-line summary of a tool result for the rail badge."""
    if isinstance(output, str):
        return output[:120]
    if isinstance(output, dict):
        if "ok" in output:
            extras = []
            if "added" in output:
                extras.append(f"+{output['added']}")
            if "total" in output:
                extras.append(f"total={output['total']}")
            tail = " ".join(extras)
            return f"ok{(' · ' + tail) if tail else ''}"
        return ", ".join(f"{k}={v}" for k, v in list(output.items())[:3])[:120]
    return str(output)[:120]
