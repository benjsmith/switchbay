# OWID pack — Our World in Data

Browse [Our World in Data](https://ourworldindata.org) charts, import a
chart's data into your workspace, and plot over it.

- **Browse** — the **OWID** tab lists a starter catalogue and filters as
  you type. It also accepts **any** chart slug or grapher URL (paste
  e.g. `life-expectancy` or `https://ourworldindata.org/grapher/population`).
- **Import** — fetches the chart's full data via OWID's public grapher
  endpoints, saves it as `data/owid/<slug>.csv` in the workspace, and
  authors a starter Vega-Lite line plot.
- **Plot / query** — the plot opens in the **Plot** tab (refine the
  Vega-Lite spec there); the saved CSV is available to the **Table**
  (DuckDB) tab for querying.

No API key, no pip install — pure HTTP. See OWID's
[chart API docs](https://docs.owid.io/projects/etl/api/chart-api/).
