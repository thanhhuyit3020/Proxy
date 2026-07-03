"""End-to-end test cho kill-switch fail-closed: khong co proxy active thi gateway
phai tu choi ket noi, khong duoc fallback ra ket noi truc tiep (IP that)."""
from __future__ import annotations

import asyncio

import pytest

from proxy_manager.gateway import ProfileGateway


async def _get_no_active_proxy():
    return None


@pytest.fixture
async def gateway():
    gw = ProfileGateway(profile_id=1, local_port=0, get_active_proxy=_get_no_active_proxy)
    server = await asyncio.start_server(gw._handle_client, host="127.0.0.1", port=0)
    gw._server = server
    port = server.sockets[0].getsockname()[1]
    try:
        yield gw, port
    finally:
        await gw.stop()


async def test_http_connect_refused_when_no_active_proxy(gateway):
    gw, port = gateway
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
    await writer.drain()

    response = await asyncio.wait_for(reader.read(200), timeout=5)
    writer.close()

    assert response.startswith(b"HTTP/1.1 502")


async def test_plain_http_refused_when_no_active_proxy(gateway):
    gw, port = gateway
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n")
    await writer.drain()

    response = await asyncio.wait_for(reader.read(200), timeout=5)
    writer.close()

    assert response.startswith(b"HTTP/1.1 502")


async def test_socks5_refused_when_no_active_proxy(gateway):
    gw, port = gateway
    reader, writer = await asyncio.open_connection("127.0.0.1", port)

    writer.write(b"\x05\x01\x00")  # greeting: 1 method, no-auth
    await writer.drain()
    method_resp = await asyncio.wait_for(reader.readexactly(2), timeout=5)
    assert method_resp == b"\x05\x00"

    # CONNECT request toi example.com:443 qua domain name (atyp=3)
    host = b"example.com"
    writer.write(b"\x05\x01\x00\x03" + bytes([len(host)]) + host + b"\x01\xbb")
    await writer.drain()
    reply = await asyncio.wait_for(reader.readexactly(10), timeout=5)
    writer.close()

    assert reply[0] == 0x05
    assert reply[1] != 0x00  # phai la ma loi, khong duoc la 0x00 (thanh cong)
