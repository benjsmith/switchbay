"""Share a workspace via GitHub (D3, stage 5).

Publish = the workspace folder becomes (or updates) a git repo pushed
with `gh`, tagged `curiosity-workspace` for discovery. Scope per the
2026-07-05 ruling: knowledge + vault with a vault opt-out —
`.workbench/` (machine/user config + rail history DB) is ALWAYS
excluded, and `.curator/` ships only its two shareable files
(profile.md, projects.json); the Kuzu build, embeddings, and caches
are regenerable and stay home. Install = the add-workspace flow
accepts a GitHub URL and clones it into the workspaces home.

`gh` owns all auth — we never touch tokens. When it isn't logged in,
the UI hands the user `!gh auth login` (an interactive pty thread —
the flow gh itself provides).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

# What a publish must never ship. gitignore semantics: un-ignoring
# inside an ignored DIRECTORY doesn't work, so .curator uses the
# `dir/*` + `!dir/file` pattern pair.
PUBLISH_IGNORES = [
    ".workbench/",
    ".DS_Store",
    ".curator/*",
    "!.curator/profile.md",
    "!.curator/projects.json",
]
VAULT_IGNORE = "vault/"

_IGNORE_HEADER = "# switchbay publish scope (managed block)"

_TIMEOUT = 120  # per git/gh step; pushes of big vaults get longer below
_PUSH_TIMEOUT = 600


class ShareError(Exception):
    """User-visible publish/clone failure."""


async def _run(
    argv: list[str], *, cwd: Path | None = None, timeout: int = _TIMEOUT,
) -> tuple[int, str]:
    """Run one git/gh step; returns (rc, combined output)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        return 127, f"{argv[0]}: not found"
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, f"{' '.join(argv[:2])}: timed out after {timeout}s"
    return proc.returncode or 0, out.decode("utf-8", errors="replace")


def gh_path() -> str | None:
    """Resolve the gh binary. The launchd daemon runs with a minimal
    PATH (no /opt/homebrew/bin) — same trap that bit `uv` — so PATH
    lookup gets explicit fallbacks."""
    p = shutil.which("gh")
    if p:
        return p
    for cand in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh"):
        if Path(cand).is_file():
            return cand
    return None


def gh_available() -> bool:
    return gh_path() is not None


async def status(workspace: Path) -> dict:
    """gh presence/auth + whether the workspace already has an origin
    remote (i.e. was published before / is a clone)."""
    out: dict = {
        "gh": gh_available(),
        "authed": False,
        "has_remote": False,
        "repo_url": None,
    }
    if out["gh"]:
        rc, _ = await _run([gh_path() or "gh", "auth", "status"])
        out["authed"] = rc == 0
    rc, remote = await _run(
        ["git", "-C", str(workspace), "remote", "get-url", "origin"],
    )
    if rc == 0 and remote.strip():
        out["has_remote"] = True
        url = remote.strip().splitlines()[0]
        # normalise ssh form for display
        m = re.match(r"git@github\.com:(.+?)(\.git)?$", url)
        out["repo_url"] = f"https://github.com/{m.group(1)}" if m else url.removesuffix(".git")
    return out


def _managed_ignore_block(include_vault: bool) -> str:
    lines = [_IGNORE_HEADER, *PUBLISH_IGNORES]
    if not include_vault:
        lines.append(VAULT_IGNORE)
    return "\n".join(lines) + "\n# end switchbay block\n"


def write_ignore(workspace: Path, *, include_vault: bool) -> None:
    """Create/refresh the managed block in .gitignore (user lines
    outside the block are preserved)."""
    p = workspace / ".gitignore"
    existing = ""
    if p.is_file():
        existing = p.read_text(encoding="utf-8")
        block_re = re.compile(
            re.escape(_IGNORE_HEADER) + r".*?# end switchbay block\n?",
            re.DOTALL,
        )
        existing = block_re.sub("", existing).rstrip()
        if existing:
            existing += "\n\n"
    p.write_text(existing + _managed_ignore_block(include_vault), encoding="utf-8")


# ── Publish preview (what leaves the machine) ──────────────────────
# `git add -A` ships the WHOLE workspace tree (minus the managed
# ignores). A user who dropped source docs, exports, or notes with an
# embedded credential into the workspace won't anticipate that blast
# radius — especially on a public repo. Before the push we compute the
# exact file set and scan text files for secret-shaped strings so the
# UI can show a preview + a warning.

_SKIP_DIR_NAMES = {".git", ".workbench", "__pycache__", "node_modules"}
_SCAN_MAX_BYTES = 1_000_000       # don't read big/binary blobs
_SCAN_MAX_FILES = 5_000           # bound the walk on huge workspaces
_TEXT_SUFFIXES = {
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".env", ".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".csv", ".html",
    ".xml", ".sql", ".conf", ".properties", ".pem", ".key", "",
}

# (name, compiled regex). Ordered most-specific first.
_SECRET_PATTERNS = [
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}")),
    ("openai key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("xai key", re.compile(r"\bxai-[A-Za-z0-9]{20,}\b")),
    ("github token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("github pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google api key", re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b")),
    ("aws access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack webhook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]+")),
    ("bearer token", re.compile(r"[Bb]earer\s+[A-Za-z0-9._-]{20,}")),
    ("generic api key", re.compile(
        r"(?i)(?:api[_-]?key|secret|token|password)\s*[:=]\s*"
        r"['\"][A-Za-z0-9/_+=.-]{16,}['\"]")),
]


def _is_published(rel: str, *, include_vault: bool) -> bool:
    """Mirror the managed .gitignore scope for a workspace-relative
    POSIX path. Not a full gitignore engine — it enforces OUR rules
    (the security-relevant ones); a user's own .gitignore is applied by
    git at push time on top of this."""
    first = rel.split("/", 1)[0]
    if first in _SKIP_DIR_NAMES or first == ".DS_Store" or rel.endswith("/.DS_Store"):
        return False
    if first == ".curator":
        return rel in (".curator/profile.md", ".curator/projects.json")
    if not include_vault and first == "vault":
        return False
    return True


def preview(workspace: Path, *, include_vault: bool) -> dict:
    """Walk the tree applying the publish scope; return a summary of what
    would ship + any secret-shaped matches. Pure/synchronous — callers
    run it via to_thread."""
    files: list[tuple[str, int]] = []
    dir_counts: dict[str, int] = {}
    secret_hits: list[dict] = []
    truncated = False
    for root, dirs, names in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIR_NAMES]
        rootp = Path(root)
        for nm in names:
            fp = rootp / nm
            try:
                rel = fp.relative_to(workspace).as_posix()
            except ValueError:
                continue
            if not _is_published(rel, include_vault=include_vault):
                continue
            if len(files) >= _SCAN_MAX_FILES:
                truncated = True
                break
            try:
                size = fp.stat().st_size
            except OSError:
                continue
            files.append((rel, size))
            top = rel.split("/", 1)[0] if "/" in rel else "(root)"
            dir_counts[top] = dir_counts.get(top, 0) + 1
            _scan_secrets(fp, rel, size, secret_hits)
        if truncated:
            break
    files.sort(key=lambda t: t[1], reverse=True)
    top_dirs = sorted(dir_counts.items(), key=lambda t: t[1], reverse=True)
    return {
        "file_count": len(files),
        "truncated": truncated,
        "top_dirs": [{"dir": d, "files": n} for d, n in top_dirs[:12]],
        "largest": [{"path": p, "bytes": b} for p, b in files[:8]],
        "secret_hits": secret_hits[:50],
    }


def _scan_secrets(fp: Path, rel: str, size: int, out: list[dict]) -> None:
    if size > _SCAN_MAX_BYTES or len(out) >= 50:
        return
    if fp.suffix.lower() not in _TEXT_SUFFIXES:
        return
    try:
        text = fp.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        return  # binary or unreadable → skip
    for lineno, line in enumerate(text.splitlines(), 1):
        for label, rx in _SECRET_PATTERNS:
            if rx.search(line):
                out.append({"path": rel, "line": lineno, "kind": label})
                if len(out) >= 50:
                    return
                break  # one hit per line is enough


async def publish(
    workspace: Path,
    *,
    name: str,
    private: bool,
    include_vault: bool,
) -> str:
    """Publish (or update) the workspace repo. Returns the repo URL.
    Raises ShareError with the failing step's output."""
    if not gh_available():
        raise ShareError("GitHub CLI not found — install it (`brew install gh`) and retry")
    rc, out = await _run([gh_path() or "gh", "auth", "status"])
    if rc != 0:
        raise ShareError("gh isn't logged in — run `gh auth login` in a shell thread first")

    ws = str(workspace)
    if not (workspace / ".git").is_dir():
        rc, out = await _run(["git", "-C", ws, "init"])
        if rc != 0:
            raise ShareError(f"git init failed:\n{out}")
    await asyncio.to_thread(write_ignore, workspace, include_vault=include_vault)
    if include_vault:
        # git doesn't track empty dirs — an empty (or sparsely
        # populated) vault would vanish from clones, and CM's merge
        # refuses a workspace without vault/. A .gitkeep makes the
        # dir survive the round-trip. (Vault-less publishes are a
        # supported CM shape — hydrate-vault exists for them — and
        # our clone path recreates vault/ locally either way.)
        def _keep() -> None:
            v = workspace / "vault"
            v.mkdir(exist_ok=True)
            (v / ".gitkeep").touch()
        await asyncio.to_thread(_keep)
    rc, out = await _run(["git", "-C", ws, "add", "-A"], timeout=_PUSH_TIMEOUT)
    if rc != 0:
        raise ShareError(f"git add failed:\n{out}")
    rc, out = await _run(
        ["git", "-C", ws, "commit", "-m", "switchbay publish"],
    )
    # rc 1 with "nothing to commit" is fine (re-publish, no changes).
    if rc != 0 and "nothing to commit" not in out:
        raise ShareError(f"git commit failed:\n{out}")

    rc, _ = await _run(["git", "-C", ws, "remote", "get-url", "origin"])
    if rc != 0:
        vis = "--private" if private else "--public"
        rc, out = await _run(
            [gh_path() or "gh", "repo", "create", name, "--source", ws, "--push", vis],
            timeout=_PUSH_TIMEOUT,
        )
        if rc != 0:
            raise ShareError(f"gh repo create failed:\n{out}")
    else:
        rc, out = await _run(
            ["git", "-C", ws, "push", "-u", "origin", "HEAD"],
            timeout=_PUSH_TIMEOUT,
        )
        if rc != 0:
            raise ShareError(f"git push failed:\n{out}")

    # Discovery topic + URL — best-effort (the push already succeeded).
    await _run([gh_path() or "gh", "repo", "edit", "--add-topic", "curiosity-workspace"], cwd=workspace)
    rc, out = await _run([gh_path() or "gh", "repo", "view", "--json", "url", "-q", ".url"], cwd=workspace)
    if rc == 0 and out.strip().startswith("http"):
        return out.strip().splitlines()[0]
    st = await status(workspace)
    return st["repo_url"] or "(pushed — URL unavailable)"


async def publish_skill(skill_dir: Path, *, name: str, private: bool) -> str:
    """Publish a single skill DIRECTORY as its own GitHub repo, so it
    can be installed with `npx skills add <owner>/<name>`. Tagged with
    the `claude-skill` topic for discoverability. Returns the repo URL.

    Deliberate + local-first: only publishes when the user asks, only
    the skill dir, and after the caller has secret-scanned it. Never
    auto-publishes."""
    if not gh_available():
        raise ShareError("GitHub CLI not found — install it (`brew install gh`) and retry")
    rc, out = await _run([gh_path() or "gh", "auth", "status"])
    if rc != 0:
        raise ShareError("gh isn't logged in — run `gh auth login` in a shell thread first")
    d = str(skill_dir)
    if not (skill_dir / "SKILL.md").is_file():
        raise ShareError("no SKILL.md in the skill directory")
    if not (skill_dir / ".git").is_dir():
        rc, out = await _run(["git", "-C", d, "init"])
        if rc != 0:
            raise ShareError(f"git init failed:\n{out}")
    rc, out = await _run(["git", "-C", d, "add", "-A"], timeout=_PUSH_TIMEOUT)
    if rc != 0:
        raise ShareError(f"git add failed:\n{out}")
    rc, out = await _run(["git", "-C", d, "commit", "-m", "publish skill"])
    if rc != 0 and "nothing to commit" not in out:
        raise ShareError(f"git commit failed:\n{out}")
    rc, _ = await _run(["git", "-C", d, "remote", "get-url", "origin"])
    if rc != 0:
        vis = "--private" if private else "--public"
        rc, out = await _run(
            [gh_path() or "gh", "repo", "create", name, "--source", d, "--push", vis],
            timeout=_PUSH_TIMEOUT)
        if rc != 0:
            raise ShareError(f"gh repo create failed:\n{out}")
    else:
        rc, out = await _run(
            ["git", "-C", d, "push", "-u", "origin", "HEAD"], timeout=_PUSH_TIMEOUT)
        if rc != 0:
            raise ShareError(f"git push failed:\n{out}")
    await _run([gh_path() or "gh", "repo", "edit", "--add-topic", "claude-skill"], cwd=skill_dir)
    rc, out = await _run(
        [gh_path() or "gh", "repo", "view", "--json", "url", "-q", ".url"], cwd=skill_dir)
    if rc == 0 and out.strip().startswith("http"):
        return out.strip().splitlines()[0]
    return "(pushed — URL unavailable)"


# ── Install from URL ───────────────────────────────────────────────

_OWNER_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def looks_like_repo_ref(raw: str) -> bool:
    """True when an Add-workspace input is a GitHub ref rather than a
    local path: full https/ssh URL, or `owner/repo` shorthand."""
    s = raw.strip()
    if s.startswith(("https://github.com/", "http://github.com/", "git@github.com:")):
        return True
    return bool(_OWNER_REPO_RE.match(s)) and not Path(s).expanduser().is_absolute()


def repo_dir_name(raw: str) -> str:
    tail = raw.strip().rstrip("/").split("/")[-1]
    tail = tail.split(":")[-1]
    return tail.removesuffix(".git") or "workspace"


async def clone(raw: str, dest: Path) -> None:
    """Clone a GitHub ref into `dest` — `gh repo clone` when available
    (handles private-repo auth), plain `git clone` otherwise."""
    if dest.exists():
        raise ShareError(f"target already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    ref = raw.strip()
    # gh only helps when it's actually signed in (private-repo auth);
    # unauthenticated gh refuses even public clones, where plain git
    # works fine.
    use_gh = False
    if gh_available():
        rc, _ = await _run([gh_path() or "gh", "auth", "status"])
        use_gh = rc == 0
    if use_gh:
        rc, out = await _run(
            [gh_path() or "gh", "repo", "clone", ref, str(dest)], timeout=_PUSH_TIMEOUT,
        )
    else:
        url = ref if ref.startswith(("http", "git@")) else f"https://github.com/{ref}"
        rc, out = await _run(
            ["git", "clone", url, str(dest)], timeout=_PUSH_TIMEOUT,
        )
    if rc != 0:
        raise ShareError(f"clone failed:\n{out}")
    # Robustness for vault-less publishes (vault opt-out, or an empty
    # vault git dropped): CE tooling and CM's merge expect the dir.
    try:
        (dest / "vault").mkdir(exist_ok=True)
    except OSError:
        pass
