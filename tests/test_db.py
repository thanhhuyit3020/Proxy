from __future__ import annotations

import time

from proxy_manager.models import Profile, ProfileStatus, Proxy, ProxyScheme, ProxyStatus


def _make_proxy(**overrides) -> Proxy:
    base = dict(id=None, scheme=ProxyScheme.HTTP, host="1.2.3.4", port=8080)
    base.update(overrides)
    return Proxy(**base)


def test_add_and_get_proxy(db):
    proxy_id = db.add_proxy(_make_proxy())
    proxy = db.get_proxy(proxy_id)
    assert proxy is not None
    assert proxy.host == "1.2.3.4"
    assert proxy.status == ProxyStatus.UNKNOWN


def test_update_proxy_health(db):
    proxy_id = db.add_proxy(_make_proxy())
    db.update_proxy_health(proxy_id, ProxyStatus.ALIVE, 42.5, "5.6.7.8", time.time())
    proxy = db.get_proxy(proxy_id)
    assert proxy.status == ProxyStatus.ALIVE
    assert proxy.latency_ms == 42.5
    assert proxy.observed_ip == "5.6.7.8"


def test_delete_proxy(db):
    proxy_id = db.add_proxy(_make_proxy())
    db.delete_proxy(proxy_id)
    assert db.get_proxy(proxy_id) is None


def test_list_proxies_empty_then_populated(db):
    assert db.list_proxies() == []
    db.add_proxy(_make_proxy())
    db.add_proxy(_make_proxy(host="9.9.9.9"))
    assert len(db.list_proxies()) == 2


def test_add_and_get_profile(db):
    proxy_id = db.add_proxy(_make_proxy())
    profile = Profile(id=None, name="test-profile", local_port=20001, proxy_ids=[proxy_id],
                       active_proxy_id=proxy_id)
    profile_id = db.add_profile(profile)
    stored = db.get_profile(profile_id)
    assert stored.name == "test-profile"
    assert stored.local_port == 20001
    assert stored.proxy_ids == [proxy_id]
    assert stored.status == ProfileStatus.STOPPED


def test_update_profile_roundtrip(db):
    proxy_id = db.add_proxy(_make_proxy())
    profile = Profile(id=None, name="p1", local_port=20002, proxy_ids=[proxy_id],
                       active_proxy_id=proxy_id)
    profile.id = db.add_profile(profile)

    profile.status = ProfileStatus.RUNNING
    profile.auto_rotate_enabled = True
    db.update_profile(profile)

    reloaded = db.get_profile(profile.id)
    assert reloaded.status == ProfileStatus.RUNNING
    assert reloaded.auto_rotate_enabled is True


def test_used_ports(db):
    proxy_id = db.add_proxy(_make_proxy())
    db.add_profile(Profile(id=None, name="a", local_port=20010, proxy_ids=[proxy_id]))
    db.add_profile(Profile(id=None, name="b", local_port=20011, proxy_ids=[proxy_id]))
    assert db.used_ports() == {20010, 20011}


def test_delete_profile(db):
    proxy_id = db.add_proxy(_make_proxy())
    profile_id = db.add_profile(Profile(id=None, name="a", local_port=20020, proxy_ids=[proxy_id]))
    db.delete_profile(profile_id)
    assert db.get_profile(profile_id) is None
