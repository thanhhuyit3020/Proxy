"""Quan ly profile: CRUD, cap phat cong local, start/stop gateway, xoay IP."""
from __future__ import annotations

import asyncio
import logging
import random
import socket

import psutil

from .db import Database
from .gateway import ProfileGateway
from .launcher import launch_browser
from .layerb.pid_map import resolve_process_name
from .models import Profile, ProfileStatus, Proxy, ProxyStatus

logger = logging.getLogger("proxy_manager.profile_manager")

PORT_RANGE = range(20000, 20999)


class ProfileManager:
    def __init__(self, db: Database):
        self.db = db
        self._gateways: dict[int, ProfileGateway] = {}
        self._rotate_tasks: dict[int, asyncio.Task] = {}
        # PID cac tien trinh (trinh duyet) da mo cho tung profile
        self._launched_pids: dict[int, list[int]] = {}

    # ---------- Port allocation ----------
    def _pick_free_port(self) -> int:
        used = self.db.used_ports()
        for port in PORT_RANGE:
            if port in used:
                continue
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                except OSError:
                    continue
            return port
        raise RuntimeError("khong con cong local trong PORT_RANGE de cap phat")

    # ---------- CRUD ----------
    def create_profile(
        self, name: str, proxy_ids: list[int], assigned_process_names: list[str] | None = None,
        auto_rotate_enabled: bool = False, auto_rotate_seconds: int = 600,
    ) -> Profile:
        name = name.strip()
        if not name:
            raise ValueError("ten profile khong duoc de trong")
        if not proxy_ids:
            raise ValueError("profile can it nhat 1 proxy")
        for proxy_id in proxy_ids:
            if self.db.get_proxy(proxy_id) is None:
                raise ValueError(f"proxy id={proxy_id} khong ton tai")
        if auto_rotate_seconds < 30:
            raise ValueError("auto_rotate_seconds toi thieu 30 giay")
        port = self._pick_free_port()
        profile = Profile(
            id=None,
            name=name,
            local_port=port,
            proxy_ids=proxy_ids,
            active_proxy_id=proxy_ids[0],
            assigned_process_names=assigned_process_names or [],
            status=ProfileStatus.STOPPED,
            auto_rotate_enabled=auto_rotate_enabled,
            auto_rotate_seconds=auto_rotate_seconds,
        )
        profile.id = self.db.add_profile(profile)
        return profile

    def update_profile_settings(
        self, profile_id: int, name: str | None = None, proxy_ids: list[int] | None = None,
        assigned_process_names: list[str] | None = None,
        auto_rotate_enabled: bool | None = None, auto_rotate_seconds: int | None = None,
    ) -> Profile:
        """Cap nhat cai dat profile. Chi doi cac truong duoc truyen (None = giu nguyen).
        Local port khong doi (giu cong da cap). Neu proxy active bi go khoi pool moi
        -> chon lai proxy dau tien trong danh sach moi."""
        profile = self.db.get_profile(profile_id)
        if profile is None:
            raise ValueError("profile khong ton tai")

        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("ten profile khong duoc de trong")
            profile.name = name

        if proxy_ids is not None:
            if not proxy_ids:
                raise ValueError("profile can it nhat 1 proxy")
            for pid in proxy_ids:
                if self.db.get_proxy(pid) is None:
                    raise ValueError(f"proxy id={pid} khong ton tai")
            profile.proxy_ids = proxy_ids
            if profile.active_proxy_id not in proxy_ids:
                profile.active_proxy_id = proxy_ids[0]

        if assigned_process_names is not None:
            profile.assigned_process_names = assigned_process_names

        if auto_rotate_seconds is not None:
            if auto_rotate_seconds < 30:
                raise ValueError("auto_rotate_seconds toi thieu 30 giay")
            profile.auto_rotate_seconds = auto_rotate_seconds

        if auto_rotate_enabled is not None:
            profile.auto_rotate_enabled = auto_rotate_enabled

        self.db.update_profile(profile)

        # Neu dang chay va vua bat auto-rotate -> khoi dong task; neu tat -> huy task
        if profile.status == ProfileStatus.RUNNING:
            if profile.auto_rotate_enabled:
                self._ensure_rotation_task(profile_id)
            else:
                task = self._rotate_tasks.pop(profile_id, None)
                if task:
                    task.cancel()

        return profile

    def delete_profile(self, profile_id: int) -> None:
        gateway = self._gateways.get(profile_id)
        if gateway and gateway.running:
            raise ValueError("dung profile truoc khi xoa")
        self.db.delete_profile(profile_id)

    def list_profiles(self) -> list[Profile]:
        return self.db.list_profiles()

    def get_profile(self, profile_id: int) -> Profile | None:
        return self.db.get_profile(profile_id)

    # ---------- Runtime ----------
    async def _get_active_proxy(self, profile_id: int) -> Proxy | None:
        profile = self.db.get_profile(profile_id)
        if not profile or profile.active_proxy_id is None:
            return None
        proxy = self.db.get_proxy(profile.active_proxy_id)
        # kill-switch (fail-closed): proxy chet thi khong tra ve gi, gateway se tu choi ket noi
        if proxy is None or proxy.status.value == "dead":
            return None
        return proxy

    async def start_profile(self, profile_id: int) -> Profile:
        profile = self.db.get_profile(profile_id)
        if profile is None:
            raise ValueError("profile khong ton tai")

        gateway = self._gateways.get(profile_id)
        if gateway is None:
            gateway = ProfileGateway(
                profile_id, profile.local_port,
                get_active_proxy=lambda pid=profile_id: self._get_active_proxy(pid),
            )
            self._gateways[profile_id] = gateway

        if not gateway.running:
            await gateway.start()

        profile.status = ProfileStatus.RUNNING
        self.db.update_profile(profile)

        if profile.auto_rotate_enabled:
            self._ensure_rotation_task(profile_id)

        return profile

    async def stop_profile(self, profile_id: int) -> Profile:
        profile = self.db.get_profile(profile_id)
        if profile is None:
            raise ValueError("profile khong ton tai")

        gateway = self._gateways.get(profile_id)
        if gateway:
            await gateway.stop()

        task = self._rotate_tasks.pop(profile_id, None)
        if task:
            task.cancel()

        profile.status = ProfileStatus.STOPPED
        self.db.update_profile(profile)
        return profile

    def rotate_ip(self, profile_id: int) -> Profile:
        """Doi thu cong sang mot proxy khac trong pool cua profile (sticky mac dinh,
        chi doi khi nguoi dung bam nut hoac auto-rotate kich hoat)."""
        profile = self.db.get_profile(profile_id)
        if profile is None:
            raise ValueError("profile khong ton tai")
        if len(profile.proxy_ids) < 2:
            return profile
        candidates = [p for p in profile.proxy_ids if p != profile.active_proxy_id]
        profile.active_proxy_id = random.choice(candidates)
        self.db.update_profile(profile)
        return profile

    def _ensure_rotation_task(self, profile_id: int) -> None:
        if profile_id in self._rotate_tasks:
            return

        async def _loop() -> None:
            while True:
                profile = self.db.get_profile(profile_id)
                if profile is None or not profile.auto_rotate_enabled:
                    return
                await asyncio.sleep(profile.auto_rotate_seconds)
                try:
                    self.rotate_ip(profile_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("auto-rotate loi cho profile=%s: %s", profile_id, exc)

        self._rotate_tasks[profile_id] = asyncio.create_task(_loop())

    def gateway_stats(self, profile_id: int) -> int:
        gateway = self._gateways.get(profile_id)
        return gateway.active_connections if gateway else 0

    # ---------- Process launcher (Layer A) ----------
    def launch_app(self, profile_id: int, browser: str = "chrome", url: str | None = None) -> int:
        """Mo trinh duyet gan proxy cua profile. Profile phai dang chay (gateway mo)
        thi moi launch, neu khong app se tro toi cong dong -> khong ket noi duoc."""
        profile = self.db.get_profile(profile_id)
        if profile is None:
            raise ValueError("profile khong ton tai")
        if profile.status != ProfileStatus.RUNNING:
            raise ValueError("profile chua chay -- bam Start truoc khi mo app")

        pid = launch_browser(profile_id, profile.local_port, browser=browser, url=url)
        self._launched_pids.setdefault(profile_id, []).append(pid)
        return pid

    def launched_apps(self, profile_id: int) -> int:
        """Dem so tien trinh da mo cho profile ma VAN con song (loc bo tien trinh da tat)."""
        pids = self._launched_pids.get(profile_id, [])
        alive = [pid for pid in pids if psutil.pid_exists(pid)]
        self._launched_pids[profile_id] = alive
        return len(alive)

    # ---------- Auto-failover ----------
    def failover_dead_proxies(self) -> list[int]:
        """Voi moi profile co active proxy vua chet, tu chuyen sang proxy con song
        trong pool cua profile. Tra ve danh sach profile_id da duoc chuyen.

        Goi sau moi lan health check. Neu khong con proxy song nao -> giu nguyen
        active_proxy_id (kill-switch se chan traffic, fail-closed, khong lo IP that)."""
        switched = []
        for profile in self.db.list_profiles():
            active = (
                self.db.get_proxy(profile.active_proxy_id)
                if profile.active_proxy_id is not None else None
            )
            if active is not None and active.status != ProxyStatus.DEAD:
                continue  # active van song -> khong can lam gi

            live = [
                pid for pid in profile.proxy_ids
                if (px := self.db.get_proxy(pid)) is not None and px.status != ProxyStatus.DEAD
            ]
            if not live:
                continue  # khong co proxy song -> kill-switch tu chan, khong fallback IP that

            profile.active_proxy_id = live[0]
            self.db.update_profile(profile)
            switched.append(profile.id)
        return switched

    # ---------- Layer B: PID -> profile mapping (B2) ----------
    def profile_for_pid(self, pid: int) -> Profile | None:
        """Tra ten tien trinh tu PID, doi chieu voi assigned_process_names cua tung
        profile (khong phan biet hoa/thuong). Tra ve profile dau tien khop, hoac None
        neu PID khong thuoc app nao duoc gan. Dung boi Handle B (redirector, B3) de
        quyet dinh goi cua tien trinh nay co bi ep dinh tuyen hay khong."""
        name = resolve_process_name(pid)
        if name is None:
            return None
        name_lower = name.lower()
        for profile in self.db.list_profiles():
            if any(name_lower == assigned.lower() for assigned in profile.assigned_process_names):
                return profile
        return None
