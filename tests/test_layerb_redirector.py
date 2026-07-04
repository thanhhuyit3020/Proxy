"""Test B3 -- phan logic _handle_packet, khong can driver that (mock packet)."""
from __future__ import annotations

import os
import time

import pytest

from proxy_manager.layerb import redirector as red
from proxy_manager.layerb.redirector import OriginalDestTable, Redirector
from proxy_manager.models import Profile, ProfileStatus, Proxy, ProxyScheme, ProxyStatus


class _FakePacket:
    def __init__(self, src_addr, src_port, dst_addr, dst_port, loopback=False):
        self.src_addr = src_addr
        self.src_port = src_port
        self.dst_addr = dst_addr
        self.dst_port = dst_port
        self.loopback = loopback
        self.checksum_calls = 0

    def recalculate_checksums(self):
        self.checksum_calls += 1


class _FakePidWatcher:
    def __init__(self, table):
        self._table = table

    def pid_for_port(self, port):
        return self._table.get(port)


class _FakeDb:
    def __init__(self, proxies):
        self._proxies = proxies

    def get_proxy(self, proxy_id):
        return self._proxies.get(proxy_id)


class _FakeProfileManager:
    def __init__(self, profiles, proxies, pid_to_profile):
        self._profiles = profiles
        self.db = _FakeDb(proxies)
        self._pid_to_profile = pid_to_profile

    def list_profiles(self):
        return self._profiles

    def profile_for_pid(self, pid):
        return self._pid_to_profile.get(pid)


@pytest.fixture(autouse=True)
def _pydivert_guard(monkeypatch):
    monkeypatch.setattr(red, "_PYDIVERT_AVAILABLE", True)


def _make_profile(proxy_id, local_port=20000, status=ProfileStatus.RUNNING):
    return Profile(id=1, name="p1", local_port=local_port, proxy_ids=[proxy_id],
                    active_proxy_id=proxy_id, status=status)


def _make_proxy(status=ProxyStatus.ALIVE):
    return Proxy(id=1, scheme=ProxyScheme.SOCKS5, host="1.2.3.4", port=1080, status=status)


def test_redirect_managed_app_to_gateway_port():
    proxy = _make_proxy()
    profile = _make_profile(proxy_id=proxy.id)
    pm = _FakeProfileManager([profile], {proxy.id: proxy}, {4321: profile})
    pw = _FakePidWatcher({55000: 4321})
    r = Redirector(pw, pm)

    packet = _FakePacket("10.1.1.5", 55000, "93.184.216.34", 443)
    r._handle_packet(packet)

    assert packet.dst_addr == "127.0.0.1"
    assert packet.dst_port == profile.local_port
    assert packet.checksum_calls == 1
    assert r.packets_redirected == 1
    assert r.orig_dest.lookup(55000) == ("93.184.216.34", 443)


def test_passthrough_when_pid_unmatched():
    pm = _FakeProfileManager([], {}, {})
    pw = _FakePidWatcher({})  # khong biet PID cho port nay
    r = Redirector(pw, pm)

    packet = _FakePacket("10.1.1.5", 55000, "93.184.216.34", 443)
    r._handle_packet(packet)

    assert packet.dst_addr == "93.184.216.34"  # khong doi
    assert packet.checksum_calls == 0
    assert r.packets_redirected == 0


def test_passthrough_when_pid_is_self():
    pm = _FakeProfileManager([], {}, {})
    pw = _FakePidWatcher({55000: os.getpid()})
    r = Redirector(pw, pm)

    packet = _FakePacket("10.1.1.5", 55000, "93.184.216.34", 443)
    r._handle_packet(packet)

    assert packet.dst_addr == "93.184.216.34"


def test_dropped_when_no_live_proxy_fail_closed():
    dead_proxy = _make_proxy(status=ProxyStatus.DEAD)
    profile = _make_profile(proxy_id=dead_proxy.id)
    pm = _FakeProfileManager([profile], {dead_proxy.id: dead_proxy}, {4321: profile})
    pw = _FakePidWatcher({55000: 4321})
    r = Redirector(pw, pm)

    packet = _FakePacket("10.1.1.5", 55000, "93.184.216.34", 443)
    r._handle_packet(packet)

    assert packet.dst_addr == "93.184.216.34"  # KHONG duoc sua -> that su bi drop
    assert r.packets_dropped == 1
    assert r.packets_redirected == 0


def test_dropped_when_profile_not_running():
    proxy = _make_proxy()
    profile = _make_profile(proxy_id=proxy.id, status=ProfileStatus.STOPPED)
    pm = _FakeProfileManager([profile], {proxy.id: proxy}, {4321: profile})
    pw = _FakePidWatcher({55000: 4321})
    r = Redirector(pw, pm)

    packet = _FakePacket("10.1.1.5", 55000, "93.184.216.34", 443)
    r._handle_packet(packet)

    assert r.packets_dropped == 1


def test_restore_source_for_gateway_reply_on_loopback():
    proxy = _make_proxy()
    profile = _make_profile(proxy_id=proxy.id, local_port=20005)
    pm = _FakeProfileManager([profile], {proxy.id: proxy}, {})
    pw = _FakePidWatcher({})
    r = Redirector(pw, pm)
    r.orig_dest.record(55000, "93.184.216.34", 443)

    # Goi gateway tra loi: src=127.0.0.1:20005 (gwport), dst=127.0.0.1:55000 (app)
    packet = _FakePacket("127.0.0.1", 20005, "127.0.0.1", 55000, loopback=True)
    r._handle_packet(packet)

    assert packet.src_addr == "93.184.216.34"
    assert packet.src_port == 443
    assert r.packets_restored == 1


def test_loopback_from_non_gateway_port_falls_through_to_case_a():
    # loopback=True nhung src_port khong phai gwport nao dang chay -> khong phai case B,
    # roi xuong case A binh thuong (o day khong khop PID nao -> passthrough)
    pm = _FakeProfileManager([], {}, {})
    pw = _FakePidWatcher({})
    r = Redirector(pw, pm)

    packet = _FakePacket("127.0.0.1", 9999, "127.0.0.1", 55000, loopback=True)
    r._handle_packet(packet)

    assert r.packets_restored == 0
    assert r.packets_redirected == 0


def test_original_dest_table_ttl_expiry():
    table = OriginalDestTable(entry_ttl_seconds=0)
    table.record(1234, "1.2.3.4", 80)
    # 0.05s: vuot ro rang do phan giai timer Windows (~15.6ms) de tranh flaky
    time.sleep(0.05)
    assert table.lookup(1234) is None


def test_original_dest_table_roundtrip():
    table = OriginalDestTable()
    table.record(1234, "1.2.3.4", 80)
    assert table.lookup(1234) == ("1.2.3.4", 80)
    assert table.snapshot() == {1234: ("1.2.3.4", 80)}


def test_redirector_raises_when_pydivert_unavailable(monkeypatch):
    monkeypatch.setattr(red, "_PYDIVERT_AVAILABLE", False)
    with pytest.raises(RuntimeError):
        Redirector(_FakePidWatcher({}), _FakeProfileManager([], {}, {}))
