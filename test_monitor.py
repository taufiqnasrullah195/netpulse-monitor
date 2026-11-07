"""
Tests for monitor.py and db.py.
Run via: python run_tests.py
"""

from __future__ import annotations

import sys
import time
import queue
import threading
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

import pytest
import db
from monitor import MonitorEngine, HostState, EngineUpdate
from scanner import HostResult
from config_loader import Config, NetworkConfig, AlertConfig, AppConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH_OVERRIDE", tmp_path / "test.db")
    db.init_db()


def _make_config(poll_interval=1, threshold=5) -> Config:
    return Config(
        network=NetworkConfig(
            subnet="192.168.119.0/28",
            poll_interval_seconds=poll_interval,
            offline_threshold_seconds=threshold,
            max_concurrent_pings=10,
        ),
        alerts=AlertConfig(desktop_notification=False),
        app=AppConfig(mode="demo"),
    )


def _host(ip: str, alive: bool, latency: int = 1) -> HostResult:
    return HostResult(ip=ip, mac="AA:BB:CC:DD:EE:01", hostname="client", alive=alive, latency_ms=latency if alive else None)


# ---------------------------------------------------------------------------
# db.py tests
# ---------------------------------------------------------------------------

def test_db_record_and_retrieve():
    db.record_poll("10.0.0.1", True, 5, "aa:bb:cc:dd:ee:01", "host1")
    db.record_poll("10.0.0.1", False, None, "aa:bb:cc:dd:ee:01", "host1")

    history = db.status_history("10.0.0.1")
    assert len(history) == 2
    assert history[0].alive is False
    assert history[1].alive is True


def test_db_latest_status_per_host():
    db.record_poll("10.0.0.1", True, 1, "", "h1")
    db.record_poll("10.0.0.2", False, None, "", "h2")
    db.record_poll("10.0.0.1", False, None, "", "h1")

    latest = {r.ip: r for r in db.latest_status_per_host()}
    assert latest["10.0.0.1"].alive is False
    assert latest["10.0.0.2"].alive is False


def test_db_uptime_percent():
    t0 = datetime(2026, 1, 1, 0, 0, 0)
    for i in range(10):
        db.record_poll("10.0.0.1", i < 7, None, "", "", polled_at=t0 + timedelta(seconds=i))

    pct = db.uptime_percent("10.0.0.1", t0.isoformat())
    assert pct == 70.0


def test_db_event_log():
    db.record_event("10.0.0.1", "host1", "went offline")
    db.record_event("10.0.0.1", "host1", "came back online")

    events = db.recent_events()
    assert len(events) == 2
    assert "online" in events[0].event


def test_db_uptime_percent_no_data():
    pct = db.uptime_percent("99.0.0.1", "2026-01-01T00:00:00")
    assert pct == 0.0


# ---------------------------------------------------------------------------
# monitor.py — state machine tests (no real network)
# ---------------------------------------------------------------------------

def _make_engine(config=None) -> MonitorEngine:
    return MonitorEngine(config or _make_config())


def _run_one_poll(engine: MonitorEngine, hosts: list[HostResult]) -> EngineUpdate:
    q: queue.Queue = queue.Queue()
    engine._gui_queue = q
    db.init_db()

    with patch("scanner.scan_subnet_sync", return_value=hosts):
        engine._poll()

    return q.get_nowait()


def test_state_transition_up_to_down():
    engine = _make_engine()
    update1 = _run_one_poll(engine, [_host("10.0.0.1", True)])
    assert not update1.events

    update2 = _run_one_poll(engine, [_host("10.0.0.1", False)])
    assert len(update2.events) == 1
    assert "offline" in update2.events[0].event


def test_state_transition_down_to_up():
    engine = _make_engine()
    _run_one_poll(engine, [_host("10.0.0.1", True)])
    _run_one_poll(engine, [_host("10.0.0.1", False)])
    update = _run_one_poll(engine, [_host("10.0.0.1", True)])
    assert any("online" in e.event for e in update.events)


def test_no_duplicate_events_same_state():
    engine = _make_engine()
    _run_one_poll(engine, [_host("10.0.0.1", True)])
    _run_one_poll(engine, [_host("10.0.0.1", True)])
    update = _run_one_poll(engine, [_host("10.0.0.1", True)])
    assert not update.events


def test_threshold_alert_fires_once():
    alerts_fired: list[tuple[str, str]] = []
    engine = _make_engine(_make_config(poll_interval=3, threshold=5))

    with patch("scanner.scan_subnet_sync", return_value=[_host("10.0.0.1", True)]):
        engine._poll()

    for _ in range(4):
        with patch("scanner.scan_subnet_sync", return_value=[_host("10.0.0.1", False)]):
            engine._on_alert = lambda ip, msg: alerts_fired.append((ip, msg))
            engine._poll()

    assert len(alerts_fired) == 1
    assert "10.0.0.1" in alerts_fired[0][0]


def test_threshold_resets_after_recovery():
    alerts_fired: list[str] = []
    engine = _make_engine(_make_config(poll_interval=3, threshold=3))

    with patch("scanner.scan_subnet_sync", return_value=[_host("10.0.0.1", True)]):
        engine._poll()

    # Go down, alert fires
    with patch("scanner.scan_subnet_sync", return_value=[_host("10.0.0.1", False)]):
        engine._on_alert = lambda ip, msg: alerts_fired.append(ip)
        engine._poll()
        engine._poll()

    # Recover, go down again — should fire again (not suppressed)
    with patch("scanner.scan_subnet_sync", return_value=[_host("10.0.0.1", True)]):
        engine._poll()

    with patch("scanner.scan_subnet_sync", return_value=[_host("10.0.0.1", False)]):
        engine._poll()
        engine._poll()

    assert len(alerts_fired) == 2


def test_mac_preserved_when_host_disappears_from_arp():
    engine = _make_engine()
    h = HostResult(ip="10.0.0.1", mac="AA:BB:CC:DD:EE:FF", hostname="pc1", alive=True, latency_ms=1)
    _run_one_poll(engine, [h])

    h2 = HostResult(ip="10.0.0.1", mac="", hostname="", alive=False, latency_ms=None)
    _run_one_poll(engine, [h2])

    state = engine._state["10.0.0.1"]
    assert state.mac == "AA:BB:CC:DD:EE:FF"
    assert state.hostname == "pc1"


def test_gui_queue_receives_update():
    engine = _make_engine()
    q: queue.Queue = queue.Queue()
    engine._gui_queue = q

    with patch("scanner.scan_subnet_sync", return_value=[_host("10.0.0.1", True)]):
        engine._poll()

    assert not q.empty()
    update: EngineUpdate = q.get_nowait()
    assert len(update.hosts) == 1
    assert update.hosts[0].ip == "10.0.0.1"
