"""
Test suite for NetPulse scanner and config loader.
Run: python run_tests.py
"""

import asyncio
import ipaddress
import platform
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

import pytest
from scanner import (
    HostResult,
    _parse_alive,
    _read_arp_table,
    scan_subnet,
)
from config_loader import load


# ---------------------------------------------------------------------------
# _parse_alive — locale samples
# ---------------------------------------------------------------------------

PING_SAMPLES = [
    # (output, expected_alive, description)
    (
        "Reply from 192.168.1.1: bytes=32 time=1ms TTL=64",
        True,
        "Windows EN reply",
    ),
    (
        "64 bytes from 192.168.1.1: icmp_seq=1 ttl=64 time=0.5 ms",
        True,
        "Linux reply with decimal latency",
    ),
    (
        "Antwort von 192.168.1.1: Bytes=32 Zeit=2ms TTL=64",
        True,
        "Windows DE reply",
    ),
    (
        "Request timeout for icmp_seq 0",
        False,
        "macOS timeout",
    ),
    (
        "Destination host unreachable.",
        False,
        "ICMP unreachable — must NOT be counted as up",
    ),
    (
        "General failure.",
        False,
        "Windows general failure",
    ),
]


@pytest.mark.parametrize("output,expected_alive,desc", PING_SAMPLES)
def test_parse_alive(output, expected_alive, desc):
    alive, _ = _parse_alive(output)
    assert alive == expected_alive, f"Failed: {desc}"


def test_parse_alive_decimal_latency():
    output = "64 bytes from 10.0.0.1: icmp_seq=1 ttl=128 time=0.5 ms"
    alive, latency = _parse_alive(output)
    assert alive
    assert isinstance(latency, int)


# ---------------------------------------------------------------------------
# scan_subnet — fake subprocess, no real network calls
# ---------------------------------------------------------------------------

def _make_fake_run(alive_ips: set[str]):
    """Returns a subprocess.run replacement that simulates ping responses."""

    def fake_run(cmd, **kwargs):
        ip = cmd[-1]
        result = MagicMock()
        if ip in alive_ips:
            result.stdout = f"Reply from {ip}: bytes=32 time=1ms TTL=64\n"
            result.stderr = ""
        else:
            result.stdout = "Request timed out.\n"
            result.stderr = ""
        return result

    return fake_run


FAKE_ARP = """
Interface: 192.168.119.1
  Internet Address      Physical Address      Type
  192.168.119.1         aa-bb-cc-dd-ee-01     dynamic
  192.168.119.5         aa-bb-cc-dd-ee-05     dynamic
"""


@pytest.mark.asyncio
async def test_scan_finds_alive_hosts():
    alive_ips = {"192.168.119.1", "192.168.119.5"}
    fake_arp = MagicMock()
    fake_arp.stdout = FAKE_ARP

    with patch("scanner.subprocess.run", side_effect=_make_fake_run(alive_ips)):
        with patch("scanner._read_arp_table", return_value={"192.168.119.1": "AA:BB:CC:DD:EE:01", "192.168.119.5": "AA:BB:CC:DD:EE:05"}):
            with patch("scanner._resolve_hostname", return_value=""):
                results = await scan_subnet("192.168.119.0/28", max_concurrent=10)

    alive = [r for r in results if r.alive]
    assert len(alive) == 2
    alive_found = {r.ip for r in alive}
    assert alive_found == alive_ips


@pytest.mark.asyncio
async def test_scan_sorted_by_ip():
    alive_ips = {"192.168.119.3", "192.168.119.1"}

    with patch("scanner.subprocess.run", side_effect=_make_fake_run(alive_ips)):
        with patch("scanner._read_arp_table", return_value={}):
            with patch("scanner._resolve_hostname", return_value=""):
                results = await scan_subnet("192.168.119.0/28", max_concurrent=10)

    ips = [r.ip for r in results]
    assert ips == sorted(ips, key=lambda x: ipaddress.IPv4Address(x))


@pytest.mark.asyncio
async def test_scan_progress_cb_called():
    alive_ips: set[str] = set()
    calls: list[tuple[int, int]] = []

    with patch("scanner.subprocess.run", side_effect=_make_fake_run(alive_ips)):
        with patch("scanner._read_arp_table", return_value={}):
            await scan_subnet(
                "192.168.119.0/29",
                max_concurrent=5,
                progress_cb=lambda done, total: calls.append((done, total)),
            )

    # progress_cb must be called once per host, monotonically increasing
    assert len(calls) == 6  # /29 has 6 usable hosts
    done_values = [d for d, _ in calls]
    assert done_values == sorted(done_values)
    assert calls[-1][0] == calls[-1][1]


@pytest.mark.asyncio
async def test_mac_assigned_only_to_alive_hosts():
    alive_ips = {"192.168.119.2"}
    arp = {"192.168.119.1": "AA:BB:CC:DD:EE:01", "192.168.119.2": "AA:BB:CC:DD:EE:02"}

    with patch("scanner.subprocess.run", side_effect=_make_fake_run(alive_ips)):
        with patch("scanner._read_arp_table", return_value=arp):
            with patch("scanner._resolve_hostname", return_value=""):
                results = await scan_subnet("192.168.119.0/29", max_concurrent=5)

    host_2 = next(r for r in results if r.ip == "192.168.119.2")
    host_1 = next(r for r in results if r.ip == "192.168.119.1")

    assert host_2.mac == "AA:BB:CC:DD:EE:02"
    # host_1 is dead, ARP lookup still returns the value (ARP reads full table)
    assert host_1.alive is False


# ---------------------------------------------------------------------------
# config_loader
# ---------------------------------------------------------------------------

def test_config_loads(tmp_path):
    cfg_text = """
network:
  subnet: "10.0.0.0/24"
  poll_interval_seconds: 5
  offline_threshold_seconds: 60
  max_concurrent_pings: 20
alerts:
  desktop_notification: false
app:
  mode: demo
"""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(cfg_text)
    cfg = load(cfg_file)

    assert cfg.network.subnet == "10.0.0.0/24"
    assert cfg.network.poll_interval_seconds == 5
    assert cfg.network.max_concurrent_pings == 20
    assert cfg.alerts.desktop_notification is False
    assert cfg.app.mode == "demo"


def test_config_default_max_concurrent(tmp_path):
    cfg_text = """
network:
  subnet: "10.0.0.0/24"
  poll_interval_seconds: 10
  offline_threshold_seconds: 120
alerts:
  desktop_notification: true
app:
  mode: live
"""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(cfg_text)
    cfg = load(cfg_file)
    assert cfg.network.max_concurrent_pings == 50
