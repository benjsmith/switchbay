"""Comms review queue: metadata-only discovery, approval, revocation.

Email threads and chat channels are sources. Discovery may only store
safe metadata. Body fetch, MIME/HTML parsing, classification of body
text, transit, logs of content, and wiki ingestion require an explicit
per-workspace approval of a stable thread/channel key — and a fresh
non-secret re-check immediately before every content fetch.

Revocation is durable, keyed by provider + account + stable id (not
subject/display name), survives restarts and account routing changes,
and wins races with polling/queued work.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from . import admin_policy, atomicio, statedir

log = logging.getLogger("switchbay.comms_review")

STORE_VERSION = 1
_LOCK = threading.RLock()

KIND_EMAIL = "email_thread"
KIND_CHANNEL = "channel"
KIND_CHAT = "chat"

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_REVOKED = "revoked"
STATUS_BLOCKED = "blocked"

DEFAULT_CLASSIFICATION_HEADERS = (
    "Sensitivity",
    "Classification",
    "X-MS-Exchange-Organization-Classification",
    "MSIP_Labels",
    "X-Microsoft-Classification",
    "X-Sensitivity",
)
DEFAULT_SECRET_NAMES = (
    "secret",
    "top secret",
    "top-secret",
    "classified secret",
)
# Outlook Sensitivity enum values that are not Secret/Top Secret.
_KNOWN_PUBLIC = frozenset({
    "normal", "personal", "private", "confidential", "public",
    "internal", "general", "unclassified", "none", "",
})

_MSGID_RE = re.compile(r"<[^>]+>")
_SECRET_SUBJ = "[redacted: classified]"


def _store_path() -> Path:
    return statedir.state_root() / "comms-review.json"


def empty_store() -> dict[str, Any]:
    return {"version": STORE_VERSION, "items": {}, "revoked": {}}


def load() -> dict[str, Any]:
    p = _store_path()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_store()
    if not isinstance(raw, dict) or raw.get("version") != STORE_VERSION:
        return empty_store()
    items = raw.get("items")
    revoked = raw.get("revoked")
    if not isinstance(items, dict):
        items = {}
    if not isinstance(revoked, dict):
        revoked = {}
    return {"version": STORE_VERSION, "items": items, "revoked": revoked}


def save(data: dict[str, Any]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": STORE_VERSION,
        "items": data.get("items") if isinstance(data.get("items"), dict) else {},
        "revoked": data.get("revoked") if isinstance(data.get("revoked"), dict) else {},
    }
    atomicio.write_json_atomic(p, payload)
    try:
        p.chmod(0o600)
    except OSError:
        pass


def source_key(provider: str, account_id: str, stable_id: str) -> str:
    p = (provider or "").strip().lower()
    a = (account_id or "").strip()
    s = (stable_id or "").strip()
    return f"{p}:{a}:{s}"


def _norm_msgid(raw: str) -> str:
    t = (raw or "").strip()
    if not t:
        return ""
    if t[0] != "<":
        t = f"<{t.strip('<>')}>"
    return t.lower()


def imap_thread_stable_id(
    *,
    message_id: str,
    references: str,
    in_reply_to: str,
    uidvalidity: str | int,
    fallback_uid: str = "",
) -> str:
    """Root Message-ID from References / In-Reply-To / Message-ID, scoped by UIDVALIDITY."""
    refs = [_norm_msgid(m) for m in _MSGID_RE.findall(references or "")]
    root = ""
    if refs:
        root = refs[0]
    if not root:
        irt = [_norm_msgid(m) for m in _MSGID_RE.findall(in_reply_to or "")]
        if irt:
            root = irt[0]
    if not root:
        root = _norm_msgid(message_id)
    if not root:
        root = f"uid:{fallback_uid}" if fallback_uid else "unknown"
    uv = str(uidvalidity or "0")
    digest = hashlib.sha1(root.encode("utf-8", errors="replace")).hexdigest()[:20]
    return f"{uv}:{digest}"


# Gmail/system labels that are not security classifications.
SYSTEM_LABEL_IDS = frozenset({
    "inbox", "unread", "starred", "important", "sent", "draft", "spam",
    "trash", "category_personal", "category_social", "category_promotions",
    "category_updates", "category_forums", "yellow_star", "chat", "all",
    "snoozed",
})


def classification_policy() -> dict[str, Any]:
    data = admin_policy.load()
    raw = data.get("comms") if isinstance(data.get("comms"), dict) else {}
    headers: list[str] = list(DEFAULT_CLASSIFICATION_HEADERS)
    seen_h = {h.lower() for h in headers}
    for h in raw.get("classification_headers") or []:
        name = str(h).strip()
        if name and name.lower() not in seen_h:
            headers.append(name)
            seen_h.add(name.lower())
    names: list[str] = list(DEFAULT_SECRET_NAMES)
    seen_n = {n.lower() for n in names}
    for n in raw.get("secret_names") or []:
        s = str(n).strip()
        if s and s.lower() not in seen_n:
            names.append(s)
            seen_n.add(s.lower())
    label_ids = raw.get("tenant_label_ids")
    if not isinstance(label_ids, list):
        label_ids = []
    require = raw.get("require_classification")
    if require is None:
        require = admin_policy.profile() == "enterprise"
    # Baked enterprise may not disable classification requirements.
    if data.get("tighten") and str(data.get("profile") or "") == "enterprise":
        require = True
    return {
        "headers": headers,
        "secret_names": names,
        "tenant_label_ids": [str(x).strip() for x in label_ids if str(x).strip()],
        "require_classification": bool(require),
        "enterprise": admin_policy.profile() == "enterprise",
    }


def _secret_match(value: str, secret_names: list[str]) -> bool:
    low = (value or "").lower()
    if not low.strip():
        return False
    for name in secret_names:
        n = name.lower().strip()
        if not n:
            continue
        if n in low.split(";") or n == low.strip():
            return True
        # MIP / header blobs: "MSIP_Label_...; name=Secret"
        if re.search(rf"(?:^|[=\s;,]){re.escape(n)}(?:$|[\s;,])", low):
            return True
    return False


def classify_metadata(
    *,
    headers: dict[str, str] | None = None,
    label_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Inspect classification labels/headers only. Never looks at bodies.

    verdict:
      secret   — Secret/Top Secret (or tenant secret label id)
      unknown  — a classification mark we do not recognise
      missing  — no classification material present
      clear    — recognised non-secret mark, or missing under open profile
    """
    pol = classification_policy()
    headers = {str(k): str(v) for k, v in (headers or {}).items() if k}
    lower_map = {k.lower(): v for k, v in headers.items()}
    raw_labels = [str(x) for x in (label_ids or []) if x]
    security_labels = [x for x in raw_labels if x.lower() not in SYSTEM_LABEL_IDS]
    hits: list[str] = []
    for h in pol["headers"]:
        val = lower_map.get(h.lower(), "")
        if val:
            hits.extend(p for p in val.split("\n") if p)
    blob = " ".join(list(headers.values()) + raw_labels)
    tenants = pol["tenant_label_ids"]
    for tid in tenants:
        if tid and tid.lower() in blob.lower():
            return {
                "verdict": "secret",
                "reason": "tenant_secret_label",
                "marks": [tid],
            }
    for lid in security_labels:
        hits.append(lid)
        if lid in tenants:
            return {
                "verdict": "secret",
                "reason": "tenant_secret_label",
                "marks": [lid],
            }
    if any(_secret_match(h, pol["secret_names"]) for h in hits):
        return {"verdict": "secret", "reason": "secret_mark", "marks": hits[:8]}
    class_hits = [h for h in hits if h.strip().lower() not in SYSTEM_LABEL_IDS]
    if not class_hits:
        if pol["require_classification"] or pol["enterprise"]:
            return {
                "verdict": "missing",
                "reason": "classification_required",
                "marks": [],
            }
        return {"verdict": "clear", "reason": "unmarked_open", "marks": []}
    normalised = [h.strip().lower() for h in class_hits]
    tenant_l = {x.lower() for x in tenants}
    if any(n not in _KNOWN_PUBLIC and n not in tenant_l for n in normalised):
        if pol["require_classification"] or pol["enterprise"]:
            return {"verdict": "unknown", "reason": "unknown_label", "marks": class_hits[:8]}
    return {"verdict": "clear", "reason": "recognised", "marks": class_hits[:8]}


def is_revoked(key: str, data: dict[str, Any] | None = None) -> bool:
    st = data if data is not None else load()
    if key in (st.get("revoked") or {}):
        return True
    item = (st.get("items") or {}).get(key)
    return isinstance(item, dict) and item.get("status") == STATUS_REVOKED


def merge_header_maps(*maps: dict[str, Any] | None) -> dict[str, str]:
    """Join header maps conservatively: duplicate names keep every value.

    A later ``Sensitivity: normal`` must not erase an earlier Secret.
    Body-like keys are dropped.
    """
    out: dict[str, str] = {}
    canon: dict[str, str] = {}
    skip = {"text", "body", "snippet"}
    for mapping in maps:
        if not isinstance(mapping, dict):
            continue
        for raw_k, raw_v in mapping.items():
            if not raw_k:
                continue
            name = str(raw_k)
            lk = name.lower()
            if lk in skip:
                continue
            val = str(raw_v or "")
            if lk in canon:
                prev = out.get(canon[lk], "")
                extra = [p for p in val.split("\n") if p and p not in prev.split("\n")]
                if extra:
                    out[canon[lk]] = prev + ("\n" if prev else "") + "\n".join(extra)
            else:
                canon[lk] = name
                out[name] = val
    return out


def _safe_subject(subject: str, *, secret: bool) -> str:
    if secret:
        return _SECRET_SUBJ
    return (subject or "")[:180]


def _ingest_view(item: dict[str, Any], workspace: str | None) -> dict[str, str]:
    by = item.get("ingest_by_workspace")
    if not isinstance(by, dict) or not by:
        return {}
    ws = str(workspace or "").strip()
    if ws and isinstance(by.get(ws), dict):
        rec = by[ws]
        return {"state": str(rec.get("state") or ""), "error": str(rec.get("error") or "")}
    # No bound workspace: show the most recently updated row.
    latest: dict[str, Any] | None = None
    latest_at = -1.0
    for rec in by.values():
        if not isinstance(rec, dict):
            continue
        try:
            at = float(rec.get("at") or 0)
        except (TypeError, ValueError):
            at = 0.0
        if at >= latest_at:
            latest_at = at
            latest = rec
    if not isinstance(latest, dict):
        return {}
    return {"state": str(latest.get("state") or ""), "error": str(latest.get("error") or "")}


def _public_item(item: dict[str, Any], *, workspace: str | None = None) -> dict[str, Any]:
    secret = item.get("status") == STATUS_BLOCKED and item.get("block_reason") in (
        "secret", "secret_mark", "tenant_secret_label",
    )
    ingest = _ingest_view(item, workspace)
    return {
        "key": item.get("key"),
        "provider": item.get("provider"),
        "account_id": item.get("account_id"),
        "stable_id": item.get("stable_id"),
        "kind": item.get("kind"),
        "status": item.get("status"),
        "block_reason": item.get("block_reason"),
        "block_detail": item.get("block_detail"),
        "subject": _safe_subject(str(item.get("subject") or ""), secret=bool(secret)),
        "sender": "" if secret else (item.get("sender") or ""),
        "deep_link": item.get("deep_link") or "",
        "labels": [] if secret else list(item.get("labels") or [])[:12],
        "approved_workspaces": list(item.get("approved_workspaces") or []),
        "suggested_workspaces": list(item.get("suggested_workspaces") or []),
        "suggested_relevance": item.get("suggested_relevance") if isinstance(item.get("suggested_relevance"), dict) else {},
        "content_capability": item.get("content_capability") or "ok",
        "content_capability_reason": item.get("content_capability_reason") or "",
        "last_ts": item.get("last_ts"),
        "updated_at": item.get("updated_at"),
        "message_count": int(item.get("message_count") or 0),
        "ingest_state": ingest.get("state") or "",
        "ingest_error": ingest.get("error") or "",
    }


def upsert_discovery(record: dict[str, Any]) -> dict[str, Any]:
    """Record safe metadata. Never stores body/snippet. Never auto-approves."""
    provider = str(record.get("provider") or "")
    account_id = str(record.get("account_id") or "")
    stable_id = str(record.get("stable_id") or "")
    key = source_key(provider, account_id, stable_id)
    headers = record.get("headers") if isinstance(record.get("headers"), dict) else {}
    labels = record.get("labels") if isinstance(record.get("labels"), list) else []
    verdict = classify_metadata(headers=headers, label_ids=labels)
    secret = verdict["verdict"] == "secret"
    with _LOCK:
        st = load()
        if is_revoked(key, st):
            item = dict((st["items"].get(key) if isinstance(st["items"].get(key), dict) else {}) or {})
            item.update({
                "key": key,
                "provider": provider,
                "account_id": account_id,
                "stable_id": stable_id,
                "status": STATUS_REVOKED,
                "subject": _SECRET_SUBJ if secret else (record.get("subject") or item.get("subject") or ""),
                "updated_at": time.time(),
            })
            st["items"][key] = item
            save(st)
            return _public_item(item)
        existing = st["items"].get(key) if isinstance(st["items"].get(key), dict) else {}
        status = str(existing.get("status") or STATUS_PENDING)
        block_reason = existing.get("block_reason")
        block_detail = existing.get("block_detail")
        if secret:
            status = STATUS_BLOCKED
            block_reason = verdict.get("reason") or "secret"
            block_detail = "classified: secret — content fetch refused"
        elif verdict["verdict"] in ("unknown", "missing") and (
            classification_policy()["enterprise"] or classification_policy()["require_classification"]
        ):
            # Stay pending for review, but content is fail-closed until marks are clear.
            block_reason = verdict.get("reason")
            block_detail = (
                "classification missing or unknown; content fetch refused under enterprise policy"
            )
        if status == STATUS_APPROVED:
            pass  # keep approval; new mail on an approved thread stays approved
        elif status == STATUS_REVOKED:
            pass
        elif status == STATUS_BLOCKED and not secret:
            status = STATUS_PENDING
        elif status == STATUS_REJECTED:
            # New activity may re-surface as a suggestion, never as approval.
            status = STATUS_PENDING
        elif status not in (STATUS_APPROVED, STATUS_REVOKED, STATUS_BLOCKED):
            status = STATUS_PENDING
        cap = str(record.get("content_capability") or existing.get("content_capability") or "ok")
        cap_reason = str(
            record.get("content_capability_reason")
            or existing.get("content_capability_reason")
            or ""
        )
        stored_headers = merge_header_maps(
            existing.get("headers") if isinstance(existing.get("headers"), dict) else {},
            headers,
        )
        item = {
            **existing,
            "key": key,
            "provider": provider,
            "account_id": account_id,
            "stable_id": stable_id,
            "kind": record.get("kind") or existing.get("kind") or KIND_EMAIL,
            "status": status,
            "block_reason": block_reason,
            "block_detail": block_detail,
            "subject": _SECRET_SUBJ if secret else (record.get("subject") or existing.get("subject") or ""),
            "sender": "" if secret else (record.get("sender") or existing.get("sender") or ""),
            "deep_link": record.get("deep_link") or existing.get("deep_link") or "",
            "labels": [] if secret else list(labels)[:16],
            "headers": stored_headers,
            "approved_workspaces": list(existing.get("approved_workspaces") or []),
            "suggested_workspaces": list(existing.get("suggested_workspaces") or []),
            "suggested_relevance": existing.get("suggested_relevance") or {},
            "content_capability": cap,
            "content_capability_reason": cap_reason,
            "last_ts": record.get("ts") or existing.get("last_ts") or time.time(),
            "updated_at": time.time(),
            "message_count": int(existing.get("message_count") or 0) + 1,
            "created_at": existing.get("created_at") or time.time(),
        }
        refs = list(existing.get("fetch_refs") or [])
        new_ref = record.get("fetch_ref") if isinstance(record.get("fetch_ref"), dict) else None
        if new_ref:
            rid = str(new_ref.get("id") or new_ref.get("uid") or "")
            if rid and not any(str(r.get("id") or r.get("uid") or "") == rid for r in refs if isinstance(r, dict)):
                refs.append({k: v for k, v in new_ref.items() if k != "text" and k != "body" and k != "snippet"})
        item["fetch_refs"] = refs
        for meta_k in ("uidvalidity", "thread_id", "conversation_id", "imap_uid"):
            if record.get(meta_k):
                item[meta_k] = record.get(meta_k)
        # Never persist body/snippet even if a caller passed one.
        item.pop("text", None)
        item.pop("snippet", None)
        item.pop("body", None)
        st["items"][key] = item
        save(st)
        return _public_item(item)


def set_suggestions(
    key: str,
    *,
    workspaces: list[str],
    relevance: dict[str, float] | None = None,
) -> None:
    """Classifier suggestions only. Never changes approval/revocation."""
    with _LOCK:
        st = load()
        if is_revoked(key, st):
            return
        item = st["items"].get(key)
        if not isinstance(item, dict):
            return
        if item.get("status") in (STATUS_APPROVED, STATUS_REVOKED, STATUS_BLOCKED):
            item["suggested_workspaces"] = list(workspaces)
            if relevance:
                item["suggested_relevance"] = {
                    str(k): float(v) for k, v in relevance.items()
                }
            st["items"][key] = item
            save(st)
            return
        item["suggested_workspaces"] = list(workspaces)
        if relevance:
            item["suggested_relevance"] = {str(k): float(v) for k, v in relevance.items()}
        st["items"][key] = item
        save(st)


def approve(key: str, workspace: str, *, allowed: list[str]) -> dict[str, Any]:
    ws = str(workspace or "").strip()
    if not ws:
        return {"ok": False, "error": "workspace is required"}
    allow = {str(p) for p in allowed}
    if ws not in allow:
        return {"ok": False, "error": "workspace is not on this account allowlist"}
    with _LOCK:
        st = load()
        if is_revoked(key, st):
            return {"ok": False, "error": "revoked — content will not be fetched"}
        item = st["items"].get(key)
        if not isinstance(item, dict):
            return {"ok": False, "error": "unknown comms source"}
        if item.get("status") == STATUS_BLOCKED and item.get("block_reason") in (
            "secret", "secret_mark", "tenant_secret_label",
        ):
            return {"ok": False, "error": "secret sources cannot be approved"}
        approved = list(item.get("approved_workspaces") or [])
        if ws not in approved:
            approved.append(ws)
        item["approved_workspaces"] = approved
        item["status"] = STATUS_APPROVED
        item["updated_at"] = time.time()
        st["items"][key] = item
        save(st)
        return {"ok": True, "item": _public_item(item)}


def reject(key: str) -> dict[str, Any]:
    with _LOCK:
        st = load()
        if is_revoked(key, st):
            item = st["items"].get(key)
            return {"ok": True, "item": _public_item(item) if isinstance(item, dict) else {"key": key, "status": STATUS_REVOKED}}
        item = st["items"].get(key)
        if not isinstance(item, dict):
            return {"ok": False, "error": "unknown comms source"}
        item["status"] = STATUS_REJECTED
        item["updated_at"] = time.time()
        st["items"][key] = item
        save(st)
        return {"ok": True, "item": _public_item(item)}


def revoke(key: str, *, reason: str = "user") -> dict[str, Any]:
    with _LOCK:
        st = load()
        st.setdefault("revoked", {})[key] = {
            "revoked_at": time.time(),
            "reason": (reason or "user")[:120],
        }
        item = st["items"].get(key) if isinstance(st["items"].get(key), dict) else {
            "key": key, "status": STATUS_REVOKED,
        }
        item["status"] = STATUS_REVOKED
        item["updated_at"] = time.time()
        item["approved_workspaces"] = []
        st["items"][key] = item
        save(st)
        return {"ok": True, "item": _public_item(item)}


def get_item(key: str, workspace: str | None = None) -> dict[str, Any] | None:
    st = load()
    item = st["items"].get(key)
    if not isinstance(item, dict):
        if is_revoked(key, st):
            return {"key": key, "status": STATUS_REVOKED}
        return None
    return _public_item(item, workspace=workspace)


def set_ingest_state(
    key: str,
    workspace: str,
    *,
    state: str,
    error: str = "",
) -> None:
    """Record per-workspace ingest outcome. Never changes approval."""
    ws = str(workspace or "").strip()
    if not key or not ws:
        return
    stt = str(state or "").strip()[:32]
    err = str(error or "").strip()[:240]
    with _LOCK:
        st = load()
        item = st["items"].get(key)
        if not isinstance(item, dict):
            return
        by = item.get("ingest_by_workspace")
        if not isinstance(by, dict):
            by = {}
        by[ws] = {"state": stt, "error": err, "at": time.time()}
        item["ingest_by_workspace"] = by
        item["updated_at"] = time.time()
        st["items"][key] = item
        save(st)


def get_raw_item(key: str) -> dict[str, Any] | None:
    """Internal: fetch refs / uidvalidity. Never includes body fields."""
    st = load()
    item = st["items"].get(key)
    if not isinstance(item, dict):
        return None
    raw = dict(item)
    raw.pop("text", None)
    raw.pop("snippet", None)
    raw.pop("body", None)
    return raw


def list_items(*, workspace: str | None = None, account_id: str | None = None) -> list[dict[str, Any]]:
    from . import streams
    st = load()
    allow_by_acct: dict[str, set[str]] = {}
    for acct in streams.list_accounts():
        aid = str(acct.get("id") or "")
        if aid:
            allow_by_acct[aid] = set(streams.allowed_workspaces(acct))
    out: list[dict[str, Any]] = []
    ws = str(workspace or "").strip()
    for item in (st.get("items") or {}).values():
        if not isinstance(item, dict):
            continue
        aid = str(item.get("account_id") or "")
        if account_id and aid != account_id:
            continue
        allowed = allow_by_acct.get(aid)
        if allowed is None:
            # Account gone: do not fall back to the active workspace.
            continue
        if ws and ws not in allowed:
            continue
        pub = _public_item(item, workspace=ws or None)
        if ws:
            approved = ws in (pub.get("approved_workspaces") or [])
            suggested = ws in (pub.get("suggested_workspaces") or [])
            pending = pub.get("status") in (STATUS_PENDING, STATUS_BLOCKED)
            revoked = pub.get("status") == STATUS_REVOKED
            if not (approved or suggested or pending or revoked):
                continue
        out.append(pub)
    out.sort(key=lambda r: float(r.get("updated_at") or 0), reverse=True)
    return out


def authorize_content_fetch(
    key: str,
    workspace: str,
    *,
    allowed: list[str],
    headers: dict[str, str] | None = None,
    label_ids: list[str] | None = None,
    classify: bool = True,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Reload store immediately before a body fetch.

    ``classify=False`` is auth-only (approval / allowlist / revocation /
    capability). Cached discovery headers must not be used as a stand-in
    for a fresh per-message classification — pass freshly fetched headers
    with ``classify=True``.

    Revocation wins. Secret cannot be overridden by prior approval.
    """
    st = load()
    if is_revoked(key, st):
        return False, "revoked", get_item(key)
    item = st["items"].get(key)
    if not isinstance(item, dict):
        return False, "unknown comms source", None
    ws = str(workspace or "")
    if ws not in {str(p) for p in allowed}:
        return False, "workspace is not on this account allowlist", _public_item(item)
    if ws not in {str(p) for p in (item.get("approved_workspaces") or [])}:
        return False, "not approved for this workspace", _public_item(item)
    if item.get("status") != STATUS_APPROVED:
        return False, f"status is {item.get('status')}", _public_item(item)
    if str(item.get("content_capability") or "ok") == "fail_closed":
        return False, str(
            item.get("content_capability_reason")
            or "adapter cannot establish safety before body fetch"
        ), _public_item(item)
    if not classify:
        return True, "", _public_item(item)
    verdict = classify_metadata(headers=headers, label_ids=label_ids)
    if verdict["verdict"] == "secret":
        revoke(key, reason="secret_recheck")
        with _LOCK:
            st2 = load()
            rec = st2["items"].get(key)
            if isinstance(rec, dict):
                rec["status"] = STATUS_BLOCKED
                rec["block_reason"] = verdict.get("reason") or "secret"
                rec["block_detail"] = "secret on re-check — approval ignored"
                rec["subject"] = _SECRET_SUBJ
                rec["sender"] = ""
                st2["items"][key] = rec
                save(st2)
        return False, "secret — content fetch refused", get_item(key)
    if verdict["verdict"] in ("unknown", "missing") and (
        classification_policy()["enterprise"] or classification_policy()["require_classification"]
    ):
        return False, "classification missing or unknown; not assumed public", _public_item(item)
    return True, "", _public_item(item)


def suggest_relevance(
    record: dict[str, Any],
    allowed_workspaces: list[str],
) -> list[str]:
    """Deterministic metadata suggestion. Never approves. Never uses bodies."""
    verdict = classify_metadata(
        headers=record.get("headers") if isinstance(record.get("headers"), dict) else {},
        label_ids=record.get("labels") if isinstance(record.get("labels"), list) else [],
    )
    if verdict["verdict"] == "secret":
        return []
    if record.get("status") == STATUS_BLOCKED:
        return []
    subj = str(record.get("subject") or "")
    if subj == _SECRET_SUBJ:
        return []
    blob = f"{subj} {record.get('sender') or ''} {record.get('kind') or ''}".lower()
    hits: list[str] = []
    for path in allowed_workspaces:
        name = Path(path).name.lower()
        if name and name in blob:
            hits.append(path)
    if not hits and len(allowed_workspaces) == 1:
        hits = [allowed_workspaces[0]]
    return hits


def approved_items_for_account(account_id: str) -> list[dict[str, Any]]:
    st = load()
    out: list[dict[str, Any]] = []
    for item in (st.get("items") or {}).values():
        if not isinstance(item, dict):
            continue
        if str(item.get("account_id") or "") != account_id:
            continue
        if item.get("status") != STATUS_APPROVED:
            continue
        if is_revoked(str(item.get("key") or ""), st):
            continue
        out.append(dict(item))
    return out


def pending_count() -> int:
    st = load()
    n = 0
    for item in (st.get("items") or {}).values():
        if isinstance(item, dict) and item.get("status") == STATUS_PENDING:
            n += 1
    return n
