"""Check GitHub releases and apply updates for Switch Bay + bundled skills.

Settings → Update compares the running Switch Bay version and the
installed curiosity-engine / curiosity-merge skills against each
repo's latest GitHub release. Anything older is updated in place,
then the daemon restarts (same path as Settings → Restart) so the
PWA reloads via the boot_id watcher.

Skill source trees are never edited here — we only invoke git or
`npx skills` on the already-installed copies.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__, cebridge, service, skillkit

log = logging.getLogger("switchbay.updater")

# skills >=1.5.13 bricks root-layout installs (SKILL.md at repo root
# — curiosity-merge) by writing only SKILL.md and deleting scripts/.
# 1.5.12 is the last version CE's own update.sh trusts. Nested-layout
# CE installs work with it too.
SKILLS_CLI_VERSION = "1.5.12"

_GITHUB_API = "https://api.github.com"
_GITHUB_RAW = "https://raw.githubusercontent.com"

_VER_LEAD = re.compile(r"^v?(\d+(?:\.\d+){0,3})", re.I)
_CHANGELOG_VER = re.compile(
    r"^##\s+(?:(?:\d{4}-\d{2}-\d{2})\s+[—–-]\s+)?v?(\d+\.\d+(?:\.\d+)*)",
    re.M,
)


@dataclass(frozen=True)
class Component:
    id: str
    label: str
    repo: str
    kind: str  # "app" | "skill"
    skill_name: str = ""
    # Candidate paths of SKILL.md inside the upstream repo (tried in
    # order when we need a content fingerprint).
    skill_md_paths: tuple[str, ...] = ()
    sentinel: str = ""  # relative path that must survive an npx update
    # Switch Bay release pairing. Help uses this when an npx skill
    # install has no git tag / CHANGELOG. Bump alongside pyproject.
    related_version: str = ""


COMPONENTS: tuple[Component, ...] = (
    Component(id="switchbay", label="Switch Bay", repo="benjsmith/switchbay", kind="app"),
    Component(
        id="curiosity-engine",
        label="Curiosity Engine",
        repo="benjsmith/curiosity-engine",
        kind="skill",
        skill_name="curiosity-engine",
        skill_md_paths=("skills/curiosity-engine/SKILL.md", "SKILL.md"),
        sentinel="scripts/setup.sh",
        related_version="1.3.0",
    ),
    Component(
        id="curiosity-merge",
        label="Curiosity Merge",
        repo="benjsmith/curiosity-merge",
        kind="skill",
        skill_name="curiosity-merge",
        skill_md_paths=("SKILL.md",),
        sentinel="scripts/setup.sh",
        related_version="0.7.0",
    ),
)


class UpdateError(Exception):
    """A check/apply step failed in a way the user should see."""


# ── versions ────────────────────────────────────────────────────────


def parse_version(raw: str | None) -> tuple[int, ...] | None:
    """Leading dotted numeric tuple from a tag / __version__ / changelog."""
    if not raw:
        return None
    m = _VER_LEAD.match(raw.strip())
    if not m:
        return None
    return tuple(int(p) for p in m.group(1).split("."))


def version_less(a: str | None, b: str | None) -> bool:
    """True when `a` is a strictly older semver than `b`."""
    pa, pb = parse_version(a), parse_version(b)
    if pa is None or pb is None:
        return False
    n = max(len(pa), len(pb))
    pa = pa + (0,) * (n - len(pa))
    pb = pb + (0,) * (n - len(pb))
    return pa < pb


def display_tag(raw: str | None) -> str:
    if not raw:
        return ""
    s = raw.strip()
    if parse_version(s) is not None and not s.lower().startswith("v"):
        return "v" + s
    return s


# ── process env / runners ───────────────────────────────────────────


def child_env() -> dict[str, str]:
    """PATH the launchd daemon's slim environment is missing.

    The installed service only sees /usr/bin + ~/.local/bin. git/npx/
    pnpm/uv live in Homebrew or the user profile; without them an
    in-app update can't fetch or rebuild.
    """
    env = os.environ.copy()
    extras = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / "bin"),
    ]
    env["PATH"] = os.pathsep.join([*extras, env.get("PATH", "")])
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["NPM_CONFIG_YES"] = "true"
    return env


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=child_env(),
    )


def _git(args: list[str], *, cwd: Path, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=cwd, timeout=timeout)


# ── HTTP ────────────────────────────────────────────────────────────


def http_get(url: str, timeout: float = 20.0) -> tuple[int, bytes]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"switchbay/{__version__}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read()
        except Exception:  # noqa: BLE001
            pass
        return int(e.code), body
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError(f"network error fetching {url}: {e}") from e


def fetch_latest_tag(repo: str) -> str:
    status, body = http_get(f"{_GITHUB_API}/repos/{repo}/releases/latest")
    if status == 404:
        raise UpdateError(f"no GitHub releases for {repo}")
    if status == 403:
        raise UpdateError("GitHub API rate-limited the release check; try again later")
    if status != 200:
        raise UpdateError(f"GitHub releases for {repo}: HTTP {status}")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise UpdateError(f"GitHub releases for {repo}: invalid JSON") from e
    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        raise UpdateError(f"GitHub latest release for {repo} has no tag")
    return tag


def fetch_remote_bytes(repo: str, tag: str, relpath: str) -> bytes | None:
    status, body = http_get(f"{_GITHUB_RAW}/{repo}/{tag}/{relpath}")
    if status == 200 and body:
        return body
    return None


def fetch_release_tags(repo: str, *, limit: int = 20) -> list[str]:
    """Newest GitHub release tags first. Raises UpdateError on HTTP failure."""
    n = max(1, min(int(limit), 100))
    status, body = http_get(f"{_GITHUB_API}/repos/{repo}/releases?per_page={n}")
    if status == 404:
        raise UpdateError(f"no GitHub releases for {repo}")
    if status == 403:
        raise UpdateError("GitHub API rate-limited the release check; try again later")
    if status != 200:
        raise UpdateError(f"GitHub releases for {repo}: HTTP {status}")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise UpdateError(f"GitHub releases for {repo}: invalid JSON") from e
    if not isinstance(data, list):
        raise UpdateError(f"GitHub releases for {repo}: expected a list")
    tags: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("tag_name") or "").strip()
        if tag:
            tags.append(tag)
    return tags


# ── local discovery ─────────────────────────────────────────────────


def find_skill_dir(name: str) -> Path | None:
    """Installed skill directory (SKILL.md present), or None if absent.

    Only user-global installs count — a workspace-local copy is not
    'the' running skill we update. CE prefers cebridge.ce_root().
    """
    candidates: list[Path] = []
    if name == "curiosity-engine":
        try:
            cr = cebridge.ce_root()
        except Exception:  # noqa: BLE001
            cr = None
        if cr is not None:
            candidates.append(cr)
    for root in skillkit._global_skill_roots():
        candidates.append(root / name)
    seen: set[Path] = set()
    for p in candidates:
        try:
            key = p.resolve()
        except OSError:
            key = p
        if key in seen:
            continue
        seen.add(key)
        if (p / "SKILL.md").is_file():
            return p
    return None


def _skill_git_repo(skill_dir: Path) -> Path | None:
    """Toplevel of the skill's own git repo, or None.

    Same 'is it really our repo' guard as CE's update.sh: an npx
    install under a git-managed $HOME must not `git pull` dotfiles.
    """
    try:
        r = _git(["rev-parse", "--show-toplevel"], cwd=skill_dir, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    top = Path((r.stdout or "").strip())
    if not top.is_dir():
        return None
    name = skill_dir.name
    try:
        skill_res = skill_dir.resolve()
        top_res = top.resolve()
    except OSError:
        skill_res, top_res = skill_dir, top
    if (top / "skills" / name / "SKILL.md").is_file():
        return top
    if top_res == skill_res and (top / "SKILL.md").is_file():
        return top
    return None


def _git_describe_tag(repo: Path) -> str | None:
    try:
        r = _git(["describe", "--tags", "--abbrev=0"], cwd=repo, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return None
    tag = (r.stdout or "").strip()
    if r.returncode == 0 and parse_version(tag):
        return tag
    return None


def _changelog_version(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _CHANGELOG_VER.search(text)
    return m.group(1) if m else None


def local_skill_version(skill_dir: Path) -> str | None:
    repo = _skill_git_repo(skill_dir)
    if repo is not None:
        tag = _git_describe_tag(repo)
        if tag:
            return tag
    return _changelog_version(skill_dir / "CHANGELOG.md")


def local_switchbay_version() -> str:
    return __version__


# npx skill installs have no git tag / CHANGELOG. Keyed by
# (component id, local SKILL.md sha256) so a daemon restart is the
# only thing that re-walks GitHub after an in-place skill update.
_FP_CACHE: dict[tuple[str, str], str | None] = {}


def match_skill_release(comp: Component, skill_dir: Path) -> str | None:
    """GitHub tag whose SKILL.md bytes match this install, or None.

    Walks recent releases newest-first. Used by the Help panel for
    npx installs that have no local semver. Failures (network, no
    match) return None; only a completed walk is cached.
    """
    local_hash = _file_sha256(skill_dir / "SKILL.md")
    if not local_hash:
        return None
    cache_key = (comp.id, local_hash)
    if cache_key in _FP_CACHE:
        return _FP_CACHE[cache_key]
    try:
        tags = fetch_release_tags(comp.repo)
    except UpdateError:
        return None
    found: str | None = None
    for tag in tags:
        try:
            remote_hash = _remote_skill_fingerprint(comp, tag)
        except UpdateError:
            continue
        if remote_hash and remote_hash == local_hash:
            found = tag
            break
    _FP_CACHE[cache_key] = found
    return found


def installed_components() -> list[dict[str, Any]]:
    """Running Switch Bay / skill versions. Local only — no GitHub.

    Skill semver comes from git tag or CHANGELOG. npx installs often
    have neither; Help then shows ``related_version`` (this Switch Bay
    release's pairing) so the panel always has a number.
    """
    rows: list[dict[str, Any]] = []
    for comp in COMPONENTS:
        row: dict[str, Any] = {
            "id": comp.id,
            "label": comp.label,
            "kind": comp.kind,
            "installed": True,
            "current": None,
        }
        if comp.kind == "app":
            row["current"] = display_tag(local_switchbay_version())
            rows.append(row)
            continue
        skill_dir = find_skill_dir(comp.skill_name)
        if skill_dir is None:
            row["installed"] = False
            rows.append(row)
            continue
        current = local_skill_version(skill_dir) or comp.related_version or None
        if current:
            row["current"] = display_tag(current)
        rows.append(row)
    return rows


def _file_sha256(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest()


def _remote_skill_fingerprint(comp: Component, tag: str) -> str | None:
    for rel in comp.skill_md_paths:
        body = fetch_remote_bytes(comp.repo, tag, rel)
        if body:
            return hashlib.sha256(body).hexdigest()
    return None


# ── check ───────────────────────────────────────────────────────────


def _component_status(comp: Component) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": comp.id,
        "label": comp.label,
        "repo": comp.repo,
        "kind": comp.kind,
        "current": None,
        "latest": None,
        "installed": True,
        "update_available": False,
        "error": None,
        "channel": None,
    }
    try:
        latest = fetch_latest_tag(comp.repo)
    except UpdateError as e:
        row["error"] = str(e)
        return row
    row["latest"] = display_tag(latest)

    if comp.kind == "app":
        current = local_switchbay_version()
        row["current"] = display_tag(current)
        row["channel"] = "git"
        row["update_available"] = version_less(current, latest)
        return row

    skill_dir = find_skill_dir(comp.skill_name)
    if skill_dir is None:
        row["installed"] = False
        row["current"] = None
        return row
    row["path"] = str(skill_dir)
    git_repo = _skill_git_repo(skill_dir)
    row["channel"] = "git" if git_repo is not None else "npx"
    current = local_skill_version(skill_dir)
    if current:
        row["current"] = display_tag(current)
        row["update_available"] = version_less(current, latest)
        return row

    # No local semver (typical npx install). Compare SKILL.md to the
    # file at the latest tag — same bytes means we're already there.
    local_hash = _file_sha256(skill_dir / "SKILL.md")
    try:
        remote_hash = _remote_skill_fingerprint(comp, latest)
    except UpdateError as e:
        row["error"] = str(e)
        row["current"] = "unknown"
        row["update_available"] = True
        return row
    if local_hash and remote_hash and local_hash == remote_hash:
        row["current"] = display_tag(latest)
        row["update_available"] = False
        return row
    row["current"] = "unknown"
    row["update_available"] = True
    return row


def check() -> dict[str, Any]:
    """Inspect GitHub + local versions. Never mutates anything."""
    components = [_component_status(c) for c in COMPONENTS]
    errors = [c["error"] for c in components if c.get("error")]
    return {
        "ok": not errors,
        "error": "; ".join(errors) if errors else None,
        "components": components,
        "update_available": any(c.get("update_available") for c in components),
    }


# ── apply ───────────────────────────────────────────────────────────


def _git_dirty(repo: Path) -> bool:
    try:
        r = _git(["status", "--porcelain"], cwd=repo, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return True
    return r.returncode != 0 or bool((r.stdout or "").strip())


def _git_detached(repo: Path) -> bool:
    try:
        r = _git(["symbolic-ref", "-q", "HEAD"], cwd=repo, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode != 0


def _resolve_tag(repo: Path, latest: str) -> str | None:
    """Return a tag name that exists after fetch, trying v-prefix variants."""
    candidates = [latest]
    if latest.lower().startswith("v"):
        candidates.append(latest[1:])
    else:
        candidates.append("v" + latest)
    for tag in candidates:
        r = _git(["rev-parse", "-q", "--verify", f"refs/tags/{tag}"], cwd=repo, timeout=8)
        if r.returncode == 0:
            return tag
    return None


def _is_ancestor(repo: Path, older: str, newer: str) -> bool:
    r = _git(["merge-base", "--is-ancestor", older, newer], cwd=repo, timeout=8)
    return r.returncode == 0


def _sync_and_build(repo: Path) -> None:
    if shutil.which("make", path=child_env().get("PATH")):
        sync = _run(["make", "sync"], cwd=repo, timeout=180)
        if sync.returncode != 0:
            raise UpdateError(
                f"make sync failed: {(sync.stderr or sync.stdout or '')[-400:]}"
            )
        build = _run(["make", "build-frontend"], cwd=repo, timeout=300)
        if build.returncode != 0:
            raise UpdateError(
                f"make build-frontend failed: {(build.stderr or build.stdout or '')[-400:]}"
            )
        return
    uv = _run(["uv", "sync"], cwd=repo, timeout=180)
    if uv.returncode != 0:
        raise UpdateError(f"uv sync failed: {(uv.stderr or uv.stdout or '')[-400:]}")
    pnpm = _run(
        ["pnpm", "--dir", "frontend", "run", "build"], cwd=repo, timeout=300,
    )
    if pnpm.returncode != 0:
        raise UpdateError(
            f"frontend build failed: {(pnpm.stderr or pnpm.stdout or '')[-400:]}"
        )


def _apply_switchbay(comp: Component, latest: str) -> dict[str, Any]:
    repo = service._repo_root()
    out: dict[str, Any] = {
        "id": comp.id,
        "label": comp.label,
        "status": "failed",
        "from": display_tag(local_switchbay_version()),
        "to": display_tag(latest),
        "detail": "",
    }
    if not (repo / ".git").exists() and not (repo / ".git").is_file():
        out["status"] = "skipped"
        out["detail"] = "this install is not a git checkout"
        return out
    if _git_dirty(repo):
        out["status"] = "skipped"
        out["detail"] = "working tree has local changes — commit or stash first"
        return out
    fetched = _git(["fetch", "--tags", "origin"], cwd=repo, timeout=90)
    if fetched.returncode != 0:
        out["detail"] = (
            f"git fetch failed: {(fetched.stderr or fetched.stdout or '')[-300:]}"
        )
        return out
    tag = _resolve_tag(repo, latest)
    if tag is None:
        out["detail"] = f"tag {display_tag(latest)} not found after fetch"
        return out
    head = _git(["rev-parse", "HEAD"], cwd=repo, timeout=8)
    target = _git(["rev-parse", f"{tag}^{{commit}}"], cwd=repo, timeout=8)
    if head.returncode == 0 and target.returncode == 0:
        if (head.stdout or "").strip() == (target.stdout or "").strip():
            out["status"] = "unchanged"
            out["detail"] = f"already at {tag}"
            return out
    if _git_detached(repo):
        co = _git(["checkout", "--detach", tag], cwd=repo, timeout=30)
        if co.returncode != 0:
            out["detail"] = (
                f"git checkout {tag} failed: {(co.stderr or co.stdout or '')[-300:]}"
            )
            return out
    elif _is_ancestor(repo, "HEAD", tag):
        mg = _git(["merge", "--ff-only", tag], cwd=repo, timeout=30)
        if mg.returncode != 0:
            out["detail"] = (
                f"git merge --ff-only {tag} failed: "
                f"{(mg.stderr or mg.stdout or '')[-300:]}"
            )
            return out
    else:
        out["status"] = "skipped"
        out["detail"] = (
            f"local branch has commits not in {tag} — update from a terminal"
        )
        return out
    try:
        _sync_and_build(repo)
    except UpdateError as e:
        out["detail"] = str(e)
        return out
    out["status"] = "updated"
    out["detail"] = f"checked out {tag} and rebuilt"
    return out


def _npx() -> str | None:
    return shutil.which("npx", path=child_env().get("PATH"))


def _apply_skill_git(comp: Component, repo: Path, latest: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": comp.id,
        "label": comp.label,
        "status": "failed",
        "from": display_tag(local_skill_version(repo) or ""),
        "to": display_tag(latest),
        "detail": "",
    }
    if _git_dirty(repo):
        out["status"] = "skipped"
        out["detail"] = "skill git checkout has local changes"
        return out
    fetched = _git(["fetch", "--tags", "origin"], cwd=repo, timeout=90)
    if fetched.returncode != 0:
        out["detail"] = (
            f"git fetch failed: {(fetched.stderr or fetched.stdout or '')[-300:]}"
        )
        return out
    tag = _resolve_tag(repo, latest)
    if tag is None:
        # Fall back to ff-only pull of the tracking branch (CE update.sh).
        pull = _git(["pull", "--ff-only"], cwd=repo, timeout=60)
        if pull.returncode != 0:
            out["detail"] = f"tag {latest} missing and git pull --ff-only failed"
            return out
        out["status"] = "updated"
        out["detail"] = "git pull --ff-only"
        return out
    head = _git(["rev-parse", "HEAD"], cwd=repo, timeout=8)
    target = _git(["rev-parse", f"{tag}^{{commit}}"], cwd=repo, timeout=8)
    if (
        head.returncode == 0
        and target.returncode == 0
        and (head.stdout or "").strip() == (target.stdout or "").strip()
    ):
        out["status"] = "unchanged"
        out["detail"] = f"already at {tag}"
        return out
    if _git_detached(repo):
        step = _git(["checkout", "--detach", tag], cwd=repo, timeout=30)
    elif _is_ancestor(repo, "HEAD", tag):
        step = _git(["merge", "--ff-only", tag], cwd=repo, timeout=30)
    else:
        out["status"] = "skipped"
        out["detail"] = f"skill branch has commits not in {tag}"
        return out
    if step.returncode != 0:
        out["detail"] = (
            f"git update to {tag} failed: {(step.stderr or step.stdout or '')[-300:]}"
        )
        return out
    out["status"] = "updated"
    out["detail"] = f"checked out {tag}"
    return out


def _restore_tree(src: Path, dest: Path) -> None:
    if dest.is_dir():
        for child in dest.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    shutil.copytree(src, dest, dirs_exist_ok=True)


def _apply_skill_npx(comp: Component, skill_dir: Path, latest: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": comp.id,
        "label": comp.label,
        "status": "failed",
        "from": display_tag(local_skill_version(skill_dir) or "") or "unknown",
        "to": display_tag(latest),
        "detail": "",
    }
    npx = _npx()
    if npx is None:
        out["detail"] = "npx not on PATH — install Node.js to update skills"
        return out
    snapshot: Path | None = None
    try:
        snapshot = Path(tempfile.mkdtemp(prefix=f"sb-{comp.id}-"))
        shutil.copytree(skill_dir, snapshot, dirs_exist_ok=True)
        argv = [
            npx, "-y", f"skills@{SKILLS_CLI_VERSION}",
            "update", "-g", "-y", comp.skill_name,
        ]
        proc = _run(argv, timeout=180)
        text = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        missing = "No installed skills found matching" in text
        if proc.returncode != 0 or missing:
            argv = [
                npx, "-y", f"skills@{SKILLS_CLI_VERSION}",
                "add", "-g", "-y", comp.repo,
            ]
            proc = _run(argv, timeout=180)
            text = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
            if proc.returncode != 0:
                if snapshot is not None:
                    _restore_tree(snapshot, skill_dir)
                out["detail"] = f"npx skills update failed: {text[-400:]}"
                return out
        sentinel = skill_dir / comp.sentinel if comp.sentinel else skill_dir / "SKILL.md"
        if not sentinel.is_file():
            if snapshot is not None:
                _restore_tree(snapshot, skill_dir)
            out["detail"] = (
                f"update left a partial install (missing {comp.sentinel or 'SKILL.md'}); "
                "rolled back"
            )
            return out
    except (OSError, subprocess.TimeoutExpired) as e:
        if snapshot is not None and snapshot.is_dir():
            try:
                _restore_tree(snapshot, skill_dir)
            except OSError:
                pass
        out["detail"] = f"skill update failed: {e}"
        return out
    finally:
        if snapshot is not None:
            shutil.rmtree(snapshot, ignore_errors=True)
    out["status"] = "updated"
    out["detail"] = f"npx skills → {display_tag(latest)}"
    return out


def _apply_skill(comp: Component, latest: str) -> dict[str, Any]:
    skill_dir = find_skill_dir(comp.skill_name)
    if skill_dir is None:
        return {
            "id": comp.id,
            "label": comp.label,
            "status": "skipped",
            "from": None,
            "to": display_tag(latest),
            "detail": "not installed",
        }
    git_repo = _skill_git_repo(skill_dir)
    if git_repo is not None:
        return _apply_skill_git(comp, git_repo, latest)
    return _apply_skill_npx(comp, skill_dir, latest)


def _summarize(results: list[dict[str, Any]]) -> str:
    updated = [r for r in results if r.get("status") == "updated"]
    failed = [r for r in results if r.get("status") == "failed"]
    skipped = [r for r in results if r.get("status") == "skipped"]
    if not updated and not failed and not skipped:
        return "Already up to date."
    bits: list[str] = []
    if updated:
        parts = []
        for r in updated:
            src, dst = r.get("from") or "?", r.get("to") or "?"
            parts.append(f"{r['label']} ({src} → {dst})")
        bits.append("Updated " + ", ".join(parts))
    if failed:
        bits.append(
            "Failed: "
            + "; ".join(f"{r['label']}: {r.get('detail') or 'error'}" for r in failed)
        )
    if skipped:
        bits.append(
            "Skipped "
            + "; ".join(f"{r['label']} ({r.get('detail') or 'skipped'})" for r in skipped)
        )
    return ". ".join(bits) + "."


def apply() -> dict[str, Any]:
    """Check GitHub and update any component that's behind.

    Does not restart the daemon — the HTTP handler does that after
    this returns so the JSON response can leave first.
    """
    report = check()
    if not report.get("ok") and not any(
        c.get("latest") for c in report.get("components") or []
    ):
        return {
            "ok": False,
            "error": report.get("error") or "could not reach GitHub",
            "components": report.get("components") or [],
            "updated": False,
            "summary": report.get("error") or "could not reach GitHub",
        }

    by_id = {c.id: c for c in COMPONENTS}
    results: list[dict[str, Any]] = []
    for row in report.get("components") or []:
        cid = str(row.get("id") or "")
        comp = by_id.get(cid)
        if comp is None:
            continue
        if row.get("error") and not row.get("latest"):
            results.append({
                "id": cid,
                "label": row.get("label") or cid,
                "status": "failed",
                "from": row.get("current"),
                "to": None,
                "detail": row.get("error"),
            })
            continue
        if not row.get("update_available"):
            results.append({
                "id": cid,
                "label": row.get("label") or cid,
                "status": "unchanged",
                "from": row.get("current"),
                "to": row.get("latest"),
                "detail": "not installed" if not row.get("installed") else "already current",
            })
            continue
        latest = str(row.get("latest") or "")
        log.info("updating %s → %s", cid, latest)
        if comp.kind == "app":
            results.append(_apply_switchbay(comp, latest))
        else:
            results.append(_apply_skill(comp, latest))

    any_updated = any(r.get("status") == "updated" for r in results)
    any_failed = any(r.get("status") == "failed" for r in results)
    summary = _summarize(results)
    return {
        "ok": not any_failed,
        "error": None if not any_failed else summary,
        "components": results,
        "updated": any_updated,
        "summary": summary,
    }
