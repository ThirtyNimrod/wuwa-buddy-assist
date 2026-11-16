"""Unit and integration tests for Phases 1, 3, 4, and 5."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from src.capture.macro_controller import AbortCaptureError, MacroController
from src.capture.screen_grabber import (
    crop_norm,
    draw_calibration_overlay,
    generate_synthetic_frame,
    run_calibration,
    run_multi_menu_calibration,
    validate_aspect_ratio,
)
from src.config import PROJECT_ROOT, load_config, load_json_file
from src.engine.strategist import run_strategist
from src.parsers.agent_bridge import (
    canonical_resonator_folder_name,
    generate_agent_task,
    rename_resonator_folders,
)
from src.parsers.models import (
    StatEntry,
    compute_crit_value,
    compute_echo_id,
    normalize_stat_key,
)
from src.parsers.offline_ocr import extract_echo_zones, is_plus_zero_echo, preprocess_for_ocr
from src.parsers.router import parse_captures


def test_normalize_stat_key_flat_vs_pct() -> None:
    assert normalize_stat_key("ATK", "18.0%") == "ATK_PCT"
    assert normalize_stat_key("ATK", "40") == "ATK_FLAT"
    assert normalize_stat_key("HP", "7.9%") == "HP_PCT"
    assert normalize_stat_key("HP", "430") == "HP_FLAT"
    assert normalize_stat_key("DEF", "10.1%") == "DEF_PCT"
    assert normalize_stat_key("DEF", "50") == "DEF_FLAT"
    assert normalize_stat_key("Crit. Rate", "8.7%") == "CRIT_RATE"
    assert normalize_stat_key("Crit. DMG", "15.0%") == "CRIT_DMG"
    assert normalize_stat_key("Energy Regen", "9.2%") == "ENERGY_REGEN"
    assert normalize_stat_key("Havoc DMG Bonus", "30.0%") == "HAVOC_DMG_PCT"


def test_crit_value_and_echo_id_deterministic() -> None:
    subs_a = [
        StatEntry(stat="CRIT_RATE", value="6.9%"),
        StatEntry(stat="CRIT_DMG", value="15.0%"),
        StatEntry(stat="ATK", value="8.6%"),
        StatEntry(stat="ATK", value="40"),
    ]
    subs_b = list(reversed(subs_a))

    cv = compute_crit_value(subs_a)
    assert cv == 28.8

    id_a = compute_echo_id("Dreamless", "Sun-sinking Eclipse", 4, 25, "CRIT_RATE", subs_a)
    id_b = compute_echo_id("Dreamless", "Sun-sinking Eclipse", 4, 25, "CRIT_RATE", subs_b)
    id_diff = compute_echo_id("Dreamless", "Sun-sinking Eclipse", 4, 20, "CRIT_RATE", subs_a)

    assert len(id_a) == 12
    assert id_a == id_b
    assert id_a != id_diff


def test_aspect_ratio_and_crop_norm() -> None:
    assert validate_aspect_ratio(1920, 1080, "16:9") is True
    assert validate_aspect_ratio(2560, 1440, "16:9") is True
    assert validate_aspect_ratio(2560, 1080, "16:9") is False

    frame = generate_synthetic_frame(1920, 1080)
    cropped = crop_norm(frame, {"x1": 0.5, "y1": 0.25, "x2": 0.75, "y2": 0.5})
    assert cropped.shape == (270, 480, 3)

    with pytest.raises(ValueError):
        crop_norm(frame, {"x1": 0.8, "y1": 0.2, "x2": 0.4, "y2": 0.6})


def test_draw_calibration_overlay_and_save(tmp_path: Path) -> None:
    anchors = load_json_file(PROJECT_ROOT / "context" / "ui_anchors_16_9.json")
    source = generate_synthetic_frame(1920, 1080)
    source_copy = source.copy()

    annotated = draw_calibration_overlay(source, anchors)
    assert annotated.shape == source.shape
    # Ensure input frame was not mutated in-place
    assert np.array_equal(source, source_copy)
    assert not np.array_equal(annotated, source)

    out_file = tmp_path / "calibration_preview.png"
    result_path = run_calibration(output_path=out_file, use_synthetic=True)
    assert result_path.exists()
    assert result_path.stat().st_size > 1000


def test_agent_bridge_generates_task_md(tmp_path: Path) -> None:
    cap_dir = tmp_path / "captures" / "latest"
    res_dir = cap_dir / "resonators" / "char_01"
    bag_dir = cap_dir / "backpack_echoes"
    res_dir.mkdir(parents=True)
    bag_dir.mkdir(parents=True)

    (res_dir / "01_overview.png").write_bytes(b"fake_png")
    (res_dir / "03_echo_slot_1.png").write_bytes(b"fake_png")
    (bag_dir / "bag_echo_001.png").write_bytes(b"fake_png")

    task_path = generate_agent_task(captures_dir=cap_dir, project_root=tmp_path)
    assert task_path.exists()
    text = task_path.read_text(encoding="utf-8")
    assert "01_overview.png" in text
    assert "03_echo_slot_1.png" in text
    assert "bag_echo_001.png" in text
    assert "context/strategy_profile.json" in text
    assert "ATK_PCT" in text


def test_offline_ocr_helpers_and_router_validation(tmp_path: Path) -> None:
    assert is_plus_zero_echo("Diamondclaw Cost 1 +0") is True
    assert is_plus_zero_echo("Dreamless Lv. 0") is True
    assert is_plus_zero_echo("Dreamless +25") is False

    frame = generate_synthetic_frame(1920, 1080)
    anchors = load_json_file(PROJECT_ROOT / "context" / "ui_anchors_16_9.json")
    binary = preprocess_for_ocr(frame[:100, :200])
    assert binary.ndim == 2

    def _mock_ocr(_img: np.ndarray) -> tuple[list[tuple[list[int], str, float]], float]:
        return [([0, 0, 10, 10], "Dreamless +25", 0.99)], 0.01

    zones = extract_echo_zones(frame, anchors, ocr_engine=_mock_ocr)
    assert len(zones) == 4
    assert zones["echo_zone1_header"] == ["Dreamless +25"]

    cfg = load_config(PROJECT_ROOT)
    with pytest.raises(ValueError):
        parse_captures(mode="unknown_mode", config=cfg, captures_dir=tmp_path)


def test_strategist_alerts_dedup_and_swaps(tmp_path: Path) -> None:
    # Copy seed data into tmp_path so test stays isolated from working data files
    roster_src = (PROJECT_ROOT / "data" / "roster.json").read_text(encoding="utf-8")
    bag_src = (PROJECT_ROOT / "data" / "echo_bag.json").read_text(encoding="utf-8")

    roster_path = tmp_path / "roster.json"
    bag_path = tmp_path / "echo_bag.json"
    out_path = tmp_path / "recommendations.json"

    roster_path.write_text(roster_src, encoding="utf-8")
    bag_path.write_text(bag_src, encoding="utf-8")

    recs = run_strategist(
        roster_path=roster_path,
        bag_path=bag_path,
        profile_path=PROJECT_ROOT / "context" / "strategy_profile.json",
        output_path=out_path,
        project_root=PROJECT_ROOT,
    )

    assert out_path.exists()
    # 1. Havoc Rover Windward Pilgrimage & ER alert
    rover_alerts = [a for a in recs.alerts if a.character == "Rover (Havoc)"]
    assert any(a.category == "mismatched_sonata_set" for a in rover_alerts)
    assert any(a.category == "energy_regen_deficit" for a in rover_alerts)

    # 2. Jianxin < 140% ER alert
    jianxin_alerts = [a for a in recs.alerts if a.character == "Jianxin"]
    assert any(a.category == "energy_regen_deficit" for a in jianxin_alerts)

    # 3. Duplicate echo suppression: bag_echo_005 matches Rover's Dreamless Slot 1
    updated_bag = json.loads(bag_path.read_text(encoding="utf-8"))
    bag_005 = next(e for e in updated_bag["echoes"] if e["source_file"] == "bag_echo_005.png")
    assert bag_005["equipped_by"] == "Rover (Havoc)"
    assert all(
        s.recommended_echo.source_file != "bag_echo_005.png"
        for s in recs.swap_recommendations
    )

    # 4. Priority sorting & expected upgrades
    scores = [s.priority_score for s in recs.swap_recommendations]
    assert scores == sorted(scores, reverse=True)
    assert recs.swap_recommendations[0].fixes_sonata_set is True
    assert recs.swap_recommendations[0].character == "Rover (Havoc)"
    assert recs.swap_recommendations[0].slot == 3
    assert "Forgery" in recs.waveplate_plan.primary_focus


def test_macro_controller_from_terminal_and_bag(tmp_path: Path) -> None:
    cfg = load_config(PROJECT_ROOT)
    anchors = load_json_file(PROJECT_ROOT / "context" / "ui_anchors_16_9.json")
    clicks: list[tuple[int, int]] = []
    keys: list[str] = []
    scrolls: list[int] = []
    frame = generate_synthetic_frame(1920, 1080)

    controller = MacroController(
        config=cfg,
        anchors=anchors,
        captures_dir=tmp_path / "captures" / "latest",
        grab_fn=lambda _mon: frame,
        click_fn=lambda x, y: clicks.append((x, y)),
        key_fn=lambda k: keys.append(k),
        scroll_fn=lambda c: scrolls.append(c),
        sleep_fn=lambda _s: None,
        focus_fn=lambda: True,
        rect_fn=lambda: {"hwnd": 1, "left": 100, "top": 50, "width": 1920, "height": 1080},
    )

    roster_res = controller.scan_roster_loop(roster_count=2, from_terminal=True)
    assert roster_res["characters_scanned"] == 2
    assert (tmp_path / "captures" / "latest" / "resonators" / "char_01" / "01_overview.png").exists()
    assert (tmp_path / "captures" / "latest" / "resonators" / "char_01" / "02_weapon.png").exists()
    assert (tmp_path / "captures" / "latest" / "resonators" / "char_01" / "03_echo_overview.png").exists()
    assert (tmp_path / "captures" / "latest" / "resonators" / "char_01" / "03_echo_slot_5.png").exists()
    assert (tmp_path / "captures" / "latest" / "resonators" / "char_02" / "08_forte.png").exists()
    # First click must land inside the 1920x1080 client area at Terminal: Resonators
    first_x, first_y = clicks[0]
    assert 100 <= first_x <= 2020
    assert 50 <= first_y <= 1130

    keys.clear()
    bag_res = controller.scan_backpack_loop(max_echos=26, navigate_from_game=True)
    assert bag_res["echoes_scanned"] == 26
    assert keys == ["esc", "esc", "b"]
    assert len(scrolls) == 1
    assert (tmp_path / "captures" / "latest" / "backpack_echoes" / "00_backpack_overview.png").exists()
    assert (tmp_path / "captures" / "latest" / "backpack_echoes" / "bag_echo_001.png").exists()
    assert (tmp_path / "captures" / "latest" / "backpack_echoes" / "bag_echo_026.png").exists()

    manifest = json.loads((tmp_path / "captures" / "latest" / "session_manifest.json").read_text(encoding="utf-8"))
    assert manifest["client_resolution"] == "1920x1080"
    assert manifest["roster_count_scanned"] == 2
    assert manifest["backpack_count_scanned"] == 26


def test_macro_controller_abort_f12(tmp_path: Path) -> None:
    cfg = load_config(PROJECT_ROOT)
    anchors = load_json_file(PROJECT_ROOT / "context" / "ui_anchors_16_9.json")
    frame = generate_synthetic_frame(1920, 1080)

    controller: MacroController

    def _click_and_abort(_x: int, _y: int) -> None:
        controller.request_abort()

    controller = MacroController(
        config=cfg,
        anchors=anchors,
        captures_dir=tmp_path / "captures" / "latest",
        grab_fn=lambda _mon: frame,
        click_fn=_click_and_abort,
        key_fn=lambda _k: None,
        scroll_fn=lambda _c: None,
        sleep_fn=lambda _s: None,
        focus_fn=lambda: True,
        rect_fn=lambda: {"hwnd": 1, "left": 0, "top": 0, "width": 1920, "height": 1080},
    )

    with pytest.raises(AbortCaptureError):
        controller.scan_roster_loop(roster_count=2, from_terminal=True)


def test_calibrate_on_uploaded_image(tmp_path: Path) -> None:
    src_img = tmp_path / "terminal_16_9.png"
    cv2.imwrite(str(src_img), generate_synthetic_frame(1024, 576))
    out_img = tmp_path / "calibration_preview.png"

    saved = run_calibration(output_path=out_img, source_image_path=src_img)
    assert saved.exists()
    loaded = cv2.imread(str(saved))
    assert loaded is not None
    assert loaded.shape == (576, 1024, 3)


def test_1600x900_windowed_test_run_scope(tmp_path: Path) -> None:
    from src.main import build_parser

    assert validate_aspect_ratio(1600, 900, "16:9") is True
    args = build_parser().parse_args(["--scan-from-terminal", "--include-bag", "--test-run"])
    assert args.scan_from_terminal is True
    assert args.include_bag is True
    assert args.test_run is True

    cfg = load_config(PROJECT_ROOT)
    anchors = load_json_file(PROJECT_ROOT / "context" / "ui_anchors_16_9.json")
    clicks: list[tuple[int, int]] = []
    frame = generate_synthetic_frame()
    assert frame.shape == (900, 1600, 3)

    controller = MacroController(
        config=cfg,
        anchors=anchors,
        captures_dir=tmp_path / "captures" / "latest",
        grab_fn=lambda _mon: frame,
        click_fn=lambda x, y: clicks.append((x, y)),
        key_fn=lambda _k: None,
        scroll_fn=lambda _c: None,
        sleep_fn=lambda _s: None,
        focus_fn=lambda: True,
        rect_fn=lambda: {"hwnd": 1, "left": 160, "top": 90, "width": 1600, "height": 900},
    )

    res = controller.scan_roster_loop(roster_count=1, from_terminal=True)
    bag = controller.scan_backpack_loop(max_echos=6, navigate_from_game=True)
    assert res["characters_scanned"] == 1
    assert bag["echoes_scanned"] == 6
    assert all(150 <= x <= 1770 and 80 <= y <= 1000 for x, y in clicks)

    manifest = json.loads(
        (tmp_path / "captures" / "latest" / "session_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["client_resolution"] == "1600x900"
    assert manifest["roster_count_scanned"] == 1
    assert manifest["backpack_count_scanned"] == 6


def test_multi_menu_calibration_outputs(tmp_path: Path) -> None:
    out_dir = tmp_path / "calibration"
    outputs = run_multi_menu_calibration(output_dir=out_dir)
    assert set(outputs.keys()) == {
        "terminal",
        "overview",
        "weapon",
        "forte",
        "echo_wheel",
        "echo_customization",
        "backpack",
    }
    for path in outputs.values():
        assert path.exists()
        assert path.stat().st_size > 1000


def test_roster_sidebar_scroll_beyond_six(tmp_path: Path) -> None:
    cfg = load_config(PROJECT_ROOT)
    anchors = load_json_file(PROJECT_ROOT / "context" / "ui_anchors_16_9.json")
    scrolls: list[int] = []
    hovers: list[tuple[int, int]] = []
    frame = generate_synthetic_frame()

    controller = MacroController(
        config=cfg,
        anchors=anchors,
        captures_dir=tmp_path / "captures" / "latest",
        grab_fn=lambda _mon: frame,
        click_fn=lambda _x, _y: None,
        hover_fn=lambda x, y: hovers.append((x, y)),
        key_fn=lambda _k: None,
        scroll_fn=lambda c: scrolls.append(c),
        sleep_fn=lambda _s: None,
        focus_fn=lambda: True,
        rect_fn=lambda: {"hwnd": 1, "left": 0, "top": 0, "width": 1600, "height": 900},
    )

    res = controller.scan_roster_loop(roster_count=7, from_terminal=False)
    assert res["characters_scanned"] == 7
    assert scrolls == [-1]
    assert len(hovers) == 1
    assert (tmp_path / "captures" / "latest" / "resonators" / "char_07" / "01_overview.png").exists()


def test_backpack_pagination_skips_top_overlap_row(tmp_path: Path) -> None:
    cfg = load_config(PROJECT_ROOT)
    anchors = load_json_file(PROJECT_ROOT / "context" / "ui_anchors_16_9.json")
    clicks: list[tuple[int, int]] = []
    hovers: list[tuple[int, int]] = []
    scrolls: list[int] = []
    frame = generate_synthetic_frame()

    controller = MacroController(
        config=cfg,
        anchors=anchors,
        captures_dir=tmp_path / "captures" / "latest",
        grab_fn=lambda _mon: frame,
        click_fn=lambda x, y: clicks.append((x, y)),
        hover_fn=lambda x, y: hovers.append((x, y)),
        key_fn=lambda _k: None,
        scroll_fn=lambda c: scrolls.append(c),
        sleep_fn=lambda _s: None,
        focus_fn=lambda: True,
        rect_fn=lambda: {"hwnd": 1, "left": 0, "top": 0, "width": 1600, "height": 900},
    )

    bag_res = controller.scan_backpack_loop(max_echos=42, navigate_from_game=False)
    assert bag_res["echoes_scanned"] == 42
    assert scrolls == [-5]
    assert len(hovers) == 1

    # Page 0 scans rows 0..3 (24 echoes); Page 1 scans rows 1..3 (18 echoes) -> total 42 clicks
    bag_cfg = anchors["backpack_grid"]
    row0_y = int(round(bag_cfg["grid_start_y"] * 900))
    row1_y = int(round((bag_cfg["grid_start_y"] + bag_cfg["step_y"]) * 900))
    jitter = cfg.pixel_jitter

    assert len(clicks) == 42
    # Page 0 starts at row 0, Page 1 (index 24) starts at row 1 (not row 0)
    assert abs(clicks[0][1] - row0_y) <= jitter
    assert abs(clicks[24][1] - row1_y) <= jitter


def test_canonical_resonator_folder_name_and_rename(tmp_path: Path) -> None:
    assert canonical_resonator_folder_name("Rover (Havoc)") == "RoverHavoc"
    assert canonical_resonator_folder_name("Perriwinkle", element="Aero") == "RoverAero"
    assert canonical_resonator_folder_name("Rover: Spectro") == "RoverSpectro"
    assert canonical_resonator_folder_name("Rover", element="electro") == "RoverElectro"
    assert canonical_resonator_folder_name("Cartethyia") == "Cartethyia"
    assert canonical_resonator_folder_name("Luuk Herssen") == "LuukHerssen"
    assert canonical_resonator_folder_name("Yangyang: Xuanling") == "YangyangXuanling"

    cap_dir = tmp_path / "captures" / "latest"
    res_dir = cap_dir / "resonators"
    (res_dir / "char_01").mkdir(parents=True)
    (res_dir / "char_02").mkdir(parents=True)
    (res_dir / "char_01" / "01_overview.png").write_bytes(b"png1")
    (res_dir / "char_02" / "01_overview.png").write_bytes(b"png2")

    manifest_path = cap_dir / "session_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "resonators": {
                    "char_01": [str(res_dir / "char_01" / "01_overview.png")],
                    "char_02": [str(res_dir / "char_02" / "01_overview.png")],
                }
            }
        ),
        encoding="utf-8",
    )

    renamed = rename_resonator_folders(
        cap_dir,
        {
            "char_01": ("Perriwinkle", "Aero"),
            "char_02": ("Luuk Herssen", "Spectro"),
        },
    )
    assert renamed == {"char_01": "RoverAero", "char_02": "LuukHerssen"}
    assert (res_dir / "RoverAero" / "01_overview.png").exists()
    assert (res_dir / "LuukHerssen" / "01_overview.png").exists()
    assert not (res_dir / "char_01").exists()

    updated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(updated_manifest["resonators"].keys()) == {"RoverAero", "LuukHerssen"}
    assert "RoverAero" in updated_manifest["resonators"]["RoverAero"][0]




