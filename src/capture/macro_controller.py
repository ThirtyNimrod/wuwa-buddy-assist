"""Humanized auto-click capture daemon for Resonators (F9) and Backpack Echoes (F10)."""

from __future__ import annotations

import ctypes
import json
import logging
import random
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import cv2
import mss
import numpy as np

from src.capture.screen_grabber import focus_game_window, get_game_window_rect, grab_screen
from src.config import PROJECT_ROOT, AppConfig, load_config, load_json_file

logger = logging.getLogger(__name__)


class AbortCaptureError(RuntimeError):
    """Raised immediately when the F12 kill-switch is activated."""


def is_admin() -> bool:
    """Return True when the current Python process runs with Windows Administrator privileges."""
    if sys.platform != "win32" or not hasattr(ctypes, "windll"):
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _default_hover(x: int, y: int) -> None:
    import pydirectinput

    pydirectinput.PAUSE = 0.02
    pydirectinput.moveTo(x, y)


def _default_click(x: int, y: int) -> None:
    import pydirectinput

    pydirectinput.PAUSE = 0.02
    pydirectinput.moveTo(x, y)
    time.sleep(0.10)
    pydirectinput.mouseDown()
    time.sleep(0.06)
    pydirectinput.mouseUp()


def _default_key(key: str) -> None:
    import pydirectinput

    pydirectinput.PAUSE = 0.02
    pydirectinput.press(key)


def _default_scroll(clicks: int) -> None:
    if sys.platform != "win32" or not hasattr(ctypes, "windll") or clicks == 0:
        return
    mouseeventf_wheel = 0x0800
    step = 120 if clicks > 0 else -120
    wheel_delta = ctypes.c_uint32(step).value
    for _ in range(abs(int(clicks))):
        ctypes.windll.user32.mouse_event(mouseeventf_wheel, 0, 0, wheel_delta, 0)
        time.sleep(0.06)


class MacroController:
    """Humanized input controller for automated Wuthering Waves screenshot capture."""

    def __init__(
        self,
        config: AppConfig | None = None,
        anchors: dict[str, Any] | None = None,
        captures_dir: Path | None = None,
        dry_run: bool = False,
        abort_event: threading.Event | None = None,
        grab_fn: Callable[[int], np.ndarray] | None = None,
        click_fn: Callable[[int, int], None] | None = None,
        hover_fn: Callable[[int, int], None] | None = None,
        key_fn: Callable[[str], None] | None = None,
        scroll_fn: Callable[[int], None] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        focus_fn: Callable[[], bool] | None = None,
        rect_fn: Callable[[], dict[str, int] | None] | None = None,
    ) -> None:
        self.config = config or load_config()
        self.anchors = anchors or load_json_file(PROJECT_ROOT / "context" / "ui_anchors_16_9.json")
        self.captures_dir = captures_dir or (PROJECT_ROOT / "captures" / "latest")
        self.dry_run = dry_run
        self.abort_event = abort_event or threading.Event()

        self._uses_real_input = (not dry_run) and (click_fn is None)
        self._grab_fn = grab_fn or (lambda mon: grab_screen(monitor_index=mon, prefer_window=True))
        self._click_fn = click_fn or (
            (lambda _x, _y: None) if dry_run else _default_click
        )
        self._hover_fn = hover_fn or (
            (lambda _x, _y: None) if (dry_run or click_fn is not None) else _default_hover
        )
        self._key_fn = key_fn or (
            (lambda _k: None) if dry_run else _default_key
        )
        self._scroll_fn = scroll_fn or (
            (lambda _c: None) if dry_run else _default_scroll
        )
        self._sleep_fn = sleep_fn or ((lambda _s: None) if dry_run else time.sleep)
        self._focus_fn = focus_fn or ((lambda: True) if dry_run else focus_game_window)
        self._rect_fn = rect_fn or get_game_window_rect

    def request_abort(self) -> None:
        """Activate the F12 abort flag so active capture stops before the next step."""
        self.abort_event.set()

    def clear_abort(self) -> None:
        """Reset the abort flag before starting a new scan."""
        self.abort_event.clear()

    def _require_admin_if_live(self) -> None:
        if self._uses_real_input and not is_admin():
            raise PermissionError(
                "Windows Administrator privileges are required for pydirectinput inside Wuthering Waves. "
                "Launch via run_capture_admin.bat or an elevated Administrator terminal."
            )

    def _check_abort(self) -> None:
        if self.abort_event.is_set():
            raise AbortCaptureError("Capture aborted by user (F12 kill-switch).")

    def _human_sleep(self, extra_ms: int = 0) -> None:
        self._check_abort()
        delay_ms = (
            self.config.base_click_delay_ms
            + random.randint(0, self.config.jitter_ms)
            + max(0, extra_ms)
        )
        self._sleep_fn(delay_ms / 1000.0)
        self._check_abort()

    def _resolve_client_bounds(self) -> tuple[int, int, int, int]:
        """Resolve exact (left, top, width, height) of the 16:9 game client area (e.g., 1600x900)."""
        win_rect = self._rect_fn()
        if win_rect and win_rect.get("width", 0) > 0 and win_rect.get("height", 0) > 0:
            return (
                int(win_rect["left"]),
                int(win_rect["top"]),
                int(win_rect["width"]),
                int(win_rect["height"]),
            )

        if self.dry_run:
            return (0, 0, 1600, 900)

        with mss.mss() as sct:
            monitors = sct.monitors
            idx = self.config.game_monitor
            if idx < 1 or idx >= len(monitors):
                idx = 1
            mon = monitors[idx]
            return (int(mon["left"]), int(mon["top"]), int(mon["width"]), int(mon["height"]))

    def _hover_norm(self, norm_x: float, norm_y: float) -> tuple[int, int]:
        self._check_abort()
        left, top, width, height = self._resolve_client_bounds()
        abs_x = left + int(round(norm_x * width))
        abs_y = top + int(round(norm_y * height))
        self._hover_fn(abs_x, abs_y)
        self._sleep_fn(0.08)
        return abs_x, abs_y

    def _click_norm(self, norm_x: float, norm_y: float, extra_wait_ms: int = 120) -> tuple[int, int]:
        self._check_abort()
        left, top, width, height = self._resolve_client_bounds()
        jitter = self.config.pixel_jitter
        dx = random.randint(-jitter, jitter) if jitter > 0 else 0
        dy = random.randint(-jitter, jitter) if jitter > 0 else 0

        abs_x = left + int(round(norm_x * width)) + dx
        abs_y = top + int(round(norm_y * height)) + dy

        self._click_fn(abs_x, abs_y)
        self._human_sleep(extra_ms=extra_wait_ms)
        return abs_x, abs_y

    def _click_target(self, target_name: str, extra_wait_ms: int = 120) -> tuple[int, int]:
        targets = self.anchors.get("click_targets", {})
        if target_name not in targets:
            raise KeyError(f"Anchor target {target_name!r} not defined in ui_anchors_16_9.json")
        pt = targets[target_name]
        return self._click_norm(float(pt["x"]), float(pt["y"]), extra_wait_ms=extra_wait_ms)

    def _capture_to(self, dest_path: Path) -> Path:
        self._check_abort()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        frame = self._grab_fn(self.config.game_monitor)
        if frame is None or frame.size == 0:
            raise RuntimeError(f"Captured empty frame while saving {dest_path}")
        if not cv2.imwrite(str(dest_path), frame):
            raise RuntimeError(f"Failed to write screenshot PNG: {dest_path}")
        return dest_path

    def _update_manifest(self, updates: dict[str, Any]) -> Path:
        manifest_path = self.captures_dir / "session_manifest.json"
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        existing: dict[str, Any] = {}
        if manifest_path.exists():
            try:
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = {}

        merged = {
            **existing,
            **updates,
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        manifest_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        return manifest_path

    def open_resonators_from_terminal(self) -> None:
        """Focus the Wuthering Waves window on the Terminal menu and click Resonators."""
        self._require_admin_if_live()
        self._check_abort()
        self._focus_fn()
        self._sleep_fn(1.0)
        self._click_target("terminal_resonators", extra_wait_ms=2800)

    def scan_roster_loop(
        self,
        roster_count: int | None = None,
        from_terminal: bool = False,
    ) -> dict[str, Any]:
        """Iterate through N Resonators on the right sidebar and capture Overview/Weapon/Forte/Echoes."""
        self._require_admin_if_live()
        self.clear_abort()

        if from_terminal:
            self.open_resonators_from_terminal()

        total = roster_count or self.config.roster_count
        resonators_root = self.captures_dir / "resonators"
        captured_chars: dict[str, list[str]] = {}

        for idx in range(1, total + 1):
            self._check_abort()
            slot_key = f"roster_slot_{idx}"
            if slot_key not in self.anchors.get("click_targets", {}):
                logger.warning("No click target defined for %s; stopping roster scan at %d.", slot_key, idx - 1)
                break

            if idx > 6:
                # Scroll the right roster sidebar down 1 notch so character 7+ moves into bottom slot 6
                self._hover_norm(0.945, 0.562)
                self._scroll_fn(-1)
                self._human_sleep(extra_ms=800)

            self._click_target(slot_key, extra_wait_ms=1400)

            char_id = f"char_{idx:02d}"
            char_dir = resonators_root / char_id
            saved_files: list[str] = []

            self._click_target("tab_overview", extra_wait_ms=1100)
            saved_files.append(str(self._capture_to(char_dir / "01_overview.png")))

            if self.config.scan_weapons:
                self._click_target("tab_weapon", extra_wait_ms=1100)
                saved_files.append(str(self._capture_to(char_dir / "02_weapon.png")))

            if self.config.scan_forte:
                self._click_target("tab_forte", extra_wait_ms=1100)
                saved_files.append(str(self._capture_to(char_dir / "08_forte.png")))

            if self.config.scan_sequences:
                self._click_target("tab_sequences", extra_wait_ms=1100)
                saved_files.append(str(self._capture_to(char_dir / "09_sequences.png")))

            if self.config.scan_echoes:
                self._click_target("tab_echoes", extra_wait_ms=1200)
                saved_files.append(str(self._capture_to(char_dir / "03_echo_overview.png")))

                # Enter Menu B (Echo Customization Menu), where Slot 1 is already selected
                self._click_target("echo_wheel_slot_1", extra_wait_ms=1200)
                saved_files.append(str(self._capture_to(char_dir / "03_echo_slot_1.png")))

                for echo_slot in range(2, 6):
                    self._click_target(f"echo_slot_{echo_slot}", extra_wait_ms=900)
                    saved_files.append(
                        str(self._capture_to(char_dir / f"03_echo_slot_{echo_slot}.png"))
                    )

                # Exit Echo Customization Menu back to the Resonator screen so right sidebar is visible
                self._click_target("echo_detail_close", extra_wait_ms=1200)

            captured_chars[char_id] = saved_files

        _, _, width, height = self._resolve_client_bounds()
        manifest_path = self._update_manifest(
            {
                "client_resolution": f"{width}x{height}",
                "roster_count_scanned": len(captured_chars),
                "resonators": captured_chars,
            }
        )
        return {
            "status": "completed",
            "characters_scanned": len(captured_chars),
            "manifest_path": str(manifest_path),
        }

    def scan_backpack_loop(
        self,
        max_echos: int | None = None,
        navigate_from_game: bool = False,
    ) -> dict[str, Any]:
        """Iterate through the 6x4 Backpack Echo grid, scrolling down every 4 rows."""
        self._require_admin_if_live()
        self.clear_abort()

        bag_dir = self.captures_dir / "backpack_echoes"
        saved_files: list[str] = []

        if navigate_from_game:
            self._focus_fn()
            # 1st ESC exits Resonators screen -> Terminal Pause Menu
            self._key_fn("esc")
            self._sleep_fn(2.4)
            # 2nd ESC exits Terminal Pause Menu -> Overworld
            self._key_fn("esc")
            self._sleep_fn(2.2)
            # B opens Backpack from Overworld
            self._key_fn("b")
            self._sleep_fn(2.2)
            self._capture_to(bag_dir / "00_backpack_overview.png")
            self._click_target("backpack_tab_echoes", extra_wait_ms=1200)

        bag_cfg = self.anchors.get("backpack_grid", {})
        start_x = float(bag_cfg["grid_start_x"])
        start_y = float(bag_cfg["grid_start_y"])
        step_x = float(bag_cfg["step_x"])
        step_y = float(bag_cfg["step_y"])
        cols = int(bag_cfg.get("cols", self.config.bag_grid_cols))
        rows = int(bag_cfg.get("visible_rows", self.config.bag_visible_rows))

        target_max = max_echos or self.config.max_bag_echos

        scanned = 0
        page_idx = 0
        while scanned < target_max:
            row_start = 0 if (page_idx == 0 or rows <= 1) else 1
            for row in range(row_start, rows):
                for col in range(cols):
                    if scanned >= target_max:
                        break
                    self._check_abort()
                    gx = start_x + col * step_x
                    gy = start_y + row * step_y
                    self._click_norm(gx, gy, extra_wait_ms=160)
                    scanned += 1
                    img_path = self._capture_to(bag_dir / f"bag_echo_{scanned:03d}.png")
                    saved_files.append(str(img_path))
                if scanned >= target_max:
                    break

            if scanned < target_max:
                self._check_abort()
                # Hover inside the Echo grid and send 5 discrete wheel notches (~547.5px = 3 rows)
                center_x = start_x + ((cols - 1) / 2.0) * step_x
                center_y = start_y + ((rows - 1) / 2.0) * step_y
                self._hover_norm(center_x, center_y)
                self._scroll_fn(-5)
                self._human_sleep(extra_ms=600)
                page_idx += 1

        manifest_path = self._update_manifest(
            {
                "backpack_count_scanned": len(saved_files),
                "backpack_echoes": saved_files,
            }
        )
        return {
            "status": "completed",
            "echoes_scanned": len(saved_files),
            "manifest_path": str(manifest_path),
        }
