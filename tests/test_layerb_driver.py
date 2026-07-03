"""Test B1 — phan logic khong can admin/driver that.

Cac test driver-dependent (bat goi that) can Windows + admin + WinDivert -> khong chay o
CI/unit; verify thu cong theo docs/layer-b-design.md."""
from __future__ import annotations

import pytest

from proxy_manager.layerb import admin, driver
from proxy_manager.layerb.driver import ForcedRouter, build_capture_filter


def test_build_filter_default():
    f = build_capture_filter()
    assert "outbound" in f
    assert "tcp" in f
    assert "ip.DstAddr != 127.0.0.1" in f


def test_build_filter_without_loopback_exclusion():
    f = build_capture_filter(exclude_loopback=False)
    assert "127.0.0.1" not in f


def test_build_filter_with_dest_ports():
    f = build_capture_filter(dest_ports=[80, 443])
    assert "tcp.DstPort == 80" in f
    assert "tcp.DstPort == 443" in f
    assert " or " in f


def test_is_admin_returns_bool():
    # Khong assert gia tri (phu thuoc moi truong), chi dam bao tra ve bool khong crash
    assert isinstance(admin.is_admin(), bool)


def test_require_admin_message_mentions_administrator():
    assert "Administrator" in admin.require_admin_message()


def test_forced_router_raises_when_pydivert_unavailable(monkeypatch):
    monkeypatch.setattr(driver, "_PYDIVERT_AVAILABLE", False)
    with pytest.raises(RuntimeError):
        ForcedRouter("outbound and tcp")


class _FakeHandle:
    def __init__(self, filter_str):
        self.filter_str = filter_str
        self.opened = False
        self.closed = False

    def open(self):
        self.opened = True

    def recv(self):
        raise OSError("handle closed")  # dung ngay -> vong lap thoat sach

    def send(self, packet):
        pass

    def close(self):
        self.closed = True


def test_forced_router_start_stop_state_machine(monkeypatch):
    class _FakePydivert:
        WinDivert = _FakeHandle

    monkeypatch.setattr(driver, "_PYDIVERT_AVAILABLE", True)
    monkeypatch.setattr(driver, "pydivert", _FakePydivert)

    router = ForcedRouter("outbound and tcp")
    assert router.running is False

    router.start()
    assert router.running is True

    router.stop()
    assert router.running is False
    # start() lai duoc sau khi stop (idempotent, khong ket)
    router.start()
    assert router.running is True
    router.stop()
