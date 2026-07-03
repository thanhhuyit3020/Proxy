"""Process launcher: mo trinh duyet (Chromium-based) voi proxy tro thang vao
gateway local cua profile, kem user-data-dir co lap cho tung profile.

Layer A chi ep duoc app CO ho tro cau hinh proxy. Trinh duyet Chromium nhan
--proxy-server nen la doi tuong chinh o day. App khong ho tro proxy se can
Layer B (WinDivert) o Giai doan 2 -- KHONG xu ly trong module nay."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# Thu muc user-data-dir co lap cho tung profile (moi profile = 1 phien trinh duyet rieng)
BROWSER_PROFILES_DIR = Path.home() / ".proxy_manager" / "browser-profiles"

# Cac vi tri cai dat pho bien cua tung trinh duyet tren Windows.
_CANDIDATE_PATHS: dict[str, list[str]] = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "brave": [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
}

# Ten file thuc thi de tra cuu qua PATH neu khong tim thay o cac duong dan chuan.
_EXE_NAMES: dict[str, str] = {"chrome": "chrome", "edge": "msedge", "brave": "brave"}


class LauncherError(Exception):
    pass


def find_browser(browser: str) -> str | None:
    """Tra ve duong dan file thuc thi cua trinh duyet, hoac None neu khong tim thay."""
    browser = browser.lower()
    for candidate in _CANDIDATE_PATHS.get(browser, []):
        if candidate and Path(candidate).is_file():
            return candidate
    exe_name = _EXE_NAMES.get(browser)
    if exe_name:
        found = shutil.which(exe_name)
        if found:
            return found
    return None


def available_browsers() -> list[str]:
    """Danh sach trinh duyet phat hien duoc tren may nay."""
    return [name for name in _CANDIDATE_PATHS if find_browser(name) is not None]


def build_command(exe: str, local_port: int, data_dir: Path, url: str | None) -> list[str]:
    """Dung lenh khoi dong Chromium voi proxy SOCKS5 tro vao gateway local.

    Dung socks5:// (thay vi http://) de Chromium giai DNS qua proxy -- tranh DNS leak.
    --user-data-dir co lap cookie/session cho tung profile."""
    cmd = [
        exe,
        f"--proxy-server=socks5://127.0.0.1:{local_port}",
        f"--user-data-dir={data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        # Chan QUIC: buoc Chromium ve TCP de khong bypass proxy qua UDP/QUIC (rui ro leak).
        "--disable-quic",
    ]
    if url:
        cmd.append(url)
    return cmd


def launch_browser(
    profile_id: int, local_port: int, browser: str = "chrome", url: str | None = None
) -> int:
    """Mo trinh duyet gan voi profile. Tra ve PID cua tien trinh vua tao.

    Raise LauncherError neu khong tim thay trinh duyet tren may."""
    exe = find_browser(browser)
    if exe is None:
        raise LauncherError(
            f"khong tim thay trinh duyet '{browser}' tren may. "
            f"Cac trinh duyet phat hien duoc: {available_browsers() or 'khong co'}"
        )

    data_dir = BROWSER_PROFILES_DIR / str(profile_id)
    data_dir.mkdir(parents=True, exist_ok=True)

    cmd = build_command(exe, local_port, data_dir, url)
    proc = subprocess.Popen(cmd)  # noqa: S603 - exe da duoc xac thuc la file that o tren
    return proc.pid
