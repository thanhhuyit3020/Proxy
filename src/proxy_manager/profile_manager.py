"""Quan ly profile: CRUD, cap phat cong local, start/stop gateway, xoay IP."""
from __future__ import annotations

import asyncio
import logging
import random
import socket

from .db import Database
from .gateway import ProfileGateway
from .models import Profile, ProfileStatus, Proxy

logger = logging.getLogger("proxy_manager.profile_manager")

PORT_RANGE = range(20000, 20999)


class ProfileManager:
    def __init__(self, db: Database):
        self.db = db
        self._gateways: dict[int, ProfileGateway] = {}
        self._rotate_tasks: dict[int, asyncio.Task] = {}

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
        if not proxy_ids:
            raise ValueError("profile can it nhat 1 proxy")
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
