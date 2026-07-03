"""Kiem tra quyen Administrator (Layer B can quyen nay de nap WinDivert driver)."""
from __future__ import annotations

import ctypes
import sys


def is_admin() -> bool:
    """True neu tien trinh hien tai dang chay voi quyen Administrator (Windows).
    Tren nen tang khac tra ve False (Layer B chi ho tro Windows)."""
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 - API co the loi tren moi truong la
        return False


def require_admin_message() -> str:
    return (
        "Layer B can quyen Administrator de nap WinDivert driver. "
        "Hay dong app va mo lai bang 'Run as administrator'."
    )
