"""Multi-option local models: hardware top-3 picks, 6-week refresh,
HF/Ollama discovery, add/remove.

Complements ``localllm.py`` (llama-server install pipeline). Ornith is
one candidate among several — not the only easy-install path.
"""

from __future__ import annotations

import json
import logging
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
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


# ── MLX (Apple silicon) ─────────────────────────────────────────────
# Apple's array framework runs quantised models directly against
# unified memory + Metal, which on an M-series mac is the native path:
# no GGUF conversion, no separate weights copy for the GPU, and the
# whole of RAM is addressable by the model. `mlx_lm.server` speaks the
# OpenAI-compatible API the llamacpp provider already talks, so it
# slots in as a third backend rather than a new transport.
#
# Gated on darwin + arm64: MLX is a no-op on Intel macs and doesn't
# exist elsewhere, so the backend stays invisible on those machines.

MLX_PORT_POOL = list(range(8888, 8896))


def mlx_supported() -> bool:
    """Apple silicon mac — the only place MLX runs."""
    return sys.platform == "darwin" and platform.machine() == "arm64"


def mlx_binary() -> str | None:
    """`mlx_lm.server` on PATH, if the user has mlx-lm installed."""
    for name in ("mlx_lm.server", "mlx_lm"):
        p = shutil.which(name)
        if p:
            return p
    return None


def mlx_installed() -> bool:
    return mlx_supported() and mlx_binary() is not None


def mlx_status() -> dict[str, Any]:
    """What the Settings panel needs to decide what to show."""
    if not mlx_supported():
        return {
            "supported": False,
            "installed": False,
            "reason": (
                "MLX needs an Apple-silicon Mac"
                if sys.platform == "darwin"
                else "MLX is macOS-only"
            ),
        }
    binp = mlx_binary()
    version = None
    if binp:
        try:
            out = subprocess.run(
                [sys.executable, "-c",
                 "import mlx_lm, sys; sys.stdout.write(mlx_lm.__version__)"],
                capture_output=True, text=True, timeout=10,
            )
            version = (out.stdout or "").strip() or None
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "supported": True,
        "installed": binp is not None,
        "binary": binp,
        "version": version,
        "install_hint": "pip install mlx-lm  (or: uv tool install mlx-lm)",
        "port_pool": list(MLX_PORT_POOL),
    }


def mlx_search(query: str = "", *, limit: int = 20, curated: bool = False) -> list[dict[str, Any]]:
    """Live search for MLX-format models on Hugging Face.

    MLX weights are published under the `mlx` library tag — mostly by
    `mlx-community`, which converts upstream releases promptly. Same
    gating story as GGUF search: `curated` for recommendations, ungated
    for the paste-any-id path.
    """
    q = urllib.parse.quote(query.strip())
    want = limit * 3 if curated else limit
    path = (
        f"models?filter=mlx&sort=downloads&direction=-1&limit={min(want, 100)}"
        + (f"&search={q}" if q else "")
    )
    rows = _hf_get(path)
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for m in rows:
        if not isinstance(m, dict):
            continue
        rid = str(m.get("id") or m.get("modelId") or "")
        if not rid:
            continue
        author = rid.split("/", 1)[0]
        tags = [str(t) for t in (m.get("tags") or [])]
        off_task = looks_off_task(rid, tags)
        if curated and off_task:
            continue
        out.append({
            "repo": rid,
            "author": author,
            "backend": "mlx",
            "downloads": m.get("downloads"),
            "likes": m.get("likes"),
            "trending": m.get("trendingScore"),
            "last_modified": m.get("lastModified"),
            "trusted": author in TRUSTED_PUBLISHERS,
            "off_task": off_task,
        })
        if len(out) >= limit:
            break
    return out


def resolve_mlx_candidate(repo: str, *, ram: float | None = None) -> dict[str, Any]:
    """Turn any HF MLX repo id into an installable candidate.

    MLX repos ship safetensors shards rather than one GGUF per quant —
    the quantisation is baked into the repo (`…-4bit`, `…-8bit`), so
    sizing reads the total weight bytes instead of choosing a file.
    """
    repo = (repo or "").strip().strip("/")
    if not re.fullmatch(r"[\w.\-]+/[\w.\-]+", repo):
        return {"ok": False, "error": (
            f"{repo!r} isn't a Hugging Face repo id — expected "
            "`owner/name`, e.g. `mlx-community/Qwen3.6-27B-4bit`."
        )}
    if not mlx_supported():
        return {"ok": False, "error": mlx_status()["reason"]}
    ram = ram if ram is not None else _ram()
    tree = _hf_get(f"models/{repo}/tree/main?recursive=true")
    if not isinstance(tree, list):
        return {"ok": False, "error": (
            f"couldn't read {repo} from Hugging Face — check the id and "
            "your connection."
        )}
    total = 0
    has_weights = False
    for item in tree:
        if not isinstance(item, dict) or item.get("type") != "file":
            continue
        path = str(item.get("path") or "")
        if not path.endswith((".safetensors", ".npz")):
            continue
        has_weights = True
        size = item.get("size")
        if not isinstance(size, int) or size <= 0:
            lfs = item.get("lfs") or {}
            size = lfs.get("size") if isinstance(lfs, dict) else 0
        total += size if isinstance(size, int) else 0
    if not has_weights:
        return {"ok": False, "error": (
            f"{repo} has no safetensors weights — is it an MLX "
            "conversion? Try `mlx-community/<model>-4bit`."
        )}
    weights_gb = round(total / 1e9, 2)
    info = hf_model_info(repo)
    quant = "4bit" if "4bit" in repo.lower() else "8bit" if "8bit" in repo.lower() else "bf16"
    return {
        "ok": True,
        "id": "mlx:" + repo.lower(),
        "label": repo.rsplit("/", 1)[-1],
        "backend": "mlx",
        "family": "custom",
        "repo": repo,
        "quant": quant,
        "weights_gb": weights_gb,
        **_ram_envelope(weights_gb),
        "est_gb": round(weights_gb + max(2.0, ram * 0.15), 1),
        "ctx": 32768 if ram < 32 else 65536,
        "installed": is_installed("mlx:" + repo.lower()),
        "fits": weights_gb <= max(2.0, ram * 0.55),
        "downloads": (info or {}).get("downloads"),
        "likes": (info or {}).get("likes"),
        "trusted": repo.split("/", 1)[0] in TRUSTED_PUBLISHERS,
        "blurb": f"MLX (Apple silicon) install from {repo}.",
    }


def allocate_mlx_port(reg: dict[str, Any] | None = None) -> int:
    reg = reg if reg is not None else load_registry()
    used = {
        int(m["port"]) for m in (reg.get("installed") or {}).values()
        if isinstance(m, dict) and m.get("port")
    }
    for p in MLX_PORT_POOL:
        if p not in used:
            return p
    return MLX_PORT_POOL[0]


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
    """Higher = better fit for THIS MACHINE. Hardware only.

    Deliberately carries no per-model preference. An earlier version
    added a flat +8 to the ``agent`` family, which pinned Ornith to the
    top of every list on any machine with ≥24 GB regardless of what else
    was available — the catalog's own opinion masquerading as a fit
    score. Model desirability now comes from live Hugging Face signals
    (`_popularity_bonus`), so a stale catalog can't outrank a better
    current model.
    """
    mn = float(entry.get("min_ram_gb") or 0)
    ideal = float(entry.get("ideal_ram_gb") or mn)
    if ram + 1.0 < mn:
        return -1.0
    # Prefer models near ideal RAM (not too small wastefully).
    dist = abs(ram - ideal)
    fit = 100.0 - dist * 2.0
    # Backend fit is a property of the machine, not the model: the
    # managed llama-server is one less moving part when RAM is ample,
    # and Ollama's on-demand paging helps when it isn't.
    if entry.get("backend") == "llamacpp" and ram >= 16:
        fit += 3
    if entry.get("backend") == "ollama" and ram < 16:
        fit += 4
    if entry.get("backend") == "mlx" and mlx_supported():
        fit += 5  # unified memory + Metal: the native path on Apple silicon
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


def ollama_available() -> bool:
    """Ollama is installed AND its daemon answers on the local port."""
    if shutil.which("ollama") is None:
        return False
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/version", method="GET")
        with urllib.request.urlopen(req, timeout=2):
            return True
    except Exception:  # noqa: BLE001
        # Binary present but daemon down — still installable (the pull
        # starts it), so treat as available.
        return True


def resolve_ollama_candidate(tag: str) -> dict[str, Any]:
    """Turn any Ollama tag into an installable candidate.

    Ollama resolves and sizes tags itself at pull time, so this only
    validates the shape and reports whether it is already local. The
    equivalent of the paste-any-GGUF path, for people who already run
    Ollama and would rather not have a second weights store.
    """
    tag = (tag or "").strip()
    if not re.fullmatch(r"[\w.\-]+(?:/[\w.\-]+)?(?::[\w.\-]+)?", tag):
        return {"ok": False, "error": (
            f"{tag!r} isn't an Ollama tag — expected `model` or "
            "`model:tag`, e.g. `qwen3.6:27b`."
        )}
    if shutil.which("ollama") is None:
        return {"ok": False, "error": (
            "Ollama isn't installed. Get it from https://ollama.com, "
            "or install a GGUF via llama.cpp instead."
        )}
    have = ollama_list_tags()
    cid = "ollama:" + tag.lower()
    return {
        "ok": True,
        "id": cid,
        "label": tag,
        "backend": "ollama",
        "family": "custom",
        "ollama_tag": tag,
        "installed": tag in have or cid in (load_registry().get("installed") or {}),
        "fits": True,   # ollama pages weights on demand
        "blurb": f"Pull `{tag}` with Ollama.",
    }


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


# ── Live Hugging Face search ────────────────────────────────────────
# The catalog above is a hand-maintained starting point and goes stale
# between releases — it shipped Qwen2.5 / Llama 3.2 long after those
# were current. Everything below queries the HF API at request time so
# the options a user sees track what actually exists today. The catalog
# survives only as a curated floor for offline machines.

_HF_API = "https://huggingface.co/api"

# GGUF publishers that repackage upstream weights faithfully. Used to
# rank the *recommendation* path only — free-text search is ungated, and
# `resolve_repo_candidate` installs any repo id the user pastes.
TRUSTED_PUBLISHERS = frozenset({
    "unsloth", "bartowski", "ggml-org", "lmstudio-community",
    "Qwen", "google", "mistralai", "meta-llama", "microsoft",
    "deepreinforce-ai", "nvidia", "ibm-granite", "allenai",
    "mlx-community",
})

# Trending GGUF lists are dominated by roleplay/"uncensored" merges.
# They're legitimate downloads — search still returns them — but they
# are poor defaults for an agent that has to emit reliable tool JSON,
# so they don't get recommended unsolicited.
_OFF_TASK_RE = re.compile(
    r"uncensored|abliterat|heretic|roleplay|\brp\b|erp|waifu|nsfw|"
    r"horror|fable-fusion|defiant|aggressive|lewd|smut",
    re.I,
)

# Quantisation tokens, best → smallest. Order drives quant preference
# when a repo offers several.
_QUANT_ORDER = [
    "F32", "BF16", "F16",
    "Q8_0", "Q6_K_L", "Q6_K", "Q5_K_M", "Q5_K_S", "Q5_0",
    "MXFP4_MOE", "Q4_K_L", "Q4_K_M", "Q4_K_S", "Q4_0",
    "IQ4_XS", "IQ4_NL", "Q3_K_L", "Q3_K_M", "Q3_K_S",
    "IQ3_M", "IQ3_S", "IQ3_XXS", "Q2_K",
    "IQ2_M", "IQ2_S", "IQ2_XXS", "IQ1_M", "IQ1_S",
]
_QUANT_RANK = {q: i for i, q in enumerate(_QUANT_ORDER)}
_QUANT_RE = re.compile(
    r"(?:^|[.\-_])(" + "|".join(re.escape(q) for q in _QUANT_ORDER) + r")(?:[.\-_]|$)",
    re.I,
)
# `model-00001-of-00003.gguf` — a split (sharded) GGUF.
_SHARD_RE = re.compile(r"^(?P<base>.+?)-(?P<idx>\d{5})-of-(?P<total>\d{5})\.gguf$", re.I)

# Sidecar GGUFs that are NOT the model: multimodal projectors, vision
# towers, LoRA adapters, draft models. They sit in the same repo, are
# small, and often carry a high-precision tag (`mmproj-F32.gguf`) — so
# a naive "best quant that fits" pick lands on one of these and serves
# a projector as though it were the language model.
_AUX_GGUF_RE = re.compile(
    r"(?:^|[/\-_])(mmproj|clip|vision|projector|adapter|lora|draft)",
    re.I,
)


def _hf_get(path: str, timeout: float = 20.0) -> Any:
    """GET a public HF API path. Returns parsed JSON, or None on any
    network/parse failure — every caller degrades to catalog-only."""
    url = f"{_HF_API}/{path.lstrip('/')}"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "switchbay-local-models/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except Exception as e:  # noqa: BLE001
        log.debug("hf GET %s: %s", url, e)
        return None


def parse_quant(filename: str) -> str | None:
    """Pull the quantisation token out of a GGUF filename."""
    m = _QUANT_RE.search(filename)
    if not m:
        return None
    tok = m.group(1).upper()
    # Normalise to the catalog spelling (the regex is case-insensitive).
    for q in _QUANT_ORDER:
        if q.upper() == tok:
            return q
    return tok


def gguf_files(repo: str) -> list[dict[str, Any]] | None:
    """Every GGUF in a repo with its REAL size, read from the HF tree.

    Returns one row per logical model — split GGUFs (`…-00001-of-00003`)
    collapse into a single row whose ``parts`` lists every shard and
    whose ``size_gb`` is the total. None on network failure.

    This is what lets an arbitrary repo id be installed without the
    hardcoded quant→size table the catalog used to need.
    """
    tree = _hf_get(f"models/{repo}/tree/main?recursive=true")
    if not isinstance(tree, list):
        return None

    shards: dict[str, dict[str, Any]] = {}
    singles: list[dict[str, Any]] = []
    for item in tree:
        if not isinstance(item, dict) or item.get("type") != "file":
            continue
        path = str(item.get("path") or "")
        if not path.lower().endswith(".gguf"):
            continue
        size = item.get("size")
        if not isinstance(size, int) or size <= 0:
            lfs = item.get("lfs") or {}
            size = lfs.get("size") if isinstance(lfs, dict) else None
        if not isinstance(size, int) or size <= 0:
            continue
        name = path.rsplit("/", 1)[-1]
        if _AUX_GGUF_RE.search(name):
            continue  # projector/adapter sidecar, not the model
        m = _SHARD_RE.match(name)
        if m:
            key = f"{path[: len(path) - len(name)]}{m.group('base')}"
            row = shards.setdefault(key, {
                "file": f"{m.group('base')}-00001-of-{m.group('total')}.gguf",
                "path": key,
                "bytes": 0,
                "parts": [],
                "total_parts": int(m.group("total")),
            })
            row["bytes"] += size
            row["parts"].append(path)
        else:
            singles.append({
                "file": name, "path": path, "bytes": size, "parts": [path],
                "total_parts": 1,
            })

    out: list[dict[str, Any]] = []
    for row in [*singles, *shards.values()]:
        row["parts"] = sorted(row["parts"])
        if len(row["parts"]) != row["total_parts"]:
            continue  # incomplete shard set — unusable
        quant = parse_quant(row["file"])
        out.append({
            "file": row["file"],
            "parts": row["parts"],
            "quant": quant or "unknown",
            "size_gb": round(row["bytes"] / 1e9, 2),
            "rank": _QUANT_RANK.get(quant or "", len(_QUANT_ORDER)),
        })
    out.sort(key=lambda r: r["rank"])
    return out


def pick_gguf_for_ram(
    files: list[dict[str, Any]], ram: float, quant: str | None = None,
) -> dict[str, Any] | None:
    """Best-quality GGUF whose weights fit the RAM budget.

    Same 45%-of-RAM weight budget the catalog path uses, but measured
    against real file sizes rather than a table that drifts.
    """
    usable = [f for f in files if f.get("size_gb")]
    if not usable:
        return None
    if quant:
        want = quant.upper()
        exact = [f for f in usable if (f.get("quant") or "").upper() == want]
        if exact:
            return min(exact, key=lambda f: f["rank"])
        return None
    budget = max(2.0, ram * 0.45)
    fits = [f for f in usable if f["size_gb"] <= budget]
    if fits:
        return min(fits, key=lambda f: f["rank"])
    return min(usable, key=lambda f: f["size_gb"])


def _ram_envelope(weights_gb: float) -> dict[str, float]:
    """RAM floor/ideal implied by a model's real weight size.

    The install planner budgets weights at ~45% of RAM (the rest goes to
    KV cache and compute buffers), so a model needing W GB of weights
    wants at least W/0.45 GB of machine. The `ideal` is where it sits
    comfortably rather than at the edge.
    """
    return {
        "min_ram_gb": round(weights_gb / 0.45, 1),
        "ideal_ram_gb": round(weights_gb / 0.30, 1),
    }


def _popularity_bonus(info: dict[str, Any]) -> float:
    """Rank contribution from live HF signals. Log-scaled so a
    million-download repo doesn't swamp the hardware-fit score."""
    import math

    dl = info.get("downloads")
    likes = info.get("likes")
    bonus = 0.0
    if isinstance(dl, int) and dl > 0:
        bonus += min(12.0, math.log10(dl) * 2.4)
    if isinstance(likes, int) and likes > 0:
        bonus += min(6.0, math.log10(likes) * 2.0)
    return bonus


def looks_off_task(repo_id: str, tags: list[str] | None = None) -> bool:
    """True for roleplay / uncensored finetunes — fine to install on
    request, wrong to recommend as an agent model."""
    if _OFF_TASK_RE.search(repo_id):
        return True
    for t in tags or []:
        if _OFF_TASK_RE.search(str(t)):
            return True
    return False


def hf_search_gguf(
    query: str = "",
    *,
    sort: str = "downloads",
    limit: int = 20,
    curated: bool = False,
) -> list[dict[str, Any]]:
    """Live GGUF search against the HF model index.

    `sort` is "downloads", "trendingScore", "likes" or "lastModified".
    `curated=True` applies the recommendation gate (trusted publishers,
    no off-task finetunes); the UI's free-text search leaves it False so
    the user can find and install anything.
    """
    sort = sort if sort in ("downloads", "trendingScore", "likes", "lastModified") else "downloads"
    q = urllib.parse.quote(query.strip())
    # Over-fetch when gating, since the gate drops a lot.
    want = limit * 4 if curated else limit
    path = (
        f"models?filter=gguf&sort={sort}&direction=-1&limit={min(want, 100)}"
        + (f"&search={q}" if q else "")
    )
    rows = _hf_get(path)
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for m in rows:
        if not isinstance(m, dict):
            continue
        rid = str(m.get("id") or m.get("modelId") or "")
        if not rid:
            continue
        author = rid.split("/", 1)[0]
        tags = [str(t) for t in (m.get("tags") or [])]
        off_task = looks_off_task(rid, tags)
        if curated and (off_task or author not in TRUSTED_PUBLISHERS):
            continue
        out.append({
            "repo": rid,
            "author": author,
            "downloads": m.get("downloads"),
            "likes": m.get("likes"),
            "trending": m.get("trendingScore"),
            "last_modified": m.get("lastModified"),
            "trusted": author in TRUSTED_PUBLISHERS,
            "off_task": off_task,
        })
        if len(out) >= limit:
            break
    return out


def resolve_repo_candidate(
    repo: str, *, ram: float | None = None, quant: str | None = None,
) -> dict[str, Any]:
    """Turn any HF GGUF repo id into an installable candidate.

    This is the free-text install path: the user pastes
    `unsloth/Qwen3.6-27B-GGUF` and we read the repo's real file list to
    choose a quant that fits, rather than requiring a catalog entry.
    Returns {ok: False, error} rather than raising.
    """
    repo = (repo or "").strip().strip("/")
    if not re.fullmatch(r"[\w.\-]+/[\w.\-]+", repo):
        return {"ok": False, "error": (
            f"{repo!r} isn't a Hugging Face repo id — expected "
            "`owner/name`, e.g. `unsloth/Qwen3.6-27B-GGUF`."
        )}
    ram = ram if ram is not None else _ram()
    info = hf_model_info(repo)
    files = gguf_files(repo)
    if files is None:
        return {"ok": False, "error": (
            f"couldn't read {repo} from Hugging Face — check the id and "
            "your connection (private/gated repos aren't supported)."
        )}
    if not files:
        return {"ok": False, "error": (
            f"{repo} has no .gguf files. For llama.cpp you need a GGUF "
            "build — try appending `-GGUF` to the model name, or search "
            "for a community conversion."
        )}
    pick = pick_gguf_for_ram(files, ram, quant)
    if not pick:
        offered = sorted({f["quant"] for f in files})
        return {"ok": False, "error": (
            f"{repo} has no {quant!r} build. Available: {', '.join(offered)}"
        )}
    cid = "hf:" + repo.lower()
    est = round(pick["size_gb"] + max(2.0, ram * 0.15), 1)
    return {
        "ok": True,
        "id": cid,
        "label": repo.rsplit("/", 1)[-1].replace("-GGUF", "").replace("_GGUF", ""),
        "backend": "llamacpp",
        "family": "custom",
        "repo": repo,
        # Derived from real weight bytes rather than a catalog guess, so
        # `_score` can rank a live hit against a catalog entry fairly.
        **_ram_envelope(pick["size_gb"]),
        "quant": pick["quant"],
        "file": pick["file"],
        "parts": pick["parts"],
        "weights_gb": pick["size_gb"],
        "est_gb": est,
        "ctx": 32768 if ram < 32 else 65536,
        "installed": is_installed(cid),
        "fits": pick["size_gb"] <= max(2.0, ram * 0.45),
        "downloads": (info or {}).get("downloads"),
        "likes": (info or {}).get("likes"),
        "trusted": repo.split("/", 1)[0] in TRUSTED_PUBLISHERS,
        "off_task": looks_off_task(repo, [str(t) for t in (info or {}).get("tags") or []]),
        "quants_available": sorted({f["quant"] for f in files}),
        "blurb": f"Custom install from Hugging Face repo {repo}.",
    }


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

    if backend == "mlx":
        repo = meta.get("repo") or entry.get("repo")
        if not repo:
            return {"ok": False, "error": f"no MLX repo recorded for {cid!r}",
                    "id": cid}
        port = int(meta.get("port") or allocate_mlx_port(reg))
        alias = str(meta.get("alias") or cid.split(":", 1)[-1].replace("/", "_")[:24])
        cfg = {
            "model": repo,
            "model_label": meta.get("label") or str(repo).rsplit("/", 1)[-1],
            "quant": meta.get("quant"),
            "repo": repo,
            "backend": "mlx",
            "ctx": int(meta.get("ctx") or 32768),
            "port": port,
            "alias": alias,
            "candidate_id": cid,
            "installed_at": meta.get("installed_at") or time.time(),
        }
        localllm.save_config(cfg)
        inst2 = dict(load_registry().get("installed") or {})
        if cid in inst2:
            reg2 = load_registry()
            inst2[cid] = {**inst2[cid], "port": port, "alias": alias}
            reg2["installed"] = inst2
            reg2["active"] = cid
            save_registry(reg2)
        return {
            "ok": True, "id": cid, "backend": "mlx", "active": cid,
            "cfg": cfg, "port": port,
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

    # ── Live Hugging Face frontier ──────────────────────────────────
    # The catalog is a floor, not the answer. Query HF for what is
    # actually current, resolve each hit's real GGUF sizes against this
    # machine's RAM, and rank by hardware fit + live popularity. This is
    # what stops a model released after the last catalog edit from being
    # invisible.
    seen_repos = {
        str((catalog_by_id(str(cid)) or {}).get("repo") or "").lower()
        for cid in installed
    }
    seen_repos |= {str(s.get("repo") or "").lower() for s in suggestions}

    live: list[dict[str, Any]] = []
    for sort in ("downloads", "trendingScore"):
        live.extend(hf_search_gguf(sort=sort, limit=10, curated=True))
    if mlx_supported():
        live.extend(mlx_search(limit=6, curated=True))

    considered: set[str] = set()
    for hit in live:
        repo = str(hit.get("repo") or "")
        key = repo.lower()
        if not repo or key in considered or key in seen_repos:
            continue
        considered.add(key)
        if hit.get("backend") == "mlx":
            cand = resolve_mlx_candidate(repo, ram=ram)
        else:
            cand = resolve_repo_candidate(repo, ram=ram)
        if not cand.get("ok") or cand.get("installed"):
            continue
        if not cand.get("fits"):
            continue  # would only run at punishing quantisation
        bits = [cand.get("blurb") or ""]
        dl = hit.get("downloads")
        if isinstance(dl, int) and dl > 0:
            bits.append(f"~{dl:,} HF downloads")
        lk = hit.get("likes")
        if isinstance(lk, int) and lk > 0:
            bits.append(f"{lk} likes")
        if hit.get("last_modified"):
            bits.append(f"updated {str(hit['last_modified'])[:10]}")
        bits.append(f"{cand['quant']}, ~{cand['weights_gb']} GB weights")
        suggestions.append({
            **cand,
            "action": "add",
            "source": "huggingface",
            "score": round(_score(cand, ram) + _popularity_bonus(hit), 1),
            "summary": " · ".join(b for b in bits if b)[:220],
        })

    # Live hits outrank stale catalog entries of equal hardware fit.
    suggestions.sort(key=lambda s: -float(s.get("score") or 0))

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
        # Which free-text install paths the Settings panel should offer
        # on THIS machine. llama.cpp/GGUF is always offered (the daemon
        # can brew-install llama-server); the other two depend on what's
        # present.
        "backends": {
            "llamacpp": {"available": True, "label": "llama.cpp (GGUF)"},
            "ollama": {
                "available": ollama_available(),
                "label": "Ollama",
                "hint": "https://ollama.com",
            },
            "mlx": {**mlx_status(), "label": "MLX (Apple silicon)"},
        },
    }
