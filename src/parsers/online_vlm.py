"""Route B (APP_MODE=online): Cloud Multimodal Gemini 2.5 Flash extraction."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT
from src.parsers.models import ResonatorBuild


def run_online_vlm(
    captures_dir: Path | None = None,
    model_name: str = "gemini-2.5-flash",
    api_key: str | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Batch captured character screenshots to Gemini with structured ResonatorBuild output."""
    resolved_key = api_key or os.getenv("GEMINI_API_KEY")
    if not resolved_key:
        raise RuntimeError(
            "APP_MODE=online requires GEMINI_API_KEY in your environment or .env.local. "
            "Set GEMINI_API_KEY or switch APP_MODE=agent in .env."
        )

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "APP_MODE=online requires the 'google-genai' package (`pip install google-genai`). "
            "Install it or switch APP_MODE=agent in .env."
        ) from exc

    root = project_root or PROJECT_ROOT
    cap_dir = captures_dir or (root / "captures" / "latest")
    resonators_dir = cap_dir / "resonators"

    char_dirs = sorted(p for p in resonators_dir.iterdir() if p.is_dir()) if resonators_dir.exists() else []
    if not char_dirs:
        return {
            "mode": "online",
            "status": "no_captures",
            "model": model_name,
            "parsed_characters": [],
        }

    client = genai.Client(api_key=resolved_key)
    parsed_builds: list[dict[str, Any]] = []

    for char_dir in char_dirs:
        pngs = sorted(char_dir.glob("*.png"))
        if not pngs:
            continue

        parts: list[Any] = [
            "Extract this Wuthering Waves Resonator build into the ResonatorBuild JSON schema. "
            "Normalize ATK/HP/DEF with '%' as *_PCT and without '%' as *_FLAT."
        ]
        for png in pngs:
            parts.append(
                types.Part.from_bytes(
                    data=png.read_bytes(),
                    mime_type="image/png",
                )
            )

        response = client.models.generate_content(
            model=model_name,
            contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ResonatorBuild,
            ),
        )
        parsed = ResonatorBuild.model_validate_json(response.text)
        parsed_builds.append(parsed.model_dump(by_alias=True))

    return {
        "mode": "online",
        "status": "completed",
        "model": model_name,
        "parsed_characters": parsed_builds,
    }
