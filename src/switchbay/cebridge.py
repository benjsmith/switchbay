"""Bridge to the curiosity-engine skill (read-only dependency).

Spawns `bash <ce_root>/scripts/viewer.sh build` with cwd=workspace, which
invokes wiki_render.py and produces a bundle at
`~/.cache/curiosity-engine/wiki-view/<basename(workspace)>/`. We only
care about `data.json` from that bundle — the static assets are forked
into `frontend/src/widgets/graph/`.

If the workspace lacks a `wiki/` subdir, viewer.sh exits non-zero and we
return None so the graph tab can show an empty state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger("switchbay.cebridge")

# Legacy standalone CE checkout (pre-skill-bundling). Kept as a last
# resort; curiosity-engine now ships as a bundled global skill. Home-
# relative so it doesn't embed a developer username in a shipped build.
DEFAULT_CE_ROOT = Path.home() / "Documents" / "bin" / "curiosity-engine"

# kuzu (CE graph) has no wheels past 3.13. System Python 3.14 makes
# `uv venv` pick 3.14 and `uv pip install kuzu` fails. Pin the
# workspace CE env (and UV_PYTHON) to this unless the operator
# overrides SWITCHBAY_CE_PYTHON.
CE_PYTHON_PIN = "3.13"


def _ce_root_candidates() -> list[Path]:
    """Where CE's scripts/ (setup.sh, viewer.sh, …) might live, in
    priority order. CE is installed as a global skill via `npx skills
    add -g` (~/.agents/skills, symlinked into ~/.claude/skills), so that
    is the primary location now; $SWITCHBAY_CE_ROOT overrides; the old
    standalone checkout is the final fallback."""
    home = Path.home()
    out: list[Path] = []
    env = os.environ.get("SWITCHBAY_CE_ROOT")
    if env:
        out.append(Path(env).expanduser())
    out.append(home / ".claude" / "skills" / "curiosity-engine")
    out.append(home / ".agents" / "skills" / "curiosity-engine")
    out.append(DEFAULT_CE_ROOT)
    return out


def ce_root() -> Path:
    """Resolve CE's root by finding the candidate that actually has
    `scripts/` (so setup.sh / viewer.sh resolve). Falls back to the
    first candidate for a clear not-found error if none exist."""
    cands = _ce_root_candidates()
    for c in cands:
        if (c / "scripts").is_dir():
            return c
    return cands[0]


def output_dir(workspace: Path) -> Path:
    """Where viewer.sh writes the bundle for this workspace."""
    cache = Path.home() / ".cache" / "curiosity-engine" / "wiki-view"
    return cache / workspace.name


def has_wiki(workspace: Path) -> bool:
    return (workspace / "wiki").is_dir()


def _ce_python_pin() -> str:
    return (os.environ.get("SWITCHBAY_CE_PYTHON") or CE_PYTHON_PIN).strip() or CE_PYTHON_PIN


def _workspace_venv_python(workspace: Path) -> Path | None:
    ws = Path(workspace)
    for rel in (
        Path(".venv") / "bin" / "python",
        Path(".venv") / "bin" / "python3",
        Path(".venv") / "Scripts" / "python.exe",
    ):
        p = ws / rel
        if p.is_file():
            return p
    return None


def workspace_venv_version(workspace: Path) -> tuple[int, int] | None:
    """(major, minor) of the workspace CE venv, or None if missing."""
    py = _workspace_venv_python(workspace)
    if py is None:
        return None
    try:
        out = subprocess.run(
            [str(py), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
            capture_output=True, text=True, timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or "").strip()
    if "." not in text:
        return None
    try:
        maj, minr = text.split(".", 1)
        return int(maj), int(minr)
    except ValueError:
        return None


def venv_python_too_new(ver: tuple[int, int] | None) -> bool:
    pin = _ce_python_pin()
    try:
        pmaj, pmin = (int(x) for x in pin.split(".", 1)[:2])
    except ValueError:
        pmaj, pmin = 3, 13
    if ver is None:
        return False
    return ver > (pmaj, pmin)


def _setup_env() -> dict[str, str]:
    env = _scrubbed_env()
    env["UV_PYTHON"] = _ce_python_pin()
    env["CURIOSITY_ENGINE_NONINTERACTIVE"] = "1"
    return env


def scripts_dir() -> Path:
    return ce_root() / "scripts"


def inject_skill_env(env: dict[str, str]) -> dict[str, str]:
    """Point non-Claude CLIs at the global CE skill.

    Copilot / Codex / Grok / Muse sandboxes do not search
    `~/.claude/skills`. CE's SKILL.md documents
    `CURIOSITY_ENGINE_SCRIPTS_DIR` as the portable substitute.
    """
    out = dict(env)
    scripts = scripts_dir()
    if scripts.is_dir():
        out["CURIOSITY_ENGINE_SCRIPTS_DIR"] = str(scripts)
        out.setdefault("CURIOSITY_ENGINE_SKILL_DIR", str(ce_root()))
    # Workspace-relative: CLI cwd is the workspace, and the rail
    # sandbox cannot see ~/.agents/skills. Copies live here.
    out.setdefault("SWITCHBAY_SKILL_MIRRORS", ".workbench/skill-mirrors")
    return out


def skill_is_installed() -> bool:
    """True when a CE install with scripts/ (not SKILL.md-only) is found."""
    return (ce_root() / "scripts" / "setup.sh").is_file()


def install_skill(*, timeout: float = 180.0) -> tuple[bool, str]:
    """Install the global curiosity-engine skill via `npx skills add -g -y`.

    Best-effort. The skills CLI must get `-y` or a headless install
    hangs on a confirmation prompt (the new-Mac failure mode).
    """
    from . import admin_policy
    if skill_is_installed():
        return True, f"curiosity-engine skill present at {ce_root()}"
    if not admin_policy.feature_enabled("install_skills_npx"):
        return False, (
            "curiosity-engine skill is not installed, and admin policy "
            "forbids `npx skills add`. Vendor the skill into the image "
            "or set SWITCHBAY_CE_ROOT. See docs/enterprise.md."
        )
    npx = shutil.which("npx")
    if npx is None:
        return False, (
            "npx not on PATH — install Node.js, then: "
            "`npx skills add -g -y benjsmith/curiosity-engine`"
        )
    try:
        proc = subprocess.run(
            [npx, "-y", "skills", "add", "-g", "-y", "benjsmith/curiosity-engine"],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "npx skills add timed out while installing curiosity-engine"
    except OSError as e:
        return False, f"failed to run npx skills add: {e}"
    if skill_is_installed():
        return True, (
            f"installed curiosity-engine skill at {ce_root()}\n"
            f"{(proc.stdout or proc.stderr or '')[-400:]}"
        )
    tail = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()[-800:]
    return False, (
        f"curiosity-engine skill still missing after npx skills add "
        f"(rc={proc.returncode}). {tail}\n"
        "Install manually: `npx skills add -g -y benjsmith/curiosity-engine`"
    )


def _write_workspace_python_pin(workspace: Path) -> None:
    """Drop `.python-version` so a later bare `uv venv` still picks 3.13."""
    pin = _ce_python_pin()
    path = Path(workspace) / ".python-version"
    try:
        if path.is_file() and path.read_text(encoding="utf-8").strip() == pin:
            return
        path.write_text(pin + "\n", encoding="utf-8")
    except OSError:
        pass


async def _ensure_uv_python(pin: str) -> None:
    """Best-effort `uv python install <pin>` so `uv venv --python` works."""
    from . import admin_policy
    if not admin_policy.feature_enabled("uv_python_install"):
        return
    if shutil.which("uv") is None:
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "uv", "python", "install", pin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await asyncio.wait_for(proc.communicate(), 180)
    except (OSError, asyncio.TimeoutError):
        log.warning("uv python install %s failed or timed out", pin)


async def ensure_pinned_venv(workspace: Path) -> tuple[bool, str]:
    """Make sure workspace `.venv` exists on Python ≤ the kuzu pin.

    CE's setup.sh runs bare `uv venv`, which follows the system
    interpreter. On a 3.14 Mac that yields a venv kuzu cannot
    install into. We create/rebuild the venv with `uv venv --python
    3.13` first so setup.sh only has to `uv pip install kuzu`.
    """
    ws = Path(workspace)
    _write_workspace_python_pin(ws)
    ver = workspace_venv_version(ws)
    if ver is not None and not venv_python_too_new(ver):
        return True, f"venv already on Python {ver[0]}.{ver[1]}"
    pin = _ce_python_pin()
    venv_dir = ws / ".venv"
    if venv_python_too_new(ver) and venv_dir.is_dir():
        log.info("removing workspace .venv on Python %s (kuzu needs ≤%s)",
                 f"{ver[0]}.{ver[1]}" if ver else "?", pin)
        try:
            shutil.rmtree(venv_dir)
        except OSError as e:
            return False, f"could not remove incompatible .venv: {e}"
    if shutil.which("uv") is None:
        return False, "uv not on PATH — install uv, then retry CE setup"
    await _ensure_uv_python(pin)
    env = _setup_env()
    proc = await asyncio.create_subprocess_exec(
        "uv", "venv", "--python", pin,
        cwd=str(ws),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    text = (out or b"").decode(errors="replace")
    if proc.returncode != 0:
        return False, (
            f"uv venv --python {pin} failed: {text[-800:]}\n"
            f"Install Python {pin} (`uv python install {pin}`) and retry."
        )
    return True, f"created .venv on Python {pin}"


async def setup(workspace: Path) -> tuple[bool, str]:
    """Run CE's `scripts/setup.sh` against the workspace. Idempotent —
    re-running on an already-initialised workspace just refreshes the
    template skeleton.

    Returns (ok, captured_output). Same env-scrubbing rule as `build()`.
    Pins the workspace venv to Python 3.13 so kuzu can install.
    """
    from . import admin_policy
    if not admin_policy.feature_enabled("ce_auto_setup"):
        return False, (
            "CE setup.sh is disabled by admin policy. Pre-provision "
            "workspace .venv on the builder, or enable ce_auto_setup. "
            "See docs/enterprise.md."
        )
    if not workspace.is_dir():
        return False, f"workspace path is not a directory: {workspace}"
    installed, skill_msg = await asyncio.to_thread(install_skill)
    if not installed:
        return False, skill_msg
    script = ce_root() / "scripts" / "setup.sh"
    if not script.is_file():
        return False, (
            f"CE setup.sh not found at {script}. "
            "Install the curiosity-engine skill: "
            "`npx skills add -g -y benjsmith/curiosity-engine`"
        )

    pinned, pin_msg = await ensure_pinned_venv(workspace)
    if not pinned:
        return False, pin_msg

    env = _setup_env()
    proc = await asyncio.create_subprocess_exec(
        "bash",
        str(script),
        cwd=str(workspace),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    text = out.decode(errors="replace")
    notes = skill_msg + "\n" + pin_msg + "\n" + text
    if proc.returncode != 0:
        return False, notes[-2000:]
    return True, notes[-2000:]


def read_cached(workspace: Path) -> dict[str, Any] | None:
    """Return the on-disk data.json from a previous viewer.sh build,
    if one exists. Cheap (single file read + json parse) — usable on
    the hot path so a workspace switch shows the graph instantly,
    even if it's a few minutes stale. Pair with `build()` running in
    the background to refresh.

    Returns None when no cached build is on disk yet OR the file
    parses badly OR the workspace has no wiki/."""
    if not has_wiki(workspace):
        return None
    data_path = output_dir(workspace) / "data.json"
    if not data_path.is_file():
        return None
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    _backfill_unclassified_types(data)
    # Filesystem-truth pass — CE's wiki_render occasionally ships
    # node entries typed `unclassified` even when the page's
    # frontmatter declares a real type. The sidebar reads node.type
    # for grouping, so without this fix tables / sources / etc. end
    # up under UNCLASSIFIED despite the .md declaring type:table.
    resync_types_from_disk(workspace, data)
    # Sketch decks (`kind: deck`, title `[deck] …`) live under
    # wiki/analyses/ but CE's graph intentionally omits them from
    # `nodes` (curator exclusion). Inject them so the BROWSER
    # ANALYSES group lists them alongside real analyses.
    inject_deck_nodes(workspace, data)
    from . import wiki_sync
    wiki_sync.inject_on_disk_pages(workspace, data)
    _override_palette(data)
    return data


def has_workspace_venv(workspace: Path) -> bool:
    """True when the workspace has a CE `.venv` with a Python binary.

    Edges come from a kuzu query run *inside* this venv by
    `viewer.sh` / `wiki_render.py`. Without it, builds emit
    nodes-only (0 edges). Used as a self-heal guard after migrate
    (which deliberately skips `.venv`) and for any env-less wiki.
    """
    ws = Path(workspace)
    # Common layouts: plain `.venv/bin/python` (Unix) and
    # `.venv/Scripts/python.exe` (Windows). Presence of either is enough
    # to attempt the build; if kuzu is still missing, viewer.sh fails
    # soft and we still get nodes.
    return (
        (ws / ".venv" / "bin" / "python").is_file()
        or (ws / ".venv" / "bin" / "python3").is_file()
        or (ws / ".venv" / "Scripts" / "python.exe").is_file()
    )


async def ensure_venv(workspace: Path) -> tuple[bool, str]:
    """Create the workspace CE env via `setup.sh` if missing.

    Also rebuilds a venv that is too new for kuzu (Python 3.14+).
    Fail-soft — callers decide whether to continue a nodes-only
    build or abort.
    """
    ver = workspace_venv_version(workspace)
    if has_workspace_venv(workspace) and not venv_python_too_new(ver):
        return True, "venv already present"
    log.info("workspace %s needs a pinned CE venv — running setup.sh", workspace)
    return await setup(workspace)


def graph_db_path(workspace: Path) -> Path:
    """CE's kuzu graph for this workspace."""
    return workspace / ".curator" / "graph.kuzu"


def _scrubbed_env() -> dict[str, str]:
    """Env for CE subprocesses: drop switchbay venv pointers so CE's
    own .venv / uv project (kuzu, embeddings) resolve correctly."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH"}
    }
    env.setdefault("UV_PYTHON", _ce_python_pin())
    return env


def _ce_python() -> list[str]:
    """Argv prefix to run a CE script with the right interpreter.

    Prefer CE's own `.venv` (kuzu + embedding stack live there), then
    fall back to `uv run` from the CE root.
    """
    root = ce_root()
    for rel in (
        Path(".venv") / "bin" / "python",
        Path(".venv") / "bin" / "python3",
        Path(".venv") / "Scripts" / "python.exe",
    ):
        p = root / rel
        if p.is_file():
            return [str(p)]
    return ["uv", "run", "--directory", str(root), "python3"]


def _script_python(cwd: Path) -> list[str]:
    """Interpreter for a CE script run *against* a workspace.

    kuzu lives in the workspace `.venv` (setup.sh). `uv run python3`
    from the workspace cwd discovers that venv. The skill-root venv
    (if any) does not have kuzu.
    """
    py = _workspace_venv_python(cwd)
    if py is not None:
        return [str(py)]
    return ["uv", "run", "python3"]


def run_script(
    script: str,
    args: list[str] | None = None,
    *,
    cwd: Path,
    timeout: float = 120.0,
    require_json: bool = True,
) -> dict[str, Any]:
    """Synchronously run a CE script and parse JSON from stdout.

    Tool handlers are sync; the daemon offloads them via
    ``asyncio.to_thread``. CE scripts emit JSON on stdout natively
    (no ``--json`` flag). Stderr advisories (e.g. "graph stale") are
    captured as ``note`` when results otherwise succeed; ``{"error":…}``
    bodies are unwrapped to a flat ``error`` string.

    ``require_json=False`` keeps stdout as text (rebuild / sweep
    verbs that print a human summary). Returns a dict always —
    never raises.
    """
    import subprocess

    root = ce_root()
    script_path = root / "scripts" / script
    if not script_path.is_file():
        # Allow bare name with or without .py
        if not script.endswith(".py"):
            script_path = root / "scripts" / f"{script}.py"
        if not script_path.is_file():
            return {"error": f"CE script not found: {script} (looked under {root / 'scripts'})"}
    if not Path(cwd).is_dir():
        return {"error": f"workspace is not a directory: {cwd}"}

    cmd = [*_script_python(Path(cwd)), str(script_path), *(args or [])]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=_scrubbed_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"{script} timed out after {int(timeout)}s"}
    except OSError as e:
        return {"error": f"failed to run {script}: {e}"}

    _STDOUT_CAP = 1_500_000  # ~1.5 MB; unbounded capture is a RAM leak
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if len(stdout) > _STDOUT_CAP:
        stdout = stdout[:_STDOUT_CAP]
    if len(stderr) > 8_000:
        stderr = stderr[-8_000:]
    note = stderr[-1500:] if stderr else None

    parsed: Any = None
    if stdout:
        # Scripts may print a single JSON value or a trailing JSON object.
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            # Try last {...} or [...] block.
            for open_c, close_c in (("{", "}"), ("[", "]")):
                start = stdout.find(open_c)
                end = stdout.rfind(close_c)
                if start >= 0 and end > start:
                    try:
                        parsed = json.loads(stdout[start:end + 1])
                        break
                    except json.JSONDecodeError:
                        pass

    if isinstance(parsed, dict) and parsed.get("error"):
        err = parsed["error"]
        if isinstance(err, dict):
            err = err.get("message") or json.dumps(err)
        out: dict[str, Any] = {"error": f"{script}: {err}"}
        if note and "error" not in (note or "").lower():
            out["note"] = note
        if proc.returncode:
            out["returncode"] = proc.returncode
        return out

    if parsed is None:
        if proc.returncode != 0:
            return {
                "error": (
                    f"{script} exited {proc.returncode}: "
                    f"{(stderr or stdout or 'no output')[-800:]}"
                ),
                "returncode": proc.returncode,
            }
        if not require_json:
            out_ok: dict[str, Any] = {"ok": True, "stdout": stdout}
            if note:
                out_ok["note"] = note
            return out_ok
        return {
            "error": f"{script}: expected JSON on stdout, got: {(stdout or '')[:400]!r}",
            "note": note,
        }

    if isinstance(parsed, dict):
        if note:
            parsed = {**parsed, "note": note}
        return parsed
    # list / scalar
    result: dict[str, Any] = {"result": parsed}
    if note:
        result["note"] = note
    return result


async def graph_rebuild(workspace: Path) -> tuple[bool, str]:
    """Run CE's `graph.py rebuild wiki` against the workspace.

    `viewer.sh build` READS the kuzu graph but never rebuilds it — with
    no `.curator/graph.kuzu` on disk, `wiki_render.py` falls back to a
    nodes-only view and the Graph tab renders pages with no edges. CE's
    curator normally does the rebuild as part of a curate wave, so a
    workspace that has never been curated (a freshly-seeded demo, or a
    wiki authored by hand) has no edges until this runs once.

    Idempotent — CE skips when the graph is newer than every page.
    Fail-soft: returns (ok, output) and never raises.
    """
    if not has_wiki(workspace):
        return False, "no wiki/ in workspace"
    script = ce_root() / "scripts" / "graph.py"
    if not script.is_file():
        return False, f"CE graph.py not found at {script}"
    env = _scrubbed_env()
    cmd = [*_script_python(Path(workspace)), str(script), "rebuild", "wiki"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(workspace),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), 900)
    except (OSError, asyncio.TimeoutError) as e:
        return False, f"graph rebuild failed: {e}"
    text = out.decode(errors="replace")
    return proc.returncode == 0, text[-2000:]


async def build(
    workspace: Path, *, ensure_env: bool = True,
) -> dict[str, Any] | None:
    """Run viewer.sh build and return parsed data.json. None if no wiki/.

    When ``ensure_env`` is True (default), a missing workspace `.venv`
    triggers `setup.sh` once before the build so kuzu is available and
    edges are emitted. Migrate excludes `.venv` by design; this is the
    self-heal path for that (and any other env-less wiki).
    """
    if not has_wiki(workspace):
        return None
    render_py = ce_root() / "scripts" / "wiki_render.py"
    script = ce_root() / "scripts" / "viewer.sh"
    if not render_py.is_file() and not script.is_file():
        log.warning("wiki_render.py / viewer.sh not found under %s", ce_root())
        return None

    if ensure_env and not has_workspace_venv(workspace):
        ok, msg = await ensure_venv(workspace)
        if not ok:
            log.warning(
                "setup.sh failed for %s (building nodes-only): %s",
                workspace, msg[-500:],
            )
            # Fall through: build still produces a usable nodes-only
            # view rather than 404. Callers that need edges should
            # check edge count / re-run after fixing the env.

    # Scrub uv/venv env vars so `uv run` inside viewer.sh resolves to the
    # *workspace's* project (which has kuzu installed), not switchbay's
    # venv. Pin UV_PYTHON so a bare `uv venv` inside setup never
    # follows system 3.14.
    env = _scrubbed_env()

    if render_py.is_file():
        import sys
        cmd = [
            sys.executable, str(render_py), "build",
            str(workspace / "wiki"),
            "--output-dir", str(output_dir(workspace)),
        ]
    else:
        cmd = ["bash", str(script), "build"]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(workspace),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        log.warning(
            "viewer.sh build exited %s\nstdout=%s\nstderr=%s",
            proc.returncode,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
        )
        return None

    data_path = output_dir(workspace) / "data.json"
    if not data_path.is_file():
        log.warning("viewer.sh build succeeded but no data.json at %s", data_path)
        return None
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("could not parse %s: %s", data_path, e)
        return None
    _backfill_unclassified_types(data)
    # Filesystem-truth pass — CE's wiki_render occasionally ships
    # node entries typed `unclassified` even when the page's
    # frontmatter declares a real type. The sidebar reads node.type
    # for grouping, so without this fix tables / sources / etc. end
    # up under UNCLASSIFIED despite the .md declaring type:table.
    resync_types_from_disk(workspace, data)
    inject_deck_nodes(workspace, data)
    from . import wiki_sync
    wiki_sync.inject_on_disk_pages(workspace, data)
    _override_palette(data)
    return data


# Switch Bay's per-category palette. Diverges from CE upstream in
# three places to give better visual separation between categories
# the user found too similar:
#
#   - analysis: deeper amethyst (was CE's mauve, too close to the
#     rose-pink figure colour)
#   - project:  Tableau brown ("container/folder" feel; was CE's
#     deep indigo, too close to source steel-blue)
#   - todo:     olive drab ("actionable" green-yellow; was CE's
#     terracotta, too close to entity bright-orange)
#
# Singular and plural forms because frontmatter uses singular while
# subdir / data.json keys can be either. CSS variables in
# `widgets/graph/ce-graph.css` mirror these values.
_PALETTE_OVERRIDE: dict[str, str] = {
    # Mirrors CE's wiki_render.PALETTE so the data.json palette
    # the d3 graph reads matches the --type-* CSS tokens the
    # sidebar dots / label-picker use. CE is the upstream source
    # of truth (2026-05-13 alignment). If CE ever updates its
    # PALETTE this needs the same change.
    "project":         "#4d1ae8",  # vivid violet
    "projects":        "#4d1ae8",
    "analysis":        "#1d6996",  # blue
    "analyses":        "#1d6996",
    "concept":         "#38a6a5",  # teal
    "concepts":        "#38a6a5",
    "entity":          "#0f8554",  # green
    "entities":        "#0f8554",
    "evidence":        "#73af48",  # lime
    "fact":            "#edad08",  # yellow-orange
    "facts":           "#edad08",
    "figure":          "#e17c05",  # orange
    "figures":         "#e17c05",
    "table":           "#cc503e",  # red
    "tables":          "#cc503e",
    "source":          "#94346e",  # magenta
    "sources":         "#94346e",
    "note":            "#6f4070",  # purple
    "notes":           "#6f4070",
    "todo":            "#9656a2",  # lighter purple
    "todo-list":       "#9656a2",
    "unclassified":    "#ffffff",  # white + black stroke via graph.js
}


def _override_palette(data: dict) -> None:
    palette = data.get("palette") if isinstance(data, dict) else None
    if not isinstance(palette, dict):
        return
    for k, v in _PALETTE_OVERRIDE.items():
        palette[k] = v


# Title prefix → CE page-type mapping. Mirrors CE's user-visible
# convention (`[tab]`, `[ana]`, etc.) so a page that has the marker
# in its title but no explicit `type:` in frontmatter still ends up
# in the right bucket. Render-time only — never rewrites disk.
_PREFIX_TO_TYPE: dict[str, str] = {
    "tab": "table",
    "ana": "analysis",
    "con": "concept",
    "ent": "entity",
    "evi": "evidence",
    "fac": "fact",
    "fig": "figure",
    "src": "source",
    "note": "note",
    "todo": "todo",
    "proj": "project",
    # Decks scaffolded by switchbay's → Slides path. CE doesn't
    # ship a `deck` type; render them as `analysis` so the existing
    # palette / sidebar bucket picks them up. The `[deck]` title
    # prefix + `kind: deck` frontmatter keep them distinct from
    # plain analyses for the curator + UI.
    "deck": "analysis",
}


def _backfill_unclassified_types(data: dict) -> None:
    """Promote `unclassified` pages into a real type when their
    title starts with the CE bracket prefix convention. Closes
    issue 6 — older table extractions ship with
    `type: unclassified` even though their `[tab]` title says
    otherwise; we infer at render time so the sidebar / graph /
    label-types panel see them correctly."""
    pages = data.get("pages") if isinstance(data, dict) else None
    nodes = data.get("nodes") if isinstance(data, dict) else None
    if not isinstance(pages, dict):
        return
    promoted = 0
    promoted_ids: dict[str, str] = {}
    for pid, page in pages.items():
        if not isinstance(page, dict):
            continue
        if str(page.get("type") or "").lower() != "unclassified":
            continue
        title = str(page.get("title") or "")
        m = re.match(r"^\s*\[([a-z]+)\]", title, flags=re.IGNORECASE)
        if not m:
            continue
        inferred = _PREFIX_TO_TYPE.get(m.group(1).lower())
        if not inferred:
            continue
        page["type"] = inferred
        promoted_ids[pid] = inferred
        promoted += 1
    # Apply the same promotion to the nodes list — the wiki sidebar
    # reads node.type, not page.type, so without this the page
    # would show as the right type in the modal but still group
    # under UNCLASSIFIED in the sidebar.
    if promoted_ids and isinstance(nodes, list):
        for n in nodes:
            if not isinstance(n, dict):
                continue
            new_type = promoted_ids.get(str(n.get("id") or ""))
            if new_type:
                n["type"] = new_type
    if promoted:
        log.info("backfilled %d page types from title prefix (pages + nodes)", promoted)


# Match a one-line `type: foo` frontmatter declaration. Tolerant of
# quoting + trailing whitespace. We don't pull a YAML dep for this —
# CE's writer emits the simple form and that's what we need to read.
_FM_TYPE_RE = re.compile(r"^\s*type\s*:\s*['\"]?([A-Za-z0-9_-]+)['\"]?\s*$")


def resync_types_from_disk(workspace: Path, data: dict) -> int:
    """Walk wiki/*.md, read each file's `type:` frontmatter line
    directly, and override `data['pages'][id].type` AND
    `data['nodes'][id].type` to match. Filesystem is the source of
    truth — CE's wiki_render sometimes ships node entries typed
    `unclassified` even when the page's frontmatter clearly
    declares a type. This forces both data structures into sync
    with what's actually on disk.

    Returns the number of nodes whose type changed."""
    wiki = workspace / "wiki"
    if not wiki.is_dir():
        return 0
    pages = data.get("pages") if isinstance(data, dict) else None
    nodes = data.get("nodes") if isinstance(data, dict) else None
    if not isinstance(pages, dict) or not isinstance(nodes, list):
        return 0
    # Map page-id → declared frontmatter type. Page ids in CE-shaped
    # data.json are the wiki-relative path minus the .md extension,
    # so `wiki/tables/foo.md` → `tables/foo`. We mirror that here.
    declared: dict[str, str] = {}
    for md in wiki.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        if end == -1:
            continue
        block = text[3:end]
        type_line = None
        for line in block.splitlines():
            m = _FM_TYPE_RE.match(line)
            if m:
                type_line = m.group(1).lower()
                break
        if not type_line:
            continue
        try:
            rel = md.resolve().relative_to(wiki.resolve())
        except ValueError:
            continue
        pid = rel.with_suffix("").as_posix()
        # Canonicalise plurals + CE subtypes → the singular form
        # the sidebar's TYPE_CANONICAL expects. `extracted-table`
        # is the CE subtype for tables lifted out of source PDFs;
        # CE itself canonicalises it to `table` on the page side
        # but not on the node side, which is the desync the user
        # hit: page modal shows `type: table`, sidebar still groups
        # under UNCLASSIFIED.
        canon = {
            "projects": "project", "analyses": "analysis",
            "concepts": "concept", "entities": "entity",
            "facts": "fact", "figures": "figure",
            "tables": "table", "sources": "source",
            "notes": "note", "todo": "todo-list",
            "todos": "todo-list",
            "extracted-table": "table",
            "extracted_table": "table",
        }.get(type_line, type_line)
        declared[pid] = canon
    if not declared:
        return 0
    changed = 0
    for pid, want in declared.items():
        page = pages.get(pid)
        if isinstance(page, dict) and str(page.get("type") or "").lower() != want:
            page["type"] = want
            changed += 1
    for n in nodes:
        if not isinstance(n, dict):
            continue
        want = declared.get(str(n.get("id") or ""))
        if want and str(n.get("type") or "").lower() != want:
            n["type"] = want
            changed += 1
    if changed:
        log.info("resync_types_from_disk: %d type fields aligned with frontmatter", changed)
    return changed


# Frontmatter keys we care about for deck discovery. Hand-rolled so we
# don't pull a YAML dep (same dialect as analyses.parse_frontmatter).
_FM_KIND_RE = re.compile(r"^\s*kind\s*:\s*['\"]?([A-Za-z0-9_-]+)['\"]?\s*$")
_FM_TITLE_RE = re.compile(r"^\s*title\s*:\s*(.+?)\s*$")


def inject_deck_nodes(workspace: Path, data: dict[str, Any]) -> int:
    """Ensure every on-disk `kind: deck` page appears in both
    `data['pages']` and `data['nodes']` as `type: analysis`.

    CE's viewer build includes deck markdown in `pages` (sometimes)
    but leaves them out of `nodes` — the BROWSER sidebar groups by
    `nodes`, so decks were invisible under ANALYSES even though they
    live at `wiki/analyses/<slug>.md` with a `[deck]` title. Render-
    time only; never rewrites disk. Returns the number of nodes added
    or updated."""
    wiki = workspace / "wiki"
    if not wiki.is_dir() or not isinstance(data, dict):
        return 0
    pages = data.get("pages")
    nodes = data.get("nodes")
    if not isinstance(pages, dict):
        pages = {}
        data["pages"] = pages
    if not isinstance(nodes, list):
        nodes = []
        data["nodes"] = nodes

    by_id = {
        str(n.get("id") or ""): n
        for n in nodes
        if isinstance(n, dict) and n.get("id")
    }
    added = 0
    for md in wiki.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        if end == -1:
            continue
        block = text[3:end]
        kind = None
        title = None
        for line in block.splitlines():
            if kind is None:
                m = _FM_KIND_RE.match(line)
                if m:
                    kind = m.group(1).lower()
            if title is None:
                m = _FM_TITLE_RE.match(line)
                if m:
                    raw = m.group(1).strip()
                    if (raw.startswith('"') and raw.endswith('"')) or (
                        raw.startswith("'") and raw.endswith("'")
                    ):
                        raw = raw[1:-1]
                    title = raw
            if kind is not None and title is not None:
                break
        if kind != "deck":
            continue
        try:
            rel = md.resolve().relative_to(wiki.resolve())
        except ValueError:
            continue
        pid = rel.with_suffix("").as_posix()
        path = rel.as_posix()
        display = title or f"[deck] {md.stem}"
        if not display.lower().startswith("[deck"):
            display = f"[deck] {display}"

        # pages entry — source of truth for the modal / editor path
        page = pages.get(pid)
        if not isinstance(page, dict):
            page = {"id": pid, "path": path, "title": display, "type": "analysis"}
            pages[pid] = page
            added += 1
        else:
            page["type"] = "analysis"
            page["title"] = display
            page.setdefault("path", path)

        # nodes entry — what the sidebar actually lists
        node = by_id.get(pid)
        if node is None:
            node = {
                "id": pid,
                "path": path,
                "type": "analysis",
                "title": display,
                "degree": 0,
            }
            nodes.append(node)
            by_id[pid] = node
            added += 1
        else:
            node["type"] = "analysis"
            node["title"] = display
            node.setdefault("path", path)

    if added:
        log.info("inject_deck_nodes: ensured %d deck page/node entries", added)
    return added
