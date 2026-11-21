#!/usr/bin/env python3
"""Local enterprise-graph demo.

Builds three graphs and asks the same tool handlers the rail uses:

* local — this workspace's wiki
* pub — a snapshot of a second wiki, pinned at a git revision
* acme — a live ce-graph/1 server (curiosity-engine's graph_serve.py)
  on a loopback port, with OAuth 2.1 PKCE

Then it writes a fact that cites the live page at that revision and
runs claim lint. A confidential page is refused onto the public snapshot.

No model calls and no paid APIs.

    PYTHONPATH=src python3 scripts/enterprise_graph_demo.py

curiosity-engine is found via CURIOSITY_ENGINE_SCRIPTS or a sibling
checkout at ../curiosity-engine.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from switchbay import claim_lint, tools  # noqa: E402
from switchbay.federation import audit, oauth, outbox  # noqa: E402
from switchbay.federation.mounts import Config, Mount, save  # noqa: E402


def _scripts() -> Path:
    env = (os.environ.get("CURIOSITY_ENGINE_SCRIPTS") or "").strip()
    if env:
        return Path(env)
    candidate = ROOT.parent / "curiosity-engine" / "skills" / "curiosity-engine" / "scripts"
    if (candidate / "graph_serve.py").is_file():
        return candidate
    raise SystemExit(
        "curiosity-engine scripts not found. Set CURIOSITY_ENGINE_SCRIPTS "
        "to the directory that contains graph_serve.py."
    )


def _page(path: Path, body: str, **fm: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for key, value in fm.items():
        lines.append(f"{key}: {value}")
    lines += ["---", "", body]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _commit(repo: Path) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "demo",
        "GIT_AUTHOR_EMAIL": "demo@example.com",
        "GIT_COMMITTER_NAME": "demo",
        "GIT_COMMITTER_EMAIL": "demo@example.com",
    }
    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "pin"], check=True, capture_output=True, env=env)
    rev = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    return rev.stdout.strip()


def main() -> int:
    scripts = _scripts()
    work = Path(tempfile.mkdtemp(prefix="switchbay-enterprise-"))
    os.environ["SWITCHBAY_STATE_DIR"] = str(work / "state")
    try:
        local = work / "workspace"
        _page(local / "wiki" / "concepts" / "local-alloy.md",
              "The workshop alloy is mixed on site.",
              title="Local alloy", type="concept", classification="public")
        public = work / "public-wiki"
        _page(public / "wiki" / "concepts" / "standard.md",
              "The public fastener standard is issue 3.",
              title="Fastener standard", type="concept", classification="public")
        public_rev = _commit(public)
        acme = work / "acme"
        _page(acme / "wiki" / "concepts" / "widget.md",
              "The widget uses a sealed bearing.",
              title="Widget", type="concept", classification="confidential")
        acme_rev = _commit(acme)
        proc = subprocess.Popen(
            [sys.executable, str(scripts / "graph_serve.py"),
             "--wiki", str(acme), "--auth", "dev", "--port", "0",
             "--graph-id", "ceg://kg.example/eng",
             "--classification", "confidential"],
            stdout=subprocess.PIPE, text=True,
        )
        line = proc.stdout.readline() if proc.stdout else ""
        if "listening on" not in line:
            raise SystemExit(f"graph server did not start: {line!r}")
        port = int(line.rsplit(":", 1)[-1])
        save(local, Config(
            mounts=[
                Mount("local", f"ceg://local/{local.name}", "local",
                      write="direct", trust="own", ceiling="restricted"),
                Mount("pub", "ceg://git/example/standard", "snapshot",
                      url=str(public), ref=public_rev, write="propose",
                      trust="external", ceiling="public"),
                Mount("acme", "ceg://kg.example/eng", "live",
                      url=f"http://127.0.0.1:{port}/mcp", auth="dev",
                      write="propose", trust="org", ceiling="confidential"),
            ],
            read_default=["local", "pub", "acme"],
        ))
        token = oauth.obtain(f"http://127.0.0.1:{port}/mcp", "acme")
        if not token:
            raise SystemExit("OAuth PKCE did not return a token")
        found = tools.execute("search_wiki", local, {"query": "alloy fastener sealed bearing", "graphs": "all"})
        graphs = {row["graph"] for row in found["results"]}
        missing = {"local", "pub", "acme"} - graphs
        if missing:
            raise SystemExit(f"search missed {sorted(missing)}: {found}")
        page = tools.execute("read_wiki_page", local, {"page": "acme:concepts/widget"})
        if page.get("rev") != acme_rev:
            raise SystemExit(f"live rev {page.get('rev')} != git {acme_rev}")
        cite = page["citation"]
        _page(local / "wiki" / "facts" / "bearing.md",
              f"The sealed bearing is part of the widget. {cite}",
              title="Sealed bearing", type="fact", classification="confidential")
        violations = claim_lint.lint_path(local)
        if violations:
            raise SystemExit("claim lint failed:\n" + "\n".join(item.format() for item in violations))
        refused = outbox.submit(
            local, mount_id="pub", path="concepts/widget",
            content=(local / "wiki" / "facts" / "bearing.md").read_text(encoding="utf-8"),
            base_rev=public_rev, mode="remote",
        )
        if refused.get("ok"):
            raise SystemExit(f"confidential page was accepted by the public mount: {refused}")
        if not any(row["event"] == "refused_write" for row in audit.read(local)):
            raise SystemExit("refusal was not audited")
        from switchbay.federation.session_label import floor
        label = floor(local)
        if label != "confidential":
            raise SystemExit(f"session label is {label}, expected confidential")
        if not any(row.get("event") == "confidential_read" for row in audit.read(local)):
            raise SystemExit("confidential read was not audited")
        print("ok")
        print(f"session {label}")
        print(f"live rev {acme_rev}")
        print(f"snapshot rev {public_rev}")
        print(f"citation {cite}")
        print("search graphs:", ", ".join(sorted(graphs)))
        return 0
    finally:
        if "proc" in locals():
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
