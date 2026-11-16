"""Route C (APP_MODE=agent): Generates AGENT_TASK.md for IDE AI agent vision parsing."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT
from src.parsers.models import EchoBagData, RosterData


def canonical_resonator_folder_name(
    name: str,
    element: str = "",
    player_name: str = "Perriwinkle",
) -> str:
    """Return canonical folder name: RoverHavoc/RoverAero/RoverSpectro/RoverElectro or <CharacterName>."""
    cleaned = re.sub(r"\s+", " ", name.strip())
    if not cleaned:
        raise ValueError("Resonator name cannot be empty.")

    lowered = cleaned.lower()
    player_lower = player_name.strip().lower()
    is_rover = lowered.startswith("rover") or (bool(player_lower) and lowered == player_lower)

    if is_rover:
        resolved_elem = element.strip()
        if not resolved_elem:
            match = re.search(r"(?:\(|:\s*)([A-Za-z]+)\)?", cleaned)
            if match:
                resolved_elem = match.group(1)
        if not resolved_elem:
            return "Rover"
        return f"Rover{resolved_elem.capitalize()}"

    tokens = re.findall(r"[A-Za-z0-9]+", cleaned)
    if not tokens:
        raise ValueError(f"Could not derive folder name from resonator name: {name!r}")
    return "".join(tok[0].upper() + tok[1:] for tok in tokens)


def rename_resonator_folders(
    captures_dir: Path,
    slot_mapping: dict[str, tuple[str, str]],
    player_name: str = "Perriwinkle",
) -> dict[str, str]:
    """Rename char_XX capture folders to canonical Resonator folder names and sync manifest."""
    resonators_dir = captures_dir / "resonators"
    if not resonators_dir.exists():
        return {}

    renamed: dict[str, str] = {}
    for old_name, (char_name, element) in slot_mapping.items():
        src = resonators_dir / old_name
        if not src.exists() or not src.is_dir():
            continue

        new_name = canonical_resonator_folder_name(
            char_name,
            element=element,
            player_name=player_name,
        )
        dst = resonators_dir / new_name

        if src != dst:
            if dst.exists():
                shutil.rmtree(dst)
            src.rename(dst)
        renamed[old_name] = new_name

    manifest_path = captures_dir / "session_manifest.json"
    if renamed and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        old_resonators = manifest.get("resonators")
        if isinstance(old_resonators, dict):
            updated_resonators: dict[str, list[str]] = {}
            for folder_key, paths in old_resonators.items():
                mapped_key = renamed.get(folder_key, folder_key)
                updated_paths = [
                    p.replace(f"\\{folder_key}\\", f"\\{mapped_key}\\").replace(
                        f"/{folder_key}/", f"/{mapped_key}/"
                    )
                    for p in paths
                ]
                updated_resonators[mapped_key] = updated_paths
            manifest["resonators"] = updated_resonators
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return renamed


def _collect_captures(captures_dir: Path) -> tuple[dict[str, list[Path]], list[Path]]:
    """Discover resonator folder screenshots and backpack echo screenshots."""
    resonators_dir = captures_dir / "resonators"
    bag_dir = captures_dir / "backpack_echoes"

    resonator_files: dict[str, list[Path]] = {}
    if resonators_dir.exists():
        for char_dir in sorted(p for p in resonators_dir.iterdir() if p.is_dir()):
            pngs = sorted(char_dir.glob("*.png"))
            if pngs:
                resonator_files[char_dir.name] = pngs

    bag_files: list[Path] = []
    if bag_dir.exists():
        bag_files = sorted(bag_dir.glob("*.png"))

    return resonator_files, bag_files


def generate_agent_task(
    captures_dir: Path | None = None,
    project_root: Path | None = None,
) -> Path:
    """Scan captures/latest/ and write AGENT_TASK.md with schemas and grounding context."""
    root = project_root or PROJECT_ROOT
    cap_dir = captures_dir or (root / "captures" / "latest")
    cap_dir.mkdir(parents=True, exist_ok=True)

    resonator_files, bag_files = _collect_captures(cap_dir)
    task_path = cap_dir / "AGENT_TASK.md"

    roster_schema_json = json.dumps(RosterData.model_json_schema(), indent=2)
    bag_schema_json = json.dumps(EchoBagData.model_json_schema(), indent=2)

    lines: list[str] = [
        "# Agent Vision Extraction Task (`AGENT_TASK.md`)",
        "",
        "Use your built-in multimodal vision capabilities to inspect the screenshots listed below and write validated JSON outputs to:",
        "- `data/roster.json`",
        "- `data/echo_bag.json`",
        "",
        "After writing both files, run `python -m src.main --strategize` to compute `data/recommendations.json`.",
        "",
        "## Grounding Context",
        "- Read `context/strategy_profile.json` (or `context/strategy_profile.example.json`) for the player's known 5-star roster whitelist, weapons, and Union Level caps.",
        "- Read `context/game_knowledge.json` for canonical Sonata Set names and stat keys.",
        "",
        "## Resonator Identification & Folder Naming Convention",
        "Stage 1 captures into `char_01/`, `char_02/`, ... without loading OCR in VRAM. When running Stage 2:",
        "1. Read `01_overview.png` in each `char_XX/` folder to identify the character name and element.",
        "2. **Rover naming rule:** When `01_overview.png` displays the player's name (e.g. `Perriwinkle`), read the Element icon above it and map it to `Rover (Havoc)` / `Rover (Aero)` / `Rover (Spectro)` / `Rover (Electro)` in `data/roster.json`.",
        "3. **Folder renaming:** Rename `char_XX/` using `rename_resonator_folders()` (`src/parsers/agent_bridge.py`) to:",
        "   - `RoverHavoc`, `RoverAero`, `RoverSpectro`, `RoverElectro` for Rover forms",
        "   - PascalCase character name (e.g., `Cartethyia`, `LuukHerssen`, `Jianxin`, `Encore`) for other Resonators.",
        "",
        "## Mandatory Echo Disambiguation Rules",
        "1. **Physical Path Isolation:** Equipped Echoes live inside `captures/latest/resonators/<ResonatorFolder>/03_echo_slot_Y.png`. Slot (`1..5`) and owner come deterministically from the file path.",
        "2. **4-Zone Visual Segmentation (Right-Hand Detail Card):**",
        "   - Zone 1 (Header): Monster Name, `COST` (`4`, `3`, or `1`), Level (`0..25`), Sonata Set.",
        "   - Zone 2 (Main Stat Bar): Variable Main Stat (top row) and Fixed Main Stat (bottom row).",
        "   - Zone 3 (Substat Block): Up to 5 tuned substats below the divider.",
        "   - Zone 4 (Equipped Badge): Bottom-right `'Equipped by <Character>'` badge in Backpack view (`null` if unequipped).",
        "3. **Flat vs. Percentage Key Normalization:**",
        "   - If the value contains `%`: `ATK_PCT`, `HP_PCT`, `DEF_PCT`.",
        "   - If the value contains NO `%`: `ATK_FLAT`, `HP_FLAT`, `DEF_FLAT`.",
        "4. **Crit Value & ID:**",
        "   - `crit_value = (CRIT_RATE * 2) + CRIT_DMG`",
        "   - `echo_id`: 12-char SHA256 hex digest (or leave empty and let `strategist.py` / Pydantic compute it).",
        "",
        "## Discovered Screenshots",
        "",
        "### 1. Resonators (`captures/latest/resonators/`)",
    ]

    if resonator_files:
        for char_id, paths in resonator_files.items():
            lines.append(f"- **{char_id}**")
            for p in paths:
                rel = p.relative_to(root).as_posix() if p.is_relative_to(root) else p.as_posix()
                lines.append(f"  - `{rel}`")
    else:
        lines.append("- *(No resonator screenshots found yet in `captures/latest/resonators/`. Capture screenshots first or test using `data/roster.json`.)*")

    lines.extend([
        "",
        "### 2. Backpack Echoes (`captures/latest/backpack_echoes/`)",
    ])
    if bag_files:
        for p in bag_files:
            rel = p.relative_to(root).as_posix() if p.is_relative_to(root) else p.as_posix()
            lines.append(f"- `{rel}`")
    else:
        lines.append("- *(No backpack echo screenshots found yet in `captures/latest/backpack_echoes/`. Capture screenshots first or test using `data/echo_bag.json`.)*")

    lines.extend([
        "",
        "## Target Pydantic JSON Schemas",
        "",
        "### `data/roster.json` Schema",
        "```json",
        roster_schema_json,
        "```",
        "",
        "### `data/echo_bag.json` Schema",
        "```json",
        bag_schema_json,
        "```",
        "",
    ])

    task_path.write_text("\n".join(lines), encoding="utf-8")
    return task_path


def run_agent_bridge(captures_dir: Path | None = None, project_root: Path | None = None) -> dict[str, Any]:
    """Execute Route C (agent mode) and return metadata about the generated task."""
    task_path = generate_agent_task(captures_dir=captures_dir, project_root=project_root)
    return {
        "mode": "agent",
        "status": "task_generated",
        "agent_task_path": str(task_path),
    }
