#!/usr/bin/env bash
# Run the workflow suite against two daemons and print a parity table.
#
# PRE is current main (default b3ea541, enterprise controls). POST is
# the checkout you run the script from. Each daemon gets its own port,
# state directory, config directory, and a copy of samples/ml-walkthrough
# with a Reviews tab and one proposed page. No provider API keys are
# forwarded.
#
#   scripts/side-by-side-workflows.sh
#   PRE_REF=5f3d915 POST_PORT=8872 PRE_PORT=8871 scripts/side-by-side-workflows.sh
#
# Writes /tmp/switchbay-parity/table.md and exits non-zero when POST is
# worse than PRE on any workflow.

set -euo pipefail
set -m

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PRE_REF="${PRE_REF:-b3ea541}"
PRE_PORT="${PRE_PORT:-8871}"
POST_PORT="${POST_PORT:-8872}"
WORK="${WORK:-/tmp/switchbay-parity}"
PRE_TREE="${PRE_TREE:-$WORK/pre-tree}"
PY="${PY:-$ROOT/.venv/bin/python}"

unset XAI_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY || true
export PATH="${HOME}/.local/bin:${PATH}"
# The daemon only serves a workspace that resolves under an allowed
# root (home, /workspace, or SWITCHBAY_WORKSPACE_ROOTS). The copies
# for this run live under $WORK.
export SWITCHBAY_WORKSPACE_ROOTS="${SWITCHBAY_WORKSPACE_ROOTS:+$SWITCHBAY_WORKSPACE_ROOTS:}$WORK"

mkdir -p "$WORK"
rm -rf "$WORK/ws-pre" "$WORK/ws-post" "$WORK/state-pre" "$WORK/state-post" \
  "$WORK/config-pre" "$WORK/config-post" "$WORK/shots"
mkdir -p "$WORK/shots/pre" "$WORK/shots/post"

if ! git -C "$ROOT" cat-file -e "${PRE_REF}^{commit}" 2>/dev/null; then
  git -C "$ROOT" fetch origin "$PRE_REF"
fi

if [[ ! -d "$PRE_TREE/.git" && ! -f "$PRE_TREE/.git" ]]; then
  git -C "$ROOT" worktree add --detach "$PRE_TREE" "$PRE_REF"
else
  git -C "$PRE_TREE" checkout --detach "$PRE_REF"
fi

echo "building frontend in $ROOT"
pnpm --dir "$ROOT/frontend" install --frozen-lockfile
pnpm --dir "$ROOT/frontend" exec playwright install chromium
pnpm --dir "$ROOT/frontend" run build

if ! git -C "$ROOT" diff --quiet "$PRE_REF" -- frontend; then
  echo "frontend differs from $PRE_REF; building the pre tree too"
  pnpm --dir "$PRE_TREE/frontend" install --frozen-lockfile
  pnpm --dir "$PRE_TREE/frontend" run build
else
  mkdir -p "$PRE_TREE/frontend"
  rm -rf "$PRE_TREE/frontend/dist"
  cp -a "$ROOT/frontend/dist" "$PRE_TREE/frontend/dist"
fi

python3 - <<PY
import json, shutil
from pathlib import Path
root = Path("$ROOT")
work = Path("$WORK")
sample = root / "samples" / "ml-walkthrough"
for name in ("ws-pre", "ws-post"):
    dest = work / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(sample, dest, ignore=shutil.ignore_patterns(".git"))
    mode = {
        "name": "default",
        "tabs": [
            {"id": "graph", "title": "Graph", "kind": "graph"},
            {"id": "editor", "title": "Editor", "kind": "markdown"},
            {"id": "table", "title": "Table", "kind": "duckdb"},
            {"id": "spreadsheet", "title": "Sheet", "kind": "univer"},
            {"id": "plot", "title": "Plot", "kind": "vega"},
            {"id": "sketch", "title": "Sketch", "kind": "sketch"},
            {"id": "library", "title": "Library", "kind": "library"},
            {"id": "projects", "title": "Projects", "kind": "projects"},
            {"id": "agents", "title": "Agents", "kind": "agents"},
            {"id": "report", "title": "Reviews", "kind": "report", "source": "user", "payload": {}},
        ],
        "model_ladder": {},
    }
    wb = dest / ".workbench"
    (wb / "state").mkdir(parents=True, exist_ok=True)
    (wb / "mode.json").write_text(json.dumps(mode), encoding="utf-8")
    body = (
        "---\nprovenance: untrusted-import\n---\n\n"
        "# Parity concept\n\nUNTRUSTED REMOTE CONTENT\n\n"
        "A seeded review for the workflow suite.\n"
    )
    page = dest / "wiki" / "concepts" / "parity-concept.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(body, encoding="utf-8")
    proposal = [{
        "id": "prop-parity01",
        "op": "create",
        "kind": "concept",
        "title": "Parity concept",
        "path": "wiki/concepts/parity-concept.md",
        "body": body,
        "status": "proposed",
        "created_at": 1,
        "review": {
            "verdict": "pass",
            "confidence": 0.5,
            "issues": [],
            "one_line": "Seeded for the review workflow.",
        },
        "original": None,
        "written": True,
        "scaffold": False,
    }]
    (wb / "state" / "page_proposals.json").write_text(
        json.dumps(proposal), encoding="utf-8")
    (wb / "state" / "classification_queue.json").write_text(json.dumps([{
        "id": "cap-parity",
        "title": "Quick entity",
        "kind": "capture",
        "source": "seed",
        "status": "pending",
        "classification": "",
    }]), encoding="utf-8")
    alt = work / f"{name}-alt"
    if alt.exists():
        shutil.rmtree(alt)
    (alt / "wiki").mkdir(parents=True)
    (alt / "wiki" / "index.md").write_text("# ALT-WORKSPACE\n\nRemote mount page.\n", encoding="utf-8")
    (wb / "graph-mounts.json").write_text(json.dumps({
        "schema": "switchbay-graph-mounts/1",
        "read_default": ["local", "remote"],
        "default_write": "local",
        "mounts": [{
            "id": "remote",
            "graph_id": "remote-wiki",
            "kind": "snapshot",
            "url": str(alt.resolve()),
            "read": True,
            "write": "none",
            "trust": "external",
            "ceiling": "public",
        }],
    }), encoding="utf-8")
print("workspaces ready")
synced = work / "Dropbox" / "inbox" / "wiki"
synced.mkdir(parents=True, exist_ok=True)
(synced / "index.md").write_text("# synced inbox\n", encoding="utf-8")
for side in ("pre", "post"):
    (work / f"admin-{side}.json").write_text(
        json.dumps({"profile": "open"}) + "\n", encoding="utf-8")
PY

for side in pre post; do
  mkdir -p "$WORK/config-$side/switchbay" "$WORK/state-$side"
  touch "$WORK/config-$side/switchbay/walkthrough-shown"
  touch "$WORK/config-$side/switchbay/intro-shown"
  # Session badge reads the floor for the default session id.
  python3 - "$WORK" "$side" <<'PY'
import hashlib, json, sys
from pathlib import Path
work, side = Path(sys.argv[1]), sys.argv[2]
ws = (work / f"ws-{side}").resolve()
digest = hashlib.sha256(str(ws).encode()).hexdigest()[:16]
dest = work / f"state-{side}" / "sessions" / digest
dest.mkdir(parents=True, exist_ok=True)
(dest / "labels.json").write_text(json.dumps({"default": "confidential"}) + "\n", encoding="utf-8")
PY
done

PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
      # Process-group kill: the daemon may have spawned children.
      kill -TERM -- "-$pid" 2>/dev/null || true
    fi
  done
  sleep 1
  for pid in "${PIDS[@]:-}"; do
    kill -KILL "$pid" 2>/dev/null || true
    kill -KILL -- "-$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT

start_daemon() {
  local side="$1" tree="$2" port="$3"
  local ws="$WORK/ws-$side"
  echo "starting $side on :$port ($tree)"
  (
    cd "$tree"
    exec env -u XAI_API_KEY -u OPENAI_API_KEY -u ANTHROPIC_API_KEY \
      SWITCHBAY_STATE_DIR="$WORK/state-$side" \
      SWITCHBAY_ADMIN_POLICY="$WORK/admin-$side.json" \
      XDG_CONFIG_HOME="$WORK/config-$side" \
      PYTHONPATH="$tree/src" \
      "$PY" -m switchbay serve --workspace "$ws" --host 127.0.0.1 --port "$port"
  ) >"$WORK/$side.log" 2>&1 &
  PIDS+=("$!")
}

start_daemon pre "$PRE_TREE" "$PRE_PORT"
start_daemon post "$ROOT" "$POST_PORT"

wait_health() {
  local port="$1" name="$2"
  for _ in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:$port/api/health" >/dev/null; then
      echo "$name healthy on :$port"
      return 0
    fi
    sleep 0.5
  done
  echo "$name did not become healthy; log follows" >&2
  tail -n 80 "$WORK/$name.log" >&2 || true
  return 1
}

wait_health "$PRE_PORT" pre
wait_health "$POST_PORT" post

run_suite() {
  local side="$1" port="$2"
  local out="$WORK/$side.json"
  echo "playing workflows against $side (:$port)"
  set +e
  (
    cd "$ROOT/frontend"
    E2E_BASE_URL="http://127.0.0.1:$port" \
      E2E_WORKSPACE="$WORK/ws-$side" \
      E2E_ALT_WORKSPACE="$WORK/ws-$side-alt" \
      E2E_ADMIN_POLICY="$WORK/admin-$side.json" \
      E2E_SYNCED_WORKSPACE="$WORK/Dropbox/inbox" \
      pnpm exec playwright test tests/e2e/workflows.spec.ts \
        --reporter=json --output "$WORK/results-$side"
  ) >"$out"
  local code=$?
  set -e
  # Failure screenshots land in the playwright output dir.
  if [[ -d "$WORK/results-$side" ]]; then
    find "$WORK/results-$side" -name '*.png' -exec cp {} "$WORK/shots/$side/" \; || true
  fi
  echo "$side playwright exit $code"
  return 0
}

run_suite pre "$PRE_PORT"
run_suite post "$POST_PORT"

WORK="$WORK" python3 - <<'PY'
import json, os, sys
from pathlib import Path
work = Path(os.environ["WORK"])

def cases(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    found = []
    def walk(node):
        if isinstance(node, dict):
            specs = node.get("specs")
            if isinstance(specs, list):
                for spec in specs:
                    title = spec.get("title") or ""
                    tests = spec.get("tests") or []
                    status = "missing"
                    if tests:
                        results = tests[0].get("results") or []
                        if results:
                            status = results[-1].get("status") or "unknown"
                        else:
                            status = tests[0].get("status") or "unknown"
                    found.append((title, status))
            for child in node.get("suites") or []:
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(data.get("suites") or [])
    return found

pre = dict(cases(work / "pre.json"))
post = dict(cases(work / "post.json"))
titles = list(dict.fromkeys([*pre, *post]))
worse = []
lines = ["| workflow | pre | post | notes |", "| --- | --- | --- | --- |"]
for title in titles:
    a = pre.get(title, "missing")
    b = post.get(title, "missing")
    note = ""
    if a != b:
        if a == "passed" and b != "passed":
            note = "regression"
            worse.append(title)
        elif b == "passed" and a != "passed":
            note = "improvement"
        else:
            note = "differs"
            if b != "passed":
                worse.append(title)
    elif a != "passed":
        note = "both failed"
        worse.append(title)
    else:
        note = "parity"
    lines.append(f"| {title} | {a} | {b} | {note} |")
text = "\n".join(lines) + "\n"
(work / "table.md").write_text(text, encoding="utf-8")
print(text)
print(f"workflows: {len(titles)}")
if len(titles) < 50:
    print(f"expected at least 50 workflows, got {len(titles)}", file=sys.stderr)
    sys.exit(1)
if worse:
    print("not parity:", file=sys.stderr)
    for title in worse:
        print(f"  - {title}", file=sys.stderr)
    sys.exit(1)
PY
