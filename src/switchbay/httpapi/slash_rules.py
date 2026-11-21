"""User rule slash commands and the in-app start alias.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
from aiohttp import web
from switchbay import agent_rules
from switchbay import protocol

from switchbay.httpapi._ns import _daemon_ns

async def _handle_rule_slash(
    app: web.Application, ws: web.WebSocketResponse, args: str,
) -> None:
    """`/rule "trigger" -> action` — explicit shortcut registration.
    Quoting around the trigger is optional; the `->` separator is
    required so we can disambiguate triggers that contain spaces."""
    workspace: Path = app["workspace"]
    if not args.strip():
        await ws.send_json(protocol.notice(
            "usage: /rule \"show me X\" -> /view X\n"
            "(or just say: when I say show me X, /view X)",
            kind="slash",
        ))
        return
    m = _daemon_ns._RULE_SLASH_RE.match(args)
    if not m:
        await ws.send_json(protocol.notice(
            "couldn't parse /rule. Format: /rule \"trigger\" -> action",
            kind="slash",
        ))
        return
    trigger = m.group("trigger").strip().strip("'\"").strip()
    action = m.group("action").strip()
    try:
        rule = agent_rules.add(workspace, trigger, action)
    except ValueError as e:
        await ws.send_json(protocol.notice(f"could not save: {e}", kind="slash"))
        return
    _daemon_ns._log_event(
        app, "rule_register",
        f"saved rule: {trigger!r} → {action!r}",
        source="rail", actor="user",
        payload={"rule_id": rule["id"], "trigger": trigger, "action": action},
    )
    await ws.send_json(protocol.notice(
        f"saved shortcut: {trigger!r} → {action!r} (id={rule['id']})",
        kind="slash",
    ))

async def _handle_rules_slash(
    app: web.Application, ws: web.WebSocketResponse, args: str,
) -> None:
    """`/rules` (list) | `/rules delete <id>` (remove)."""
    workspace: Path = app["workspace"]
    args = args.strip()
    if args.startswith("delete"):
        rid = args[len("delete"):].strip()
        if not rid:
            await ws.send_json(protocol.notice(
                "usage: /rules delete <id>", kind="slash",
            ))
            return
        ok = agent_rules.remove(workspace, rid)
        await ws.send_json(protocol.notice(
            f"removed rule {rid}" if ok else f"no rule with id {rid}",
            kind="slash",
        ))
        return
    rules = agent_rules.load(workspace)
    if not rules:
        await ws.send_json(protocol.notice(
            "no shortcuts saved. Add one with /rule \"trigger\" -> action, "
            "or say: when I say X, do Y.",
            kind="slash",
        ))
        return
    lines = [f"saved shortcuts ({len(rules)}):"]
    for r in rules:
        lines.append(f"  · {r['id']}  {r['trigger']!r} → {r['action']!r}")
    lines.append("(remove with /rules delete <id>)")
    await ws.send_json(protocol.notice("\n".join(lines), kind="slash"))
