"""Pinned copy of a git or OKF bundle, kept outside the workspace."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import statedir
from .mounts import Mount


@dataclass
class Snapshot:
    root: Path
    wiki: Path
    rev: str
    graph_id: str


def _dest(mount: Mount) -> Path:
    digest = hashlib.sha256((mount.graph_id or mount.url).encode()).hexdigest()[:16]
    return statedir.state_root() / "mounts" / digest


def _rev_of(path: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=False, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        out = None
    if out and out.returncode == 0 and out.stdout.strip():
        return out.stdout.strip()
    digest = hashlib.sha256()
    wiki = path / "wiki" if (path / "wiki").is_dir() else path
    for file in sorted(wiki.rglob("*.md")):
        digest.update(file.relative_to(wiki).as_posix().encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()[:16]


def _copy_wiki(src: Path, dest: Path) -> None:
    wiki_src = src / "wiki" if (src / "wiki").is_dir() else src
    wiki_dest = dest / "wiki"
    if wiki_dest.exists():
        shutil.rmtree(wiki_dest)
    shutil.copytree(wiki_src, wiki_dest, ignore=shutil.ignore_patterns(".git"))


def ensure(workspace: Path, mount: Mount, *, refresh: bool = False) -> Snapshot:
    """Materialise ``mount`` and return the pinned copy.

    A local directory is copied. An https URL is cloned. The copy is
    reused while its revision matches.
    """
    dest = _dest(mount)
    dest.mkdir(parents=True, exist_ok=True)
    source = _materialize_source(mount, dest / "src", refresh=refresh)
    rev = mount.ref if _looks_like_sha(mount.ref) else _rev_of(source)
    marker = dest / "rev"
    if refresh or not marker.is_file() or marker.read_text(encoding="utf-8").strip() != rev or not (dest / "wiki").is_dir():
        _copy_wiki(source, dest)
        marker.write_text(rev + "\n", encoding="utf-8")
        (dest / "graph-id").write_text((mount.graph_id or "") + "\n", encoding="utf-8")
        _lock_tree(dest)
    return Snapshot(root=dest, wiki=dest / "wiki", rev=rev, graph_id=mount.graph_id)


def _lock_tree(root: Path) -> None:
    """Owner-only mode bits, matching the other per-user caches."""
    from . import secure
    secure.owner_dir(root)
    for dirpath, _dirnames, filenames in os.walk(root):
        secure.owner_dir(Path(dirpath))
        for name in filenames:
            try:
                (Path(dirpath) / name).chmod(0o600)
            except OSError:
                pass


def pinned(workspace: Path, mount: Mount) -> Snapshot | None:
    dest = _dest(mount)
    marker = dest / "rev"
    wiki = dest / "wiki"
    if not marker.is_file() or not wiki.is_dir():
        return None
    return Snapshot(
        root=dest, wiki=wiki, rev=marker.read_text(encoding="utf-8").strip(),
        graph_id=mount.graph_id,
    )


def _looks_like_sha(ref: str) -> bool:
    return len(ref) in (12, 40) and all(c in "0123456789abcdef" for c in ref.lower())


def _materialize_source(mount: Mount, dest: Path, *, refresh: bool) -> Path:
    url = mount.url
    local = Path(url).expanduser()
    if local.is_dir():
        return local.resolve()
    if not url.startswith(("https://", "http://", "git@", "file://")):
        raise ValueError(f"snapshot url is not a git remote or a directory: {url}")
    if dest.is_dir() and (dest / ".git").is_dir() and not refresh:
        return dest
    if dest.exists():
        shutil.rmtree(dest)
    cmd = ["git", "clone", "--depth", "1"]
    if mount.ref and not _looks_like_sha(mount.ref):
        cmd += ["--branch", mount.ref]
    cmd += [url, str(dest)]
    out = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise ValueError(f"could not fetch snapshot: {out.stderr.strip() or out.stdout.strip()}")
    if mount.ref and _looks_like_sha(mount.ref):
        fetched = subprocess.run(
            ["git", "-C", str(dest), "fetch", "--depth", "1", "origin", mount.ref],
            check=False, capture_output=True, text=True, timeout=60,
        )
        if fetched.returncode != 0:
            raise ValueError(f"could not fetch revision {mount.ref}")
        subprocess.run(
            ["git", "-C", str(dest), "checkout", mount.ref],
            check=True, capture_output=True, text=True, timeout=30,
        )
    return dest


def read_page(snap: Snapshot, path: str) -> dict | None:
    rel = path.strip().lstrip("/")
    if rel.endswith(".md"):
        rel = rel[:-3]
    file = (snap.wiki / f"{rel}.md").resolve()
    try:
        file.relative_to(snap.wiki.resolve())
    except ValueError:
        return None
    if not file.is_file():
        stem = Path(rel).name.casefold()
        for cand in snap.wiki.rglob("*.md"):
            if cand.stem.casefold() == stem:
                file = cand
                rel = cand.relative_to(snap.wiki).as_posix()[:-3]
                break
        else:
            return None
    text = file.read_text(encoding="utf-8", errors="replace")
    title, ptype, label = _meta(text)
    return {
        "path": rel,
        "title": title or Path(rel).stem,
        "type": ptype,
        "content": text,
        "classification": label,
        "rev": snap.rev,
        "graph_id": snap.graph_id,
    }


def search(snap: Snapshot, query: str, limit: int) -> list[dict]:
    import re
    terms = [t.casefold() for t in re.findall(r"\w{2,}", query or "")]
    hits = []
    for file in sorted(snap.wiki.rglob("*.md")):
        text = file.read_text(encoding="utf-8", errors="replace")
        low = text.casefold()
        score = 0
        first = -1
        stem = file.stem.casefold()
        for term in terms:
            n = low.count(term)
            if not n:
                continue
            score += min(n, 10)
            if term in stem:
                score += 25
            if first < 0:
                first = low.find(term)
        if terms and score == 0:
            continue
        rel = file.relative_to(snap.wiki).as_posix()
        if rel.endswith(".md"):
            rel = rel[:-3]
        title, ptype, label = _meta(text)
        source_ref = ""
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end > 0:
                for line in text[4:end].splitlines():
                    if line.startswith("source_ref:"):
                        source_ref = line.split(":", 1)[1].strip()
        start = max(0, first if first >= 0 else 0)
        hits.append({
            "path": rel,
            "title": title or file.stem,
            "type": ptype,
            "score": score or 1,
            "snippet": " ".join(text[start:start + 180].split()),
            "classification": label,
            "rev": snap.rev,
            "source_ref": source_ref,
        })
    hits.sort(key=lambda row: (-row["score"], row["path"]))
    return hits[:limit]


def _meta(text: str) -> tuple[str, str, str]:
    title = ptype = ""
    label = "public"
    if not text.startswith("---"):
        return title, ptype, label
    end = text.find("\n---", 3)
    if end < 0:
        return title, ptype, label
    for line in text[4:end].splitlines():
        if line.startswith("title:"):
            title = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("type:"):
            ptype = line.split(":", 1)[1].strip()
        elif line.startswith("classification:"):
            label = line.split(":", 1)[1].strip().lower()
    return title, ptype, label
