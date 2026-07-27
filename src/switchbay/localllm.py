"""Local agent model via llama.cpp — the one-click Ornith installer.

Ruling (2026-07-05, user): switchbay ships an installer that sets up
**Ornith 1.0** (deepreinforce-ai, GGUF builds) behind a managed
`llama-server`, with quantization, KV-cache quantization, and context
length **auto-planned from the machine's RAM** — and the model ladder's
lower rungs pointed at it so cheap chores stop burning expensive
provider tokens. Under 16 GB we refuse and suggest alternatives.

Plan table (anchored on the user's measurements: 9B Q8_0 @ 131k runs
comfortably in ~30 GB on a 48 GB M3 Max; a 16 GB M4 fits Q4_K_M @ 32k):

    RAM        model  quant    ctx      est. use
    <16 GB     —      refuse (suggest Ollama + a ~3B model)
    16–23 GB   9B     Q4_K_M   32k      ~11 GB
    24–31 GB   9B     Q5_K_M   65k      ~17 GB
    32–47 GB   9B     Q6_K     65k      ~18 GB
    48–63 GB   9B     Q8_0     131k     ~30 GB   (user-verified)
    64–95 GB   35B    Q5_K_M   65k      ~35 GB
    ≥96 GB     35B    Q8_0     131k     ~57 GB

KV cache is always quantized q8_0 (with flash attention) — Ornith is
a hybrid linear/full-attention architecture, so the KV footprint is
already modest; q8_0 halves it again at negligible quality cost.
Each tier also exposes LARGER context options (64k/131k) as
explicitly experimental — the user asked that these stay testable
on smaller machines rather than hidden.

State: config in `~/.config/switchbay/localllm.json`; the GGUF in
`statedir.state_root()/models/` (machine-local — a 6-37 GB binary
must never land on a sync service). The daemon owns the llama-server
child (respawned at boot when installed).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from . import workspaces, statedir
from . import atomicio

log = logging.getLogger(__name__)

PORT = 8878
SERVER_URL = f"http://127.0.0.1:{PORT}"
# Ports reserved for managed llama-server instances (multi-active).
PORT_POOL = list(range(8878, 8888))  # up to 10 concurrent GGUF servers

_HF_BASE = "https://huggingface.co"

MODELS = {
    "9b": {
        "repo": "deepreinforce-ai/Ornith-1.0-9B-GGUF",
        "label": "Ornith 1.0 9B",
        "files": {
            "Q4_K_M": ("ornith-1.0-9b-Q4_K_M.gguf", 5.63),
            "Q5_K_M": ("ornith-1.0-9b-Q5_K_M.gguf", 6.47),
            "Q6_K": ("ornith-1.0-9b-Q6_K.gguf", 7.36),
            "Q8_0": ("ornith-1.0-9b-Q8_0.gguf", 9.53),
        },
    },
    "35b": {
        "repo": "deepreinforce-ai/Ornith-1.0-35B-GGUF",
        "label": "Ornith 1.0 35B",
        "files": {
            "Q4_K_M": ("ornith-1.0-35b-Q4_K_M.gguf", 21.17),
            "Q5_K_M": ("ornith-1.0-35b-Q5_K_M.gguf", 24.73),
            "Q6_K": ("ornith-1.0-35b-Q6_K.gguf", 28.51),
            "Q8_0": ("ornith-1.0-35b-Q8_0.gguf", 36.9),
        },
    },
}

# (min_ram_gb, model, quant, default_ctx, extra_ctx_options)
_TIERS = [
    (96, "35b", "Q8_0", 131072, []),
    (64, "35b", "Q5_K_M", 65536, [131072]),
    (48, "9b", "Q8_0", 131072, []),
    (32, "9b", "Q6_K", 65536, [131072]),
    (24, "9b", "Q5_K_M", 65536, [131072]),
    (16, "9b", "Q4_K_M", 32768, [65536, 131072]),
]


def ram_gb() -> float:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError, AttributeError):
        return 0.0


def _cache_est_gb(model: str, ctx: int) -> float:
    """Runtime overhead beyond weights (KV/state + compute buffers),
    scaled from the user's 48 GB anchor (9B Q8 @131k ≈ 30 GB total,
    weights 9.5 → ~20 GB overhead). Hybrid attention makes this close
    to linear in ctx; the 35B scales it by ~1.7."""
    base_at_131k = 20.0 if model == "9b" else 34.0
    return round(base_at_131k * ctx / 131072 + 1.0, 1)


def _est_total_gb(model: str, quant: str, ctx: int) -> float:
    return round(MODELS[model]["files"][quant][1] + _cache_est_gb(model, ctx), 1)


def plan(ram: float | None = None) -> dict[str, Any]:
    """The machine-derived install plan (or a refusal under 16 GB)."""
    ram = ram if ram is not None else ram_gb()
    if ram < 15.0:  # nominal-16GB machines report ~17.2e9/1e9
        return {
            "ok": False,
            "ram_gb": round(ram, 1),
            "reason": (
                f"This machine has ~{ram:.0f} GB RAM — under the 16 GB "
                "floor for Ornith 9B. Suggestion: run a ~3B model via "
                "Ollama instead (Settings → Providers → Ollama), or use "
                "cloud rungs only."
            ),
        }
    for min_gb, model, quant, ctx, extras in _TIERS:
        if ram >= min_gb - 1.0:  # tolerate 15.x/23.x reporting
            fname, weights_gb = MODELS[model]["files"][quant]
            ctx_options = [{
                "ctx": ctx,
                "est_gb": _est_total_gb(model, quant, ctx),
                "recommended": True,
            }] + [{
                "ctx": c,
                "est_gb": _est_total_gb(model, quant, c),
                "recommended": False,
                "experimental": True,
            } for c in extras]
            return {
                "ok": True,
                "ram_gb": round(ram, 1),
                "model": model,
                "model_label": MODELS[model]["label"],
                "repo": MODELS[model]["repo"],
                "quant": quant,
                "file": fname,
                "weights_gb": weights_gb,
                "ctx": ctx,
                "ctx_options": ctx_options,
                "kv_quant": "q8_0",
                "est_gb": _est_total_gb(model, quant, ctx),
            }
    return {"ok": False, "ram_gb": round(ram, 1), "reason": "unplannable"}


# ── Config + paths ─────────────────────────────────────────────────


def _config_path() -> Path:
    return workspaces.config_dir() / "localllm.json"


def models_dir() -> Path:
    return statedir.state_root() / "models"


def server_log_path() -> Path:
    """Where the managed llama-server's stdout/stderr is captured, so
    the user can watch it (Settings → Watch server). Truncated on each
    spawn — it reflects the CURRENT server session."""
    return statedir.state_root() / "llama-server.log"


# ── Model harness (silent for casual users, editable for power users) ─
# A small operating-rules block appended to the system prompt for the
# models listed in its `applies_to` frontmatter (default: the local
# llama.cpp model). Ornith is capable but, being smaller, loops when a
# tool errors or no-ops: it starts INTROSPECTING ("I called the wrong
# tool" → "why did I call the wrong tool" → …) and spirals instead of
# moving on. The harness is deliberately anti-introspective — it frames
# the model as an executor, forbids self-analysis, and biases hard
# toward "do something different or STOP". Measured (Session 33) to cut
# a delete-tool loop ~3x and make the model self-terminate + report
# rather than run out the turn cap. This beats reasoning-OFF, which
# threw away the model's actual capability. It lives in an editable
# Markdown file so a power user can tune it (Settings → advanced) and
# apply it to more models; it also AUTO-TUNES (harness_append_rule) and
# is periodically consolidated by a strong model once it grows large
# (see the daemon's refine path).

DEFAULT_HARNESS = """\
---
applies_to: llamacpp
---

You are an executor. Act; do not describe, rate, or explain yourself.

Each step: make ONE tool call, or give the final answer. If a call
errors or changes nothing, immediately do something different — or STOP
and answer with what you have. Never repeat a call. Do not analyze your
own tool choices and never call a tool "wrong": reason only about the
task in front of you, not about yourself.

STOP as soon as the goal is met, and answer plainly.
Write only what your sources or the task give you. Do NOT invent
specific numbers, dates, equations, definitions, or named methods — if
you are unsure of a specific, leave it out or mark it unverified rather
than guess. (This is about the content you output, not a cue to
re-examine yourself.)
For the knowledge base, use the wiki tools directly (search_wiki,
read_wiki_page, wiki_neighbors) — do not load a skill.
"""

# The judge-refine ceiling: once the harness passes this many lines the
# daemon runs a strong model to consolidate + tighten it (dedupe,
# merge, drop stale rules). Deduped appends keep day-to-day growth slow;
# this is the backstop against unbounded, unoptimized drift. Kept small
# (pi-agent minimalism) so the harness stays high-signal.
HARNESS_REFINE_LINES = 150
_HARNESS_HARD_CAP = 40_000  # absolute safety cap (chars) on any write


def harness_path() -> Path:
    return workspaces.config_dir() / "model-harness.md"


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return ({key: value}, body) from a leading `--- ... ---` block."""
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end].strip()
            body = text[end + 4:].lstrip("\n")
            for line in block.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip().lower()] = v.strip()
    return meta, body


def load_harness() -> str:
    """The full harness file (frontmatter + rules), for editing. Seeds
    DEFAULT_HARNESS on first read. Never raises."""
    p = harness_path()
    try:
        if p.is_file():
            txt = p.read_text(encoding="utf-8").strip()
            if txt:
                return txt
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(DEFAULT_HARNESS, encoding="utf-8")
    except OSError:
        pass
    return DEFAULT_HARNESS


def save_harness(text: str) -> None:
    """Persist an edited harness (power-user editor / judge refine)."""
    p = harness_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text[:_HARNESS_HARD_CAP], encoding="utf-8")


def harness_applies_to(provider_id: str) -> bool:
    """Whether the harness targets `provider_id` (its `applies_to`
    frontmatter — a space/comma list; default llamacpp)."""
    meta, _ = _split_frontmatter(load_harness())
    raw = meta.get("applies_to", "llamacpp")
    ids = {t.strip() for t in raw.replace(",", " ").split() if t.strip()}
    return provider_id in ids


def harness_body() -> str:
    """Just the rules (frontmatter stripped) — what goes in the prompt."""
    _, body = _split_frontmatter(load_harness())
    return body.strip()


def harness_line_count() -> int:
    return len(load_harness().splitlines())


def harness_append_rule(rule: str) -> bool:
    """Auto-tune: append one concise `- ...` rule, deduped. Returns True
    if added. Dedupe (on a normalized prefix) plus the daemon's judge-
    refine at HARNESS_REFINE_LINES keep it from drifting unbounded."""
    rule = " ".join(rule.split()).strip().lstrip("-").strip()
    if not rule:
        return False
    cur = load_harness()
    if rule.lower()[:60] in cur.lower():
        return False
    if len(cur) + len(rule) + 8 > _HARNESS_HARD_CAP:
        return False
    try:
        save_harness(cur.rstrip() + f"\n- {rule}\n")
        return True
    except OSError:
        return False


def load_config() -> dict[str, Any] | None:
    p = _config_path()
    if not p.is_file():
        return None
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return cfg if isinstance(cfg, dict) and cfg.get("file") else None


def save_config(cfg: dict[str, Any]) -> None:
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, cfg)


# ── Install pipeline (async; caller tracks progress via `rec`) ────


def server_binary() -> str | None:
    p = shutil.which("llama-server")
    if p:
        return p
    for cand in ("/opt/homebrew/bin/llama-server", "/usr/local/bin/llama-server"):
        if Path(cand).is_file():
            return cand
    return None


def _brew() -> str | None:
    p = shutil.which("brew")
    if p:
        return p
    for cand in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if Path(cand).is_file():
            return cand
    return None


async def ensure_llama_cpp(rec: dict[str, Any]) -> str:
    """llama-server on PATH, or install via Homebrew. Returns the
    binary path; raises RuntimeError with instructions otherwise."""
    binp = server_binary()
    if binp:
        return binp
    brew = _brew()
    if not brew:
        raise RuntimeError(
            "llama.cpp isn't installed and Homebrew wasn't found. "
            "Install Homebrew (https://brew.sh) or `llama.cpp` manually, "
            "then retry."
        )
    rec["step"] = "installing llama.cpp (brew)"
    proc = await asyncio.create_subprocess_exec(
        brew, "install", "llama.cpp",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out_b, _ = await asyncio.wait_for(proc.communicate(), 1800)
    if proc.returncode != 0:
        tail = out_b.decode(errors="replace").strip().splitlines()[-6:]
        raise RuntimeError("brew install llama.cpp failed:\n" + "\n".join(tail))
    binp = server_binary()
    if not binp:
        raise RuntimeError("brew finished but llama-server still isn't on PATH")
    return binp


async def download_gguf(
    repo: str, fname: str, expect_gb: float, rec: dict[str, Any],
) -> Path:
    """Resumable download via curl (-C -). Progress = on-disk size vs
    the known total, polled into rec['percent'] by the caller loop."""
    dest = models_dir() / fname
    if dest.is_file() and dest.stat().st_size > expect_gb * 0.97e9:
        return dest  # already downloaded
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    url = f"{_HF_BASE}/{repo}/resolve/main/{fname}"
    rec["step"] = f"downloading {fname} ({expect_gb:.1f} GB)"
    proc = await asyncio.create_subprocess_exec(
        "curl", "-L", "--fail", "-C", "-", "-o", str(part), url,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    total = expect_gb * 1e9
    while True:
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
            break
        except asyncio.TimeoutError:
            try:
                rec["percent"] = min(99, int(part.stat().st_size / total * 100))
            except OSError:
                pass
    if proc.returncode != 0:
        raise RuntimeError(
            f"download failed (curl rc={proc.returncode}); it resumes "
            "from where it stopped — click Install again"
        )
    part.rename(dest)
    rec["percent"] = 100
    return dest


# ── Managed llama-server ───────────────────────────────────────────
# Multi-active: ``app["localllm_servers"]`` maps candidate_id →
# {proc, logf, cfg, port}. Legacy single ``localllm_proc`` is kept in
# sync with the *active* server for older call sites.


def server_url_for(cfg: dict[str, Any] | None = None) -> str:
    """OpenAI-compatible base URL for the active (or given) config."""
    if cfg is None:
        cfg = load_config() or {}
    port = int(cfg.get("port") or PORT)
    return f"http://127.0.0.1:{port}"


def server_args(binp: str, cfg: dict[str, Any]) -> list[str]:
    return [
        binp,
        "-m", str(cfg["file"]),
        "--host", "127.0.0.1",
        "--port", str(cfg.get("port") or PORT),
        "-c", str(cfg.get("ctx") or 32768),
        "--flash-attn", "on",
        "--cache-type-k", cfg.get("kv_quant") or "q8_0",
        "--cache-type-v", cfg.get("kv_quant") or "q8_0",
        "--jinja",
        "--alias", str(cfg.get("alias") or "ornith"),
    ]


def _servers(app: dict) -> dict[str, dict[str, Any]]:
    return app.setdefault("localllm_servers", {})


def _slot_key(cfg: dict[str, Any]) -> str:
    return str(
        cfg.get("candidate_id")
        or cfg.get("alias")
        or cfg.get("model")
        or "default"
    )


async def _stop_slot(app: dict, key: str) -> None:
    servers = _servers(app)
    slot = servers.pop(key, None)
    if not slot:
        return
    proc = slot.get("proc")
    logf = slot.get("logf")
    if proc is not None and proc.returncode is None:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), 10)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
    if logf is not None:
        try:
            logf.close()
        except OSError:
            pass
    if app.get("localllm_proc") is proc:
        app["localllm_proc"] = None
        app["localllm_logf"] = None


async def spawn_server(app: dict, cfg: dict[str, Any]) -> None:
    """Start a managed llama-server for ``cfg``.

    If another server already owns this candidate_id, it is replaced.
    Other candidates keep running (multi-active). The active config
    (``load_config``) is what chat uses; call ``activate`` via
    local_models to retarget the ladder / config.
    """
    key = _slot_key(cfg)
    await _stop_slot(app, key)
    # Free port if another dead/stale slot holds the same port
    port = int(cfg.get("port") or PORT)
    for other_key, slot in list(_servers(app).items()):
        if int((slot.get("cfg") or {}).get("port") or 0) == port:
            await _stop_slot(app, other_key)

    binp = server_binary()
    if not binp:
        log.warning("localllm configured but llama-server not found")
        return
    logp = server_log_path_for(key)
    logp.parent.mkdir(parents=True, exist_ok=True)
    try:
        logf = logp.open("w", encoding="utf-8")
        logf.write(f"# llama-server starting: {' '.join(server_args(binp, cfg))}\n")
        logf.flush()
    except OSError:
        logf = None
    proc = await asyncio.create_subprocess_exec(
        *server_args(binp, cfg),
        stdout=(logf or asyncio.subprocess.DEVNULL),
        stderr=(asyncio.subprocess.STDOUT if logf else asyncio.subprocess.DEVNULL),
        start_new_session=True,
    )
    _servers(app)[key] = {"proc": proc, "logf": logf, "cfg": dict(cfg), "port": port}
    # Legacy mirrors: active/primary process for status helpers
    active_id = str((load_config() or {}).get("candidate_id") or "")
    if not active_id or active_id == key or key in ("default", "ornith", "ornith-9b"):
        app["localllm_proc"] = proc
        app["localllm_logf"] = logf
    log.info(
        "llama-server started key=%s pid=%d port=%s ctx=%s",
        key, proc.pid, port, cfg.get("ctx"),
    )


async def stop_server(app: dict, candidate_id: str | None = None) -> None:
    """Stop one server (by id) or all managed servers."""
    if candidate_id:
        await _stop_slot(app, candidate_id)
        return
    for key in list(_servers(app).keys()):
        await _stop_slot(app, key)
    # Legacy single-proc leftover
    proc = app.get("localllm_proc")
    if proc is not None and proc.returncode is None:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), 10)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
    app["localllm_proc"] = None


def running_servers(app: dict) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, slot in _servers(app).items():
        proc = slot.get("proc")
        cfg = slot.get("cfg") or {}
        alive = proc is not None and proc.returncode is None
        out.append({
            "id": key,
            "port": slot.get("port") or cfg.get("port"),
            "alive": alive,
            "pid": getattr(proc, "pid", None) if alive else None,
            "alias": cfg.get("alias"),
            "file": cfg.get("file"),
            "model_label": cfg.get("model_label"),
        })
    return out


def server_log_path_for(key: str = "default") -> Path:
    if key in ("default", "ornith", "ornith-9b", ""):
        return server_log_path()
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", key)[:48]
    return statedir.state_root() / f"llama-server-{safe}.log"


async def server_healthy(port: int | None = None) -> bool:
    import aiohttp
    p = int(port or (load_config() or {}).get("port") or PORT)
    try:
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(f"http://127.0.0.1:{p}/health") as resp:
                return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


_WARMUP_S = 120


async def wait_healthy(
    timeout_s: float = _WARMUP_S, port: int | None = None,
) -> bool:
    """A 30 GB model takes a while to mmap + warm — poll /health."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if await server_healthy(port):
            return True
        await asyncio.sleep(2)
    return False
