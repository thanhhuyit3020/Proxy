"""B1 — WinDivert bring-up.

Nap WinDivert, bat goi outbound TCP theo filter va reinject NGUYEN TRANG (passthrough).
Chua redirect gi — muc tieu B1 la chung minh: co the chan goi + tha lai ma khong lam dut
ket noi cua app, va master on/off dong/mo handle sach se.

Redirect that su (ghi de dich) o buoc B3. PID scoping o buoc B2.

pydivert duoc import-guard: neu WinDivert/pydivert khong san sang (khong phai Windows,
chua co driver, thieu admin) thi pydivert_available() tra False va ForcedRouter.start()
bao loi ro rang thay vi crash ca app.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger("proxy_manager.layerb.driver")

try:
    import pydivert
    _PYDIVERT_AVAILABLE = True
except Exception:  # noqa: BLE001 - ImportError hoac loi nap DLL tren nen tang la
    pydivert = None
    _PYDIVERT_AVAILABLE = False


def pydivert_available() -> bool:
    return _PYDIVERT_AVAILABLE


def build_capture_filter(dest_ports: list[int] | None = None, exclude_loopback: bool = True) -> str:
    """Dung chuoi filter WinDivert cho goi TCP outbound.

    - exclude_loopback: bo qua 127.0.0.1 (tranh dung vao chinh gateway local)
    - dest_ports: neu co, chi bat goi toi cac cong dich nay (thu hep pham vi khi test B1)
    Cu phap filter theo tai lieu WinDivert (vd: 'outbound and tcp and ip.DstAddr != 127.0.0.1')."""
    parts = ["outbound", "tcp"]
    if exclude_loopback:
        parts.append("ip.DstAddr != 127.0.0.1")
    if dest_ports:
        port_expr = " or ".join(f"tcp.DstPort == {int(p)}" for p in dest_ports)
        parts.append(f"({port_expr})")
    return " and ".join(parts)


class ForcedRouter:
    """B1 passthrough router. Bat goi theo filter, reinject nguyen trang.

    Vong lap chay trong thread nen (daemon). stop() = master-off cung: dong handle,
    khoi phuc mang binh thuong ngay lap tuc."""

    def __init__(self, filter_str: str):
        if not _PYDIVERT_AVAILABLE:
            raise RuntimeError(
                "pydivert/WinDivert khong san sang (can Windows + admin + driver). "
                "Khong the khoi dong Layer B tren may nay."
            )
        self.filter_str = filter_str
        self._handle = None
        self._thread: threading.Thread | None = None
        self._running = False
        self.packets_seen = 0

    def start(self) -> None:
        if self._running:
            return
        self._handle = pydivert.WinDivert(self.filter_str)
        self._handle.open()
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="layerb-b1", daemon=True)
        self._thread.start()
        logger.info("Layer B B1 passthrough started (filter=%s)", self.filter_str)

    def _loop(self) -> None:
        while self._running:
            try:
                packet = self._handle.recv()
            except Exception:  # noqa: BLE001 - handle dong khi stop() -> thoat vong lap
                break
            self.packets_seen += 1
            try:
                self._handle.send(packet)  # passthrough: reinject nguyen trang
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        self._running = False
        if self._handle is not None:
            try:
                self._handle.close()
            except Exception:  # noqa: BLE001
                pass
            self._handle = None
        logger.info("Layer B B1 passthrough stopped (packets_seen=%s)", self.packets_seen)

    @property
    def running(self) -> bool:
        return self._running
