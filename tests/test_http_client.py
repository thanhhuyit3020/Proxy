from __future__ import annotations

import base64

import pytest

from proxy_manager.http_client import HttpConnectError, http_connect


async def test_connect_success(reader_factory, fake_writer):
    data = b"HTTP/1.1 200 Connection Established\r\nProxy-Agent: test\r\n\r\n"
    reader = reader_factory(data)
    await http_connect(reader, fake_writer, "example.com", 443)
    sent = fake_writer.buffer.decode()
    assert sent.startswith("CONNECT example.com:443 HTTP/1.1")
    assert "Host: example.com:443" in sent


async def test_connect_sends_proxy_authorization_header(reader_factory, fake_writer):
    data = b"HTTP/1.1 200 OK\r\n\r\n"
    reader = reader_factory(data)
    await http_connect(reader, fake_writer, "example.com", 443, username="u", password="p")
    sent = fake_writer.buffer.decode()
    expected_token = base64.b64encode(b"u:p").decode()
    assert f"Proxy-Authorization: Basic {expected_token}" in sent


async def test_connect_rejected_raises(reader_factory, fake_writer):
    data = b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n"
    reader = reader_factory(data)
    with pytest.raises(HttpConnectError):
        await http_connect(reader, fake_writer, "example.com", 443)


async def test_connect_closed_before_response_raises(reader_factory, fake_writer):
    reader = reader_factory(b"")
    with pytest.raises(HttpConnectError):
        await http_connect(reader, fake_writer, "example.com", 443)
