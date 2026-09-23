"""Renders the final BI report as a self-contained HTML page.

Kept separate from `dashboard_builder` because the report's purpose is
different: it tells the story of the run (source, methodology,
findings, recommendations) and embeds the dashboard by reference.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any


_REPORT_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{title}</title>
<style>
  :root {{
    --bg: #f4f9f8;
    --ink: #0f2a30;
    --muted: #5b7178;
    --accent: #0d9488;
    --accent-strong: #047857;
    --accent-soft: #d1faf2;
    --card: #ffffff;
    --border: #d7e6e3;
    --good: #047857;
    --warn: #b45309;
    --bad: #b91c1c;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--ink); }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
    line-height: 1.55;
    font-size: 15px;
  }}
  .wrap {{ max-width: 980px; margin: 0 auto; padding: 0 28px 80px; }}
  header.hero {{
    background: linear-gradient(135deg, #0d9488 0%, #047857 60%, #065f46 100%);
    color: #fff;
    padding: 48px 28px 40px;
    margin-bottom: 30px;
  }}
  header.hero .wrap {{ padding-bottom: 0; }}
  header.hero .eyebrow {{
    font-size: 12px; letter-spacing: 1.5px; text-transform: uppercase; opacity: 0.85;
  }}
  header.hero h1 {{ margin: 8px 0 4px; font-size: 30px; font-weight: 600; }}
  header.hero .meta {{ font-size: 13px; opacity: 0.85; }}
  h2 {{
    font-size: 18px; margin-top: 36px; margin-bottom: 10px;
    border-bottom: 2px solid var(--accent); padding-bottom: 6px; display: inline-block;
  }}
  h3 {{ font-size: 15px; margin: 20px 0 8px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }}
  p {{ margin: 8px 0; }}
  ul {{ padding-left: 22px; margin: 8px 0; }}
  li {{ margin: 4px 0; }}
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 12px;
    margin: 12px 0 20px;
  }}
  .kpi-card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px 16px;
  }}
  .kpi-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }}
  .kpi-value {{ font-size: 22px; font-weight: 600; margin-top: 6px; }}
  .kpi-desc  {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
  table.simple {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 13px; }}
  table.simple th, table.simple td {{
    text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border);
  }}
  table.simple th {{ background: var(--accent-soft); color: var(--ink); font-weight: 600; }}
  .role-pill {{
    display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 999px;
    background: var(--accent-soft); color: var(--accent-strong); font-weight: 600;
  }}
  .role-measure   {{ background: #d1faf2; color: #047857; }}
  .role-dimension {{ background: #fef3c7; color: #92400e; }}
  .role-datetime  {{ background: #cffafe; color: #0e7490; }}
  .role-identifier{{ background: #e5edec; color: #5b7178; }}
  .role-text      {{ background: #e5edec; color: #5b7178; }}
  .role-boolean   {{ background: #fce7f3; color: #9d174d; }}
  .role-high_card_dim {{ background: #fef3c7; color: #92400e; }}
  .pill-good {{ color: var(--good); font-weight: 600; }}
  .pill-warn {{ color: var(--warn); font-weight: 600; }}
  .pill-bad  {{ color: var(--bad);  font-weight: 600; }}
  .callout {{
    background: var(--accent-soft); border-left: 4px solid var(--accent);
    padding: 12px 16px; border-radius: 4px; margin: 12px 0;
  }}
  .verify-badge {{
    display: inline-block; font-size: 13px; font-weight: 600;
    border-radius: 8px; padding: 8px 14px; margin: 4px 0 12px;
    border: 1px solid var(--border);
  }}
  .verify-badge.ok   {{ background: #e8f8f4; color: var(--good); border-color: #b7e6d8; }}
  .verify-badge.warn {{ background: #fef3c7; color: var(--warn); border-color: #f3d893; }}
  .verify-badge.none {{ background: #fde8e8; color: var(--bad);  border-color: #f3b6b6; }}
  .verify-badge .offenders {{ font-weight: 400; }}
  .dashboard-link {{
    display: inline-block; background: var(--accent); color: #fff;
    text-decoration: none; padding: 10px 18px; border-radius: 6px; margin-top: 6px;
    font-weight: 600; transition: background 0.15s;
  }}
  .dashboard-link:hover {{ background: var(--accent-strong); }}
  footer {{
    margin-top: 50px; padding-top: 20px; border-top: 1px solid var(--border);
    font-size: 12px; color: var(--muted);
  }}
  code {{
    background: #f0f0f5; padding: 1px 5px; border-radius: 3px; font-size: 12px;
  }}
  /* ---- Report toolbar (Save as PDF / Download HTML) ---- */
  .report-toolbar {{
    margin-top: 18px;
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }}
  .toolbar-btn {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(255,255,255,0.16);
    color: #fff !important;
    border: 1px solid rgba(255,255,255,0.45);
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: 600;
    font-size: 13px;
    cursor: pointer;
    text-decoration: none;
    transition: background 0.15s;
    font-family: inherit;
  }}
  .toolbar-btn:hover {{
    background: rgba(255,255,255,0.28);
    text-decoration: none;
  }}
  .toolbar-btn svg {{ width: 14px; height: 14px; }}

  /* ---- Print stylesheet ---- */
  @media print {{
    /* Force backgrounds (hero gradient, role pills, kpi cards) to actually print
       in WebKit / Blink browsers. Without this they would print as white. */
    * {{ -webkit-print-color-adjust: exact !important;
         print-color-adjust: exact !important; }}
    .no-print, .no-print * {{ display: none !important; }}
    body, html {{ background: #fff !important; }}
    .wrap {{ max-width: 100% !important; padding: 0 24px !important; }}
    header.hero {{ padding: 24px 24px 18px !important; margin-bottom: 18px; }}
    header.hero h1 {{ font-size: 22px; }}
    /* Avoid cards splitting across pages. */
    .kpi-card, .chart-card, table.simple tr, .callout {{
      break-inside: avoid;
      page-break-inside: avoid;
    }}
    section {{ break-inside: auto; }}
    h2 {{ break-after: avoid; page-break-after: avoid; }}
    a {{ color: var(--accent-strong) !important; text-decoration: none; }}
    /* Sensible page margins. */
    @page {{ margin: 14mm; size: A4; }}
  }}
</style>
</head>
<body>
  <header class="hero">
    <div class="wrap">
      <div class="eyebrow">BI Report</div>
      <h1>{title}</h1>
      <div class="meta">Run <code>{run_id}</code> · Generated {generated_at}</div>
      <div class="report-toolbar no-print">
        <a class="toolbar-btn" href="/" title="Back to the home page">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5"/><polyline points="12 19 5 12 12 5"/></svg>
          Home
        </a>
        <a class="toolbar-btn" href="dashboard.html" title="Open the interactive dashboard for this run.">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/><rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/></svg>
          Dashboard
        </a>
        <button type="button" class="toolbar-btn" onclick="window.print()" title="Opens your browser's print dialog. Choose 'Save as PDF' as the destination to download a PDF copy.">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
          Save as PDF
        </button>
        <a class="toolbar-btn" href="report.html" download="{download_name}.html" title="Download a self-contained HTML copy of this report.">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          Download HTML
        </a>
      </div>
    </div>
  </header>

  <div class="wrap">

    <section>
      <h2>Executive Summary</h2>
      <p>{executive_summary}</p>
    </section>

    <section>
      <h2>Data Source</h2>
      <table class="simple">
        <tbody>
          <tr><th>File</th><td><code>{source_name}</code></td></tr>
          <tr><th>Rows</th><td>{row_count}</td></tr>
          <tr><th>Columns</th><td>{column_count}</td></tr>
          <tr><th>Measures detected</th><td>{measures_count}</td></tr>
          <tr><th>Dimensions detected</th><td>{dimensions_count}</td></tr>
          <tr><th>Datetime columns</th><td>{datetimes_count}</td></tr>
          <tr><th>Validation</th><td>{validation_pill}</td></tr>
          <tr><th>Cleaning operations applied</th><td>{cleaning_count}</td></tr>
        </tbody>
      </table>

      <h3>Column Schema</h3>
      <table class="simple">
        <thead><tr><th>Column</th><th>Role</th><th>Type</th><th>Cardinality</th><th>Missing</th></tr></thead>
        <tbody>
          {schema_rows}
        </tbody>
      </table>
    </section>

    <section>
      <h2>Methodology</h2>
      <p>{methodology}</p>
      {cleaning_block}
    </section>

    <section>
      <h2>Key Performance Indicators</h2>
      <div class="kpi-grid">
        {kpi_cards}
      </div>
    </section>

    <section>
      <h2>Dashboard</h2>
      <p>The interactive dashboard for this run contains {chart_count} charts spanning trends, comparisons, distributions, and compositions.</p>
      <p><a class="dashboard-link" href="dashboard.html" target="_blank">Open interactive dashboard →</a></p>
      <h3>Chart inventory</h3>
      <ul>
        {chart_list}
      </ul>
    </section>

    <section>
      <h2>Findings</h2>
      {findings_verify_badge}
      <ul>
        {findings_list}
      </ul>
    </section>

    {recommendations_block}

    {anomalies_block}

    {segments_block}

    {correlations_block}

    <footer>
      Generated by the MCP-Powered BI Ecosystem. All numbers in this report are
      derived deterministically from the source dataset; narrative prose was
      composed by the Reporter agent and grounded in the same numbers.
    </footer>
  </div>
</body>
</html>
"""


def _validation_pill(validation: dict[str, Any]) -> str:
    if not validation:
        return '<span class="pill-warn">not run</span>'
    if validation.get("ok"):
        return '<span class="pill-good">passed</span>'
    issues = validation.get("issues") or []
    return (
        f'<span class="pill-warn">{len(issues)} issue(s)</span>'
        + (": " + escape("; ".join(issues)) if issues else "")
    )


def _role_pill(role: str) -> str:
    safe_role = role if role.replace("_", "").isalpha() else "text"
    return f'<span class="role-pill role-{safe_role}">{escape(role)}</span>'


def _verify_badge(fv: dict[str, Any] | None) -> str:
    """Render the grounded-findings verification badge shown above the
    Findings list. Empty string when there were no numeric claims."""
    if not fv or fv.get("checked", 0) == 0:
        return ""
    verdict = fv.get("verdict", "verified")
    checked = fv.get("checked", 0)
    supported = fv.get("supported", 0)
    if verdict == "verified":
        return (
            f'<div class="verify-badge ok">&#10003; All {checked} quantitative '
            f'claim(s) verified against computed KPIs.</div>'
        )
    offenders = ", ".join(escape(u.get("number", "")) for u in fv.get("unsupported", []))
    cls = "warn" if verdict == "partial" else "none"
    return (
        f'<div class="verify-badge {cls}">&#9888; {supported}/{checked} '
        f'claim(s) verified against computed KPIs. '
        f'<span class="offenders">Unmatched: {offenders}</span></div>'
    )


def _anomalies_block(anomalies: list[dict[str, Any]]) -> str:
    """Render the 'Anomalies & Outliers' report section, or '' if none."""
    if not anomalies:
        return ""
    rows = []
    for a in anomalies:
        ex = a.get("examples", [])
        if a.get("kind") == "time_spike":
            top = ex[0] if ex else {}
            detail = f"period {escape(str(top.get('period', '')))} = {escape(str(top.get('value', '')))}"
        else:
            top = ex[0] if ex else {}
            detail = (
                f"value {escape(str(top.get('value', '')))}"
                + (f" ({escape(str(top.get('row_label', '')))})" if top.get("row_label") else "")
            )
        kind_label = "time spike" if a.get("kind") == "time_spike" else "value outlier"
        rows.append(
            f"<tr><td><code>{escape(str(a.get('measure', '')))}</code></td>"
            f"<td>{kind_label}</td>"
            f"<td>{a.get('count', 0):,}</td>"
            f"<td>most extreme: {detail} <span class='muted'>(score {escape(str(top.get('score', '')))})</span></td></tr>"
        )
    return f"""
    <section>
      <h2>Anomalies &amp; Outliers</h2>
      <p>Values flagged by a robust modified z-score (outliers are far from the
      typical range — not necessarily errors, but worth a look):</p>
      <table class="simple">
        <thead><tr><th>Measure</th><th>Type</th><th>Flagged</th><th>Most extreme</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </section>
    """


def _segments_block(segments: list[dict[str, Any]]) -> str:
    """Render the 'Segment Comparison' report section, or '' if none."""
    if not segments:
        return ""
    rows = []
    for s in segments:
        top, bot = s.get("top", {}), s.get("bottom", {})
        ratio = s.get("ratio")
        ratio_txt = f"{ratio:g}×" if ratio else "—"
        rows.append(
            f"<tr><td><code>{escape(str(s.get('measure', '')))}</code> by "
            f"<code>{escape(str(s.get('dimension', '')))}</code></td>"
            f"<td>{escape(str(top.get('label', '')))} "
            f"<strong>({escape(str(top.get('mean', '')))})</strong></td>"
            f"<td>{escape(str(bot.get('label', '')))} "
            f"<strong>({escape(str(bot.get('mean', '')))})</strong></td>"
            f"<td>{ratio_txt}</td></tr>"
        )
    return f"""
    <section>
      <h2>Segment Comparison</h2>
      <p>How each measure's average differs across the groups of a dimension —
      ranked by the size of the gap between the highest and lowest group:</p>
      <table class="simple">
        <thead><tr><th>Measure × Segment</th><th>Highest group (avg)</th><th>Lowest group (avg)</th><th>Ratio</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </section>
    """


def _slug(s: str) -> str:
    """ASCII-safe, filename-friendly slug. Used for the `download` attribute
    on the 'Download HTML' button so the saved file gets a clean name."""
    out = []
    for c in s:
        if c.isalnum():
            out.append(c)
        elif c in (" ", "-", "_"):
            out.append("_")
    slug = "".join(out).strip("_")
    # Collapse repeated underscores
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "report"


def render_report_html(
    *,
    run_id: str,
    source_name: str,
    profile: dict[str, Any],
    kpis: list[dict[str, Any]],
    charts: list[dict[str, Any]],
    validation: dict[str, Any],
    cleaning_log: dict[str, Any],
    executive_summary: str,
    methodology: str,
    findings: list[str],
    recommendations: list[str],
    source_display_name: str | None = None,
    findings_validation: dict[str, Any] | None = None,
    anomalies: list[dict[str, Any]] | None = None,
    segments: list[dict[str, Any]] | None = None,
) -> str:
    columns = profile.get("columns") or []
    schema_rows = "\n".join(
        f"<tr>"
        f"<td><code>{escape(str(c.get('name', '')))}</code></td>"
        f"<td>{_role_pill(c.get('role', 'text'))}</td>"
        f"<td>{escape(str(c.get('dtype', '')))}</td>"
        f"<td>{c.get('cardinality', 0):,}</td>"
        f"<td>{c.get('null_pct', 0)}%</td>"
        f"</tr>"
        for c in columns
    )

    kpi_cards = "\n".join(
        f"""
        <div class="kpi-card">
          <div class="kpi-label">{escape(str(k.get('title', k.get('id', ''))))}</div>
          <div class="kpi-value">{escape(str(k.get('display', 'n/a')))}</div>
          <div class="kpi-desc">{escape(str(k.get('description', '')))}</div>
        </div>"""
        for k in kpis
    )

    chart_list = "\n".join(
        f"<li><strong>{escape(str(c.get('title', c.get('id', ''))))}</strong> "
        f"<em style='color:#5b667d'>({escape(str(c.get('kind', '')))})</em> "
        f"— {escape(str(c.get('description', '')))}</li>"
        for c in charts
    ) or "<li><em>(no charts built)</em></li>"

    findings_list = "\n".join(
        f"<li>{escape(f)}</li>" for f in findings
    ) or "<li><em>(no findings recorded)</em></li>"

    findings_verify_badge = _verify_badge(findings_validation)

    recommendations_block = ""
    if recommendations:
        items = "\n".join(f"<li>{escape(r)}</li>" for r in recommendations)
        recommendations_block = (
            f'<section><h2>Recommendations</h2><ul>{items}</ul></section>'
        )

    # Cleaning block
    applied = cleaning_log.get("applied") if cleaning_log else None
    if applied:
        items = "\n".join(f"<li><code>{escape(a)}</code></li>" for a in applied)
        cleaning_block = (
            f'<div class="callout"><strong>Cleaning operations applied:</strong>'
            f'<ul>{items}</ul></div>'
        )
    else:
        cleaning_block = (
            '<div class="callout">No cleaning operations were required — '
            'the dataset was already in good shape.</div>'
        )

    # Correlations block
    correlations = profile.get("correlations") or []
    correlations_block = ""
    if correlations:
        rows = "\n".join(
            f"<tr><td>{escape(str(c['a']))}</td><td>{escape(str(c['b']))}</td>"
            f"<td>{c['pearson']:+.3f}</td></tr>"
            for c in correlations[:8]
        )
        correlations_block = f"""
        <section>
          <h2>Notable Relationships</h2>
          <p>Pearson correlations between measures meeting the reporting threshold:</p>
          <table class="simple">
            <thead><tr><th>Measure A</th><th>Measure B</th><th>r</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </section>
        """

    anomalies_block = _anomalies_block(anomalies or [])
    segments_block = _segments_block(segments or [])

    # The title uses the humanized display name; the Data Source table
    # below still shows the raw file name verbatim.
    title_name = source_display_name or source_name
    # Filename suggested when the user clicks "Download HTML" — safe ASCII,
    # no spaces, suffix added by the anchor.
    download_name = "BI_Report_" + _slug(title_name) if title_name else "BI_Report"
    return _REPORT_HTML.format(
        title=escape(f"BI Report — {title_name}"),
        download_name=escape(download_name),
        run_id=escape(run_id),
        generated_at=escape(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
        executive_summary=escape(executive_summary).replace("\n\n", "</p><p>"),
        source_name=escape(source_name),
        row_count=f"{profile.get('row_count', 0):,}",
        column_count=profile.get("column_count", 0),
        measures_count=len(profile.get("measures", [])),
        dimensions_count=len(profile.get("dimensions", [])),
        datetimes_count=len(profile.get("datetimes", [])),
        validation_pill=_validation_pill(validation),
        cleaning_count=len(applied) if applied else 0,
        schema_rows=schema_rows,
        methodology=escape(methodology).replace("\n\n", "</p><p>"),
        anomalies_block=anomalies_block,
        segments_block=segments_block,
        cleaning_block=cleaning_block,
        kpi_cards=kpi_cards,
        chart_count=len(charts),
        chart_list=chart_list,
        findings_verify_badge=findings_verify_badge,
        findings_list=findings_list,
        recommendations_block=recommendations_block,
        correlations_block=correlations_block,
    )
