"""First-run seeding of the bundled demo workspace.

`make install` registers a launchd/systemd job that serves the repo
checkout itself as the workspace (`serve --workspace <repo>`). A clone
has no `wiki/`, so the very first launch used to land on an empty
workspace: no graph, no pages, the walkthrough's graph steps showing
nothing, and the FirstRunWizard modal firing immediately.

`samples/ml-walkthrough/` ships a curated ML corpus for exactly this
moment but nothing referenced it. This module copies it into the user's
workspace area on first run and registers it, so a fresh install opens
on a populated wiki.

Deliberate properties:

* **Once.** A marker in the config dir means a user who deletes or moves
  the demo doesn't get it silently restored on the next boot.
* **Never clobbers.** If the destination already exists we adopt it
  rather than overwrite — the user may have curated it.
* **Copied, not symlinked.** It becomes theirs: editable, curatable,
  and safe to delete without touching the install.
* **Fail-soft.** Any error leaves the daemon booting on its original
  workspace. A missing demo is a worse first run, not a broken one.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from . import workspaces

log = logging.getLogger(__name__)

DEMO_DIRNAME = "ml-walkthrough"
# `~/Workspaces` is the convention the sample's own README suggests and
# where existing curiosity-engine workspaces live.
WORKSPACES_ROOT = "Workspaces"


def bundled_source() -> Path:
    """The demo shipped inside the checkout (repo/samples/<name>)."""
    return Path(__file__).resolve().parents[2] / "samples" / DEMO_DIRNAME


def seed_target() -> Path:
    return Path.home() / WORKSPACES_ROOT / DEMO_DIRNAME


def marker_path() -> Path:
    """Set once we've seeded (or decided not to). Its presence is what
    stops a deleted demo from reappearing every boot."""
    return workspaces.config_dir() / "demo-seeded"


def already_seeded() -> bool:
    try:
        return marker_path().is_file()
    except OSError:
        return True  # can't tell → don't touch anything


def _mark(note: str) -> None:
    try:
        p = marker_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{note}\n", encoding="utf-8")
    except OSError:
        log.debug("could not write demo-seed marker", exc_info=True)


def has_wiki(path: Path) -> bool:
    return (path / "wiki").is_dir()


def maybe_seed(*, register: bool = True) -> Path | None:
    """Copy + register the bundled demo if this is a fresh install.

    Returns the demo workspace path when one is available to serve
    (freshly seeded or already present), else None. Never raises.
    """
    if already_seeded():
        dest = seed_target()
        return dest if dest.is_dir() and has_wiki(dest) else None

    src = bundled_source()
    if not src.is_dir() or not has_wiki(src):
        # Source-less install (e.g. packaged without samples/). Mark so
        # we don't re-check on every boot.
        _mark("no bundled demo in this install")
        return None

    dest = seed_target()
    try:
        if dest.exists():
            # Pre-existing directory — adopt, never overwrite.
            _mark(f"adopted existing {dest}")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Copy to a temp sibling then rename, so an interrupted copy
            # can't leave a half-populated workspace that looks seeded.
            staging = dest.with_name(dest.name + ".partial")
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            shutil.copytree(src, staging, symlinks=False)
            staging.rename(dest)
            _mark(f"seeded from {src}")
            log.info("seeded bundled demo workspace at %s", dest)
    except OSError:
        log.exception("demo workspace seed failed")
        return None

    if register:
        try:
            workspaces.register(dest, set_active=True)
        except (workspaces.OutsideHomeError, OSError):
            log.exception("could not register demo workspace %s", dest)

    return dest if has_wiki(dest) else None


def should_prefer(launch_workspace: Path) -> bool:
    """Whether the demo should win over the CLI-supplied workspace.

    Only when the launch workspace is not itself a knowledge workspace —
    which is exactly the `serve --workspace <repo-checkout>` case the
    service installs. A user who points the daemon at a real workspace
    keeps it.
    """
    try:
        from . import admin_policy
        if not admin_policy.feature_enabled("demo_workspace"):
            return False
        return not has_wiki(launch_workspace)
    except OSError:
        return False
