# `wuwa-buddy-assist`

A non-intrusive, account-aware desktop companion, capture pipeline, and theorycrafting strategist for *Wuthering Waves*.

---

## Core Design Principles

1. **Zero Anti-Cheat Risk:** Never reads process memory, injects DLLs, or intercepts network traffic. Captures screens strictly through OS Desktop Duplication (`mss`) and automates navigation using simulated hardware scan-codes (`pydirectinput`) with randomized delay and pixel jitter.
2. **8GB VRAM Two-Stage Pipeline:**
   * **Stage 1 (In-Game Capture):** Lightweight capture daemon snaps PNG screenshots into `captures/latest/` without loading OCR or VLM models in VRAM, then fires a native Windows Toast notification.
   * **Stage 2 (Post-Game Processing & Strategy):** Parses captures via `APP_MODE=agent` (IDE multimodal vision via `AGENT_TASK.md`), `offline` (OpenCV + RapidOCR), or `online` (Gemini VLM), runs deterministic Echo Crit Value & upgrade analysis (`src/engine/strategist.py`), and powers a local HTML dashboard (`ui/index.html`).

---

## Recommended Setup: `1600×900` Windowed Mode

Running *Wuthering Waves* in **`1600×900` (16:9) Windowed Mode** prevents Windows taskbar or display-scaling clipping on 1080p/1440p screens while keeping the entire game canvas inside a clean `16:9` coordinate frame.

`src/capture/screen_grabber.py` uses Win32 `GetClientRect` and `ClientToScreen` (`get_game_window_rect()`) to detect the inner `1600×900` game client area automatically—excluding the window title bar and borders—so all normalized `0.0–1.0` coordinates in `context/ui_anchors_16_9.json` map accurately onto the game window.

---

## Installation & Configuration

1. **Install Python dependencies:**
   ```powershell
   python -m pip install -r requirements.txt
   ```

2. **Create your local `.env` and account profile from the templates:**
   ```powershell
   Copy-Item .env.example .env
   Copy-Item context/strategy_profile.example.json context/strategy_profile.json
   ```
   Edit `.env` to adjust `APP_MODE` (`agent`, `offline`, `online`), `ROSTER_COUNT`, `MAX_BAG_ECHOS`, and hotkeys (`F8` calibrate, `F9` roster, `F10` bag, `F12` abort).
   *(If using `APP_MODE=online`, set `GEMINI_API_KEY` in your shell environment or `.env.local`—never commit secrets.)*

---

## Quick Test Run (`1600×900` from the Terminal Menu)

Before running a full 9-character / 50-Echo capture, run a fast `--test-run` (scans **1 Resonator** + **6 Backpack Echoes** and skips waiting for game exit):

1. Set *Wuthering Waves* to **`1600×900` Windowed** and open the **Terminal (`ESC`) menu**.
2. Double-click **`run_test_capture_admin.bat`** (accept the Windows UAC Administrator prompt—required by Windows UIPI so `pydirectinput` reaches the elevated game window), **or** run from an **Administrator PowerShell**:
   ```powershell
   python -m src.main --scan-from-terminal --include-bag --test-run
   ```
3. Press **`F12`** at any time to abort immediately (`AbortCaptureError`).
4. Verify the captured PNGs in `captures/latest/resonators/char_01/`, `captures/latest/backpack_echoes/`, `captures/latest/session_manifest.json`, and `captures/latest/AGENT_TASK.md`.

---

## Full Workflow Commands

| Task | Command | Notes |
| :--- | :--- | :--- |
| **Visual Calibration (Live Window)** | `python -m src.main --calibrate` | Captures game window and writes `captures/calibration_preview.png` |
| **Visual Calibration (Image / Headless)** | `python -m src.main --calibrate --synthetic` | Uses `1600×900` canvas (or `--image path/to/shot.png`) |
| **Full Capture (from Terminal Menu)** | `python -m src.main --scan-from-terminal --include-bag` | Or double-click `run_capture_admin.bat` (Admin required) |
| **Direct Screen Capture** | `python -m src.main --scan-roster` / `--scan-bag` | Start already on Resonators (`C`) or Backpack (`B`) screen |
| **Global Hotkey Listener** | `python -m src.main --listen-hotkeys` | `F8` calibrate, `F9` roster, `F10` bag, `F12` abort |
| **Parse Captures** | `python -m src.main --parse --mode agent` | Generates `captures/latest/AGENT_TASK.md` (or runs `offline`/`online`) |
| **Run Strategist Engine** | `python -m src.main --strategize` | Computes Echo CV, `echo_id` hashes, swaps & `data/recommendations.json` |
| **Serve Local Dashboard** | `python -m src.main --serve-ui --port 8080` | Open `http://127.0.0.1:8080/ui/index.html` |
| **Run Test Suite** | `python -m pytest -v` | Runs unit and integration tests |

---

## Repository Structure

```text
wuwa-buddy-assist/
├── .env.example                      # Configuration template (.env is gitignored)
├── context/
│   ├── game_knowledge.json           # Sonata sets, Echo cost & CV rules
│   ├── strategy_profile.example.json # Template player profile (strategy_profile.json is gitignored)
│   └── ui_anchors_16_9.json          # Normalized 16:9 click & crop coordinates
├── src/
│   ├── main.py                       # CLI & hotkey entrypoint
│   ├── config.py                     # Immutable .env loader
│   ├── capture/                      # 16:9 screen grabber, macro controller, notifier
│   ├── parsers/                      # Pydantic schemas, router, agent/offline/online parsers
│   └── engine/                       # Deterministic Strategist Engine
├── captures/latest/                  # Captured PNGs, session_manifest.json, AGENT_TASK.md
├── data/                             # roster.json, echo_bag.json, recommendations.json
├── ui/index.html                     # Single-file local dark-mode dashboard
├── run_test_capture_admin.bat        # One-click Admin launcher for 1600x900 test run
└── run_capture_admin.bat             # One-click Admin launcher for full scan
```

---

## Privacy & `.gitignore` Policy

Personal account details, environment configs, chat transcripts, screenshots, and generated JSON data are **excluded from git tracking** by `.gitignore`:

* `.env` and `.env.*` (except `.env.example`)
* `context/strategy_profile.json` (use `context/strategy_profile.example.json` as the tracked template)
* `data/*.json` (`roster.json`, `echo_bag.json`, `recommendations.json`)
* `captures/calibration_preview.png` and everything inside `captures/latest/` (except `.gitkeep`)
* `docs/chat.md`
