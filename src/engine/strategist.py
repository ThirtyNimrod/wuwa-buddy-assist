"""Deterministic Buddy Assist Strategist Engine (Phase 4)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT, load_json_file
from src.parsers.models import (
    BackpackEcho,
    BuildAlert,
    CharacterEvaluation,
    EchoBagData,
    EchoBase,
    EchoCleanupCandidate,
    EchoCleanupPlan,
    EquippedEcho,
    FortePriority,
    RecommendationsData,
    ResonatorBuild,
    RosterData,
    SwapRecommendation,
    Team2Suggestion,
    WaveplateAllocation,
    WaveplatePlan,
    compute_crit_value,
    compute_echo_id,
)


def _echo_energy_regen(echo: EchoBase) -> float:
    """Return total Energy Regen % contributed by an Echo's main stat and substats."""
    total = 0.0
    if echo.main_stat.stat == "ENERGY_REGEN":
        total += echo.main_stat.value
    for sub in echo.substats:
        if sub.stat == "ENERGY_REGEN":
            total += sub.value
    return round(total, 1)


def _normalize_echo(echo: EchoBase) -> dict[str, Any]:
    """Return a clean dict dump with deterministically recomputed CV and echo_id."""
    cv = compute_crit_value(echo.substats)
    eid = compute_echo_id(
        name=echo.name,
        sonata_set=echo.sonata_set,
        cost=echo.cost,
        level=echo.level,
        main_stat_key=echo.main_stat.stat,
        substats=echo.substats,
    )
    data = echo.model_dump()
    data["crit_value"] = cv
    data["echo_id"] = eid
    return data


def _retag_roster_and_bag(
    roster: RosterData,
    echo_bag: EchoBagData,
) -> tuple[RosterData, EchoBagData, dict[str, str]]:
    """Return updated copies of RosterData and EchoBagData with fresh CV/echo_id tags."""
    equipped_owners: dict[str, str] = {}
    updated_resonators: list[ResonatorBuild] = []

    for res in roster.resonators:
        updated_echoes: list[EquippedEcho] = []
        for echo in res.equipped_echoes:
            echo_dict = _normalize_echo(echo)
            equipped_owners[echo_dict["echo_id"]] = res.name
            updated_echoes.append(EquippedEcho.model_validate(echo_dict))

        res_dict = res.model_dump(by_alias=True)
        res_dict["equipped_echoes"] = [e.model_dump() for e in updated_echoes]
        updated_resonators.append(ResonatorBuild.model_validate(res_dict))

    new_roster = RosterData(
        last_updated=roster.last_updated,
        union_level=roster.union_level,
        resonators=updated_resonators,
    )

    seen_bag_ids: set[str] = set()
    updated_bag_echoes: list[BackpackEcho] = []
    for bag_echo in echo_bag.echoes:
        bag_dict = _normalize_echo(bag_echo)
        eid = bag_dict["echo_id"]
        if eid in equipped_owners and not bag_dict.get("equipped_by"):
            bag_dict["equipped_by"] = equipped_owners[eid]
        # Preserve only the first occurrence of identical echoes if duplicate scan occurred
        if eid in seen_bag_ids:
            continue
        seen_bag_ids.add(eid)
        updated_bag_echoes.append(BackpackEcho.model_validate(bag_dict))

    new_bag = EchoBagData(
        last_updated=echo_bag.last_updated,
        total_scanned=len(updated_bag_echoes),
        echoes=updated_bag_echoes,
    )
    return new_roster, new_bag, equipped_owners


def _evaluate_forte_steps(
    resonator: ResonatorBuild,
    target_cfg: dict[str, Any],
) -> list[FortePriority]:
    """Check character's Forte progress against their strategy_profile roadmap."""
    priorities: list[FortePriority] = []
    forte_dump = resonator.forte.model_dump()
    for step_cfg in target_cfg.get("forte_roadmap", []):
        step_num = int(step_cfg["step"])
        nodes = list(step_cfg["nodes"])
        target_lvl = int(step_cfg["target_level"])
        desc = str(step_cfg["description"])

        statuses: list[str] = []
        done = True
        for node in nodes:
            val = forte_dump.get(node)
            if isinstance(val, bool):
                statuses.append(f"{node}: {'Unlocked' if val else 'Locked'}")
                if not val:
                    done = False
            else:
                curr = int(val or 1)
                statuses.append(f"{node}: Lv.{curr}/{target_lvl}")
                if curr < target_lvl:
                    done = False

        priorities.append(
            FortePriority(
                character=resonator.name,
                step=step_num,
                description=desc,
                current_status=" | ".join(statuses),
                completed=done,
            )
        )
    return priorities


def _evaluate_character(
    resonator: ResonatorBuild,
    target_cfg: dict[str, Any],
    alerts: list[BuildAlert],
) -> CharacterEvaluation:
    """Generate alerts and summary metrics for a single Resonator."""
    sonata_counts: dict[str, int] = {}
    for echo in resonator.equipped_echoes:
        sonata_counts[echo.sonata_set] = sonata_counts.get(echo.sonata_set, 0) + 1

    total_cv = round(sum((e.crit_value or 0.0) for e in resonator.equipped_echoes), 1)
    avg_cv = round(total_cv / len(resonator.equipped_echoes), 1) if resonator.equipped_echoes else 0.0

    target_set = target_cfg.get("target_sonata_set")
    acceptable_sets = set(target_cfg.get("acceptable_sonata_sets") or ([target_set] if target_set else []))
    forbidden_sets = set(target_cfg.get("forbidden_sonata_sets") or [])

    for echo in resonator.equipped_echoes:
        if echo.sonata_set in forbidden_sets:
            alerts.append(
                BuildAlert(
                    character=resonator.name,
                    severity="critical",
                    category="mismatched_sonata_set",
                    message=(
                        f"Slot {echo.slot} ({echo.name}) uses forbidden/mismatched Sonata set "
                        f"'{echo.sonata_set}'. Replace with '{target_set}'."
                    ),
                    current_value=echo.sonata_set,
                    target_value=target_set,
                )
            )
        elif (echo.crit_value or 0.0) < 20.0 and resonator.name != "Jianxin":
            alerts.append(
                BuildAlert(
                    character=resonator.name,
                    severity="medium",
                    category="low_crit_value",
                    message=(
                        f"Slot {echo.slot} ({echo.name}) has low Crit Value ({echo.crit_value:.1f} CV < 20.0)."
                    ),
                    current_value=echo.crit_value,
                    target_value=20.0,
                )
            )

    set_bonus_ok = any(sonata_counts.get(s, 0) >= 5 for s in acceptable_sets) if acceptable_sets else True
    if not set_bonus_ok and acceptable_sets:
        expected_label = " or ".join(sorted(acceptable_sets))
        best_count = max((sonata_counts.get(s, 0) for s in acceptable_sets), default=0)
        alerts.append(
            BuildAlert(
                character=resonator.name,
                severity="high",
                category="incomplete_5pc_set",
                message=(
                    f"{resonator.name} is missing 5-pc {expected_label} bonus "
                    f"(currently {best_count}/5 pieces)."
                ),
                current_value=best_count,
                target_value=5,
            )
        )

    min_er = float(target_cfg.get("min_energy_regen", 100.0))
    er_ok = resonator.stats.energy_regen >= min_er
    if not er_ok:
        alerts.append(
            BuildAlert(
                character=resonator.name,
                severity="high" if resonator.name == "Jianxin" else "medium",
                category="energy_regen_deficit",
                message=(
                    f"{resonator.name} Energy Regen is {resonator.stats.energy_regen:.1f}%, "
                    f"below target {min_er:.1f}%."
                ),
                current_value=resonator.stats.energy_regen,
                target_value=min_er,
            )
        )

    preferred_4 = set(target_cfg.get("preferred_4_cost_echoes") or [])
    if preferred_4:
        cost4_echoes = [e for e in resonator.equipped_echoes if e.cost == 4]
        if cost4_echoes and not any(e.name in preferred_4 for e in cost4_echoes):
            alerts.append(
                BuildAlert(
                    character=resonator.name,
                    severity="medium",
                    category="suboptimal_main_echo",
                    message=(
                        f"{resonator.name} 4-Cost Echo is '{cost4_echoes[0].name}'; "
                        f"target is {', '.join(sorted(preferred_4))}."
                    ),
                    current_value=cost4_echoes[0].name,
                    target_value=", ".join(sorted(preferred_4)),
                )
            )

    forte_steps = _evaluate_forte_steps(resonator, target_cfg)
    next_step = next((f.description for f in forte_steps if not f.completed), None)

    return CharacterEvaluation(
        character=resonator.name,
        sonata_counts=sonata_counts,
        total_echo_cv=total_cv,
        avg_echo_cv=avg_cv,
        energy_regen=resonator.stats.energy_regen,
        energy_regen_ok=er_ok,
        set_bonus_ok=set_bonus_ok,
        next_forte_step=next_step,
    )


def _find_swap_recommendations(
    active_resonators: list[ResonatorBuild],
    bag_echoes: list[BackpackEcho],
    equipped_ids: set[str],
    character_targets: dict[str, Any],
) -> list[SwapRecommendation]:
    """Compare unequipped Backpack Echoes against equipped slots on the active team."""
    swaps: list[SwapRecommendation] = []
    unequipped_bag = [
        e for e in bag_echoes if e.equipped_by is None and e.echo_id not in equipped_ids
    ]

    for res in active_resonators:
        target_cfg = character_targets.get(res.name)
        if not target_cfg:
            continue

        target_set = target_cfg.get("target_sonata_set")
        acceptable_sets = set(target_cfg.get("acceptable_sonata_sets") or ([target_set] if target_set else []))
        preferred_main_by_cost = target_cfg.get("preferred_main_stats_by_cost", {})
        min_er = float(target_cfg.get("min_energy_regen", 100.0))
        needs_er = res.stats.energy_regen < min_er

        for equipped in res.equipped_echoes:
            allowed_mains = set(preferred_main_by_cost.get(str(equipped.cost), []))
            equipped_cv = equipped.crit_value or 0.0
            equipped_er = _echo_energy_regen(equipped)
            equipped_is_valid_set = equipped.sonata_set in acceptable_sets

            for candidate in unequipped_bag:
                if candidate.cost != equipped.cost:
                    continue
                if acceptable_sets and candidate.sonata_set not in acceptable_sets:
                    continue
                if allowed_mains and candidate.main_stat.stat not in allowed_mains:
                    continue

                cand_cv = candidate.crit_value or 0.0
                cand_er = _echo_energy_regen(candidate)
                cv_gain = round(cand_cv - equipped_cv, 1)
                er_gain = round(cand_er - equipped_er, 1)
                fixes_set = (not equipped_is_valid_set) and (candidate.sonata_set in acceptable_sets)

                qualifies = False
                reasons: list[str] = []

                if fixes_set:
                    qualifies = True
                    reasons.append(
                        f"Replaces mismatched '{equipped.sonata_set}' with '{candidate.sonata_set}'"
                    )
                if needs_er and er_gain >= 4.0 and cv_gain >= -6.0:
                    qualifies = True
                    reasons.append(f"+{er_gain:.1f}% Energy Regen toward {min_er:.0f}% target")
                if cv_gain > 0.5 and (not needs_er or er_gain >= 0.0):
                    qualifies = True
                    reasons.append(f"+{cv_gain:.1f} CV upgrade ({equipped_cv:.1f} -> {cand_cv:.1f})")

                if not qualifies:
                    continue

                score = (
                    (100.0 if fixes_set else 0.0)
                    + (er_gain * 2.2 if needs_er else er_gain * 0.3)
                    + cv_gain
                )
                swaps.append(
                    SwapRecommendation(
                        character=res.name,
                        slot=equipped.slot,
                        priority_score=round(score, 1),
                        reason="; ".join(reasons),
                        current_echo=equipped,
                        recommended_echo=candidate,
                        cv_gain=cv_gain,
                        er_gain=er_gain,
                        fixes_sonata_set=fixes_set,
                    )
                )

    swaps.sort(key=lambda item: item.priority_score, reverse=True)
    return swaps


def _build_waveplate_plan(
    forte_priorities: list[FortePriority],
    alerts: list[BuildAlert],
) -> WaveplatePlan:
    """Allocate daily 240 Waveplates between Forgery Challenges and Tacet Fields."""
    rover_pending = [
        f for f in forte_priorities if f.character == "Rover (Havoc)" and not f.completed
    ]
    missing_sets = any(a.category in {"mismatched_sonata_set", "incomplete_5pc_set"} for a in alerts)

    if rover_pending:
        next_rover = rover_pending[0].description
        if missing_sets:
            return WaveplatePlan(
                daily_waveplates=240,
                primary_focus="Forgery Challenges + Tacet Field Split (Havoc Rover Forte Lv.6 -> Lv.8)",
                reasoning=(
                    f"Prioritize Havoc Rover's Forte roadmap ({next_rover}) with 3 Forgery Challenge runs "
                    "and allocate remaining Waveplates to Tacet Fields for Sun-sinking Eclipse / Rejuvenating Glow."
                ),
                allocations=[
                    WaveplateAllocation(
                        activity="Forgery Challenge (Metallic Drip / Forte Materials)",
                        runs=3,
                        waveplates=120,
                        target="Rover (Havoc)",
                        detail=f"Progress '{next_rover}' toward UL59 Lv.8 cap",
                    ),
                    WaveplateAllocation(
                        activity="Tacet Field (Sun-sinking Eclipse / Rejuvenating Glow)",
                        runs=2,
                        waveplates=120,
                        target="Rover (Havoc) & Jianxin",
                        detail="Farm 3-Cost Havoc DMG / ER pieces + Sealed Tubes",
                    ),
                ],
            )
        return WaveplatePlan(
            daily_waveplates=240,
            primary_focus="Forgery Challenges (Havoc Rover Lv. 6 -> Lv. 8 Roadmap)",
            reasoning=(
                f"Active team Sonata sets are complete; invest full 240 Waveplates into Forgery Challenges "
                f"for '{next_rover}'."
            ),
            allocations=[
                WaveplateAllocation(
                    activity="Forgery Challenge (Sword / Forte Materials)",
                    runs=6,
                    waveplates=240,
                    target="Rover (Havoc)",
                    detail=next_rover,
                )
            ],
        )

    return WaveplatePlan(
        daily_waveplates=240,
        primary_focus="Tacet Fields (Echo CV & Tuner Optimization)",
        reasoning="Forte roadmap milestones up to UL59 cap are satisfied; focus Waveplates on Echo tuning.",
        allocations=[
            WaveplateAllocation(
                activity="Tacet Field",
                runs=4,
                waveplates=240,
                target="Cartethyia / Rover (Havoc)",
                detail="Upgrade sub-25 CV slots and build Echo XP reserves",
            )
        ],
    )


def _build_cleanup_plan(
    bag_echoes: list[BackpackEcho],
    recommended_ids: set[str],
    equipped_ids: set[str],
) -> EchoCleanupPlan:
    """Identify unequipped Backpack Echoes safe for Echo XP or Data Merge."""
    candidates: list[EchoCleanupCandidate] = []
    for echo in bag_echoes:
        if echo.equipped_by is not None or echo.echo_id in equipped_ids:
            continue
        if echo.echo_id in recommended_ids:
            continue

        cv = echo.crit_value or 0.0
        er = _echo_energy_regen(echo)
        is_support_er = echo.sonata_set == "Rejuvenating Glow" and (
            echo.main_stat.stat in {"HEALING_BONUS", "ENERGY_REGEN", "ATK_PCT"} and er >= 8.0
        )
        if is_support_er:
            continue

        reason: str | None = None
        if echo.main_stat.stat in {"HP_PCT", "DEF_PCT"} and echo.cost in {3, 4}:
            reason = f"Dead main stat ({echo.main_stat.stat}) on Cost {echo.cost} {echo.sonata_set}"
        elif echo.level == 0:
            reason = "Unenhanced +0 Echo (safe Data Merge candidate if not keeping for tuning)"
        elif echo.level >= 15 and cv < 15.0:
            reason = f"Low Crit Value ({cv:.1f} CV) at +{echo.level}"

        if reason:
            candidates.append(
                EchoCleanupCandidate(
                    echo_id=echo.echo_id,
                    name=echo.name,
                    sonata_set=echo.sonata_set,
                    cost=echo.cost,
                    level=echo.level,
                    main_stat=echo.main_stat.stat,
                    crit_value=cv,
                    reason=reason,
                )
            )

    return EchoCleanupPlan(candidate_count=len(candidates), candidates=candidates)


def _build_team2_suggestion(roster: RosterData) -> Team2Suggestion:
    """Propose a comfortable Endgame Team 2 from benched Resonators without field-time bottlenecks."""
    available_names = {r.name for r in roster.resonators}
    primary_names = {"Cartethyia", "Rover (Havoc)", "Jianxin"}
    benched = [name for name in sorted(available_names) if name not in primary_names]

    members: list[dict[str, str]] = []
    if "Encore" in available_names:
        members.append({"name": "Encore", "role": "Main DPS (Fusion Quick-Swap)"})
    elif "Calcharo" in available_names:
        members.append({"name": "Calcharo", "role": "Main DPS (Electro)"})

    if "Yangyang: Xuanling" in available_names:
        members.append({"name": "Yangyang: Xuanling", "role": "Sub-DPS / Grouping & Outro Energy Battery"})
    elif "Luuk Herssen" in available_names:
        members.append({"name": "Luuk Herssen", "role": "Sub-DPS / Flex"})

    if "Luuk Herssen" in available_names and not any(m["name"] == "Luuk Herssen" for m in members):
        members.append({"name": "Luuk Herssen", "role": "Flex Sustain / Sub-DPS"})
    elif "Rebecca" in available_names:
        members.append({"name": "Rebecca", "role": "Flex Support"})

    if not members and benched:
        members = [{"name": name, "role": "Benched Flex"} for name in benched[:3]]

    return Team2Suggestion(
        archetype_name="Encore Quick-Swap + Energy Battery Core",
        members=members,
        synergy_notes=(
            "Encore's cancelable Heavy/Skill windows pair smoothly with Yangyang: Xuanling's "
            "20-Energy Outro battery and grouping, avoiding greedy on-field lockouts."
        ),
        avoided_bottlenecks="Explicitly avoids dual-selfish comps like Aero Rover + Calcharo + Lucy.",
    )


def run_strategist(
    roster_path: Path | None = None,
    bag_path: Path | None = None,
    profile_path: Path | None = None,
    output_path: Path | None = None,
    project_root: Path | None = None,
) -> RecommendationsData:
    """Execute Phase 4 deterministic evaluation and write data/recommendations.json."""
    root = project_root or PROJECT_ROOT
    r_path = roster_path or (root / "data" / "roster.json")
    b_path = bag_path or (root / "data" / "echo_bag.json")
    default_profile = root / "context" / "strategy_profile.json"
    if not default_profile.exists():
        default_profile = root / "context" / "strategy_profile.example.json"
    p_path = profile_path or default_profile
    out_path = output_path or (root / "data" / "recommendations.json")

    raw_roster = load_json_file(r_path)
    raw_bag = load_json_file(b_path)
    profile = load_json_file(p_path)

    roster_in = RosterData.model_validate(raw_roster)
    bag_in = EchoBagData.model_validate(raw_bag)

    roster, bag, equipped_owners = _retag_roster_and_bag(roster_in, bag_in)
    equipped_ids = set(equipped_owners.keys())

    # Persist normalized echo_ids and crit_values back to roster.json and echo_bag.json
    r_path.write_text(
        json.dumps(roster.model_dump(by_alias=True), indent=2) + "\n",
        encoding="utf-8",
    )
    b_path.write_text(
        json.dumps(bag.model_dump(), indent=2) + "\n",
        encoding="utf-8",
    )

    preferred_members = [
        m["name"]
        for m in profile.get("playstyle_and_comfort_rules", {})
        .get("preferred_primary_team", {})
        .get("members", [])
    ]
    character_targets = profile.get("character_targets", {})

    alerts: list[BuildAlert] = []
    forte_priorities: list[FortePriority] = []
    evaluations: dict[str, CharacterEvaluation] = {}
    active_resonators: list[ResonatorBuild] = []

    roster_by_name = {r.name: r for r in roster.resonators}
    for member_name in preferred_members:
        res = roster_by_name.get(member_name)
        if res is None:
            continue
        active_resonators.append(res)
        target_cfg = character_targets.get(member_name, {})
        evaluations[member_name] = _evaluate_character(res, target_cfg, alerts)
        forte_priorities.extend(_evaluate_forte_steps(res, target_cfg))

    for res in roster.resonators:
        if res.name in evaluations:
            continue
        target_cfg = character_targets.get(res.name, {})
        evaluations[res.name] = _evaluate_character(res, target_cfg, alerts)

    swaps = _find_swap_recommendations(
        active_resonators=active_resonators,
        bag_echoes=bag.echoes,
        equipped_ids=equipped_ids,
        character_targets=character_targets,
    )
    recommended_bag_ids = {s.recommended_echo.echo_id for s in swaps}

    waveplate_plan = _build_waveplate_plan(forte_priorities, alerts)
    cleanup_plan = _build_cleanup_plan(bag.echoes, recommended_bag_ids, equipped_ids)
    team2 = _build_team2_suggestion(roster)

    recommendations = RecommendationsData(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        union_level=roster.union_level,
        primary_team=preferred_members,
        alerts=alerts,
        swap_recommendations=swaps,
        forte_priorities=forte_priorities,
        waveplate_plan=waveplate_plan,
        echo_cleanup=cleanup_plan,
        team2_builder=team2,
        character_evaluations=evaluations,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(recommendations.model_dump(), indent=2) + "\n",
        encoding="utf-8",
    )
    return recommendations
