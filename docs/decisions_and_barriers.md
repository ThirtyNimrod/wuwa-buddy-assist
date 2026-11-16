# Engineering Decisions & Technical Barriers Log

This document records the architectural decisions, calibration discoveries, and Windows/UI barriers encountered while building **`wuwa-buddy-assist`**.

---

## 1. Architectural & Workflow Decisions

### 1.1 Staged Build Order (Phases 1, 3, 4 & 5 Before Phase 2 Auto-Click)
* **Decision:** Implement configuration, visual calibration (`--calibrate`), Pydantic schemas, multi-mode parser router (`agent`, `offline`, `online`), the Strategist Engine, and the HTML dashboard (`ui/index.html`) before enabling in-game `pydirectinput` mouse automation.
* **Why:** Prevents blind automated clicking inside an active game client until normalized coordinates are visually verified against real screenshots.

### 1.2 Windowed `1600×900` (16:9) Standard + Client-Area Isolation
* **Decision:** Standardize on **`1600×900` Windowed Mode** instead of `1920×1080` windowed, paired with Win32 `GetClientRect` + `ClientToScreen` (`get_game_window_rect()` in `src/capture/screen_grabber.py`).
* **Why:** A `1920×1080` window on a 1080p/1440p monitor collides with the Windows taskbar and window title bar, shifting normalized `0.0–1.0` coordinates. `1600×900` preserves exact `16:9` aspect ratio cleanly inside the screen, while `GetClientRect` + `ClientToScreen` targets only the inner game canvas.

### 1.3 Starting Automation from the Terminal (`ESC`) Pause Menu
* **Decision:** Support launching directly from the **Terminal (`ESC`) menu** via `--scan-from-terminal`, clicking `terminal_resonators` (`0.496, 0.455`), and adding `--test-run` / `--roster-count` overrides (`run_test_capture_admin.bat`).
* **Why:** Gives the player a consistent, predictable starting screen and enables fast 1-character or 3-character test runs before executing full 9-character + 50-Echo sweeps.

### 1.4 Menu-Scoped Automated Calibration (`--calibrate-menus`)
* **Decision:** Tag every entry in `context/ui_anchors_16_9.json` with `"menus": [...]` and implement `--calibrate-menus` to render isolated per-menu previews into `captures/calibration/`:
  * `01_terminal.png` (`terminal`)
  * `02_overview.png` (`overview`)
  * `03_weapon.png` (`weapon`)
  * `04_forte.png` (`forte`)
  * `05_echo_wheel.png` (`echo_wheel`)
  * `06_echo_customization.png` (`echo_customization`)
  * `07_backpack.png` (`backpack`)
* **Why:** Drawing every menu's crop boxes and crosshairs onto a single image created severe label overlap and hid alignment errors. Per-menu overlays verify every screen cleanly.

### 1.5 Two-Stage Echo Capture Flow
* **Decision:** Capture `Overview -> Weapon -> Forte -> Sequences -> Echo Wheel Overview -> Echo Customization (Slots 1..5) -> Close (X)` per Resonator in `MacroController.scan_roster_loop()`.
* **Why:** Clicking `tab_forte` before entering the Echo Customization sub-screen ensures Echo detail menus can never obscure the left sidebar tabs, and clicking `echo_detail_close` (`0.941, 0.058`) cleanly restores the Resonator screen with the right-hand roster sidebar (`01..06`).

### 1.6 Post-Capture Resonator Folder Naming (`RoverHavoc`, `RoverAero`, etc.)
* **Decision:** Keep Stage 1 (in-game burst capture) zero-VRAM by writing into positional `char_01/`, `char_02/` folders, then resolve and rename folders during Stage 2 (`AGENT_TASK.md` / Vision Parser) using `canonical_resonator_folder_name()` and `rename_resonator_folders()` in `src/parsers/agent_bridge.py`:
  * **Rover forms:** Identified by player name (`Perriwinkle`) + Element icon in `01_overview.png`, mapped to `RoverHavoc`, `RoverAero`, `RoverSpectro`, `RoverElectro`.
  * **Other Resonators:** Mapped to PascalCase folder names (`Cartethyia`, `LuukHerssen`, `Jianxin`, `Encore`).
* **Why:** In *Wuthering Waves*, Stage 1 cannot read the character's name without loading an OCR/vision model in VRAM (violating the 8GB VRAM constraint) or reading game memory (violating the zero anti-cheat constraint). Identifying the name from `01_overview.png` during Stage 2 keeps Stage 1 lightweight and safe while giving folders human-readable names synchronized with `data/roster.json` and `session_manifest.json`.

### 1.7 Privacy & `.gitignore` Policy
* **Decision:** Git-ignore `.env`, `.env.*` (except `.env.example`), `context/strategy_profile.json` (keep `context/strategy_profile.example.json`), `data/*.json` (keep `data/.gitkeep`), `docs/chat.md`, `captures/calibration/`, `captures/calibration_preview.png`, and `captures/latest/*` (except `.gitkeep` files).
* **Why:** Prevents accidental commits of player UID, account roster snapshots, screenshots, or API keys.

### 1.8 9-Resonator Sidebar Scroll & 3-Row Backpack Pagination
* **Decision:** Support full `ROSTER_COUNT=9` roster sweeps by scrolling the right sidebar (`-1` discrete wheel notch per Resonator past Slot 6, clicking `roster_slot_7..9` at `y = 0.825`), and paginate the `6×4` Backpack Echo grid using `-5` discrete wheel notches (scanning Rows `0..3` on Page 0 and Rows `1..3` on subsequent pages).
* **Why:** Keeping scroll distances aligned to exact UI row multiples avoids repeating already-captured Echoes or missing the bottom character slot on `1600×900` screens.

---

## 2. Technical Barriers & How They Were Solved

### Barrier 1 — Windows UIPI Elevation & Sandboxed Agent Shell (`IsAdmin: False` / `BitBlt` Failure)
* **Symptom:** *Wuthering Waves* (`Client-Win64-Shipping.exe`) runs elevated as Administrator. Running `mss` (`BitBlt`) or `pydirectinput` (`SendInput`) from Antigravity's non-elevated, isolated tool shell failed with `ScreenShotError: BitBlt` and blocked synthetic clicks due to Windows UIPI.
* **Resolution:**
  1. Enforced explicit Windows Administrator checks (`is_admin()`) in `MacroController`.
  2. Created self-elevating UAC batch launchers (`run_test_capture_admin.bat`, `run_capture_admin.bat`) using `Start-Process -Verb RunAs`.
  3. Added `--calibrate --image <path>` and `--calibrate-menus` so calibration overlays can be inspected and refined offline inside the IDE from saved screenshots.

### Barrier 2 — `pydirectinput` Lacks a `.scroll()` Method
* **Symptom:** `pydirectinput` exposes `moveTo`, `click`, `mouseDown`, `mouseUp`, and `press`, but no `scroll()` function for scrolling the `6×4` Backpack Echo grid.
* **Resolution:** Implemented `_default_scroll()` in `src/capture/macro_controller.py` using Win32 `ctypes.windll.user32.mouse_event(0x0800, 0, 0, delta, 0)` (`MOUSEEVENTF_WHEEL`).

### Barrier 3 — 3D Camera Transition Delays & Unreal Slate Hover Detection (Test Run #1)
* **Symptom:** Clicking `Resonators` on the Terminal pause menu triggers a ~3-second 3D scene/camera transition. The initial `0.9s` wait caused `roster_slot_1` (`01`) to click mid-load and be ignored (leaving Slot 3 `Luuk Herssen` active). Similarly, `0.7s` after pressing `ESC -> B` captured a completely black fade screen, and instant clicks intermittently missed Unreal Slate hover triggers.
* **Resolution:**
  1. Raised `BASE_CLICK_DELAY_MS=750` and `JITTER_MS=150`.
  2. Added `1.0s` post-focus settle + `~3.6s` wait after clicking `terminal_resonators`, `~2.2s` per character switch, `~1.9s` per tab, and `1.8s` / `1.6s` waits for `ESC -> B` Backpack transitions.
  3. Updated `_default_click()` to `moveTo` -> `100ms` hover pause -> `mouseDown` -> `60ms` hold -> `mouseUp`.

### Barrier 4 — Pre-Calibration Placeholder Coordinate Offsets (Test Run #1)
* **Symptom:** Initial `16:9` coordinate guesses put `tab_echoes` at `y=0.365` (landing in blank space between Weapon and Echoes) and `tab_forte` at `y=0.445` (clicking the Echoes icon instead of Forte), while `resonator_header`/`weapon_detail_card` crop boxes pointed at the right side instead of the left panel.
* **Resolution:** Measured exact pixel centroids directly from real `1600×900` captures (`tab_overview..tab_sequences` at `x=0.039, y=0.177..0.676`; `roster_slot_1..6` at `x=0.945, y=0.200..0.802`; left-side stat/weapon crop zones `x1=0.095..0.305`) and verified them visually via `captures/calibration/`.

### Barrier 5 — Echo Wheel vs. Echo Customization Menu Split (Test Run #2)
* **Symptom:** Clicking `echo_wheel_slot_1` (`0.770, 0.262`) on the Resonator Echo Wheel does not select it in place—it transitions into a separate **Echo Customization Menu** where Slot 1 is already displayed on the right (`x=0.775..0.975`) and Slots 1–5 move to the **far-left vertical column** (`x=0.055, y=0.232..0.689`). Subsequent clicks on the right arc (`echo_wheel_slot_2..5`) hit Echo Skill description text instead of switching Echoes.
* **Resolution:** Split Echo coordinates into two distinct menu definitions (`"echo_wheel"` vs. `"echo_customization"`) in `context/ui_anchors_16_9.json` and updated `scan_roster_loop()` to enter Echo Customization via `echo_wheel_slot_1`, iterate left-column `echo_slot_2..5`, and close back via `echo_detail_close` (`0.941, 0.058`). Verified cleanly in Test Run #3.

### Barrier 6 — Resonators-to-Backpack Navigation (`ESC -> ESC -> B`) & `6×4` Grid Stride Calibration (Test Run #4)
* **Symptom:** Pressing `ESC` once from the Resonators menu returns to the Terminal Pause Menu (where `B` does not open the Backpack), and initial Backpack grid coordinates (`grid_start_x=0.145, step_x=0.082`) were too narrow, double-clicking Column 3 and missing Column 6 entirely.
* **Resolution:** Updated `scan_backpack_loop()` to send `ESC` (`2.4s`) -> `ESC` (`2.2s`) to exit to Overworld before pressing `B` (`2.2s`), captured `00_backpack_overview.png`, aligned `backpack_tab_echoes` to `(0.039, 0.300)`, and calibrated `backpack_grid` in `context/ui_anchors_16_9.json` to `grid_start_x=0.129, step_x=0.0925, grid_start_y=0.214, step_y=0.200` (verified across all 6 columns in `07_backpack.png` and `bag_echo_001..006.png`).

### Barrier 7 — Unreal Engine `WM_MOUSEWHEEL` Single-Event Clamping & Backpack 3-Row Scroll Calibration (Full Capture #1)
* **Symptom:** During the first full `run_capture_admin.bat` capture, `scan_backpack_loop()` re-scanned Rows 1–3 (`bag_echo_025..048`) after the first page scroll instead of advancing to new Echoes.
* **Root Cause & Measurement:**
  1. `_default_scroll(clicks)` previously multiplied `clicks * 120` into a **single** `mouse_event(0x0800, ...)` call. Unreal Engine's `SScrollBox` clamps any single `WM_MOUSEWHEEL` message to **1 wheel notch**, ignoring the multiplier.
  2. OpenCV template matching across `bag_echo_024.png`, `bag_echo_025.png`, and `bag_echo_049.png` proved that **1 discrete wheel notch shifts the `1600×900` Backpack Echo grid by `109.5 px` (`~0.61` of a `180.0 px` row)**, leaving Rows 1–3 still visible after a single clamped call.
  3. On the Right Roster Sidebar, `roster_slot_7..9` scrolled in cleanly per 1 wheel notch, centered vertically at `y = 0.825` rather than `0.802`.
* **Resolution:**
  1. Updated `_default_scroll(clicks)` in `src/capture/macro_controller.py` to loop `abs(clicks)` times sending `±120` per `mouse_event` with a `60ms` delay between notches.
  2. Calibrated Backpack scrolling to **`-5` discrete wheel notches (`5 × 109.5 px = 547.5 px` ≈ 3 rows = `540.0 px`, only `+7.5 px` drift)** per scroll and updated `scan_backpack_loop()` to scan Rows `0..3` (24 Echoes) on Page 0, then Rows `1..3` (18 newly scrolled-in Echoes) on each subsequent page after hovering grid center and waiting `+600ms`.
  3. Updated `scan_roster_loop()` to send `-1` notch per character beyond Slot 6 and shifted `roster_slot_7..9` in `context/ui_anchors_16_9.json` to `y = 0.825`.
