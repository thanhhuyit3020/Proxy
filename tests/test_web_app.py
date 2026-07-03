"""Smoke test cho FastAPI dashboard, dung DB tam thoi (khong dung tren ~/.proxy_manager)."""
from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXY_MANAGER_DB_PATH", str(tmp_path / "web_test.db"))
    from proxy_manager.web import app as app_module

    importlib.reload(app_module)  # ap dung PROXY_MANAGER_DB_PATH moi cho lan reload nay
    with TestClient(app_module.app) as c:
        yield c


def test_list_proxies_empty(client):
    resp = client.get("/api/proxies")
    assert resp.status_code == 200
    assert resp.json() == []


def test_add_and_list_proxy(client):
    resp = client.post("/api/proxies", json={
        "scheme": "http", "host": "1.2.3.4", "port": 8080,
    })
    assert resp.status_code == 200
    proxy = resp.json()
    assert proxy["host"] == "1.2.3.4"

    resp = client.get("/api/proxies")
    assert len(resp.json()) == 1


def test_create_profile_without_proxy_returns_400(client):
    resp = client.post("/api/profiles", json={"name": "p1", "proxy_ids": [999]})
    assert resp.status_code == 400


def test_create_profile_then_start_stop(client):
    proxy_resp = client.post("/api/proxies", json={
        "scheme": "socks5", "host": "9.9.9.9", "port": 1080,
    })
    proxy_id = proxy_resp.json()["id"]

    profile_resp = client.post("/api/profiles", json={"name": "p1", "proxy_ids": [proxy_id]})
    assert profile_resp.status_code == 200
    profile_id = profile_resp.json()["id"]

    start_resp = client.post(f"/api/profiles/{profile_id}/start")
    assert start_resp.status_code == 200
    assert start_resp.json()["status"] == "running"

    stop_resp = client.post(f"/api/profiles/{profile_id}/stop")
    assert stop_resp.status_code == 200
    assert stop_resp.json()["status"] == "stopped"


def test_delete_unknown_proxy_is_idempotent(client):
    resp = client.delete("/api/proxies/12345")
    assert resp.status_code == 200


def test_list_browsers_endpoint(client):
    resp = client.get("/api/browsers")
    assert resp.status_code == 200
    assert "available" in resp.json()
    assert isinstance(resp.json()["available"], list)


def test_launch_rejected_when_profile_stopped(client):
    proxy_id = client.post("/api/proxies", json={
        "scheme": "socks5", "host": "9.9.9.9", "port": 1080,
    }).json()["id"]
    profile_id = client.post("/api/profiles", json={"name": "p1", "proxy_ids": [proxy_id]}).json()["id"]

    # Profile chua start -> launch phai tra 400 (guard), khong mo trinh duyet
    resp = client.post(f"/api/profiles/{profile_id}/launch", json={"browser": "chrome"})
    assert resp.status_code == 400


def test_static_assets_served_with_no_cache(client):
    resp = client.get("/static/app.js")
    assert resp.status_code == 200
    assert "no-cache" in resp.headers.get("cache-control", "")


def test_index_injects_asset_version(client):
    resp = client.get("/")
    assert resp.status_code == 200
    # placeholder phai duoc thay bang version that -> cache-busting hoat dong
    assert "__ASSET_VERSION__" not in resp.text
    assert "app.js?v=" in resp.text


def test_update_profile_endpoint(client):
    proxy_id = client.post("/api/proxies", json={
        "scheme": "socks5", "host": "9.9.9.9", "port": 1080,
    }).json()["id"]
    profile_id = client.post("/api/profiles", json={"name": "p1", "proxy_ids": [proxy_id]}).json()["id"]

    resp = client.put(f"/api/profiles/{profile_id}", json={
        "name": "renamed", "auto_rotate_enabled": True, "auto_rotate_seconds": 90,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "renamed"
    assert body["auto_rotate_enabled"] is True
    assert body["auto_rotate_seconds"] == 90


def test_update_profile_rejects_bad_rotate_interval(client):
    proxy_id = client.post("/api/proxies", json={
        "scheme": "socks5", "host": "9.9.9.9", "port": 1080,
    }).json()["id"]
    profile_id = client.post("/api/profiles", json={"name": "p1", "proxy_ids": [proxy_id]}).json()["id"]

    resp = client.put(f"/api/profiles/{profile_id}", json={"auto_rotate_seconds": 5})
    assert resp.status_code == 400


def test_list_processes_endpoint(client):
    resp = client.get("/api/processes")
    assert resp.status_code == 200
    procs = resp.json()["processes"]
    assert isinstance(procs, list)
    # Test process nay dang chay -> phai co it nhat 1 tien trinh
    assert len(procs) > 0
