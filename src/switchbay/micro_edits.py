"""Micro-edit routing: classify small UI edits, resolve ladder rungs,
seed default ladders, and track first-run feedback policy.

See plan Session micro-edits (2026-07-18): ordinary rail chat ignores
the model ladder; micro-edits (sheet/slide/SQL/plot with live focus)
use a dedicated policy rung (default ``trivial``) so latency/cost drop
without inventing a parallel "fast mode".
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from . import app_settings, atomicio, modestore, sheet_focus, ui_focus

Scope = Literal["thread", "workspace", "global"]
Rung = Literal["trivial", "normal", "hard"]
RUNGS: tuple[Rung, ...] = ("trivial", "normal", "hard")

MAX_MICRO_CHARS = 280

# Edit-shaped language — conservative; long "analyze/explain" fails out.
_EDIT_RE = re.compile(
    r"\b("
    r"change|set|put|add|fix|update|rename|replace|fill|write|"
    r"average|sum|formula|subtitle|title|caption|label|"
    r"sql|query|run|select|icon|image|slide|cell|column|row|"
    r"plot|chart|spec|mean|total"
    r")\b",
    re.I,
)
_EXCLUDE_RE = re.compile(
    r"\b("
    r"analyze|analyse|explain|summarize|summarise|curate|research|"
    r"compare|write\s+a\s+(deck|report|essay)|make\s+slides?\s+from|"
    r"what\s+do\s+we\s+know|how\s+does|why\s+does"
    r")\b",
    re.I,
)

# Per-provider trivial/normal/hard model ids. ``None`` for trivial means
# "same as default_model". Fallbacks keep routing working when a
# suggested fast model isn't on the account.
_PROVIDER_LADDER: dict[str, dict[str, str | None]] = {
    "grok-build": {
        "trivial": "grok-composer-2.5-fast",
        "normal": "grok-4.5",
        "hard": "grok-4.5",
    },
    "claude-code": {
        "trivial": "haiku",
        "normal": "sonnet",
        "hard": "opus",
    },
    "anthropic": {
        "trivial": "claude-haiku-4-5-20251001",
        "normal": "claude-sonnet-4-6",
        "hard": "claude-opus-4-7",
    },
    "openai-codex": {
        "trivial": "gpt-5.4-mini",
        "normal": None,
        "hard": None,
    },
    "openai": {
        "trivial": "gpt-4o-mini",
        "normal": None,
        "hard": None,
    },
    "gemini": {
        "trivial": "gemini-2.5-flash",
        "normal": "gemini-2.5-pro",
        "hard": "gemini-2.5-pro",
    },
    "xai": {
        "trivial": "grok-4.3",
        "normal": None,
        "hard": None,
    },
    "llamacpp": {
        "trivial": "ornith",
        "normal": "ornith",
        "hard": "ornith",
    },
    "ollama": {
        "trivial": None,
        "normal": None,
        "hard": None,
    },
    "github_copilot": {
        "trivial": "gpt-4o-mini",
        "normal": None,
        "hard": None,
    },
}


def _thread_prefs_path(workspace: Path) -> Path:
    return workspace / ".workbench" / "state" / "micro-edits-threads.json"


def _load_thread_prefs(workspace: Path) -> dict[str, Any]:
    p = _thread_prefs_path(workspace)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_thread_prefs(workspace: Path, data: dict[str, Any]) -> None:
    p = _thread_prefs_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, data)


def _ws_micro(workspace: Path) -> dict[str, Any]:
    mode = modestore.load(workspace)
    raw = mode.get("micro_edits")
    return raw if isinstance(raw, dict) else {}


def _global_micro() -> dict[str, Any]:
    raw = app_settings.load().get("micro_edits")
    return raw if isinstance(raw, dict) else {}


def _sanitize_rung(raw: Any) -> Rung | None:
    s = str(raw or "").strip().lower()
    return s if s in RUNGS else None  # type: ignore[return-value]


def effective_rung(workspace: Path, thread_id: str | None) -> Rung:
    """thread > workspace > global > trivial."""
    if thread_id:
        tp = _load_thread_prefs(workspace).get(thread_id)
        if isinstance(tp, dict):
            r = _sanitize_rung(tp.get("rung"))
            if r:
                return r
    r = _sanitize_rung(_ws_micro(workspace).get("rung"))
    if r:
        return r
    r = _sanitize_rung(_global_micro().get("rung"))
    if r:
        return r
    return "trivial"


def feedback_shown(workspace: Path, thread_id: str | None) -> bool:
    """True once the user has answered or dismissed the calibration card
    at any scope that covers this thread (thread/ws/global)."""
    if thread_id:
        tp = _load_thread_prefs(workspace).get(thread_id)
        if isinstance(tp, dict) and tp.get("feedback_shown"):
            return True
    if _ws_micro(workspace).get("feedback_shown"):
        return True
    if _global_micro().get("feedback_shown"):
        return True
    return False


def should_show_feedback(workspace: Path, thread_id: str | None) -> bool:
    return not feedback_shown(workspace, thread_id)


def set_rung(
    scope: Scope,
    workspace: Path,
    thread_id: str | None,
    rung: Rung,
    *,
    mark_feedback: bool = False,
) -> None:
    if rung not in RUNGS:
        raise ValueError(f"invalid rung: {rung}")
    if scope == "thread":
        if not thread_id:
            raise ValueError("thread scope requires thread_id")
        data = _load_thread_prefs(workspace)
        row = dict(data.get(thread_id) or {}) if isinstance(data.get(thread_id), dict) else {}
        row["rung"] = rung
        if mark_feedback:
            row["feedback_shown"] = True
        data[thread_id] = row
        _save_thread_prefs(workspace, data)
        return
    if scope == "workspace":
        path = workspace / ".workbench" / "mode.json"
        if path.is_file():
            try:
                mode = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                mode = dict(modestore.DEFAULT_MODE)
        else:
            mode = dict(modestore.DEFAULT_MODE)
        if not isinstance(mode, dict):
            mode = dict(modestore.DEFAULT_MODE)
        me = dict(mode.get("micro_edits") or {}) if isinstance(mode.get("micro_edits"), dict) else {}
        me["rung"] = rung
        if mark_feedback:
            me["feedback_shown"] = True
        mode["micro_edits"] = me
        path.parent.mkdir(parents=True, exist_ok=True)
        atomicio.write_json_atomic(path, mode)
        return
    # global
    data = app_settings.load()
    me = dict(data.get("micro_edits") or {}) if isinstance(data.get("micro_edits"), dict) else {}
    me["rung"] = rung
    if mark_feedback:
        me["feedback_shown"] = True
    data["micro_edits"] = me
    app_settings.save(data)


def mark_feedback_shown(
    scope: Scope,
    workspace: Path,
    thread_id: str | None,
) -> None:
    """Suppress future cards without changing rung (dismiss / keep)."""
    if scope == "thread":
        if not thread_id:
            return
        data = _load_thread_prefs(workspace)
        row = dict(data.get(thread_id) or {}) if isinstance(data.get(thread_id), dict) else {}
        row["feedback_shown"] = True
        if "rung" not in row:
            row["rung"] = effective_rung(workspace, thread_id)
        data[thread_id] = row
        _save_thread_prefs(workspace, data)
        return
    if scope == "workspace":
        set_rung("workspace", workspace, thread_id, effective_rung(workspace, thread_id), mark_feedback=True)
        return
    set_rung("global", workspace, thread_id, effective_rung(workspace, thread_id), mark_feedback=True)


def next_rung(rung: Rung) -> Rung:
    i = RUNGS.index(rung)
    return RUNGS[min(i + 1, len(RUNGS) - 1)]


def has_live_focus(workspace: Path) -> bool:
    """True if sheet/table/plot/sketch focus is fresh."""
    if sheet_focus.is_fresh(sheet_focus.load(workspace)):
        return True
    for surface in ("table", "plot", "sketch"):
        f = ui_focus.load(workspace, surface)
        if ui_focus.is_fresh(f):
            return True
    return False


def is_micro_edit(workspace: Path, text: str) -> bool:
    """Conservative classifier — prefer false negative over false positive."""
    t = (text or "").strip()
    if not t or len(t) > MAX_MICRO_CHARS:
        return False
    if t.count("\n") >= 4:
        return False
    # Explicit rail prefixes that target live tabs (chat path may still
    # arrive as plain language after interpretation).
    low = t.lower()
    if low.startswith(("!fn ", "!exc ", "!sql ")):
        return has_live_focus(workspace)
    if low.startswith("/"):
        return False  # slash commands handled elsewhere
    if _EXCLUDE_RE.search(t):
        return False
    if not _EDIT_RE.search(t):
        return False
    return has_live_focus(workspace)


def ensure_ladder_defaults(provider_id: str) -> dict[str, dict[str, str]]:
    """No-op since 2026-07-24 — kept for call-site compatibility.

    This used to auto-seed every ladder rung (trivial/normal/hard) to
    the newly-picked provider. That seeding is exactly what created the
    confusing "picker says Opus, curate runs on Grok" state: a rung got
    silently pinned and then overrode the selection. The ladder is now a
    CE-curation-only construct with **follow-the-picker** defaults —
    an unset rung means "use the picker", so there is nothing to seed.
    Users opt into cheaper workers explicitly (Settings → CE curation).
    Returns the current global ladder unchanged."""
    return modestore.global_ladder()


def _micro_models(scope_dict: dict[str, Any]) -> dict[str, Any]:
    m = scope_dict.get("models")
    return m if isinstance(m, dict) else {}


def micro_model_for_rung(
    workspace: Path, rung: Rung,
) -> tuple[str | None, str | None]:
    """The micro-edit model for `rung`, as `(provider, model)`.

    Reads the micro-edit's OWN model map (`micro_edits.models.<rung>`),
    NOT the CE model ladder — micro-edits were decoupled from the ladder
    on 2026-07-24 (the ladder is now a CE-curation-only construct). ws
    overrides global. Returns `(None, None)` when the rung has no model
    configured, which the caller reads as "follow the picker" (no
    downgrade). `model` may be None → the provider's default model."""
    for src in (_ws_micro(workspace), _global_micro()):
        row = _micro_models(src).get(rung)
        if isinstance(row, dict):
            pid = str(row.get("provider") or "").strip()
            if pid:
                model = str(row.get("model") or "").strip()
                return pid, (model or None)
    return None, None


def set_micro_model(
    scope: Scope, workspace: Path, rung: Rung,
    provider: str | None, model: str | None,
) -> None:
    """Persist (or clear, when provider is falsy) the micro-edit model
    for `rung` at the given scope."""
    def _apply(me: dict[str, Any]) -> dict[str, Any]:
        me = dict(me)
        models = dict(_micro_models(me))
        if provider and provider.strip():
            models[rung] = {"provider": provider.strip(), "model": (model or "").strip()}
        else:
            models.pop(rung, None)
        if models:
            me["models"] = models
        else:
            me.pop("models", None)
        return me

    if scope == "global":
        data = app_settings.load()
        data["micro_edits"] = _apply(
            data.get("micro_edits") if isinstance(data.get("micro_edits"), dict) else {})
        app_settings.save(data)
        return
    # workspace scope → mode.json
    path = workspace / ".workbench" / "mode.json"
    mode = modestore.load(workspace)
    mode = dict(mode) if isinstance(mode, dict) else {}
    mode["micro_edits"] = _apply(
        mode.get("micro_edits") if isinstance(mode.get("micro_edits"), dict) else {})
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(path, mode)


def clear_micro_models(scope: Scope, workspace: Path) -> None:
    """Clear ALL micro-edit models at a scope → micro-edits follow the
    picker again (`/micro-edits picker`)."""
    for rung in RUNGS:
        set_micro_model(scope, workspace, rung, None, None)


def resolve_micro_dispatch(
    workspace: Path, thread_id: str | None,
) -> tuple[str, str, Rung] | None:
    """Return (provider_id, model, rung) for a micro-edit, or None to
    run it on the picker/default provider (no downgrade).

    Reads the micro-edit's own model map (decoupled from the CE ladder,
    2026-07-24). Unset → None → the caller leaves provider_override
    unset and the micro-edit runs on the picker, same as ordinary rail
    chat."""
    from . import llmgateway

    rung = effective_rung(workspace, thread_id)
    pid, model = micro_model_for_rung(workspace, rung)
    if not pid:
        return None
    try:
        prov = llmgateway.get(pid)
    except Exception:  # noqa: BLE001
        return None
    if not prov.has_key():
        return None
    if not model:
        model = str(prov.PROVIDER.get("default_model") or "") or None
    if not model:
        return None
    return pid, model, rung


def status_text(workspace: Path, thread_id: str | None) -> str:
    rung = effective_rung(workspace, thread_id)
    pid, model = micro_model_for_rung(workspace, rung)
    lines = [
        f"Micro-edits use tier: **{rung}** "
        f"(thread → workspace → global → trivial).",
    ]
    if pid:
        lines.append(f"Model: **{pid} / {model or '(provider default)'}**.")
    else:
        lines.append(
            "Model: **follows the picker** — no separate micro-edit model set, "
            "so micro-edits run on your selected model like ordinary chat.")
    lines.append(
        f"Feedback card shown: {'yes' if feedback_shown(workspace, thread_id) else 'no'}.")
    lines.append(
        "Set a fast model in Settings → Micro-edits, or "
        "`/micro-edits picker` to clear it (follow the picker again).")
    return "\n".join(lines)


def parse_slash_args(args: str) -> tuple[str, Any]:
    """Return (action, payload) for /micro-edits.

    actions: status | set
    """
    parts = (args or "").strip().split()
    if not parts or parts[0].lower() in ("status", "show", "?"):
        return "status", None
    if parts[0].lower() in ("picker", "off", "clear", "default"):
        # Clear the micro-edit model → follow the picker again.
        return "clear", {"scope": "global"}
    if parts[0].lower() in RUNGS:
        return "set", {"scope": "workspace", "rung": parts[0].lower()}
    if parts[0].lower() in ("global", "workspace", "thread") and len(parts) >= 2:
        scope = parts[0].lower()
        rung = parts[1].lower()
        if rung in RUNGS and scope in ("global", "workspace", "thread"):
            return "set", {"scope": scope, "rung": rung}
    if parts[0].lower() == "reset-feedback":
        return "reset_feedback", None
    return "status", None


def reset_feedback(workspace: Path) -> None:
    """Allow the calibration card to show again (global + workspace)."""
    data = app_settings.load()
    me = dict(data.get("micro_edits") or {}) if isinstance(data.get("micro_edits"), dict) else {}
    me["feedback_shown"] = False
    data["micro_edits"] = me
    app_settings.save(data)
    path = workspace / ".workbench" / "mode.json"
    if path.is_file():
        try:
            mode = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(mode, dict):
            wme = dict(mode.get("micro_edits") or {}) if isinstance(mode.get("micro_edits"), dict) else {}
            wme["feedback_shown"] = False
            mode["micro_edits"] = wme
            atomicio.write_json_atomic(path, mode)


def new_feedback_id() -> str:
    return f"mef-{uuid.uuid4().hex[:10]}"


# In-memory pending feedback cards (run_id / feedback id → context for redo).
_PENDING: dict[str, dict[str, Any]] = {}


def store_pending_feedback(
    feedback_id: str,
    *,
    workspace: Path,
    thread_id: str,
    original_text: str,
    rung_used: Rung,
    provider: str,
    model: str,
) -> None:
    _PENDING[feedback_id] = {
        "workspace": str(workspace),
        "thread_id": thread_id,
        "original_text": original_text,
        "rung_used": rung_used,
        "provider": provider,
        "model": model,
        "created_at": time.time(),
    }
    # Drop stale cards (>1h).
    cutoff = time.time() - 3600
    for k, v in list(_PENDING.items()):
        if float(v.get("created_at") or 0) < cutoff:
            _PENDING.pop(k, None)


def pop_pending_feedback(feedback_id: str) -> dict[str, Any] | None:
    return _PENDING.pop(feedback_id, None)


def get_pending_feedback(feedback_id: str) -> dict[str, Any] | None:
    return _PENDING.get(feedback_id)
