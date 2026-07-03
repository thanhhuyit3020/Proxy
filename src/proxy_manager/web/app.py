"""FastAPI dashboard: REST API + WebSocket realtime cho proxy pool / profiles."""
from __future__ import annotations

import dataclasses
import os
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..db import Database
from ..leak_test import run_full_leak_report
from ..models import Proxy, ProxyScheme
from ..profile_manager import ProfileManager
from ..proxy_pool import health_check_all, parse_proxy_file

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Proxy Manager Dashboard")
# PROXY_MANAGER_DB_PATH cho phep chay nhieu instance / test co lap voi DB rieng,
# khong bi dinh cung mot file trong ~/.proxy_manager.
_db_path = os.environ.get("PROXY_MANAGER_DB_PATH")
db = Database(_db_path) if _db_path else Database()
manager = ProfileManager(db)

_ws_clients: set[WebSocket] = set()


async def broadcast(event: dict) -> None:
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_json(event)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    for ws in dead:
        _ws_clients.discard(ws)


# ---------- Schemas ----------
class ProxyIn(BaseModel):
    scheme: ProxyScheme
    host: str
    port: int
    username: str | None = None
    password: str | None = None


class ProfileIn(BaseModel):
    name: str
    proxy_ids: list[int]
    assigned_process_names: list[str] = []
    auto_rotate_enabled: bool = False
    auto_rotate_seconds: int = 600


class ProfileUpdateIn(BaseModel):
    # Tat ca optional -> chi cap nhat truong duoc gui (None = giu nguyen)
    name: str | None = None
    proxy_ids: list[int] | None = None
    assigned_process_names: list[str] | None = None
    auto_rotate_enabled: bool | None = None
    auto_rotate_seconds: int | None = None


class LaunchIn(BaseModel):
    browser: str = "chrome"
    url: str | None = None


# ---------- Proxy endpoints ----------
@app.get("/api/proxies")
def list_proxies():
    return [dataclasses.asdict(p) for p in db.list_proxies()]


@app.post("/api/proxies")
def add_proxy(payload: ProxyIn):
    proxy = Proxy(id=None, **payload.model_dump())
    proxy.id = db.add_proxy(proxy)
    return dataclasses.asdict(proxy)


@app.post("/api/proxies/import")
async def import_proxies(file: UploadFile):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    proxies = parse_proxy_file(tmp_path)
    Path(tmp_path).unlink(missing_ok=True)
    for p in proxies:
        p.id = db.add_proxy(p)
    return {"imported": len(proxies)}


@app.post("/api/proxies/health-check")
async def health_check_endpoint():
    proxies = db.list_proxies()
    results = await health_check_all(proxies)
    for p in results:
        db.update_proxy_health(p.id, p.status, p.latency_ms, p.observed_ip, p.last_checked_at)
    # Sau health check: tu chuyen cac profile co proxy active vua chet sang proxy song
    switched = manager.failover_dead_proxies()
    await broadcast({"type": "health_check_done", "count": len(results)})
    if switched:
        await broadcast({"type": "auto_failover", "profile_ids": switched})
    return [dataclasses.asdict(p) for p in results]


@app.delete("/api/proxies/{proxy_id}")
def delete_proxy(proxy_id: int):
    db.delete_proxy(proxy_id)
    return {"deleted": proxy_id}


# ---------- Profile endpoints ----------
@app.get("/api/profiles")
def list_profiles():
    out = []
    for p in db.list_profiles():
        d = dataclasses.asdict(p)
        d["active_connections"] = manager.gateway_stats(p.id)
        d["launched_apps"] = manager.launched_apps(p.id)
        out.append(d)
    return out


@app.post("/api/profiles")
def create_profile(payload: ProfileIn):
    try:
        profile = manager.create_profile(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return dataclasses.asdict(profile)


@app.put("/api/profiles/{profile_id}")
async def update_profile(profile_id: int, payload: ProfileUpdateIn):
    try:
        profile = manager.update_profile_settings(profile_id, **payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await broadcast({"type": "profile_updated", "profile_id": profile_id})
    return dataclasses.asdict(profile)


@app.get("/api/processes")
def list_processes():
    from ..launcher import list_running_process_names

    return {"processes": list_running_process_names()}


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: int):
    try:
        manager.delete_profile(profile_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"deleted": profile_id}


@app.post("/api/profiles/{profile_id}/start")
async def start_profile(profile_id: int):
    try:
        profile = await manager.start_profile(profile_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await broadcast({"type": "profile_started", "profile_id": profile_id})
    return dataclasses.asdict(profile)


@app.post("/api/profiles/{profile_id}/stop")
async def stop_profile(profile_id: int):
    try:
        profile = await manager.stop_profile(profile_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await broadcast({"type": "profile_stopped", "profile_id": profile_id})
    return dataclasses.asdict(profile)


@app.post("/api/profiles/{profile_id}/rotate")
async def rotate_profile(profile_id: int):
    try:
        profile = manager.rotate_ip(profile_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await broadcast({"type": "ip_rotated", "profile_id": profile_id})
    return dataclasses.asdict(profile)


@app.get("/api/browsers")
def list_browsers():
    from ..launcher import available_browsers

    return {"available": available_browsers()}


@app.post("/api/profiles/{profile_id}/launch")
async def launch_profile_app(profile_id: int, payload: LaunchIn):
    from ..launcher import LauncherError

    try:
        pid = manager.launch_app(profile_id, browser=payload.browser, url=payload.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except LauncherError as exc:
        raise HTTPException(404, str(exc)) from exc
    await broadcast({"type": "app_launched", "profile_id": profile_id, "pid": pid})
    return {"profile_id": profile_id, "pid": pid, "browser": payload.browser}


@app.post("/api/profiles/{profile_id}/leak-test")
async def leak_test_profile(profile_id: int):
    profile = db.get_profile(profile_id)
    if profile is None:
        raise HTTPException(404, "profile khong ton tai")
    result = await run_full_leak_report(db, profile)
    await broadcast({"type": "leak_test_done", "profile_id": profile_id, "pass": result.ip_leak_pass})
    return dataclasses.asdict(result)


@app.get("/api/profiles/export.csv")
def export_profiles_csv():
    rows = db.list_profiles()
    path = Path(tempfile.gettempdir()) / "profiles_export.csv"
    with open(path, "w", encoding="utf-8") as f:
        f.write("id,name,local_port,status,active_proxy_id\n")
        for p in rows:
            f.write(f"{p.id},{p.name},{p.local_port},{p.status.value},{p.active_proxy_id}\n")
    return FileResponse(path, filename="profiles_export.csv")


# ---------- WebSocket ----------
@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)


# ---------- Static dashboard ----------
class NoCacheStaticFiles(StaticFiles):
    """Tat cache cho tai san static -- de UI cap nhat ngay khi reload trong luc dev
    (dashboard noi bo, khong can toi uu cache CDN)."""

    def is_not_modified(self, response_headers, request_headers) -> bool:  # noqa: ARG002
        return False

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


if STATIC_DIR.exists():
    app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")


# Version asset dua theo thoi diem khoi dong server -> moi lan restart la cache bi bust,
# UI luon cap nhat theo file moi nhat khi dev.
_ASSET_VERSION = str(int(time.time()))


@app.get("/", response_class=HTMLResponse)
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        html = index_file.read_text(encoding="utf-8")
        return html.replace("__ASSET_VERSION__", _ASSET_VERSION)
    return "<h1>Proxy Manager</h1><p>static/index.html not found</p>"
