"""Our World in Data (OWID) — browse charts, import their data into a
workspace, and get a starter plot. Backs the bundled `owid` pack's
browse tab (search → import → plot over it in the Plot/Table tabs).

No API key, no pip install — pure HTTP against OWID's public grapher
endpoints (https://docs.owid.io/projects/etl/api/chart-api/):

  https://ourworldindata.org/grapher/<slug>.csv?csvType=full&useColumnShortNames=true
  https://ourworldindata.org/grapher/<slug>.metadata.json?useColumnShortNames=true

CSV shape: `entity, code, year, <value…>`. On import we save the full
CSV under `<workspace>/data/owid/<slug>.csv` (so the Table/DuckDB tab and
any later analysis can use it) and auto-author a small Vega-Lite line
plot (a sensible entity subset, kept inline so the spec stays light).
"""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import plots

_BASE = "https://ourworldindata.org/grapher"
_TIMEOUT = 25
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# A curated starter set so "browse" shows something immediately; the tab
# also accepts any grapher slug/URL, so this isn't a ceiling. Validated
# against live OWID at build time.
SEED_CATALOG: list[dict[str, str]] = [
    {"slug": "life-expectancy", "title": "Life expectancy", "topic": "Health"},
    {"slug": "child-mortality", "title": "Child mortality", "topic": "Health"},
    {"slug": "share-of-individuals-using-the-internet", "title": "Internet users (share)", "topic": "Technology"},
    {"slug": "population", "title": "Population", "topic": "Population"},
    {"slug": "human-development-index", "title": "Human Development Index", "topic": "Economy"},
    {"slug": "share-of-population-in-extreme-poverty", "title": "Extreme poverty (share)", "topic": "Economy"},
    {"slug": "co-emissions-per-capita", "title": "CO₂ emissions per capita", "topic": "Climate"},
    {"slug": "annual-co2-emissions-per-country", "title": "Annual CO₂ emissions", "topic": "Climate"},
    {"slug": "share-electricity-renewables", "title": "Renewable electricity (share)", "topic": "Energy"},
    {"slug": "gdp-per-capita-worldbank", "title": "GDP per capita", "topic": "Economy"},
    {"slug": "children-per-woman-un", "title": "Fertility rate (children per woman)", "topic": "Population"},
    {"slug": "daily-per-capita-caloric-supply", "title": "Daily calorie supply", "topic": "Food"},
]

# Default entities for the starter plot when a chart spans many; "World"
# is preferred, else these majors, else the first few by row count.
_DEFAULT_ENTITIES = [
    "World", "United States", "China", "India", "Germany",
    "Nigeria", "Brazil", "Japan",
]


def search(query: str) -> list[dict[str, str]]:
    q = (query or "").strip().lower()
    if not q:
        return list(SEED_CATALOG)
    return [c for c in SEED_CATALOG
            if q in c["title"].lower() or q in c["slug"] or q in c["topic"].lower()]


def slug_from(text: str) -> str | None:
    """Accept a bare slug or a full grapher URL and return the slug."""
    t = (text or "").strip()
    if not t:
        return None
    if "grapher/" in t:
        t = t.split("grapher/", 1)[1]
    t = t.split("?", 1)[0].split("#", 1)[0].strip("/").strip()
    return t if _SLUG_RE.match(t) else None


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "switchbay-owid/1.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310 (fixed host)
        return r.read()


def _chart_title(slug: str) -> str:
    url = f"{_BASE}/{slug}.metadata.json?useColumnShortNames=true"
    try:
        meta = json.loads(_fetch(url).decode("utf-8"))
        t = (meta.get("chart") or {}).get("title")
        if isinstance(t, str) and t.strip():
            return t.strip()
    except (urllib.error.URLError, json.JSONDecodeError, ValueError, TimeoutError):
        pass
    return slug.replace("-", " ").title()


def import_chart(workspace: Path, slug: str) -> dict[str, Any]:
    """Fetch a chart's data → save the CSV under `data/owid/` → author a
    starter Vega-Lite line plot. Returns a summary dict (or {ok:False})."""
    slug = slug_from(slug) or ""
    if not slug:
        return {"ok": False, "error": "not a valid OWID chart slug or grapher URL"}
    csv_url = (f"{_BASE}/{slug}.csv?csvType=full&useColumnShortNames=true")
    try:
        raw = _fetch(csv_url).decode("utf-8")
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"OWID has no chart '{slug}' (HTTP {e.code})"}
    except (urllib.error.URLError, TimeoutError) as e:
        return {"ok": False, "error": f"couldn't reach OWID: {e}"}

    rows = list(csv.reader(io.StringIO(raw)))
    if len(rows) < 2:
        return {"ok": False, "error": "chart returned no data"}
    header = rows[0]
    if len(header) < 4:
        return {"ok": False, "error": f"unexpected CSV shape: {header}"}
    # entity, code, year, <value…> — take the first value column.
    val_col = header[3]
    yr_i, ent_i, val_i = 2, 0, 3
    title = _chart_title(slug)

    # Save the full CSV for the Table tab / later analysis.
    data_dir = workspace / "data" / "owid"
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = data_dir / f"{slug}.csv"
    csv_path.write_text(raw, encoding="utf-8")
    rel_csv = str(csv_path.relative_to(workspace))

    # Pick a small entity set for the starter plot so the spec stays light.
    entities = [r[ent_i] for r in rows[1:] if len(r) > val_i]
    present = set(entities)
    chosen = [e for e in _DEFAULT_ENTITIES if e in present]
    if not chosen:
        # Fall back to the entities with the most observations.
        counts: dict[str, int] = {}
        for e in entities:
            counts[e] = counts.get(e, 0) + 1
        chosen = [e for e, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:6]]
    chosen_set = set(chosen)

    values: list[dict[str, Any]] = []
    for r in rows[1:]:
        if len(r) <= val_i or r[ent_i] not in chosen_set:
            continue
        try:
            y = float(r[val_i]) if r[val_i] not in ("", "NaN") else None
        except ValueError:
            y = None
        if y is None:
            continue
        try:
            yr = int(r[yr_i])
        except ValueError:
            continue
        values.append({"entity": r[ent_i], "year": yr, "value": y})

    # Legibility: many OWID series carry a long, SPARSE ancient tail
    # (population from 10 000 BCE, GDP from year 1, …) that squashes the
    # readable modern range into a spike at the right edge. Frame the axis
    # where the data actually lives by dropping the oldest ~8% of
    # observations — adapts per series (a purely-modern series barely
    # changes; the full CSV keeps every year for deeper analysis).
    if len(values) > 40:
        yrs = sorted(v["year"] for v in values)
        start_year = yrs[int(len(yrs) * 0.08)]
        clipped = [v for v in values if v["year"] >= start_year]
        if len(clipped) >= 20:
            values = clipped
    span = ((max(v["year"] for v in values), min(v["year"] for v in values))
            if values else (0, 0))

    # Large magnitudes (population, emissions) read better with SI-style
    # abbreviated ticks; small ones (rates, indices) keep plain numbers.
    ymax = max((abs(v["value"]) for v in values), default=0)
    y_axis: dict[str, Any] = {"title": title}
    if ymax >= 1e4:
        y_axis["format"] = "~s"   # 8G, 2.5M, 800k …

    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": title,
        "data": {"values": values},
        "mark": {"type": "line", "point": False, "tooltip": True},
        "encoding": {
            "x": {"field": "year", "type": "quantitative",
                  "scale": {"nice": False, "zero": False},
                  "axis": {"format": "d", "title": "Year"}},
            "y": {"field": "value", "type": "quantitative", "title": title,
                  "axis": y_axis},
            "color": {"field": "entity", "type": "nominal", "title": "Entity"},
        },
    }
    plot = plots.save_plot(
        workspace, name=f"OWID · {title}", spec=spec, origin="owid",
    )
    return {
        "ok": True, "slug": slug, "title": title,
        "csv_path": rel_csv, "rows": len(rows) - 1,
        "plot_id": plot.get("id"), "entities_plotted": chosen,
        "value_column": val_col,
    }
