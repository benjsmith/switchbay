"""Provider and model selection for a wave.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import logging
from switchbay import llmgateway
from switchbay import modestore
from switchbay.agents import orchestration_policy

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

def _auto_roster_pair(
    workspace: Path,
    *,
    hint_pid: str | None = None,
    hint_model: str | None = None,
    preference: float | None = None,
) -> tuple[str, str | None]:
    """Chief-of-staff (provider, model) given the rail picker.

    The picker is the primary model for questions, ``/curate``, and
    the chief. Dashboard denylist can still veto that pair; workers
    fan out separately.
    """
    pid = hint_pid or _daemon_ns._resolve_default_provider()
    model = hint_model or _daemon_ns._effective_model(pid) or None
    pref = (
        orchestration_policy.clamp_preference(preference)
        if preference is not None
        else orchestration_policy.get_preference()
    )
    try:
        chosen_pid, chosen_model = orchestration_policy.pick_chief_pair(
            default_provider=pid,
            default_model=model,
            preference=pref,
            workspace=workspace,
        )
    except Exception:  # noqa: BLE001
        log.exception("auto roster pick failed; using %s/%s", pid, model)
        return pid, model
    if chosen_pid:
        return chosen_pid, chosen_model
    return pid, model

def _ce_action_provider(workspace: Path) -> tuple[str | None, str | None]:
    """Which provider runs the ORCHESTRATOR of a CE action (curate /
    ingest / add-source).

    The CE model ladder (2026-07-24 reframe) is a CE-curation-only
    construct with three roles: **hard = orchestrator**, **normal =
    fan-out workers**, **trivial = cheap sub-calls**. The orchestrator
    is the top-level agent this function routes; workers/sub-calls are
    resolved per-difficulty inside the fan-out path.

    A pinned `hard` rung (Settings → CE curation → Override, or a
    per-run override) still wins. When that rung is unset, the rail
    picker is the curator (dashboard denylist can veto it). ``/curate``
    stays one CE curator — this only chooses which model drives it.
    Phase 2 workers may still use other allowlisted models.

    Returns the Auto roster pair when the `hard` rung is:
      · unset (the default);
      · unknown / keyless / unavailable; or
      · not curate-capable — a propose-only provider cannot curate, so
        we fall back rather than silently degrade to proposals (the
        2026-07-24 curator bug).
    """
    rung_pid, rung_model = modestore.resolve_for_difficulty(workspace, "hard")
    if not rung_pid:
        return _daemon_ns._auto_roster_pair(workspace)
    try:
        p = llmgateway.get(rung_pid)
    except llmgateway.ProviderError:
        return _daemon_ns._auto_roster_pair(workspace)
    if not p.has_key():
        return _daemon_ns._auto_roster_pair(workspace)
    if not llmgateway.can_curate(rung_pid):
        log.info(
            "CE action: hard rung %s cannot curate; "
            "falling back to the Auto roster", rung_pid)
        return _daemon_ns._auto_roster_pair(workspace)
    return rung_pid, rung_model

def _provider_is_local(pid: str) -> bool:
    """True if `pid` is a local (on-device) provider — llama.cpp/Ollama.
    Used to localise CE-action prompts: a local model can't load the CE
    skill, so it needs the operating rules inlined."""
    try:
        return llmgateway.get(pid).PROVIDER.get("category") == "local"
    except llmgateway.ProviderError:
        return False

def _curate_wave_prime_system(
    workspace: Path, args: str, *, local: bool,
) -> str:
    """Inject CE Phase 1 (pick-mode) for capable /curate. Local skips."""
    if local:
        return ""
    from switchbay import ce_host
    from switchbay.ce_protocol import CURATE_MODE_ALIASES
    token = args.split(None, 1)[0].lower() if (args or "").strip() else ""
    payload: dict[str, Any] = (
        {"mode": token} if token in CURATE_MODE_ALIASES else {}
    )
    try:
        prime = ce_host.wave_prime(workspace, payload)
    except Exception as exc:  # noqa: BLE001
        return f"ce_wave_prime failed: {exc}"
    return (
        "ce_wave_prime result (Phase 1 already ran; execute this mode):\n"
        + json.dumps(prime, default=str)[:6000]
    )

def _ce_action_prompt(
    name: str, args: str, *, local: bool = False,
    local_rung: Any = None,
) -> str | None:
    """Translate a CE-flavoured slash command into a canned prompt
    that the rail agent (loaded with the curiosity-engine skill)
    can act on. Returns None when the slash isn't a CE action.

    The prompts are deliberately terse — the CE skill itself is
    long-form in the global curiosity-engine skill
    (`~/.agents/skills/curiosity-engine/`, or `~/.claude/skills/`
    if Claude Code is installed) and the agent reads it via
    load_skill before running. We just say what to do; the
    skill's body says how.

    `local=True` targets the local model, which CAN'T load that skill
    (too big → capped). For it we drop the "load the skill" dead-end and
    inline the essential operating rules (`_LOCAL_CURATE_HOWTO`)."""
    n = name.strip().lower()
    a = args.strip()
    if n in ("curate", "curator"):
        mode = a.split(None, 1)[0].lower() if a else ""
        if local:
            focus = (
                f" Focus on `{mode}` items." if mode in _daemon_ns._CE_CURATE_MODES
                else (f" Focus on: {a}." if a else "")
            )
            worker = _daemon_ns._LOCAL_CURATE_WORKER
            if local_rung is not None and not getattr(
                local_rung, "force_scaffold", True,
            ):
                worker = _daemon_ns._LOCAL_CURATE_LARGE
            return (
                "Worker-curate this workspace's wiki. "
                + worker + focus + " "
                + _daemon_ns._LOCAL_CURATE_HOWTO
            )
        focus = (
            f" Mode: `{mode}`." if mode in _daemon_ns._CE_CURATE_MODES
            else (f" Focus: {a}." if a else "")
        )
        return (
            "Run curiosity-engine CURATE over this workspace. "
            + _daemon_ns._CURATE_TOOLS + focus
            + " Report a short summary when the wave finishes."
        )
    # `viewer` / `build-viewer` no longer return a chat prompt —
    # the dispatch in handle_ws short-circuits them into
    # `_handle_rescan` (cebridge.build on the daemon side). Routing
    # via claude-code made the agent refuse because viewer.sh isn't
    # on its bash allowlist.
    if n in ("add-source", "addsource", "source-add"):
        if not a:
            return (
                "User invoked /add-source with no argument. Tell "
                "them: pass a filesystem path (we'll copy the file "
                "into vault/raw/) or paste text content (we'll "
                "write it as a new file in vault/raw/ then ingest)."
            )
        return (
            f"The user wants to add a new source to vault/raw/. "
            f"Argument: `{a}`. If it looks like an existing "
            f"filesystem path, copy that file into vault/raw/ (use "
            f"the original basename, slugified for safety). If it "
            f"looks like raw text content, write it to a new file "
            f"under vault/raw/ with a sensible slug filename. Then "
            f"run CE's local_ingest.py against vault/raw/ to drain "
            f"and create wiki/sources/ pages. Report the new "
            f"source page paths."
        )
    if n in ("ingest", "drain"):
        return (
            "Drain whatever's currently in vault/raw/ — run CE's "
            "scripts/local_ingest.py to ingest each file and write "
            "the resulting wiki/sources/ pages. Skip files already "
            "ingested; report new source paths created."
        )
    return None
