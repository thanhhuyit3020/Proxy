"""Self-test B2 — chay THU CONG voi quyen Administrator de kiem chung PID->profile mapping.

Cach chay (mo terminal 'Run as administrator'):
    .venv\\Scripts\\python.exe -m proxy_manager.layerb.selftest_b2

Kich ban kiem chung:
1. Script bat su kien CONNECT o SOCKET layer trong ~20 giay (sniff-only, KHONG dung
   goi nao -- an toan, khong lam dut ket noi cua bat ky app nao).
2. Trong luc do, MO MOT TRINH DUYET (hoac app bat ky) va vao mot trang web.
3. Sau khi ket thuc, script in bang local_port -> pid -> ten tien trinh da bat duoc.
4. Ban tu doi chieu: mo Task Manager, tim PID that su cua trinh duyet vua mo, kiem tra
   PID do co xuat hien trong bang khong.
5. PASS neu: events_seen > 0 VA it nhat 1 dong trong bang co ten tien trinh khop voi
   app ban vua mo (vd chrome.exe, msedge.exe).
"""
from __future__ import annotations

import time

from . import admin
from .pid_map import PidWatcher, pydivert_available, resolve_process_name

DURATION_SECONDS = 20


def main() -> int:
    if not admin.is_admin():
        print("[FAIL]", admin.require_admin_message())
        return 1
    if not pydivert_available():
        print("[FAIL] pydivert/WinDivert khong san sang. Cai: pip install pydivert")
        return 1

    print(f"[..] Bat su kien CONNECT o SOCKET layer (sniff-only) trong {DURATION_SECONDS}s.")
    print("     -> Hay mo mot trinh duyet va vao mot trang web bat ky ngay bay gio.")
    watcher = PidWatcher()
    watcher.start()
    try:
        time.sleep(DURATION_SECONDS)
    finally:
        watcher.stop()

    snapshot = watcher.snapshot()
    print(f"[..] events_seen = {watcher.events_seen}, entries in table = {len(snapshot)}")

    if not snapshot:
        print("[WARN] Khong bat duoc entry nao. Kiem tra: co mo ket noi TCP moi trong luc test khong?")
        return 2

    print("[..] Bang local_port -> pid -> ten tien trinh (kiem tra thu cong voi Task Manager):")
    for port, pid in sorted(snapshot.items()):
        name = resolve_process_name(pid) or "(khong xac dinh -- tien trinh co the da thoat)"
        print(f"     127.0.0.1:{port}  -> PID {pid}  -> {name}")

    print("[PASS] Da bat duoc su kien va xay bang PID. Doi chieu PID/ten o tren voi Task Manager")
    print("       de xac nhan dung tien trinh -> B2 PID mapping OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
