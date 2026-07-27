"""Codex resume re-injects system prompt (focus freshness)."""

from __future__ import annotations

import ast
from pathlib import Path


def test_codex_source_re_injects_system_on_resume():
    """Guard against regressing to first-turn-only system fold-in."""
    src = Path("src/switchbay/llmgateway/openai_codex.py").read_text(
        encoding="utf-8",
    )
    assert "system-update" in src
    assert "resume_id" in src
    # Parse to ensure file still valid Python
    ast.parse(src)
