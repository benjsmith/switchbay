"""Provider-channel memory for Auto — separate from policy quality.

Network layer, not decision layer:

* A weekly-limit or dead local server is a *channel outage*.
* Whether ``ivs_diverse_2`` is a good topology is a *policy* question.

Mixing them creates a degenerate loop: Claude hits a quota → diverse
policies look like they failed → Auto stops buying independence even
after the quota resets. So this module only stores **availability with
TTL**. The bandit never sees these rows.

Cooldowns expire. The rail picker is never blocked by this file.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import atomicio, statedir

log = logging.getLogger("switchbay.agents.orchestration_health")

HEALTH_VERSION = 1

COOLDOWN_DOWN_S = 10 * 60
COOLDOWN_RATE_S = 6 * 3600
COOLDOWN_GENERIC_S = 30 * 60
COOLDOWN_WEEKLY_FALLBACK_S = 24 * 3600
# Credit/billing exhaustion has no advertised reset. Don't hammer a
# dead key; retry after a few hours in case the user topped up.
# Weekly-limit channels still win the wait (they have a real until).
COOLDOWN_CREDIT_S = 6 * 3600

_WEEKLY_RE = re.compile(
    r"weekly limit.*?resets\s+([A-Za-z]+)\s+(\d{1,2})\s+at\s+"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
    r"(?:\s*\(([^)]+)\))?",
    re.I | re.S,
)
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def health_path() -> Path:
    return statedir.state_root() / "orchestration_providers.json"


def empty_health() -> dict[str, Any]:
    return {"version": HEALTH_VERSION, "updated_at": time.time(), "providers": {}}


def load_health() -> dict[str, Any]:
    p = health_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_health()
    if not isinstance(data, dict) or data.get("version") != HEALTH_VERSION:
        return empty_health()
    data.setdefault("providers", {})
    return data


def save_health(data: dict[str, Any]) -> None:
    data = dict(data)
    data["version"] = HEALTH_VERSION
    data["updated_at"] = time.time()
    p = health_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, data)


# Tight patterns for *streaming* assistant text. classify_error is
# looser (a "quota" in a traceback is enough) because it runs on
# exceptions. Investigator prose about "import quotas" must not
# kill the worker.
_OUTAGE_TEXT_RE = re.compile(
    r"hit your weekly limit|you've hit your (?:usage |rate )?limit"
    r"|weekly limit\b.*\bresets"
    r"|insufficient[_ ](?:quota|funds)|out of credits?"
    r"|\b429\b|rate[_ ]limit(?:ed)?(?: exceeded)?"
    r"|too many requests",
    re.I | re.S,
)

CHANNEL_RETRY_KINDS = frozenset({"weekly_limit", "credit", "rate", "down"})


def classify_error(err: str) -> str:
    low = (err or "").lower()
    if "weekly limit" in low:
        return "weekly_limit"
    if any(
        n in low for n in (
            "insufficient_quota", "insufficient_funds", "out of credit",
            "out of credits", "credit balance", "billing",
            "payment required", "spend limit",
        )
    ):
        return "credit"
    if "quota" in low:
        return "weekly_limit"
    if "429" in low or "rate limit" in low or "too many requests" in low:
        return "rate"
    if (
        "isn't answering" in low or "not answering" in low
        or "connection" in low or "refused" in low or "timed out" in low
        or "out of memory" in low
    ):
        return "down"
    return "error"


def looks_like_outage(text: str) -> str | None:
    """If streaming text *is* a channel outage, return its kind.

    Used mid-stream so a weekly-limit banner aborts the worker
    immediately instead of being filed as a successful finding.
    Returns None for ordinary assistant prose.
    """
    blob = (text or "").strip()
    if not blob or not _OUTAGE_TEXT_RE.search(blob):
        return None
    kind = classify_error(blob)
    return kind if kind in CHANNEL_RETRY_KINDS else None


def parse_weekly_until(err: str, *, now: float | None = None) -> float | None:
    """Unix time for 'resets Aug 26 at 11pm (Europe/Zurich)', or None."""
    m = _WEEKLY_RE.search(err or "")
    if not m:
        return None
    mon = _MONTHS.get(m.group(1).lower()[:3])
    if not mon:
        return None
    day = int(m.group(2))
    hour = int(m.group(3))
    minute = int(m.group(4) or 0)
    ampm = (m.group(5) or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    tzname = (m.group(6) or "").strip() or "UTC"
    now = now if now is not None else time.time()
    year = datetime.fromtimestamp(now, tz=timezone.utc).year
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tzname.replace(" ", "_")) if "/" in tzname or tzname == "UTC" else ZoneInfo("UTC")
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    try:
        dt = datetime(year, mon, day, hour, minute, tzinfo=tz)
    except ValueError:
        return None
    ts = dt.timestamp()
    if ts < now - 86400:
        try:
            dt = datetime(year + 1, mon, day, hour, minute, tzinfo=tz)
            ts = dt.timestamp()
        except ValueError:
            pass
    return ts


def _until_for(kind: str, err: str, *, now: float) -> float:
    if kind == "weekly_limit":
        parsed = parse_weekly_until(err, now=now)
        if parsed:
            return parsed
        return now + COOLDOWN_WEEKLY_FALLBACK_S
    if kind == "credit":
        return now + COOLDOWN_CREDIT_S
    if kind == "rate":
        return now + COOLDOWN_RATE_S
    if kind == "down":
        return now + COOLDOWN_DOWN_S
    return now + COOLDOWN_GENERIC_S


def is_available(provider_id: str, *, now: float | None = None) -> bool:
    now = now if now is not None else time.time()
    rec = (load_health().get("providers") or {}).get(provider_id)
    if not isinstance(rec, dict):
        return True
    until = rec.get("until")
    try:
        return float(until or 0) <= now
    except (TypeError, ValueError):
        return True


def _touch_provider(st: dict[str, Any], provider_id: str) -> dict[str, Any]:
    providers = st.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        st["providers"] = providers
    rec = providers.get(provider_id)
    if not isinstance(rec, dict):
        rec = {}
        providers[provider_id] = rec
    return rec


def note_success(provider_id: str) -> None:
    if not provider_id:
        return
    st = load_health()
    rec = _touch_provider(st, provider_id)
    rec["status"] = "ok"
    rec["until"] = 0
    rec["last_ok"] = time.time()
    rec["successes"] = int(rec.get("successes") or 0) + 1
    save_health(st)


def note_failure(provider_id: str, err: str, *, now: float | None = None) -> dict[str, Any]:
    now = now if now is not None else time.time()
    kind = classify_error(err)
    until = _until_for(kind, err, now=now)
    st = load_health()
    rec = _touch_provider(st, provider_id)
    rec["status"] = "cooldown"
    rec["kind"] = kind
    rec["until"] = until
    rec["last_error"] = (err or "")[:400]
    rec["last_fail"] = now
    rec["failures"] = int(rec.get("failures") or 0) + 1
    save_health(st)
    return {
        "provider": provider_id,
        "kind": kind,
        "until": until,
        "until_label": _fmt_until(until),
        "reason": kind,
    }


def skip_notes(*, now: float | None = None) -> list[str]:
    """Human lines for providers currently in cooldown."""
    now = now if now is not None else time.time()
    out: list[str] = []
    for pid, rec in (load_health().get("providers") or {}).items():
        if not isinstance(rec, dict):
            continue
        try:
            until = float(rec.get("until") or 0)
        except (TypeError, ValueError):
            continue
        if until <= now:
            continue
        kind = str(rec.get("kind") or "error")
        label = _fmt_until(until)
        if kind == "weekly_limit":
            out.append(f"{pid} (weekly limit until {label})")
        elif kind == "credit":
            out.append(f"{pid} (API credits exhausted)")
        elif kind == "down":
            out.append(f"{pid} (not answering; retry after {label})")
        else:
            out.append(f"{pid} (unavailable until {label})")
    return out


def format_worker_error(provider_id: str, err: str) -> str:
    info = note_failure(provider_id, err)
    until = info.get("until_label") or "later"
    kind = info.get("kind")
    if kind == "weekly_limit":
        return (
            f"{provider_id} weekly limit (resets {until}). "
            "This worker was a probe for an independent evidence path; "
            "your rail picker is unchanged."
        )
    if kind == "credit":
        return (
            f"{provider_id} API credits exhausted. "
            "Auto will not keep billing this key; it will wait for a "
            "subscription reset or a local server, unless you add credit."
        )
    if kind == "down":
        return (
            f"{provider_id} isn't answering (retry after {until}). "
            "Probe dropped; remaining workers continue."
        )
    return (
        f"{provider_id} unavailable ({kind}; retry after {until}). "
        "Probe dropped; remaining workers continue."
    )


def earliest_resume_at(
    *,
    now: float | None = None,
    kinds: tuple[str, ...] | None = None,
) -> float | None:
    """Soonest ``until`` among cooling providers, or None."""
    now = now if now is not None else time.time()
    soonest: float | None = None
    for rec in (load_health().get("providers") or {}).values():
        if not isinstance(rec, dict):
            continue
        if kinds is not None and str(rec.get("kind") or "") not in kinds:
            continue
        try:
            until = float(rec.get("until") or 0)
        except (TypeError, ValueError):
            continue
        if until <= now:
            continue
        if soonest is None or until < soonest:
            soonest = until
    return soonest


def cooling_records(*, now: float | None = None) -> list[dict[str, Any]]:
    now = now if now is not None else time.time()
    out: list[dict[str, Any]] = []
    for pid, rec in (load_health().get("providers") or {}).items():
        if not isinstance(rec, dict):
            continue
        try:
            until = float(rec.get("until") or 0)
        except (TypeError, ValueError):
            continue
        if until <= now:
            continue
        out.append({
            "provider": pid,
            "kind": rec.get("kind"),
            "until": until,
            "until_label": _fmt_until(until),
        })
    return out


def _fmt_until(until: float) -> str:
    try:
        return datetime.fromtimestamp(until, tz=timezone.utc).strftime("%b %d %H:%M UTC")
    except (OSError, OverflowError, ValueError):
        return "later"


def inspect() -> dict[str, Any]:
    st = load_health()
    now = time.time()
    rows = []
    for pid, rec in (st.get("providers") or {}).items():
        if not isinstance(rec, dict):
            continue
        until = float(rec.get("until") or 0)
        rows.append({
            "provider": pid,
            "status": "cooldown" if until > now else "ok",
            "kind": rec.get("kind"),
            "until": until or None,
            "failures": rec.get("failures"),
            "successes": rec.get("successes"),
        })
    return {"providers": rows}
