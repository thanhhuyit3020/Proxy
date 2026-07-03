from __future__ import annotations

import pytest

from proxy_manager.socks_client import SocksError, socks5_connect


def _connect_reply(atyp: int = 0x01, rep: int = 0x00) -> bytes:
    if atyp == 0x01:
        addr = bytes([127, 0, 0, 1]) + b"\x00\x50"
    elif atyp == 0x03:
        host = b"example.com"
        addr = bytes([len(host)]) + host + b"\x00\x50"
    elif atyp == 0x04:
        addr = bytes(16) + b"\x00\x50"
    else:
        raise ValueError("unsupported atyp for test helper")
    return bytes([0x05, rep, 0x00, atyp]) + addr


async def test_no_auth_success_ipv4_reply(reader_factory, fake_writer):
    data = b"\x05\x00" + _connect_reply(atyp=0x01)
    reader = reader_factory(data)
    await socks5_connect(reader, fake_writer, "93.184.216.34", 80)
    assert fake_writer.buffer[:3] == b"\x05\x01\x00"  # greeting: ver=5, 1 method, no-auth


async def test_no_auth_success_domain_reply(reader_factory, fake_writer):
    data = b"\x05\x00" + _connect_reply(atyp=0x03)
    reader = reader_factory(data)
    await socks5_connect(reader, fake_writer, "example.com", 443)


async def test_no_auth_success_ipv6_reply(reader_factory, fake_writer):
    data = b"\x05\x00" + _connect_reply(atyp=0x04)
    reader = reader_factory(data)
    await socks5_connect(reader, fake_writer, "example.com", 443)


async def test_username_password_auth_success(reader_factory, fake_writer):
    data = b"\x05\x02" + b"\x01\x00" + _connect_reply()
    reader = reader_factory(data)
    await socks5_connect(reader, fake_writer, "1.2.3.4", 80, username="u", password="p")
    # greeting should advertise both no-auth (0x00) and user/pass (0x02) methods
    assert fake_writer.buffer[:2] == b"\x05\x02"


async def test_auth_required_but_no_credentials_raises(reader_factory, fake_writer):
    data = b"\x05\x02"  # upstream demands user/pass auth
    reader = reader_factory(data)
    with pytest.raises(SocksError):
        await socks5_connect(reader, fake_writer, "1.2.3.4", 80)


async def test_no_acceptable_methods_raises(reader_factory, fake_writer):
    data = b"\x05\xff"
    reader = reader_factory(data)
    with pytest.raises(SocksError):
        await socks5_connect(reader, fake_writer, "1.2.3.4", 80)


async def test_upstream_auth_failure_raises(reader_factory, fake_writer):
    data = b"\x05\x02" + b"\x01\x01"  # auth status != 0x00 -> failed
    reader = reader_factory(data)
    with pytest.raises(SocksError):
        await socks5_connect(reader, fake_writer, "1.2.3.4", 80, username="u", password="wrong")


async def test_connect_rejected_raises(reader_factory, fake_writer):
    data = b"\x05\x00" + _connect_reply(rep=0x05)  # connection refused
    reader = reader_factory(data)
    with pytest.raises(SocksError):
        await socks5_connect(reader, fake_writer, "1.2.3.4", 80)
