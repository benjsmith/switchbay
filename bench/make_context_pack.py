"""Pre-compute a self-contained context pack for a frontier-model re-run driven
by an INTERACTIVE agent session (Claude Code / Grok at a chosen effort). The
agent needs no retrieval infra — it just answers from each arm's context and
judges. Deterministic; run once (single-threaded to avoid concurrent ONNX).

Output: bench/results/context_pack.json — a list of
  {id, category, question, gold_answer, gold_pages, contexts:{arm: text}}
"""
from __future__ import annotations

import json
from pathlib import Path

from bench.retrievers import ARMS

ARMS_TO_TEST = ["A0", "A1", "B", "Bp", "R"]  # the deck's headline table


def main():
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "bench/results/pilot-20260712-163102.json"
    per_cat = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    ws = Path.home() / "Dev" / "curiosity-test"
    data = json.loads(Path(src).read_text())
    seen: dict[str, int] = {}
    pack = []
    for i, q in enumerate(data):
        c = q["category"]
        if seen.get(c, 0) >= per_cat:
            continue
        seen[c] = seen.get(c, 0) + 1
        ctxs = {}
        for arm in ARMS_TO_TEST:
            ctx, _ = ARMS[arm](ws, q["question"], category=c)
            ctxs[arm] = ctx
        pack.append({
            "id": f"{c}-{seen[c]}",
            "category": c,
            "question": q["question"],
            "gold_answer": q.get("gold_answer", ""),
            "gold_pages": q.get("gold_pages", []),
            "contexts": ctxs,
        })
        if len(pack) % 20 == 0:
            print(f"  packed {len(pack)}")
    out = Path("bench/results/context_pack.json")
    out.write_text(json.dumps(pack, indent=1))
    print(f"wrote {out} — {len(pack)} items, arms {ARMS_TO_TEST}, {per_cat}/cat")
    print(f"  size: {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
