"""Route A (APP_MODE=offline): OpenCV preprocessing + RapidOCR (ONNX) extraction."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from src.capture.screen_grabber import crop_norm
from src.config import PROJECT_ROOT, load_json_file


def preprocess_for_ocr(crop: np.ndarray, invert: bool = True) -> np.ndarray:
    """Convert an image crop to a denoised high-contrast binary frame for OCR."""
    if crop is None or crop.size == 0:
        raise ValueError("Cannot preprocess an empty image crop for OCR.")

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop.copy()
    upscaled = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    blurred = cv2.GaussianBlur(upscaled, (3, 3), 0)
    thresh_type = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
    _, binary = cv2.threshold(blurred, 0, 255, thresh_type + cv2.THRESH_OTSU)
    return binary


def is_plus_zero_echo(header_text: str) -> bool:
    """Detect +0 / Lv.0 unenhanced Echoes for STOP_ON_PLUS_ZERO early termination."""
    cleaned = header_text.strip()
    return bool(re.search(r"(?:\+\s*0\b|\bLv\.?\s*0\b)", cleaned, flags=re.IGNORECASE))


def _get_rapidocr_engine() -> Any:
    """Load RapidOCR lazily so non-offline modes do not require ONNX Runtime."""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise RuntimeError(
            "APP_MODE=offline requires 'rapidocr-onnxruntime' to be installed. "
            "Install it (`pip install rapidocr-onnxruntime`) or switch APP_MODE=agent in .env."
        ) from exc
    return RapidOCR()


def extract_echo_zones(
    frame: np.ndarray,
    anchors: dict[str, Any],
    ocr_engine: Any | None = None,
) -> dict[str, list[str]]:
    """Crop the 4 Echo detail card zones and extract OCR text lines per zone."""
    crop_zones = anchors.get("crop_zones", {})
    engine = ocr_engine or _get_rapidocr_engine()

    zone_keys = (
        "echo_zone1_header",
        "echo_zone2_main_stats",
        "echo_zone3_substats",
        "echo_zone4_equipped_badge",
    )
    results: dict[str, list[str]] = {}
    for zone_key in zone_keys:
        if zone_key not in crop_zones:
            raise KeyError(f"Anchor file missing required crop zone: {zone_key!r}")
        cropped = crop_norm(frame, crop_zones[zone_key])
        processed = preprocess_for_ocr(cropped)
        ocr_out, _ = engine(processed)
        lines = [item[1].strip() for item in (ocr_out or []) if len(item) >= 2 and item[1].strip()]
        results[zone_key] = lines
    return results


def run_offline_ocr(
    captures_dir: Path | None = None,
    stop_on_plus_zero: bool = True,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Run offline RapidOCR extraction across captured PNGs."""
    root = project_root or PROJECT_ROOT
    cap_dir = captures_dir or (root / "captures" / "latest")
    anchors = load_json_file(root / "context" / "ui_anchors_16_9.json")

    bag_dir = cap_dir / "backpack_echoes"
    bag_images = sorted(bag_dir.glob("*.png")) if bag_dir.exists() else []

    if not bag_images:
        return {
            "mode": "offline",
            "status": "no_captures",
            "processed_bag_echoes": 0,
            "stopped_on_plus_zero": False,
        }

    engine = _get_rapidocr_engine()
    extracted_echoes: list[dict[str, Any]] = []
    stopped_early = False

    for img_path in bag_images:
        frame = cv2.imread(str(img_path))
        if frame is None:
            raise ValueError(f"Failed to load captured screenshot: {img_path}")
        zones = extract_echo_zones(frame, anchors, ocr_engine=engine)
        header_joined = " ".join(zones.get("echo_zone1_header", []))
        if stop_on_plus_zero and is_plus_zero_echo(header_joined):
            stopped_early = True
            break
        extracted_echoes.append({"file": img_path.name, "zones": zones})

    return {
        "mode": "offline",
        "status": "completed",
        "processed_bag_echoes": len(extracted_echoes),
        "stopped_on_plus_zero": stopped_early,
        "extracted_echoes": extracted_echoes,
    }
