"""Limit-robust llm_call wrapper for long unattended bench runs.

Subscription/API limits are time-recoverable: on a limit-shaped provider
error, sleep and retry until the window resets (auto-resume), bounded by a
patience budget. Non-limit errors raise immediately (llm_call already did
its transient retries).
"""

from __future__ import annotations

import re
import time
from typing import Callable

# Error text that means "wait and the call will succeed later".
_LIMIT_RE = re.compile(
    r"(?i)(usage limit|rate.?limit|too many requests|429|quota|overload|"
    r"capacity|resets? at|limit (?:reached|exceeded)|exhaust|try again later|"
    r"session limit|(?:hit|reached) (?:your|the) [^\n]{0,40}limit|"
    r"5.?hour|weekly limit)"
)


class LimitPatienceExceeded(RuntimeError):
    pass


def is_limit_error(text: str) -> bool:
    return bool(_LIMIT_RE.search(text or ""))


def robust_llm_call(
    provider: str,
    prompt: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
    workspace: str | None = None,
    limit_sleep_s: int = 1800,
    limit_patience_h: float = 12.0,
    log: Callable[[str], None] = print,
    _sleep=time.sleep,
) -> str:
    """Return text or raise. Sleeps through provider limit windows."""
    from bench import llm

    waited = 0.0
    while True:
        text, ok = llm.llm_call(
            provider, prompt, model=model, max_tokens=max_tokens,
            temperature=temperature, workspace=workspace,
        )
        if ok:
            return text or ""
        err = text or "[unknown provider error]"
        if not is_limit_error(err):
            raise RuntimeError(f"provider error [{provider}]: {err[:300]}")
        if waited >= limit_patience_h * 3600:
            raise LimitPatienceExceeded(
                f"[{provider}] still limited after {waited / 3600:.1f}h: {err[:200]}"
            )
        log(
            f"[limit] {provider} limited ({err[:120]!r}) — sleeping "
            f"{limit_sleep_s}s then auto-resuming "
            f"({waited / 3600:.1f}h/{limit_patience_h}h patience used)"
        )
        _sleep(limit_sleep_s)
        waited += limit_sleep_s
