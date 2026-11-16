"""Parser mode router dispatching to agent, offline, or online pipelines."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.config import AppConfig, PROJECT_ROOT, load_config
from src.parsers.agent_bridge import run_agent_bridge
from src.parsers.offline_ocr import run_offline_ocr
from src.parsers.online_vlm import run_online_vlm


def parse_captures(
    mode: str | None = None,
    config: AppConfig | None = None,
    captures_dir: Path | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Dispatch screenshot parsing based on APP_MODE ('agent' | 'offline' | 'online')."""
    root = project_root or PROJECT_ROOT
    cfg = config or load_config(project_root=root)
    active_mode = (mode or cfg.app_mode).strip().lower()

    if active_mode == "agent":
        return run_agent_bridge(captures_dir=captures_dir, project_root=root)
    if active_mode == "offline":
        return run_offline_ocr(
            captures_dir=captures_dir,
            stop_on_plus_zero=cfg.stop_on_plus_zero,
            project_root=root,
        )
    if active_mode == "online":
        return run_online_vlm(
            captures_dir=captures_dir,
            model_name=cfg.gemini_model,
            api_key=cfg.gemini_api_key,
            project_root=root,
        )

    raise ValueError(
        f"Unsupported parser mode: {active_mode!r}. Expected 'agent', 'offline', or 'online'."
    )
