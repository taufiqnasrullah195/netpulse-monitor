"""
NetPulse reporter — daily uptime summary + export.

Produces:
  - CSV report: one row per host with uptime%, total polls, down count
  - PDF report: formatted table + uptime bar chart
  - In-memory chart data for the GUI detail drawer

Dependencies: matplotlib (chart rendering), reportlab (PDF).
Both are optional for the core engine — this module imports them lazily
so the rest of the app works even if they are not installed.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import db


@dataclass
class HostSummary:
    ip: str
    hostname: str
    uptime_pct: float
    total_polls: int
    down_count: int
    avg_latency_ms: Optional[float]


def _since_iso(days: int = 1) -> str:
    return (datetime.utcnow() - timedelta(days=days)).isoformat()


def _summarize(since_iso: str) -> list[HostSummary]:
    latest = {r.ip: r for r in db.latest_status_per_host()}
    if not latest:
        return []

    summaries: list[HostSummary] = []
    for ip, latest_row in latest.items():
        history = db.status_history(ip, limit=10_000)
        recent = [r for r in history if r.polled_at >= since_iso]
        if not recent:
            continue

        total = len(recent)
        down = sum(1 for r in recent if not r.alive)
        latencies = [r.latency_ms for r in recent if r.latency_ms is not None]
        avg_lat = round(sum(latencies) / len(latencies), 1) if latencies else None
        uptime = round(((total - down) / total) * 100, 2)

        summaries.append(
            HostSummary(
                ip=ip,
                hostname=latest_row.hostname,
                uptime_pct=uptime,
                total_polls=total,
                down_count=down,
                avg_latency_ms=avg_lat,
            )
        )

    summaries.sort(key=lambda s: s.uptime_pct)
    return summaries


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def export_csv(path: Path, days: int = 1) -> Path:
    since = _since_iso(days)
    summaries = _summarize(since)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "IP", "Hostname", "Uptime %",
            "Total Polls", "Down Count", "Avg Latency (ms)",
            "Report Period (days)",
        ])
        for s in summaries:
            writer.writerow([
                s.ip, s.hostname, s.uptime_pct,
                s.total_polls, s.down_count,
                s.avg_latency_ms if s.avg_latency_ms is not None else "",
                days,
            ])

    return path


# ---------------------------------------------------------------------------
# Chart — uptime bar chart (returns PNG bytes for GUI embedding)
# ---------------------------------------------------------------------------

def render_uptime_chart(days: int = 1) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    since = _since_iso(days)
    summaries = _summarize(since)

    if not summaries:
        fig, ax = plt.subplots(figsize=(6, 2))
        ax.text(0.5, 0.5, "No data", ha="center", va="center")
        ax.axis("off")
    else:
        labels = [s.hostname or s.ip for s in summaries]
        values = [s.uptime_pct for s in summaries]
        colors = ["#A94F1C" if v < 95 else "#2E7D32" for v in values]

        fig, ax = plt.subplots(figsize=(max(6, len(labels) * 0.8), 4))
        bars = ax.barh(labels, values, color=colors)
        ax.set_xlim(0, 100)
        ax.set_xlabel("Uptime %")
        ax.set_title(f"Host Uptime — Last {days} day(s)")
        ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=8)
        fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=96)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def render_latency_chart(ip: str, days: int = 7) -> bytes:
    """Latency over time for one host — used in the detail drawer."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    since = _since_iso(days)
    history = db.status_history(ip, limit=10_000)
    recent = [r for r in history if r.polled_at >= since and r.latency_ms is not None]

    fig, ax = plt.subplots(figsize=(6, 3))
    if recent:
        times = [r.polled_at for r in reversed(recent)]
        lats = [r.latency_ms for r in reversed(recent)]
        ax.plot(times, lats, linewidth=1, color="#A94F1C")
        ax.set_ylabel("Latency (ms)")
        ax.set_title(f"{ip} — Latency (last {days}d)")
        ax.tick_params(axis="x", rotation=30, labelsize=7)
    else:
        ax.text(0.5, 0.5, "No data", ha="center", va="center")
        ax.axis("off")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=96)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------

def export_pdf(path: Path, days: int = 1) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image,
    )
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm

    since = _since_iso(days)
    summaries = _summarize(since)
    generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("NetPulse — Daily Report", styles["Title"]))
    elements.append(Paragraph(f"Generated: {generated_at} | Period: last {days} day(s)", styles["Normal"]))
    elements.append(Spacer(1, 0.5 * cm))

    # Uptime chart
    chart_bytes = render_uptime_chart(days)
    chart_buf = io.BytesIO(chart_bytes)
    elements.append(Image(chart_buf, width=15 * cm, height=8 * cm))
    elements.append(Spacer(1, 0.5 * cm))

    # Table
    header = ["IP", "Hostname", "Uptime %", "Polls", "Down", "Avg Lat (ms)"]
    rows = [header] + [
        [
            s.ip,
            s.hostname or "-",
            f"{s.uptime_pct:.1f}%",
            str(s.total_polls),
            str(s.down_count),
            f"{s.avg_latency_ms:.1f}" if s.avg_latency_ms else "-",
        ]
        for s in summaries
    ]

    tbl = Table(rows, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#A94F1C")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F0E2D8")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DAD8D3")),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
    ]))
    elements.append(tbl)

    doc = SimpleDocTemplate(str(path), pagesize=A4)
    doc.build(elements)
    return path
