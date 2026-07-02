"""SOCKS5 client handshake toi upstream proxy (RFC 1928 / 1929)."""
from __future__ import annotations

import asyncio
import struct


class SocksError(Exception):
    pass


_REPLY_MESSAGES = {
    0x01: "general SOCKS server failure",
    0x02: "connection not allowed by ruleset",
    0x03: "network unreachable",
    0x04: "host unreachable",
    0x05: "connection refused",
    0x06: "TTL expired",
    0x07: "command not supported",
    0x08: "address type not supported",
}


async def socks5_connect(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    dest_host: str,
    dest_port: int,
    username: str | None = None,
    password: str | None = None,
) -> None:
    """Thuc hien handshake SOCKS5 tren mot ket noi TCP da mo toi upstream proxy,
    yeu cau upstream CONNECT toi dest_host:dest_port. Sau khi ham nay tra ve,
    reader/writer co the dung de relay du lieu thang toi dest."""
    auth_methods = b"\x00\x02" if username else b"\x00"
    writer.write(b"\x05" + bytes([len(auth_methods)]) + auth_methods)
    await writer.drain()

    resp = await reader.readexactly(2)
    if resp[0] != 0x05:
        raise SocksError("invalid SOCKS5 version from upstream")
    method = resp[1]

    if method == 0x02:
        if not username:
            raise SocksError("upstream requires auth but no credentials provided")
        user_b = username.encode()
        pass_b = (password or "").encode()
        writer.write(bytes([0x01, len(user_b)]) + user_b + bytes([len(pass_b)]) + pass_b)
        await writer.drain()
        auth_resp = await reader.readexactly(2)
        if auth_resp[1] != 0x00:
            raise SocksError("upstream SOCKS5 auth failed")
    elif method == 0xFF:
        raise SocksError("upstream rejected all auth methods")

    try:
        addr_bytes = b"\x01" + bytes(int(p) for p in dest_host.split("."))
        if len(addr_bytes) != 5:
            raise ValueError
    except ValueError:
        host_b = dest_host.encode()
        addr_bytes = b"\x03" + bytes([len(host_b)]) + host_b

    writer.write(b"\x05\x01\x00" + addr_bytes + struct.pack(">H", dest_port))
    await writer.drain()

    header = await reader.readexactly(4)
    if header[0] != 0x05:
        raise SocksError("invalid SOCKS5 reply version")
    if header[1] != 0x00:
        raise SocksError(f"upstream CONNECT failed: {_REPLY_MESSAGES.get(header[1], header[1])}")

    atyp = header[3]
    if atyp == 0x01:
        await reader.readexactly(4 + 2)
    elif atyp == 0x03:
        length = (await reader.readexactly(1))[0]
        await reader.readexactly(length + 2)
    elif atyp == 0x04:
        await reader.readexactly(16 + 2)
    else:
        raise SocksError("unknown address type in SOCKS5 reply")
