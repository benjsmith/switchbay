"""Skill discovery + loading.

A "skill" is a directory containing a `SKILL.md` with a small
frontmatter + a markdown body. Anthropic's Claude Skills format —
we follow it byte-for-byte so user-global skills under
`~/.claude/skills/` and CE's own `/Users/.../curiosity-engine/SKILL.md`
work without translation.

Discovery roots (scanned in priority order; later wins on name
collision):

  1. `~/.claude/skills/<name>/SKILL.md`        — user-global
  2. `<workspace>/.workbench/skills/<name>/SKILL.md` — workspace
  3. `<workspace>/.workbench/packs/<pack>/skills/<name>/SKILL.md` — pack
  4. `~/.config/switchbay/packs/<pack>/skills/<name>/SKILL.md` — user-global pack

Plus the curiosity-engine repo itself as a single-skill bundle
(its top-level SKILL.md describes the whole tool surface; we
register it as the `curiosity-engine` skill).

Loading model: discovery + listing today (this commit). The
agent's existing system prompt mentions tools rail-default knows
about; making a skill *active* — i.e. injecting its body as
additional system context for the next turn — is a follow-up
once the rail has a per-conversation skill-set state to attach.
For now `get_skill(name).body` returns the full markdown so the
agent can read it via the `load_skill` MCP tool inline.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import cebridge, packstore

log = logging.getLogger("switchbay.skillkit")

SKILL_FILE = "SKILL.md"


_FM_RE = re.compile(r"\A---\s*\n(?P<fm>.*?)\n---\s*\n(?P<body>.*)\Z", re.DOTALL)


@dataclass
class Skill:
    name: str
    description: str
    source: str          # 'user' | 'workspace' | 'pack:<pack-name>' | 'ce'
    path: str            # absolute path to the SKILL.md
    body: str = ""       # markdown body (sans frontmatter)
    when_to_use: str = ""  # extracted from description / frontmatter
    extras: dict[str, str] = field(default_factory=dict)


# ── Roots ───────────────────────────────────────────────────────────


def _user_skills_root() -> Path:
    return Path.home() / ".claude" / "skills"


def _workspace_skills_root(workspace: Path) -> Path:
    return workspace / ".workbench" / "skills"


def _pack_skill_dirs(workspace: Path) -> list[tuple[str, Path]]:
    """`(pack_name, skills_dir)` for every pack that ships skills.

    Each pack contributes two flavours of skill directory, both
    shaped as `<parent>/<skill-name>/SKILL.md` so `_scan_root` can
    walk them uniformly:

      1. `<pack>/skills/` — bundled, declared in the manifest as a
         bare-name string or just dropped in by the pack author.
      2. `<pack>/.fetched-skills/` — populated by
         packstore.fetch_remote_skills() from `github:owner/repo`
         / `git+https://…` refs in the manifest. Each cloned repo
         lives in `.fetched-skills/<safe-id>/` and contains its own
         SKILL.md, matching the bundled shape."""
    out: list[tuple[str, Path]] = []
    for p in packstore.list_packs(workspace):
        pack_dir = Path(str(p.get("path") or ""))
        if not pack_dir.is_dir():
            continue
        pack_name = str(p.get("name") or pack_dir.name)
        bundled = pack_dir / "skills"
        if bundled.is_dir():
            out.append((pack_name, bundled))
        fetched = pack_dir / packstore.FETCHED_SKILLS_DIR
        if fetched.is_dir():
            out.append((f"{pack_name}/remote", fetched))
    return out


# ── Manifest parsing ────────────────────────────────────────────────


def _parse_skill_md(text: str) -> tuple[dict[str, str], str]:
    """Read a SKILL.md. Frontmatter is YAML-ish key/value lines matching
    what Anthropic's skill format actually emits; we don't pull a YAML
    dep for this. Handles **block scalars** (`>`, `>-`, `|`, `|-`, and
    their `+` variants) — real skills wrap long descriptions with
    `description: >-`, which a naive `partition(':')` would read as the
    literal string ">-". Returns (frontmatter dict, body)."""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    fm: dict[str, str] = {}
    lines = m.group("fm").splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            i += 1
            continue
        k, _, v = line.partition(":")
        key_indent = len(line) - len(line.lstrip())
        k = k.strip()
        v = v.strip()
        if k and v and v[0] in "|>" and v.strip("|>+-") == "":
            # Block scalar: collect the more-indented continuation lines.
            folded = v[0] == ">"
            block: list[str] = []
            i += 1
            while i < n:
                nxt = lines[i]
                if nxt.strip() == "":
                    block.append("")
                    i += 1
                    continue
                if (len(nxt) - len(nxt.lstrip())) <= key_indent:
                    break
                block.append(nxt.strip())
                i += 1
            if folded:
                # Folded: join lines with spaces (blank lines would mark
                # paragraph breaks; descriptions are one paragraph).
                v = " ".join(x for x in block if x).strip()
            else:
                v = "\n".join(block).strip()
            fm[k] = v
            continue
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        if k:
            fm[k] = v
        i += 1
    return fm, m.group("body").lstrip()


def _read_skill(skill_md: Path, *, source: str, fallback_name: str) -> Skill | None:
    if not skill_md.is_file():
        return None
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    fm, body = _parse_skill_md(text)
    name = fm.get("name", "").strip() or fallback_name
    description = fm.get("description", "").strip()
    extras = {k: v for k, v in fm.items() if k not in ("name", "description")}
    when_to_use = extras.get("when_to_use") or _extract_when_clause(description)
    return Skill(
        name=name,
        description=description,
        source=source,
        path=str(skill_md),
        body=body,
        when_to_use=when_to_use,
        extras=extras,
    )


def _extract_when_clause(description: str) -> str:
    """Pull a "when to use" hint out of a long description so the
    Agent Dashboard can show a short trigger summary without rendering
    the whole blurb. Heuristic: the first sentence that contains
    "use" / "when" / "trigger". Falls back to the first sentence."""
    if not description:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", description.strip())
    for s in sentences:
        sl = s.lower()
        if "when " in sl or "trigger" in sl or "use this" in sl or "use when" in sl:
            return s
    return sentences[0] if sentences else ""


# ── Public API ──────────────────────────────────────────────────────


def list_skills(workspace: Path) -> list[Skill]:
    """Discover every skill visible to this workspace. Later sources
    override earlier ones on name collision: workspace-installed
    beats user-global, pack-provided beats both (so a project can
    pin specific behaviour by dropping a SKILL.md into
    `.workbench/skills/<name>/`)."""
    by_name: dict[str, Skill] = {}

    # 1. CE repo as a single-skill bundle. Resolve CE's root the same way
    #    cebridge does (env override → bundled global skill → legacy
    #    checkout) so it works on any machine, not a hardcoded path.
    ce_md = cebridge.ce_root() / SKILL_FILE
    sk = _read_skill(ce_md, source="ce", fallback_name="curiosity-engine")
    if sk is not None:
        by_name[sk.name] = sk

    # 2. user-global ~/.claude/skills/<name>/SKILL.md
    for sk in _scan_root(_user_skills_root(), source="user"):
        by_name[sk.name] = sk

    # 3. workspace .workbench/skills/<name>/SKILL.md
    for sk in _scan_root(_workspace_skills_root(workspace), source="workspace"):
        by_name[sk.name] = sk

    # 4. pack-bundled skills (workspace + user-global pack scopes).
    for pack_name, skills_dir in _pack_skill_dirs(workspace):
        for sk in _scan_root(skills_dir, source=f"pack:{pack_name}"):
            by_name[sk.name] = sk

    out = list(by_name.values())
    out.sort(key=lambda s: (s.source, s.name))
    return out


def _scan_root(root: Path, *, source: str) -> list[Skill]:
    if not root.is_dir():
        return []
    out: list[Skill] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        sk = _read_skill(child / SKILL_FILE, source=source, fallback_name=child.name)
        if sk is not None:
            out.append(sk)
    return out


def get_skill(workspace: Path, name: str) -> Skill | None:
    """Look up a single skill by name across all roots; same priority
    order as list_skills."""
    if not name:
        return None
    for sk in list_skills(workspace):
        if sk.name == name:
            return sk
    return None


def to_summary(sk: Skill) -> dict[str, object]:
    """Listing-friendly dict: drops the body to keep the listing API
    cheap. Use get_skill / load_skill (the MCP tool) for the body."""
    return {
        "name": sk.name,
        "description": sk.description,
        "when_to_use": sk.when_to_use,
        "source": sk.source,
        "path": sk.path,
    }


def to_full(sk: Skill) -> dict[str, object]:
    """Full record incl. body. Used by the load_skill MCP tool the
    agent calls when it actually needs the skill's content."""
    return {
        **to_summary(sk),
        "body": sk.body,
        "extras": sk.extras,
        "writable": sk.source in WRITABLE_SOURCES,
    }


# ── Authoring (create / edit / delete / promote) ────────────────────
#
# Skills are just directories with a SKILL.md — so authoring is plain
# file writes, no new store. Only the two USER-OWNED scopes are
# writable: a private per-workspace skill (`workspace`) and a personal
# user-global skill (`user`). CE's bundled skill and pack-provided
# skills are read-only upstream — editing those would fight their
# source of truth, so we refuse. Local-first authoring (workspace →
# personal → publish) is the whole security posture: nothing here ever
# fetches a skill from the web.

WRITABLE_SOURCES = ("workspace", "user")

# Scope → where a new/edited skill's directory lives.
_SCOPES = ("workspace", "user")

# First-party bundled skills are read-only upstream (charter: never
# modify the curiosity-engine repo). They are *symlinked* into
# `~/.claude/skills/` at install, so discovery reports them with
# source="user" even though they are NOT user-authored. Editing one
# would clobber the upstream skill. Belt-and-suspenders: a name
# denylist PLUS a symlink/real-path check (`_is_writable_dir`).
_PROTECTED_NAMES = frozenset({"curiosity-engine", "curiosity-merge"})


class SkillError(Exception):
    """Authoring failure with a human-facing message."""


def _real(p: Path) -> Path:
    try:
        return p.resolve()
    except OSError:
        return p


def _is_writable_dir(workspace: Path, skill_dir: Path) -> bool:
    """True only when `skill_dir` is a REAL directory sitting directly
    inside one of the two writable roots. A symlink (how bundled
    first-party skills are installed) or a dir whose real parent is
    somewhere else (e.g. `~/.agents/skills`, a pack, the CE repo) is
    read-only — editing it would fight its upstream source of truth."""
    if skill_dir.is_symlink():
        return False
    real_parent = _real(skill_dir).parent
    writable_roots = {
        str(_real(_workspace_skills_root(workspace))),
        str(_real(_user_skills_root())),
    }
    return str(real_parent) in writable_roots


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Directory-safe slug for a skill name. Matches the Anthropic
    convention (kebab-case)."""
    s = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return s or "skill"


def _scope_root(workspace: Path, scope: str) -> Path:
    if scope == "workspace":
        return _workspace_skills_root(workspace)
    if scope == "user":
        return _user_skills_root()
    raise SkillError(f"unknown or read-only scope: {scope!r}")


def render_skill_md(name: str, description: str, body: str,
                    extras: dict[str, str] | None = None) -> str:
    """Serialise a SKILL.md. Frontmatter is the minimal name/description
    the loader reads, plus any preserved extras (e.g. metadata:). Values
    are quoted when they contain a colon so the flat parser round-trips."""
    def _fm_val(v: str) -> str:
        v = (v or "").replace("\n", " ").strip()
        return f'"{v}"' if (":" in v or v.startswith(("'", '"'))) else v

    lines = ["---", f"name: {slugify(name)}", f"description: {_fm_val(description)}"]
    for k, v in (extras or {}).items():
        if k in ("name", "description"):
            continue
        lines.append(f"{k}: {_fm_val(str(v))}")
    lines.append("---")
    lines.append("")
    lines.append((body or "").strip() + "\n")
    return "\n".join(lines)


# Broad on purpose — a "weak trigger" is a heuristic, and a false
# positive on a skill that fires fine is worse than a miss (the user
# flagged this). Accept the many natural ways a description signals when
# to fire. The reliable judge is the on-demand model "Test", not this.
_TRIGGER_RE = re.compile(
    r"\buse (?:when|this|for|it)\b|\bwhen (?:the|you|a|an|it|they|user|users|asked|asking|mention)"
    r"|\bwhenever\b|\btrigger|\bhelps? (?:you|the )?users?\b|\bapplies? to\b"
    r"|\bfor (?:when|tasks|building|creating|any)\b|\bauto-?trigger",
    re.I)


def _named_sources(workspace: Path, name: str) -> list[str]:
    """Every scope that defines a skill of `name`, deduped by REAL path
    (later = higher priority / the one that actually fires). Deduping by
    resolved path is load-bearing: bundled first-party skills are
    symlinked into `~/.claude/skills`, so the same SKILL.md is reachable
    as both `ce` (via cebridge) and `user` (via the link) — that is NOT
    a collision and must not be flagged as one."""
    slug = name
    order: list[str] = []
    seen: set[str] = set()

    def _add(md: Path, src: str) -> None:
        try:
            rp = str(md.resolve())
        except OSError:
            rp = str(md)
        if rp not in seen:
            seen.add(rp)
            order.append(src)

    # Mirror list_skills' roots + order (ce < user < workspace < pack).
    try:
        ce_md = cebridge.ce_root() / SKILL_FILE
        sk = _read_skill(ce_md, source="ce", fallback_name="curiosity-engine")
        if sk is not None and sk.name == slug:
            _add(ce_md, "ce")
    except Exception:  # noqa: BLE001
        pass
    for root, src in ((_user_skills_root(), "user"),
                      (_workspace_skills_root(workspace), "workspace")):
        md = root / slug / SKILL_FILE
        if md.exists():
            _add(md, src)
    for pack_name, skills_dir in _pack_skill_dirs(workspace):
        md = skills_dir / slug / SKILL_FILE
        if md.exists():
            _add(md, f"pack:{pack_name}")
    return order


def diagnose(workspace: Path, sk: Skill) -> list[dict[str, str]]:
    """Deterministic "why won't it fire?" checks for one skill. Each is
    `{level: ok|warn|fail, code, message}`. These need no model — they
    catch the common novice failures (weak/absent trigger, shadowing,
    empty body) precisely and for free. The model-judgment half (does a
    given request match?) lives in the daemon explain endpoint."""
    out: list[dict[str, str]] = []

    if not sk.name:
        out.append({"level": "fail", "code": "no-name",
                    "message": "SKILL.md has no `name:` — it won't be discovered."})
    else:
        out.append({"level": "ok", "code": "discoverable",
                    "message": f"Discovered as '{sk.name}' ({sk.source})."})

    if not (sk.description or "").strip():
        out.append({"level": "fail", "code": "no-description",
                    "message": "No description — the agent has nothing to match on. "
                               "Add a 'Use when …' sentence."})
    elif not _TRIGGER_RE.search(sk.description):
        out.append({"level": "warn", "code": "weak-trigger",
                    "message": "The description has no clear trigger. Skills fire "
                               "when the agent matches a 'Use when the user …' "
                               "clause — start the description with one."})
    else:
        out.append({"level": "ok", "code": "has-trigger",
                    "message": "Has a trigger clause."})

    if not (sk.body or "").strip():
        out.append({"level": "warn", "code": "empty-body",
                    "message": "The body is empty — even if it fires, there are no "
                               "instructions to follow."})

    if sk.name:
        srcs = _named_sources(workspace, sk.name)
        if len(srcs) > 1:
            winner = srcs[-1]
            if winner != sk.source:
                out.append({"level": "warn", "code": "shadowed",
                            "message": f"Another '{sk.name}' in {winner} outranks this "
                                       f"{sk.source} one — the agent loads {winner}'s, "
                                       "not this. Rename one of them."})
            else:
                out.append({"level": "warn", "code": "name-collision",
                            "message": f"'{sk.name}' is also defined in "
                                       f"{', '.join(s for s in srcs if s != sk.source)} "
                                       "— this one wins, but the duplicate is confusing."})
    return out


# ── Route skills (a saved /route: task pattern + sub-task split) ────

ROUTE_KIND = "route"
_ROUTE_TASK_RE = re.compile(
    r"^\s*\d+[.)]\s*(?:\[(?P<diff>trivial|normal|hard)\]\s*)?(?P<desc>.+?)\s*$", re.I)


def is_route_skill(sk: Skill) -> bool:
    """A route-skill carries `kind: route` and a parseable sub-task list —
    re-invoking it replays the split instead of loading prose."""
    return (sk.extras.get("kind") or "").strip().lower() == ROUTE_KIND


def route_body(tasks: list[dict[str, Any]]) -> str:
    """Render fan-out tasks (`{description, difficulty}`) into a SKILL.md
    body a route-skill can round-trip through `parse_route_tasks`."""
    lines = ["Route this into parallel sub-tasks across the model ladder.", "",
             "## Sub-tasks"]
    for i, t in enumerate(tasks, 1):
        diff = str(t.get("difficulty") or "normal").lower()
        if diff not in ("trivial", "normal", "hard"):
            diff = "normal"
        lines.append(f"{i}. [{diff}] {str(t.get('description') or '').strip()}")
    lines += ["", "Then merge the sub-task results into a single answer."]
    return "\n".join(lines)


def parse_route_tasks(sk: Skill) -> list[dict[str, Any]] | None:
    """Extract a route-skill's stored sub-tasks (from its `## Sub-tasks`
    section), or None if it isn't a route-skill / has no parseable list."""
    if not is_route_skill(sk):
        return None
    tasks: list[dict[str, Any]] = []
    in_section = False
    for line in (sk.body or "").splitlines():
        low = line.strip().lower()
        if low.startswith("## sub-tasks") or low.startswith("## subtasks"):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            m = _ROUTE_TASK_RE.match(line)
            if m and m.group("desc").strip():
                tasks.append({
                    "description": m.group("desc").strip(),
                    "difficulty": (m.group("diff") or "normal").lower(),
                })
    return tasks or None


def worst_level(diags: list[dict[str, str]]) -> str:
    """The most severe level across diagnostics: fail > warn > ok."""
    levels = {d.get("level") for d in diags}
    if "fail" in levels:
        return "fail"
    if "warn" in levels:
        return "warn"
    return "ok"


def is_writable_skill(workspace: Path, sk: Skill) -> bool:
    """Cheap writability check for a Skill we already hold (no re-scan)."""
    if sk.source not in WRITABLE_SOURCES:
        return False
    if sk.name in _PROTECTED_NAMES:
        return False
    return _is_writable_dir(workspace, Path(sk.path).parent)


def find_writable(workspace: Path, name: str) -> Skill | None:
    """Locate an existing WRITABLE skill by name (workspace or user
    scope only). None if absent, read-only (ce/pack), a protected
    first-party name, or a symlinked/foreign-rooted directory."""
    sk = get_skill(workspace, name)
    if sk is None or sk.source not in WRITABLE_SOURCES:
        return None
    if sk.name in _PROTECTED_NAMES or slugify(name) in _PROTECTED_NAMES:
        return None
    if not _is_writable_dir(workspace, Path(sk.path).parent):
        return None
    return sk


def create_skill(workspace: Path, scope: str, name: str,
                 description: str, body: str,
                 extras: dict[str, str] | None = None) -> Skill:
    """Author a new skill under `scope`. Refuses if a skill of that
    slug already exists in that scope (edit it instead), or if the name
    collides with a read-only CE/pack skill of the same name."""
    if scope not in _SCOPES:
        raise SkillError(f"scope must be one of {_SCOPES}")
    if not (name or "").strip():
        raise SkillError("a skill needs a name")
    slug = slugify(name)
    if slug in _PROTECTED_NAMES:
        raise SkillError(f"'{slug}' is a built-in skill — pick another name")
    root = _scope_root(workspace, scope)
    skill_dir = root / slug
    # A symlink here = a bundled first-party skill linked in; never
    # write through it. A real dir with a SKILL.md = a real collision.
    if skill_dir.is_symlink():
        raise SkillError(f"'{slug}' is a built-in skill — pick another name")
    if (skill_dir / SKILL_FILE).exists():
        raise SkillError(f"a {scope} skill '{slug}' already exists — edit it instead")
    existing = get_skill(workspace, slug)
    if existing is not None and (
            existing.source not in WRITABLE_SOURCES
            or existing.name in _PROTECTED_NAMES):
        raise SkillError(
            f"'{slug}' is a built-in ({existing.source}) skill — pick another name")
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / SKILL_FILE).write_text(
        render_skill_md(slug, description, body, extras), encoding="utf-8")
    sk = _read_skill(skill_dir / SKILL_FILE, source=scope, fallback_name=slug)
    if sk is None:
        raise SkillError("wrote the skill but failed to read it back")
    return sk


def update_skill(workspace: Path, name: str, description: str, body: str,
                 extras: dict[str, str] | None = None) -> Skill:
    """Rewrite an existing writable skill's SKILL.md in place."""
    cur = find_writable(workspace, name)
    if cur is None:
        raise SkillError(f"no editable skill named '{name}' (built-ins are read-only)")
    md = Path(cur.path)
    merged = dict(cur.extras)
    if extras:
        merged.update(extras)
    md.write_text(
        render_skill_md(cur.name, description, body, merged), encoding="utf-8")
    sk = _read_skill(md, source=cur.source, fallback_name=cur.name)
    if sk is None:
        raise SkillError("wrote the skill but failed to read it back")
    return sk


def delete_skill(workspace: Path, name: str) -> bool:
    """Delete a writable skill's directory. Refuses read-only skills.
    Only removes the skill dir (its SKILL.md + any siblings it owns)."""
    import shutil

    cur = find_writable(workspace, name)
    if cur is None:
        raise SkillError(f"no editable skill named '{name}' (built-ins are read-only)")
    skill_dir = Path(cur.path).parent
    # Safety: the dir must sit directly under a known writable root.
    roots = {str(_scope_root(workspace, s).resolve()) for s in _SCOPES}
    if str(skill_dir.parent.resolve()) not in roots:
        raise SkillError("refusing to delete a skill outside the skills roots")
    shutil.rmtree(skill_dir, ignore_errors=True)
    return True


def promote_skill(workspace: Path, name: str) -> Skill:
    """Move a workspace-private skill up to the user-global scope
    (`~/.claude/skills/`), so it's available in every workspace. The
    deliberate 'ready to reuse everywhere' step below publishing."""
    import shutil

    cur = find_writable(workspace, name)
    if cur is None or cur.source != "workspace":
        raise SkillError("promote applies to a workspace-private skill")
    src_dir = Path(cur.path).parent
    dst_dir = _user_skills_root() / src_dir.name
    if (dst_dir / SKILL_FILE).exists():
        raise SkillError(f"a personal skill '{src_dir.name}' already exists")
    dst_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src_dir), str(dst_dir))
    sk = _read_skill(dst_dir / SKILL_FILE, source="user", fallback_name=src_dir.name)
    if sk is None:
        raise SkillError("moved the skill but failed to read it back")
    return sk
