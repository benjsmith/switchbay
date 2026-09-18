"""Per-desk live worker admission.

Concurrency is a live-seat gate (queue/backpressure), not a lifetime
spawn budget and not an early stop. The **chief is counted**. Nested
CE workers share the same workspace+desk domain.

Default 8 total live seats. User-configurable floor is 4 (chief +
verifier + synthesizer + specialist). Admin/baked policy may only
tighten the ceiling; preference/model/plan/nested dispatch cannot
raise it.

Cap is re-read from Settings/admin on acquire and while waiters
block. Raising the cap wakes waiters; lowering admits no extras
until live work drains under the new cap. Coordinating parents
park their seat while awaiting nested children so the desk cannot
deadlock when every holder is a waiter.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path
from typing import Any

from . import orchestration_policy as policy

log = logging.getLogger("switchbay.agents.desk_admission")

# Chief occupies one live seat for the life of execute().
CHIEF_COUNTED = True
MIN_LIVE_SEATS = 4
DEFAULT_LIVE_SEATS = 8

_GATES: dict[str, "DeskGate"] = {}
_GATES_LOCK = threading.Lock()


def effective_live_cap(workspace: Any = None) -> int:
    """Server-enforced total live seats per desk, chief included.

    ``max(MIN_LIVE_SEATS, min(user, admin_ceiling, HARD_MAX_CONCURRENCY))``.
    Admin/baked values only tighten.
    """
    from .. import admin_policy, app_settings

    hard = int(policy.HARD_MAX_CONCURRENCY) if policy.HARD_MAX_CONCURRENCY > 0 else DEFAULT_LIVE_SEATS
    if hard < MIN_LIVE_SEATS:
        hard = MIN_LIVE_SEATS
    user = app_settings.get_desk_max_live_workers()
    try:
        user_n = int(user)
    except (TypeError, ValueError):
        user_n = DEFAULT_LIVE_SEATS
    user_n = max(MIN_LIVE_SEATS, min(user_n, hard))
    ceiling = admin_policy.max_live_workers_ceiling()
    if ceiling is not None:
        try:
            ceil_n = int(ceiling)
        except (TypeError, ValueError):
            ceil_n = hard
        # Admin may only tighten; never raise above the code hard cap.
        user_n = min(user_n, max(MIN_LIVE_SEATS, min(ceil_n, hard)))
    return max(MIN_LIVE_SEATS, min(user_n, hard))


def public_view(workspace: Any = None) -> dict[str, Any]:
    cap = effective_live_cap(workspace)
    from .. import admin_policy, app_settings
    return {
        "desk_max_live_workers": cap,
        "requested": app_settings.get_desk_max_live_workers(),
        "min": MIN_LIVE_SEATS,
        "default": DEFAULT_LIVE_SEATS,
        "hard_max": int(policy.HARD_MAX_CONCURRENCY) or DEFAULT_LIVE_SEATS,
        "admin_ceiling": admin_policy.max_live_workers_ceiling(),
        "chief_counted": CHIEF_COUNTED,
        "note": (
            "Total live seats per desk, including the chief-of-staff. "
            f"Floor {MIN_LIVE_SEATS} (chief + verifier + synthesizer + specialist). "
            "Admin policy may only lower the ceiling."
        ),
    }


def desk_domain_id(workspace: Path | str | None, desk_id: str | None) -> str:
    """Stable admission domain: one gate per workspace + standing desk."""
    desk = str(desk_id or "desk").strip() or "desk"
    if workspace is None or str(workspace) == "":
        return desk
    try:
        ws = str(Path(workspace).expanduser().resolve())
    except (OSError, RuntimeError, ValueError):
        ws = str(workspace)
    return f"{ws}::{desk}"


def slot_id(run_id: str | None, name: str) -> str:
    """Lease identity unique across overlapping runs on the same desk."""
    rid = str(run_id or "").strip()
    nm = str(name or "").strip() or "worker"
    if not rid:
        return nm
    return f"{rid}:{nm}"


# Tests patch this so acquire waiters notice cap changes quickly.
ACQUIRE_WAIT_TIMEOUT = 2.0


def _wait_timeout() -> float:
    return float(ACQUIRE_WAIT_TIMEOUT)


class DeskGate:
    """One admission domain (workspace + desk, shared by overlapping runs)."""

    def __init__(self, desk_id: str, cap: int, *, workspace: Any = None) -> None:
        self.desk_id = desk_id
        self._workspace = workspace
        self._follow_settings = workspace is not None
        self._cap = max(MIN_LIVE_SEATS, int(cap))
        self._held: dict[str, str] = {}  # slot_id -> kind
        self._parked: dict[str, str] = {}  # slot_id -> kind (not counted)
        self._refs = 0
        self._cond = asyncio.Condition()

    @property
    def cap(self) -> int:
        return self._cap

    def live(self) -> int:
        return len(self._held)

    def free(self) -> int:
        return max(0, self._cap - len(self._held))

    def snapshot(self) -> dict[str, Any]:
        return {
            "desk_id": self.desk_id,
            "cap": self._cap,
            "live": len(self._held),
            "parked": len(self._parked),
            "refs": self._refs,
            "chief_counted": CHIEF_COUNTED,
            "slots": dict(self._held),
        }

    def refresh_cap(self, workspace: Any = None) -> int:
        """Re-read Settings/admin ceiling and wake waiters if the cap rose.

        Explicit test/pinned caps (no workspace) stay put so a fixture
        ``DeskGate(..., cap=4)`` is not rewritten to the user default.
        """
        if workspace is not None:
            self._workspace = workspace
            self._follow_settings = True
        if not self._follow_settings:
            return self._cap
        cap = effective_live_cap(self._workspace)
        if cap != self._cap:
            self.set_cap(cap)
        return self._cap

    def set_cap(self, cap: int) -> None:
        new = max(MIN_LIVE_SEATS, int(cap))
        prev = self._cap
        self._cap = new
        if new != prev:
            self._wake()

    def retain(self) -> None:
        self._refs += 1

    def drop_ref(self) -> int:
        self._refs = max(0, self._refs - 1)
        return self._refs

    def _wake(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if not loop.is_running():
            return

        async def _notify() -> None:
            async with self._cond:
                self._cond.notify_all()

        try:
            loop.create_task(_notify())
        except RuntimeError:
            pass

    def _drop_slot(self, sid: str) -> bool:
        gone = False
        if sid in self._held:
            self._held.pop(sid, None)
            gone = True
        if sid in self._parked:
            self._parked.pop(sid, None)
            gone = True
        return gone

    async def acquire(self, slot_id: str, *, kind: str = "worker") -> bool:
        if not slot_id:
            return False
        async with self._cond:
            if slot_id in self._held:
                return True
            # A parked parent restoring via acquire (not unpark) is live again.
            self._parked.pop(slot_id, None)
            while True:
                self.refresh_cap()
                if len(self._held) < self._cap:
                    break
                try:
                    await asyncio.wait_for(self._cond.wait(), timeout=_wait_timeout())
                except asyncio.TimeoutError:
                    continue
            self._held[slot_id] = kind
            return True

    def try_acquire(self, slot_id: str, *, kind: str = "worker") -> bool:
        if not slot_id:
            return False
        if slot_id in self._held:
            return True
        self.refresh_cap()
        if len(self._held) >= self._cap:
            return False
        self._parked.pop(slot_id, None)
        self._held[slot_id] = kind
        return True

    def release(self, slot_id: str) -> None:
        if not slot_id:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            loop.create_task(self._release_async(slot_id))
            return
        self._drop_slot(slot_id)

    async def _release_async(self, slot_id: str) -> None:
        async with self._cond:
            self._drop_slot(slot_id)
            self._cond.notify_all()

    async def release_async(self, slot_id: str) -> None:
        await self._release_async(slot_id)

    async def park(self, slot_id: str) -> bool:
        """Temporarily free a coordinating parent's seat while nested work runs.

        Live count drops; the slot is remembered so restore is identity-safe.
        Nested children can then take the seat. No-op if the slot is not held.
        """
        if not slot_id:
            return False
        async with self._cond:
            kind = self._held.pop(slot_id, None)
            if kind is None:
                return False
            self._parked[slot_id] = kind
            self._cond.notify_all()
            return True

    async def unpark(self, slot_id: str, *, restore: bool = True) -> bool:
        """Restore a parked parent seat, or drop it if the parent is dying."""
        if not slot_id:
            return False
        try:
            async with self._cond:
                kind = self._parked.pop(slot_id, None)
                if kind is None:
                    return slot_id in self._held
                if not restore:
                    self._cond.notify_all()
                    return False
                if slot_id in self._held:
                    return True
                while True:
                    self.refresh_cap()
                    if len(self._held) < self._cap:
                        break
                    try:
                        await asyncio.wait_for(
                            self._cond.wait(), timeout=_wait_timeout(),
                        )
                    except asyncio.TimeoutError:
                        continue
                self._held[slot_id] = kind
                return True
        except asyncio.CancelledError:
            async with self._cond:
                self._parked.pop(slot_id, None)
                self._held.pop(slot_id, None)
                self._cond.notify_all()
            raise


def gate_for(
    desk_id: str,
    *,
    cap: int | None = None,
    workspace: Any = None,
) -> DeskGate:
    cid = str(desk_id or "desk")
    with _GATES_LOCK:
        g = _GATES.get(cid)
        if g is None:
            g = DeskGate(
                cid,
                cap if cap is not None else effective_live_cap(workspace),
                workspace=workspace,
            )
            _GATES[cid] = g
        else:
            if workspace is not None:
                g._workspace = workspace
                g._follow_settings = True
            if cap is not None and not g._follow_settings:
                g.set_cap(cap)
            else:
                g.refresh_cap(workspace)
        return g


def drop_gate(desk_id: str) -> None:
    with _GATES_LOCK:
        g = _GATES.get(str(desk_id or ""))
        if g is None:
            return
        if g._refs > 0 or g._held or g._parked:
            return
        _GATES.pop(str(desk_id or ""), None)


def release_domain(gate: DeskGate | None) -> None:
    if gate is None:
        return
    gate.drop_ref()
    drop_gate(gate.desk_id)


def reset_for_tests() -> None:
    with _GATES_LOCK:
        _GATES.clear()
