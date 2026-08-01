"""Self-contained HTML application dashboard (ai-job-search html-report pattern)."""

from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.services.job_search.methodology import BUCKET_COLORS, normalize_status_bucket


def _safe(value: Any) -> str:
    return html.escape(str(value or ""))


def build_analytics_summary(applications: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = Counter()
    sectors = Counter()
    channels = Counter()
    rows: list[dict[str, Any]] = []

    for app in applications:
        status = str(app.get("status") or "saved")
        bucket = normalize_status_bucket(status)
        buckets[bucket] += 1
        sector = str(app.get("sector") or app.get("platform") or "Unknown")
        sectors[sector] += 1
        channel = str(app.get("source") or app.get("channel") or "unknown")
        channels[channel] += 1
        rows.append(
            {
                "date": app.get("submittedAt") or app.get("createdAt") or "",
                "company": app.get("companyName") or app.get("company") or "",
                "role": app.get("roleTitle") or app.get("role") or "",
                "sector": sector,
                "channel": channel,
                "status": status,
                "bucket": bucket,
                "notes": app.get("notes") or "",
                "url": app.get("url") or "",
                "fitRating": app.get("fitRating") or app.get("fit_rating") or "",
            }
        )

    total = len(applications)
    resolved = buckets["Rejected/Closed"] + buckets["Hired"] + buckets["Offer"]
    rejection_rate = round((buckets["Rejected/Closed"] / resolved) * 100, 1) if resolved else 0.0
    interview_rate = round((buckets["Interview"] / total) * 100, 1) if total else 0.0

    return {
        "total": total,
        "buckets": dict(buckets),
        "sectors": dict(sectors),
        "channels": dict(channels),
        "rejectionRate": rejection_rate,
        "interviewRate": interview_rate,
        "rows": rows,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


def _svg_doughnut(buckets: dict[str, int], size: int = 180) -> str:
    total = sum(buckets.values()) or 1
    cx = cy = size // 2
    radius = size // 2 - 8
    start_angle = -90
    parts: list[str] = []
    for label, count in buckets.items():
        if count <= 0:
            continue
        sweep = 360 * (count / total)
        end_angle = start_angle + sweep
        large_arc = 1 if sweep > 180 else 0
        import math

        x1 = cx + radius * math.cos(math.radians(start_angle))
        y1 = cy + radius * math.sin(math.radians(start_angle))
        x2 = cx + radius * math.cos(math.radians(end_angle))
        y2 = cy + radius * math.sin(math.radians(end_angle))
        color = BUCKET_COLORS.get(label, "#94a3b8")
        parts.append(
            f'<path d="M{cx},{cy} L{x1:.1f},{y1:.1f} A{radius},{radius} 0 {large_arc},1 {x2:.1f},{y2:.1f} Z" fill="{color}"/>'
        )
        start_angle = end_angle
    return f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">{"".join(parts)}</svg>'


def _svg_hbar(data: dict[str, int], width: int = 320, bar_height: int = 18) -> str:
    if not data:
        return '<svg width="320" height="40"><text x="8" y="24" fill="#64748b">No data</text></svg>'
    max_val = max(data.values()) or 1
    rows = []
    y = 8
    for label, count in sorted(data.items(), key=lambda item: item[1], reverse=True)[:8]:
        bar_w = int((count / max_val) * (width - 120))
        rows.append(
            f'<text x="0" y="{y + 12}" fill="#334155" font-size="11">{_safe(label)[:18]}</text>'
            f'<rect x="110" y="{y}" width="{bar_w}" height="{bar_height}" rx="4" fill="#3b82f6"/>'
            f'<text x="{115 + bar_w}" y="{y + 12}" fill="#64748b" font-size="11">{count}</text>'
        )
        y += bar_height + 10
    return f'<svg width="{width}" height="{y + 8}">{"".join(rows)}</svg>'


def render_html_report(applications: list[dict[str, Any]]) -> str:
    summary = build_analytics_summary(applications)
    buckets = summary["buckets"]
    generated = summary["generatedAt"][:10]
    rows_json = json.dumps(summary["rows"])

    stat_cards = "".join(
        f'<div class="card"><div class="label">{_safe(label)}</div><div class="value">{buckets.get(label, 0)}</div></div>'
        for label in ["Active", "Interview", "Offer", "Hired", "Rejected/Closed"]
    )

    table_rows = []
    for row in sorted(summary["rows"], key=lambda item: item.get("date") or "", reverse=True):
        bucket = row["bucket"]
        color = BUCKET_COLORS.get(bucket, "#94a3b8")
        notes = row["notes"][:80] + ("..." if len(row["notes"]) > 80 else "")
        url = row["url"]
        source_cell = f'<a href="{_safe(url)}" target="_blank" rel="noopener">Link</a>' if url.startswith("http") else _safe(url)
        table_rows.append(
            "<tr>"
            f"<td>{_safe(row['date'][:10] if row['date'] else '')}</td>"
            f"<td>{_safe(row['company'])}</td>"
            f"<td>{_safe(row['role'])}</td>"
            f"<td>{_safe(row['sector'])}</td>"
            f"<td>{_safe(row['channel'])}</td>"
            f'<td><span class="pill" style="background:{color}">{_safe(bucket)}</span></td>'
            f'<td title="{_safe(row["notes"])}">{_safe(notes)}</td>'
            f"<td>{source_cell}</td>"
            "</tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>CareerOS Job Search Dashboard</title>
<style>
body {{ font-family: Inter, system-ui, sans-serif; background:#f8fafc; color:#0f172a; margin:0; padding:24px; }}
header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; }}
h1 {{ margin:0; font-size:1.5rem; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:12px; margin-bottom:20px; }}
.card {{ background:#fff; border:1px solid #e2e8f0; border-radius:10px; padding:12px; }}
.label {{ color:#64748b; font-size:12px; text-transform:uppercase; }}
.value {{ font-size:24px; font-weight:700; margin-top:4px; }}
.charts {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:20px; }}
.panel {{ background:#fff; border:1px solid #e2e8f0; border-radius:10px; padding:16px; }}
.panel h2 {{ margin:0 0 12px; font-size:14px; color:#475569; }}
table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid #e2e8f0; border-radius:10px; overflow:hidden; }}
th, td {{ padding:10px 12px; border-bottom:1px solid #f1f5f9; font-size:13px; text-align:left; }}
th {{ background:#f8fafc; color:#475569; }}
.pill {{ color:#fff; padding:2px 8px; border-radius:999px; font-size:11px; }}
.filters {{ display:flex; gap:8px; margin:16px 0; }}
input, select {{ padding:8px 10px; border:1px solid #cbd5e1; border-radius:8px; }}
footer {{ margin-top:20px; color:#64748b; font-size:12px; }}
@media (max-width:900px) {{ .charts {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<header>
  <h1>Job Search Dashboard</h1>
  <div>Generated {generated}</div>
</header>
<section class="stats">
  <div class="card"><div class="label">Total</div><div class="value">{summary['total']}</div></div>
  {stat_cards}
</section>
<section class="charts">
  <div class="panel"><h2>Status distribution</h2>{_svg_doughnut(buckets)}</div>
  <div class="panel"><h2>By sector</h2>{_svg_hbar(summary['sectors'])}</div>
  <div class="panel"><h2>By channel</h2>{_svg_hbar(summary['channels'])}</div>
  <div class="panel"><h2>Rates</h2>
    <p>Interview rate: <strong>{summary['interviewRate']}%</strong></p>
    <p>Rejection rate (resolved): <strong>{summary['rejectionRate']}%</strong></p>
  </div>
</section>
<div class="filters">
  <input id="search" type="search" placeholder="Search company, role, sector..." oninput="filterRows()"/>
  <select id="statusFilter" onchange="filterRows()">
    <option value="">All statuses</option>
    <option>Active</option><option>Interview</option><option>Offer</option><option>Hired</option><option>Rejected/Closed</option>
  </select>
</div>
<table id="appsTable">
  <thead><tr><th>Date</th><th>Company</th><th>Role</th><th>Sector</th><th>Channel</th><th>Status</th><th>Notes</th><th>Source</th></tr></thead>
  <tbody>{''.join(table_rows)}</tbody>
</table>
<footer>Generated by CareerOS · {summary['generatedAt']}</footer>
<script>
const ROWS = {rows_json};
function filterRows() {{
  const q = document.getElementById('search').value.toLowerCase();
  const status = document.getElementById('statusFilter').value;
  const tbody = document.querySelector('#appsTable tbody');
  tbody.innerHTML = '';
  ROWS.filter(r => {{
    const hay = `${{r.company}} ${{r.role}} ${{r.sector}}`.toLowerCase();
    if (q && !hay.includes(q)) return false;
    if (status && r.bucket !== status) return false;
    return true;
  }}).forEach(r => {{
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${{(r.date||'').slice(0,10)}}</td><td>${{r.company}}</td><td>${{r.role}}</td><td>${{r.sector}}</td><td>${{r.channel}}</td><td>${{r.bucket}}</td><td>${{r.notes.slice(0,80)}}</td><td>${{r.url ? 'Link' : ''}}</td>`;
    tbody.appendChild(tr);
  }});
}}
</script>
</body>
</html>"""
