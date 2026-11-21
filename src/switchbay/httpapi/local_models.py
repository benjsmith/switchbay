"""Local model search, install, and activation routes.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
import asyncio
import json
import logging
from aiohttp import web
from switchbay import conversations
from switchbay import local_models
from switchbay import localllm
from switchbay import modestore
from switchbay import protocol
from switchbay import terminals

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_local_models_search(request: web.Request) -> web.Response:
    """Live model search across the local backends.

    Query: ?q=<text>&backend=llamacpp|mlx|ollama&sort=downloads|trendingScore
    &curated=0|1

    Ungated by default: the catalog is a starting point, not a fence, so
    a user searching for a model released last week finds it. `curated=1`
    applies the recommendation gate (trusted GGUF publishers, no
    roleplay finetunes) for the "best fits" surface.
    """
    blocked = _daemon_ns._policy_block("hf_model_download")
    if blocked:
        return blocked
    q = request.rel_url.query
    query = (q.get("q") or "").strip()
    backend = (q.get("backend") or "llamacpp").strip()
    sort = (q.get("sort") or "downloads").strip()
    curated = q.get("curated") in ("1", "true", "yes")
    try:
        limit = max(1, min(int(q.get("limit") or 20), 50))
    except ValueError:
        limit = 20

    error: str | None = None
    if backend == "mlx":
        if not local_models.mlx_supported():
            return web.json_response({
                "backend": "mlx", "results": [],
                "error": local_models.mlx_status().get("reason"),
            })
        results, error = await asyncio.to_thread(
            local_models.mlx_search_with_status, query,
            limit=limit, curated=curated, sort=sort)
    elif backend == "ollama":
        # Ollama has no public search API; the tag is resolved directly.
        results = []
    else:
        backend = "llamacpp"
        results, error = await asyncio.to_thread(
            local_models.hf_search_gguf_with_status, query,
            sort=sort, limit=limit, curated=curated)
    return web.json_response({
        "backend": backend, "query": query, "sort": sort,
        "curated": curated, "results": results,
        **({"error": error} if error else {}),
    })

async def handle_local_models_resolve(request: web.Request) -> web.Response:
    """Resolve a pasted model id into an installable candidate.

    Body: {repo | ollama_tag, backend?, quant?}

    This is the free-text path — it reads the repo's real file list to
    size the download, so no catalog entry is needed. Returns the
    candidate for confirmation; POST /api/localllm/install performs it.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    backend = str((body or {}).get("backend") or "").strip()
    repo = str((body or {}).get("repo") or (body or {}).get("id") or "").strip()
    tag = str((body or {}).get("ollama_tag") or "").strip()
    quant = str((body or {}).get("quant") or "").strip() or None

    if not backend:
        backend = "ollama" if tag else "llamacpp"
    if backend == "ollama":
        out = await asyncio.to_thread(
            local_models.resolve_ollama_candidate, tag or repo)
    elif backend == "mlx":
        out = await asyncio.to_thread(local_models.resolve_mlx_candidate, repo)
    else:
        out = await asyncio.to_thread(
            local_models.resolve_repo_candidate, repo, quant=quant)
    return web.json_response(out, status=200 if out.get("ok") else 400)

async def handle_local_models_discover(request: web.Request) -> web.Response:
    """Run HF/catalog discovery (may take a few seconds)."""
    result = await asyncio.to_thread(local_models.discover_updates)
    await _daemon_ns._broadcast(request.app, protocol.custom({
        "type": "local_models.discovery",
        "discovery": result,
    }))
    return web.json_response(result)

async def handle_local_models_remove(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    cid = str(body.get("id") or "").strip()
    if not cid:
        return web.json_response({"error": "id required"}, status=400)
    await localllm.stop_server(request.app, cid)
    out = await asyncio.to_thread(local_models.unregister, cid)
    return web.json_response(out)

async def handle_local_models_activate(request: web.Request) -> web.Response:
    """Switch the active local model; start its llama-server if needed.

    Body: {id: candidate_id, keep_others?: true}

    When keep_others is true (default), other GGUF servers stay up on
    their ports (multi-active). Chat uses the active config port.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    cid = str(body.get("id") or "").strip()
    if not cid:
        return web.json_response({"error": "id required"}, status=400)
    keep_others = body.get("keep_others", True)
    out = await asyncio.to_thread(local_models.activate, cid)
    if not out.get("ok"):
        return web.json_response(out, status=400)
    cfg = out.get("cfg")
    backend = str((cfg or {}).get("backend") or out.get("backend") or "")
    if isinstance(cfg, dict) and backend in ("", "llamacpp", "mlx"):
        if not keep_others:
            await localllm.stop_server(request.app)
        await localllm.spawn_server(request.app, cfg)
        healthy = await localllm.wait_healthy(
            timeout_s=180 if backend == "mlx" else 60,
            port=int(cfg.get("port") or localllm.PORT),
        )
        if healthy and backend == "mlx" and isinstance(cfg, dict):
            cfg = await localllm.remember_mlx_served_model(cfg)
            out["cfg"] = cfg
        out["server_healthy"] = healthy
        out["servers"] = localllm.running_servers(
            request.app, await asyncio.to_thread(local_models.list_installed),
        )
        try:
            ladder = await asyncio.to_thread(modestore.global_ladder)
            alias = str(cfg.get("alias") or cid)
            provider = "mlx" if backend == "mlx" else "llamacpp"
            ladder["trivial"] = {"provider": provider, "model": alias}
            ladder["normal"] = {"provider": provider, "model": alias}
            await asyncio.to_thread(modestore.set_global_ladder, ladder)
            out["ladder_updated"] = True
        except Exception:  # noqa: BLE001
            log.exception("ladder update on activate failed")
    elif out.get("backend") == "ollama":
        tag = out.get("ollama_tag")
        if tag:
            try:
                ladder = await asyncio.to_thread(modestore.global_ladder)
                ladder["trivial"] = {"provider": "ollama", "model": tag}
                ladder["normal"] = {"provider": "ollama", "model": tag}
                await asyncio.to_thread(modestore.set_global_ladder, ladder)
                out["ladder_updated"] = True
            except Exception:  # noqa: BLE001
                log.exception("ladder update on ollama activate failed")
    await _daemon_ns._broadcast(request.app, protocol.custom({
        "type": "local_models.activated",
        "id": cid,
        "backend": out.get("backend"),
    }))
    return web.json_response(out)

async def handle_localllm_control(request: web.Request) -> web.Response:
    """Start / stop / restart a managed local-model server.

    Body: {id?, action: start|stop|restart}. ``id`` defaults to the
    active registry candidate. Ollama is not spawned here (external
    daemon); we only report whether :11434 answers.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    action = str(body.get("action") or "").strip().lower()
    if action not in ("start", "stop", "restart"):
        return web.json_response(
            {"error": "action must be start|stop|restart"}, status=400)
    cid = str(body.get("id") or "").strip()
    if not cid:
        payload = await asyncio.to_thread(local_models.status_payload)
        cid = str(payload.get("active") or "")
    if not cid:
        return web.json_response({"error": "no local model selected"}, status=400)
    installed = await asyncio.to_thread(local_models.list_installed)
    meta = next((m for m in installed if m.get("id") == cid), {}) or {}
    backend = str(meta.get("backend") or "")
    if action == "stop":
        if backend == "ollama":
            return web.json_response({
                "ok": False,
                "error": "Ollama is an external app — stop it from the menu bar.",
            }, status=400)
        port = meta.get("port")
        try:
            port_i = int(port) if port is not None else None
        except (TypeError, ValueError):
            port_i = None
        await localllm.stop_server(request.app, cid, port=port_i)
        return web.json_response({
            "ok": True, "id": cid, "action": "stop",
            "servers": localllm.running_servers(request.app, installed),
        })
    out = await asyncio.to_thread(local_models.activate, cid)
    if not out.get("ok"):
        return web.json_response(out, status=400)
    cfg = out.get("cfg")
    backend = str((cfg or {}).get("backend") or out.get("backend") or backend)
    if backend == "ollama":
        healthy = await localllm.server_healthy(port=11434)
        return web.json_response({
            "ok": healthy, "id": cid, "backend": "ollama",
            "server_healthy": healthy,
            "error": None if healthy else "Ollama is not answering on :11434 — start the Ollama app.",
        }, status=200 if healthy else 503)
    if not isinstance(cfg, dict):
        return web.json_response({"error": "could not build server config"}, status=400)
    if action == "restart":
        await localllm.stop_server(
            request.app, cid, port=int(cfg.get("port") or localllm.PORT),
        )
    await localllm.spawn_server(request.app, cfg)
    port = int(cfg.get("port") or localllm.PORT)
    healthy = await localllm.wait_healthy(
        timeout_s=180 if backend == "mlx" else 60,
        port=port,
    )
    if healthy and backend == "mlx" and isinstance(cfg, dict):
        cfg = await localllm.remember_mlx_served_model(cfg)
    servers = localllm.running_servers(request.app, installed)
    return web.json_response({
        "ok": True, "id": cid, "action": action,
        "server_healthy": healthy,
        "served_model": (cfg or {}).get("served_model") if isinstance(cfg, dict) else None,
        "servers": servers,
    })

async def handle_local_models_verify(request: web.Request) -> web.Response:
    """Verify catalog GGUF filenames against Hugging Face trees."""
    result = await asyncio.to_thread(local_models.verify_catalog_filenames)
    return web.json_response(result)

async def handle_local_models_prompt_ack(request: web.Request) -> web.Response:
    """User dismissed or accepted the 6-week check prompt."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    action = str(body.get("action") or "dismiss").lower()
    await asyncio.to_thread(local_models.mark_check_prompt_shown)
    if action == "check":
        # Kick discovery in background
        async def _bg() -> None:
            try:
                result = await asyncio.to_thread(local_models.discover_updates)
                await _daemon_ns._broadcast(request.app, protocol.custom({
                    "type": "local_models.discovery",
                    "discovery": result,
                }))
            except Exception:  # noqa: BLE001
                log.exception("local models discovery failed")
        asyncio.create_task(_bg())
        return web.json_response({"ok": True, "started": True})
    return web.json_response({"ok": True, "dismissed": True})

async def handle_localllm_watch(request: web.Request) -> web.Response:
    """Open a terminal tailing the *active* local-model server log.

    Body: {id?} — defaults to the active localllm config's slot.
    MLX and llama.cpp write per-slot files; Watch used to always tail
    the Ornith ``llama-server.log``, so an MLX server on :8888 showed
    a leftover llama.cpp bind-fail.
    """
    import shlex
    app = request.app
    cid = ""
    try:
        if request.content_length:
            body = await request.json()
            if isinstance(body, dict):
                cid = str(body.get("id") or "").strip()
    except (json.JSONDecodeError, TypeError):
        cid = ""
    cfg = await asyncio.to_thread(localllm.load_config)
    logp = localllm.watch_log_path(cfg, cid or None)
    label = localllm.server_process_label(cfg, candidate_id=cid or None)
    if not logp.exists():
        # Give tail -f something to follow even if the server hasn't
        # written yet (or predates output capture — a restart repopulates
        # it). A one-line hint beats an empty pane.
        try:
            logp.parent.mkdir(parents=True, exist_ok=True)
            logp.write_text(
                f"# {label} log is empty. If the server was started "
                "before this build, Restart it in Settings to capture "
                "output here.\n",
                encoding="utf-8",
            )
        except OSError:
            pass
    workspace: Path = app["workspace"]
    thread_id = await asyncio.to_thread(
        conversations.new_thread, workspace, label, "interactive-pty",
    )
    app["thread_id"] = thread_id
    app["thread_kind"] = "interactive-pty"
    try:
        session = await _daemon_ns._spawn_pty_for_thread(app, thread_id, name=label)
    except Exception as e:  # noqa: BLE001
        log.exception("localllm watch spawn failed")
        return web.json_response({"error": str(e)}, status=500)
    await _daemon_ns._broadcast(app, protocol.thread_focused(
        thread_id, "interactive-pty", workspace=str(workspace),
    ))
    await asyncio.sleep(0.08)
    terminals.write_input(
        session, f"tail -n 200 -f {shlex.quote(str(logp))}\n".encode("utf-8"),
    )
    return web.json_response({
        "ok": True, "thread_id": thread_id, "log": str(logp), "label": label,
    })

async def handle_localllm_reasoning(request: web.Request) -> web.Response:
    """Toggle the local model's chain-of-thought. ON by default: Ornith
    derives most of its capability from reasoning, and the loop guard
    (not reasoning-off) is what keeps it on the rails. Turning it off
    makes the model act directly + burn less context, at a quality cost.
    Body: {enabled: bool}."""
    cfg = await asyncio.to_thread(localllm.load_config)
    if cfg is None:
        return web.json_response({"error": "not installed"}, status=400)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    cfg["reasoning"] = bool(body.get("enabled"))
    await asyncio.to_thread(localllm.save_config, cfg)
    return web.json_response({"ok": True, "reasoning": cfg["reasoning"]})

async def handle_localllm_harness(request: web.Request) -> web.Response:
    """Read (GET) or replace (POST {text}) the model harness — the
    operating-rules block appended to the system prompt for the models in
    its `applies_to` frontmatter. Power-user surface; casual users never
    see it (it applies silently)."""
    if request.method == "POST":
        try:
            body = await request.json()
        except json.JSONDecodeError:
            body = {}
        text = str(body.get("text", "")).strip()
        if not text:
            return web.json_response({"error": "empty harness"}, status=400)
        await asyncio.to_thread(localllm.save_harness, text)
    text = await asyncio.to_thread(localllm.load_harness)
    return web.json_response({
        "text": text,
        "lines": len(text.splitlines()),
        "refine_lines": localllm.HARNESS_REFINE_LINES,
        "path": str(localllm.harness_path()),
    })
