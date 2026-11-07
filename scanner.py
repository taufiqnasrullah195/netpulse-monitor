"""
NetPulse network scanner.

Responsibilities:
- ICMP ping all hosts in a subnet concurrently via asyncio
- ARP table lookup to resolve MAC addresses (Windows: `arp -a`)
- Returns a list of HostResult dataclasses

Concurrency: bounded by a semaphore (max_concurrent_pings from config).
Latency: one ping per host, 1s timeout. Full /24 scan completes in ~5s.
"""

from __future__ import annotations

import asyncio
import ipaddress
import platform
import re
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class HostResult:
    ip: str
    mac: str        # empty string if not in ARP table
    hostname: str   # empty string if reverse DNS fails
    alive: bool
    latency_ms: Optional[int]  # None when host is down


def _ping_flags() -> list[str]:
    if platform.system() == "Windows":
        return ["-n", "1", "-w", "1000"]
    return ["-c", "1", "-W", "1"]


def _parse_alive(output: str) -> tuple[bool, Optional[int]]:
    # Presence of TTL in the reply line is the reliable up-indicator across
    # Windows/Linux locales (stats-based parsing misidentifies ICMP unreachables).
    if "ttl=" not in output.lower():
        return False, None

    match = re.search(r"[Tt]ime[=<]([\d.]+)", output)
    latency = int(float(match.group(1))) if match else None
    return True, latency


async def _ping_host(
    ip: str,
    semaphore: asyncio.Semaphore,
) -> tuple[str, bool, Optional[int]]:
    async with semaphore:
        loop = asyncio.get_event_loop()
        flags = _ping_flags()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["ping"] + flags + [ip],
                capture_output=True,
                text=True,
                timeout=3,
            ),
        )
        alive, latency = _parse_alive(result.stdout + result.stderr)
        return ip, alive, latency


def _read_arp_table() -> dict[str, str]:
    """Returns {ip: mac} from the OS ARP cache."""
    try:
        result = subprocess.run(
            ["arp", "-a"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return {}

    table: dict[str, str] = {}
    # Windows:  192.168.1.1   aa-bb-cc-dd-ee-ff  dynamic
    # Linux:    192.168.1.1   ether  aa:bb:cc:dd:ee:ff  C  eth0
    mac_pattern = re.compile(
        r"([\d.]+)\s+.*?([0-9a-f]{2}[-:][0-9a-f]{2}[-:][0-9a-f]{2}"
        r"[-:][0-9a-f]{2}[-:][0-9a-f]{2}[-:][0-9a-f]{2})",
        re.IGNORECASE,
    )
    for line in result.stdout.splitlines():
        m = mac_pattern.search(line)
        if m:
            ip, mac = m.group(1), m.group(2).upper().replace("-", ":")
            table[ip] = mac
    return table


async def _resolve_hostname(ip: str) -> str:
    try:
        loop = asyncio.get_event_loop()
        host, *_ = await loop.run_in_executor(
            None,
            lambda: __import__("socket").gethostbyaddr(ip),
        )
        return host
    except Exception:
        return ""


async def scan_subnet(
    subnet: str,
    max_concurrent: int = 50,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> list[HostResult]:
    """
    Ping every host in `subnet` concurrently and return HostResult list.
    Only alive hosts get an ARP and reverse-DNS lookup.

    progress_cb(done, total) fires after each host completes.
    """
    network = ipaddress.IPv4Network(subnet, strict=False)
    hosts = [str(h) for h in network.hosts()]
    total = len(hosts)

    semaphore = asyncio.Semaphore(max_concurrent)
    done_count = 0

    ping_tasks = [_ping_host(ip, semaphore) for ip in hosts]
    ping_results: list[tuple[str, bool, Optional[int]]] = []

    for coro in asyncio.as_completed(ping_tasks):
        ip, alive, latency = await coro
        ping_results.append((ip, alive, latency))
        done_count += 1
        if progress_cb:
            progress_cb(done_count, total)

    arp_table = _read_arp_table()

    resolve_tasks = {
        ip: _resolve_hostname(ip)
        for ip, alive, _ in ping_results
        if alive
    }
    resolved = {}
    if resolve_tasks:
        resolved_values = await asyncio.gather(*resolve_tasks.values())
        resolved = dict(zip(resolve_tasks.keys(), resolved_values))

    results: list[HostResult] = []
    for ip, alive, latency in ping_results:
        results.append(
            HostResult(
                ip=ip,
                mac=arp_table.get(ip, ""),
                hostname=resolved.get(ip, ""),
                alive=alive,
                latency_ms=latency,
            )
        )

    results.sort(key=lambda h: ipaddress.IPv4Address(h.ip))
    return results


# Synchronous wrapper for callers that cannot run an event loop directly
def scan_subnet_sync(
    subnet: str,
    max_concurrent: int = 50,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> list[HostResult]:
    return asyncio.run(scan_subnet(subnet, max_concurrent, progress_cb))
