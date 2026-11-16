# Antigravity Development Plan: `wuwa-buddy-assist`

This document details the **Step-by-Step Antigravity Development Plan** for **`wuwa-buddy-assist`**. For full architectural context, directory structures, hardware constraints, and data schemas, refer to [technical_architecture_proposal.md](file:///d:/AntiGravity/wuwa-buddy-assist/technical_architecture_proposal.md).

---

## Development Plan Overview

This development plan is structured into **5 sequential, self-contained phases**. You can feed each phase directly to **Antigravity** (or Claude Code) one at a time. Each phase has clear deliverables and a verification test before moving to the next.

---

### Phase 1: Project Scaffolding, `.env` Config & Visual Calibration Tool

**Goal:** Establish the repository structure, configuration loader, and a zero-click visual calibration script (`F8`) that captures a single 1080p/1440p frame and draws red bounding boxes + green click-target crosshairs onto `calibration_preview.png`.

* **Files to Generate:**
  * `.env` and `requirements.txt` (`mss`, `opencv-python`, `numpy`, `pydirectinput`, `keyboard`, `pydantic`, `python-dotenv`, `win11toast`).
  * `context/ui_anchors_16_9.json` (contains normalized `0.0–1.0` coordinates for Left Tab Icons, Right Roster Sidebar, Echo Slots 1–5, Backpack Grid origin/steps, and Stat Crop regions).
  * `src/capture/screen_grabber.py` (uses `mss` to capture `GAME_MONITOR`, validates `16:9` aspect ratio, and provides `crop_norm()` and `draw_calibration_overlay()`).

* **Prompt to Give Antigravity for Phase 1:**
  > *"Read `technical_architecture_proposal.md` and `antigravity_development_plan.md`. Implement Phase 1: Create the folder structure, `.env`, `context/ui_anchors_16_9.json`, and `src/capture/screen_grabber.py`. Add a CLI flag `--calibrate` (or hotkey `F8`) that grabs the current screen, draws labeled red bounding boxes and green click points from `ui_anchors_16_9.json`, and saves `captures/calibration_preview.png` so I can verify alignment on my 1440p/1080p monitor."*

* **Verification Gate:** Run `--calibrate` with *Wuthering Waves* open on the Resonator screen (`C`). Open `calibration_preview.png` and confirm the green dots sit cleanly on the Overview, Weapon, Echoes, and Forte tab icons.

---

### Phase 2: The Humanized Auto-Click Daemon & Windows Notifier

**Goal:** Build the automated in-game capture loops for both **Resonators (`F9`)** and **Backpack Echoes (`F10`)**, complete with an emergency kill-switch (`F12`), Windows Toast Notification, and process exit watcher.

* **Files to Generate:**
  * `src/capture/macro_controller.py`:
    * Uses `pydirectinput` (with Administrator privilege check on startup).
    * Adds randomized human jitter (`BASE_CLICK_DELAY_MS + random(0, JITTER_MS)` and `±PIXEL_JITTER`).
    * Implements `scan_roster_loop(roster_count)`: Loops through `N` characters on the right sidebar, clicking Overview -> Weapon -> Echo Slots 1..5 -> Forte Tree, saving organized PNGs into `captures/latest/resonators/char_XX/`.
    * Implements `scan_backpack_loop(max_echos)`: Iterates through the `6 × 4` Backpack grid (`GRID_START_X + col * STEP_X`, `GRID_START_Y + row * STEP_Y`), scrolls down every 4 rows, and saves `captures/latest/backpack_echoes/bag_echo_XXX.png`.
  * `src/capture/notifier.py`:
    * Fires a native Windows Toast Notification (`win11toast`) when the scan finishes: *"Capture Complete! You may now close Wuthering Waves to start processing."*
    * Polls `psutil` (if `WAIT_FOR_GAME_EXIT=true`) to detect when `Client-Win64-Shipping.exe` closes before launching Phase 3.

* **Prompt to Give Antigravity for Phase 2:**
  > *"Implement Phase 2 from `antigravity_development_plan.md`: Build `src/capture/macro_controller.py`, `src/capture/notifier.py`, and wire hotkeys `F9` (Roster Scan), `F10` (Backpack Scan), and `F12` (Instant Abort) into `src/main.py`. Ensure the script checks for Windows Admin privileges so `pydirectinput` works inside Wuthering Waves."*

---

### Phase 3: The Multi-Mode Parser Router (`offline` | `online` | `agent`)

**Goal:** Build the post-game processing pipeline that turns `captures/latest/` into validated `data/roster.json` and `data/echo_bag.json` using whichever mode is set in `.env`.

* **Files to Generate:**
  * `src/parsers/models.py`: Strict **Pydantic v2** schemas matching `roster.json`, `echo_bag.json`, and `recommendations.json`.
  * `src/parsers/agent_bridge.py` (**Route C — `APP_MODE=agent`**, Priority #1):
    * Scans `captures/latest/` and writes a structured `captures/latest/AGENT_TASK.md` file listing every captured image path, the Pydantic JSON schema, and instructions referencing `context/strategy_profile.json`.
    * Allows you to simply tell Antigravity / Claude Code / GHCP: *"Run `@captures/latest/AGENT_TASK.md`"* to populate `data/roster.json` and `data/echo_bag.json` using your IDE agent's built-in vision.
  * `src/parsers/offline_ocr.py` (**Route A — `APP_MODE=offline`**):
    * Uses `rapidocr-onnxruntime` + OpenCV binary thresholding to extract text from cropped zones on CPU/GPU after the game closes, plus `STOP_ON_PLUS_ZERO` detection for Backpack scans.
  * `src/parsers/online_vlm.py` (**Route B — `APP_MODE=online`**):
    * Batches character screenshots to the Gemini 2.5 Flash API with `response_schema=CharacterBuild`.

* **Prompt to Give Antigravity for Phase 3:**
  > *"Implement Phase 3 from `antigravity_development_plan.md`: Create the Pydantic models in `src/parsers/models.py`, the `.env` router in `src/parsers/router.py`, and implement `agent_bridge.py` (`APP_MODE=agent`), `offline_ocr.py` (`APP_MODE=offline`), and `online_vlm.py` (`APP_MODE=online`). Also populate `context/strategy_profile.json` and `context/game_knowledge.json`."*

---

### Phase 4: The "Buddy Assist" Strategist Engine

**Goal:** Build the deterministic math and rule engine (`src/engine/strategist.py`) that runs automatically after `roster.json` and `echo_bag.json` are generated.

* **What `strategist.py` Computes Automatically:**
  1. **Echo CV & Hash Tagging:** Computes `crit_value` and `echo_id` for every equipped and backpack Echo, flagging duplicates.
  2. **Mismatched Set & Threshold Alerts:**
     * Flags if **Havoc Rover** still has any *Windward Pilgrimage* pieces equipped or is below 115% Energy Regen.
     * Flags if **Jianxin** is below her **140% Energy Regen** target or missing 5-pc *Rejuvenating Glow*.
  3. **Backpack Upgrade Finder (Auto-Swap Recommender):**
     * Compares every unequipped Echo in `echo_bag.json` against the 5 equipped slots on your active team (**Cartethyia, Havoc Rover, Jianxin**).
     * If a Backpack Echo matches the target Sonata set (e.g., *Sun-sinking Eclipse* or *Rejuvenating Glow*), matches the slot Cost (`4`, `3`, or `1`), and has a higher **Crit Value** or required **Energy Regen %**, it writes a prioritized swap entry into `data/recommendations.json`.
  4. **Daily 240 Waveplate Planner:** Outputs whether today's Waveplates should go to Forgery Challenges (for Havoc Rover's Lv. 6 → Lv. 8 Forte roadmap) or Tacet Fields.

* **Prompt to Give Antigravity for Phase 4:**
  > *"Implement Phase 4 from `antigravity_development_plan.md`: Build `src/engine/strategist.py` to analyze `data/roster.json`, `data/echo_bag.json`, and `context/strategy_profile.json`, and output actionable Echo swap alerts, Crit Value rankings, and Forte upgrade steps into `data/recommendations.json`."*

---

### Phase 5: Local Interactive HTML Buddy Dashboard (`ui/index.html`)

**Goal:** Create a modern, dark-themed, zero-build-step HTML/JS interface (`ui/index.html`) that loads `data/roster.json`, `data/echo_bag.json`, and `data/recommendations.json`.

* **Dashboard Features:**
  * **Tab 1 — Active Team & Roster Cards:** Visual cards for **Cartethyia, Havoc Rover, Jianxin**, and your benched 5-stars, showing total stats, weapon ranks, Forte skill progress bars (highlighting the next node to unlock), and colour-coded Echo CV badges (`Gold` > 35 CV, `Purple` 25–35 CV, `Red` < 20 CV or wrong Sonata set).
  * **Tab 2 — Echo Bag Explorer & Swap Matrix:** Filterable table of all scanned Backpack Echoes by Sonata Set, Cost (`4/3/1`), Main Stat, and CV, with a green **"Upgrade Available for [Character] Slot [X]"** badge whenever a bag piece beats an equipped piece.
  * **Tab 3 — Buddy Strategy & Task Selector:** Interactive toggle between *"Daily 240 Waveplate Plan"*, *"Echo Bag Cleanup"*, and *"Endgame Team 2 Builder (ToA / Endstate Matrix)"*, plus a **"Copy Context for Chat"** button to paste your latest JSON summary into Antigravity or chat.

* **Prompt to Give Antigravity for Phase 5:**
  > *"Implement Phase 5 from `antigravity_development_plan.md`: Build `ui/index.html` (and a lightweight local static server command `python src/main.py --serve-ui`) that renders the Roster Cards, Echo Bag Explorer, and Buddy Strategy recommendations from the `/data/*.json` files."*

---

## How to Kick Off the Build in Antigravity Right Now

1. Ensure the workspace root has [technical_architecture_proposal.md](file:///d:/AntiGravity/wuwa-buddy-assist/technical_architecture_proposal.md) and [antigravity_development_plan.md](file:///d:/AntiGravity/wuwa-buddy-assist/antigravity_development_plan.md).
2. In the Antigravity chat panel, paste this kickoff command:
   > *"Read `technical_architecture_proposal.md` and `antigravity_development_plan.md`. Let's start with **Phase 1**. Generate the directory scaffolding, `.env`, `requirements.txt`, `context/ui_anchors_16_9.json`, `context/strategy_profile.json`, and the visual calibration script in `src/capture/screen_grabber.py` so we can test the 16:9 overlay."*
