from __future__ import annotations

from pathlib import Path

import pytest

from proxy_manager import launcher
from proxy_manager.launcher import LauncherError, build_command, launch_browser


def test_build_command_uses_socks5_and_isolated_data_dir():
    cmd = build_command("chrome.exe", 20005, Path("/tmp/p1"), url="https://example.com")
    assert cmd[0] == "chrome.exe"
    assert "--proxy-server=socks5://127.0.0.1:20005" in cmd
    assert any(a.startswith("--user-data-dir=") for a in cmd)
    assert "--disable-quic" in cmd
    assert cmd[-1] == "https://example.com"


def test_build_command_without_url_has_no_trailing_url():
    cmd = build_command("chrome.exe", 20006, Path("/tmp/p2"), url=None)
    assert not cmd[-1].startswith("http")


def test_find_browser_returns_none_for_unknown():
    assert launcher.find_browser("nonexistent-browser") is None


def test_launch_browser_raises_when_not_found(monkeypatch):
    monkeypatch.setattr(launcher, "find_browser", lambda _b: None)
    monkeypatch.setattr(launcher, "available_browsers", lambda: [])
    with pytest.raises(LauncherError):
        launch_browser(profile_id=1, local_port=20007, browser="chrome")


def test_launch_browser_returns_pid(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "find_browser", lambda _b: "chrome.exe")
    monkeypatch.setattr(launcher, "BROWSER_PROFILES_DIR", tmp_path)

    captured = {}

    class FakePopen:
        def __init__(self, cmd):
            captured["cmd"] = cmd
            self.pid = 4321

    monkeypatch.setattr(launcher.subprocess, "Popen", FakePopen)

    pid = launch_browser(profile_id=7, local_port=20008, browser="chrome", url="https://x.test")
    assert pid == 4321
    assert "--proxy-server=socks5://127.0.0.1:20008" in captured["cmd"]
    # user-data-dir phai nam duoi thu muc profile co lap cua profile 7
    assert any(str(tmp_path / "7") in a for a in captured["cmd"])
