"""Compare Grok Build harness vs Pi + xAI API vs Pi + MLX on the same jobs.

    PYTHONPATH=src uv run --no-sync python -m switchbay.kernel.probe \\
        --workspace <ws> --job curate --job deck --arm pi-mlx

Does not nest Pi under `grok`. Arms:
  grok-build  → full Grok Build CLI (headless -p)
  pi-xai      → Pi RPC, --provider xai, XAI_API_KEY (HTTP model)
  pi-mlx      → Pi RPC, --provider mlx, mlx_lm.server (local Qwen)

Writes a JSON report next to the workspace (or --out).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from .harness import NodeRequest, pick_harness, run_node
from .packages import CURATOR_ID, SLIDESHOW_ID, get_package

_mlx_child: asyncio.subprocess.Process | None = None


async def ensure_mlx() -> dict[str, Any]:
    """Reuse the managed mlx_lm.server if it is up; otherwise spawn one.

    Does not stop an already-running daemon slot. Probe-spawned children
    are reaped in ``main``.
    """
    global _mlx_child
    from .. import localllm
    cfg = localllm.load_config() or {}
    port = int(cfg.get("port") or 8888)
    info: dict[str, Any] = {
        "port": port,
        "backend": cfg.get("backend"),
        "repo": cfg.get("repo") or cfg.get("model"),
        "spawned": False,
    }
    if await localllm.server_healthy(port):
        info["ok"] = True
        return info
    if str(cfg.get("backend") or "") != "mlx":
        info["ok"] = False
        info["error"] = "localllm backend is not mlx — pick the small Qwen in Settings"
        return info
    binp = localllm.binary_for(cfg)
    if not binp:
        info["ok"] = False
        info["error"] = "mlx_lm.server not on PATH"
        return info
    argv = localllm.server_args(binp, cfg)
    logp = localllm.server_log_path_for(str(cfg.get("candidate_id") or "probe-mlx"))
    logp.parent.mkdir(parents=True, exist_ok=True)
    logf = logp.open("a", encoding="utf-8")
    logf.write(f"# probe mlx start: {' '.join(argv)}\n")
    logf.flush()
    _mlx_child = await asyncio.create_subprocess_exec(
        *argv,
        stdout=logf,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    info["spawned"] = True
    info["pid"] = _mlx_child.pid
    for _ in range(90):
        await asyncio.sleep(1)
        if await localllm.server_healthy(port):
            info["ok"] = True
            return info
        if _mlx_child.returncode is not None:
            info["ok"] = False
            info["error"] = f"mlx_lm.server exited { _mlx_child.returncode}"
            return info
    info["ok"] = False
    info["error"] = "mlx_lm.server did not become healthy in 90s"
    return info

JOBS: dict[str, dict[str, str]] = {
    "curate": {
        "package": CURATOR_ID,
        "user": (
            "Run one bounded CURATE wave. Call ce_wave_prime first. "
            "Report the pick-mode JSON. If the mode is sweep, run mechanical "
            "ce_sweep verbs only. Do not delete pages. Prefer not to "
            "ce_wiki_commit unless you produced a real accepted page."
        ),
    },
    "deck": {
        "package": SLIDESHOW_ID,
        "user": (
            "Using ce_query (verb=introspect, then sql or cypher), find the "
            "main vault-backed themes in this workspace. Read source excerpts "
            "with read_source. Call create_slideshow with title "
            "'Vault briefing', 6–8 slides (title, bullets or cards, close), "
            "and cite vault/wiki paths. Do not invent numbers. If retrieval "
            "is empty, say so."
        ),
    },
}

ARMS: dict[str, dict[str, str | None]] = {
    "grok-build": {"harness": "grok-build", "provider": "grok-build", "model": "grok-4.6"},
    "pi-xai": {"harness": "pi", "provider": "xai", "model": "grok-4.5"},
    "pi-mlx": {"harness": "pi", "provider": "mlx", "model": "default_model"},
}


def _slideshows(workspace: Path) -> list[str]:
    root = workspace / "slideshows"
    if not root.is_dir():
        return []
    return sorted(str(p.relative_to(workspace)) for p in root.glob("*/index.html"))


async def run_arm(
    *,
    job: str,
    arm: str,
    workspace: Path,
    timeout_sec: float,
) -> dict[str, Any]:
    spec = JOBS[job]
    arm_spec = ARMS[arm]
    pkg = get_package(spec["package"])
    assert pkg is not None
    harness = str(arm_spec["harness"] or "")
    provider = str(arm_spec["provider"] or "")
    model = arm_spec["model"]
    mapped = pick_harness(pkg.id, provider, pi_available=(harness == "pi"))
    extra: dict[str, Any] = {"timeout_sec": timeout_sec}
    req = NodeRequest(
        package_id=pkg.id,
        system=pkg.system,
        user=spec["user"],
        tools=list(pkg.tools),
        provider_id=provider,
        model=str(model) if model else None,
        workspace=workspace,
        extra=extra,
    )
    before_slides = set(_slideshows(workspace))
    t0 = time.time()
    print(f"probe start job={job} arm={arm} harness={harness}", flush=True)
    result = await run_node(req, harness=harness)
    print(f"probe end job={job} arm={arm} ok={result.error is None} s={time.time()-t0:.1f}", flush=True)
    elapsed = time.time() - t0
    after_slides = set(_slideshows(workspace))
    created = sorted(after_slides - before_slides)
    text = result.text or ""
    tools = list(result.tool_trace or [])
    ok = result.error is None
    if job == "deck":
        # Success is an artifact or an honest empty-retrieval, not
        # merely "the harness did not crash" (earlier arms' decks
        # must not count).
        ok = bool(
            result.error is None
            and (created or "create_slideshow" in tools
                 or "empty" in text.lower() or "ce_query" in tools)
        )
    elif job == "curate":
        ok = bool(result.error is None and (tools or "ce_wave_prime" in text.lower()))
    return {
        "job": job,
        "arm": arm,
        "harness": result.harness or harness,
        "pick_harness": mapped,
        "provider": provider,
        "model": model,
        "ok": ok,
        "error": result.error,
        "elapsed_s": round(elapsed, 2),
        "tool_trace": tools,
        "text_excerpt": text[:1500],
        "text_chars": len(text),
        "slideshows_created": created,
        "nested_pi_under_grok": harness == "pi" and provider == "grok-build",
    }


async def run_probe(
    *,
    workspace: Path,
    jobs: list[str],
    arms: list[str],
    timeout_sec: float,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    mlx_info: dict[str, Any] | None = None
    if "pi-mlx" in arms:
        mlx_info = await ensure_mlx()
        if not mlx_info.get("ok"):
            return {
                "workspace": str(workspace),
                "jobs": jobs,
                "arms": arms,
                "mlx": mlx_info,
                "results": [{
                    "job": job, "arm": "pi-mlx", "ok": False,
                    "error": mlx_info.get("error"),
                } for job in jobs],
            }
    for job in jobs:
        for arm in arms:
            rows.append(await run_arm(
                job=job, arm=arm, workspace=workspace, timeout_sec=timeout_sec,
            ))
    return {
        "workspace": str(workspace),
        "jobs": jobs,
        "arms": arms,
        "note": (
            "grok-build = full CLI harness; pi-xai = Pi harness + xAI HTTP; "
            "pi-mlx = Pi harness + mlx_lm.server. Not Pi wrapping grok."
        ),
        "results": rows,
        **({"mlx": mlx_info} if mlx_info else {}),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="switchbay.kernel.probe")
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--job", action="append", choices=sorted(JOBS), dest="jobs")
    p.add_argument("--arm", action="append", choices=sorted(ARMS), dest="arms")
    p.add_argument("--timeout", type=float, default=600.0)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)
    ws = args.workspace.expanduser().resolve()
    if not ws.is_dir():
        print(json.dumps({"ok": False, "error": f"workspace not a directory: {ws}"}))
        return 2
    jobs = args.jobs or ["curate", "deck"]
    arms = args.arms or ["grok-build", "pi-xai"]
    try:
        report = asyncio.run(run_probe(
            workspace=ws, jobs=jobs, arms=arms, timeout_sec=float(args.timeout),
        ))
    finally:
        if _mlx_child is not None and _mlx_child.returncode is None:
            try:
                _mlx_child.terminate()
            except ProcessLookupError:
                pass
    text = json.dumps(report, indent=2, default=str)
    out = args.out or (ws / "probe-report.json")
    out.write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"wrote {out}", file=__import__("sys").stderr)
    fails = [r for r in report["results"] if not r.get("ok")]
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
