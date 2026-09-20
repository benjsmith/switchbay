"""Curiosity-engine scripts as Switch Bay tools.

HTTP providers (GitHub Copilot, Anthropic, xAI, local models) have no
shell, so they cannot run CE's ``uv run python3 <skill>/scripts/…``
surface. Copilot additionally sandboxes any shell it *does* spawn, so
the global skill is invisible there.

These tools wrap every CE script the skill documents, running them
in-process via ``cebridge.run_script`` (workspace ``.venv``, pinned
Python). Any model that sees the Switch Bay tool registry can curate
without a CE-aware shell.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from . import ce_host, cebridge, ingest_prep
from .tools import Tool, register

# Scripts CE's SKILL.md names on the bash allowlist, plus the rest of
# the shipped scripts/ tree we wrap. Dynamic listing (below) still
# wins for newly added scripts; this is the documented contract.
_KNOWN_SCRIPTS = (
    "sweep.py", "graph.py", "vault_search.py", "vault_index.py",
    "local_ingest.py", "lint_scores.py", "score_diff.py", "scrub_check.py",
    "naming.py", "tables.py", "figures.py", "query_router.py",
    "epoch_summary.py", "planner.py", "scan.py", "bootstrap.py",
    "restyle.py", "okf_export.py", "code_repo.py", "entity_gate.py",
    "identifier_cache.py", "identifier_resolve.py", "shape_check.py",
    "derived_cache.py", "activity_log.py", "session_brief.py",
    "session_drainer.py", "embedder.py", "projects.py",
    "curate_status.py", "curate_launch.py", "code_capture.py",
)

_UNSAFE_ARG = re.compile(r"[;&|`$<>\n\r]|\$\(")


def _listed_scripts() -> list[str]:
    root = cebridge.ce_root() / "scripts"
    names: list[str] = []
    try:
        for f in sorted(root.iterdir()):
            if f.is_file() and f.suffix == ".py":
                names.append(f.name)
    except OSError:
        return list(_KNOWN_SCRIPTS)
    return names or list(_KNOWN_SCRIPTS)


def _safe_args(raw: Any) -> tuple[list[str], str | None]:
    if raw is None:
        return [], None
    if isinstance(raw, str):
        parts = raw.split()
    elif isinstance(raw, list):
        parts = [str(a) for a in raw]
    else:
        return [], "args must be a string or list of strings"
    out: list[str] = []
    for a in parts:
        if not a:
            continue
        if _UNSAFE_ARG.search(a):
            return [], f"refusing arg with shell metacharacters: {a!r}"
        out.append(a)
    return out, None


def _ce_run(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    from . import permissions
    if permissions.needs_web_consent("ce_run", payload):
        blocked = permissions.web_egress_block_reason(
            workspace, "ce_run", payload,
        )
        if blocked:
            return {"ok": False, "error": blocked}
        if not permissions.invocation_approved():
            return {"ok": False, "error": "web egress denied"}
    script = str(payload.get("script") or "").strip()
    if script.endswith(".sh"):
        return {"error": "use viewer/setup via dedicated Switch Bay actions, not ce_run"}
    if not script.endswith(".py"):
        script = f"{script}.py"
    allowed = set(_listed_scripts()) | set(_KNOWN_SCRIPTS)
    if script not in allowed:
        return {
            "error": f"unknown CE script {script!r}",
            "available": sorted(allowed),
        }
    args, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    timeout = float(payload.get("timeout") or 180)
    timeout = max(15.0, min(timeout, 900.0))
    require_json = payload.get("json", True)
    if isinstance(require_json, str):
        require_json = require_json.lower() not in ("0", "false", "no")
    prep_meta: dict[str, Any] | None = None
    if script == "local_ingest.py":
        args, prep_meta = _with_ingest_prep(workspace, path="", extra=args)
        if args is None:
            return prep_meta
        out = _run_local_ingest(
            workspace, prep_meta, extra_flags=_ingest_extra_flags(args),
            timeout=timeout,
        )
        return out
    out = cebridge.run_script(
        script, args, cwd=workspace, timeout=timeout,
        require_json=bool(require_json),
    )
    return out


def _ce_graph_rebuild(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    del payload
    return cebridge.run_script(
        "graph.py", ["rebuild", "wiki"],
        cwd=workspace, timeout=900.0, require_json=False,
    )


def _ce_graph_retrieve(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    args = ["retrieve", "wiki", query]
    if payload.get("seeds"):
        args.extend(["--seeds", str(int(payload["seeds"]))])
    if payload.get("limit"):
        args.extend(["--limit", str(int(payload["limit"]))])
    if payload.get("hops"):
        args.extend(["--hops", str(int(payload["hops"]))])
    route = str(payload.get("route") or "").strip()
    if route in ("auto", "graph", "blend"):
        args.extend(["--route", route])
    return cebridge.run_script("graph.py", args, cwd=workspace, timeout=180.0)


def _ce_sweep(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    verb = str(payload.get("verb") or payload.get("command") or "scan").strip()
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    extraction = str(payload.get("extraction") or "").strip()
    if extraction:
        extra.extend(["--extraction", extraction])
    json_file = str(payload.get("json_file") or "").strip()
    if json_file:
        extra.extend(["--json-file", json_file])
    tab_page = str(payload.get("tab_page") or "").strip()
    if tab_page:
        extra.extend(["--tab-page", tab_page])
    verdict = payload.get("verdict")
    if verdict is None:
        verdict = payload.get("verdict_json")
    if verdict is not None:
        if isinstance(verdict, (dict, list)):
            raw = json.dumps(verdict)
        else:
            raw = str(verdict)
        extra.extend(["--verdict-json", raw])
    args = [verb, "wiki", *extra]
    return cebridge.run_script(
        "sweep.py", args, cwd=workspace, timeout=180.0, require_json=False,
    )


def _ce_lint(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    args = ["wiki"]
    if payload.get("top"):
        args.extend(["--top", str(int(payload["top"]))])
    if payload.get("minimal"):
        args.append("--minimal")
    return cebridge.run_script("lint_scores.py", args, cwd=workspace, timeout=180.0)


def _ce_vault_index(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    path = str(payload.get("path") or "").strip()
    title = str(payload.get("title") or "").strip()
    args: list[str] = []
    if payload.get("rebuild"):
        args.append("--rebuild")
    if payload.get("reembed"):
        args.append("--reembed")
    if path:
        args.append(path)
        if title:
            args.append(title)
    args.extend(extra)
    return cebridge.run_script("vault_index.py", args, cwd=workspace, timeout=180.0)


_INGEST_VALUE_FLAGS = ("--exts", "--max-files", "--projects")


def _split_ingest_cli(args: list[str]) -> tuple[str, list[str]]:
    """Pull a path out of local_ingest CLI args. Rest is flags."""
    path = ""
    rest: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--file" and i + 1 < len(args):
            path = args[i + 1]
            i += 2
            continue
        if a.startswith("-"):
            rest.append(a)
            if a in _INGEST_VALUE_FLAGS and i + 1 < len(args) and not args[i + 1].startswith("-"):
                rest.append(args[i + 1])
                i += 2
                continue
            i += 1
            continue
        if not path:
            path = a
        else:
            rest.append(a)
        i += 1
    return path, rest


def _with_ingest_prep(
    workspace: Path,
    *,
    path: str,
    extra: list[str],
    source_path_only: bool = False,
) -> tuple[list[str] | None, dict[str, Any]]:
    cli_path, rest = _split_ingest_cli(extra)
    target_path = path or cli_path
    prep = ingest_prep.prepare(workspace, target_path)
    if prep.error:
        return None, {"error": prep.error}
    args = list(prep.ce_args) + rest
    if source_path_only and "--source-path-only" not in args:
        args.append("--source-path-only")
    return args, prep.as_meta()


def _ce_ingest(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    from . import permissions
    if permissions.needs_web_consent("ce_ingest", payload):
        blocked = permissions.web_egress_block_reason(
            workspace, "ce_ingest", payload,
        )
        if blocked:
            return {"ok": False, "error": blocked}
        if not permissions.invocation_approved():
            return {"ok": False, "error": "web egress denied"}
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    path = str(payload.get("path") or payload.get("directory") or "").strip()
    args, meta = _with_ingest_prep(
        workspace,
        path=path,
        extra=extra,
        source_path_only=bool(payload.get("source_path_only")),
    )
    if args is None:
        return meta
    timeout = float(payload.get("timeout") or 300.0)
    timeout = max(15.0, min(timeout, 900.0))
    extra_flags = _ingest_extra_flags(args)
    return _run_local_ingest(
        workspace, meta, extra_flags=extra_flags, timeout=timeout,
    )


def _ingest_extra_flags(args: list[str]) -> list[str]:
    extra: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--file" and i + 1 < len(args):
            i += 2
            continue
        if a.startswith("-"):
            extra.append(a)
            if a in _INGEST_VALUE_FLAGS and i + 1 < len(args) and not args[i + 1].startswith("-"):
                extra.append(args[i + 1])
                i += 2
                continue
            i += 1
            continue
        i += 1
    return extra


def _targets_from_prep(
    workspace: Path, meta: dict[str, Any],
) -> list[str]:
    converted = meta.get("converted")
    if meta.get("staged") and isinstance(converted, list):
        files = [
            str(c.get("staged")) for c in converted
            if isinstance(c, dict) and c.get("staged")
        ]
        if files:
            return files
    args = list(meta.get("ce_args") or [])
    if args[:1] == ["--file"] and len(args) >= 2:
        return [args[1]]
    if args and not str(args[0]).startswith("-"):
        root = Path(args[0])
        if not root.is_absolute():
            root = workspace / args[0]
        if root.is_file():
            return [args[0]]
        if root.is_dir():
            return [
                ingest_prep.rel_to_workspace(workspace, p)
                for p in ingest_prep._iter_source_files(root)
            ]
    drop = workspace / "vault" / "raw"
    if drop.is_dir():
        return [
            ingest_prep.rel_to_workspace(workspace, p)
            for p in ingest_prep._iter_source_files(drop)
        ]
    return []


def _merge_local_ingest(parts: list[dict[str, Any]]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    interpreters: list[list[str]] = []
    considered = 0
    notes: list[str] = []
    for part in parts:
        interp = part.get("interpreter")
        if isinstance(interp, list) and interp:
            interpreters.append([str(x) for x in interp])
        if part.get("note"):
            notes.append(str(part["note"]))
        rows = part.get("results")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    results.append(row)
            considered += int(part.get("considered") or len(rows))
            continue
        if part.get("error"):
            results.append({
                "ok": False,
                "reason": part.get("error"),
                "source_path": part.get("file"),
            })
            considered += 1
            continue
        if part.get("extracted") or part.get("extraction_method"):
            results.append(part)
            considered += 1
    ok_n = sum(1 for r in results if r.get("ok") is True)
    out: dict[str, Any] = {
        "considered": considered or len(results),
        "ok": ok_n,
        "failed": max(0, len(results) - ok_n),
        "results": results,
    }
    if interpreters:
        # Unique, stable order.
        seen: set[tuple[str, ...]] = set()
        uniq: list[list[str]] = []
        for item in interpreters:
            key = tuple(item)
            if key in seen:
                continue
            seen.add(key)
            uniq.append(item)
        out["interpreters"] = uniq
        out["interpreter"] = uniq[0] if len(uniq) == 1 else uniq
    if notes:
        out["note"] = " | ".join(notes)[-1500:]
    return out


def _run_local_ingest(
    workspace: Path,
    meta: dict[str, Any],
    *,
    extra_flags: list[str],
    timeout: float,
) -> dict[str, Any]:
    """Run CE local_ingest per file with the interpreter that has that extractor."""
    files = _targets_from_prep(workspace, meta)
    flags = list(extra_flags)
    deadline = time.monotonic() + timeout
    parts: list[dict[str, Any]] = []
    if not files:
        remain = max(1.0, deadline - time.monotonic())
        py = cebridge.python_for_ingest(workspace, "")
        part = cebridge.run_script(
            "local_ingest.py", list(meta.get("ce_args") or []) + flags,
            cwd=workspace, timeout=remain, python=py,
        )
        if isinstance(part, dict):
            part["interpreter"] = py
            parts.append(part)
    else:
        for rel in files:
            remain = deadline - time.monotonic()
            if remain <= 1.0:
                parts.append({
                    "ok": False, "error": f"ingest timed out after {int(timeout)}s",
                    "file": rel, "interpreter": [],
                })
                continue
            ext = Path(rel).suffix.lower()
            py = cebridge.python_for_ingest(workspace, ext)
            part = cebridge.run_script(
                "local_ingest.py", ["--file", rel, *flags],
                cwd=workspace, timeout=remain, python=py,
            )
            if isinstance(part, dict):
                part["interpreter"] = py
                part["file"] = rel
                parts.append(part)
            else:
                parts.append({
                    "ok": False, "error": "ingest returned non-dict",
                    "file": rel, "interpreter": py,
                })
    out = _merge_local_ingest(parts)
    out["ingest_prep"] = meta
    out["timeout_s"] = timeout
    out["extractor_host"] = cebridge.host_extractor_info()
    if "interpreter" not in out:
        out["interpreter"] = cebridge.python_for_ingest(workspace, "")
    flagged = ingest_prep.flag_raw_pdf_extractions(workspace, out)
    if flagged:
        out["raw_pdf_extractions"] = flagged
        out["warning"] = (
            "extraction looks like raw PDF bytes, not prose. "
            "Current curiosity-engine uses pypdf; re-ingest the PDF "
            "or run pending-multimodal. Do not cite these files."
        )
    return _reject_failed_structured_extracts(workspace, out)


_FAILED_METHOD_RE = re.compile(
    r"^(pptx_failed|xlsx_failed|pypdf_failed|csv_failed)",
    re.I,
)


def _ingest_rows(out: dict[str, Any]) -> list[dict[str, Any]]:
    rows = out.get("results")
    if isinstance(rows, list):
        return [r for r in rows if isinstance(r, dict)]
    return [out] if any(k in out for k in ("extracted", "extraction_method")) else []


def _frontmatter_map(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    meta: dict[str, str] = {}
    for ln in text[3:end].splitlines():
        if ":" not in ln:
            continue
        key, _, val = ln.partition(":")
        key = key.strip()
        if key:
            meta[key] = val.strip()
    return meta


def _row_extract_status(workspace: Path, row: dict[str, Any]) -> tuple[str, str]:
    """Extractor method/quality from the row, else extract frontmatter only."""
    method = str(row.get("extraction_method") or "")
    quality = str(row.get("extraction_quality") or "")
    if method or quality:
        return method, quality
    extracted = str(row.get("extracted") or row.get("extracted_path") or "")
    if not extracted:
        return method, quality
    cand = Path(extracted)
    if not cand.is_absolute():
        cand = workspace / extracted
    try:
        text = cand.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return method, quality
    meta = _frontmatter_map(text)
    return (
        method or str(meta.get("extraction_method") or ""),
        quality or str(meta.get("extraction_quality") or ""),
    )


def _exact_index_paths(workspace: Path, extracted: Path) -> list[str]:
    """Canonical vault-relative and absolute extract paths. No LIKE/globs."""
    out: list[str] = []

    def add(raw: str) -> None:
        if raw and raw not in out:
            out.append(raw)

    add(str(extracted))
    add(extracted.as_posix())
    try:
        resolved = extracted.resolve()
    except OSError:
        resolved = extracted
    add(str(resolved))
    add(resolved.as_posix())
    try:
        rel = resolved.relative_to((workspace / "vault").resolve())
        add(str(rel))
        add(rel.as_posix())
    except (ValueError, OSError):
        pass
    return out


def _deindex_exact_paths(workspace: Path, paths: list[str]) -> None:
    db = workspace / "vault" / "vault.db"
    paths = [p for p in paths if str(p).endswith(".extracted.md")]
    if not db.is_file() or not paths:
        return
    import sqlite3
    with sqlite3.connect(str(db)) as conn:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        for path in paths:
            if "sources" in tables:
                conn.execute("DELETE FROM sources WHERE path = ?", (path,))
            if "source_meta" in tables:
                conn.execute("DELETE FROM source_meta WHERE path = ?", (path,))
            if "embedding_meta" in tables:
                conn.execute("DELETE FROM embedding_meta WHERE path = ?", (path,))
        conn.commit()


def _unlink_failed_extract(workspace: Path, row: dict[str, Any]) -> None:
    raw = str(row.get("extracted") or row.get("extracted_path") or "")
    extra: list[str] = []
    indexed = row.get("indexed")
    if isinstance(indexed, dict) and indexed.get("path"):
        extra.append(str(indexed["path"]))
    cand: Path | None = None
    if raw:
        extra.append(raw)
        extra.append(Path(raw).as_posix())
        cand = Path(raw)
        if not cand.is_absolute():
            cand = workspace / raw
        try:
            resolved = cand.resolve()
            ws = workspace.resolve()
        except OSError:
            cand = None
        else:
            if resolved == ws or ws not in resolved.parents:
                cand = None
            elif not resolved.name.endswith(".extracted.md"):
                cand = None
            else:
                cand = resolved
    paths = list(extra)
    if cand is not None:
        for p in _exact_index_paths(workspace, cand):
            if p not in paths:
                paths.append(p)
        _deindex_exact_paths(workspace, paths)
        try:
            if cand.is_file():
                cand.unlink()
        except OSError:
            pass
        return
    _deindex_exact_paths(workspace, paths)


def _row_failed_extract(workspace: Path, row: dict[str, Any]) -> str | None:
    if row.get("ok") is False:
        return str(row.get("reason") or row.get("error") or "ingest failed")
    method, quality = _row_extract_status(workspace, row)
    if quality == "failed" or _FAILED_METHOD_RE.match(method):
        return f"extraction failed ({method or quality})"
    if quality == "empty" and (
        method.startswith(("python-pptx", "openpyxl", "pptx", "xlsx"))
        or method.startswith(("pptx_failed", "xlsx_failed"))
    ):
        return "extraction produced no content"
    return None


def _reject_failed_structured_extracts(
    workspace: Path, out: dict[str, Any],
) -> dict[str, Any]:
    """Refuse metadata-only / unavailable-placeholder success.

    CE ``local_ingest.py`` still writes ``.extracted.md`` and ``ok: true``
    when python-pptx is missing or the PPTX is corrupt. Switch Bay treats
    that as a retryable failure and removes the placeholder extract so it
    is not accepted as ingested content. User vaults are not rewritten
    except for extracts produced by this call.
    """
    if out.get("error") and "results" not in out:
        out.setdefault("retryable", True)
        return out
    rows = _ingest_rows(out)
    failed: list[dict[str, Any]] = []
    ok_rows: list[dict[str, Any]] = []
    for row in rows:
        reason = _row_failed_extract(workspace, row)
        if reason:
            _unlink_failed_extract(workspace, row)
            failed.append({**row, "reject_reason": reason})
        elif row.get("ok") is False:
            failed.append(row)
        else:
            ok_rows.append(row)
    if not failed:
        return out
    out = dict(out)
    out["failed_extractions"] = failed
    out["results"] = ok_rows
    out["failed"] = len(failed)
    if not ok_rows:
        reason = failed[0].get("reject_reason") or failed[0].get("reason") or (
            "extraction failed"
        )
        out["ok"] = False
        out["error"] = str(reason)
        out["retryable"] = True
        return out
    out["ok"] = len(ok_rows)
    warn = out.get("warning") or ""
    extra = (
        f"{len(failed)} file(s) failed structured extraction and were not "
        "accepted. Re-ingest those sources once the file is readable."
    )
    out["warning"] = f"{warn} {extra}".strip() if warn else extra
    return out


def ingest_is_success(out: dict[str, Any] | None) -> bool:
    """True when CE ingest produced accepted extracted content."""
    if not isinstance(out, dict):
        return False
    if out.get("error"):
        return False
    if out.get("ok") is False:
        return False
    if isinstance(out.get("ok"), int) and out["ok"] <= 0:
        return False
    if out.get("retryable") and out.get("failed_extractions") and not _ingest_rows(out):
        return False
    return True


def _ce_query(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    verb = str(payload.get("verb") or "introspect").strip()
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    q = str(payload.get("query") or "").strip()
    args = [verb]
    if q:
        args.append(q)
    args.extend(extra)
    return cebridge.run_script("query_router.py", args, cwd=workspace, timeout=120.0)


def _ce_score_diff(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    page = str(payload.get("page") or "").strip()
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    if not page:
        return {"error": "page is required"}
    new_text = payload.get("new_text")
    new_file = str(payload.get("new_text_file") or payload.get("new_file") or "").strip()
    if new_text is not None and str(new_text):
        tmp = ce_host.write_temp(workspace, ".tmp-score-diff.md", str(new_text))
        extra.extend(["--new-text-file", str(tmp)])
    elif new_file:
        extra.extend(["--new-text-file", new_file])
    vault_db = workspace / "vault" / "vault.db"
    if vault_db.is_file() and "--vault-db" not in extra:
        extra.extend(["--vault-db", str(vault_db)])
    args = [page, *extra]
    if payload.get("new_page"):
        args.append("--new-page")
    return cebridge.run_script("score_diff.py", args, cwd=workspace, timeout=120.0)


def _ce_scrub_check(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "wiki").strip()
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    path = str(payload.get("path") or "").strip()
    args = ["--mode", mode]
    if path:
        args.append(path)
    args.extend(extra)
    return cebridge.run_script("scrub_check.py", args, cwd=workspace, timeout=60.0)


def _ce_naming(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    out = cebridge.run_script("naming.py", extra, cwd=workspace, timeout=30.0)
    if isinstance(out, dict):
        for key in ("stem", "citation_stem", "name"):
            val = out.get(key)
            if isinstance(val, str):
                out[key] = ingest_prep.dedupe_citation_stem(val)
    return out


def _ce_tables(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    verb = str(payload.get("verb") or "list").strip()
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    return cebridge.run_script("tables.py", [verb, *extra], cwd=workspace, timeout=120.0)


def _ce_figures(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    verb = str(payload.get("verb") or "list").strip()
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    args = [verb, *extra]
    if verb in ("check", "list", "regen") and "wiki" not in args:
        args.append("wiki")
    return cebridge.run_script("figures.py", args, cwd=workspace, timeout=180.0)


def _ce_epoch_summary(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    args = extra if extra else ["wiki"]
    return cebridge.run_script("epoch_summary.py", args, cwd=workspace, timeout=180.0)


def _ce_planner(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    verb = str(payload.get("verb") or "pick-mode").strip()
    args = [verb, *extra]
    if "--wiki" not in args:
        args.extend(["--wiki", "wiki"])
    return cebridge.run_script("planner.py", args, cwd=workspace, timeout=60.0)


def _ce_scan(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    verb = str(payload.get("verb") or "all").strip()
    args = [verb, *extra]
    if "--workspace" not in args:
        args.extend(["--workspace", str(workspace)])
    return cebridge.run_script("scan.py", args, cwd=workspace, timeout=180.0)


_SCRIPT_BLURB = (
    "Available scripts (pass as `script`): "
    + ", ".join(_KNOWN_SCRIPTS)
    + ". Common verbs: sweep.py scan|fix-index|fix-source-stubs|"
    "promote-extracted-tables|pending-numeric-review|apply-numeric-review|"
    "multimodal-table-candidates|write-extracted-tables|"
    "mark-multimodal-extracted|figure-candidates|pending-multimodal|"
    "annotate-cross-table-conflicts; "
    "graph.py rebuild|retrieve|neighbors|path|shared-sources|bridge-candidates|"
    "link-candidates|embed; query_router.py introspect|sql|cypher|classify; "
    "tables.py list|query|schema|sync|insert|update|cross-table-conflicts|"
    "extracted-query|list-backups|restore-backup|audit|risk; "
    "figures.py list|check|regen|render-all|mark-extracted; naming.py; "
    "local_ingest.py; vault_index.py; lint_scores.py; score_diff.py; "
    "scrub_check.py; epoch_summary.py; planner.py pick-mode; scan.py all."
)


register(Tool(
    name="ce_run",
    description=(
        "Run any curiosity-engine script against this workspace. Use this "
        "instead of a shell — Copilot/HTTP sandboxes cannot see "
        "~/.agents/skills. " + _SCRIPT_BLURB
    ),
    input_schema={
        "type": "object",
        "required": ["script"],
        "properties": {
            "script": {"type": "string", "description": "CE script name, e.g. sweep.py"},
            "args": {
                "description": "Arguments after the script (string or list).",
            },
            "json": {"type": "boolean", "description": "Expect JSON stdout (default true)."},
            "timeout": {"type": "number", "description": "Seconds (default 180, cap 900)."},
        },
    },
    handler=_ce_run,
))

register(Tool(
    name="ce_graph_rebuild",
    description=(
        "Rebuild the kuzu knowledge graph from wiki pages on disk "
        "(CE graph.py rebuild wiki). Run after authoring or accepting "
        "pages so [[wikilink]] edges appear. Idempotent."
    ),
    input_schema={"type": "object", "properties": {}},
    handler=_ce_graph_rebuild,
))

register(Tool(
    name="ce_graph_retrieve",
    description=(
        "Primary CE retrieval: semantic seed → multi-hop graph expansion "
        "(graph.py retrieve). Prefer this over raw vault_search for "
        "named-entity / 'what do we know about X' questions."
    ),
    input_schema={
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string"},
            "seeds": {"type": "integer"},
            "limit": {"type": "integer"},
            "hops": {"type": "integer"},
            "route": {"type": "string", "enum": ["auto", "graph", "blend"]},
        },
    },
    handler=_ce_graph_retrieve,
))

register(Tool(
    name="ce_sweep",
    description=(
        "CE sweep.py. Hygiene: scan, fix-index, fix-source-stubs, "
        "fix-citation-paths, promote-extracted-tables, sync-notes, "
        "sync-todos. CURATE queues/persist: pending-numeric-review, "
        "apply-numeric-review, multimodal-table-candidates, "
        "write-extracted-tables, mark-multimodal-extracted, "
        "pending-multimodal, figure-candidates, "
        "annotate-cross-table-conflicts, concept-candidates, "
        "evidence-candidates, orphan-sources. Always adds wiki as "
        "the positional target. For apply-numeric-review pass "
        "tab_page + verdict (JSON object or string)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "verb": {"type": "string", "description": "sweep.py subcommand (default scan)."},
            "args": {"description": "Extra args after `wiki`."},
            "extraction": {"type": "string", "description": "--extraction path"},
            "json_file": {"type": "string", "description": "--json-file path"},
            "tab_page": {"type": "string", "description": "--tab-page for apply-numeric-review"},
            "verdict": {"type": "string", "description": "apply-numeric-review JSON (stringified object ok)"},
        },
    },
    handler=_ce_sweep,
))

register(Tool(
    name="ce_lint",
    description="Wiki health scores (lint_scores.py). Higher = worse.",
    input_schema={
        "type": "object",
        "properties": {
            "top": {"type": "integer"},
            "minimal": {"type": "boolean"},
        },
    },
    handler=_ce_lint,
))

register(Tool(
    name="ce_vault_index",
    description="Index a vault extraction into vault/vault.db (vault_index.py).",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "title": {"type": "string"},
            "rebuild": {"type": "boolean"},
            "reembed": {"type": "boolean"},
            "args": {},
        },
    },
    handler=_ce_vault_index,
))

register(Tool(
    name="ce_ingest",
    description=(
        "Ingest files into the vault (local_ingest.py). Drop-folder: no "
        "path (vault/raw/). File or directory: pass `path` (a file is "
        "accepted). Large HTML/XML/JSON is staged as readable text so "
        "CE's extract cap indexes content rather than schema; originals "
        "are unchanged. PPTX/XLSX extractors run with the Switch Bay "
        "interpreter (python-pptx / openpyxl); missing-extractor "
        "placeholders are not accepted as success."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "source_path_only": {"type": "boolean"},
            "args": {},
        },
    },
    handler=_ce_ingest,
))

register(Tool(
    name="read_source",
    description=(
        "Read a workspace source file as readable text. Use when a vault "
        "hit is `extraction: snippet`, when you need the original at "
        "`source_path`, or before quoting a cache file. HTML/XML/JSON "
        "are converted the same way as ce_ingest (visible text / "
        "compacted JSON). Path must stay inside the workspace. Never "
        "quote extract frontmatter (extraction, max_extract_bytes, "
        "sha256, ingested_at) as evidence."
    ),
    input_schema={
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative file (vault extract, cache original, or staged text).",
            },
        },
    },
    handler=ingest_prep.read_source,
))

register(Tool(
    name="ce_query",
    description=(
        "Structured/structural queries (query_router.py). Verbs: "
        "introspect, sql, cypher, classify."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "verb": {"type": "string", "enum": ["introspect", "sql", "cypher", "classify"]},
            "query": {"type": "string"},
            "args": {},
        },
    },
    handler=_ce_query,
))

register(Tool(
    name="ce_score_diff",
    description=(
        "CE citation/bloat gate (score_diff.py). Pass new_text; on "
        "accept the script writes the page. Then ce_scrub_check and "
        "ce_wiki_commit. CURATE write path — not propose_wiki_page."
    ),
    input_schema={
        "type": "object",
        "required": ["page"],
        "properties": {
            "page": {"type": "string"},
            "new_text": {"type": "string", "description": "Full page body to gate and write."},
            "new_text_file": {"type": "string"},
            "new_page": {"type": "boolean"},
            "args": {},
        },
    },
    handler=_ce_score_diff,
))

register(Tool(
    name="ce_scrub_check",
    description="Injection/URL scrub (scrub_check.py) on a wiki or vault path.",
    input_schema={
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["wiki", "vault"]},
            "path": {"type": "string"},
            "args": {},
        },
    },
    handler=_ce_scrub_check,
))

register(Tool(
    name="ce_naming",
    description="CE naming helpers (naming.py) — citation_stem, titles, prefixes.",
    input_schema={"type": "object", "properties": {"args": {}}},
    handler=_ce_naming,
))

register(Tool(
    name="ce_tables",
    description=(
        "Class-table store (tables.py). Verbs: list, schema, query, "
        "sync, insert, update, cross-table-conflicts, extracted-query, "
        "extracted-list, list-backups, restore-backup, audit, risk."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "verb": {"type": "string"},
            "args": {},
        },
    },
    handler=_ce_tables,
))

register(Tool(
    name="ce_figures",
    description=(
        "Figure assets (figures.py). Verbs: list, check, regen, "
        "render-all, pages, extract, mark-extracted."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "verb": {"type": "string"},
            "args": {},
        },
    },
    handler=_ce_figures,
))

register(Tool(
    name="ce_epoch_summary",
    description="CURATE plan snapshot (epoch_summary.py wiki).",
    input_schema={"type": "object", "properties": {"args": {}}},
    handler=_ce_epoch_summary,
))

register(Tool(
    name="ce_planner",
    description="CURATE mode picker (planner.py pick-mode --wiki wiki).",
    input_schema={
        "type": "object",
        "properties": {
            "verb": {"type": "string"},
            "args": {},
        },
    },
    handler=_ce_planner,
))

register(Tool(
    name="ce_scan",
    description="Scan registered project-dirs for new/changed files (scan.py).",
    input_schema={
        "type": "object",
        "properties": {
            "verb": {"type": "string"},
            "args": {},
        },
    },
    handler=_ce_scan,
))

register(Tool(
    name="ce_wiki_commit",
    description=(
        "git -C wiki add -A && commit. CE CURATE end-of-wave only. "
        "Message is required; no vault body in the message."
    ),
    input_schema={
        "type": "object",
        "required": ["message"],
        "properties": {
            "message": {"type": "string", "description": "Commit message, e.g. curate: numeric-review"},
        },
    },
    handler=ce_host.wiki_commit,
))

register(Tool(
    name="ce_evolve_guard",
    description=(
        "CE evolve_guard.sh snapshot|check|hash. Snapshot at wave "
        "start; check at wave end. Drift aborts the wave."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "verb": {"type": "string", "enum": ["snapshot", "check", "hash"]},
            "path": {"type": "string", "description": "Snapshot file (default .curator/.guard.snapshot)"},
        },
    },
    handler=ce_host.evolve_guard,
))

register(Tool(
    name="ce_wave_prime",
    description=(
        "CURATE Phase 1 (mechanical): evolve_guard snapshot, scan, "
        "epoch_summary, planner pick-mode. Call at /curate start. "
        "Optional mode overrides pick-mode (tables, figures, numeric, "
        "repair, …). Then execute that mode's Phase 2."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "mode": {"type": "string", "description": "Optional /curate alias or CE wave mode"},
        },
    },
    handler=ce_host.wave_prime,
))

register(Tool(
    name="ce_dispatch_worker",
    description=(
        "Load a CE worker template from .curator/prompts.md and fill "
        "it. Roles: figure_extractor, scientific_table_extractor, "
        "numeric_transcription_review, batch_reviewer, link_proposer, "
        "link_classifier, worker, notes_curator, summary_table_builder. "
        "VS Code: spawn the named Copilot agent with the returned prompt. "
        "PWA: the host runs a fresh-context child run (read tools) when a "
        "non-local provider is keyed; local stays in-session."
    ),
    input_schema={
        "type": "object",
        "required": ["role"],
        "properties": {
            "role": {"type": "string"},
            "brief": {"type": "string"},
            "substitutions": {
                "type": "string",
                "description": "JSON object of <PLACEHOLDER> → value",
            },
        },
    },
    handler=ce_host.dispatch_worker,
))

MECHANICAL_SWEEP_VERBS: tuple[str, ...] = (
    "scan",
    "fix-index",
    "fix-source-stubs",
    "sync-notes",
    "sync-todos",
)


def _preview_sweep_out(out: Any) -> str:
    if not isinstance(out, dict):
        return str(out)[:400]
    if out.get("error"):
        return str(out["error"])[:200]
    for key in ("stdout", "text", "summary", "result"):
        val = out.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:400]
        if isinstance(val, dict):
            return json.dumps(val, default=str)[:400]
    slim = {k: v for k, v in out.items() if k not in ("ok", "note")}
    if not slim:
        return ""
    return json.dumps(slim, default=str)[:400]


def mechanical_hygiene(
    workspace: Path,
    *,
    verbs: tuple[str, ...] = MECHANICAL_SWEEP_VERBS,
) -> dict[str, Any]:
    """Run deterministic sweep.py verbs (no LLM). Safe to call at
    /curate start. Failures are recorded; later verbs still run."""
    steps: list[dict[str, Any]] = []
    for verb in verbs:
        try:
            out = _ce_sweep(workspace, {"verb": verb})
        except Exception as exc:  # noqa: BLE001
            steps.append({
                "verb": verb, "ok": False, "error": str(exc)[:200],
                "preview": "",
            })
            continue
        err = None
        if isinstance(out, dict):
            err = out.get("error")
        steps.append({
            "verb": verb,
            "ok": not err,
            "error": (str(err)[:200] if err else None),
            "preview": _preview_sweep_out(out if isinstance(out, dict) else {}),
        })
    return {
        "ok": all(s["ok"] for s in steps),
        "steps": steps,
    }


# Public list for tests / ALLOWED_TOOLS sync.
CE_TOOL_NAMES = (
    "ce_run",
    "ce_graph_rebuild",
    "ce_graph_retrieve",
    "ce_sweep",
    "ce_lint",
    "ce_vault_index",
    "ce_ingest",
    "ce_query",
    "ce_score_diff",
    "ce_scrub_check",
    "ce_naming",
    "ce_tables",
    "ce_figures",
    "ce_epoch_summary",
    "ce_planner",
    "ce_scan",
    "ce_wiki_commit",
    "ce_evolve_guard",
    "ce_wave_prime",
    "ce_dispatch_worker",
)
