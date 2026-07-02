"""FastAPI dashboard: REST API + WebSocket realtime cho proxy pool / profiles."""
from __future__ import annotations

import dataclasses
import tempfile
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
db = Database()
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
    await broadcast({"type": "health_check_done", "count": len(results)})
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
        out.append(d)
    return out


@app.post("/api/profiles")
def create_profile(payload: ProfileIn):
    try:
        profile = manager.create_profile(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return dataclasses.asdict(profile)


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
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return index_file.read_text(encoding="utf-8")
    return "<h1>Proxy Manager</h1><p>static/index.html not found</p>"
