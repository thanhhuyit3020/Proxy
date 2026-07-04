"""Layer A: local listener (127.0.0.1:port) noi SOCKS5 + HTTP proxy cho 1 profile,
chain moi ket noi qua upstream proxy dang active cua profile do."""
from __future__ import annotations

import asyncio
import logging
import struct
from typing import Awaitable, Callable

from .models import Proxy
from .upstream import open_via_upstream

logger = logging.getLogger("proxy_manager.gateway")

GetActiveProxy = Callable[[], Awaitable[Proxy | None]]
OrigDestLookup = Callable[[int], "tuple[str, int] | None"]


class GatewayError(Exception):
    pass


class ProfileGateway:
    """Mot instance gan voi 1 profile: lang nghe tren 127.0.0.1:local_port."""

    def __init__(
        self, profile_id: int, local_port: int, get_active_proxy: GetActiveProxy,
        orig_dest_lookup: OrigDestLookup | None = None,
    ):
        self.profile_id = profile_id
        self.local_port = local_port
        self._get_active_proxy = get_active_proxy
        # Layer B (B3): tra dich goc theo peer port khi ket noi den la do WinDivert
        # dinh tuyen trong suot (app khong gui SOCKS5/HTTP framing). None = chi Layer A.
        self._orig_dest_lookup = orig_dest_lookup
        self._server: asyncio.base_events.Server | None = None
        self.active_connections = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, host="127.0.0.1", port=self.local_port
        )

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    @property
    def running(self) -> bool:
        return self._server is not None

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.active_connections += 1

        if self._orig_dest_lookup is not None:
            peer = writer.get_extra_info("peername")
            peer_port = peer[1] if peer else None
            orig = self._orig_dest_lookup(peer_port) if peer_port is not None else None
            if orig is not None:
                try:
                    await self._serve_transparent(reader, writer, orig[0], orig[1])
                except Exception as exc:  # noqa: BLE001
                    logger.debug("profile=%s transparent connection error: %s", self.profile_id, exc)
                finally:
                    self.active_connections -= 1
                    writer.close()
                return

        try:
            first_byte = await reader.readexactly(1)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            self.active_connections -= 1
            writer.close()
            return

        try:
            if first_byte == b"\x05":
                await self._serve_socks5(reader, writer, first_byte)
            else:
                await self._serve_http(reader, writer, first_byte)
        except Exception as exc:  # noqa: BLE001 - log va dong ket noi, khong crash gateway
            logger.debug("profile=%s connection error: %s", self.profile_id, exc)
        finally:
            self.active_connections -= 1
            writer.close()

    # ---------- Layer B transparent mode (B3): ket noi den khong co framing SOCKS5/HTTP ----------
    async def _serve_transparent(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, dest_host: str, dest_port: int
    ) -> None:
        """App bi WinDivert dinh tuyen trong suot ve day, dich that lay tu side-channel
        (Redirector.orig_dest, B3). Khong co byte framing nao de doc -- relay thang."""
        proxy = await self._get_active_proxy()
        if proxy is None:
            return  # kill-switch: khong co proxy -> dong ket noi, khong forward goi nao
        try:
            up_reader, up_writer = await open_via_upstream(proxy, dest_host, dest_port)
        except Exception:
            return
        await _relay(reader, writer, up_reader, up_writer)

    # ---------- SOCKS5 server side (client -> gateway) ----------
    async def _serve_socks5(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, first_byte: bytes
    ) -> None:
        nmethods = (await reader.readexactly(1))[0]
        await reader.readexactly(nmethods)
        writer.write(b"\x05\x00")  # no-auth
        await writer.drain()

        header = await reader.readexactly(4)
        if header[0:1] != b"\x05" or header[1] != 0x01:  # chi ho tro CONNECT
            writer.write(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
            return

        atyp = header[3]
        if atyp == 0x01:
            addr = ".".join(str(b) for b in await reader.readexactly(4))
        elif atyp == 0x03:
            length = (await reader.readexactly(1))[0]
            addr = (await reader.readexactly(length)).decode()
        elif atyp == 0x04:
            raw = await reader.readexactly(16)
            addr = ":".join(f"{raw[i]:02x}{raw[i+1]:02x}" for i in range(0, 16, 2))
        else:
            writer.write(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
            return
        port = struct.unpack(">H", await reader.readexactly(2))[0]

        proxy = await self._get_active_proxy()
        if proxy is None:
            writer.write(b"\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00")  # kill-switch: khong co proxy -> tu choi
            await writer.drain()
            return

        try:
            up_reader, up_writer = await open_via_upstream(proxy, addr, port)
        except Exception:
            writer.write(b"\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
            return

        writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        await writer.drain()
        await _relay(reader, writer, up_reader, up_writer)

    # ---------- HTTP proxy server side ----------
    async def _serve_http(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, first_byte: bytes
    ) -> None:
        request_line = first_byte + await reader.readline()
        try:
            method, target, _version = request_line.decode(errors="replace").split()
        except ValueError:
            writer.close()
            return

        header_lines = []
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            header_lines.append(line)

        proxy = await self._get_active_proxy()
        if proxy is None:
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            return

        if method == "CONNECT":
            host, _, port_s = target.partition(":")
            port = int(port_s or 443)
            try:
                up_reader, up_writer = await open_via_upstream(proxy, host, port)
            except Exception:
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            await _relay(reader, writer, up_reader, up_writer)
            return

        # plain HTTP (absolute-URI): parse host tu target
        host, port, path = _parse_absolute_uri(target)
        if not host:
            writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            return
        try:
            up_reader, up_writer = await open_via_upstream(proxy, host, port)
        except Exception:
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            return
        up_writer.write(f"{method} {path} HTTP/1.1\r\n".encode())
        for line in header_lines:
            up_writer.write(line)
        up_writer.write(b"\r\n")
        await up_writer.drain()
        await _relay(reader, writer, up_reader, up_writer)


def _parse_absolute_uri(target: str) -> tuple[str, int, str]:
    rest = target.split("://", 1)[-1]
    hostport, _, path = rest.partition("/")
    host, _, port_s = hostport.partition(":")
    port = int(port_s) if port_s else 80
    return host, port, "/" + path


async def _relay(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    upstream_reader: asyncio.StreamReader,
    upstream_writer: asyncio.StreamWriter,
) -> None:
    async def pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
        try:
            while True:
                chunk = await src.read(65536)
                if not chunk:
                    break
                dst.write(chunk)
                await dst.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            dst.close()

    await asyncio.gather(
        pipe(client_reader, upstream_writer),
        pipe(upstream_reader, client_writer),
        return_exceptions=True,
    )
