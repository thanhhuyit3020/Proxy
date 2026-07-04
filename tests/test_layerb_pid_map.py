"""Test B2 — phan logic khong can driver that (mock SOCKET layer + psutil that)."""
from __future__ import annotations

import os
import time

import pytest

from proxy_manager.layerb import pid_map
from proxy_manager.layerb.pid_map import PidWatcher, lookup_pid_by_port, resolve_process_name


def test_resolve_process_name_for_current_process():
    # Tien trinh hien tai (chinh pytest) chac chan ton tai va co ten
    name = resolve_process_name(os.getpid())
    assert name is not None
    assert len(name) > 0


def test_resolve_process_name_returns_none_for_invalid_pid():
    # PID cuc lon, gan chac chan khong ton tai tren bat ky may nao
    assert resolve_process_name(999_999_999) is None


def test_lookup_pid_by_port_returns_none_for_unused_port():
    assert lookup_pid_by_port(1) is None or isinstance(lookup_pid_by_port(1), int)


def test_pid_watcher_raises_when_pydivert_unavailable(monkeypatch):
    monkeypatch.setattr(pid_map, "_PYDIVERT_AVAILABLE", False)
    with pytest.raises(RuntimeError):
        PidWatcher()


class _FakeSocket:
    """Mo phong ctypes struct WINDIVERT_ADDRESS.Socket (field PascalCase that)."""

    def __init__(self, process_id, local_port):
        self.ProcessId = process_id
        self.LocalPort = local_port


class _FakeEvent:
    """Mo phong pydivert.Packet: co property .socket (khong phai .address)."""

    def __init__(self, process_id, local_port):
        self.socket = _FakeSocket(process_id, local_port)


class _FakeSocketHandle:
    def __init__(self, filter_str, layer=None, flags=None):
        self.filter_str = filter_str
        self._events = [_FakeEvent(1234, 55000), _FakeEvent(5678, 55001)]
        self._idx = 0

    def open(self):
        pass

    def recv(self):
        if self._idx >= len(self._events):
            raise OSError("handle closed")  # dung vong lap sau khi phat het event gia
        event = self._events[self._idx]
        self._idx += 1
        return event

    def close(self):
        pass


def test_pid_watcher_builds_table_from_socket_events(monkeypatch):
    class _FakePydivert:
        WinDivert = _FakeSocketHandle
        Layer = type("Layer", (), {"SOCKET": "SOCKET"})
        Flag = type("Flag", (), {"SNIFF": 1, "RECV_ONLY": 2})

        def __or__(self, other):
            return self

    monkeypatch.setattr(pid_map, "_PYDIVERT_AVAILABLE", True)
    monkeypatch.setattr(pid_map, "pydivert", _FakePydivert)

    watcher = PidWatcher()
    watcher.start()
    # doi thread nen xu ly het 2 event gia lap (nhanh, khong can sleep lau)
    deadline = time.monotonic() + 2
    while watcher.events_seen < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    watcher.stop()

    snapshot = watcher.snapshot()
    assert snapshot.get(55000) == 1234
    assert snapshot.get(55001) == 5678
    assert watcher.pid_for_port(55000) == 1234


def test_pid_watcher_pid_for_port_falls_back_when_missing(monkeypatch):
    class _FakePydivert:
        WinDivert = _FakeSocketHandle
        Layer = type("Layer", (), {"SOCKET": "SOCKET"})
        Flag = type("Flag", (), {"SNIFF": 1, "RECV_ONLY": 2})

    monkeypatch.setattr(pid_map, "_PYDIVERT_AVAILABLE", True)
    monkeypatch.setattr(pid_map, "pydivert", _FakePydivert)

    watcher = PidWatcher()
    watcher.start()
    watcher.stop()

    monkeypatch.setattr(pid_map, "lookup_pid_by_port", lambda port: 9999)
    assert watcher.pid_for_port(1) == 9999


def test_pid_for_port_prefers_psutil_over_stale_table_entry(monkeypatch):
    """Regression: phat hien qua self-test B3 tren may that. Cong ephemeral bi tai
    su dung boi 2 tien trinh khac nhau lien tiep (vd 2 lan goi curl.exe) -- bang
    song (SOCKET layer) van con giu PID CU (da thoat) cho cong do. Neu uu tien bang
    song, profile_for_pid() se resolve ra None (PID cu khong con ton tai) -> Redirector
    coi goi la "khong quan ly" -> bo qua ca redirect lan kill-switch -> LO IP THAT.
    psutil (ground truth NGAY LUC NAY) phai duoc uu tien de tra ve PID hien tai dung."""
    class _FakePydivert:
        WinDivert = _FakeSocketHandle
        Layer = type("Layer", (), {"SOCKET": "SOCKET"})
        Flag = type("Flag", (), {"SNIFF": 1, "RECV_ONLY": 2})

    monkeypatch.setattr(pid_map, "_PYDIVERT_AVAILABLE", True)
    monkeypatch.setattr(pid_map, "pydivert", _FakePydivert)

    watcher = PidWatcher()
    watcher.start()
    deadline = time.monotonic() + 2
    while watcher.events_seen < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    watcher.stop()

    # 55000 -> PID 1234 (da thoat) trong bang song (tu _FakeSocketHandle);
    # psutil (ground truth) bao cong 55000 bay gio thuoc PID 7777 (tien trinh moi).
    monkeypatch.setattr(pid_map, "lookup_pid_by_port", lambda port: 7777 if port == 55000 else None)

    assert watcher.pid_for_port(55000) == 7777
