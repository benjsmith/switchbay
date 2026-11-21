"""Permission prompts and the web-egress policy routes.

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
import os
import re
import shutil
from aiohttp import web
from switchbay import conversations
from switchbay import permissions
from switchbay import protocol
from switchbay import workspaces

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_permission_request(request: web.Request) -> web.Response:
    """Hook subprocess (claude-code PreToolUse / codex sandbox-denial
    bridge) posts here with `{provider, tool, input, run_id}` and
    long-polls for the verdict. Returns `{decision: approve|deny,
    remember: bool}` once the user clicks in the rail.

    Pre-approved patterns short-circuit without bothering the user —
    that's the whole point of "Approve + remember"."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    provider = str(body.get("provider") or "").strip() or "?"
    tool = str(body.get("tool") or "").strip()
    tool_input = body.get("input") or {}
    run_id = body.get("run_id")
    if not tool:
        return web.json_response({"error": "tool required"}, status=400)
    if not isinstance(tool_input, dict):
        tool_input = {}

    # Ownership: which rail thread (if any) spawned this CLI session?
    # Primary signal is the CSWY_THREAD_ID the daemon exported at spawn
    # (forwarded by the hook as `origin_thread`); fallback is a reverse
    # lookup of the CLI session id in llm_sessions (covers resumed
    # turns from spawns that predate the env plumbing). No match =
    # external session (bench, scripts) — the card renders in the
    # rail's out-of-thread approvals strip instead of any transcript.
    thread_id = str(body.get("origin_thread") or "").strip() or None
    if thread_id is None and isinstance(run_id, str) and run_id:
        sessions: dict[str, str] = request.app.get("llm_sessions") or {}
        thread_id = next(
            (t for t, s in sessions.items() if s == run_id), None,
        )
    origin: str | None = None
    origin_path: str | None = None
    if thread_id is None:
        # External request: do permission bookkeeping (pre-approve
        # lookups + "remember" writes) against the ORIGIN workspace,
        # not whatever workspace the UI happens to be focused on.
        cwd = str(body.get("cwd") or "").strip()
        cwd_path = Path(cwd) if cwd else None
        if (
            cwd_path is not None and cwd_path.is_absolute()
            and cwd_path.is_dir() and workspaces.is_within_home(cwd_path)
        ):
            workspace = cwd_path.resolve()
            origin_path = str(workspace)
        home = str(Path.home())
        label = cwd or provider
        if label.startswith(home):
            label = "~" + label[len(home):]
        origin = label

        # Muted source: the user chose to stop this external session's
        # approvals from coming through the rail. Skip without a card —
        # `skip` tells the (new) hook to fall through to the spawned
        # CLI's OWN static allowlist (old hooks read it as deny). Keyed
        # by the display label so it survives per-session run-id churn.
        muted: set[str] = request.app.setdefault("muted_origins", set())
        if origin in muted:
            # Protected egress must fail closed — never skip into the
            # CLI's static allowlist.
            if permissions.needs_web_consent(tool, tool_input):
                return web.json_response({
                    "decision": "deny",
                    "remember": False,
                    "muted": True,
                    "reason": "web egress denied",
                })
            return web.json_response({"decision": "skip", "muted": True})

    # Hard deny home/FS-wide scans BEFORE pre-approve / cards — agents
    # must not be able to "Approve + remember" a `find /Users` that
    # trips macOS "access data from other apps" dialogs.
    deny_reason = permissions.hard_deny_reason(tool, tool_input)
    if deny_reason:
        log.warning(
            "hard-denied %s tool=%s: %s",
            provider, tool, (tool_input.get("command") or "")[:120],
        )
        return web.json_response({
            "decision": "deny",
            "remember": False,
            "hard": True,
            "reason": deny_reason,
        })

    if permissions.needs_web_consent(tool, tool_input):
        blocked = permissions.web_egress_block_reason(workspace, tool, tool_input)
        if blocked:
            return web.json_response({
                "decision": "deny",
                "remember": False,
                "reason": blocked,
            })
        # Policy on: per-call card. Never short-circuit via allow-list.
    else:
        pattern = permissions.pattern_for(tool, tool_input)
        if permissions.is_pre_approved(
            workspace, pattern, tool=tool, tool_input=tool_input,
        ):
            return web.json_response({"decision": "approve", "remember": True, "cached": True})

    pattern = permissions.pattern_for(tool, tool_input)

    rec = permissions.register(
        workspace=workspace, provider=provider, tool=tool,
        tool_input=tool_input,
        run_id=str(run_id) if isinstance(run_id, str) else None,
        thread_id=thread_id, origin=origin, origin_path=origin_path,
    )
    await _daemon_ns._broadcast(request.app, protocol.permission_request(
        req_id=rec.req_id, provider=provider, tool=tool,
        tool_input=tool_input, pattern=rec.pattern, run_id=rec.run_id,
        thread_id=rec.thread_id, origin=rec.origin, origin_path=rec.origin_path,
        protected=permissions.is_protected_egress(tool),
    ))
    decision = await permissions.await_decision(rec)
    # Tell the frontend the card is settled even when await_decision
    # auto-denied on TIMEOUT (the user-click path broadcasts from
    # handle_permission_decide; the timeout path didn't, leaving a stale
    # "pending" card that does nothing when clicked). Idempotent with the
    # click-path broadcast.
    await _daemon_ns._broadcast(request.app, protocol.permission_resolved(rec.req_id, decision))
    return web.json_response({
        "decision": decision,
        "remember": rec.remember,
        "pattern": rec.pattern,
    })

async def handle_permission_decide(request: web.Request) -> web.Response:
    """Frontend posts `{req_id, decision, remember}` — resolves the
    awaiting hook so the agent can proceed."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    req_id = str(body.get("req_id") or "").strip()
    decision = str(body.get("decision") or "").strip()
    remember = bool(body.get("remember"))
    session = bool(body.get("session"))
    pattern = str(body.get("pattern") or "").strip() or None
    if not req_id or decision not in ("approve", "deny"):
        return web.json_response({"error": "req_id + decision required"}, status=400)
    rec = permissions.resolve(
        req_id, decision=decision, remember=remember,
        pattern=pattern, session=session,
    )
    if rec is None:
        return web.json_response({"ok": False, "note": "request already settled"})
    await _daemon_ns._broadcast(request.app, protocol.permission_resolved(req_id, decision))
    return web.json_response({"ok": True})

async def handle_permission_allow_list(request: web.Request) -> web.Response:
    """List remembered allow patterns for the active workspace."""
    workspace: Path = request.app["workspace"]
    return web.json_response({"patterns": permissions.list_allowed(workspace)})

async def handle_permission_pending(request: web.Request) -> web.Response:
    """Snapshot of undecided permission cards. Cards are in-memory only
    (they settle within the hook's long-poll), so thread hydration and
    reconnects re-offer them from here instead of losing them."""
    muted: set[str] = request.app.get("muted_origins") or set()
    return web.json_response({
        "pending": [
            {
                "req_id": rec.req_id,
                "provider": rec.provider,
                "tool": rec.tool,
                "tool_input": rec.tool_input,
                "pattern": rec.pattern,
                "run_id": rec.run_id,
                "thread_id": rec.thread_id,
                "origin": rec.origin,
                "origin_path": rec.origin_path,
                "created_at": rec.created_at,
            }
            for rec in permissions.list_pending()
            if rec.decision is None
        ],
        "muted_origins": sorted(muted),
    })

async def handle_permission_mute(request: web.Request) -> web.Response:
    """Mute (or unmute) an external source so its approval requests
    stop coming through the rail. `{origin, muted: bool}`. Muting also
    settles any of that source's currently-pending cards (decision
    `skip` → the CLI's own allowlist decides) so the strip clears at
    once. In-memory + per-daemon: cleared on restart, which is the
    right lifetime for a transient external run (a bench sweep, a
    script)."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    origin = str(body.get("origin") or "").strip()
    if not origin:
        return web.json_response({"error": "origin required"}, status=400)
    want_muted = bool(body.get("muted", True))
    muted: set[str] = request.app.setdefault("muted_origins", set())
    if want_muted:
        muted.add(origin)
        # Clear this source's in-flight cards now.
        for rec in permissions.list_pending():
            if rec.decision is None and rec.origin == origin:
                # Protected cards deny (fail closed). Other tools skip
                # to the CLI allowlist.
                verdict = (
                    "deny"
                    if permissions.needs_web_consent(rec.tool, rec.tool_input)
                    else "skip"
                )
                permissions.resolve(rec.req_id, decision=verdict, remember=False)
                await _daemon_ns._broadcast(
                    request.app, protocol.permission_resolved(rec.req_id, verdict),
                )
    else:
        muted.discard(origin)
    return web.json_response({"ok": True, "muted_origins": sorted(muted)})

async def handle_permission_watch(request: web.Request) -> web.Response:
    """Open a shell rooted at an external source's workspace so the
    user can watch/inspect what that outside session is doing.
    `{origin_path}` — an absolute dir under $HOME. Spawns an
    `interactive-pty` thread (in the daemon's current workspace
    registry) with its cwd set to the source dir, and focuses it."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    raw = str(body.get("origin_path") or "").strip()
    if not raw:
        return web.json_response({"error": "origin_path required"}, status=400)
    p = Path(raw)
    if not (p.is_absolute() and p.is_dir() and workspaces.is_within_home(p)):
        return web.json_response(
            {"error": "origin_path must be an existing dir under home"}, status=400,
        )
    target = p.resolve()
    app = request.app
    workspace: Path = app["workspace"]
    name = f"watch: {target.name}"[:40]
    thread_id = await asyncio.to_thread(
        conversations.new_thread, workspace, name, "interactive-pty",
    )
    app["thread_id"] = thread_id
    app["thread_kind"] = "interactive-pty"
    try:
        await _daemon_ns._spawn_pty_for_thread(app, thread_id, name=name, cwd=target)
    except Exception as e:  # noqa: BLE001
        log.exception("watch-in-shell spawn failed")
        return web.json_response({"error": str(e)}, status=500)
    await _daemon_ns._broadcast(app, protocol.thread_focused(
        thread_id, "interactive-pty", workspace=str(workspace),
    ))
    return web.json_response({"ok": True, "thread_id": thread_id})

async def handle_permission_allow_add(request: web.Request) -> web.Response:
    """Add a pattern directly. Used by Settings controls (e.g. the
    Codex elevated-sandbox toggle) that express a permanent intent
    without needing to be paired with a live tool-call request."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    pattern = str(body.get("pattern") or "").strip()
    if not pattern:
        return web.json_response({"error": "pattern required"}, status=400)
    if permissions.is_protected_pattern(pattern):
        return web.json_response({
            "ok": False,
            "error": "web egress cannot be remembered as a blanket grant",
            "patterns": permissions.list_allowed(workspace),
        }, status=400)
    patterns = permissions.add_pattern(workspace, pattern)
    return web.json_response({"ok": True, "patterns": patterns})

async def handle_permission_allow_delete(request: web.Request) -> web.Response:
    """Drop one remembered pattern via `?pattern=<pat>`."""
    workspace: Path = request.app["workspace"]
    pattern = request.query.get("pattern", "").strip()
    if not pattern:
        return web.json_response({"error": "pattern required"}, status=400)
    permissions.revoke(workspace, pattern)
    return web.json_response({"ok": True})

async def handle_web_policy_get(request: web.Request) -> web.Response:
    from switchbay import web_policy as web_policy_mod
    workspace = _daemon_ns._workspace_from_request(request)
    if isinstance(workspace, web.Response):
        return workspace
    return web.json_response(web_policy_mod.public_view(workspace))

async def handle_web_policy_post(request: web.Request) -> web.Response:
    from switchbay import web_policy as web_policy_mod
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    if not isinstance(body, dict) or "enabled" not in body:
        return web.json_response({"error": "enabled required"}, status=400)
    workspace = _daemon_ns._workspace_from_request(request, body)
    if isinstance(workspace, web.Response):
        return workspace
    want = bool(body.get("enabled"))
    if want and not web_policy_mod.admin_allows():
        view = web_policy_mod.public_view(workspace)
        return web.json_response({
            "error": "web egress is disabled by admin policy",
            **view,
        }, status=403)
    web_policy_mod.save(workspace, enabled=want)
    view = web_policy_mod.public_view(workspace)
    await _daemon_ns._broadcast(request.app, protocol.web_policy_state({
        "workspace": str(workspace),
        **view,
    }))
    return web.json_response({"ok": True, **view})

async def handle_packs_registry(request: web.Request) -> web.Response:
    """Curated registry of known packs the user can browse + install.

    Default source: the `packs/registry.json` file bundled with
    switchbay. Override via env `CSWY_PACK_REGISTRY` for users /
    organisations that want to run their own list — point it at any
    URL or local-file path that returns the same shape. The
    front-end's Settings → Extension packs → Browse subsection
    consumes this list."""
    override = os.environ.get("CSWY_PACK_REGISTRY", "").strip()
    target: Path | None = None
    if override and (override.startswith("http://") or override.startswith("https://")):
        # Remote registry. Best-effort fetch with a short timeout —
        # falls back to the bundled list if the remote is down.
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    override, timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        body = await resp.json(content_type=None)
                        return web.json_response(body)
        except Exception:  # noqa: BLE001
            log.exception("pack registry fetch failed; falling back to bundled")
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            target = candidate
    if target is None:
        # Walk up from this module to <repo>/packs/registry.json.
        target = Path(_daemon_ns.__file__).resolve().parent.parent.parent / "packs" / "registry.json"
    try:
        body = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return web.json_response(
            {"error": f"could not read registry: {e}", "packs": []},
            status=500,
        )
    return web.json_response(body)

def _find_uv() -> str | None:
    """Locate the `uv` binary. shutil.which first, then common install
    locations — under launchd the daemon's PATH is minimal and may not
    include Homebrew/cargo dirs where uv lives."""
    found = shutil.which("uv")
    if found:
        return found
    for c in (
        Path.home() / ".local" / "bin" / "uv",
        Path("/opt/homebrew/bin/uv"),
        Path("/usr/local/bin/uv"),
        Path.home() / ".cargo" / "bin" / "uv",
    ):
        if c.is_file():
            return str(c)
    return None

async def handle_packs_pip_install(request: web.Request) -> web.Response:
    """Install one (or more) Python extras into switchbay's
    environment. Called from the Settings UI when the user
    activates a pack that declares `requires_extra: […]` and
    confirms the install dialog. Returns the pip output so the
    Settings panel can surface success / failure inline.

    Best-effort: we run `<python> -m pip install <pkg>...` with the
    daemon's interpreter. Users running switchbay via `uv tool
    install` will get those deps installed inside the tool's
    isolated env."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    pkgs_raw = body.get("packages") or []
    if not isinstance(pkgs_raw, list) or not pkgs_raw:
        return web.json_response({"error": "packages required"}, status=400)
    pkgs: list[str] = []
    for p in pkgs_raw:
        s = str(p).strip()
        # Defence-in-depth: only allow standard PEP-508-ish package
        # specifiers — letters, digits, dots, dashes, underscores,
        # square brackets, parens, comparison operators, semver.
        if not s or not re.match(r"^[A-Za-z0-9_.\-\[\]><=!~,\s]+$", s):
            return web.json_response(
                {"error": f"invalid package spec: {s!r}"}, status=400,
            )
        pkgs.append(s)
    import sys as _sys
    # Install into switchbay's venv with `uv pip install` — uv-created
    # venvs don't ship `pip`, so `python -m pip` fails with "No module
    # named pip". `--python <interp>` targets this venv explicitly. Fall
    # back to `python -m pip` only if uv truly isn't available.
    uv = _find_uv()
    if uv:
        cmd = [uv, "pip", "install", "--python", _sys.executable, "--upgrade", *pkgs]
    else:
        cmd = [_sys.executable, "-m", "pip", "install", "--upgrade", *pkgs]
    log.info("pack install (%s): %s", "uv" if uv else "pip", " ".join(pkgs))
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600.0)
    except asyncio.TimeoutError:
        return web.json_response(
            {"ok": False, "error": "install timed out after 10 minutes"},
            status=504,
        )
    except FileNotFoundError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)
    ok = proc.returncode == 0
    return web.json_response({
        "ok": ok,
        "returncode": proc.returncode,
        "stdout": stdout.decode("utf-8", errors="replace")[-4000:],
        "stderr": stderr.decode("utf-8", errors="replace")[-4000:],
        "packages": pkgs,
    })
