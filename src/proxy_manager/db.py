"""SQLite storage cho proxies va profiles."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Profile, ProfileStatus, Proxy, ProxyScheme, ProxyStatus

DEFAULT_DB_PATH = Path.home() / ".proxy_manager" / "proxy_manager.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scheme TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    username TEXT,
    password TEXT,
    status TEXT NOT NULL DEFAULT 'unknown',
    latency_ms REAL,
    observed_ip TEXT,
    last_checked_at REAL
);

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    local_port INTEGER NOT NULL UNIQUE,
    proxy_ids TEXT NOT NULL DEFAULT '[]',
    active_proxy_id INTEGER,
    assigned_process_names TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'stopped',
    auto_rotate_enabled INTEGER NOT NULL DEFAULT 0,
    auto_rotate_seconds INTEGER NOT NULL DEFAULT 600,
    created_at REAL NOT NULL
);
"""


class Database:
    def __init__(self, path: Path | str = DEFAULT_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------- Proxy ----------
    def add_proxy(self, proxy: Proxy) -> int:
        cur = self.conn.execute(
            "INSERT INTO proxies (scheme, host, port, username, password, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (proxy.scheme.value, proxy.host, proxy.port, proxy.username,
             proxy.password, proxy.status.value),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_proxy_health(self, proxy_id: int, status: ProxyStatus,
                             latency_ms: float | None, observed_ip: str | None,
                             checked_at: float) -> None:
        self.conn.execute(
            "UPDATE proxies SET status=?, latency_ms=?, observed_ip=?, last_checked_at=? "
            "WHERE id=?",
            (status.value, latency_ms, observed_ip, checked_at, proxy_id),
        )
        self.conn.commit()

    def delete_proxy(self, proxy_id: int) -> None:
        self.conn.execute("DELETE FROM proxies WHERE id=?", (proxy_id,))
        self.conn.commit()

    def list_proxies(self) -> list[Proxy]:
        rows = self.conn.execute("SELECT * FROM proxies").fetchall()
        return [_row_to_proxy(r) for r in rows]

    def get_proxy(self, proxy_id: int) -> Proxy | None:
        row = self.conn.execute("SELECT * FROM proxies WHERE id=?", (proxy_id,)).fetchone()
        return _row_to_proxy(row) if row else None

    # ---------- Profile ----------
    def add_profile(self, profile: Profile) -> int:
        cur = self.conn.execute(
            "INSERT INTO profiles (name, local_port, proxy_ids, active_proxy_id, "
            "assigned_process_names, status, auto_rotate_enabled, auto_rotate_seconds, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (profile.name, profile.local_port, json.dumps(profile.proxy_ids),
             profile.active_proxy_id, json.dumps(profile.assigned_process_names),
             profile.status.value, int(profile.auto_rotate_enabled),
             profile.auto_rotate_seconds, profile.created_at),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_profile(self, profile: Profile) -> None:
        self.conn.execute(
            "UPDATE profiles SET name=?, local_port=?, proxy_ids=?, active_proxy_id=?, "
            "assigned_process_names=?, status=?, auto_rotate_enabled=?, auto_rotate_seconds=? "
            "WHERE id=?",
            (profile.name, profile.local_port, json.dumps(profile.proxy_ids),
             profile.active_proxy_id, json.dumps(profile.assigned_process_names),
             profile.status.value, int(profile.auto_rotate_enabled),
             profile.auto_rotate_seconds, profile.id),
        )
        self.conn.commit()

    def delete_profile(self, profile_id: int) -> None:
        self.conn.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
        self.conn.commit()

    def list_profiles(self) -> list[Profile]:
        rows = self.conn.execute("SELECT * FROM profiles").fetchall()
        return [_row_to_profile(r) for r in rows]

    def get_profile(self, profile_id: int) -> Profile | None:
        row = self.conn.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
        return _row_to_profile(row) if row else None

    def used_ports(self) -> set[int]:
        rows = self.conn.execute("SELECT local_port FROM profiles").fetchall()
        return {r["local_port"] for r in rows}


def _row_to_proxy(row: sqlite3.Row) -> Proxy:
    return Proxy(
        id=row["id"],
        scheme=ProxyScheme(row["scheme"]),
        host=row["host"],
        port=row["port"],
        username=row["username"],
        password=row["password"],
        status=ProxyStatus(row["status"]),
        latency_ms=row["latency_ms"],
        observed_ip=row["observed_ip"],
        last_checked_at=row["last_checked_at"],
    )


def _row_to_profile(row: sqlite3.Row) -> Profile:
    return Profile(
        id=row["id"],
        name=row["name"],
        local_port=row["local_port"],
        proxy_ids=json.loads(row["proxy_ids"]),
        active_proxy_id=row["active_proxy_id"],
        assigned_process_names=json.loads(row["assigned_process_names"]),
        status=ProfileStatus(row["status"]),
        auto_rotate_enabled=bool(row["auto_rotate_enabled"]),
        auto_rotate_seconds=row["auto_rotate_seconds"],
        created_at=row["created_at"],
    )
