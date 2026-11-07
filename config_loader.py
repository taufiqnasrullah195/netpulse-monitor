"""
NetPulse configuration loader.
Reads config.yaml from the project root and exposes a typed Config object.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).parent / "config.yaml"


@dataclass
class NetworkConfig:
    subnet: str
    poll_interval_seconds: int
    offline_threshold_seconds: int
    max_concurrent_pings: int


@dataclass
class AlertConfig:
    desktop_notification: bool


@dataclass
class AppConfig:
    mode: str  # "demo" | "live"


@dataclass
class Config:
    network: NetworkConfig
    alerts: AlertConfig
    app: AppConfig


def load(path: Path = CONFIG_PATH) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    net = raw["network"]
    return Config(
        network=NetworkConfig(
            subnet=net["subnet"],
            poll_interval_seconds=int(net["poll_interval_seconds"]),
            offline_threshold_seconds=int(net["offline_threshold_seconds"]),
            max_concurrent_pings=int(net.get("max_concurrent_pings", 50)),
        ),
        alerts=AlertConfig(
            desktop_notification=bool(raw["alerts"]["desktop_notification"]),
        ),
        app=AppConfig(
            mode=raw["app"]["mode"],
        ),
    )
