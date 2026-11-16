"""Windows Toast notifications and game process exit watcher."""

from __future__ import annotations

import logging
import sys
import time

import psutil

logger = logging.getLogger(__name__)


def is_game_running(process_name: str = "Client-Win64-Shipping.exe") -> bool:
    """Check whether the Wuthering Waves game process is currently active."""
    target = process_name.strip().lower()
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info.get("name") or "").strip().lower()
            if name == target:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def notify_capture_complete(
    title: str = "wuwa-buddy-assist",
    message: str = "Capture Complete! You may now close Wuthering Waves to start processing.",
) -> bool:
    """Send a native Windows Toast notification without crashing on headless sessions."""
    if sys.platform != "win32":
        logger.info("[Notify] %s: %s", title, message)
        return False

    try:
        from win11toast import toast

        toast(title, message)
        return True
    except Exception as exc:
        logger.warning("Unable to display Windows Toast notification: %s", exc)
        return False


def wait_for_game_exit(
    process_name: str = "Client-Win64-Shipping.exe",
    poll_interval: float = 2.0,
    timeout_sec: float | None = None,
) -> bool:
    """Poll until Client-Win64-Shipping.exe closes. Returns True once exited, False on timeout."""
    start = time.monotonic()
    while is_game_running(process_name):
        if timeout_sec is not None and (time.monotonic() - start) >= timeout_sec:
            return False
        time.sleep(poll_interval)
    return True
