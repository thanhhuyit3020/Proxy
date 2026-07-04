"""B3 -- transparent redirect (Handle B, NETWORK layer).

Thiet ke: docs/layer-b-design.md muc 4. Ghi de dich cho ket noi outbound cua app
duoc gan ve cong gateway cua profile, va ghi de nguoc lai src cho goi tra loi
tu gateway tren duong loopback de app khong bao gio biet no bi chuyen huong.

Dung Handle A (pid_map.PidWatcher, B2) de biet PID nao dang mo ket noi, va
ProfileManager de tra PID -> profile + ap dung dung kill-switch fail-closed nhu
Layer A (khong co proxy song -> DROP goi, tuyet doi khong cho ra mang that).

Chi bat outbound (khong bat inbound rieng): ca hai chieu (app gui di, gateway
tra loi) deu la "outbound" tu goc nhin cua tien trinh gui, WinDivert loopback
se giao goi da sua cho phia con lai -- day la each lam chuan cua cac tool
transparent-proxy tren Windows dung WinDivert."""
from __future__ import annotations

import logging
import os
import threading
import time

from ..models import ProfileStatus, ProxyStatus

logger = logging.getLogger("proxy_manager.layerb.redirector")

try:
    import pydivert
    _PYDIVERT_AVAILABLE = True
except Exception:  # noqa: BLE001 - import-guard, dong bo voi driver.py / pid_map.py
    pydivert = None
    _PYDIVERT_AVAILABLE = False


def pydivert_available() -> bool:
    return _PYDIVERT_AVAILABLE


REDIRECT_FILTER = "outbound and tcp"
DEFAULT_ENTRY_TTL_SECONDS = 300


class OriginalDestTable:
    """Bang local_port (cong ephemeral cua app) -> (dest_ip, dest_port) da bi
    thay the. Gateway (Layer A, che do transparent) tra cuu bang nay qua peer
    port cua ket noi den de biet dich that ma chain toi upstream proxy -- day
    la "side-channel" nhac toi trong thiet ke (ban Windows cua SO_ORIGINAL_DST)."""

    def __init__(self, entry_ttl_seconds: int = DEFAULT_ENTRY_TTL_SECONDS):
        self.entry_ttl_seconds = entry_ttl_seconds
        self._lock = threading.Lock()
        self._table: dict[int, tuple[str, int, float]] = {}

    def record(self, local_port: int, dest_ip: str, dest_port: int) -> None:
        with self._lock:
            self._table[local_port] = (dest_ip, dest_port, time.monotonic())

    def lookup(self, local_port: int) -> tuple[str, int] | None:
        with self._lock:
            entry = self._table.get(local_port)
        if entry is None:
            return None
        dest_ip, dest_port, recorded_at = entry
        if time.monotonic() - recorded_at > self.entry_ttl_seconds:
            return None
        return dest_ip, dest_port

    def snapshot(self) -> dict[int, tuple[str, int]]:
        with self._lock:
            return {port: (ip, p) for port, (ip, p, _) in self._table.items()}


class Redirector:
    """B3: Handle B (NETWORK layer). Ghi de dich cho ket noi outbound cua app
    duoc gan, ghi de nguoc lai src cho goi tra loi tren duong loopback."""

    def __init__(self, pid_watcher, profile_manager, orig_dest_table: OriginalDestTable | None = None):
        if not _PYDIVERT_AVAILABLE:
            raise RuntimeError(
                "pydivert/WinDivert khong san sang (can Windows + admin + driver). "
                "Khong the khoi dong Redirector tren may nay."
            )
        self._pid_watcher = pid_watcher
        self._profile_manager = profile_manager
        self.orig_dest = orig_dest_table if orig_dest_table is not None else OriginalDestTable()
        self._own_pid = os.getpid()
        self._handle = None
        self._thread: threading.Thread | None = None
        self._running = False
        self.packets_seen = 0
        self.packets_redirected = 0
        self.packets_restored = 0
        self.packets_dropped = 0

    def start(self) -> None:
        if self._running:
            return
        self._handle = pydivert.WinDivert(REDIRECT_FILTER)
        self._handle.open()
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="layerb-b3-redirector", daemon=True)
        self._thread.start()
        logger.info("Layer B B3 redirector started (filter=%s)", REDIRECT_FILTER)

    def stop(self) -> None:
        self._running = False
        if self._handle is not None:
            try:
                self._handle.close()
            except Exception:  # noqa: BLE001
                pass
            self._handle = None
        logger.info(
            "Layer B B3 redirector stopped (seen=%s redirected=%s restored=%s dropped=%s)",
            self.packets_seen, self.packets_redirected, self.packets_restored, self.packets_dropped,
        )

    @property
    def running(self) -> bool:
        return self._running

    def _running_gateway_ports(self) -> set[int]:
        return {
            p.local_port for p in self._profile_manager.list_profiles()
            if p.status == ProfileStatus.RUNNING
        }

    def _loop(self) -> None:
        while self._running:
            try:
                packet = self._handle.recv()
            except Exception:  # noqa: BLE001 - handle dong khi stop() -> thoat vong lap
                break
            self.packets_seen += 1
            try:
                self._handle_packet(packet)
            except Exception as exc:  # noqa: BLE001 - 1 goi loi khong duoc lam chet vong lap
                logger.debug("redirector loi xu ly goi: %s", exc)
                self._reinject(packet)

    def _handle_packet(self, packet) -> None:
        # Case B: goi tra loi tu gateway (src la 1 trong cac cong gwport dang chay,
        # tren duong loopback) -> ghi de src ve dich that de app khong biet bi chuyen huong.
        if packet.loopback and packet.src_port in self._running_gateway_ports():
            orig = self.orig_dest.lookup(packet.dst_port)
            if orig is not None:
                packet.src_addr, packet.src_port = orig[0], orig[1]
                packet.recalculate_checksums()
                self.packets_restored += 1
            self._reinject(packet)
            return

        # Case A: goi outbound cua app -> kiem tra PID co thuoc profile duoc gan khong.
        pid = self._pid_watcher.pid_for_port(packet.src_port)
        if pid is None or pid == self._own_pid:
            self._reinject(packet)  # khong xac dinh duoc PID hoac la chinh minh -> bo qua
            return

        profile = self._profile_manager.profile_for_pid(pid)
        if profile is None:
            self._reinject(packet)  # PID khong thuoc app nao duoc gan -> bo qua
            return

        active_proxy = (
            self._profile_manager.db.get_proxy(profile.active_proxy_id)
            if profile.active_proxy_id is not None else None
        )
        proxy_alive = active_proxy is not None and active_proxy.status != ProxyStatus.DEAD

        if profile.status != ProfileStatus.RUNNING or not proxy_alive:
            # Kill-switch fail-closed: app duoc gan nhung khong co gateway/proxy song
            # -> DROP, tuyet doi khong cho goi ra mang that (khong reinject).
            self.packets_dropped += 1
            return

        self.orig_dest.record(packet.src_port, packet.dst_addr, packet.dst_port)
        packet.dst_addr = "127.0.0.1"
        packet.dst_port = profile.local_port
        packet.recalculate_checksums()
        self.packets_redirected += 1
        self._reinject(packet)

    def _reinject(self, packet) -> None:
        try:
            self._handle.send(packet)
        except Exception:  # noqa: BLE001
            pass
