"""MLX (Apple silicon local) provider — the daemon-managed mlx_lm server.

On an M-series Mac, MLX runs quantised weights directly against unified
memory and Metal: no GGUF conversion step, no separate GPU copy of the
weights, and the whole of RAM is addressable by the model. For a machine
that has it, this is the native local path — `llamacpp` remains the
portable one.

`mlx_lm.server` exposes the same OpenAI-compatible chat-completions API
as `llama-server`, and the daemon spawns it through the same
``localllm.spawn_server`` slot machinery (see ``localllm.server_args``,
which branches on ``cfg["backend"]``). So the wire protocol is already
implemented: this module is a distinct provider identity — its own id,
label, capabilities and readiness check — over ``llamacpp``'s streaming
implementation, rather than a second copy of it.

Registered only as a provider id; ``has_key`` gates it to Apple silicon
with mlx-lm actually installed, so it stays invisible everywhere else.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from . import base, llamacpp
from .. import local_models, localllm

log = logging.getLogger("switchbay.llm.mlx")

ID = "mlx"
LABEL = "MLX (Apple silicon)"
DEFAULT_MODEL = "local"
DEFAULT_TIMEOUT_S = llamacpp.DEFAULT_TIMEOUT_S

PROVIDER = {
    "id": ID,
    "label": LABEL,
    "category": "local",
    "default_model": DEFAULT_MODEL,
    "auth_help": (
        "Apple-silicon local models — Settings → Local agent model → "
        "MLX. Needs `mlx-lm` on PATH (`uv tool install mlx-lm`); paste "
        "any mlx-community repo id, or pick one of the suggestions."
    ),
    "model_suggestions": [],  # filled live from installed MLX models
    "capabilities": {
        "chat": True,
        "streaming": True,
        # mlx_lm.server renders the model's own chat template and parses
        # tool calls back out, same contract as llama-server --jinja.
        "tools": True,
        # Execution surface — see base.CAPABILITY_NOTES.
        # local HTTP: switchbay tool registry only.
        "shell": False,
        "file_write": False,
        "key_validation": True,
    },
}


def supported() -> bool:
    """Apple silicon with mlx-lm installed."""
    return local_models.mlx_installed()


def has_key() -> bool:
    """Configured = an MLX model is the active local config AND the
    runtime is present. Unlike a hosted provider there's no credential;
    readiness is "the server can actually start"."""
    if not supported():
        return False
    cfg = localllm.load_config()
    return bool(cfg and cfg.get("backend") == "mlx")


def reasoning_options(model: str | None = None) -> list[dict]:
    """Same two-state thinking toggle as llamacpp — `mlx_lm.server`
    renders the model's own chat template, so the control is the
    template's `enable_thinking` boolean either way."""
    return llamacpp.reasoning_options(model)


async def chat_stream(req: base.ChatRequest) -> AsyncIterator[base.ChunkEvent]:
    """Delegate to the llama.cpp streaming path.

    Both servers speak OpenAI chat-completions on a loopback port, and
    ``llamacpp.chat_stream`` resolves that port from the active
    ``localllm`` config — which, for an MLX model, is the MLX slot. A
    second implementation here would only be a copy that drifts.
    """
    async for chunk in llamacpp.chat_stream(req):
        yield chunk


async def list_models() -> list[str]:
    """Installed MLX models, by alias (what the ladder addresses)."""
    out: list[str] = []
    for meta in local_models.list_installed():
        if meta.get("backend") != "mlx":
            continue
        alias = meta.get("alias") or meta.get("repo") or meta.get("id")
        if alias:
            out.append(str(alias))
    return out


async def validate_key(*, workspace: str | None = None) -> bool:
    """Healthy when the managed MLX server answers on its port."""
    if not has_key():
        return False
    cfg = localllm.load_config() or {}
    return await localllm.server_healthy(port=cfg.get("port"))
