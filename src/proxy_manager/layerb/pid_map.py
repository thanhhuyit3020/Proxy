"""B2 — PID -> profile mapping.

Handle A (thiet ke o docs/layer-b-design.md muc 3): WinDivert SOCKET layer, sniff-only,
nhan su kien CONNECT/BIND kem PID + local_port ngay khi app mo ket noi. Ket qua duoc
luu vao bang trong bo nho (local_port -> pid) de Handle B (NETWORK layer, redirect o B3)
tra cuu goi thuoc tien trinh nao.

psutil.net_connections() duoc dung lam fallback/doi chieu (tuong duong GetExtendedTcpTable
nhac toi trong thiet ke) cho cac ket noi da mo TRUOC khi watcher bat dau."""
from __future__ import annotations

import logging
import os
import threading
import time

import psutil

logger = logging.getLogger("proxy_manager.layerb.pid_map")

# Cung bien voi redirector.py -- bat de chan doan khi vong lap watcher chet som
# ma khong ro nguyen nhan (vd xung dot khi mo dong thoi voi Handle B NETWORK layer).
_DEBUG = os.environ.get("PROXY_MANAGER_LAYERB_DEBUG") == "1"


def _dbg(*args) -> None:
    if _DEBUG:
        print("[pid_map debug]", *args, flush=True)


try:
    import pydivert
    _PYDIVERT_AVAILABLE = True
except Exception:  # noqa: BLE001 - import-guard, dong bo voi driver.py
    pydivert = None
    _PYDIVERT_AVAILABLE = False


def pydivert_available() -> bool:
    return _PYDIVERT_AVAILABLE


SOCKET_LAYER_FILTER = "outbound and tcp"

# Bang entry het han sau khoang thoi gian nay neu khong duoc lam moi -- tranh phinh bo
# nho vo han cho cac ket noi da dong ma khong co su kien dong tuong ung o SOCKET layer.
DEFAULT_ENTRY_TTL_SECONDS = 300


def resolve_process_name(pid: int) -> str | None:
    """Tra ve ten tien trinh (vd 'chrome.exe') tu PID, hoac None neu tien trinh khong
    con ton tai hoac khong co quyen truy cap."""
    try:
        return psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def lookup_pid_by_port(local_port: int) -> int | None:
    """Fallback: tra PID theo local_port qua psutil.net_connections (tuong duong
    GetExtendedTcpTable). Dung cho ket noi da mo truoc khi PidWatcher bat dau,
    hoac khi WinDivert SOCKET layer khong san sang."""
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr and conn.laddr.port == local_port and conn.pid:
                return conn.pid
    except (psutil.AccessDenied, PermissionError):
        return None
    return None


class PidWatcher:
    """B2: theo doi su kien CONNECT o SOCKET layer, xay bang local_port -> pid.

    Sniff-only (khong sua/chan goi nao) -- an toan chay song song voi B1 passthrough
    hoac Layer A gateway ma khong anh huong traffic that."""

    def __init__(self, entry_ttl_seconds: int = DEFAULT_ENTRY_TTL_SECONDS):
        if not _PYDIVERT_AVAILABLE:
            raise RuntimeError(
                "pydivert/WinDivert khong san sang (can Windows + admin + driver). "
                "Khong the khoi dong PidWatcher tren may nay."
            )
        self.entry_ttl_seconds = entry_ttl_seconds
        self._handle = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._table: dict[int, tuple[int, float]] = {}  # local_port -> (pid, last_seen)
        self.events_seen = 0

    def start(self) -> None:
        if self._running:
            return
        self._handle = pydivert.WinDivert(
            SOCKET_LAYER_FILTER,
            layer=pydivert.Layer.SOCKET,
            flags=pydivert.Flag.SNIFF | pydivert.Flag.RECV_ONLY,
        )
        self._handle.open()
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="layerb-b2-pidmap", daemon=True)
        self._thread.start()
        logger.info("Layer B B2 PidWatcher started (filter=%s)", SOCKET_LAYER_FILTER)

    def _loop(self) -> None:
        while self._running:
            try:
                packet = self._handle.recv()
            except Exception as exc:  # noqa: BLE001 - handle dong khi stop() -> thoat vong lap
                if self._running:
                    _dbg(f"recv() loi bat ngo, vong lap PidWatcher DUNG SOM: {exc!r}")
                    logger.warning("Layer B B2 PidWatcher: recv() loi, dung vong lap: %r", exc)
                break
            self.events_seen += 1
            # pydivert: Packet.socket la ctypes struct WINDIVERT_ADDRESS.Socket khi
            # layer=SOCKET, voi field PascalCase (ProcessId, LocalPort...) -- khong
            # phai property tien loi kieu snake_case.
            sock = getattr(packet, "socket", None)
            if sock is None:
                continue
            pid = getattr(sock, "ProcessId", None)
            local_port = getattr(sock, "LocalPort", None)
            if pid is None or local_port is None:
                continue
            with self._lock:
                self._table[local_port] = (pid, time.monotonic())
            _dbg(f"table[{local_port}] = pid {pid}")

    def stop(self) -> None:
        self._running = False
        if self._handle is not None:
            try:
                self._handle.close()
            except Exception:  # noqa: BLE001
                pass
            self._handle = None
        logger.info("Layer B B2 PidWatcher stopped (events_seen=%s)", self.events_seen)

    @property
    def running(self) -> bool:
        return self._running

    def pid_for_port(self, local_port: int) -> int | None:
        """Tra cuu PID theo local_port: uu tien psutil (phan anh dung trang thai OS
        NGAY LUC NAY, khong the stale) truoc; chi fallback sang bang song (SOCKET
        layer) neu psutil khong thay gi.

        Ly do dao thu tu (khong uu tien bang song nhu ban dau): cong ephemeral co
        the bi he dieu hanh tai su dung rat nhanh giua 2 lan ket noi cua 2 tien
        trinh khac nhau (vd 2 lan goi lien tiep cung 1 app). Bang song ghi nhan PID
        tai thoi diem CONNECT xay ra va KHONG tu xoa khi tien trinh do thoat, nen
        neu cong bi tai su dung, bang song se tra ve PID CU (da thoat) thay vi PID
        that su dang giu cong ngay luc nay -- lam profile_for_pid() khong resolve
        duoc ten tien trinh, khien Redirector coi goi la "khong quan ly" va cho di
        thang (bo qua ca redirect lan kill-switch, tuc la LO IP THAT). Phat hien
        qua self-test B3 thuc te: kill-switch bi bo qua o lan goi curl.exe thu 2."""
        pid = lookup_pid_by_port(local_port)
        if pid is not None:
            _dbg(f"pid_for_port({local_port}) = {pid} (nguon: psutil)")
            return pid
        with self._lock:
            entry = self._table.get(local_port)
        if entry is not None:
            pid, last_seen = entry
            if time.monotonic() - last_seen <= self.entry_ttl_seconds:
                _dbg(f"pid_for_port({local_port}) = {pid} (nguon: bang song SOCKET layer)")
                return pid
        _dbg(f"pid_for_port({local_port}) = None (khong tim thay o ca 2 nguon)")
        return None

    def snapshot(self) -> dict[int, int]:
        """Ban sao bang hien tai (local_port -> pid), khong loc TTL -- dung de debug/hien thi."""
        with self._lock:
            return {port: pid for port, (pid, _) in self._table.items()}
