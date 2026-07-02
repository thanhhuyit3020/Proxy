"""Data models cho Proxy va Profile."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class ProxyScheme(str, Enum):
    HTTP = "http"
    HTTPS = "https"
    SOCKS5 = "socks5"


class ProxyStatus(str, Enum):
    UNKNOWN = "unknown"
    ALIVE = "alive"
    DEAD = "dead"


class ProfileStatus(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class Proxy:
    id: int | None
    scheme: ProxyScheme
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    status: ProxyStatus = ProxyStatus.UNKNOWN
    latency_ms: float | None = None
    observed_ip: str | None = None
    last_checked_at: float | None = None

    def label(self) -> str:
        return f"{self.scheme.value}://{self.host}:{self.port}"


@dataclass
class Profile:
    id: int | None
    name: str
    local_port: int
    proxy_ids: list[int] = field(default_factory=list)
    active_proxy_id: int | None = None
    assigned_process_names: list[str] = field(default_factory=list)
    status: ProfileStatus = ProfileStatus.STOPPED
    auto_rotate_enabled: bool = False
    auto_rotate_seconds: int = 600
    created_at: float = field(default_factory=time.time)
