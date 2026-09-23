"""Adaptive chart and dashboard construction.

`suggest_charts(profile)` proposes chart specs from roles alone — no
column-name heuristics for content, only for axis labels. The
Dashboard agent prunes / reorders these.

`build_chart(df, spec)` renders a Plotly figure and returns it as an
HTML <div> (no JS dependency at view time since Plotly is loaded once
in the dashboard wrapper).

`build_dashboard_html(charts, kpis, title)` glues KPI cards + chart
divs into a single self-contained HTML page.
"""
from __future__ import annotations

import warnings
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

from .profiler import DatasetProfile


# Chart spec shape:
# {
#   "id": "stable_slug",
#   "title": "...",
#   "kind": "line" | "bar" | "scatter" | "histogram" | "box" | "pie"
#           | "heatmap",
#   "x": "<col>" | None,
#   "y": "<col>" | None,
#   "color": "<col>" | None,
#   "agg": "sum" | "mean" | "count" | None,
#   "top_n": int | None,
#   "description": "..."
# }


def suggest_charts(
    profile: DatasetProfile,
    *,
    top_n: int = 15,
    max_charts: int = 12,
) -> list[dict[str, Any]]:
    charts: list[dict[str, Any]] = []

    measures = profile.measures
    dims = profile.dimensions
    dts = profile.datetimes
    geos = profile.geos

    # 0. Choropleth map: total of the first measure by the first geo column.
    if geos and measures:
        g = geos[0]
        m = measures[0]
        charts.append({
            "id": f"map_{_slug(g)}_{_slug(m)}",
            "title": f"{m} by {g} (map)",
            "kind": "choropleth",
            "location": g,
            "y": m,
            "agg": "sum",
            "description": f"Geographic distribution of total {m} across {g}.",
        })

    # 1. Time-series per measure (one line chart for each of the first
    #    measures over the first datetime).
    if dts and measures:
        dt = dts[0]
        for m in measures[:3]:
            charts.append({
                "id": f"trend_{_slug(m)}_over_{_slug(dt)}",
                "title": f"{m} over {dt}",
                "kind": "line",
                "x": dt,
                "y": m,
                "agg": "sum",
                "description": f"Trend of total {m} over {dt}, auto-bucketed by month if granular.",
            })

    # 2. Bar chart: top-N dimension by total measure.
    for d in dims[:3]:
        for m in measures[:2]:
            charts.append({
                "id": f"top_{_slug(d)}_by_{_slug(m)}",
                "title": f"Top {d} by total {m}",
                "kind": "bar",
                "x": d,
                "y": m,
                "agg": "sum",
                "top_n": top_n,
                "description": f"Top-{top_n} values of {d} ranked by total {m}.",
            })

    # 3. Distribution: histogram per measure.
    for m in measures[:3]:
        charts.append({
            "id": f"dist_{_slug(m)}",
            "title": f"Distribution of {m}",
            "kind": "histogram",
            "x": m,
            "description": f"Histogram showing the spread of {m} values.",
        })

    # 4. Scatter of the two strongest-correlated measures (if any).
    if profile.correlations:
        top = profile.correlations[0]
        charts.append({
            "id": f"scatter_{_slug(top['a'])}_vs_{_slug(top['b'])}",
            "title": f"{top['a']} vs {top['b']} (r={top['pearson']})",
            "kind": "scatter",
            "x": top["a"],
            "y": top["b"],
            "color": dims[0] if dims else None,
            "description": (
                f"Pairwise relationship between {top['a']} and {top['b']} "
                f"(Pearson r = {top['pearson']})."
            ),
        })

    # 5. Pie of category share if there is a low-card dimension and a measure.
    for d in dims[:2]:
        if measures:
            m = measures[0]
            charts.append({
                "id": f"share_{_slug(d)}_{_slug(m)}",
                "title": f"Share of total {m} by {d}",
                "kind": "pie",
                "x": d,
                "y": m,
                "agg": "sum",
                "top_n": 10,
                "description": f"Composition of total {m} across {d}.",
            })

    # 6. Correlation heatmap if 3+ measures.
    if len(measures) >= 3:
        charts.append({
            "id": "corr_heatmap",
            "title": "Measure correlation heatmap",
            "kind": "heatmap",
            "description": "Pearson correlation matrix across all measures.",
        })

    return charts[:max_charts]


# ---------------------------------------------------------------------------
# Chart rendering
# ---------------------------------------------------------------------------

_PLOTLY_TEMPLATE = "plotly_white"

# Custom colorway harmonizing with the dashboard/report's teal-emerald theme.
# Used for every figure so colors stay consistent across the dashboard.
_PLOTLY_COLORWAY = [
    "#0d9488",  # teal-600 (primary)
    "#047857",  # emerald-700
    "#0891b2",  # cyan-600
    "#65a30d",  # lime-600
    "#0e7490",  # cyan-700
    "#16a34a",  # green-600
    "#f59e0b",  # amber-500 (warm accent)
    "#dc2626",  # red-600 (warning accent)
    "#7c3aed",  # violet-600
    "#0f766e",  # teal-700
]


def build_chart(df: pd.DataFrame, spec: dict[str, Any]) -> str:
    """Render a single chart spec to a self-contained HTML <div>.

    Plotly.js is loaded once by the dashboard wrapper, so each chart
    div is small (just data + layout)."""
    try:
        fig = _build_figure(df, spec)
    except Exception as e:
        return (
            f'<div class="chart-error"><strong>Could not render '
            f'{spec.get("title", spec.get("id"))}:</strong> '
            f"{type(e).__name__}: {e}</div>"
        )
    kind = spec.get("kind")
    # Uniform height for the grid charts; the map is full-width (its own row)
    # and a bit taller, with near-zero margins so the globe fills the card.
    is_map = kind == "choropleth"
    chart_height = 420 if is_map else 360
    margin = dict(l=0, r=0, t=46, b=0) if is_map else dict(l=50, r=24, t=50, b=44)
    fig.update_layout(
        template=_PLOTLY_TEMPLATE,
        autosize=True,
        height=chart_height,
        margin=margin,
        title=dict(text=spec.get("title", ""), x=0.5, xanchor="center"),
        title_font_size=15,
        colorway=_PLOTLY_COLORWAY,
        font=dict(family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif",
                  color="#0f2a30"),
    )
    # Single-trace charts don't honor `colorway`; coerce them to the
    # primary teal so the theme stays consistent. Each chart kind has a
    # different attribute, so update them conditionally.
    primary = _PLOTLY_COLORWAY[0]
    try:
        if kind in ("bar", "histogram"):
            fig.update_traces(marker_color=primary)
        elif kind == "line":
            fig.update_traces(line_color=primary)
    except Exception:
        pass  # Some trace types reject these; leave the default.
    return pio.to_html(
        fig,
        include_plotlyjs=False,
        full_html=False,
        default_height=f"{chart_height}px",
        # Expose ONLY the "download as PNG" button (top-right, on hover) so
        # users can export each graph without the full toolbar cluttering
        # the card or overlapping the centered title.
        config={
            "displaylogo": False,
            "responsive": True,
            "displayModeBar": "hover",
            "modeBarButtons": [["toImage"]],
            "toImageButtonOptions": {
                "format": "png",
                "filename": f"chart_{spec['id']}",
                "scale": 2,
            },
        },
        div_id=f"chart_{spec['id']}",
    )


# pandas >= 2.2 renamed the month/quarter/year resample offset aliases
# ('M'->'ME', 'Q'->'QE', 'Y'->'YE') and pandas 3.0 removed the old forms
# entirely ("'M' is no longer supported for offsets"). We resolve the
# alias the installed pandas actually accepts, once, and cache it — so
# the line charts work on pandas 2.1, 2.2, and 3.x alike.
_OFFSET_ALIAS_CACHE: dict[str, str] = {}


def _offset_alias(freq: str) -> str:
    if freq in _OFFSET_ALIAS_CACHE:
        return _OFFSET_ALIAS_CACHE[freq]
    modern = {"M": "ME", "Q": "QE", "Y": "YE", "A": "YE"}.get(freq, freq)
    probe = pd.Series([0.0, 1.0], index=pd.to_datetime(["2020-01-01", "2020-02-01"]))
    chosen = freq
    for candidate in (modern, freq):
        try:
            probe.resample(candidate).sum()
            chosen = candidate
            break
        except Exception:
            continue
    _OFFSET_ALIAS_CACHE[freq] = chosen
    return chosen


def _build_figure(df: pd.DataFrame, spec: dict[str, Any]) -> go.Figure:
    kind = spec["kind"]

    if kind == "line":
        x, y = spec["x"], spec["y"]
        d = pd.DataFrame({
            "x": pd.to_datetime(df[x], errors="coerce"),
            "y": pd.to_numeric(df[y], errors="coerce"),
        }).dropna()
        # Bucket if too many points.
        if len(d) > 200:
            s = d.set_index("x")["y"]
            for freq in ("D", "W", "M", "Q"):
                bucketed = s.resample(_offset_alias(freq)).sum().reset_index()
                if len(bucketed) <= 200:
                    d = bucketed
                    break
            else:
                # Even yearly buckets exceed the cap — fall back to raw points.
                d = d.groupby("x", as_index=False)["y"].sum()
        else:
            d = d.groupby("x", as_index=False)["y"].sum()
        return px.line(d, x="x", y="y", labels={"x": x, "y": y})

    if kind == "bar":
        x, y = spec["x"], spec["y"]
        top_n = spec.get("top_n", 15)
        agg = spec.get("agg", "sum")
        s = pd.to_numeric(df[y], errors="coerce")
        grouped = s.groupby(df[x]).agg(agg).sort_values(ascending=False).head(top_n)
        return px.bar(
            x=grouped.index.astype(str),
            y=grouped.values,
            labels={"x": x, "y": f"{agg}({y})"},
        )

    if kind == "histogram":
        x = spec["x"]
        s = pd.to_numeric(df[x], errors="coerce").dropna()
        return px.histogram(s, x=s, labels={"x": x, "value": x}, nbins=30)

    if kind == "scatter":
        x, y = spec["x"], spec["y"]
        color = spec.get("color")
        cols = {x: pd.to_numeric(df[x], errors="coerce"),
                y: pd.to_numeric(df[y], errors="coerce")}
        if color and color in df.columns:
            cols[color] = df[color].astype(str)
        d = pd.DataFrame(cols).dropna(subset=[x, y])
        # Cap points for performance.
        if len(d) > 5000:
            d = d.sample(5000, random_state=0)
        return px.scatter(d, x=x, y=y, color=color if color else None, opacity=0.7)

    if kind == "pie":
        x, y = spec["x"], spec["y"]
        top_n = spec.get("top_n", 10)
        s = pd.to_numeric(df[y], errors="coerce")
        grouped = s.groupby(df[x]).sum().sort_values(ascending=False)
        if len(grouped) > top_n:
            top = grouped.head(top_n - 1)
            other = pd.Series([grouped.iloc[top_n - 1:].sum()], index=["Other"])
            grouped = pd.concat([top, other])
        return px.pie(values=grouped.values, names=grouped.index.astype(str), hole=0.4)

    if kind == "heatmap":
        numeric = df.select_dtypes(include="number")
        if numeric.shape[1] < 2:
            raise ValueError("Heatmap needs >= 2 numeric columns")
        corr = numeric.corr()
        # "Tealrose" runs red ↔ teal, matching our palette better than RdBu.
        return px.imshow(corr, text_auto=".2f", aspect="auto",
                         color_continuous_scale="Tealrose_r", zmin=-1, zmax=1)

    if kind == "choropleth":
        loc, y = spec["location"], spec["y"]
        agg = spec.get("agg", "sum")
        s = pd.to_numeric(df[y], errors="coerce")
        labels = df[loc].astype(str).str.strip()
        grouped = s.groupby(labels).agg(agg)
        grouped = grouped[grouped.index != ""].dropna()
        if grouped.empty:
            raise ValueError("No mappable locations")
        with warnings.catch_warnings():
            # We intentionally use country-name matching; Plotly warns that
            # the backing list may change in a future version. Harmless here.
            warnings.simplefilter("ignore", category=DeprecationWarning)
            fig = px.choropleth(
                locations=grouped.index.tolist(),
                locationmode="country names",
                color=grouped.values,
                color_continuous_scale="Tealgrn",
                labels={"color": f"{agg}({y})"},
            )
        # Plotly silently drops locations it can't map (e.g. "Scotland");
        # the companion bar chart remains the exhaustive comparison.
        # Constrain the view to the populated latitudes/longitudes and use a
        # transparent background so the map fills its card instead of
        # leaving large empty margins around the globe.
        fig.update_geos(
            showframe=False,
            showcoastlines=False,
            projection_type="natural earth",
            lataxis_range=[-56, 84],
            lonaxis_range=[-168, 190],
            bgcolor="rgba(0,0,0,0)",
            # Make the geo subplot occupy the entire plot area (edge-to-edge).
            domain=dict(x=[0, 1], y=[0, 1]),
        )
        # Slim the colorbar so it doesn't steal width from the map.
        fig.update_coloraxes(colorbar=dict(thickness=12, len=0.85, x=1.0, xpad=0))
        return fig

    raise ValueError(f"Unknown chart kind: {kind}")


# ---------------------------------------------------------------------------
# Dashboard assembly
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{title}</title>
<script src="https://cdn.plot.ly/plotly-2.30.0.min.js"></script>
<style>
  :root {{
    --bg: #f4f9f8;
    --card: #ffffff;
    --ink: #0f2a30;
    --muted: #5b7178;
    --accent: #0d9488;
    --border: #d7e6e3;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--ink);
  }}
  header {{
    padding: 18px 40px 18px;
    background: linear-gradient(135deg, #0d9488 0%, #047857 60%, #065f46 100%);
    color: #fff;
  }}
  header h1 {{ margin: 0; font-size: 24px; font-weight: 600; }}
  header p {{ margin: 6px 0 0; opacity: 0.85; font-size: 14px; }}
  .topnav {{
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 14px;
  }}
  .topnav a {{
    display: inline-flex; align-items: center; gap: 6px;
    color: #fff; text-decoration: none; font-size: 13px; font-weight: 600;
    background: rgba(255,255,255,0.16); border: 1px solid rgba(255,255,255,0.4);
    padding: 7px 14px; border-radius: 7px; transition: background 0.15s;
  }}
  .topnav a:hover {{ background: rgba(255,255,255,0.3); }}
  main {{ padding: 24px 40px 60px; }}
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 14px;
    margin-bottom: 32px;
  }}
  .kpi-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 18px;
  }}
  .kpi-label {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }}
  .kpi-value {{ font-size: 24px; font-weight: 600; margin-top: 6px; color: var(--ink); }}
  .kpi-desc  {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
  .charts {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
    gap: 18px;
  }}
  .chart-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px;
    min-height: 360px;
  }}
  /* Full-width row for the map so its wide aspect ratio fills the card. */
  .chart-card--full {{ grid-column: 1 / -1; }}
  .chart-card--full .plotly-graph-div {{ width: 100%; }}
  .chart-desc {{ font-size: 12px; color: var(--muted); margin-top: 8px; text-align: center; }}
  .chart-error {{ color: #b00020; font-size: 13px; padding: 10px; }}
</style>
</head>
<body>
  <header>
    <nav class="topnav">
      <a href="/" title="Back to the home page">&larr; Home</a>
      <a href="report.html" title="Open the BI report for this run">View BI report &rarr;</a>
    </nav>
    <h1>{title}</h1>
    <p>{subtitle}</p>
  </header>
  <main>
    <section class="kpi-grid">{kpi_cards}</section>
    <section class="charts">{chart_cards}</section>
  </main>
</body>
</html>
"""


def build_dashboard_html(
    *,
    title: str,
    subtitle: str,
    kpis: list[dict[str, Any]],
    charts_html: list[dict[str, Any]],
) -> str:
    """Compose KPI cards + chart divs into a single self-contained HTML
    page. `charts_html` items must have keys: id, title, description, html."""
    kpi_cards = "\n".join(
        f"""
        <div class="kpi-card">
          <div class="kpi-label">{_escape(k.get('title', k.get('id', '')))}</div>
          <div class="kpi-value">{_escape(k.get('display', 'n/a'))}</div>
          <div class="kpi-desc">{_escape(k.get('description', ''))}</div>
        </div>"""
        for k in kpis
    )
    # The choropleth is wide-and-short; give it its own full-width row so it
    # fills the card edge-to-edge instead of letterboxing in a narrow column.
    chart_cards = "\n".join(
        f"""
        <div class="chart-card{' chart-card--full' if c.get('kind') == 'choropleth' else ''}">
          {c.get('html', '')}
          <div class="chart-desc">{_escape(c.get('description', ''))}</div>
        </div>"""
        for c in charts_html
    )
    return _DASHBOARD_HTML.format(
        title=_escape(title),
        subtitle=_escape(subtitle),
        kpi_cards=kpi_cards,
        chart_cards=chart_cards,
    )


def _escape(s: Any) -> str:
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _slug(s: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in s).strip("_")
