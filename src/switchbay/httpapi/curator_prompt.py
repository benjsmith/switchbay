"""Curator-profile text loaded into prompts.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
from switchbay import proposals

from switchbay.httpapi._ns import _daemon_ns

_MISSING = object()

def _est_tokens(text: str) -> int:
    return -(-len(text) // _daemon_ns._CHARS_PER_TOKEN_EST)

def _curator_profile(
    workspace: Path, cap_tokens: int = _MISSING,
) -> str:
    """The profile text, capped (by estimated tokens) for prompt
    injection; "" when absent. Sync read — call via to_thread
    (cloud-sync eviction can block)."""
    if cap_tokens is _MISSING:
        cap_tokens = _daemon_ns._CURATOR_PROFILE_CAP_TOKENS
    try:
        text = (workspace / ".curator" / "profile.md").read_text(
            encoding="utf-8",
        ).strip()
    except OSError:
        return ""
    return text[:cap_tokens * _daemon_ns._CHARS_PER_TOKEN_EST]

def _curator_profile_system(profile: str) -> str:
    """System-side steering from ``.curator/profile.md``. Kept off the
    user transcript so Jump on a failed run does not dump the profile
    into the rail composer."""
    if not profile:
        return ""
    return (
        "Workspace curator profile (user-authored steering — honor it "
        "when deciding what counts as an entity or knowledge in this "
        f"workspace):\n{profile}"
    )

def _review_feedback_system(workspace: Path) -> str:
    """Honor recent Reviews comments on the next curation wave."""
    try:
        lines = proposals.recent_review_feedback(workspace)
    except Exception:  # noqa: BLE001
        return ""
    if not lines:
        return ""
    body = "\n".join(f"- {ln}" for ln in lines)
    return (
        "Reviewer feedback from recent Reviews (honor when writing or "
        "revising pages; do not wait for more review):\n" + body
    )
