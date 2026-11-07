"""
Wake-on-LAN — sends a magic packet to wake a sleeping host.

Magic packet structure:
  6 bytes 0xFF followed by the target MAC address repeated 16 times.
  Sent as a UDP broadcast on port 9 (or 7).

Usage:
    from wol import wake
    wake("AA:BB:CC:DD:EE:FF")               # broadcast
    wake("AA:BB:CC:DD:EE:FF", "10.0.0.255") # directed broadcast
"""

from __future__ import annotations

import re
import socket
import struct


_MAC_RE = re.compile(r"^([0-9a-f]{2}[:\-]){5}[0-9a-f]{2}$", re.IGNORECASE)

WOL_PORT = 9


def _build_magic_packet(mac: str) -> bytes:
    mac_clean = mac.upper().replace("-", ":").replace(".", ":")
    if not _MAC_RE.match(mac_clean):
        raise ValueError(f"Invalid MAC address: {mac!r}")

    mac_bytes = bytes.fromhex(mac_clean.replace(":", ""))
    return b"\xff" * 6 + mac_bytes * 16


def wake(mac: str, broadcast: str = "255.255.255.255", port: int = WOL_PORT) -> None:
    """
    Send a Wake-on-LAN magic packet.

    mac       — target MAC in any common format (AA:BB:CC:DD:EE:FF or AA-BB-CC-DD-EE-FF)
    broadcast — destination IP; use the subnet broadcast for a directed packet
                (e.g. 192.168.119.255) so it does not cross router boundaries
    port      — typically 9 or 7
    """
    packet = _build_magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, port))
