"""HTTP CONNECT client toi upstream HTTP/HTTPS proxy."""
from __future__ import annotations

import asyncio
import base64


class HttpConnectError(Exception):
    pass


async def http_connect(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    dest_host: str,
    dest_port: int,
    username: str | None = None,
    password: str | None = None,
) -> None:
    """Gui HTTP CONNECT toi upstream proxy tren mot ket noi TCP da mo.
    Sau khi tra ve thanh cong, reader/writer dung duoc de relay du lieu (TLS tunnel)."""
    lines = [f"CONNECT {dest_host}:{dest_port} HTTP/1.1", f"Host: {dest_host}:{dest_port}"]
    if username:
        token = base64.b64encode(f"{username}:{password or ''}".encode()).decode()
        lines.append(f"Proxy-Authorization: Basic {token}")
    lines.append("Proxy-Connection: Keep-Alive")
    lines.append("")
    lines.append("")
    writer.write("\r\n".join(lines).encode())
    await writer.drain()

    status_line = await reader.readline()
    if not status_line:
        raise HttpConnectError("upstream closed connection during CONNECT")
    parts = status_line.decode(errors="replace").split(None, 2)
    if len(parts) < 2 or not parts[1].startswith("2"):
        raise HttpConnectError(f"upstream CONNECT failed: {status_line!r}")

    # tieu thu het headers cho den dong trong
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break
