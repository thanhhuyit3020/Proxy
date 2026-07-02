"""Import proxy list va health check."""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from .models import Proxy, ProxyScheme, ProxyStatus
from .upstream import open_via_upstream

IP_ECHO_HOST = "api.ipify.org"
IP_ECHO_PORT = 80

_URI_RE = re.compile(
    r"^(?P<scheme>https?|socks5)://(?:(?P<user>[^:@]+):(?P<pass>[^@]*)@)?(?P<host>[^:]+):(?P<port>\d+)$"
)


def parse_proxy_line(line: str) -> Proxy | None:
    """Ho tro 2 dinh dang: scheme://user:pass@host:port  va  host:port:user:pass"""
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    m = _URI_RE.match(line)
    if m:
        return Proxy(
            id=None,
            scheme=ProxyScheme(m.group("scheme").replace("https", "http")),
            host=m.group("host"),
            port=int(m.group("port")),
            username=m.group("user"),
            password=m.group("pass"),
        )

    parts = line.split(":")
    if len(parts) >= 2:
        host, port = parts[0], parts[1]
        username = parts[2] if len(parts) > 2 else None
        password = parts[3] if len(parts) > 3 else None
        return Proxy(
            id=None,
            scheme=ProxyScheme.HTTP,
            host=host,
            port=int(port),
            username=username,
            password=password,
        )

    return None


def parse_proxy_file(path: Path | str) -> list[Proxy]:
    text = Path(path).read_text(encoding="utf-8")
    proxies = []
    for line in text.splitlines():
        proxy = parse_proxy_line(line)
        if proxy:
            proxies.append(proxy)
    return proxies


async def health_check(proxy: Proxy, timeout: float = 10.0) -> Proxy:
    """Ket noi qua proxy toi ip-echo endpoint, do latency, lay IP thoat thuc te."""
    started = time.monotonic()
    try:
        reader, writer = await open_via_upstream(proxy, IP_ECHO_HOST, IP_ECHO_PORT, timeout=timeout)
        try:
            request = (
                f"GET / HTTP/1.1\r\nHost: {IP_ECHO_HOST}\r\n"
                "Connection: close\r\nUser-Agent: proxy-manager-healthcheck\r\n\r\n"
            )
            writer.write(request.encode())
            await writer.drain()
            raw = await asyncio.wait_for(reader.read(4096), timeout=timeout)
        finally:
            writer.close()

        latency_ms = (time.monotonic() - started) * 1000
        body = raw.split(b"\r\n\r\n", 1)[-1].decode(errors="replace").strip()
        if not _looks_like_ip(body):
            raise ValueError(f"unexpected ip-echo response: {body!r}")

        proxy.status = ProxyStatus.ALIVE
        proxy.latency_ms = round(latency_ms, 1)
        proxy.observed_ip = body
    except Exception:
        proxy.status = ProxyStatus.DEAD
        proxy.latency_ms = None
        proxy.observed_ip = None
    proxy.last_checked_at = time.time()
    return proxy


def _looks_like_ip(value: str) -> bool:
    return bool(re.match(r"^\d{1,3}(\.\d{1,3}){3}$", value)) or ":" in value


async def health_check_all(proxies: list[Proxy], concurrency: int = 20) -> list[Proxy]:
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(p: Proxy) -> Proxy:
        async with sem:
            return await health_check(p)

    return await asyncio.gather(*(_bounded(p) for p in proxies))
