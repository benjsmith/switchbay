"""Natural-language intent and rule shortcut dispatch.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from aiohttp import web
from switchbay import agent_rules
from switchbay import protocol
from switchbay import rail
from switchbay import verbs

from switchbay.httpapi._ns import _daemon_ns

def _match_to_dict(m: verbs.Match) -> dict[str, Any]:
    return {
        "label": m.label,
        "detail": m.detail,
        "tab_kind": m.tab_kind,
        "payload": m.payload,
        "score": round(m.score, 3),
    }

async def _try_rule_dispatch(
    app: web.Application, ws: web.WebSocketResponse, text: str,
) -> bool:
    """User-defined shortcut handling. Two cases:
       (a) `text` is a rule registration ("when I say X, do Y"), in
           which case we save it and confirm. (b) `text` matches a
           saved rule's trigger, in which case we execute the action.
    Returns True if either path handled the input. Rules live in
    `<workspace>/.workbench/state/agent_rules.json` and persist
    across daemon restarts."""
    workspace: Path = app["workspace"]

    # (a) Rule registration via NL.
    detected = agent_rules.detect_nl_rule(text)
    if detected:
        trigger, action = detected
        try:
            rule = agent_rules.add(workspace, trigger, action)
        except ValueError as e:
            await ws.send_json(protocol.notice(f"could not save rule: {e}", kind="slash"))
            return True
        _daemon_ns._log_user_turn(app, workspace, text)
        _daemon_ns._log_event(
            app, "rule_register",
            f"saved rule: {trigger!r} → {action!r}",
            source="rail", actor="user",
            payload={"rule_id": rule["id"], "trigger": trigger, "action": action},
        )
        await ws.send_json(protocol.notice(
            f"saved shortcut: {trigger!r} → {action!r}\n"
            f"(id={rule['id']}; manage with /rules)",
            kind="slash",
        ))
        return True

    # (b) Trigger match.
    rule = agent_rules.match(workspace, text)
    if rule:
        action = str(rule.get("action") or "")
        _daemon_ns._log_user_turn(app, workspace, text)
        _daemon_ns._log_event(
            app, "rule_apply",
            f"rule {rule.get('id', '?')} → {action}",
            source="rail", actor="user",
            payload={"rule_id": rule.get("id"), "trigger": text, "action": action},
        )
        # Action grammar today: literal slash command. Re-parse so the
        # full slash → verb pipeline runs with persistence + decisive
        # match logic.
        sub_parsed = rail.parse(action)
        sub_kind = sub_parsed.get("kind")
        if sub_kind == "slash":
            sname = str(sub_parsed.get("name", ""))
            sargs = str(sub_parsed.get("args", ""))
            verb = verbs.lookup(sname)
            if verb is not None:
                await _daemon_ns._dispatch_verb(app, ws, verb, sargs)
                return True
        # Action wasn't a recognised slash. Surface clearly rather
        # than silently doing nothing.
        await ws.send_json(protocol.notice(
            f"rule {rule.get('id')} action {action!r} is not a known slash command.",
            kind="slash",
        ))
        return True

    return False

async def _try_intent_dispatch(
    app: web.Application, ws: web.WebSocketResponse, text: str,
) -> bool:
    """Route obvious NL "view X" phrases through the verb registry.
    Returns True iff we handled it (so the caller skips chat).

    Once the regex confirms the user is asking to view *something*, we
    commit to the verb path: decisive match → nav, ambiguous → post a
    disambiguation list. Only "no matches at all" falls through to
    chat — better to let the user pick from candidates than to dump
    file contents into the rail."""
    m = _daemon_ns._INTENT_VIEW_RE.match(text)
    if not m:
        return False
    query = m.group(1).strip()
    if not query:
        return False
    verb = verbs.lookup("view")
    if verb is None:
        return False
    workspace: Path = app["workspace"]
    pages = (app.get("graph_data") or {}).get("pages")
    files = _daemon_ns._walk_tree(workspace)
    ctx = verbs.VerbContext(
        workspace=workspace,
        query=query,
        pages=pages if isinstance(pages, dict) else None,
        files=files,
    )
    result = verb.handler(ctx)
    if not result.matches:
        return False  # nothing in the workspace looks like that — let chat handle
    best = result.matches[0]
    runner_up = result.matches[1] if len(result.matches) > 1 else None
    decisive = (
        best.score >= 0.45
        and (runner_up is None or best.score - runner_up.score >= 0.10)
    )
    _daemon_ns._log_user_turn(app, workspace, text)
    if decisive:
        _daemon_ns._log_event(
            app, "nav", f"intent:view {query!r} → {best.label}",
            source="rail", actor="user",
            payload={
                "verb": "view", "query": query, "intent": True,
                "tab_kind": best.tab_kind, "match": _match_to_dict(best),
            },
        )
        await _daemon_ns._broadcast(app, protocol.nav(best.tab_kind, best.payload, best.label))
        return True
    # Ambiguous — show disambiguation list, don't fall through to chat.
    top = result.matches[:5]
    lines = [f"matches for {query!r} (be more specific or click one):"]
    for i, mm in enumerate(top, 1):
        lines.append(f"  {i}. {mm.label}  ·  {mm.detail}")
    _daemon_ns._log_event(
        app, "slash", f"intent:view {query!r} → {len(top)} matches",
        source="rail", actor="user",
        payload={
            "verb": "view", "query": query, "intent": True,
            "matches": [_match_to_dict(mm) for mm in top],
        },
    )
    await ws.send_json(protocol.notice("\n".join(lines), kind="slash"))
    return True
