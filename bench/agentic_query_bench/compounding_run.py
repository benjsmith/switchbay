"""CE compounding study — does the CE−RAG quality gap OPEN as the wiki grows?

Design: docs/ce-compounding-study-design.md. On a COPY of a curated CE workspace
(never the shipped one), start from an empty wiki + the raw sources, and rebuild
incrementally: for each tranche k (chronological), ingest → CURATE → snapshot →
evaluate a fixed held-out query set through three arms (CE curated-wiki / modern-RAG
raw-sources / closed-book) → blind-judge → plot CE−RAG and CE−closed-book vs k.

Expensive part = N agentic CURATE sessions (`curate_launch.py`, detached `claude -p`).
Resumable + limit-recovering: checkpoint per (k, phase); a `<synthetic>`/limit hit is
retriable, never scored. The runner (`bench.reproduce`, stage `compound`) hard-gates
before the curate cost and prints the estimate.

This module orchestrates; it deliberately does NOT auto-run the curate sessions
without the reproduce.py cost gate.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def _skill_scripts() -> Path:
    """Resolve either supported global skill install, with an explicit override."""
    override = os.environ.get("CURIOSITY_ENGINE_SKILL_DIR")
    candidates = ([Path(override).expanduser()] if override else []) + [
        Path.home() / ".agents/skills/curiosity-engine",
        Path.home() / ".claude/skills/curiosity-engine",
    ]
    for skill_dir in candidates:
        scripts = skill_dir / "scripts"
        if (scripts / "setup.sh").is_file():
            return scripts
    return candidates[0] / "scripts"


SKILL_SCRIPTS = _skill_scripts()
QUERIES = ROOT / "compounding_queries.json"
_YEAR = re.compile(r"-(19|20)\d{2}-")


def order_sources(stage: Path) -> list[Path]:
    """ORIGINAL sources (prefer .pdf so CE extracts once — never the pre-made
    .extracted.md, which double-extracts), chronological by paper year."""
    srcs = sorted(stage.glob("*.pdf"))
    if not srcs:
        srcs = [p for p in sorted(stage.glob("*")) if p.is_file() and not p.name.endswith(".extracted.md")]
    def key(p: Path):
        m = _YEAR.search(p.name)
        return (int(m.group(0).strip("-")) if m else 9999, p.name)
    return sorted(srcs, key=key)


def _trust_workspace(work: Path, log=print) -> bool:
    """Register the workspace as trusted in ~/.claude.json so Claude Code honours the
    .claude/settings.json allowlist non-interactively (the CURATE precondition).
    Only ADDS a project trust entry; preserves everything else."""
    cj = Path("~/.claude.json").expanduser()
    try:
        d = json.loads(cj.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        log("[trust] ~/.claude.json unreadable — cannot trust workspace"); return False
    projs = d.setdefault("projects", {})
    entry = projs.setdefault(str(work), {})
    entry["hasTrustDialogAccepted"] = True
    tmp = cj.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8"); tmp.replace(cj)
    log(f"[trust] workspace registered trusted in ~/.claude.json")
    return True


def tranche(sources: list[Path], n: int) -> list[list[Path]]:
    per = max(1, (len(sources) + n - 1) // n)
    return [sources[i:i + per] for i in range(0, len(sources), per)][:n]


def setup_workspace(src_ws: Path, work: Path, log=print) -> Path:
    """Fresh compounding workspace, PROPERLY initialised by the skill's setup.sh
    (git-repo wiki, curator state, and the .claude/settings.json allowlist that lets
    autonomous CURATE run non-interactively). Raw sources are staged aside and fed
    tranche-by-tranche. Never touches src_ws."""
    work = Path(work)
    if work.exists():
        log(f"[setup] reusing existing {work}")
        return work
    work.mkdir(parents=True)
    # stage the raw sources OUTSIDE the workspace so setup.sh's initial scan can't
    # ingest them — they're fed tranche-by-tranche instead.
    stage = work.parent / "_source_stream"; stage.mkdir(exist_ok=True)
    for p in (src_ws / "vault").glob("*"):
        if p.is_file():
            shutil.copy2(p, stage / p.name)
    # proper init: git repo + curator state + permission allowlist (the missing piece).
    # setup.sh's default no-flag flow bootstraps a workspace at cwd; -y = non-interactive.
    r = subprocess.run(["bash", str(SKILL_SCRIPTS / "setup.sh"), "-y"],
                       cwd=work, capture_output=True, text=True, timeout=600)
    log(f"[setup] setup.sh (bootstrap at cwd) rc={r.returncode}")
    if r.returncode != 0:
        log(f"[setup] setup.sh stderr: {(r.stderr or r.stdout)[:300]}")
    # topic context for CURATE (the corpus's CLAUDE.md), if not created by setup
    s = src_ws / "CLAUDE.md"
    if s.is_file() and not (work / "CLAUDE.md").is_file():
        shutil.copy2(s, work / "CLAUDE.md")
    has_allow = (work / ".claude" / "settings.json").is_file()
    _trust_workspace(work, log=log)  # honour the allowlist non-interactively
    log(f"[setup] workspace at {work} · {len(list(stage.glob('*')))} staged sources · "
        f"permission allowlist: {'yes' if has_allow else 'MISSING'}")
    return work


def ingest_tranche(work: Path, files: list[Path], log=print) -> bool:
    """Deterministic, cheap: local_ingest the tranche's staged sources into vault."""
    stage = work.parent / "_source_stream"
    env_ok = True
    for f in files:
        src = (stage / f.name).resolve()  # absolute — cwd=work would double a relative path
        if not src.is_file():
            continue
        cmd = [sys.executable, str(SKILL_SCRIPTS / "local_ingest.py"), "--file", str(src)]
        r = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=600)
        env_ok = env_ok and (r.returncode == 0)
    log(f"[ingest] tranche of {len(files)} → returncode ok={env_ok}")
    return env_ok


def _last_json(text: str) -> dict:
    """Extract the JSON object from CLI stdout (pretty-printed, possibly multi-line
    with preceding log lines). Take the widest {...}."""
    t = text or ""
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return {}
    try:
        return json.loads(t[i:j + 1])
    except Exception:  # noqa: BLE001
        return {}


# Keywords that mean the detached session died on a subscription/credit limit
# (short log, no real work) rather than finishing — retry after a back-off.
LIMIT_KEYWORDS = ("session limit", "hit your", "synthetic",
                  "credit balance", "usage limit", "resets ")


def _curate_prompt(wave_cap: int) -> str:
    return (f"Run the CURATE loop on this workspace for AT MOST {wave_cap} wave(s), then "
            f"STOP and report. Curate the newly-ingested vault sources into wiki pages "
            f"(concepts/evidence/analyses) with dense citations and links; do not exceed "
            f"{wave_cap} waves.")


def _explore_prompt(questions: list[str]) -> str:
    """DEPTH mode: pose exploration questions and let CE natively answer each with a
    new analysis doc (no source ingestion, no page-linking/table micro-instructions —
    CE's default query→analysis behaviour, model-knowledge sections included)."""
    qs = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    return ("A user of this knowledge base asks the questions below. Answer each one "
            "using the standard CE query workflow — write a NEW analysis document in "
            "the wiki for each, as its native synthesis. Do NOT ingest new sources; "
            "this is exploration of the existing corpus.\n\n" + qs)


def curate(work: Path, wave_cap: int, patience_h: float, log=print,
           model: str = "claude-sonnet-5", prompt: str | None = None,
           label: str = "curate", expect_pages: bool = False) -> bool:
    """Launch a detached CURATE session (`curate_launch --workspace --prompt`) and wait
    until its pid exits (`curate_status --id → alive:false`). Autorecovers a
    limit/synthetic hit by re-launching after a sleep, up to patience_h.

    prompt: override the default curate prompt (DEPTH mode passes an explore prompt).
    expect_pages: success = the wiki gained pages (explore writes new analyses), vs
    the default wave-marker check (a curate wave may enrich pages without adding any)."""
    # Force --host claude: CE curation is Claude-native, and _detect_host() in
    # curate_launch checks codex/gemini BEFORE claude, so a codex binary on PATH
    # (common) shadows claude whenever CLAUDECODE isn't set (i.e. any plain shell,
    # not just inside a Claude Code session). Passing --host bypasses detection.
    launch = [sys.executable, str(SKILL_SCRIPTS / "curate_launch.py"),
              "--host", "claude", "--workspace", str(work),
              "--prompt", prompt if prompt is not None else _curate_prompt(wave_cap)]
    # Force the model via ANTHROPIC_MODEL: curate_launch hardcodes `claude -p <prompt>`
    # with no --model, so the detached session inherits the user's GLOBAL default
    # (~/.claude/settings.json) — which may be a credit-gated model (e.g. fable-5) that
    # dies on launch. This env var overrides the global default for the spawned session.
    env = {**os.environ, "ANTHROPIC_MODEL": model}
    before_pages = snapshot_state(work)["wiki_pages"]
    waited = 0.0
    while waited < patience_h * 3600:
        r = subprocess.run(launch, capture_output=True, text=True, timeout=300, env=env)
        info = _last_json(r.stdout)
        st = info.get("status"); sid = info.get("id")
        log(f"[{label}] launch status={st} id={sid} rc={r.returncode}")
        if st == "fallback-in-session":
            log(f"[{label}] no host CLI detected — cannot run detached session here"); return False
        if st != "launched" or not sid:
            log(f"[{label}] launch failed: {(r.stdout or r.stderr)[:200]}"); return False
        status = [sys.executable, str(SKILL_SCRIPTS / "curate_status.py"),
                  "--workspace", str(work), "--id", str(sid)]
        for _ in range(int(patience_h * 3600 / 30)):
            time.sleep(30)
            s = subprocess.run(status, capture_output=True, text=True, timeout=60)
            out = (s.stdout or "")
            low = out.lower()
            if "synthetic" in low or "credit balance" in low:
                log(f"[{label}] limit/synthetic in session — will re-launch after sleep"); break
            d = _last_json(out)
            if d and d.get("alive") is False:
                # Validate the session actually did work — a session-limit / synthetic /
                # credit death produces a short log with no output. Retry (wait out the
                # reset), don't accept it as done (this masked the k2/k3 no-ops).
                logf = Path(info.get("log", "")) if info.get("log") else None
                body = logf.read_text(errors="replace") if (logf and logf.is_file()) else ""
                bl = body.lower()
                limited = any(t in bl for t in LIMIT_KEYWORDS)
                after_pages = snapshot_state(work)["wiki_pages"]
                did_work = (after_pages > before_pages) if expect_pages \
                    else (re.search(r"\bwave\b|\baccept", bl) is not None)
                if limited or not did_work:
                    log(f"[{label}] session produced no output (limit={limited}, "
                        f"did_work={did_work}) — sleeping 30min before re-launch (a session "
                        f"limit resets in HOURS, not minutes — do not spin)"); break
                log(f"[{label}] session done (pages now {after_pages})")
                return True
        waited += 1800
        time.sleep(1800)  # session limits reset in hours; 30-min back-off, not 60s spin
    log(f"[{label}] patience exhausted"); return False


_CONTENT_TYPES = ("concepts", "evidence", "analyses", "entities", "facts", "sources", "figures", "tables")


def snapshot_state(work: Path) -> dict[str, Any]:
    """Count CORPUS content only — CE content-type pages + ingested sources —
    excluding the template scaffolding (todos/notes/index) and vault infra."""
    wiki = work / "wiki"
    pages = sum(len(list((wiki / t).glob("*.md"))) for t in _CONTENT_TYPES if (wiki / t).is_dir())
    srcs = len(list((work / "vault").rglob("*.extracted.md")))
    return {"wiki_pages": pages, "vault_sources": srcs}


def _snapshot(work: Path, out_dir: Path, k: int) -> Path:
    """Freeze the workspace wiki+vault(+.curator) AS-OF checkpoint k so the eval can
    query the state at each point. Excludes vault db WAL/SHM + the uv cache."""
    snap = out_dir / "wiki-snapshots" / f"k{k}"
    if snap.exists():
        shutil.rmtree(snap)
    snap.mkdir(parents=True)
    shutil.copytree(work / "wiki", snap / "wiki")
    shutil.copytree(work / "vault", snap / "vault")
    if (work / ".curator").is_dir():
        shutil.copytree(work / ".curator", snap / ".curator",
                        ignore=shutil.ignore_patterns("uv-cache", "*.db-wal", "*.db-shm"))
    return snap


def _split(items: list, n: int) -> list[list]:
    """Split items into n roughly-equal, contiguous batches (drops empty batches)."""
    n = max(1, min(n, len(items)))
    q, r = divmod(len(items), n)
    out, i = [], 0
    for b in range(n):
        size = q + (1 if b < r else 0)
        out.append(items[i:i + size]); i += size
    return [b for b in out if b]


def run(*, src_ws: Path, out_dir: Path, n_tranches: int, wave_cap: int,
        patience_h: float = 6.0, do_curate: bool = True, do_eval: bool = True,
        eval_only: bool = False, gen: str | None = None,
        judges: list[str] | None = None, curate_model: str = "claude-sonnet-5",
        repeats: int = 1, log=print) -> dict[str, Any]:
    out_dir = Path(out_dir).resolve()  # absolute so cwd=work subprocesses resolve staged paths
    src_ws = Path(src_ws).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if eval_only:
        log("[eval-only] skipping build; scoring existing wiki snapshots")
        return {"eval": _eval_stage(out_dir, log, gen=gen, judges=judges, repeats=repeats)}
    work = setup_workspace(src_ws, out_dir / "workspace", log=log)
    sources = order_sources(out_dir / "_source_stream")
    tranches = tranche(sources, n_tranches)
    log(f"[plan] {len(sources)} sources → {len(tranches)} tranches (wave_cap {wave_cap})")
    ckpt_path = out_dir / "checkpoints.json"
    ckpts = json.loads(ckpt_path.read_text()) if ckpt_path.is_file() else []
    done_k = {c["k"] for c in ckpts}
    for k, tr in enumerate(tranches, 1):
        if k in done_k:
            log(f"[k={k}] already checkpointed, skip"); continue
        log(f"[k={k}] ingest {len(tr)} sources …")
        ingest_tranche(work, tr, log=log)
        if do_curate:
            ok = curate(work, wave_cap, patience_h, log=log, model=curate_model)
            if not ok:
                log(f"[k={k}] curate incomplete — stopping (resumable)"); break
        state = snapshot_state(work)
        snap = _snapshot(work, out_dir, k)  # freeze the wiki AS-OF k for the eval
        ckpts.append({"k": k, "state": state, "snapshot": str(snap),
                      "regime": "breadth", "eval": "pending"})
        ckpt_path.write_text(json.dumps(ckpts, indent=2), encoding="utf-8")
        log(f"[k={k}] checkpointed: {state} (wiki snapshot → {snap.name})")
    log(f"[done] {len(ckpts)}/{len(tranches)} checkpoints")
    result = {"checkpoints": len(ckpts), "tranches": len(tranches)}
    if do_eval:
        result["eval"] = _eval_stage(out_dir, log, gen=gen, judges=judges, repeats=repeats)
    return result


EXPLORE_QUERIES = ROOT / "compounding_explore_queries.json"


def run_depth(*, out_dir: Path, rounds: int, wave_cap: int = 2, patience_h: float = 20.0,
              curate_model: str = "claude-sonnet-5", explore_queries: Path = EXPLORE_QUERIES,
              do_eval: bool = True, gen: str | None = None,
              judges: list[str] | None = None, repeats: int = 1,
              log=print) -> dict[str, Any]:
    """DEPTH study: continue from a COMPLETED breadth workspace (corpus fixed, no new
    sources) and run `rounds` exploration rounds. Each round poses a batch of the frozen
    exploration questions → CE writes new analyses → snapshot (k continues past breadth).
    RAG/closed-book are flat by construction, so any CE−RAG rise is pure curation depth."""
    out_dir = Path(out_dir).resolve()
    work = out_dir / "workspace"
    if not (work / "wiki").is_dir():
        raise SystemExit(f"No completed workspace at {work} — run the breadth build first "
                         "(compounding_run … ) so the corpus is fully ingested + curated.")
    questions = [q["q"] for q in json.loads(Path(explore_queries).read_text())["queries"]]
    batches = _split(questions, rounds)
    ckpt_path = out_dir / "checkpoints.json"
    ckpts = json.loads(ckpt_path.read_text()) if ckpt_path.is_file() else []
    done_k = {c["k"] for c in ckpts}
    # Anchor depth to the last BREADTH checkpoint (not max(all) — else a re-run would
    # continue past the depth rounds it already did instead of resuming them).
    start_k = max((c["k"] for c in ckpts if c.get("regime") != "depth"), default=0)
    # Rewind point: back up the FULL pre-depth workspace ONCE (before any depth curation
    # mutates it) so depth can be redone from scratch with a different curator model.
    # Guard on NO existing depth checkpoints — else a resumed/extended run (workspace
    # already mutated to k>5) would back up a depth state, not the pre-depth one.
    existing_depth = [c for c in ckpts if c.get("regime") == "depth"]
    backup = out_dir / "workspace.pre-depth"
    if not backup.exists() and not existing_depth:
        log(f"[depth] backing up pre-depth workspace → {backup.name} (rewind point) …")
        shutil.copytree(work, backup, symlinks=True,
                        ignore=shutil.ignore_patterns("uv-cache", "*.db-wal", "*.db-shm"))
    log(f"[depth] {len(questions)} exploration questions → {len(batches)} rounds "
        f"(k={start_k + 1}..{start_k + len(batches)}); corpus FIXED, model {curate_model}")
    for i, batch in enumerate(batches, 1):
        k = start_k + i
        if k in done_k:
            log(f"[depth k={k}] already checkpointed, skip"); continue
        log(f"[depth k={k}] exploring {len(batch)} question(s) → new analyses …")
        ok = curate(work, wave_cap, patience_h, log=log, model=curate_model,
                    prompt=_explore_prompt(batch), label="explore", expect_pages=True)
        if not ok:
            log(f"[depth k={k}] explore incomplete — stopping (resumable)"); break
        state = snapshot_state(work)
        snap = _snapshot(work, out_dir, k)
        ckpts.append({"k": k, "state": state, "snapshot": str(snap), "regime": "depth",
                      "curator": curate_model, "questions": batch, "eval": "pending"})
        ckpt_path.write_text(json.dumps(ckpts, indent=2), encoding="utf-8")
        log(f"[depth k={k}] checkpointed: {state} (snapshot → {snap.name})")
    depth_done = len([c for c in ckpts if c.get("regime") == "depth"])
    log(f"[depth done] {depth_done} depth checkpoints (total {len(ckpts)})")
    result = {"depth_checkpoints": depth_done, "total_checkpoints": len(ckpts)}
    if do_eval:
        result["eval"] = _eval_stage(out_dir, log, gen=gen, judges=judges, repeats=repeats)
    return result


def rewind_depth(out_dir: Path, log=print) -> dict[str, Any]:
    """Restore an out_dir to its PRE-DEPTH (last-breadth) state so depth can be redone
    with a different curator: archive the prior depth curve, restore the workspace from
    workspace.pre-depth, drop the depth checkpoints + snapshots, and drop depth eval
    cells (so a re-eval recomputes them for the new curator). Breadth k1..N untouched."""
    out_dir = Path(out_dir).resolve()
    work = out_dir / "workspace"
    backup = out_dir / "workspace.pre-depth"
    ckpt_path = out_dir / "checkpoints.json"
    ckpts = json.loads(ckpt_path.read_text()) if ckpt_path.is_file() else []
    breadth = [c for c in ckpts if c.get("regime") != "depth"]
    depth = [c for c in ckpts if c.get("regime") == "depth"]
    if not depth:
        log("[rewind] no depth checkpoints — already at pre-depth"); return {"rewound": 0}
    last_breadth = max((c["k"] for c in breadth), default=0)
    base_snap = out_dir / "wiki-snapshots" / f"k{last_breadth}"
    if not backup.exists() and not (base_snap / "wiki").is_dir():
        raise SystemExit(f"Nothing to rewind to: no {backup.name} and no k{last_breadth} "
                         "wiki snapshot to restore the pre-depth wiki from.")
    prev_curator = (depth[-1].get("curator") or "unknown").replace("/", "-")
    # archive the prior depth curve so switching curators doesn't lose it
    for name in ("eval-report.md", "eval-results.json"):
        p = out_dir / name
        if p.is_file():
            arch = out_dir / f"{p.stem}.depth-{prev_curator}{p.suffix}"
            shutil.copy2(p, arch); log(f"[rewind] archived {name} → {arch.name}")
    # restore the workspace to its pre-depth state
    if backup.exists():
        log(f"[rewind] restoring full workspace from {backup.name} …")
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(backup, work, symlinks=True)
    else:
        # Fallback (run predates the auto-backup): depth only mutates the wiki
        # (vault/.claude/.venv unchanged), so restore wiki (+.curator embeddings) from
        # the last-breadth snapshot in place, keeping the rest of the workspace.
        log(f"[rewind] no {backup.name}; restoring wiki+.curator from k{last_breadth} "
            "snapshot (vault/.claude/.venv untouched) …")
        for sub in ("wiki", ".curator"):
            src = base_snap / sub
            if src.is_dir():
                dst = work / sub
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst, symlinks=True)
    # drop depth snapshots + depth eval cells (k > last breadth)
    for c in depth:
        snap = Path(c["snapshot"])
        if snap.exists():
            shutil.rmtree(snap)
    er = out_dir / "eval-results.json"
    if er.is_file():
        d = json.loads(er.read_text())
        d["cells"] = {k: v for k, v in d.get("cells", {}).items()
                      if int(k.split("|")[0][1:]) <= last_breadth}
        er.write_text(json.dumps(d, indent=2))
    ckpt_path.write_text(json.dumps(breadth, indent=2))
    log(f"[rewind] done — back to pre-depth k={last_breadth} (prior curve archived as "
        f"*.depth-{prev_curator}.*). Re-run --depth with a different --curate-model.")
    return {"rewound": len(depth), "prev_curator": prev_curator, "back_to_k": last_breadth}


def _eval_stage(out_dir: Path, log=print, *, gen: str | None = None,
                judges: list[str] | None = None, repeats: int = 1) -> dict[str, Any]:
    """Score every wiki snapshot (CE/RAG/closed-book, blind-judged) → CE−RAG /
    CE−CB curves. Resumable, unlike the curate cycles. repeats>1 averages K samples
    per cell to cut the noise floor."""
    from bench.agentic_query_bench import compounding_eval
    try:
        res = compounding_eval.run_eval(out_dir, generator=gen, judges=judges,
                                        repeats=repeats, log=log)
    except SystemExit as e:  # no snapshots / no provider — non-fatal for the build
        log(f"[eval] skipped: {e}")
        return {"status": "skipped", "reason": str(e)}
    return {"status": "ok", "curves": res.get("curves"), "per_k": res.get("per_k")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-ws", type=Path, default=Path("samples/ml-walkthrough"))
    ap.add_argument("--out-dir", type=Path, default=ROOT.parents[1] / "bench/results/compounding-v2")
    ap.add_argument("--tranches", type=int, default=5)
    ap.add_argument("--wave-cap", type=int, default=4)
    ap.add_argument("--patience-h", type=float, default=6.0)
    ap.add_argument("--no-curate", action="store_true", help="setup + ingest only (free; skip agentic curate)")
    ap.add_argument("--no-eval", action="store_true", help="build snapshots only; skip the CE/RAG/CB scoring pass")
    ap.add_argument("--eval-only", action="store_true", help="score existing wiki snapshots; skip build+curate")
    ap.add_argument("--generator", default=None, help="force eval generator provider id (e.g. xai)")
    ap.add_argument("--judges", default=None, help="comma-separated eval judge provider ids (e.g. xai,gemini)")
    ap.add_argument("--curate-model", default="claude-sonnet-5",
                    help="model for the detached CURATE sessions (overrides the CLI's "
                         "global default via ANTHROPIC_MODEL; avoids credit-gated defaults)")
    ap.add_argument("--depth", action="store_true",
                    help="DEPTH study: continue from a completed breadth workspace (corpus "
                         "fixed) and run exploration rounds that accumulate new analyses")
    ap.add_argument("--depth-rounds", type=int, default=4,
                    help="number of depth exploration rounds (the frozen exploration "
                         "questions are split across them); default 4")
    ap.add_argument("--explore-queries", type=Path, default=EXPLORE_QUERIES,
                    help="frozen exploration-question JSON for depth rounds")
    ap.add_argument("--rewind", action="store_true",
                    help="restore out-dir to its pre-depth (last-breadth) state so depth "
                         "can be redone with a different --curate-model; archives the prior curve")
    ap.add_argument("--repeats", type=int, default=1,
                    help="auto-eval: independent samples per cell, averaged, to cut the "
                         "noise floor (e.g. 3). Applies to the eval run after the build.")
    a = ap.parse_args(argv)
    judges = a.judges.split(",") if a.judges else None
    if a.rewind:
        r = rewind_depth(out_dir=a.out_dir)
    elif a.depth:
        r = run_depth(out_dir=a.out_dir, rounds=a.depth_rounds, wave_cap=a.wave_cap,
                      patience_h=a.patience_h, curate_model=a.curate_model,
                      explore_queries=a.explore_queries, do_eval=not a.no_eval,
                      gen=a.generator, judges=judges, repeats=a.repeats)
    else:
        r = run(src_ws=a.src_ws.expanduser().resolve(), out_dir=a.out_dir, n_tranches=a.tranches,
                wave_cap=a.wave_cap, patience_h=a.patience_h, do_curate=not a.no_curate,
                do_eval=not a.no_eval, eval_only=a.eval_only, gen=a.generator,
                judges=judges, curate_model=a.curate_model, repeats=a.repeats)
    print(json.dumps(r, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
