"""Map okstratr ``host_notify`` envelopes onto Switchbay rail notices.

Contract C2: Switchbay sink is the **rail** only (path-native). okstratr
emits ``okstratr.host_notify``; this host maps to ``protocol.notice`` and
broadcasts on the agent chat stream.
"""

from __future__ import annotations

from typing import Any

from . import protocol

ENVELOPE_TYPE = "okstratr.host_notify"
ENVELOPE_V = 1

_KIND_LABELS = {
    "schedule.start": "Schedule started",
    "schedule.progress": "Schedule progress",
    "schedule.done": "Schedule done",
    "schedule.failed": "Schedule failed",
    "desk.progress": "Desk progress",
    "desk.done": "Desk done",
}


def validate_envelope(body: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Return (envelope, error). error is set when invalid."""
    if not isinstance(body, dict):
        return None, "envelope must be a JSON object"
    if body.get("type") != ENVELOPE_TYPE:
        return None, f"type must be {ENVELOPE_TYPE!r}"
    v = body.get("v", ENVELOPE_V)
    try:
        if int(v) != ENVELOPE_V:
            return None, f"unsupported envelope v={v!r}"
    except (TypeError, ValueError):
        return None, f"unsupported envelope v={v!r}"
    kind = body.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        return None, "kind is required"
    return body, None


def format_rail_text(envelope: dict[str, Any]) -> str:
    """Human rail line from a validated envelope."""
    kind = str(envelope.get("kind") or "")
    label = _KIND_LABELS.get(kind, kind)
    title = (envelope.get("title") or "").strip()
    body = (envelope.get("body") or "").strip()
    desk = envelope.get("desk")
    schedule_id = envelope.get("schedule_id")
    progress = envelope.get("progress") if isinstance(envelope.get("progress"), dict) else None

    parts: list[str] = [f"[okstratr] {label}"]
    if title:
        parts[0] = f"[okstratr] {label}: {title}"
    meta: list[str] = []
    if desk not in (None, "", "null"):
        meta.append(f"desk={desk}")
    if schedule_id:
        meta.append(f"id={schedule_id}")
    if progress:
        pct = progress.get("pct")
        phase = progress.get("phase")
        detail = progress.get("detail")
        bits: list[str] = []
        if pct is not None:
            bits.append(f"{pct}%")
        if phase:
            bits.append(str(phase))
        if detail:
            bits.append(str(detail))
        if bits:
            meta.append(" · ".join(bits))
    lines = [parts[0]]
    if meta:
        lines.append("(" + ", ".join(meta) + ")")
    if body:
        lines.append(body)
    return "\n".join(lines)


def notice_from_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Build a ``protocol.notice`` payload for rail broadcast."""
    return protocol.notice(format_rail_text(envelope), kind="okstratr")


def _notice_text(msg: dict[str, Any]) -> str | None:
    """Extract human text from a protocol.notice CUSTOM envelope."""
    if "text" in msg and isinstance(msg.get("text"), str):
        return msg["text"]
    val = msg.get("value")
    if isinstance(val, dict) and isinstance(val.get("text"), str):
        return val["text"]
    return None


async def apply_host_notify(app: Any, envelope: dict[str, Any]) -> dict[str, Any]:
    """Validate + broadcast to rail. Returns result dict for HTTP handlers."""
    env, err = validate_envelope(envelope)
    if err or env is None:
        return {"ok": False, "error": err or "invalid envelope"}
    msg = notice_from_envelope(env)
    # Daemon stores the bound helper as ``_broadcast_fn`` (same as CE).
    bc = app.get("_broadcast_fn") if hasattr(app, "get") else None
    if callable(bc):
        await bc(app, msg)
    else:
        from . import daemon as _daemon

        await _daemon._broadcast(app, msg)
    return {
        "ok": True,
        "broadcast": True,
        "text": _notice_text(msg) if isinstance(msg, dict) else None,
        "notice": msg,
    }
