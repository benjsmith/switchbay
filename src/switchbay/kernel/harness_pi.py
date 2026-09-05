"""Pi RPC harness. Optional binary; never a product lockfile pin.

Grok *models* go through Pi's xAI HTTP provider. Grok Build CLI is a
different harness and is never spawned from here.

Do not pass --offline when talking to a model API — that flag blocks
the xAI request as well as telemetry.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import sys
from pathlib import Path

from .harness import CLI_HARNESSES, NodeRequest, NodeResult
from .packages import get_package, package_tool_names

PACK_ROOT = Path(__file__).resolve().parent / "pi_packages"
REPO_ROOT = Path(__file__).resolve().parents[3]
SPIKE_PI = REPO_ROOT / ".local" / "pi-spike" / "node_modules" / ".bin" / "pi"

# Switch Bay provider id → Pi --provider id
_PI_PROVIDER = {
    "xai": "xai",
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "google",
    "gemini": "google",
    "mlx": "mlx",
}


def pi_binary() -> str | None:
    env = (os.environ.get("SWITCHBAY_PI") or "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            return str(p)
    found = shutil.which("pi")
    if found:
        return found
    if SPIKE_PI.is_file():
        return str(SPIKE_PI)
    return None


def pack_extension(package_id: str) -> Path | None:
    pkg = get_package(package_id)
    if pkg is None:
        return None
    path = PACK_ROOT / pkg.pi_extension
    return path if path.is_file() else None


def pi_provider_id(switchbay_provider: str | None) -> str | None:
    pid = str(switchbay_provider or "")
    if pid in CLI_HARNESSES or pid == "github_copilot":
        return None
    return _PI_PROVIDER.get(pid)


_PROVIDER_KEY_ENV: dict[str, tuple[tuple[str, str], ...]] = {
    "xai": (("XAI_API_KEY", "xai"),),
    "anthropic": (("ANTHROPIC_API_KEY", "anthropic"),),
    "openai": (("OPENAI_API_KEY", "openai"),),
    "google": (("GEMINI_API_KEY", "gemini"), ("GOOGLE_API_KEY", "gemini")),
    "gemini": (("GEMINI_API_KEY", "gemini"), ("GOOGLE_API_KEY", "gemini")),
}


def _inject_provider_key(env: dict[str, str], req: NodeRequest) -> None:
    pid = str(req.provider_id or "")
    pairs = list(_PROVIDER_KEY_ENV.get(pid) or ())
    if (req.model or "").startswith("grok") and pid != "xai":
        pairs = list(pairs) + [("XAI_API_KEY", "xai")]
    if not pairs:
        return
    try:
        from .. import secrets
    except Exception:  # noqa: BLE001
        secrets = None  # type: ignore[assignment]
    for env_name, secret_id in pairs:
        if env.get(env_name):
            continue
        key = None
        if secrets is not None:
            try:
                key = secrets.get(secret_id)
            except Exception:  # noqa: BLE001
                key = None
        if not key:
            key = os.environ.get(env_name)
        if key:
            env[env_name] = key


def spawn_env(req: NodeRequest) -> dict[str, str]:
    env = os.environ.copy()
    env["PI_TELEMETRY"] = "0"
    env["PI_SKIP_VERSION_CHECK"] = "1"
    env.pop("PI_OFFLINE", None)
    src = str(Path(__file__).resolve().parents[2])
    # Always absolute: a relative PYTHONPATH=src from the repo root
    # breaks when Pi's cwd is the workspace.
    env["PYTHONPATH"] = src
    env["SWITCHBAY_SRC"] = src
    env["SWITCHBAY_PYTHON"] = env.get("SWITCHBAY_PYTHON") or sys.executable
    tools = package_tool_names(req.package_id, req.tools)
    env["SWITCHBAY_PACKAGE_ID"] = req.package_id
    env["SWITCHBAY_PACKAGE_TOOLS"] = ",".join(tools)
    _inject_provider_key(env, req)
    if req.provider_id == "mlx":
        url, model = mlx_endpoint(req)
        if url and model:
            env["SWITCHBAY_MLX_URL"] = url
            env["SWITCHBAY_MLX_MODEL"] = model
    return env


def mlx_endpoint(req: NodeRequest) -> tuple[str, str]:
    """OpenAI-compat URL + model id for Pi's registered mlx provider.

    Distinct from Pi's llama.cpp GGUF router (LLAMA_BASE_URL). mlx_lm.server
    is Switch Bay's Apple-silicon local path. The managed process serves
    one model; a Switch Bay alias 404s, so we send ``default_model``
    unless the caller set ``extra.mlx_model``.
    """
    extra = req.extra or {}
    url = str(extra.get("mlx_url") or "").strip()
    model = str(extra.get("mlx_model") or "").strip()
    try:
        from .. import localllm
        cfg = localllm.load_config() or {}
        if not url:
            url = localllm.server_url_for(cfg).rstrip("/") + "/v1"
        if not model:
            served = str(cfg.get("served_model") or "").strip()
            alias = str(cfg.get("alias") or "")
            asked = str(req.model or "").strip()
            # mlx_lm.server 404s on Switch Bay aliases; /v1/models lists
            # the snapshot path (served_model). Keep an explicit path.
            if asked and asked not in {"default_model", "local", alias}:
                model = asked
            else:
                model = served or "default_model"
    except Exception:  # noqa: BLE001
        if not model:
            model = str(req.model or "default_model").strip()
    return url.rstrip("/") if url else "", model or "default_model"


def pi_argv(req: NodeRequest, *, binary: str, ext: Path) -> list[str]:
    argv = [
        binary,
        "--mode", "rpc",
        "--no-builtin-tools",
        "--no-skills",
        "--no-session",
        "-e", str(ext),
    ]
    # Never --offline: that blocks the xAI HTTP API.
    pi_prov = pi_provider_id(req.provider_id)
    if pi_prov:
        argv.extend(["--provider", pi_prov])
    model = req.model
    if req.provider_id == "mlx":
        _url, mlx_model = mlx_endpoint(req)
        if mlx_model:
            model = mlx_model
    if model:
        argv.extend(["--model", model])
    return argv


def _killpg(proc: asyncio.subprocess.Process, sig: int = signal.SIGTERM) -> None:
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


async def _reap_pi(proc: asyncio.subprocess.Process, *, kill: bool) -> str:
    """Close stdin, optionally kill the process group, always wait."""
    stderr_tail = ""
    try:
        if proc.stderr is not None:
            err_b = await asyncio.wait_for(proc.stderr.read(), timeout=0.4 if kill else 2)
            stderr_tail = err_b.decode("utf-8", errors="replace")[-800:]
    except Exception:  # noqa: BLE001
        pass
    try:
        if proc.stdin and not proc.stdin.is_closing():
            proc.stdin.close()
    except Exception:  # noqa: BLE001
        pass
    if kill and proc.returncode is None:
        _killpg(proc)
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except Exception:  # noqa: BLE001
        _killpg(proc, signal.SIGKILL)
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except Exception:  # noqa: BLE001
            pass
    return stderr_tail


class PiHarness:
    name = "pi"

    async def run(self, req: NodeRequest) -> NodeResult:
        binary = pi_binary()
        if not binary:
            return NodeResult(text="", error="pi binary not on PATH", harness=self.name)
        ext = pack_extension(req.package_id)
        if ext is None:
            return NodeResult(
                text="", error=f"no Pi pack for {req.package_id}", harness=self.name,
            )
        argv = pi_argv(req, binary=binary, ext=ext)
        env = spawn_env(req)
        timeout = float((req.extra or {}).get("timeout_sec") or 600.0)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(req.workspace),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                limit=16 * 1024 * 1024,
                start_new_session=True,
            )
        except FileNotFoundError:
            return NodeResult(text="", error="pi binary not on PATH", harness=self.name)

        message = "\n\n".join(p for p in (req.system.strip(), req.user.strip()) if p)
        payload = json.dumps({
            "id": "job-1",
            "type": "prompt",
            "message": message,
        }) + "\n"
        assert proc.stdin is not None
        proc.stdin.write(payload.encode("utf-8"))
        try:
            await proc.stdin.drain()
        except Exception:  # noqa: BLE001
            pass
        # Keep stdin open until agent_settled. EOF is a shutdown signal
        # and aborts the in-flight xAI turn.

        text_parts: list[str] = []
        tools: list[str] = []
        err: str | None = None
        settled = False
        result: NodeResult | None = None
        try:
            assert proc.stdout is not None
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
                if not line:
                    break
                raw = line.decode("utf-8", errors="replace").strip()
                if not raw:
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                kind = str(ev.get("type") or "")
                if kind == "message_update":
                    inner = ev.get("assistantMessageEvent") or {}
                    if isinstance(inner, dict) and inner.get("type") == "text_delta":
                        delta = inner.get("delta") or ""
                        if isinstance(delta, str) and delta:
                            text_parts.append(delta)
                    elif isinstance(inner, dict) and inner.get("type") == "text_end":
                        content = inner.get("content")
                        if isinstance(content, str) and content and not text_parts:
                            text_parts.append(content)
                elif kind == "message_end":
                    msg = ev.get("message") or {}
                    if msg.get("role") == "assistant":
                        if msg.get("stopReason") == "error" or msg.get("errorMessage"):
                            err = str(msg.get("errorMessage") or "pi model error")[:400]
                        for block in msg.get("content") or []:
                            if isinstance(block, dict) and block.get("type") == "text":
                                t = str(block.get("text") or "")
                                if t and t not in "".join(text_parts):
                                    text_parts.append(t)
                elif kind == "agent_end":
                    for msg in ev.get("messages") or []:
                        if isinstance(msg, dict) and msg.get("errorMessage"):
                            err = str(msg.get("errorMessage"))[:400]
                elif kind == "tool_execution_start":
                    name = str(ev.get("toolName") or ev.get("name") or "")
                    if not name:
                        inner = ev.get("assistantMessageEvent") or {}
                        name = str(inner.get("toolName") or "")
                    if name:
                        tools.append(name)
                elif kind == "agent_settled":
                    settled = True
                    break
                elif kind == "response" and ev.get("success") is False:
                    err = str(ev.get("error") or ev.get("message") or "pi rpc failed")[:400]
                elif kind == "extension_error":
                    err = str(ev.get("error") or ev.get("message") or "extension error")[:400]
        except asyncio.TimeoutError:
            err = "pi rpc timed out"
        except asyncio.CancelledError:
            err = "pi rpc cancelled"
            raise
        finally:
            stderr_tail = await _reap_pi(proc, kill=not settled)
            if not settled and err is None and not text_parts and not tools:
                err = "pi rpc ended before agent_settled (empty turn)"
            if err and stderr_tail:
                err = f"{err}\n{stderr_tail}"[:800]
            elif not text_parts and not tools and not err and stderr_tail:
                err = stderr_tail[:400]
            result = NodeResult(
                text="".join(text_parts),
                error=err,
                harness=self.name,
                tool_trace=tools,
            )
        return result or NodeResult(text="", error=err, harness=self.name, tool_trace=tools)
