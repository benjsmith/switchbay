"""Harness plugs: one node, one model conversation.

Pi and Grok Build are two implementations of the same package job.
The kernel must not care which plug is in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol




@dataclass
class NodeRequest:
    package_id: str
    system: str
    user: str
    tools: list[str]
    provider_id: str
    model: str | None
    workspace: Path
    session_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class NodeResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    session_id: str | None = None
    error: str | None = None
    harness: str = "rail"
    tool_trace: list[str] = field(default_factory=list)


class NodeHarness(Protocol):
    name: str

    async def run(self, req: NodeRequest) -> NodeResult: ...


# Full CLI agents — never nested under Pi.
CLI_HARNESSES = frozenset({"grok-build", "claude-code", "openai-codex", "muse-code"})
# HTTP model providers Pi can drive (xAI API, not Grok Build).
PI_MODEL_PROVIDERS = frozenset({
    "xai", "anthropic", "openai", "google", "gemini", "mlx",
})


def pi_harness_permitted() -> bool:
    """Admin flag and user Settings toggle. Binary presence is separate."""
    try:
        from .. import admin_policy
        if not admin_policy.feature_enabled("pi_harness"):
            return False
    except Exception:  # noqa: BLE001
        return False
    try:
        from .. import llm_config
        if not llm_config.get_pi_harness():
            return False
    except Exception:  # noqa: BLE001
        return False
    return True


def pi_available() -> bool:
    if not pi_harness_permitted():
        return False
    from .harness_pi import pi_binary
    return pi_binary() is not None


def pick_harness(
    package_id: str,
    provider_id: str | None,
    *,
    pi_available: bool | None = None,
) -> str:
    """One harness per node. Grok Build is never Pi. xAI API under Pi is fine.
    """
    pid = str(provider_id or "")
    if pid in CLI_HARNESSES:
        return pid
    use_pi = pi_available if pi_available is not None else globals()["pi_available"]()
    if use_pi and pid in PI_MODEL_PROVIDERS:
        return "pi"
    return "rail"


async def run_node(req: NodeRequest, *, harness: str | None = None) -> NodeResult:
    name = harness or pick_harness(req.package_id, req.provider_id)
    impl = _impl(name)
    result = await impl.run(req)
    result.harness = name
    return result


def _impl(name: str) -> NodeHarness:
    if name == "pi":
        from .harness_pi import PiHarness
        return PiHarness()
    if name == "grok-build":
        from .harness_grok import GrokBuildHarness
        return GrokBuildHarness()
    from .harness_rail import RailHarness
    return RailHarness()
