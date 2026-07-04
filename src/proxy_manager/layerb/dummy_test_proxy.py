"""CHI DE TEST -- SOCKS5 proxy toi gian chay local, dung khi khong co proxy that
de kiem chung selftest_b3 (transparent redirect). KHONG an danh IP that: proxy nay
chay tren cung may, IP quan sat se la IP that cua may ban.

Van co gia tri kiem thu: no van la mot "upstream proxy" tach biet ma Layer B phai
dinh tuyen toi -- kiem chung dung co che redirect/checksum/kill-switch (phan rui ro
ky thuat that su cua B3), chi khong kiem chung duoc phan "an danh IP" (can proxy that
de kiem tra dieu do).

Chay (KHONG can quyen admin, terminal rieng voi terminal chay selftest_b3):
    .venv\\Scripts\\python.exe -m proxy_manager.layerb.dummy_test_proxy

Sau do dung voi selftest_b3:
    .venv\\Scripts\\python.exe -m proxy_manager.layerb.selftest_b3 socks5://127.0.0.1:1080
"""
from __future__ import annotations

import asyncio
import struct

LISTEN_PORT = 1080


async def _relay(a: asyncio.StreamReader, b: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await a.read(65536)
            if not chunk:
                break
            b.write(chunk)
            await b.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        b.close()


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        ver = await reader.readexactly(1)
        if ver != b"\x05":
            writer.close()
            return
        nmethods = (await reader.readexactly(1))[0]
        await reader.readexactly(nmethods)
        writer.write(b"\x05\x00")  # no-auth
        await writer.drain()

        header = await reader.readexactly(4)
        if header[1] != 0x01:  # chi ho tro CONNECT
            writer.write(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
            return

        atyp = header[3]
        if atyp == 0x01:
            addr = ".".join(str(b) for b in await reader.readexactly(4))
        elif atyp == 0x03:
            length = (await reader.readexactly(1))[0]
            addr = (await reader.readexactly(length)).decode()
        else:
            writer.write(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
            return
        port = struct.unpack(">H", await reader.readexactly(2))[0]

        try:
            dest_reader, dest_writer = await asyncio.open_connection(addr, port)
        except OSError:
            writer.write(b"\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
            return

        writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        await writer.drain()
        await asyncio.gather(
            _relay(reader, dest_writer), _relay(dest_reader, writer), return_exceptions=True
        )
    except (asyncio.IncompleteReadError, ConnectionResetError):
        pass
    finally:
        writer.close()


async def main() -> None:
    server = await asyncio.start_server(_handle, host="127.0.0.1", port=LISTEN_PORT)
    print(f"[dummy_test_proxy] SOCKS5 test-only proxy tren 127.0.0.1:{LISTEN_PORT}")
    print("[dummy_test_proxy] KHONG an danh IP -- chi de kiem chung co che redirect.")
    print("[dummy_test_proxy] Ctrl+C de dung.")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
