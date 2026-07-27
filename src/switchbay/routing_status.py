"""Effective LLM routing, for honest display in the rail picker.

The rail's model picker shows one headline provider+model (the
default / picker selection). Everything the user types in the rail runs
on it. But two subsystems deliberately route elsewhere, and the picker
should say so — "displayed == what runs".

**CE curation ladder (2026-07-24 reframe).** The model ladder is a
CE-curation-only construct with three roles:

  · **orchestrator** (`hard` rung) — the top-level curate/ingest agent.
    Defaults to the picker; only a *pinned* hard rung is an override.
  · **workers** (`normal` rung) — CE fan-out workers.
  · **sub-tasks** (`trivial` rung) — cheap CE sub-calls.

**Micro-edits.** Short, edit-shaped rail messages with a live tab
focused. They have their OWN fast-model setting now (decoupled from the
ladder); unset → they follow the picker.

This module computes those routes so the picker can surface any that
differ from the headline, plus a **risk warning**: a CE rung that pairs
a WEAK model with an execute-capable provider (a small model is more
likely to misuse a destructive tool — Session 33 saw a local model try
to delete a charter it had just read a "preserve" ruling for).

Pure functions over (workspace, config); kept out of daemon.py so it is
unit-testable without a running server.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import llmgateway, micro_edits, modestore


# Model-id fragments that mark a small / fast / cheap tier.
_WEAK_MODEL_RE = re.compile(
    r"(?:^|[-_/])(?:"
    r"haiku|mini|nano|flash|lite|small|fast|tiny|"
    r"composer|"                       # grok-composer (fast tier)
    r"\d+b"                            # 7b / 8b / 13b … local GGUFs
    r")(?:[-_/.]|$)",
    re.IGNORECASE,
)


def _provider_label(pid: str) -> str:
    try:
        return str(llmgateway.get(pid).LABEL)
    except Exception:  # noqa: BLE001
        return pid


def is_weak_model(model: str) -> bool:
    """Heuristic: does this model id look like a small/fast tier?"""
    return bool(model) and bool(_WEAK_MODEL_RE.search(model))


def _effective_static_model(pid: str) -> str:
    from . import llm_config

    user = llm_config.get_model(pid)
    if user:
        return user
    try:
        return str(llmgateway.get(pid).PROVIDER.get("default_model", ""))
    except Exception:  # noqa: BLE001
        return ""


def _rung_route(
    workspace: Path, rung: str,
) -> tuple[str | None, str | None]:
    """(provider, model) a CE ladder rung resolves to, or (None, None)
    when the rung is unset (→ follows the picker)."""
    pid, model = modestore.resolve_for_difficulty(workspace, rung)
    if not pid:
        return None, None
    if not model:
        model = _effective_static_model(pid)
    return pid, model


def ce_orchestrator_route(workspace: Path) -> tuple[str | None, str | None]:
    """The CE orchestrator (curate/ingest) provider+model, mirroring
    `daemon._ce_action_provider`: the pinned `hard` rung IFF it can
    execute, else (None, None) = follows the picker."""
    pid, model = _rung_route(workspace, "hard")
    if not pid:
        return None, None
    if not llmgateway.can_execute(pid):
        return None, None
    return pid, model


def micro_edit_route(workspace: Path) -> tuple[str | None, str | None]:
    """What micro-edits route to (their own fast-model setting), or
    (None, None) when unset → follows the picker."""
    rung = micro_edits.effective_rung(workspace, None)
    return micro_edits.micro_model_for_rung(workspace, rung)


def compute(
    workspace: Path, default_provider: str, default_model: str,
) -> dict[str, Any]:
    """Full routing summary for the picker.

    Shape:
      {
        "default": {provider, model, provider_label},
        "overrides": [ {kind, label, provider, model, provider_label,
                        reason}, … ],   # routes that DIFFER from the headline
        "warnings":  [ {kind, scope, provider, model, message}, … ],
      }

    A route is included in `overrides` when it names a concrete provider
    (a pinned CE rung, or a micro-edit fast model). An unset rung follows
    the picker and is not listed — the picker headline already shows it.
    """
    default_model = default_model or _effective_static_model(default_provider)
    out: dict[str, Any] = {
        "default": {
            "provider": default_provider,
            "model": default_model,
            "provider_label": _provider_label(default_provider),
        },
        "overrides": [],
        "warnings": [],
    }

    # CE curation ladder + micro-edits. Each entry: (kind, label,
    # (pid, model), reason, is_ce_exec) — is_ce_exec marks the CE rungs
    # that run with scoped shell (candidates for the weak-model warning).
    routes = [
        ("ce-orchestrator", "Curate (orchestrator)",
         ce_orchestrator_route(workspace), "pinned hard rung", True),
        ("ce-workers", "CE workers",
         _rung_route(workspace, "normal"), "CE fan-out normal rung", True),
        ("ce-subtasks", "CE sub-tasks",
         _rung_route(workspace, "trivial"), "CE fan-out trivial rung", True),
        ("micro-edit", "Micro-edits",
         micro_edit_route(workspace), "micro-edit fast model", False),
    ]
    for kind, label, (pid, model), reason, is_ce_exec in routes:
        if not pid:
            continue
        out["overrides"].append({
            "kind": kind,
            "label": label,
            "provider": pid,
            "model": model,
            "provider_label": _provider_label(pid),
            "reason": reason,
        })
        # Weak-model-with-destructive-scope risk: only the CE rungs run
        # with scoped shell/edit/write, and only an execute-capable
        # provider has a destructive tool to misuse.
        if (is_ce_exec and llmgateway.can_execute(pid)
                and is_weak_model(model or "")):
            out["warnings"].append({
                "kind": "weak-destructive",
                "scope": kind,
                "provider": pid,
                "model": model,
                "message": (
                    f"{label} runs on {_provider_label(pid)} · {model} — a "
                    "fast/low-cost tier that here ALSO has file-write and "
                    "scoped-shell access. Smaller models are more error-prone "
                    "with tools that can change files, so prefer a stronger "
                    "model for this rung. (This flags tool scope, not raw "
                    "quality: propose-only providers — local models and plain "
                    "APIs — never warn, since they can't run destructive "
                    "tools even when small.)"
                ),
            })
    return out
