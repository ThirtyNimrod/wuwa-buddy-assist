"""Strict Pydantic v2 schemas and deterministic Echo math helpers."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def parse_stat_value(raw_value: str | float | int) -> float:
    """Parse a numeric stat string such as '22.0%', '+40', or '1,980' into float."""
    if isinstance(raw_value, (int, float)):
        return float(raw_value)
    cleaned = str(raw_value).strip().replace(",", "").replace("%", "").lstrip("+")
    if not cleaned:
        raise ValueError(f"Empty stat value cannot be parsed: {raw_value!r}")
    return float(cleaned)


def normalize_stat_key(raw_stat: str, raw_value: str | float | int) -> str:
    """Normalize Wuthering Waves stat names, distinguishing flat vs percentage ATK/HP/DEF."""
    text = re.sub(r"\s+", " ", raw_stat.strip()).lower()
    val_str = str(raw_value).strip()
    is_pct = "%" in val_str

    already_normalized = {
        "atk_pct",
        "atk_flat",
        "hp_pct",
        "hp_flat",
        "def_pct",
        "def_flat",
        "crit_rate",
        "crit_dmg",
        "energy_regen",
        "healing_bonus",
        "havoc_dmg_pct",
        "aero_dmg_pct",
        "spectro_dmg_pct",
        "fusion_dmg_pct",
        "glacio_dmg_pct",
        "electro_dmg_pct",
        "basic_attack_dmg",
        "heavy_attack_dmg",
        "resonance_skill_dmg",
        "resonance_liberation_dmg",
    }
    key_candidate = text.replace(".", "").replace(" ", "_")
    if key_candidate in already_normalized:
        return key_candidate.upper()

    if text in {"atk", "attack"}:
        return "ATK_PCT" if is_pct else "ATK_FLAT"
    if text in {"hp", "health"}:
        return "HP_PCT" if is_pct else "HP_FLAT"
    if text in {"def", "defense", "defence"}:
        return "DEF_PCT" if is_pct else "DEF_FLAT"

    alias_map = {
        "crit. rate": "CRIT_RATE",
        "crit rate": "CRIT_RATE",
        "crit. dmg": "CRIT_DMG",
        "crit dmg": "CRIT_DMG",
        "energy regen": "ENERGY_REGEN",
        "healing bonus": "HEALING_BONUS",
        "havoc dmg bonus": "HAVOC_DMG_PCT",
        "aero dmg bonus": "AERO_DMG_PCT",
        "spectro dmg bonus": "SPECTRO_DMG_PCT",
        "fusion dmg bonus": "FUSION_DMG_PCT",
        "glacio dmg bonus": "GLACIO_DMG_PCT",
        "electro dmg bonus": "ELECTRO_DMG_PCT",
        "basic attack dmg bonus": "BASIC_ATTACK_DMG",
        "heavy attack dmg bonus": "HEAVY_ATTACK_DMG",
        "resonance skill dmg bonus": "RESONANCE_SKILL_DMG",
        "resonance liberation dmg bonus": "RESONANCE_LIBERATION_DMG",
    }
    if text in alias_map:
        return alias_map[text]

    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")


class StatEntry(BaseModel):
    """Normalized stat entry on an Echo main stat or substat row."""

    stat: str
    value: float

    @model_validator(mode="before")
    @classmethod
    def _normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict) and "stat" in data and "value" in data:
            raw_stat = str(data["stat"])
            raw_val = data["value"]
            return {
                "stat": normalize_stat_key(raw_stat, raw_val),
                "value": parse_stat_value(raw_val),
            }
        return data


def compute_crit_value(substats: list[StatEntry]) -> float:
    """Compute Crit Value from Echo substats: CV = (Crit Rate * 2) + Crit DMG."""
    crit_rate = 0.0
    crit_dmg = 0.0
    for sub in substats:
        if sub.stat == "CRIT_RATE":
            crit_rate += sub.value
        elif sub.stat == "CRIT_DMG":
            crit_dmg += sub.value
    return round((crit_rate * 2.0) + crit_dmg, 1)


def compute_echo_id(
    name: str,
    sonata_set: str,
    cost: int,
    level: int,
    main_stat_key: str,
    substats: list[StatEntry],
) -> str:
    """Generate a deterministic 12-char SHA256 fingerprint for Echo deduplication."""
    sorted_subs = sorted(f"{s.stat}:{s.value:.1f}" for s in substats)
    payload = "|".join(
        [
            name.strip().lower(),
            sonata_set.strip().lower(),
            str(int(cost)),
            str(int(level)),
            main_stat_key.strip().upper(),
            ",".join(sorted_subs),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


class ResonatorStats(BaseModel):
    """Resonator overview stats panel values."""

    model_config = ConfigDict(populate_by_name=True)

    hp: float = Field(ge=0)
    atk: float = Field(ge=0)
    defense: float = Field(alias="def", ge=0)
    energy_regen: float = Field(ge=100.0)
    crit_rate: float = Field(ge=0.0)
    crit_dmg: float = Field(ge=100.0)
    element_dmg_bonus: float = Field(default=0.0, ge=0.0)


class WeaponInfo(BaseModel):
    """Equipped weapon metadata."""

    name: str
    level: int = Field(ge=1, le=90)
    rank: int = Field(default=1, ge=1, le=5)


class ForteLevels(BaseModel):
    """Forte skill tree node levels and inherent passives."""

    basic_attack: int = Field(ge=1, le=10)
    resonance_skill: int = Field(ge=1, le=10)
    forte_circuit: int = Field(ge=1, le=10)
    resonance_liberation: int = Field(ge=1, le=10)
    intro_skill: int = Field(ge=1, le=10)
    inherent_skill_1: bool = False
    inherent_skill_2: bool = False


class EchoBase(BaseModel):
    """Shared Echo structure for both equipped and backpack Echoes."""

    echo_id: str = ""
    name: str
    cost: Literal[1, 3, 4]
    level: int = Field(ge=0, le=25)
    sonata_set: str
    main_stat: StatEntry
    fixed_stat: StatEntry | None = None
    substats: list[StatEntry] = Field(default_factory=list, max_length=5)
    crit_value: float | None = None

    @model_validator(mode="after")
    def _populate_derived(self) -> "EchoBase":
        computed_cv = compute_crit_value(self.substats)
        if self.crit_value is None or self.crit_value == 0.0:
            self.crit_value = computed_cv
        else:
            self.crit_value = round(float(self.crit_value), 1)

        if not self.echo_id:
            self.echo_id = compute_echo_id(
                name=self.name,
                sonata_set=self.sonata_set,
                cost=self.cost,
                level=self.level,
                main_stat_key=self.main_stat.stat,
                substats=self.substats,
            )
        return self


class EquippedEcho(EchoBase):
    """Equipped Echo bound to a deterministic slot (1..5)."""

    slot: int = Field(ge=1, le=5)


class BackpackEcho(EchoBase):
    """Echo scanned from the Backpack Echo grid."""

    source_file: str | None = None
    equipped_by: str | None = None


class ResonatorBuild(BaseModel):
    """Complete Resonator build record."""

    id: str
    name: str
    element: str
    level: int = Field(ge=1, le=90)
    level_cap: int = Field(default=80, ge=20, le=90)
    sequence: int = Field(default=0, ge=0, le=6)
    stats: ResonatorStats
    weapon: WeaponInfo
    forte: ForteLevels
    equipped_echoes: list[EquippedEcho] = Field(default_factory=list, max_length=5)


class RosterData(BaseModel):
    """Root schema for data/roster.json."""

    last_updated: str
    union_level: int = Field(ge=1, le=80)
    resonators: list[ResonatorBuild] = Field(default_factory=list)


class EchoBagData(BaseModel):
    """Root schema for data/echo_bag.json."""

    last_updated: str
    total_scanned: int = Field(ge=0)
    echoes: list[BackpackEcho] = Field(default_factory=list)


class BuildAlert(BaseModel):
    """Actionable warning or benchmark deficit detected by the Strategist Engine."""

    character: str
    severity: Literal["critical", "high", "medium", "info"]
    category: str
    message: str
    current_value: str | float | None = None
    target_value: str | float | None = None


class SwapRecommendation(BaseModel):
    """Prioritized Echo swap from Backpack onto an active team Resonator."""

    character: str
    slot: int = Field(ge=1, le=5)
    priority_score: float
    reason: str
    current_echo: EquippedEcho | None = None
    recommended_echo: BackpackEcho
    cv_gain: float
    er_gain: float
    fixes_sonata_set: bool = False


class FortePriority(BaseModel):
    """Next Forte upgrade task for an active character."""

    character: str
    step: int
    description: str
    current_status: str
    completed: bool = False


class WaveplateAllocation(BaseModel):
    """Single activity block within the daily 240 Waveplate plan."""

    activity: str
    runs: int
    waveplates: int
    target: str
    detail: str


class WaveplatePlan(BaseModel):
    """Daily 240 Waveplate expenditure recommendation."""

    daily_waveplates: int = 240
    primary_focus: str
    reasoning: str
    allocations: list[WaveplateAllocation] = Field(default_factory=list)


class EchoCleanupCandidate(BaseModel):
    """Unequipped Backpack Echo flagged as fodder/merge candidate."""

    echo_id: str
    name: str
    sonata_set: str
    cost: int
    level: int
    main_stat: str
    crit_value: float
    reason: str


class EchoCleanupPlan(BaseModel):
    """Summary of Backpack Echoes safe to discard or feed as XP."""

    candidate_count: int
    candidates: list[EchoCleanupCandidate] = Field(default_factory=list)


class Team2Suggestion(BaseModel):
    """Comfortable secondary team recommendation for Tower of Adversity / Endgame."""

    archetype_name: str
    members: list[dict[str, str]] = Field(default_factory=list)
    synergy_notes: str
    avoided_bottlenecks: str


class CharacterEvaluation(BaseModel):
    """Computed build summary for a single Resonator."""

    character: str
    sonata_counts: dict[str, int] = Field(default_factory=dict)
    total_echo_cv: float
    avg_echo_cv: float
    energy_regen: float
    energy_regen_ok: bool
    set_bonus_ok: bool
    next_forte_step: str | None = None


class RecommendationsData(BaseModel):
    """Root schema for data/recommendations.json."""

    generated_at: str
    union_level: int
    primary_team: list[str] = Field(default_factory=list)
    alerts: list[BuildAlert] = Field(default_factory=list)
    swap_recommendations: list[SwapRecommendation] = Field(default_factory=list)
    forte_priorities: list[FortePriority] = Field(default_factory=list)
    waveplate_plan: WaveplatePlan
    echo_cleanup: EchoCleanupPlan
    team2_builder: Team2Suggestion
    character_evaluations: dict[str, CharacterEvaluation] = Field(default_factory=dict)
