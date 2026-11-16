"""Immutable runtime configuration loader for wuwa-buddy-assist."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class AppConfig(BaseModel):
    """Validated, immutable runtime configuration loaded from .env."""

    model_config = ConfigDict(frozen=True)

    app_mode: Literal["agent", "offline", "online"] = "agent"

    hotkey_scan_roster: str = "F9"
    hotkey_scan_bag: str = "F10"
    hotkey_calibrate: str = "F8"
    hotkey_abort: str = "F12"

    roster_count: int = Field(default=9, ge=1, le=50)
    scan_weapons: bool = True
    scan_echoes: bool = True
    scan_forte: bool = True
    scan_sequences: bool = False

    max_bag_echos: int = Field(default=50, ge=1, le=1000)
    stop_on_plus_zero: bool = True
    bag_grid_cols: int = Field(default=6, ge=1, le=12)
    bag_visible_rows: int = Field(default=4, ge=1, le=12)

    game_monitor: int = Field(default=1, ge=1, le=10)
    aspect_ratio: str = "16:9"
    base_click_delay_ms: int = Field(default=750, ge=50, le=5000)
    jitter_ms: int = Field(default=150, ge=0, le=1000)
    pixel_jitter: int = Field(default=3, ge=0, le=30)
    wait_for_game_exit: bool = True

    gemini_model: str = "gemini-2.5-flash"
    gemini_api_key: str | None = Field(default=None, repr=False)


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value in configuration: {raw!r}")


def _parse_int(raw: str | None, default: int, name: str) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"Configuration {name} must be an integer, got {raw!r}") from exc


def load_config(project_root: Path | None = None) -> AppConfig:
    """Load configuration from .env and optional .env.local overrides."""
    root = project_root or PROJECT_ROOT
    env_path = root / ".env"
    local_env_path = root / ".env.local"

    if env_path.exists():
        load_dotenv(env_path, override=False)
    if local_env_path.exists():
        load_dotenv(local_env_path, override=True)

    app_mode = os.getenv("APP_MODE", "agent").strip().lower()
    if app_mode not in {"agent", "offline", "online"}:
        raise ValueError(f"APP_MODE must be one of 'agent', 'offline', 'online'; got {app_mode!r}")

    return AppConfig(
        app_mode=app_mode,  # type: ignore[arg-type]
        hotkey_scan_roster=os.getenv("HOTKEY_SCAN_ROSTER", "F9").strip(),
        hotkey_scan_bag=os.getenv("HOTKEY_SCAN_BAG", "F10").strip(),
        hotkey_calibrate=os.getenv("HOTKEY_CALIBRATE", "F8").strip(),
        hotkey_abort=os.getenv("HOTKEY_ABORT", "F12").strip(),
        roster_count=_parse_int(os.getenv("ROSTER_COUNT"), 9, "ROSTER_COUNT"),
        scan_weapons=_parse_bool(os.getenv("SCAN_WEAPONS"), True),
        scan_echoes=_parse_bool(os.getenv("SCAN_ECHOES"), True),
        scan_forte=_parse_bool(os.getenv("SCAN_FORTE"), True),
        scan_sequences=_parse_bool(os.getenv("SCAN_SEQUENCES"), False),
        max_bag_echos=_parse_int(os.getenv("MAX_BAG_ECHOS"), 50, "MAX_BAG_ECHOS"),
        stop_on_plus_zero=_parse_bool(os.getenv("STOP_ON_PLUS_ZERO"), True),
        bag_grid_cols=_parse_int(os.getenv("BAG_GRID_COLS"), 6, "BAG_GRID_COLS"),
        bag_visible_rows=_parse_int(os.getenv("BAG_VISIBLE_ROWS"), 4, "BAG_VISIBLE_ROWS"),
        game_monitor=_parse_int(os.getenv("GAME_MONITOR"), 1, "GAME_MONITOR"),
        aspect_ratio=os.getenv("ASPECT_RATIO", "16:9").strip(),
        base_click_delay_ms=_parse_int(os.getenv("BASE_CLICK_DELAY_MS"), 300, "BASE_CLICK_DELAY_MS"),
        jitter_ms=_parse_int(os.getenv("JITTER_MS"), 80, "JITTER_MS"),
        pixel_jitter=_parse_int(os.getenv("PIXEL_JITTER"), 3, "PIXEL_JITTER"),
        wait_for_game_exit=_parse_bool(os.getenv("WAIT_FOR_GAME_EXIT"), True),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
    )


def load_json_file(path: Path) -> dict[str, Any]:
    """Read and parse a JSON file with explicit missing-file errors."""
    if not path.exists():
        raise FileNotFoundError(f"Required JSON file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}, got {type(data).__name__}")
    return data
