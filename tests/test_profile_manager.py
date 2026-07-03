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


def test_update_profile_settings_changes_fields(db):
    manager = ProfileManager(db)
    proxy_a = _add_proxy(db, host="1.1.1.1")
    proxy_b = _add_proxy(db, host="2.2.2.2")
    profile = manager.create_profile(name="old", proxy_ids=[proxy_a])

    updated = manager.update_profile_settings(
        profile.id, name="new", proxy_ids=[proxy_a, proxy_b],
        assigned_process_names=["chrome.exe"], auto_rotate_enabled=True, auto_rotate_seconds=120,
    )
    assert updated.name == "new"
    assert updated.proxy_ids == [proxy_a, proxy_b]
    assert updated.assigned_process_names == ["chrome.exe"]
    assert updated.auto_rotate_enabled is True
    assert updated.auto_rotate_seconds == 120


def test_update_profile_settings_partial_keeps_others(db):
    manager = ProfileManager(db)
    proxy_id = _add_proxy(db)
    profile = manager.create_profile(name="keep", proxy_ids=[proxy_id])
    updated = manager.update_profile_settings(profile.id, auto_rotate_enabled=True)
    assert updated.name == "keep"  # khong doi
    assert updated.auto_rotate_enabled is True


def test_update_profile_settings_rejects_unknown_proxy(db):
    manager = ProfileManager(db)
    proxy_id = _add_proxy(db)
    profile = manager.create_profile(name="p", proxy_ids=[proxy_id])
    with pytest.raises(ValueError):
        manager.update_profile_settings(profile.id, proxy_ids=[999])


def test_update_reselects_active_when_removed_from_pool(db):
    manager = ProfileManager(db)
    proxy_a = _add_proxy(db, host="1.1.1.1")
    proxy_b = _add_proxy(db, host="2.2.2.2")
    profile = manager.create_profile(name="p", proxy_ids=[proxy_a, proxy_b])
    assert profile.active_proxy_id == proxy_a
    # Bo proxy_a khoi pool -> active phai chuyen sang proxy con lai
    updated = manager.update_profile_settings(profile.id, proxy_ids=[proxy_b])
    assert updated.active_proxy_id == proxy_b


def test_failover_switches_to_live_proxy_when_active_dead(db):
    from proxy_manager.models import ProxyStatus

    manager = ProfileManager(db)
    dead = _add_proxy(db, host="1.1.1.1")
    live = _add_proxy(db, host="2.2.2.2")
    profile = manager.create_profile(name="p", proxy_ids=[dead, live])
    assert profile.active_proxy_id == dead

    db.update_proxy_health(dead, ProxyStatus.DEAD, None, None, 0)
    db.update_proxy_health(live, ProxyStatus.ALIVE, 10, "2.2.2.2", 0)

    switched = manager.failover_dead_proxies()
    assert profile.id in switched
    assert db.get_profile(profile.id).active_proxy_id == live


def test_failover_keeps_active_when_no_live_proxy(db):
    from proxy_manager.models import ProxyStatus

    manager = ProfileManager(db)
    p1 = _add_proxy(db, host="1.1.1.1")
    profile = manager.create_profile(name="p", proxy_ids=[p1])
    db.update_proxy_health(p1, ProxyStatus.DEAD, None, None, 0)

    # Khong con proxy song -> giu nguyen active (kill-switch chan traffic, khong fallback IP that)
    switched = manager.failover_dead_proxies()
    assert profile.id not in switched
    assert db.get_profile(profile.id).active_proxy_id == p1


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
