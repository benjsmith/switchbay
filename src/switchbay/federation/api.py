"""HTTP routes for session labels, review classification, exclusion
rules, and the public-write dialog.
"""

from __future__ import annotations

from pathlib import Path

from aiohttp import web

from . import exclusion, public_write, review_queue, session_label


def _ws(request: web.Request) -> Path:
    return Path(request.app["workspace"])


async def session_get(request: web.Request) -> web.Response:
    workspace = _ws(request)
    label = session_label.floor(workspace)
    return web.json_response({"label": label, "session": session_label.current_id()})


async def session_lower(request: web.Request) -> web.Response:
    body = await _json(request)
    result = session_label.lower(
        _ws(request),
        str(body.get("reason") or ""),
        human_confirmed=bool(body.get("human_confirmed")),
    )
    return web.json_response(result, status=200 if result.get("ok") else 400)


async def exclusion_get(request: web.Request) -> web.Response:
    return web.json_response({"rules": exclusion.load(_ws(request))})


async def exclusion_put(request: web.Request) -> web.Response:
    body = await _json(request)
    rules = body.get("rules") if isinstance(body.get("rules"), list) else []
    saved = exclusion.save(_ws(request), rules)
    return web.json_response({"rules": saved})


async def classification_get(request: web.Request) -> web.Response:
    workspace = _ws(request)
    return web.json_response({
        "items": review_queue.pending(workspace),
        "mandatory": review_queue.mandatory(workspace),
    })


async def classification_decide(request: web.Request) -> web.Response:
    body = await _json(request)
    result = review_queue.decide(
        _ws(request), str(body.get("id") or ""), str(body.get("label") or ""),
    )
    return web.json_response(result, status=200 if result.get("ok") else 400)


async def classification_mandatory(request: web.Request) -> web.Response:
    body = await _json(request)
    result = review_queue.set_mandatory(_ws(request), bool(body.get("mandatory")))
    return web.json_response(result, status=200 if result.get("ok") else 400)


async def public_write_status(request: web.Request) -> web.Response:
    workspace = _ws(request)
    return web.json_response({
        "presidio_installed": public_write.presidio_installed(),
        "presidio_enabled": public_write.presidio_enabled_for_user(workspace),
        "user_may_toggle": public_write.user_may_toggle(),
        "guidance": public_write.GUIDANCE,
        "rules": public_write.list_rules(workspace),
    })


async def public_write_toggle(request: web.Request) -> web.Response:
    body = await _json(request)
    result = public_write.set_workspace_presidio(_ws(request), bool(body.get("enabled", True)))
    return web.json_response(result, status=200 if result.get("ok") else 400)


async def public_write_confirm(request: web.Request) -> web.Response:
    body = await _json(request)
    result = public_write.confirm(
        _ws(request), str(body.get("choice") or ""), mount_id=str(body.get("mount") or ""),
    )
    return web.json_response(result, status=200 if result.get("ok") else 400)


async def public_write_scope(request: web.Request) -> web.Response:
    body = await _json(request)
    result = public_write.set_rule_scope(
        _ws(request), str(body.get("id") or ""), str(body.get("scope") or ""),
    )
    return web.json_response(result, status=200 if result.get("ok") else 400)


async def _json(request: web.Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def register(app: web.Application) -> None:
    app.router.add_get("/api/session/label", session_get)
    app.router.add_post("/api/session/label", session_lower)
    app.router.add_get("/api/exclusion-rules", exclusion_get)
    app.router.add_put("/api/exclusion-rules", exclusion_put)
    app.router.add_get("/api/classification/queue", classification_get)
    app.router.add_post("/api/classification/decide", classification_decide)
    app.router.add_post("/api/classification/mandatory", classification_mandatory)
    app.router.add_get("/api/public-write", public_write_status)
    app.router.add_post("/api/public-write/presidio", public_write_toggle)
    app.router.add_post("/api/public-write/confirm", public_write_confirm)
    app.router.add_post("/api/public-write/scope", public_write_scope)
