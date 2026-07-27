"""Multi-option local models: hardware top-3 picks, 6-week refresh,
HF/Ollama discovery, add/remove.

Complements ``localllm.py`` (llama-server install pipeline). Ornith is
one candidate among several — not the only easy-install path.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import app_settings, atomicio, localllm, statedir

log = logging.getLogger("switchbay.local_models")

CHECK_INTERVAL_S = 6 * 7 * 24 * 3600  # ~6 weeks

# Curated catalog — ids are stable. ``backend`` is llamacpp (GGUF) or
# ollama (tag pull). ``min_ram_gb`` is a soft floor; plan_top3 ranks by fit.
CATALOG: list[dict[str, Any]] = [
    {
        "id": "ornith-9b",
        "label": "Ornith 1.0 9B",
        "backend": "llamacpp",
        "family": "agent",
        "min_ram_gb": 16,
        "ideal_ram_gb": 32,
        "repo": "deepreinforce-ai/Ornith-1.0-9B-GGUF",
        "quants": {
            "Q4_K_M": ("ornith-1.0-9b-Q4_K_M.gguf", 5.63),
            "Q5_K_M": ("ornith-1.0-9b-Q5_K_M.gguf", 6.47),
            "Q6_K": ("ornith-1.0-9b-Q6_K.gguf", 7.36),
            "Q8_0": ("ornith-1.0-9b-Q8_0.gguf", 9.53),
        },
        "blurb": "Agent-tuned hybrid model; strong on tool use and wiki chores.",
        "why_default": "Best agentic chore model in the easy-install set.",
    },
    {
        "id": "ornith-35b",
        "label": "Ornith 1.0 35B",
        "backend": "llamacpp",
        "family": "agent",
        "min_ram_gb": 48,
        "ideal_ram_gb": 64,
        "repo": "deepreinforce-ai/Ornith-1.0-35B-GGUF",
        "quants": {
            "Q4_K_M": ("ornith-1.0-35b-Q4_K_M.gguf", 21.17),
            "Q5_K_M": ("ornith-1.0-35b-Q5_K_M.gguf", 24.73),
            "Q6_K": ("ornith-1.0-35b-Q6_K.gguf", 28.51),
            "Q8_0": ("ornith-1.0-35b-Q8_0.gguf", 36.9),
        },
        "blurb": "Larger agent model when you have ≥48 GB RAM.",
        "why_default": "Higher-quality local agent when the machine can hold it.",
    },
    {
        "id": "qwen25-coder-7b",
        "label": "Qwen2.5-Coder 7B",
        "backend": "llamacpp",
        "family": "coding",
        "min_ram_gb": 12,
        "ideal_ram_gb": 24,
        "repo": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
        "quants": {
            "Q4_K_M": ("qwen2.5-coder-7b-instruct-q4_k_m.gguf", 4.68),
            "Q5_K_M": ("qwen2.5-coder-7b-instruct-q5_k_m.gguf", 5.44),
            "Q6_K": ("qwen2.5-coder-7b-instruct-q6_k.gguf", 6.25),
        },
        "blurb": "Coding-focused instruct model; good for code + light agent work.",
        "why_default": "Strong open coding model for micro-edits and tool JSON.",
        "ollama_tag": "qwen2.5-coder:7b",
    },
    {
        "id": "llama32-3b",
        "label": "Llama 3.2 3B",
        "backend": "llamacpp",
        "family": "general",
        "min_ram_gb": 8,
        "ideal_ram_gb": 16,
        "repo": "bartowski/Llama-3.2-3B-Instruct-GGUF",
        "quants": {
            "Q4_K_M": ("Llama-3.2-3B-Instruct-Q4_K_M.gguf", 2.02),
            "Q5_K_M": ("Llama-3.2-3B-Instruct-Q5_K_M.gguf", 2.32),
            "Q8_0": ("Llama-3.2-3B-Instruct-Q8_0.gguf", 3.42),
        },
        "blurb": "Small general instruct model for machines under ~16 GB.",
        "why_default": "Fits tight RAM; fine for titles, triage, and short edits.",
        "ollama_tag": "llama3.2:3b",
    },
    {
        "id": "qwen25-14b",
        "label": "Qwen2.5 14B Instruct",
        "backend": "llamacpp",
        "family": "general",
        "min_ram_gb": 24,
        "ideal_ram_gb": 40,
        "repo": "bartowski/Qwen2.5-14B-Instruct-GGUF",
        "quants": {
            "Q4_K_M": ("Qwen2.5-14B-Instruct-Q4_K_M.gguf", 8.99),
            "Q5_K_M": ("Qwen2.5-14B-Instruct-Q5_K_M.gguf", 10.5),
        },
        "blurb": "Mid-size general model — stronger prose and reasoning than 7B class.",
        "why_default": "Step up from 7B when you have ~24–40 GB free.",
        "ollama_tag": "qwen2.5:14b",
    },
    {
        "id": "ollama-qwen25-coder",
        "label": "Qwen2.5-Coder 7B (Ollama)",
        "backend": "ollama",
        "family": "coding",
        "min_ram_gb": 12,
        "ideal_ram_gb": 20,
        "ollama_tag": "qwen2.5-coder:7b",
        "blurb": "Same coding model via Ollama — no GGUF manage if you already use Ollama.",
        "why_default": "One-command pull if Ollama is already installed.",
    },
    {
        "id": "ollama-llama32",
        "label": "Llama 3.2 3B (Ollama)",
        "backend": "ollama",
        "family": "general",
        "min_ram_gb": 8,
        "ideal_ram_gb": 12,
        "ollama_tag": "llama3.2:3b",
        "blurb": "Tiny general model via Ollama for low-RAM machines.",
        "why_default": "Easiest path under 16 GB when llama-server is heavy.",
    },
]


def _ram() -> float:
    return localllm.ram_gb()


def _pick_quant(entry: dict[str, Any], ram: float) -> tuple[str, str, float] | None:
    quants = entry.get("quants") or {}
    if not quants:
        return None
    # Prefer higher quality that still fits ~0.55 of RAM for weights.
    budget = max(2.0, ram * 0.45)
    ordered = sorted(quants.items(), key=lambda kv: kv[1][1], reverse=True)
    for qname, (fname, gb) in ordered:
        if gb <= budget:
            return qname, fname, float(gb)
    # Fall back to smallest
    qname, (fname, gb) = min(quants.items(), key=lambda kv: kv[1][1])
    return qname, fname, float(gb)


def _score(entry: dict[str, Any], ram: float) -> float:
    """Higher = better fit for this machine. Prefer diverse families."""
    mn = float(entry.get("min_ram_gb") or 0)
    ideal = float(entry.get("ideal_ram_gb") or mn)
    if ram + 1.0 < mn:
        return -1.0
    # Prefer models near ideal RAM (not too small wastefully).
    dist = abs(ram - ideal)
    fit = 100.0 - dist * 2.0
    # Slight boost for agent family on larger machines, coding on mid.
    family = entry.get("family") or ""
    if family == "agent" and ram >= 24:
        fit += 8
    if family == "coding" and 12 <= ram < 48:
        fit += 6
    if family == "general" and ram < 20:
        fit += 5
    # Prefer llamacpp managed path when RAM is ample (one stack).
    if entry.get("backend") == "llamacpp" and ram >= 16:
        fit += 3
    if entry.get("backend") == "ollama" and ram < 16:
        fit += 4
    return fit


def plan_top3(ram: float | None = None) -> dict[str, Any]:
    """Best three hardware-appropriate easy-install candidates."""
    ram = ram if ram is not None else _ram()
    ranked: list[tuple[float, dict[str, Any]]] = []
    for entry in CATALOG:
        s = _score(entry, ram)
        if s < 0:
            continue
        ranked.append((s, entry))
    ranked.sort(key=lambda x: -x[0])

    # Diversify families: pick top score, then prefer different family.
    picks: list[dict[str, Any]] = []
    used_families: set[str] = set()
    for s, entry in ranked:
        fam = str(entry.get("family") or entry["id"])
        if len(picks) >= 3:
            break
        if fam in used_families and len(picks) < 2:
            continue  # force diversity early
        if fam in used_families and any(p["family"] == fam for p in picks):
            # allow second of same family only if we still need slots
            if len(picks) < 2:
                continue
        cand = _candidate_payload(entry, ram, rank=len(picks) + 1, score=s)
        if cand:
            picks.append(cand)
            used_families.add(fam)
    # Fill remaining without diversity constraint
    if len(picks) < 3:
        for s, entry in ranked:
            if any(p["id"] == entry["id"] for p in picks):
                continue
            cand = _candidate_payload(entry, ram, rank=len(picks) + 1, score=s)
            if cand:
                picks.append(cand)
            if len(picks) >= 3:
                break

    return {
        "ok": len(picks) > 0,
        "ram_gb": round(ram, 1),
        "candidates": picks,
        "reason": None if picks else (
            f"~{ram:.0f} GB RAM — no catalog models fit. "
            "Install Ollama and pull a small model, or use cloud rungs."
        ),
    }


def _candidate_payload(
    entry: dict[str, Any], ram: float, *, rank: int, score: float,
) -> dict[str, Any] | None:
    backend = entry["backend"]
    out: dict[str, Any] = {
        "id": entry["id"],
        "label": entry["label"],
        "backend": backend,
        "family": entry.get("family"),
        "blurb": entry.get("blurb"),
        "why": entry.get("why_default"),
        "rank": rank,
        "score": round(score, 1),
        "min_ram_gb": entry.get("min_ram_gb"),
        "installed": is_installed(entry["id"]),
    }
    if backend == "llamacpp":
        pq = _pick_quant(entry, ram)
        if not pq:
            return None
        quant, fname, wgb = pq
        est = round(wgb + max(2.0, ram * 0.15), 1)
        out.update({
            "repo": entry["repo"],
            "quant": quant,
            "file": fname,
            "weights_gb": wgb,
            "est_gb": est,
            "ctx": 32768 if ram < 32 else 65536,
        })
    else:
        out["ollama_tag"] = entry.get("ollama_tag")
        out["est_gb"] = float(entry.get("min_ram_gb") or 8) * 0.6
    return out


def catalog_by_id(cid: str) -> dict[str, Any] | None:
    for e in CATALOG:
        if e["id"] == cid:
            return e
    return None


def _registry_path() -> Path:
    return statedir.state_root() / "local-models.json"


def load_registry() -> dict[str, Any]:
    p = _registry_path()
    if not p.is_file():
        # Migrate legacy localllm single config into registry.
        legacy = localllm.load_config()
        if legacy:
            cid = "ornith-9b"
            return {
                "active": cid,
                "installed": {
                    cid: {
                        "id": cid,
                        "label": legacy.get("model_label") or "Ornith",
                        "backend": "llamacpp",
                        "file": legacy.get("file"),
                        "quant": legacy.get("quant"),
                        "ctx": legacy.get("ctx"),
                        "alias": legacy.get("alias") or "ornith",
                        "installed_at": legacy.get("installed_at"),
                    },
                },
                "last_check_prompt_at": 0,
                "last_discovery_at": 0,
                "discovery": None,
            }
        return {
            "active": None,
            "installed": {},
            "last_check_prompt_at": 0,
            "last_discovery_at": 0,
            "discovery": None,
        }
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"active": None, "installed": {}, "last_check_prompt_at": 0,
                "last_discovery_at": 0, "discovery": None}
    return data if isinstance(data, dict) else {
        "active": None, "installed": {}, "last_check_prompt_at": 0,
        "last_discovery_at": 0, "discovery": None,
    }


def save_registry(data: dict[str, Any]) -> None:
    p = _registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, data)


def is_installed(cid: str) -> bool:
    reg = load_registry()
    inst = reg.get("installed") or {}
    if cid in inst:
        return True
    # Legacy single ornith file
    cfg = localllm.load_config()
    if cfg and cid.startswith("ornith"):
        return True
    if cid.startswith("ollama-"):
        tag = (catalog_by_id(cid) or {}).get("ollama_tag")
        if tag:
            return tag in ollama_list_tags()
    return False


def list_installed() -> list[dict[str, Any]]:
    reg = load_registry()
    out = list((reg.get("installed") or {}).values())
    # Ollama pulls not in registry
    for entry in CATALOG:
        if entry.get("backend") != "ollama":
            continue
        tag = entry.get("ollama_tag")
        if tag and tag in ollama_list_tags():
            if not any(x.get("id") == entry["id"] for x in out):
                out.append({
                    "id": entry["id"],
                    "label": entry["label"],
                    "backend": "ollama",
                    "ollama_tag": tag,
                    "source": "ollama-list",
                })
    return out


def ollama_list_tags() -> set[str]:
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as r:
            body = json.load(r)
    except Exception:  # noqa: BLE001
        return set()
    tags: set[str] = set()
    for m in body.get("models") or []:
        name = str(m.get("name") or "")
        if name:
            tags.add(name)
            # also bare name without :latest
            if ":" in name:
                tags.add(name.split(":", 1)[0])
    return tags


def should_prompt_refresh() -> bool:
    """True if user uses local models and 6 weeks elapsed since last prompt."""
    reg = load_registry()
    if not list_installed() and not localllm.load_config():
        # Also prompt if ladder points at local
        try:
            from . import modestore
            ladder = modestore.global_ladder()
            uses_local = any(
                (ladder.get(r) or {}).get("provider") in ("llamacpp", "ollama")
                for r in ("trivial", "normal", "hard")
            )
            if not uses_local:
                return False
        except Exception:  # noqa: BLE001
            return False
    last = float(reg.get("last_check_prompt_at") or 0)
    return (time.time() - last) >= CHECK_INTERVAL_S


def mark_check_prompt_shown() -> None:
    reg = load_registry()
    reg["last_check_prompt_at"] = time.time()
    save_registry(reg)


def mark_discovery(result: dict[str, Any]) -> None:
    reg = load_registry()
    reg["last_discovery_at"] = time.time()
    reg["discovery"] = result
    save_registry(reg)


def get_discovery() -> dict[str, Any] | None:
    reg = load_registry()
    d = reg.get("discovery")
    return d if isinstance(d, dict) else None


def hf_model_info(repo: str) -> dict[str, Any] | None:
    """Public HF API — downloads/likes if available."""
    url = f"https://huggingface.co/api/models/{repo}"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "switchbay-local-models/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.load(r)
    except Exception as e:  # noqa: BLE001
        log.debug("hf info %s: %s", repo, e)
        return None


def hf_list_repo_files(repo: str) -> list[str] | None:
    """List filenames at repo root via HF tree API. None on network error."""
    url = f"https://huggingface.co/api/models/{repo}/tree/main"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "switchbay-local-models/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
    except Exception as e:  # noqa: BLE001
        log.debug("hf tree %s: %s", repo, e)
        return None
    if not isinstance(data, list):
        return None
    names: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if path and not path.endswith("/"):
            # Keep basename for nested GGUF paths
            names.append(path.rsplit("/", 1)[-1] if "/" in path else path)
            if "/" in path:
                names.append(path)
    return names


def _fuzzy_gguf_match(wanted: str, available: list[str]) -> str | None:
    """Find a repo file matching wanted GGUF when exact name drifted."""
    if wanted in available:
        return wanted
    w = wanted.lower()
    # Exact case-insensitive
    for a in available:
        if a.lower() == w:
            return a
    # Same quant token + extension
    quant = None
    for token in ("q4_k_m", "q5_k_m", "q6_k", "q8_0", "q4_0", "q5_0"):
        if token in w.replace("-", "_"):
            quant = token
            break
    stem = w.replace(".gguf", "").replace("-", "").replace("_", "")
    candidates = [a for a in available if a.lower().endswith(".gguf")]
    if quant:
        q_hits = [
            a for a in candidates
            if quant in a.lower().replace("-", "_")
        ]
        if len(q_hits) == 1:
            return q_hits[0]
        # Prefer stem overlap among quant hits
        best = None
        best_score = 0
        for a in q_hits:
            al = a.lower().replace("-", "").replace("_", "").replace(".gguf", "")
            score = sum(1 for i in range(min(len(stem), len(al))) if stem[i] == al[i])
            if score > best_score:
                best_score = score
                best = a
        if best and best_score >= 6:
            return best
    return None


def verify_catalog_filenames() -> dict[str, Any]:
    """Check catalog GGUF filenames against HF tree; suggest fixes.

    Does not invent files — only reports exact/fuzzy matches or missing.
    """
    results: list[dict[str, Any]] = []
    for entry in CATALOG:
        if entry.get("backend") != "llamacpp" or not entry.get("repo"):
            continue
        repo = str(entry["repo"])
        files = hf_list_repo_files(repo)
        quants = entry.get("quants") or {}
        for quant, qinfo in quants.items():
            if not isinstance(qinfo, (list, tuple)) or not qinfo:
                continue
            fname = str(qinfo[0])
            row: dict[str, Any] = {
                "id": entry["id"],
                "repo": repo,
                "quant": quant,
                "catalog_file": fname,
            }
            if files is None:
                row["status"] = "unchecked"
                row["note"] = "HF tree unavailable"
            elif fname in files:
                row["status"] = "ok"
            else:
                alt = _fuzzy_gguf_match(fname, files)
                if alt:
                    row["status"] = "renamed"
                    row["resolved_file"] = alt
                    row["note"] = f"catalog {fname!r} → repo {alt!r}"
                else:
                    row["status"] = "missing"
                    row["note"] = f"{fname!r} not in repo tree"
                    row["sample_gguf"] = [
                        f for f in files if f.lower().endswith(".gguf")
                    ][:8]
            results.append(row)
    return {
        "ok": True,
        "checked_at": time.time(),
        "entries": results,
        "ok_count": sum(1 for r in results if r.get("status") == "ok"),
        "renamed_count": sum(1 for r in results if r.get("status") == "renamed"),
        "missing_count": sum(1 for r in results if r.get("status") == "missing"),
    }


def resolve_gguf_filename(entry: dict[str, Any], quant: str) -> tuple[str, str | None]:
    """Return (filename, note) for install — prefers verified HF name."""
    quants = entry.get("quants") or {}
    qinfo = quants.get(quant)
    if not isinstance(qinfo, (list, tuple)) or not qinfo:
        raise ValueError(f"no quant {quant} for {entry.get('id')}")
    catalog_name = str(qinfo[0])
    repo = str(entry.get("repo") or "")
    if not repo:
        return catalog_name, None
    files = hf_list_repo_files(repo)
    if files is None:
        return catalog_name, "HF tree unchecked — using catalog filename"
    if catalog_name in files:
        return catalog_name, None
    alt = _fuzzy_gguf_match(catalog_name, files)
    if alt:
        return alt, f"resolved renamed GGUF: {catalog_name} → {alt}"
    raise ValueError(
        f"GGUF {catalog_name!r} not found in HF repo {repo}; "
        f"known: {[f for f in files if f.lower().endswith('.gguf')][:6]}"
    )


def allocate_port(reg: dict[str, Any] | None = None, *, prefer: int | None = None) -> int:
    """Pick a free port from the managed pool for a new llama-server."""
    reg = reg if reg is not None else load_registry()
    used: set[int] = set()
    for meta in (reg.get("installed") or {}).values():
        if isinstance(meta, dict) and meta.get("port"):
            try:
                used.add(int(meta["port"]))
            except (TypeError, ValueError):
                pass
    cfg = localllm.load_config()
    if cfg and cfg.get("port"):
        try:
            used.add(int(cfg["port"]))
        except (TypeError, ValueError):
            pass
    if prefer is not None and prefer not in used:
        return prefer
    for p in localllm.PORT_POOL:
        if p not in used:
            return p
    # All taken — still return prefer or base (will stop conflicting slot)
    return prefer or localllm.PORT


def activate(cid: str) -> dict[str, Any]:
    """Mark installed model active and build localllm config for it.

    Caller (daemon) is responsible for spawning/stopping servers.
    """
    reg = load_registry()
    inst = (reg.get("installed") or {}).get(cid)
    entry = catalog_by_id(cid) or {}
    if not inst and not entry:
        return {"ok": False, "error": f"unknown model id {cid!r}"}
    meta = dict(inst or {})
    backend = str(meta.get("backend") or entry.get("backend") or "llamacpp")
    reg["active"] = cid
    save_registry(reg)

    if backend == "ollama":
        tag = meta.get("ollama_tag") or entry.get("ollama_tag")
        return {
            "ok": True,
            "id": cid,
            "backend": "ollama",
            "ollama_tag": tag,
            "active": cid,
            "cfg": None,
            "note": "Active for ladder — Ollama serves this tag on demand.",
        }

    path = meta.get("file")
    if not path or not Path(str(path)).is_file():
        return {
            "ok": False,
            "error": f"no GGUF file on disk for {cid!r} — reinstall",
            "id": cid,
        }
    port = int(meta.get("port") or allocate_port(reg, prefer=localllm.PORT))
    alias = str(meta.get("alias") or cid.replace("-", "_")[:24])
    cfg = {
        "model": meta.get("model") or cid,
        "model_label": meta.get("label") or entry.get("label") or cid,
        "quant": meta.get("quant"),
        "file": str(path),
        "ctx": int(meta.get("ctx") or 32768),
        "kv_quant": meta.get("kv_quant") or "q8_0",
        "port": port,
        "alias": alias,
        "candidate_id": cid,
        "installed_at": meta.get("installed_at") or time.time(),
    }
    # Keep legacy localllm.json pointed at active server for chat path
    localllm.save_config(cfg)
    # Persist port on registry entry
    reg = load_registry()
    inst2 = dict(reg.get("installed") or {})
    if cid in inst2:
        inst2[cid] = {**inst2[cid], "port": port, "alias": alias}
        reg["installed"] = inst2
        reg["active"] = cid
        save_registry(reg)
    return {
        "ok": True,
        "id": cid,
        "backend": "llamacpp",
        "active": cid,
        "cfg": cfg,
        "port": port,
    }


def discover_updates() -> dict[str, Any]:
    """Background discovery: refresh catalog candidates vs installed,
    pull HF popularity signals, list ollama-available tags.

    Does not claim fabricated benchmark scores — only HF downloads/likes
    and catalog blurbs. Recommendations explain *why* from real signals.
    """
    ram = _ram()
    plan = plan_top3(ram)
    installed = {m.get("id"): m for m in list_installed()}
    suggestions: list[dict[str, Any]] = []
    removals: list[dict[str, Any]] = []

    for cand in plan.get("candidates") or []:
        cid = cand["id"]
        entry = catalog_by_id(cid) or {}
        if cid in installed or cand.get("installed"):
            continue
        why_parts = [str(cand.get("why") or cand.get("blurb") or "")]
        if entry.get("backend") == "llamacpp" and entry.get("repo"):
            info = hf_model_info(str(entry["repo"]))
            if info:
                dl = info.get("downloads")
                likes = info.get("likes")
                if isinstance(dl, int) and dl > 0:
                    why_parts.append(f"~{dl:,} HF downloads")
                if isinstance(likes, int) and likes > 0:
                    why_parts.append(f"{likes} likes on Hugging Face")
        if entry.get("backend") == "ollama":
            why_parts.append("Available via Ollama pull (no GGUF manage).")
        suggestions.append({
            **cand,
            "action": "add",
            "summary": " · ".join(p for p in why_parts if p)[:220],
        })

    # Also surface catalog entries not in top3 but installed options for remove
    for cid, meta in installed.items():
        entry = catalog_by_id(str(cid)) or {}
        removals.append({
            "id": cid,
            "label": meta.get("label") or cid,
            "backend": meta.get("backend") or entry.get("backend"),
            "action": "remove",
            "summary": "Currently installed — remove to free disk if unused.",
        })

    # HF "new" signal: if a non-installed catalog model has high recent interest
    for entry in CATALOG:
        if entry["id"] in installed:
            continue
        if any(s["id"] == entry["id"] for s in suggestions):
            continue
        if float(entry.get("min_ram_gb") or 99) > ram + 2:
            continue
        info = None
        if entry.get("backend") == "llamacpp" and entry.get("repo"):
            info = hf_model_info(str(entry["repo"]))
        if info and int(info.get("downloads") or 0) > 50_000:
            cand = _candidate_payload(entry, ram, rank=0, score=_score(entry, ram))
            if cand:
                suggestions.append({
                    **cand,
                    "action": "add",
                    "summary": (
                        f"{entry.get('blurb', '')} · "
                        f"popular on HF (~{int(info.get('downloads') or 0):,} downloads)"
                    )[:220],
                })

    verification = verify_catalog_filenames()
    # Surface renamed/missing GGUFs as install warnings in suggestions
    rename_map = {
        (r["id"], r["quant"]): r
        for r in verification.get("entries") or []
        if r.get("status") in ("renamed", "missing")
    }
    for s in suggestions:
        key = (s.get("id"), s.get("quant"))
        if key in rename_map:
            r = rename_map[key]
            if r.get("status") == "renamed":
                s["summary"] = (
                    (s.get("summary") or "") + f" · GGUF now {r.get('resolved_file')}"
                )[:220]
                s["gguf_file"] = r.get("resolved_file")
            elif r.get("status") == "missing":
                s["summary"] = (
                    (s.get("summary") or "") + " · catalog GGUF missing on HF"
                )[:220]
                s["gguf_missing"] = True

    result = {
        "ok": True,
        "ram_gb": round(ram, 1),
        "checked_at": time.time(),
        "suggestions": suggestions[:8],
        "removals": removals,
        "gguf_verification": verification,
        "note": (
            "Summaries use catalog notes + Hugging Face download/like signals "
            "when available. We do not invent benchmark scores. GGUF filenames "
            "are checked against the HF tree when reachable."
        ),
    }
    mark_discovery(result)
    return result


def register_installed(cid: str, meta: dict[str, Any], *, activate: bool = True) -> None:
    reg = load_registry()
    inst = dict(reg.get("installed") or {})
    inst[cid] = {"id": cid, **meta, "installed_at": time.time()}
    reg["installed"] = inst
    if activate:
        reg["active"] = cid
    save_registry(reg)


def unregister(cid: str) -> dict[str, Any]:
    """Remove registry entry and delete GGUF file if managed. Returns summary."""
    reg = load_registry()
    inst = dict(reg.get("installed") or {})
    meta = inst.pop(cid, None) or {}
    freed = 0
    path = meta.get("file")
    if path and Path(str(path)).is_file():
        try:
            p = Path(str(path))
            freed = p.stat().st_size
            p.unlink()
        except OSError as e:
            log.warning("unlink %s: %s", path, e)
    if reg.get("active") == cid:
        reg["active"] = next(iter(inst), None)
    reg["installed"] = inst
    save_registry(reg)
    # Ollama: we don't auto-rm models (user may use outside SB); note only
    return {
        "ok": True,
        "id": cid,
        "freed_bytes": freed,
        "backend": meta.get("backend"),
        "ollama_note": (
            f"Ollama tag still on disk — run `ollama rm {meta.get('ollama_tag')}` "
            "if you want it gone."
            if meta.get("backend") == "ollama" else None
        ),
    }


def status_payload() -> dict[str, Any]:
    ram = _ram()
    reg = load_registry()
    return {
        "ram_gb": round(ram, 1),
        "top3": plan_top3(ram),
        "installed": list_installed(),
        "active": reg.get("active"),
        "should_prompt_refresh": should_prompt_refresh(),
        "discovery": get_discovery(),
        "check_interval_days": 42,
        "port_pool": list(localllm.PORT_POOL),
    }
