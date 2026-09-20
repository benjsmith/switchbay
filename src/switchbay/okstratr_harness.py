"""Thin client over okstratr harness+model registry (SSOT).

Ben lock: okstratr owns the harness allowlist and model pools
(``harnesses.toml``). Switchbay Settings / shells configure that registry
through HTTP — they must **not** invent a parallel Switchbay allowlist.

Call paths
----------
* **Browser (preferred same-origin):** ``/embed/okstratr/api/harness…``
  when the embed proxy is up (loopback rules + ``X-Okstratr-Host`` stay
  intact).
* **Daemon thin routes:** ``/api/okstratr/harness`` (and
  ``…/enable|disable|set|reload``) so UI/shells need not know embed
  paths. Server-side these call ``SWITCHBAY_OKSTRATR_UPSTREAM``
  (default ``http://127.0.0.1:8767``), loopback-guarded via
  :mod:`switchbay.embed_proxy`, with ``X-Okstratr-Host: switchbay``.

okbay should mirror this thin-client pattern (see okbay
``docs/HERDR-AND-REGISTRY.md`` and Switchbay ``/api/okstratr/host-notify``).
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from aiohttp import ClientSession, ClientTimeout, web

from . import embed_proxy

log = logging.getLogger("switchbay.okstratr_harness")

# Upstream okstratr paths (also available under /api/config/harness…).
_PATHS = {
    "list": "/api/harness",
    "enable": "/api/harness/enable",
    "disable": "/api/harness/disable",
    "set": "/api/harness/set",
    "reload": "/api/harness/reload",
}

# Same-origin embed prefixes the browser can use directly.
EMBED_LIST = "/embed/okstratr/api/harness"
EMBED_ENABLE = "/embed/okstratr/api/harness/enable"
EMBED_DISABLE = "/embed/okstratr/api/harness/disable"
EMBED_SET = "/embed/okstratr/api/harness/set"
EMBED_RELOAD = "/embed/okstratr/api/harness/reload"


class OkstratrHarnessError(RuntimeError):
    """Upstream unreachable, non-loopback, or bad response."""

    def __init__(self, message: str, *, status: int = 502, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.detail = detail


def embed_paths() -> dict[str, str]:
    """Public same-origin paths (for docs / UI hints)."""
    return {
        "list": EMBED_LIST,
        "enable": EMBED_ENABLE,
        "disable": EMBED_DISABLE,
        "set": EMBED_SET,
        "reload": EMBED_RELOAD,
    }


def upstream_url(action: str = "list") -> str:
    """Absolute loopback URL for a harness API action."""
    path = _PATHS.get(action)
    if path is None:
        raise ValueError(f"unknown harness action: {action!r}")
    try:
        base = embed_proxy.assert_loopback_upstream(embed_proxy.okstratr_upstream())
    except embed_proxy.UpstreamNotLoopback as e:
        raise OkstratrHarnessError(str(e), status=502) from e
    return f"{base}{path}"


def normalize_registry(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Map okstratr ``list_for_api`` JSON into a stable Switchbay view.

    Pass-through of the SSOT fields; never invents an allowlist. Missing
    keys become empty defaults so the Settings UI can render safely.
    """
    raw = dict(payload or {})
    harnesses_in = raw.get("harnesses")
    rows: list[dict[str, Any]] = []
    if isinstance(harnesses_in, list):
        for item in harnesses_in:
            if not isinstance(item, dict):
                continue
            hid = str(item.get("id") or "").strip().lower()
            if not hid:
                continue
            models = item.get("models") or []
            if not isinstance(models, list):
                models = []
            effort = item.get("effort") if isinstance(item.get("effort"), dict) else {}
            settings = (
                item.get("settings") if isinstance(item.get("settings"), dict) else {}
            )
            rows.append(
                {
                    "id": hid,
                    "label": str(item.get("label") or hid),
                    "enabled": bool(item.get("enabled")),
                    "installed": bool(item.get("installed")),
                    "default_model": item.get("default_model"),
                    "models": [str(m) for m in models],
                    "effort": dict(effort),
                    "settings": dict(settings),
                    "herdr_kind": item.get("herdr_kind"),
                    "bin_names": list(item.get("bin_names") or []),
                    "notes": str(item.get("notes") or ""),
                }
            )
    enabled = raw.get("enabled")
    if not isinstance(enabled, list):
        enabled = [h["id"] for h in rows if h["enabled"]]
    preference = raw.get("preference")
    if not isinstance(preference, list):
        preference = list(enabled)
    defaults = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
    blackboard = (
        raw.get("blackboard") if isinstance(raw.get("blackboard"), dict) else {}
    )
    return {
        "ok": bool(raw.get("ok", True)),
        "ssot": "okstratr",
        "path": raw.get("path"),
        "enabled": [str(x).strip().lower() for x in enabled if str(x).strip()],
        "preference": [str(x).strip().lower() for x in preference if str(x).strip()],
        "defaults": dict(defaults),
        "backend": str(raw.get("backend") or defaults.get("backend") or ""),
        "harnesses": rows,
        "blackboard": dict(blackboard),
        "embed_paths": embed_paths(),
    }


def _hosted_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        embed_proxy.HOST_HEADER_OKSTRATR: embed_proxy.HOSTED_SHELL,
    }


async def _session_for(app: web.Application | None) -> tuple[ClientSession, bool]:
    """Reuse embed_http session when available; else open a short-lived one."""
    timeout = ClientTimeout(total=30, connect=5, sock_connect=5)
    if app is not None:
        sess = app.get("embed_http")
        if sess is not None and not sess.closed:
            return sess, False
    return ClientSession(timeout=timeout), True


async def call_harness(
    action: str,
    *,
    method: str = "GET",
    body: Mapping[str, Any] | None = None,
    app: web.Application | None = None,
) -> dict[str, Any]:
    """HTTP call to okstratr harness API; return normalized registry (or error)."""
    url = upstream_url(action)
    session, owns = await _session_for(app)
    try:
        async with session.request(
            method.upper(),
            url,
            headers=_hosted_headers(),
            json=dict(body) if body is not None else None,
            allow_redirects=False,
        ) as resp:
            try:
                data = await resp.json(content_type=None)
            except Exception:  # noqa: BLE001
                text = await resp.text()
                raise OkstratrHarnessError(
                    f"okstratr harness returned non-JSON (HTTP {resp.status})",
                    status=502 if resp.status >= 500 else resp.status,
                    detail=text[:500],
                )
            if resp.status >= 400:
                err = None
                if isinstance(data, dict):
                    err = data.get("error") or data.get("detail")
                raise OkstratrHarnessError(
                    str(err or f"okstratr harness HTTP {resp.status}"),
                    status=resp.status,
                    detail=data,
                )
            if not isinstance(data, dict):
                raise OkstratrHarnessError(
                    "okstratr harness response must be a JSON object",
                    status=502,
                    detail=data,
                )
            # Mutations return list_for_api; reload wraps under "config".
            if action == "reload" and isinstance(data.get("config"), dict):
                return normalize_registry(data["config"])
            return normalize_registry(data)
    except OkstratrHarnessError:
        raise
    except OSError as e:
        log.warning("okstratr harness unreachable %s: %s", url, e)
        raise OkstratrHarnessError(
            "okstratr harness unreachable (is okstratr up on the embed upstream?)",
            status=502,
            detail=str(e),
        ) from e
    except Exception as e:  # noqa: BLE001
        log.exception("okstratr harness call failed for %s", url)
        raise OkstratrHarnessError(
            f"okstratr harness call failed: {e}",
            status=502,
            detail=str(e),
        ) from e
    finally:
        if owns:
            await session.close()


async def list_harnesses(app: web.Application | None = None) -> dict[str, Any]:
    return await call_harness("list", method="GET", app=app)


async def enable_harness(
    harness_id: str, *, app: web.Application | None = None
) -> dict[str, Any]:
    hid = (harness_id or "").strip()
    if not hid:
        raise OkstratrHarnessError("id is required", status=400)
    return await call_harness(
        "enable", method="POST", body={"id": hid}, app=app
    )


async def disable_harness(
    harness_id: str, *, app: web.Application | None = None
) -> dict[str, Any]:
    hid = (harness_id or "").strip()
    if not hid:
        raise OkstratrHarnessError("id is required", status=400)
    return await call_harness(
        "disable", method="POST", body={"id": hid}, app=app
    )


async def set_harness_value(
    key: str,
    value: str,
    *,
    app: web.Application | None = None,
) -> dict[str, Any]:
    k = (key or "").strip()
    if not k:
        raise OkstratrHarnessError("key is required", status=400)
    return await call_harness(
        "set",
        method="POST",
        body={"key": k, "value": "" if value is None else str(value)},
        app=app,
    )


async def reload_harnesses(app: web.Application | None = None) -> dict[str, Any]:
    return await call_harness("reload", method="POST", body={}, app=app)


def error_response(exc: OkstratrHarnessError) -> web.Response:
    payload: dict[str, Any] = {
        "ok": False,
        "ssot": "okstratr",
        "error": str(exc),
    }
    if exc.detail is not None:
        payload["detail"] = exc.detail
    return web.json_response(payload, status=int(exc.status or 502))
