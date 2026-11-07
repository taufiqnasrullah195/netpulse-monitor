"""
NetPulse monitoring engine.

Runs a background thread that:
  1. Calls scanner.scan_subnet_sync() every poll_interval_seconds
  2. Tracks per-host state transitions (up → down, down → up)
  3. Writes every poll result to SQLite via db.record_poll()
  4. Emits event_log entries on state changes
  5. Triggers alerts.notify() when a host exceeds offline_threshold_seconds
  6. Pushes updates to a queue.Queue for the GUI to drain

The GUI imports this module and calls:
    engine = MonitorEngine(config)
    engine.start(update_queue)   # non-blocking
    engine.stop()

State machine per host:
    UNKNOWN → UP (first successful ping)
    UP      → DOWN (missed ping)
    DOWN    → UP   (ping recovered)
    DOWN stays DOWN until recovered; threshold alert fires once per outage.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import db
import scanner
from config_loader import Config


@dataclass
class HostState:
    ip: str
    alive: bool
    latency_ms: Optional[int]
    mac: str
    hostname: str
    # ISO timestamp of last state change
    changed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    # Seconds since last seen alive (for threshold alert)
    offline_seconds: float = 0.0
    # True if threshold alert already fired for this outage
    alert_fired: bool = False


@dataclass
class EngineUpdate:
    """Payload pushed to the GUI queue after each scan cycle."""
    hosts: list[HostState]
    events: list[db.EventRow]
    scan_duration_s: float
    timestamp: str


class MonitorEngine:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._state: dict[str, HostState] = {}
        self._gui_queue: Optional[queue.Queue] = None
        self._on_alert: Optional[Callable[[str, str], None]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(
        self,
        gui_queue: Optional[queue.Queue] = None,
        on_alert: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self._gui_queue = gui_queue
        self._on_alert = on_alert
        self._stop_event.clear()
        db.init_db()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="netpulse-monitor")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            start = time.monotonic()
            self._poll()
            elapsed = time.monotonic() - start
            sleep_time = max(0, self._config.network.poll_interval_seconds - elapsed)
            self._stop_event.wait(timeout=sleep_time)

    def _poll(self) -> None:
        try:
            results = scanner.scan_subnet_sync(
                self._config.network.subnet,
                max_concurrent=self._config.network.max_concurrent_pings,
            )
        except Exception:
            return

        now = datetime.utcnow()
        new_events: list[db.EventRow] = []

        for host in results:
            try:
                db.record_poll(
                    ip=host.ip,
                    alive=host.alive,
                    latency_ms=host.latency_ms,
                    mac=host.mac,
                    hostname=host.hostname,
                    polled_at=now,
                )
            except Exception:
                pass

            prev = self._state.get(host.ip)
            state = self._update_state(host, prev, now)
            self._state[host.ip] = state

            event = self._detect_transition(host, prev, state, now)
            if event:
                new_events.append(event)

            self._check_threshold(state)

        if self._gui_queue is not None:
            update = EngineUpdate(
                hosts=list(self._state.values()),
                events=new_events,
                scan_duration_s=0.0,
                timestamp=now.isoformat(),
            )
            try:
                self._gui_queue.put_nowait(update)
            except queue.Full:
                pass

    def _update_state(
        self,
        host: scanner.HostResult,
        prev: Optional[HostState],
        now: datetime,
    ) -> HostState:
        if prev is None:
            return HostState(
                ip=host.ip,
                alive=host.alive,
                latency_ms=host.latency_ms,
                mac=host.mac,
                hostname=host.hostname,
                changed_at=now.isoformat(),
                offline_seconds=0.0,
                alert_fired=False,
            )

        state_changed = prev.alive != host.alive
        offline_seconds = (
            0.0
            if host.alive
            else prev.offline_seconds + self._config.network.poll_interval_seconds
        )
        alert_fired = prev.alert_fired if not host.alive else False

        return HostState(
            ip=host.ip,
            alive=host.alive,
            latency_ms=host.latency_ms,
            mac=host.mac or prev.mac,
            hostname=host.hostname or prev.hostname,
            changed_at=now.isoformat() if state_changed else prev.changed_at,
            offline_seconds=offline_seconds,
            alert_fired=alert_fired,
        )

    def _detect_transition(
        self,
        host: scanner.HostResult,
        prev: Optional[HostState],
        state: HostState,
        now: datetime,
    ) -> Optional[db.EventRow]:
        if prev is None:
            return None

        label = state.hostname or state.ip

        if prev.alive and not host.alive:
            event_text = f"{label} went offline"
            try:
                db.record_event(host.ip, state.hostname, event_text, now)
            except Exception:
                pass
            return db.EventRow(
                ip=host.ip,
                hostname=state.hostname,
                event=event_text,
                occurred_at=now.isoformat(),
            )

        if not prev.alive and host.alive:
            downtime = int(state.offline_seconds)
            event_text = f"{label} came back online (was down ~{downtime}s)"
            try:
                db.record_event(host.ip, state.hostname, event_text, now)
            except Exception:
                pass
            return db.EventRow(
                ip=host.ip,
                hostname=state.hostname,
                event=event_text,
                occurred_at=now.isoformat(),
            )

        return None

    def _check_threshold(self, state: HostState) -> None:
        if state.alive or state.alert_fired:
            return
        threshold = self._config.network.offline_threshold_seconds
        if state.offline_seconds >= threshold:
            state.alert_fired = True
            label = state.hostname or state.ip
            if self._on_alert:
                try:
                    self._on_alert(state.ip, f"{label} offline > {threshold}s")
                except Exception:
                    pass
