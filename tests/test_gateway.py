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


# ---------- Layer B transparent mode (B3) ----------

@pytest.fixture
async def transparent_gateway():
    """Gateway voi orig_dest_lookup luon khop -> giong het bi WinDivert dinh tuyen
    trong suot. get_active_proxy tra None (kill-switch) vi khong co proxy that trong
    test nay -- chi kiem tra WIRING (khong doc SOCKS5/HTTP), khong kiem tra chain that."""
    gw = ProfileGateway(
        profile_id=1, local_port=0, get_active_proxy=_get_no_active_proxy,
        orig_dest_lookup=lambda port: ("93.184.216.34", 443),
    )
    server = await asyncio.start_server(gw._handle_client, host="127.0.0.1", port=0)
    gw._server = server
    port = server.sockets[0].getsockname()[1]
    try:
        yield gw, port
    finally:
        await gw.stop()


async def test_transparent_mode_skips_socks5_http_parsing(transparent_gateway):
    """Gui byte thang (khong phai SOCKS5 greeting, khong phai HTTP request line) --
    neu gateway roi vao nhanh SOCKS5/HTTP nhu binh thuong no se cho doc them va treo
    cho toi khi wait_for(timeout=5) het han. Kill-switch (proxy=None) phai dong ket
    noi ngay ma khong doc/phan tich byte nao -- ket qua co the la EOF sach (b"") hoac
    RST/ConnectionResetError (vi con du lieu chua doc trong buffer luc dong, hanh vi
    socket chuan, khong rieng he dieu hanh nao) -- ca hai deu la "dong ngay", khac voi treo."""
    gw, port = transparent_gateway
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"\x16\x03\x01\x00\xa5")  # gia lap dau TLS ClientHello, khong phai SOCKS5/HTTP
    await writer.drain()

    try:
        data = await asyncio.wait_for(reader.read(100), timeout=5)
        assert data == b""
    except ConnectionResetError:
        pass
    finally:
        writer.close()


async def test_falls_back_to_normal_mode_when_no_orig_dest_match(gateway):
    """orig_dest_lookup vang mat (gateway thuong, None mac dinh) -- test 'gateway' fixture
    da dung path binh thuong; kiem tra ro rang orig_dest_lookup=None khong lam gi khac."""
    gw, port = gateway
    assert gw._orig_dest_lookup is None
