# Technical Architecture Proposal: `wuwa-buddy-assist`

This document serves as the **System Architecture Specification** for **`wuwa-buddy-assist`**. For the phased implementation and agent prompt templates, refer to [antigravity_development_plan.md](file:///d:/AntiGravity/wuwa-buddy-assist/antigravity_development_plan.md).

---

## 1. Executive Summary & Core Philosophy

### 1.1 Project Vision

`wuwa-buddy-assist` is a non-intrusive, account-aware desktop companion and theorycrafting strategist ("Buddy Assist") for *Wuthering Waves*. It automates the capture of in-game Resonator builds (Overview stats, Weapons, Equipped Echoes, Forte skill trees) and unequipped Backpack Echoes, converts those screenshots into structured JSON, and powers both a local interactive HTML dashboard and an AI Agent chat workflow.

### 1.2 Hardware & Anti-Cheat Design Constraints

1. **Zero Anti-Cheat Risk:** *Wuthering Waves* utilizes kernel-level Anti-Cheat Expert (ACE). This utility **never** reads process memory (`ReadProcessMemory`), injects DLLs, or intercepts network packets. It relies strictly on **OS-level Desktop Duplication (Screen Capture) + Simulated Hardware Mouse Scan-Codes** with randomized human-like jitter.
2. **8GB VRAM Optimization (RTX 2070 Max-Q Target):** Running *Wuthering Waves* at 1440p or 1080p consumes the majority of an 8GB GPU's VRAM. Therefore, the architecture enforces a **Two-Stage Decoupled Pipeline**:
   * **Stage 1 (In-Game Burst Capture):** Zero OCR or AI models are loaded while the game runs. A lightweight background daemon snaps screenshots into a local session folder and fires a Windows Toast Notification when finished.
   * **Stage 2 (Post-Game Processing & Strategy):** Once the user closes the game (or triggers post-processing), the router inspects `.env` (`APP_MODE=offline | online | agent`) to parse the screenshots into JSON and generate actionable upgrade/swap recommendations.

---

## 2. System Architecture & Directory Contract

### 2.1 Repository Directory Structure

```text
wuwa-buddy-assist/
├── .env                              # Runtime configuration & mode switches
├── technical_architecture_proposal.md # System architecture specification
├── antigravity_development_plan.md   # Step-by-step phased execution plan
├── context/
│   ├── strategy_profile.json         # Player roster, team preferences, UL caps, Forte roadmaps
│   ├── game_knowledge.json           # Sonata sets, Echo cost rules, Crit Value (CV) math
│   └── ui_anchors_16_9.json          # Normalized (0.0-1.0) click & crop coordinates for 1080p/1440p
├── src/
│   ├── main.py                       # Entry point: Hotkey listener & state coordinator
│   ├── capture/
│   │   ├── screen_grabber.py         # mss / dxcam 16:9 frame capture & resolution normalizer
│   │   ├── macro_controller.py       # Humanized auto-clicker for Resonators & Backpack grid
│   │   └── notifier.py               # Windows Toast Notification & process watcher
│   ├── parsers/
│   │   ├── router.py                 # Reads APP_MODE from .env and dispatches to A, B, or C
│   │   ├── offline_ocr.py            # Route A: OpenCV thresholding + RapidOCR (ONNX) + pHash
│   │   ├── online_vlm.py             # Route B: Cloud Multimodal API structured JSON extractor
│   │   └── agent_bridge.py           # Route C: Generates AGENT_TASK.md for Antigravity/Claude/GHCP
│   └── engine/
│       └── strategist.py             # Computes Crit Value, Echo hashes, and swap recommendations
├── captures/
│   └── latest/                       # Auto-cleaned or timestamped capture buffer
│       ├── session_manifest.json     # Metadata of captured screens & resolution
│       ├── resonators/               # char_01/ (01_overview.png, 02_weapon.png, 03_echo1..5.png, 08_forte.png)
│       └── backpack_echoes/          # bag_echo_001.png .. bag_echo_050.png
├── data/
│   ├── roster.json                   # Validated output of all scanned Resonators
│   ├── echo_bag.json                 # Validated output of unequipped/equipped Backpack Echoes
│   └── recommendations.json          # Buddy Assist output: Swaps, Waveplate tasks, Forte steps
└── ui/
    └── index.html                    # Single-file Local HTML/JS Buddy Dashboard
```

---

### 2.2 Configuration Specification (`.env`)

```ini
# --- EXECUTION ROUTING ---
# Options: "offline" (Local RapidOCR/Ollama), "online" (Cloud VLM API), "agent" (Antigravity/Claude/GHCP)
APP_MODE=agent

# --- HOTKEYS ---
HOTKEY_SCAN_ROSTER=F9
HOTKEY_SCAN_BAG=F10
HOTKEY_CALIBRATE=F8
HOTKEY_ABORT=F12

# --- ROSTER SCANNING SCOPE ---
ROSTER_COUNT=9
SCAN_WEAPONS=true
SCAN_ECHOES=true
SCAN_FORTE=true
SCAN_SEQUENCES=false

# --- BACKPACK ECHO SCANNING SCOPE ---
MAX_BAG_ECHOS=50
STOP_ON_PLUS_ZERO=true
BAG_GRID_COLS=6
BAG_VISIBLE_ROWS=4

# --- DISPLAY & TIMING ---
GAME_MONITOR=1
ASPECT_RATIO=16:9
BASE_CLICK_DELAY_MS=300
JITTER_MS=80
PIXEL_JITTER=3
WAIT_FOR_GAME_EXIT=true
```

---

### 2.3 Domain Context & Player Profile (`context/strategy_profile.json`)

To prevent OCR hallucinations and ground the AI Buddy Assist in the player's actual account state, `context/strategy_profile.json` stores the player's baseline truth:

* **Account Progression:** Union Level 59 (Resonator Level Cap: 80, Forte Skill Level Cap: 8/10). Story progression at Chapter 3 Act 2.
* **Known 5-Star Roster Whitelist:** `["Rover (Havoc)", "Rover (Aero)", "Rover (Spectro)", "Cartethyia", "Jianxin", "Luuk Herssen", "Yangyang: Xuanling", "Calcharo", "Encore", "Lucy", "Rebecca"]`.
* **Known 5-Star Weapons:** `["Bloodpact's Pledge (R2)", "Daybreaker's Spine"]`.
* **Playstyle & Comfort Rules:**
  * *Disliked:* Dual-selfish on-field comps with clunky field-time bottlenecks (e.g., Aero Rover + Calcharo + Lucy).
  * *Preferred Primary Team (Option 2 Core):* **Cartethyia (Main DPS) + Havoc Rover (Sub-DPS Burst) + Jianxin (Shield/Heal/Grouping Sustain & Liberation Deepen Outro)**.
* **Character-Specific Target Benchmarks:**
  * **Havoc Rover:** Must transition off mismatched *Windward Pilgrimage* (Aero) pieces onto **5-pc Sun-sinking Eclipse** (4-3-3-1-1 cost) with 4-Cost **Dreamless** (Crit Rate/DMG main stat, 50% post-Liberation bonus), 3-Cost **Tambourinist / Roseshroom / Havoc Dreadmane** (Havoc DMG%), 1-Cost **ATK%**, and **115%–120% Energy Regen**. Forte upgrade priority: Resonance Liberation & Forte Circuit `Lv. 5 → 6` → Unlock Inherent Skill 1 (*Metamorphosis*) → Liberation & Forte Circuit `Lv. 6 → 8` → Resonance Skill `Lv. 5 → 7/8`.
  * **Cartethyia:** Target **5-pc Sun-sinking Eclipse** or **Sierra Gale** (4-3-3-1-1 cost) with *Dreamless* or *Crownless*.
  * **Jianxin:** Target **5-pc Rejuvenating Glow** with 4-Cost **Bell-Borne Geochelone** (team damage reduction + 15% DMG shield) and **140%+ Energy Regen** (plus ATK% for Primordial Chi shield scaling).

---

### 2.4 Echo Disambiguation & Fingerprinting Specification

Because every Echo has randomized substats and players swap Echoes between characters, the system enforces four disambiguation rules:

1. **Physical Path Isolation:** Equipped Echoes are saved inside `captures/latest/resonators/char_XX/03_echo_slot_Y.png`. The slot (`1` through `5`) and owner (`char_XX`) are determined deterministically by the folder path before OCR begins.
2. **4-Zone Visual Segmentation (Right-Hand Detail Card):**
   * **Zone 1 (Header):** Extracts Echo Monster Name, `COST` integer (`4`, `3`, or `1`), Level (`+0` to `+25`), and Sonata Set Icon.
   * **Zone 2 (Main Stat Bar):** Shaded upper box containing exactly two rows: Variable Main Stat (top) and Fixed Main Stat (bottom).
   * **Zone 3 (Substat Block):** Up to 5 tuned substat rows below the horizontal divider.
   * **Zone 4 (Equipped Badge):** Bottom-right indicator in the Backpack view (`"Equipped by <Character>"` vs. `null`).
3. **Flat vs. Percentage Key Normalization:**
   * In *Wuthering Waves*, `ATK`, `HP`, and `DEF` appear as both flat integers and percentages on the same Echo.
   * **Rule:** If the extracted value string contains `%`, normalize the key to `ATK_PCT`, `HP_PCT`, or `DEF_PCT`. If it contains no `%`, normalize to `ATK_FLAT`, `HP_FLAT`, or `DEF_FLAT`.
4. **Deterministic Echo ID Hash & Crit Value (CV):**
   * **Formula for Crit Value:** $\text{CV} = (\text{Crit Rate} \times 2) + \text{Crit DMG}$.
   * **Unique Fingerprint (`echo_id`):** `SHA256(monster_name + sonata_set + cost + level + main_stat_key + sorted(substats))[:12]`. This allows the Strategist Engine to detect when an Echo in the Backpack is the exact same piece equipped on a Resonator.

---

### 2.5 Standardized JSON Data Contracts

#### `data/roster.json` Schema

```json
{
  "last_updated": "2026-11-15T14:00:00Z",
  "union_level": 59,
  "resonators": [
    {
      "id": "char_01",
      "name": "Rover (Havoc)",
      "element": "Havoc",
      "level": 80,
      "level_cap": 80,
      "sequence": 5,
      "stats": {
        "hp": 14250,
        "atk": 1980,
        "def": 1120,
        "energy_regen": 122.4,
        "crit_rate": 68.5,
        "crit_dmg": 242.0,
        "element_dmg_bonus": 42.0
      },
      "weapon": {
        "name": "Bloodpact's Pledge",
        "level": 80,
        "rank": 2
      },
      "forte": {
        "basic_attack": 5,
        "resonance_skill": 5,
        "forte_circuit": 6,
        "resonance_liberation": 6,
        "intro_skill": 5,
        "inherent_skill_1": true,
        "inherent_skill_2": false
      },
      "equipped_echoes": [
        {
          "echo_id": "a8f92c104b2e",
          "slot": 1,
          "name": "Dreamless",
          "cost": 4,
          "level": 25,
          "sonata_set": "Sun-sinking Eclipse",
          "main_stat": { "stat": "CRIT_RATE", "value": 22.0 },
          "substats": [
            { "stat": "CRIT_DMG", "value": 15.0 },
            { "stat": "ATK_PCT", "value": 8.6 },
            { "stat": "ENERGY_REGEN", "value": 9.2 },
            { "stat": "ATK_FLAT", "value": 40 }
          ],
          "crit_value": 15.0
        }
      ]
    }
  ]
}
```
