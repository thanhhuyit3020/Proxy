from __future__ import annotations

import pytest

from proxy_manager.models import Proxy, ProxyScheme
from proxy_manager.profile_manager import ProfileManager


def _add_proxy(db, host="1.2.3.4", port=8080) -> int:
    return db.add_proxy(Proxy(id=None, scheme=ProxyScheme.HTTP, host=host, port=port))


def test_create_profile_requires_at_least_one_proxy(db):
    manager = ProfileManager(db)
    with pytest.raises(ValueError):
        manager.create_profile(name="p", proxy_ids=[])


def test_create_profile_rejects_blank_name(db):
    manager = ProfileManager(db)
    proxy_id = _add_proxy(db)
    with pytest.raises(ValueError):
        manager.create_profile(name="   ", proxy_ids=[proxy_id])


def test_create_profile_rejects_unknown_proxy_id(db):
    manager = ProfileManager(db)
    with pytest.raises(ValueError):
        manager.create_profile(name="p1", proxy_ids=[999])


def test_create_profile_rejects_too_small_rotate_interval(db):
    manager = ProfileManager(db)
    proxy_id = _add_proxy(db)
    with pytest.raises(ValueError):
        manager.create_profile(name="p1", proxy_ids=[proxy_id], auto_rotate_enabled=True,
                                auto_rotate_seconds=5)


def test_create_profile_allocates_free_port(db):
    manager = ProfileManager(db)
    proxy_id = _add_proxy(db)
    profile = manager.create_profile(name="p1", proxy_ids=[proxy_id])
    assert profile.local_port is not None
    assert profile.active_proxy_id == proxy_id


def test_create_profile_allocates_distinct_ports(db):
    manager = ProfileManager(db)
    proxy_id = _add_proxy(db)
    p1 = manager.create_profile(name="p1", proxy_ids=[proxy_id])
    p2 = manager.create_profile(name="p2", proxy_ids=[proxy_id])
    assert p1.local_port != p2.local_port


def test_rotate_ip_switches_active_proxy(db):
    manager = ProfileManager(db)
    proxy_a = _add_proxy(db, host="1.1.1.1")
    proxy_b = _add_proxy(db, host="2.2.2.2")
    profile = manager.create_profile(name="p1", proxy_ids=[proxy_a, proxy_b])
    assert profile.active_proxy_id == proxy_a

    rotated = manager.rotate_ip(profile.id)
    assert rotated.active_proxy_id == proxy_b


def test_rotate_ip_noop_with_single_proxy(db):
    manager = ProfileManager(db)
    proxy_id = _add_proxy(db)
    profile = manager.create_profile(name="p1", proxy_ids=[proxy_id])
    rotated = manager.rotate_ip(profile.id)
    assert rotated.active_proxy_id == proxy_id


async def test_delete_profile_blocked_while_running(db):
    manager = ProfileManager(db)
    proxy_id = _add_proxy(db)
    profile = manager.create_profile(name="p1", proxy_ids=[proxy_id])

    await manager.start_profile(profile.id)
    try:
        with pytest.raises(ValueError):
            manager.delete_profile(profile.id)
    finally:
        await manager.stop_profile(profile.id)

    manager.delete_profile(profile.id)  # should succeed once stopped
    assert db.get_profile(profile.id) is None


async def test_start_then_stop_updates_status(db):
    from proxy_manager.models import ProfileStatus

    manager = ProfileManager(db)
    proxy_id = _add_proxy(db)
    profile = manager.create_profile(name="p1", proxy_ids=[proxy_id])

    started = await manager.start_profile(profile.id)
    assert started.status == ProfileStatus.RUNNING

    stopped = await manager.stop_profile(profile.id)
    assert stopped.status == ProfileStatus.STOPPED


def test_launch_app_blocked_when_profile_stopped(db):
    manager = ProfileManager(db)
    proxy_id = _add_proxy(db)
    profile = manager.create_profile(name="p1", proxy_ids=[proxy_id])
    # Profile chua Start -> khong duoc phep mo app (tranh app tro toi cong dong)
    with pytest.raises(ValueError):
        manager.launch_app(profile.id, browser="chrome")


async def test_launch_app_tracks_pid_when_running(db, monkeypatch):
    from proxy_manager import profile_manager as pm

    manager = ProfileManager(db)
    proxy_id = _add_proxy(db)
    profile = manager.create_profile(name="p1", proxy_ids=[proxy_id])
    await manager.start_profile(profile.id)

    monkeypatch.setattr(pm, "launch_browser", lambda *a, **k: 9999)
    monkeypatch.setattr(pm.psutil, "pid_exists", lambda pid: pid == 9999)
    try:
        pid = manager.launch_app(profile.id, browser="chrome")
        assert pid == 9999
        assert manager.launched_apps(profile.id) == 1
    finally:
        await manager.stop_profile(profile.id)
