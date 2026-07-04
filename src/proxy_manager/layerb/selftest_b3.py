"""Self-test B3 -- kiem chung trong suot end-to-end (B1+B2+B3 cung mot luc) voi proxy that.

Cach chay (mo terminal 'Run as administrator'):
    .venv\\Scripts\\python.exe -m proxy_manager.layerb.selftest_b3 <proxy-url>

<proxy-url> dinh dang giong proxy_pool (vd: socks5://user:pass@1.2.3.4:1080,
hoac http://host:port khong can auth).

Kich ban kiem chung:
1. Tao DB tam, 1 profile gan proxy do, assigned_process_names=["curl.exe"].
2. Health-check proxy -- phai con song moi tiep tuc.
3. Start profile (Layer A gateway) + Layer B (B2 PidWatcher + B3 Redirector).
4. Chay `curl.exe` NHU MOT SUBPROCESS BINH THUONG -- KHONG dung flag --proxy nao,
   mo phong dung mot app khong ho tro cau hinh proxy (game client, tool bat ky).
5. So sanh IP curl nhan duoc voi observed_ip cua proxy (buoc 2).
6. Test kill-switch: danh dau proxy DEAD, chay lai curl -- PASS neu curl KHONG lay
   duoc IP nao (timeout), chung minh khong fallback ra IP that.
7. Don dep: stop Layer B, stop profile, xoa DB tam.

PASS neu ca buoc 5 (redirect dung) VA buoc 6 (kill-switch khong leak) deu dat.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import admin
from .driver import pydivert_available
from ..db import Database
from ..models import ProxyStatus
from ..profile_manager import ProfileManager
from ..proxy_pool import IP_ECHO_HOST, health_check, parse_proxy_line

CURL_TIMEOUT_SECONDS = 12


def _run_curl() -> str | None:
    """Chay curl.exe nhu mot app binh thuong (khong proxy flag). Tra ve IP text
    hoac None neu that bai/timeout."""
    curl = shutil.which("curl") or shutil.which("curl.exe")
    if curl is None:
        print("[FAIL] khong tim thay curl.exe tren PATH (co san tu Windows 10 1803+).")
        return None
    try:
        result = subprocess.run(
            [curl, "-s", "--max-time", str(CURL_TIMEOUT_SECONDS), f"https://{IP_ECHO_HOST}/"],
            capture_output=True, text=True, timeout=CURL_TIMEOUT_SECONDS + 5,
        )
    except subprocess.TimeoutExpired:
        return None
    output = result.stdout.strip()
    return output or None


async def main_async(proxy_url: str) -> int:
    if not admin.is_admin():
        print("[FAIL]", admin.require_admin_message())
        return 1
    if not pydivert_available():
        print("[FAIL] pydivert/WinDivert khong san sang. Cai: pip install pydivert")
        return 1

    proxy = parse_proxy_line(proxy_url)
    if proxy is None:
        print(f"[FAIL] khong parse duoc proxy URL: {proxy_url!r}")
        return 1

    print(f"[..] Health-check proxy {proxy.label()}...")
    proxy = await health_check(proxy)
    if proxy.status != ProxyStatus.ALIVE:
        print(f"[FAIL] proxy {proxy.label()} khong song. Chon proxy khac roi thu lai.")
        return 1
    print(f"[..] Proxy song, IP ky vong = {proxy.observed_ip}, latency = {proxy.latency_ms}ms")

    db_path = Path(tempfile.gettempdir()) / f"selftest_b3_{int(time.time())}.db"
    db = Database(db_path)
    manager = ProfileManager(db)
    proxy_id = db.add_proxy(proxy)
    db.update_proxy_health(proxy_id, proxy.status, proxy.latency_ms, proxy.observed_ip, time.time())

    profile = manager.create_profile(
        name="selftest-b3", proxy_ids=[proxy_id], assigned_process_names=["curl.exe"],
    )

    try:
        await manager.start_profile(profile.id)
        print(f"[..] Profile started, gateway tren 127.0.0.1:{profile.local_port}")
        manager.start_layer_b()
        print("[..] Layer B (B2 PidWatcher + B3 Redirector) da bat.")

        print(f"[..] Chay curl.exe (khong proxy flag) toi https://{IP_ECHO_HOST}/ ...")
        observed = _run_curl()
        print(f"[..] curl tra ve: {observed!r}")

        redirect_pass = observed is not None and observed == proxy.observed_ip
        if redirect_pass:
            print(f"[PASS] IP khop proxy ({proxy.observed_ip}) -- transparent redirect hoat dong.")
        else:
            print(f"[FAIL] IP khong khop (mong {proxy.observed_ip}, nhan {observed!r}).")

        print("[..] Test kill-switch: danh dau proxy DEAD, chay lai curl...")
        db.update_proxy_health(proxy_id, ProxyStatus.DEAD, None, None, time.time())
        killswitch_observed = _run_curl()
        killswitch_pass = killswitch_observed is None
        if killswitch_pass:
            print("[PASS] curl khong lay duoc IP nao khi proxy chet -- khong fallback ra IP that.")
        else:
            print(f"[FAIL] curl VAN lay duoc IP ({killswitch_observed!r}) du proxy da chet -- RO RI IP THAT!")

        return 0 if (redirect_pass and killswitch_pass) else 2
    finally:
        manager.stop_layer_b()
        await manager.stop_profile(profile.id)
        db.conn.close()
        db_path.unlink(missing_ok=True)


def main() -> int:
    if len(sys.argv) != 2:
        print("Dung: selftest_b3.py <proxy-url>")
        print("  vd:  selftest_b3.py socks5://user:pass@1.2.3.4:1080")
        return 1
    return asyncio.run(main_async(sys.argv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
