"""Tests for reporter.py — CSV export, chart rendering, PDF export."""

from __future__ import annotations

import sys
import csv
import io
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest
import db
import reporter


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH_OVERRIDE", tmp_path / "test.db")
    db.init_db()


def _seed(ip: str, hostname: str, alive_count: int, down_count: int):
    t0 = datetime.utcnow() - timedelta(hours=12)
    for i in range(alive_count):
        db.record_poll(ip, True, 5, "AA:BB:CC:DD:EE:01", hostname,
                       polled_at=t0 + timedelta(seconds=i * 10))
    for i in range(down_count):
        db.record_poll(ip, False, None, "AA:BB:CC:DD:EE:01", hostname,
                       polled_at=t0 + timedelta(seconds=(alive_count + i) * 10))


def test_csv_export_columns(tmp_path):
    _seed("10.0.0.1", "pc1", 90, 10)
    out = tmp_path / "report.csv"
    reporter.export_csv(out, days=1)

    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert len(rows) == 1
    row = rows[0]
    assert row["IP"] == "10.0.0.1"
    assert row["Hostname"] == "pc1"
    assert float(row["Uptime %"]) == pytest.approx(90.0, abs=0.5)
    assert int(row["Down Count"]) == 10


def test_csv_export_multiple_hosts(tmp_path):
    _seed("10.0.0.1", "pc1", 80, 20)
    _seed("10.0.0.2", "pc2", 100, 0)
    out = tmp_path / "report.csv"
    reporter.export_csv(out, days=1)

    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert len(rows) == 2


def test_csv_empty_when_no_data(tmp_path):
    out = tmp_path / "empty.csv"
    reporter.export_csv(out, days=1)
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert rows == []


def test_uptime_chart_returns_png_bytes():
    _seed("10.0.0.1", "pc1", 90, 10)
    png = reporter.render_uptime_chart(days=1)
    assert isinstance(png, bytes)
    assert png[:4] == b"\x89PNG"


def test_uptime_chart_no_data_still_returns_png():
    png = reporter.render_uptime_chart(days=1)
    assert png[:4] == b"\x89PNG"


def test_latency_chart_returns_png():
    _seed("10.0.0.5", "pc5", 20, 0)
    png = reporter.render_latency_chart("10.0.0.5", days=7)
    assert png[:4] == b"\x89PNG"


def test_pdf_export_creates_file(tmp_path):
    _seed("10.0.0.1", "pc1", 50, 5)
    out = tmp_path / "report.pdf"
    reporter.export_pdf(out, days=1)
    assert out.exists()
    assert out.stat().st_size > 1000
    # PDF magic bytes
    assert open(out, "rb").read(4) == b"%PDF"
