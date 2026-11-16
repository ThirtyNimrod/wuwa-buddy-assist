# How to Run `wuwa-buddy-assist`

A practical step-by-step runbook for calibrating, capturing your live *Wuthering Waves* account, parsing screenshots into structured JSON, and viewing recommendations in the local dashboard.

---

## 1. Pre-Flight Checklist

1. **Game Display Settings:** Set *Wuthering Waves* to **`1600×900` Windowed Mode**.
   * `get_game_window_rect()` (`src/capture/screen_grabber.py`) automatically detects the inner `1600×900` client canvas (ignoring title bar and window borders).
2. **Environment Configuration (`.env`):**
   * Copy `.env.example` to `.env` if you haven't already (`Copy-Item .env.example .env`).
   * Key defaults:
     * `APP_MODE=agent` (generates `captures/latest/AGENT_TASK.md` for AI vision parsing)
     * `ROSTER_COUNT=9`, `MAX_BAG_ECHOS=50`
     * `BASE_CLICK_DELAY_MS=750`, `JITTER_MS=150`, `PIXEL_JITTER=3`
     * `SCAN_SEQUENCES=false` (set to `true` if you want Resonance Chain `S0–S6` screens captured too)
     * `WAIT_FOR_GAME_EXIT=true` (for full runs; skipped automatically by `--test-run`)
3. **Administrator Privileges (Required on Windows):**
   * Because *Wuthering Waves* (`Client-Win64-Shipping.exe`) runs elevated, Windows UIPI blocks `pydirectinput` clicks from non-elevated shells. Always use the provided `*_admin.bat` launchers or an **Administrator PowerShell**.

---

## 2. Step 1 — Run the Expanded Test & Backpack Calibration

Before running a full 9-character + 50-Echo capture, run the expanded end-to-end test once to verify the **Resonators → Terminal → Overworld → Backpack (`B`)** transition and Backpack Echo grid coordinates:

1. Leave *Wuthering Waves* (`1600×900` windowed) open on the **Terminal (`ESC`) Pause Menu**.
2. Double-click **`run_test_capture_admin.bat`** and accept the UAC Admin prompt (or run in Administrator PowerShell):
   ```powershell
   python -m src.main --scan-from-terminal --roster-count 1 --include-bag --max-bag-echos 6 --test-run
   python -m src.main --calibrate-menus
   ```
3. Press **`F12`** at any time if you need to abort immediately.
4. Inspect the generated **`captures/calibration/07_backpack.png`** (plus `01_terminal.png`–`06_echo_customization.png`) and **`captures/latest/backpack_echoes/`** to confirm:
   * `00_backpack_overview.png` shows the Backpack screen (not a black fade screen).
   * `bag_echo_001.png`–`bag_echo_006.png` show the Echoes tab with each grid card selected and its right-hand stat card visible.
   * The cyan `B0,0`–`B3,5` grid dots in `captures/calibration/07_backpack.png` sit cleanly inside the Backpack Echo tiles.

---

## 3. Step 2 — Run a Complete Account Capture

Once `07_backpack.png` calibration is verified:

1. Open *Wuthering Waves* (`1600×900` windowed) to the **Terminal (`ESC`) Pause Menu**.
2. Double-click **`run_capture_admin.bat`** (runs `--scan-from-terminal --include-bag` using `ROSTER_COUNT` and `MAX_BAG_ECHOS` from `.env`), **or** customize counts from an Administrator PowerShell:
   ```powershell
   python -m src.main --scan-from-terminal --roster-count 9 --include-bag --max-bag-echos 50
   ```
   *(If you are already on the Resonators (`C`) or Backpack (`B`) screen, you can also run `python -m src.main --scan-roster` or `python -m src.main --scan-bag`, or start the background hotkey listener with `python -m src.main --listen-hotkeys`.)*
3. When the Windows Toast says *"Capture Complete! You may now close Wuthering Waves to start processing."*, close the game.

---

## 4. Step 3 — Parse Captures, Rename Folders & Run Strategist

### Option A: `APP_MODE=agent` (Recommended)
1. Ensure `captures/latest/AGENT_TASK.md` is up to date (generated automatically after capture, or manually via `python -m src.main --parse --mode agent`).
2. In your AI IDE chat (Antigravity / Claude Code / GHCP), say:
   > `Run @captures/latest/AGENT_TASK.md`
3. The agent will:
   * Read `01_overview.png`, `02_weapon.png`, `08_forte.png`, and `03_echo_slot_1..5.png` for each character plus `backpack_echoes/`.
   * Rename `char_XX/` folders using `rename_resonator_folders()` (`RoverHavoc`, `RoverAero`, `RoverSpectro`, `RoverElectro`, `Cartethyia`, `LuukHerssen`, etc.).
   * Write validated `data/roster.json` and `data/echo_bag.json`.
4. Run the deterministic Strategist Engine:
   ```powershell
   python -m src.main --strategize
   ```
   This computes Crit Values (`CV`), deterministic 12-char `echo_id` hashes, duplicate suppression, swap upgrades, Forte priorities, Waveplate allocation, and writes `data/recommendations.json`.

### Option B: `APP_MODE=offline` or `APP_MODE=online`
* **Offline OCR:** Install `rapidocr-onnxruntime` and run `python -m src.main --parse --mode offline`.
* **Online Gemini VLM:** Install `google-genai`, set `GEMINI_API_KEY` in `.env.local` or your environment, and run `python -m src.main --parse --mode online`.

---

## 5. Step 4 — Launch the Interactive Buddy Dashboard

Start the local static HTTP server:
```powershell
python -m src.main --serve-ui --port 8080
```
Open **http://127.0.0.1:8080/ui/index.html** in your browser to inspect:
* **Tab 1 — Active Team & Roster Cards:** Stats, weapons, ER threshold pills, Forte bars, and color-coded Echo CV badges.
* **Tab 2 — Echo Bag Explorer & Swap Matrix:** Filterable Backpack Echo table with green upgrade badges.
* **Tab 3 — Buddy Strategy & Task Selector:** Daily 240 Waveplate plan, Echo Bag Cleanup, Endgame Team 2 Builder, and **"Copy Context for Chat"**.

---

## 6. Hotkeys & Emergency Controls

| Key | Action | Notes |
| :--- | :--- | :--- |
| **`F8`** | Calibrate (`--calibrate`) | Captures game window and saves `captures/calibration_preview.png` |
| **`F9`** | Roster Scan (`--scan-roster`) | Scans from the Resonators (`C`) screen when `--listen-hotkeys` is active |
| **`F10`** | Backpack Scan (`--scan-bag`) | Scans from the Backpack (`B`) screen when `--listen-hotkeys` is active |
| **`F12`** | **Instant Abort** | Immediately raises `AbortCaptureError` and halts any running scan |
