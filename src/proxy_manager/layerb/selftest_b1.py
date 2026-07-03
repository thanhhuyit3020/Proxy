"""Self-test B1 — chay THU CONG voi quyen Administrator de kiem chung bring-up.

Cach chay (mo terminal 'Run as administrator'):
    .venv\\Scripts\\python.exe -m proxy_manager.layerb.selftest_b1

Kich ban kiem chung:
1. Script bat goi outbound TCP toi cong 80/443 va reinject nguyen trang trong ~15 giay.
2. Trong luc do, MO TRINH DUYET va vao mot trang web bat ky.
3. Ket qua PASS neu:
   - Trang web VAN tai binh thuong (chung to reinject khong lam dut ket noi), VA
   - packets_seen > 0 (chung to WinDivert that su bat duoc goi).
Neu thieu admin hoac driver, script bao loi ro rang thay vi crash.
"""
from __future__ import annotations

import time

from . import admin
from .driver import ForcedRouter, build_capture_filter, pydivert_available

DURATION_SECONDS = 15


def main() -> int:
    if not admin.is_admin():
        print("[FAIL]", admin.require_admin_message())
        return 1
    if not pydivert_available():
        print("[FAIL] pydivert/WinDivert khong san sang. Cai: pip install pydivert")
        return 1

    filter_str = build_capture_filter(dest_ports=[80, 443])
    print(f"[..] Bat goi outbound TCP (cong 80/443) trong {DURATION_SECONDS}s.")
    print("     -> Hay mo trinh duyet va vao mot trang web bat ky ngay bay gio.")
    router = ForcedRouter(filter_str)
    router.start()
    try:
        time.sleep(DURATION_SECONDS)
    finally:
        router.stop()

    print(f"[..] packets_seen = {router.packets_seen}")
    if router.packets_seen > 0:
        print("[PASS] WinDivert bat duoc goi va da reinject nguyen trang.")
        print("       Neu trang web van tai binh thuong -> B1 bring-up OK.")
        return 0
    print("[WARN] Khong bat duoc goi nao. Kiem tra: co traffic HTTP/HTTPS trong luc test khong?")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
