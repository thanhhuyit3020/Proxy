"""Leak test & report: xac nhan traffic di qua dung proxy, khong lo IP that,
va kill-switch chan traffic khi proxy chet (fail-closed)."""
from __future__ import annotations

import asyncio
import csv
import dataclasses
import json
import time
from pathlib import Path

from .db import Database
from .models import Profile, ProxyStatus
from .proxy_pool import IP_ECHO_HOST, IP_ECHO_PORT

LOCAL_HOST = "127.0.0.1"


@dataclasses.dataclass
class LeakTestResult:
    profile_id: int
    profile_name: str
    expected_ip: str | None
    observed_ip: str | None
    ip_leak_pass: bool
    kill_switch_pass: bool | None
    tested_at: float = dataclasses.field(default_factory=time.time)
    notes: str = ""


async def _fetch_ip_via_local_gateway(local_port: int, timeout: float = 10.0) -> str | None:
    """Gia lap mot ung dung: ket noi toi local gateway nhu mot HTTP proxy va xin IP thoat."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(LOCAL_HOST, local_port), timeout=timeout
        )
    except (OSError, asyncio.TimeoutError):
        return None

    try:
        request = (
            f"GET http://{IP_ECHO_HOST}/ HTTP/1.1\r\nHost: {IP_ECHO_HOST}\r\n"
            "Connection: close\r\n\r\n"
        )
        writer.write(request.encode())
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(4096), timeout=timeout)
    except (OSError, asyncio.TimeoutError):
        return None
    finally:
        writer.close()

    if b" 200 " not in raw.split(b"\r\n", 1)[0]:
        return None
    body = raw.split(b"\r\n\r\n", 1)[-1].decode(errors="replace").strip()
    return body or None


async def run_ip_leak_test(db: Database, profile: Profile) -> LeakTestResult:
    expected_ip = None
    if profile.active_proxy_id is not None:
        proxy = db.get_proxy(profile.active_proxy_id)
        expected_ip = proxy.observed_ip if proxy else None

    observed_ip = await _fetch_ip_via_local_gateway(profile.local_port)
    ip_leak_pass = observed_ip is not None and expected_ip is not None and observed_ip == expected_ip

    return LeakTestResult(
        profile_id=profile.id,
        profile_name=profile.name,
        expected_ip=expected_ip,
        observed_ip=observed_ip,
        ip_leak_pass=ip_leak_pass,
        kill_switch_pass=None,
        notes="" if ip_leak_pass else "IP quan sat khong khop IP proxy ky vong (co the ro ri hoac proxy chet)",
    )


async def run_kill_switch_test(db: Database, profile: Profile) -> bool:
    """Gia lap proxy chet: danh dau DEAD tam thoi, xac nhan gateway tu choi ket noi
    (fail-closed) thay vi fallback ra IP that. Khoi phuc trang thai proxy sau khi test."""
    if profile.active_proxy_id is None:
        return False
    proxy = db.get_proxy(profile.active_proxy_id)
    if proxy is None:
        return False

    original_status = proxy.status
    db.update_proxy_health(proxy.id, ProxyStatus.DEAD, None, None, time.time())
    try:
        observed_ip = await _fetch_ip_via_local_gateway(profile.local_port)
        # Pass neu gateway KHONG tra ve IP nao (tu choi ket noi thay vi fallback)
        return observed_ip is None
    finally:
        db.update_proxy_health(
            proxy.id, original_status, proxy.latency_ms, proxy.observed_ip, time.time()
        )


async def run_full_leak_report(db: Database, profile: Profile) -> LeakTestResult:
    result = await run_ip_leak_test(db, profile)
    result.kill_switch_pass = await run_kill_switch_test(db, profile)
    return result


def export_csv(results: list[LeakTestResult], path: Path | str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[f.name for f in dataclasses.fields(LeakTestResult)])
        writer.writeheader()
        for r in results:
            writer.writerow(dataclasses.asdict(r))


def export_json(results: list[LeakTestResult], path: Path | str) -> None:
    Path(path).write_text(
        json.dumps([dataclasses.asdict(r) for r in results], indent=2), encoding="utf-8"
    )
