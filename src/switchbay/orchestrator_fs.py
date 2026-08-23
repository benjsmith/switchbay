"""Workspace-local Auto desk state (``.orchestrator/``).

Analogous to CE's ``.curator/``: operational, hidden, not the wiki.

This is **not** all-to-all file passing among workers. Intra-run
coordination stays on the typed evidence blackboard. This folder is
the *desk* — watchlist, caches, dated briefs, last-run timestamps —
so the next orchestration can read shared *inputs and artifacts*
without inheriting sibling conclusions.

Layout::

    .orchestrator/
      README.md
      watchlist.csv          # optional desk input
      briefs/                # dated synthesizer briefs (unreviewed)
      cache/filings/
      cache/transcripts/
      state/last.json
      state/snapshot.md      # last in-flight Auto snapshot (resume)
      log.md                 # append-only
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import atomicio

DIRNAME = ".orchestrator"


def root(workspace: Path) -> Path:
    return Path(workspace) / DIRNAME


def ensure(workspace: Path) -> Path:
    """Create the desk layout if missing. Idempotent."""
    r = root(workspace)
    for sub in ("briefs", "cache/filings", "cache/transcripts", "state"):
        (r / sub).mkdir(parents=True, exist_ok=True)
    readme = r / "README.md"
    if not readme.is_file():
        readme.write_text(
            "# .orchestrator\n\n"
            "Auto orchestration desk state. Not the wiki.\n\n"
            "- `watchlist.csv` — optional shared *input* (ticker,sector,thesis)\n"
            "- `APPROACH.md` — desk problem-solving sequence (optional)\n"
            "- `briefs/` — dated unreviewed briefs from the synthesizer\n"
            "- `cache/` — downloaded filings/transcripts (immutable)\n"
            "- `postmortems/` — overnight audits\n"
            "- `state/last.json` — last-run timestamps\n"
            "- `state/snapshot.md` — last in-flight Auto snapshot for resume\n"
            "- `state/org.json` — last effective desk roster (standing org)\n"
            "- `log.md` — append-only journal\n\n"
            "Investigators do not write here. Durable knowledge still goes "
            "through propose → Reviews → wiki.\n",
            encoding="utf-8",
        )
    logp = r / "log.md"
    if not logp.is_file():
        logp.write_text("# Orchestration log\n\n", encoding="utf-8")
    gitignore = r / ".gitignore"
    if not gitignore.is_file():
        gitignore.write_text(
            "# Operational; watchlist + README may roam.\n"
            "*\n"
            "!.gitignore\n"
            "!README.md\n"
            "!watchlist.csv\n"
            "!APPROACH.md\n",
            encoding="utf-8",
        )
    return r


def watchlist_path(workspace: Path) -> Path:
    return root(workspace) / "watchlist.csv"


def approach_path(workspace: Path) -> Path:
    return root(workspace) / "APPROACH.md"


def approach_excerpt(workspace: Path, *, limit: int = 6000) -> str:
    p = approach_path(workspace)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return ""
    return text[:limit]


def watchlist_excerpt(workspace: Path, *, limit: int = 4000) -> str:
    p = watchlist_path(workspace)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return ""
    return text[:limit]


def append_log(workspace: Path, block: str) -> None:
    ensure(workspace)
    p = root(workspace) / "log.md"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = (block or "").strip()
    if not body:
        return
    with p.open("a", encoding="utf-8") as f:
        f.write(f"## {stamp}\n\n{body}\n\n")


def write_brief(
    workspace: Path,
    orchestration_id: str,
    *,
    objective: str,
    output: str,
    findings_n: int = 0,
    conflicts: int = 0,
    unsupported: int = 0,
) -> Path:
    """Dated markdown brief. Unreviewed — not a wiki page."""
    ensure(workspace)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    slug = (orchestration_id or "run").replace("/", "-")[-16:]
    path = root(workspace) / "briefs" / f"{day}-{slug}.md"
    lines = [
        f"# Brief {orchestration_id}",
        "",
        f"_Objective:_ {objective.strip()[:500]}",
        "",
        f"Findings: {findings_n} · conflicts: {conflicts} · "
        f"unsupported: {unsupported}",
        "",
        "## Synthesis",
        "",
        (output or "_(no synthesizer output)_").strip()[:20_000],
        "",
        "Durable wiki pages still require propose → Reviews.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_desk_snapshot(
    workspace: Path, markdown: str, payload: dict[str, Any] | None = None,
) -> None:
    """Last-run snapshot the next chief of staff can read."""
    ensure(workspace)
    state = root(workspace) / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "snapshot.md").write_text(markdown or "", encoding="utf-8")
    if payload is not None:
        atomicio.write_json_atomic(state / "snapshot.json", payload)


def snapshot_excerpt(workspace: Path, *, limit: int = 4000) -> str:
    p = root(workspace) / "state" / "snapshot.md"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return ""
    return text[:limit]


ORG_VERSION = 1


def org_path(workspace: Path) -> Path:
    return root(workspace) / "state" / "org.json"


def save_org(workspace: Path, payload: dict[str, Any]) -> None:
    """Persist the last effective desk roster (no failed/pruned nodes)."""
    ensure(workspace)
    data = dict(payload)
    data["version"] = ORG_VERSION
    data["updated_at"] = time.time()
    atomicio.write_json_atomic(org_path(workspace), data)


def load_org(workspace: Path) -> dict[str, Any] | None:
    p = org_path(workspace)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != ORG_VERSION:
        return None
    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return None
    return data


def record_last(workspace: Path, payload: dict[str, Any]) -> None:
    ensure(workspace)
    data = dict(payload)
    data["updated_at"] = time.time()
    atomicio.write_json_atomic(root(workspace) / "state" / "last.json", data)


PLAYBOOK_VERSION = 1


def playbook_path(workspace: Path) -> Path:
    return root(workspace) / "state" / "playbook.json"


def load_playbook(workspace: Path) -> dict[str, Any]:
    p = playbook_path(workspace)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": PLAYBOOK_VERSION, "by_bucket": {}}
    if not isinstance(data, dict) or data.get("version") != PLAYBOOK_VERSION:
        return {"version": PLAYBOOK_VERSION, "by_bucket": {}}
    data.setdefault("by_bucket", {})
    return data


def remember_success(
    workspace: Path,
    *,
    policy_id: str,
    roster: list[tuple[str, str | None]],
    bucket: str = "",
) -> None:
    """Record a working roster for this desk. Sort hint only — not a lock-in."""
    ensure(workspace)
    clean = [
        [str(p), str(m) if m else ""]
        for p, m in roster
        if p
    ]
    if not clean:
        return
    st = load_playbook(workspace)
    rec = {
        "policy_id": policy_id,
        "roster": clean,
        "at": time.time(),
        "n": int((st.get("by_bucket") or {}).get(bucket, {}).get("n") or 0) + 1
        if bucket else 1,
    }
    st["last_ok"] = rec
    if bucket:
        buckets = st.setdefault("by_bucket", {})
        prev = buckets.get(bucket) if isinstance(buckets.get(bucket), dict) else {}
        rec = dict(rec)
        rec["n"] = int(prev.get("n") or 0) + 1
        buckets[bucket] = rec
    st["updated_at"] = time.time()
    st["version"] = PLAYBOOK_VERSION
    atomicio.write_json_atomic(playbook_path(workspace), st)


def preferred_roster(
    workspace: Path, *, bucket: str = "",
) -> list[tuple[str, str | None]]:
    st = load_playbook(workspace)
    rec = None
    if bucket:
        rec = (st.get("by_bucket") or {}).get(bucket)
    if not isinstance(rec, dict):
        rec = st.get("last_ok")
    if not isinstance(rec, dict):
        return []
    out: list[tuple[str, str | None]] = []
    for row in rec.get("roster") or []:
        if isinstance(row, (list, tuple)) and row:
            pid = str(row[0])
            model = str(row[1]) if len(row) > 1 and row[1] else None
            if pid:
                out.append((pid, model))
    return out


LANDED_VERSION = 1


def landed_path(workspace: Path) -> Path:
    return root(workspace) / "state" / "landed_pages.json"


def normalize_source(src: str) -> str:
    """Coarse locator so ``wiki/foo.md`` matches a finding source."""
    s = str(src or "").strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    if "wiki/" in s:
        s = "wiki/" + s.split("wiki/", 1)[-1]
    return s


def landed_pages(workspace: Path) -> set[str]:
    p = landed_path(workspace)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(data, dict) or data.get("version") != LANDED_VERSION:
        return set()
    raw = data.get("paths") or []
    if not isinstance(raw, list):
        return set()
    return {normalize_source(x) for x in raw if isinstance(x, str) and x.strip()}


def remember_landed(workspace: Path, path: str) -> None:
    """Desk inventory: a wiki/report path Auto (or rail) just wrote."""
    norm = normalize_source(path)
    if not norm:
        return
    ensure(workspace)
    paths = landed_pages(workspace)
    if norm in paths:
        return
    paths.add(norm)
    atomicio.write_json_atomic(landed_path(workspace), {
        "version": LANDED_VERSION,
        "updated_at": time.time(),
        "paths": sorted(paths),
    })


def forget_landed(workspace: Path, path: str) -> None:
    """Reviews dismiss — undo inventory, not a bandit penalty."""
    norm = normalize_source(path)
    if not norm:
        return
    paths = landed_pages(workspace)
    if norm not in paths:
        return
    paths.discard(norm)
    ensure(workspace)
    atomicio.write_json_atomic(landed_path(workspace), {
        "version": LANDED_VERSION,
        "updated_at": time.time(),
        "paths": sorted(paths),
    })


def reused_desk_sources(workspace: Path, sources: set[str] | list[str]) -> int:
    """How many of this run's sources were pages the desk already landed."""
    prior = landed_pages(workspace)
    if not prior:
        return 0
    seen = {normalize_source(s) for s in sources if s}
    return len(seen & prior)
