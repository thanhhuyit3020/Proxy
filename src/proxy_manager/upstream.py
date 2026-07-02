"""Mo ket noi TCP toi dest_host:dest_port, di qua mot upstream proxy (Proxy model)."""
from __future__ import annotations

import asyncio

from .http_client import http_connect
from .models import Proxy, ProxyScheme
from .socks_client import socks5_connect


async def open_via_upstream(
    proxy: Proxy, dest_host: str, dest_port: int, timeout: float = 10.0
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Tra ve (reader, writer) da san sang de doc/ghi du lieu ung dung toi dest,
    sau khi da chain qua upstream proxy cua profile."""
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(proxy.host, proxy.port), timeout=timeout
    )
    try:
        if proxy.scheme == ProxyScheme.SOCKS5:
            await asyncio.wait_for(
                socks5_connect(reader, writer, dest_host, dest_port, proxy.username, proxy.password),
                timeout=timeout,
            )
        elif proxy.scheme in (ProxyScheme.HTTP, ProxyScheme.HTTPS):
            await asyncio.wait_for(
                http_connect(reader, writer, dest_host, dest_port, proxy.username, proxy.password),
                timeout=timeout,
            )
        else:
            raise ValueError(f"unsupported upstream scheme: {proxy.scheme}")
    except Exception:
        writer.close()
        raise
    return reader, writer
