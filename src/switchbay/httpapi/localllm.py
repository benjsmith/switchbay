"""Managed local model server routes.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from typing import Any
import asyncio
import json
import logging
import re
import time
from aiohttp import web
from switchbay import local_models
from switchbay import localllm
from switchbay import modestore
from switchbay import protocol
from switchbay.agents import rail_default

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_localllm_status(request: web.Request) -> web.Response:
    """Local models: legacy single plan + multi-candidate top3, install
    progress, registry, multi-active servers, and discovery results."""
    plan = await asyncio.to_thread(localllm.plan)
    multi = await asyncio.to_thread(local_models.status_payload)
    cfg = await asyncio.to_thread(localllm.load_config)
    port = int((cfg or {}).get("port") or localllm.PORT) if cfg else None
    rec = request.app.get("localllm_install")
    installed = multi.get("installed") or []
    servers = localllm.running_servers(request.app, installed)
    healthy = False
    if cfg:
        cid = str(cfg.get("candidate_id") or "")
        alias = str(cfg.get("alias") or "")
        alive = any(
            s.get("alive") and (
                (cid and s.get("id") == cid)
                or (port is not None and s.get("port") == port)
                or (alias and s.get("alias") == alias)
            )
            for s in servers
        )
        healthy = bool(alive and await localllm.server_healthy(port))
    return web.json_response({
        "plan": plan,
        "top3": multi.get("top3"),
        "installed": multi.get("installed"),
        "active": multi.get("active"),
        "should_prompt_refresh": multi.get("should_prompt_refresh"),
        "discovery": multi.get("discovery"),
        "config": cfg,
        "server_healthy": healthy,
        "server_url": localllm.server_url_for(cfg) if cfg else None,
        "servers": servers,
        "port_pool": multi.get("port_pool"),
        # Which free-text install paths this machine supports (incl. MLX).
        "backends": multi.get("backends"),
        "install": rec if isinstance(rec, dict) else None,
        "local_rung": rail_default.resolve_local_rung(
            localllm.ram_gb(),
            model_hint=rail_default.model_hint_from_cfg(cfg),
        ).to_public(),
    })

async def handle_localllm_install(request: web.Request) -> web.Response:
    """Install a local model.

    Body: {candidate_id?, repo?, ollama_tag?, backend?, quant?, ctx?}.

    Three paths:
      * `repo` / `ollama_tag` — free-text install of ANY llama.cpp-
        compatible GGUF repo, MLX repo, or Ollama tag. Sizes come from
        the repo's real file list, so no catalog entry is needed.
      * `candidate_id` from plan_top3 / discovery — catalog install.
      * neither — legacy RAM-planned Ornith.
    """
    blocked = _daemon_ns._policy_block("hf_model_download")
    if blocked:
        return blocked
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except json.JSONDecodeError:
        pass
    cand_id = str(body.get("candidate_id") or body.get("id") or "").strip()
    repo = str(body.get("repo") or "").strip()
    otag = str(body.get("ollama_tag") or "").strip()
    backend = str(body.get("backend") or "").strip()
    quant = str(body.get("quant") or "").strip() or None
    cur = request.app.get("localllm_install")
    if isinstance(cur, dict) and cur.get("state") == "running":
        return web.json_response({"error": "install already running"}, status=409)

    ram = localllm.ram_gb()

    # ── Free-text path ─────────────────────────────────────────────
    # A candidate the user pasted rather than picked. Resolved against
    # the live registry (HF tree / ollama) so an id that never appears
    # in our catalog still installs.
    if repo or otag:
        if not backend:
            backend = "ollama" if otag else "llamacpp"
        if backend == "ollama":
            cand = await asyncio.to_thread(
                local_models.resolve_ollama_candidate, otag or repo)
            if not cand.get("ok"):
                return web.json_response({"error": cand.get("error")}, status=400)
            return await _install_ollama_model(request.app, {
                "id": cand["id"], "label": cand["label"],
                "ollama_tag": cand["ollama_tag"],
            })
        if backend == "mlx":
            cand = await asyncio.to_thread(
                local_models.resolve_mlx_candidate, repo)
            if not cand.get("ok"):
                return web.json_response({"error": cand.get("error")}, status=400)
            return await _install_mlx_model(
                request.app, cand, ctx=int(body.get("ctx") or cand["ctx"]))
        cand = await asyncio.to_thread(
            local_models.resolve_repo_candidate, repo, ram=ram, quant=quant)
        if not cand.get("ok"):
            return web.json_response({"error": cand.get("error")}, status=400)
        plan = {
            "ok": True,
            "model": cand["id"],
            "model_label": cand["label"],
            "repo": cand["repo"],
            "quant": cand["quant"],
            "file": cand["file"],
            "parts": cand.get("parts") or [cand["file"]],
            "weights_gb": cand["weights_gb"],
            "ctx": int(body.get("ctx") or cand["ctx"]),
            "kv_quant": "q8_0",
            "alias": re.sub(r"[^a-zA-Z0-9_]+", "_", cand["label"])[:24] or "local",
            "candidate_id": cand["id"],
            "port": await asyncio.to_thread(local_models.allocate_port),
            "gguf_note": None,
        }
        return await _start_gguf_install(request.app, plan)

    # ── Catalog / legacy paths ─────────────────────────────────────
    entry = local_models.catalog_by_id(cand_id) if cand_id else None
    if entry and entry.get("backend") == "ollama":
        return await _install_ollama_model(request.app, entry)

    if entry and entry.get("backend") == "llamacpp":
        plan_row = local_models._candidate_payload(  # noqa: SLF001
            entry, ram, rank=1, score=0)
        if not plan_row:
            return web.json_response({"error": "cannot plan this model"}, status=400)
        quant = plan_row["quant"]
        try:
            gguf_name, gguf_note = await asyncio.to_thread(
                local_models.resolve_gguf_filename, entry, quant,
            )
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        port = await asyncio.to_thread(local_models.allocate_port)
        plan = {
            "ok": True,
            "model": entry["id"],
            "model_label": entry["label"],
            "repo": entry["repo"],
            "quant": quant,
            "file": gguf_name,
            "weights_gb": plan_row["weights_gb"],
            "ctx": int(body.get("ctx") or plan_row["ctx"]),
            "kv_quant": "q8_0",
            "ctx_options": [{"ctx": plan_row["ctx"], "recommended": True}],
            "alias": entry["id"].replace("-", "_")[:24],
            "candidate_id": entry["id"],
            "port": port,
            "gguf_note": gguf_note,
        }
    else:
        plan = await asyncio.to_thread(localllm.plan)
        if not plan.get("ok"):
            return web.json_response(
                {"error": plan.get("reason", "not plannable on this machine")},
                status=400,
            )
        plan = dict(plan)
        plan["alias"] = "ornith"
        plan["candidate_id"] = "ornith-9b" if plan.get("model") == "9b" else "ornith-35b"
        plan["model_label"] = plan.get("model_label") or "Ornith"
        ctx = int(body.get("ctx") or plan["ctx"])
        opts = [o["ctx"] for o in (plan.get("ctx_options") or [])]
        if opts and ctx not in opts:
            return web.json_response({"error": f"ctx {ctx} not offered"}, status=400)
        plan["ctx"] = ctx

    return await _start_gguf_install(request.app, plan)

async def _start_gguf_install(
    app: web.Application, plan: dict[str, Any],
) -> web.Response:
    """Kick off a GGUF download → llama-server → ladder install.

    Shared by the catalog path, the legacy Ornith path and the
    paste-any-repo path — they differ only in how `plan` is built.
    """
    rec: dict[str, Any] = {
        "state": "running", "step": "starting", "percent": 0, "error": None,
        "candidate_id": plan.get("candidate_id"),
    }
    app["localllm_install"] = rec
    ctx = int(plan["ctx"])

    async def _worker() -> None:
        try:
            await localllm.ensure_llama_cpp(rec)
            dest = await localllm.download_gguf(
                plan["repo"], plan["file"], plan["weights_gb"], rec,
                parts=plan.get("parts"),
            )
            alias = str(plan.get("alias") or "local")
            port = int(plan.get("port") or localllm.PORT)
            cid = str(plan.get("candidate_id") or alias)
            cfg = {
                "model": plan.get("model") or plan.get("candidate_id"),
                "model_label": plan["model_label"],
                "quant": plan["quant"],
                "file": str(dest),
                "ctx": ctx,
                "kv_quant": plan.get("kv_quant") or "q8_0",
                "port": port,
                "alias": alias,
                "installed_at": time.time(),
                "candidate_id": cid,
            }
            await asyncio.to_thread(localllm.save_config, cfg)
            await asyncio.to_thread(
                local_models.register_installed,
                cid,
                {
                    "label": plan["model_label"],
                    "backend": "llamacpp",
                    "file": str(dest),
                    "quant": plan["quant"],
                    "ctx": ctx,
                    "alias": alias,
                    "port": port,
                },
                activate=True,
            )
            rec["step"] = "starting llama-server"
            await localllm.spawn_server(app, cfg)
            rec["step"] = "loading model (first load takes a minute)"
            healthy = await localllm.wait_healthy(port=port)
            ladder = await asyncio.to_thread(modestore.global_ladder)
            ladder["trivial"] = {"provider": "llamacpp", "model": alias}
            ladder["normal"] = {"provider": "llamacpp", "model": alias}
            await asyncio.to_thread(modestore.set_global_ladder, ladder)
            rec.update(state="done", step="done")
            _daemon_ns._log_event(
                app, "exec",
                f"local model installed: {plan['model_label']} "
                f"{plan['quant']} ctx={ctx} → ladder lower rungs",
                source="localllm", actor="user",
                payload={"quant": plan["quant"], "ctx": ctx,
                         "healthy": healthy,
                         "candidate_id": plan.get("candidate_id")},
            )
            await _daemon_ns._broadcast(app, protocol.notice(
                f"{plan['model_label']} installed ({plan['quant']}, "
                f"{ctx // 1024}k context)"
                + ("" if healthy else " — still loading")
                + ". GLOBAL ladder trivial + normal → local; "
                "planning/review keeps your best provider.",
                kind="chat",
            ))
        except Exception as e:  # noqa: BLE001
            log.exception("local model install failed")
            rec.update(state="error", error=str(e))
            await _daemon_ns._broadcast(app, protocol.notice(
                f"local model install failed: {e}", kind="chat",
            ))

    asyncio.create_task(_worker())
    return web.json_response({
        "ok": True, "started": True, "ctx": ctx,
        "candidate_id": plan.get("candidate_id"),
    })

async def _install_mlx_model(
    app: web.Application, cand: dict[str, Any], *, ctx: int,
) -> web.Response:
    """Install an MLX model: ensure mlx-lm, then start its server.

    Unlike GGUF there is no file to fetch ourselves — `mlx_lm.server`
    resolves the HF repo and manages its own weight cache, so the
    "download" is the server's first load. We register it, point the
    ladder's lower rungs at it, and wait for the port to answer.
    """
    if not local_models.mlx_supported():
        return web.json_response(
            {"error": local_models.mlx_status().get("reason")}, status=400)
    if not local_models.mlx_binary():
        return web.json_response({"error": (
            "mlx-lm isn't installed. Install it with "
            "`uv tool install mlx-lm` (or `pip install mlx-lm`) and retry."
        )}, status=400)

    cid = str(cand["id"])
    repo = str(cand["repo"])
    alias = re.sub(r"[^a-zA-Z0-9_]+", "_", str(cand["label"]))[:24] or "mlx"
    rec: dict[str, Any] = {
        "state": "running", "step": f"starting mlx_lm.server ({repo})",
        "percent": 0, "error": None, "candidate_id": cid,
    }
    app["localllm_install"] = rec

    async def _worker() -> None:
        try:
            port = await asyncio.to_thread(local_models.allocate_mlx_port)
            cfg = {
                "model": repo,
                "model_label": cand["label"],
                "quant": cand.get("quant"),
                "repo": repo,
                "backend": "mlx",
                "ctx": ctx,
                "port": port,
                "alias": alias,
                "installed_at": time.time(),
                "candidate_id": cid,
            }
            await asyncio.to_thread(localllm.save_config, cfg)
            await asyncio.to_thread(
                local_models.register_installed,
                cid,
                {
                    "label": cand["label"],
                    "backend": "mlx",
                    "repo": repo,
                    "quant": cand.get("quant"),
                    "ctx": ctx,
                    "alias": alias,
                    "port": port,
                },
                activate=False,
            )
            await localllm.spawn_server(app, cfg)
            rec["step"] = "downloading weights + loading (first run is slow)"
            rec["percent"] = 0
            target_bytes = float(cand.get("weights_gb") or 0) * (1024 ** 3)
            deadline = time.time() + 1800
            healthy = False
            while time.time() < deadline:
                if await localllm.server_healthy(port=port):
                    healthy = True
                    rec["percent"] = 100
                    rec["step"] = "server ready"
                    break
                got = await asyncio.to_thread(local_models.mlx_cache_bytes, repo)
                gb = got / (1024 ** 3)
                if target_bytes > 0 and got > 0:
                    rec["percent"] = min(99, int(got / target_bytes * 100))
                    rec["step"] = (
                        f"downloading weights {gb:.2f} GB ({rec['percent']}%)"
                    )
                elif got > 0:
                    rec["percent"] = min(90, 5 + int(min(gb, 20) / 20 * 85))
                    rec["step"] = f"downloading weights ({gb:.2f} GB)"
                else:
                    rec["step"] = "downloading weights + loading (first run is slow)"
                await asyncio.sleep(2)
            if healthy:
                cfg = await localllm.remember_mlx_served_model(cfg)
            if not healthy:
                rec.update(
                    state="error",
                    error="server did not become healthy (download or load timed out)",
                )
                await _daemon_ns._broadcast(app, protocol.notice(
                    f"MLX install of {cand['label']} timed out — "
                    "use Start in Settings once the download finishes.",
                    kind="chat"))
                return
            await asyncio.to_thread(
                local_models.register_installed,
                cid,
                {
                    "label": cand["label"],
                    "backend": "mlx",
                    "repo": repo,
                    "quant": cand.get("quant"),
                    "ctx": ctx,
                    "alias": alias,
                    "port": port,
                },
                activate=True,
            )
            ladder = await asyncio.to_thread(modestore.global_ladder)
            ladder["trivial"] = {"provider": "mlx", "model": alias}
            ladder["normal"] = {"provider": "mlx", "model": alias}
            await asyncio.to_thread(modestore.set_global_ladder, ladder)
            rec.update(state="done", step="done", percent=100)
            _daemon_ns._log_event(
                app, "exec",
                f"MLX model installed: {cand['label']} ctx={ctx} → ladder lower rungs",
                source="localllm", actor="user",
                payload={"repo": repo, "ctx": ctx, "healthy": healthy,
                         "candidate_id": cid},
            )
            await _daemon_ns._broadcast(app, protocol.notice(
                f"{cand['label']} ready on MLX ({ctx // 1024}k context). "
                "GLOBAL ladder trivial + normal → mlx.",
                kind="chat",
            ))
        except Exception as e:  # noqa: BLE001
            log.exception("mlx install failed")
            rec.update(state="error", error=str(e))
            await _daemon_ns._broadcast(app, protocol.notice(
                f"MLX install failed: {e}", kind="chat"))

    asyncio.create_task(_worker())
    return web.json_response({
        "ok": True, "started": True, "ctx": ctx, "candidate_id": cid,
        "backend": "mlx",
    })

async def _install_ollama_model(
    app: web.Application, entry: dict[str, Any],
) -> web.Response:
    tag = str(entry.get("ollama_tag") or "")
    if not tag:
        return web.json_response({"error": "no ollama tag"}, status=400)
    rec: dict[str, Any] = {
        "state": "running", "step": f"ollama pull {tag}", "percent": 0, "error": None,
        "candidate_id": entry["id"],
    }
    app["localllm_install"] = rec

    async def _worker() -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ollama", "pull", tag,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").strip()
                if line:
                    rec["step"] = line[:120]
            rc = await proc.wait()
            if rc != 0:
                raise RuntimeError(f"ollama pull failed (rc={rc})")
            await asyncio.to_thread(
                local_models.register_installed,
                entry["id"],
                {
                    "label": entry["label"],
                    "backend": "ollama",
                    "ollama_tag": tag,
                },
                activate=False,
            )
            ladder = await asyncio.to_thread(modestore.global_ladder)
            ladder["trivial"] = {"provider": "ollama", "model": tag}
            ladder["normal"] = {"provider": "ollama", "model": tag}
            await asyncio.to_thread(modestore.set_global_ladder, ladder)
            rec.update(state="done", step="done")
            await _daemon_ns._broadcast(app, protocol.notice(
                f"Ollama model {tag} ready — ladder trivial+normal → ollama/{tag}.",
                kind="chat",
            ))
        except Exception as e:  # noqa: BLE001
            log.exception("ollama install failed")
            rec.update(state="error", error=str(e))
            await _daemon_ns._broadcast(app, protocol.notice(
                f"ollama install failed: {e}", kind="chat",
            ))

    asyncio.create_task(_worker())
    return web.json_response({"ok": True, "started": True, "ollama_tag": tag})
