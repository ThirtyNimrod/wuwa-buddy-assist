"""16:9 screen capture, windowed game detection, normalized cropping, and calibration overlay."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import sys
from pathlib import Path
from typing import Any

import cv2
import mss
import numpy as np

from src.config import PROJECT_ROOT, load_json_file

logger = logging.getLogger(__name__)

RED_BGR = (0, 0, 255)
GREEN_BGR = (0, 255, 0)
CYAN_BGR = (255, 220, 0)
DARK_BG_BGR = (18, 22, 30)
WHITE_BGR = (245, 245, 245)


def validate_aspect_ratio(
    width: int,
    height: int,
    expected: str = "16:9",
    tolerance: float = 0.02,
) -> bool:
    """Validate that frame dimensions match the expected aspect ratio within tolerance."""
    if width <= 0 or height <= 0:
        raise ValueError(f"Frame dimensions must be positive, got {width}x{height}")

    parts = expected.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid aspect ratio specification: {expected!r}")

    exp_w = float(parts[0])
    exp_h = float(parts[1])
    if exp_w <= 0 or exp_h <= 0:
        raise ValueError(f"Invalid aspect ratio values: {expected!r}")

    target_ratio = exp_w / exp_h
    actual_ratio = width / height
    return abs(actual_ratio - target_ratio) <= tolerance


def _find_game_hwnd(window_titles: tuple[str, ...] = ("Wuthering Waves",)) -> int | None:
    """Find the top-level visible HWND for the Wuthering Waves client window."""
    if sys.platform != "win32" or not hasattr(ctypes, "windll"):
        return None

    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

    lowered_prefixes = tuple(t.lower() for t in window_titles)
    matches: list[int] = []
    enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title:
            return True
        if any(title.lower().startswith(prefix) for prefix in lowered_prefixes):
            class_buf = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, class_buf, 128)
            if class_buf.value == "UnrealWindow" or "wuthering" in title.lower():
                matches.append(int(hwnd))
                return False
        return True

    user32.EnumWindows(enum_proc_type(_callback), 0)
    return matches[0] if matches else None


def get_game_window_rect(
    window_titles: tuple[str, ...] = ("Wuthering Waves",),
) -> dict[str, int] | None:
    """Return exact client-area coordinates {'hwnd','left','top','width','height'} for windowed mode."""
    if sys.platform != "win32" or not hasattr(ctypes, "windll"):
        return None

    hwnd = _find_game_hwnd(window_titles=window_titles)
    if not hwnd:
        return None

    user32 = ctypes.windll.user32
    rect = wt.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None

    pt = wt.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None

    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width <= 0 or height <= 0:
        return None

    logger.info("Detected game client rect: %dx%d at (%d, %d)", width, height, pt.x, pt.y)
    return {
        "hwnd": int(hwnd),
        "left": int(pt.x),
        "top": int(pt.y),
        "width": width,
        "height": height,
    }


def focus_game_window(
    hwnd: int | None = None,
    window_titles: tuple[str, ...] = ("Wuthering Waves",),
) -> bool:
    """Restore if minimized and bring the Wuthering Waves window to the foreground."""
    if sys.platform != "win32" or not hasattr(ctypes, "windll"):
        return False

    target_hwnd = hwnd or _find_game_hwnd(window_titles=window_titles)
    if not target_hwnd:
        return False

    user32 = ctypes.windll.user32
    sw_restore = 9
    if user32.IsIconic(target_hwnd):
        user32.ShowWindow(target_hwnd, sw_restore)
    return bool(user32.SetForegroundWindow(target_hwnd))


def grab_screen(monitor_index: int = 1, prefer_window: bool = True) -> np.ndarray:
    """Capture the Wuthering Waves client area if found, otherwise the target monitor."""
    region: dict[str, int] | None = None
    if prefer_window:
        win_rect = get_game_window_rect()
        if win_rect is not None:
            region = {
                "left": win_rect["left"],
                "top": win_rect["top"],
                "width": win_rect["width"],
                "height": win_rect["height"],
            }

    with mss.mss() as sct:
        if region is None:
            monitors = sct.monitors
            if len(monitors) <= 1:
                raise RuntimeError("No display monitors detected by mss.")

            selected_idx = monitor_index
            if selected_idx < 1 or selected_idx >= len(monitors):
                logger.warning(
                    "Requested GAME_MONITOR=%d out of range (available: 1..%d). Falling back to monitor 1.",
                    monitor_index,
                    len(monitors) - 1,
                )
                selected_idx = 1

            region = dict(monitors[selected_idx])

        try:
            raw = sct.grab(region)
        except mss.exception.ScreenShotError as exc:
            raise RuntimeError(
                "Live screen capture failed (no active Windows desktop surface, e.g. locked screen "
                "or headless/sandboxed session). Run with '--calibrate --synthetic' or '--image <path>' "
                "here, or run '--calibrate' from an active Windows desktop session."
            ) from exc
        frame_bgra = np.asarray(raw, dtype=np.uint8)
        return cv2.cvtColor(frame_bgra, cv2.COLOR_BGRA2BGR)


def generate_synthetic_frame(width: int = 1600, height: int = 900) -> np.ndarray:
    """Generate a dark 16:9 reference frame for headless or pre-game calibration checks."""
    frame = np.full((height, width, 3), DARK_BG_BGR, dtype=np.uint8)

    grid_color = (34, 40, 52)
    for step in range(1, 10):
        x = int(width * (step / 10.0))
        y = int(height * (step / 10.0))
        cv2.line(frame, (x, 0), (x, height), grid_color, 1)
        cv2.line(frame, (0, y), (width, y), grid_color, 1)

    cv2.putText(
        frame,
        f"wuwa-buddy-assist // Synthetic Calibration Canvas ({width}x{height})",
        (int(width * 0.22), int(height * 0.05)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (160, 175, 195),
        2,
        cv2.LINE_AA,
    )
    return frame


def crop_norm(frame: np.ndarray, box: dict[str, float]) -> np.ndarray:
    """Crop a BGR frame using normalized [0.0..1.0] coordinates without mutating the source."""
    if frame is None or frame.size == 0:
        raise ValueError("Cannot crop an empty frame.")

    for key in ("x1", "y1", "x2", "y2"):
        if key not in box:
            raise KeyError(f"Crop box missing required coordinate key: {key!r}")

    x1_n = float(box["x1"])
    y1_n = float(box["y1"])
    x2_n = float(box["x2"])
    y2_n = float(box["y2"])

    if not (0.0 <= x1_n < x2_n <= 1.0 and 0.0 <= y1_n < y2_n <= 1.0):
        raise ValueError(
            f"Normalized crop coordinates must satisfy 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1; got {box}"
        )

    height, width = frame.shape[:2]
    x1 = int(round(x1_n * width))
    y1 = int(round(y1_n * height))
    x2 = int(round(x2_n * width))
    y2 = int(round(y2_n * height))

    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"Degenerate pixel crop box {x1},{y1},{x2},{y2} for frame {width}x{height}")

    return frame[y1:y2, x1:x2].copy()


def _draw_label_pill(
    canvas: np.ndarray,
    text: str,
    origin: tuple[int, int],
    bg_color: tuple[int, int, int],
    font_scale: float = 0.45,
) -> None:
    """Draw readable text with a solid dark pill behind it."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    thickness = 1
    (tw, th), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    x, y = origin
    h_img, w_img = canvas.shape[:2]
    x = max(4, min(x, max(4, w_img - tw - 10)))
    y = max(th + 6, min(y, h_img - baseline - 4))

    cv2.rectangle(canvas, (x - 3, y - th - 4), (x + tw + 4, y + baseline + 2), bg_color, -1)
    cv2.putText(canvas, text, (x, y), font, font_scale, WHITE_BGR, thickness, cv2.LINE_AA)


def _matches_menu(entry: dict[str, Any], menu_filter: str | None) -> bool:
    """Return True if an anchor entry applies to the requested menu filter."""
    if not menu_filter:
        return True
    menus = entry.get("menus")
    return isinstance(menus, list) and menu_filter in menus


def _draw_grid_points(
    canvas: np.ndarray,
    grid_cfg: dict[str, Any],
    prefix: str = "G",
) -> None:
    """Draw normalized grid click dots onto canvas."""
    height, width = canvas.shape[:2]
    start_x = float(grid_cfg["grid_start_x"])
    start_y = float(grid_cfg["grid_start_y"])
    step_x = float(grid_cfg["step_x"])
    step_y = float(grid_cfg["step_y"])
    cols = int(grid_cfg.get("cols", 6))
    rows = int(grid_cfg.get("visible_rows", 4))

    for row in range(rows):
        for col in range(cols):
            gx = int(round((start_x + col * step_x) * width))
            gy = int(round((start_y + row * step_y) * height))
            cv2.circle(canvas, (gx, gy), 6, CYAN_BGR, 2)
            cv2.circle(canvas, (gx, gy), 2, GREEN_BGR, -1)
            cv2.putText(
                canvas,
                f"{prefix}{row},{col}",
                (gx + 8, gy - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                CYAN_BGR,
                1,
                cv2.LINE_AA,
            )


def draw_calibration_overlay(
    frame: np.ndarray,
    anchors: dict[str, Any],
    menu_filter: str | None = None,
) -> np.ndarray:
    """Return a copy of frame annotated with red crop boxes and green click crosshairs."""
    if frame is None or frame.size == 0:
        raise ValueError("Cannot draw calibration overlay on an empty frame.")

    canvas = frame.copy()
    height, width = canvas.shape[:2]

    # 1. Red bounding boxes for OCR / VLM crop zones
    crop_zones = anchors.get("crop_zones", {})
    for name, box in crop_zones.items():
        if not _matches_menu(box, menu_filter):
            continue
        x1 = int(round(float(box["x1"]) * width))
        y1 = int(round(float(box["y1"]) * height))
        x2 = int(round(float(box["x2"]) * width))
        y2 = int(round(float(box["y2"]) * height))
        cv2.rectangle(canvas, (x1, y1), (x2, y2), RED_BGR, 2)
        label = str(box.get("label") or name)
        _draw_label_pill(canvas, f"{name}: {label}", (x1 + 4, y1 + 18), (20, 20, 120))

    # 2. Green crosshairs for static click targets
    click_targets = anchors.get("click_targets", {})
    for name, pt in click_targets.items():
        if not _matches_menu(pt, menu_filter):
            continue
        cx = int(round(float(pt["x"]) * width))
        cy = int(round(float(pt["y"]) * height))
        cv2.circle(canvas, (cx, cy), 8, GREEN_BGR, 2)
        cv2.circle(canvas, (cx, cy), 2, GREEN_BGR, -1)
        cv2.line(canvas, (cx - 14, cy), (cx + 14, cy), GREEN_BGR, 1)
        cv2.line(canvas, (cx, cy - 14), (cx, cy + 14), GREEN_BGR, 1)
        label = str(pt.get("label") or name)
        label_x = cx + 14 if cx < width * 0.72 else cx - 205
        _draw_label_pill(canvas, f"{name} ({label})", (label_x, cy + 4), (15, 75, 25), font_scale=0.38)

    # 3. Grid points (Backpack 6x4 or Echo Customization 3x5)
    bag_grid = anchors.get("backpack_grid")
    if isinstance(bag_grid, dict) and _matches_menu(bag_grid, menu_filter):
        _draw_grid_points(canvas, bag_grid, prefix="B")

    echo_grid = anchors.get("echo_customization_grid")
    if isinstance(echo_grid, dict) and _matches_menu(echo_grid, menu_filter):
        _draw_grid_points(canvas, echo_grid, prefix="E")

    ratio_ok = validate_aspect_ratio(width, height, expected=str(anchors.get("aspect_ratio", "16:9")))
    menu_tag = menu_filter or "ALL"
    status_text = f"Capture: {width}x{height} | 16:9={'OK' if ratio_ok else 'MISMATCH'} | Menu={menu_tag}"
    _draw_label_pill(canvas, status_text, (16, 26), (30, 30, 30), font_scale=0.55)
    return canvas


def run_calibration(
    output_path: Path | None = None,
    monitor_index: int = 1,
    use_synthetic: bool = False,
    anchors_path: Path | None = None,
    expected_aspect_ratio: str = "16:9",
    source_image_path: Path | None = None,
    menu_filter: str | None = None,
) -> Path:
    """Capture screen (or load source image / synthetic canvas), render overlay, and save PNG."""
    target_anchors = anchors_path or (PROJECT_ROOT / "context" / "ui_anchors_16_9.json")
    anchors = load_json_file(target_anchors)

    target_output = output_path or (PROJECT_ROOT / "captures" / "calibration_preview.png")
    target_output.parent.mkdir(parents=True, exist_ok=True)

    if source_image_path is not None:
        frame = cv2.imread(str(source_image_path))
        if frame is None:
            raise FileNotFoundError(f"Could not read source calibration image: {source_image_path}")
    elif use_synthetic:
        frame = generate_synthetic_frame()
    else:
        frame = grab_screen(monitor_index=monitor_index)

    height, width = frame.shape[:2]
    if not validate_aspect_ratio(width, height, expected=expected_aspect_ratio):
        logger.warning(
            "Captured resolution %dx%d does not match expected %s aspect ratio. "
            "Normalized coordinates may appear stretched.",
            width,
            height,
            expected_aspect_ratio,
        )

    annotated = draw_calibration_overlay(frame, anchors, menu_filter=menu_filter)
    success = cv2.imwrite(str(target_output), annotated)
    if not success:
        raise RuntimeError(f"Failed to write calibration preview image to {target_output}")

    return target_output


def run_multi_menu_calibration(
    output_dir: Path | None = None,
    menu_sources: dict[str, Path] | None = None,
    anchors_path: Path | None = None,
    project_root: Path | None = None,
) -> dict[str, Path]:
    """Generate clean per-menu calibration overlays into captures/calibration/."""
    root = project_root or PROJECT_ROOT
    out_dir = output_dir or (root / "captures" / "calibration")
    out_dir.mkdir(parents=True, exist_ok=True)

    res_root = root / "captures" / "latest" / "resonators"
    char1_dir = res_root / "char_01"
    if not char1_dir.exists() and res_root.exists():
        candidates = sorted(
            p for p in res_root.iterdir() if p.is_dir() and (p / "01_overview.png").exists()
        )
        if candidates:
            char1_dir = candidates[0]

    bag_root = root / "captures" / "latest" / "backpack_echoes"
    bag_overview = bag_root / "bag_echo_001.png"
    if not bag_overview.exists() and (bag_root / "00_backpack_overview.png").exists():
        bag_overview = bag_root / "00_backpack_overview.png"

    default_sources: dict[str, Path] = {
        "overview": char1_dir / "01_overview.png",
        "weapon": char1_dir / "02_weapon.png",
        "forte": char1_dir / "08_forte.png",
        "echo_wheel": char1_dir / "03_echo_overview.png",
        "echo_customization": char1_dir / "03_echo_slot_1.png",
        "backpack": bag_overview,
    }
    if menu_sources:
        default_sources.update(menu_sources)

    menu_specs = [
        ("terminal", "01_terminal.png"),
        ("overview", "02_overview.png"),
        ("weapon", "03_weapon.png"),
        ("forte", "04_forte.png"),
        ("echo_wheel", "05_echo_wheel.png"),
        ("echo_customization", "06_echo_customization.png"),
        ("backpack", "07_backpack.png"),
    ]

    outputs: dict[str, Path] = {}
    for menu_name, filename in menu_specs:
        src = default_sources.get(menu_name)
        has_source = src is not None and src.exists()
        out_path = run_calibration(
            output_path=out_dir / filename,
            use_synthetic=not has_source,
            anchors_path=anchors_path or (root / "context" / "ui_anchors_16_9.json"),
            source_image_path=src if has_source else None,
            menu_filter=menu_name,
        )
        outputs[menu_name] = out_path

    return outputs
