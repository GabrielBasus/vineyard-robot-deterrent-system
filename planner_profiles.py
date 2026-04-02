from __future__ import annotations

import sys
from typing import Any, Dict, Iterable, Mapping, MutableMapping


THESIS_CONFIRM_PROFILE_ID = "thesis_confirm"
THESIS_CALIBRATED_SELECTIVE_PROPOSED_PROFILE_ID = "thesis_calibrated_selective_proposed"


PLANNER_PROFILE_ALIASES = {
    "thesis_confirm": THESIS_CONFIRM_PROFILE_ID,
    "post_fix": THESIS_CONFIRM_PROFILE_ID,
    "thesis_calibrated_selective_proposed": THESIS_CALIBRATED_SELECTIVE_PROPOSED_PROFILE_ID,
    "thesis_selective": THESIS_CALIBRATED_SELECTIVE_PROPOSED_PROFILE_ID,
    "calibrated_selective": THESIS_CALIBRATED_SELECTIVE_PROPOSED_PROFILE_ID,
    "selective_proposed": THESIS_CALIBRATED_SELECTIVE_PROPOSED_PROFILE_ID,
}


PLANNER_PROFILES: Dict[str, Dict[str, Any]] = {
    THESIS_CONFIRM_PROFILE_ID: {
        "description": (
            "Conservative post-fix planner preset that keeps the older heuristic "
            "preventive admission behavior while preserving the rest of the runtime "
            "fixes and calibration support."
        ),
        "values": {
            "enable_assignment_task_value_term": True,
            "assigner_w_task_value": 0.20,
            "model_deterring_window_s": 120.0,
            "model_deterring_min_persistence_replans": 3,
            "model_deterring_max_eta_s": 90.0,
            "model_deterring_score_margin": 0.20,
            "model_deterring_budget_per_robot_per_hr": 3,
            "model_deterring_budget_mode": "count_per_hour",
            "model_deterring_budget_utility_per_robot_per_hr": 5.0,
            "model_deterring_gate_policy": "heuristic",
            "model_deterring_chance_threshold": 0.25,
            "model_deterring_min_deltaJ_per_cost": 0.25,
        },
        "rationale": {
            "assigner_w_task_value": (
                "Keeps task value as a moderate tie-break so corrected preventive utility "
                "matters without overpowering distance and load costs."
            ),
            "model_deterring_window_s": (
                "Uses a 120 s evidence window to stabilize post-fix preventive scoring "
                "without dragging in stale detections."
            ),
            "model_deterring_min_persistence_replans": (
                "Requires three consecutive replans before admission so a candidate must "
                "survive more than one transient hotspot refresh."
            ),
            "model_deterring_max_eta_s": (
                "Caps ETA at 90 s so admitted preventive work is still timely after the "
                "dispatch ordering fixes."
            ),
            "model_deterring_score_margin": (
                "Requires a 0.20 margin over patrol so preventive tasks only displace "
                "patrol when they are materially better."
            ),
            "model_deterring_budget_per_robot_per_hr": (
                "Limits each robot to about three preventive admissions per hour to keep "
                "yield high instead of maximizing preventive volume."
            ),
            "model_deterring_gate_policy": (
                "Keeps the legacy heuristic preventive gate instead of the later "
                "selective SPRT/capacity admission path."
            ),
            "model_deterring_chance_threshold": (
                "Retained for compatibility, but the heuristic gate no longer depends "
                "on the later selective event-probability admission stage."
            ),
            "model_deterring_min_deltaJ_per_cost": (
                "Retained for compatibility, but the heuristic gate does not use the "
                "later deltaJ-per-cost selective admission stage."
            ),
        },
    },
    THESIS_CALIBRATED_SELECTIVE_PROPOSED_PROFILE_ID: {
        "description": (
            "Thesis-facing proposed runtime preset: frozen calibrated intervention-aware "
            "SESTPP parameters with the older heuristic preventive admission behavior."
        ),
        "values": {
            "preventive_policy": "heuristic",
            "use_frozen_calibration": True,
            "calibration_manifest_path": "results/sestpp_calibration_sweep/sestpp_calibration_sweep_manifest.json",
            "enable_assignment_task_value_term": True,
            "assigner_w_task_value": 0.20,
            "model_deterring_window_s": 120.0,
            "enable_predicted_deltaJ_gate": False,
            "min_predicted_deltaJ_for_model_deterring": 0.0,
            "model_deterring_min_persistence_replans": 2,
            "model_deterring_max_eta_s": 120.0,
            "model_deterring_score_margin": 0.10,
            "model_deterring_budget_per_robot_per_hr": 4,
            "model_deterring_budget_mode": "count_per_hour",
            "model_deterring_budget_utility_per_robot_per_hr": 5.0,
            "model_deterring_gate_policy": "heuristic",
            "model_deterring_sprt_alpha": 0.25,
            "model_deterring_sprt_beta": 0.40,
            "model_deterring_sprt_patch_radius_m": 30.0,
            "model_deterring_min_sprt_margin": 1.25,
            "model_deterring_chance_threshold": 0.35,
            "model_deterring_min_deltaJ_per_cost": 1.0e5,
            "model_deterring_min_selection_weight": 0.25,
            "model_deterring_capacity_rho_max": 0.85,
            "model_deterring_capacity_history_window_s": 3600.0,
            "model_deterring_capacity_min_completed_tasks": 3,
            "model_deterring_capacity_fallback_budget_per_hr": 4,
            "model_deterring_global_admission_cap_per_cycle": 1,
            "model_deterring_require_idle_robot_for_admission": False,
            "model_deterring_prefer_idle_robots_for_assignment": True,
            "model_deterring_busy_fallback_p_event_min": 0.95,
            "model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
            "model_deterring_busy_fallback_eta_s_max": 1.25,
            "protect_direct_detection_from_model_deterring": True,
            "model_deterring_direct_conflict_radius_m": 35.0,
            "model_deterring_direct_conflict_window_s": 120.0,
            "protect_active_model_deterring_persistence": True,
            "model_deterring_min_persistence_lifetime_s": 180.0,
            "model_deterring_persistence_eta_multiplier": 2.0,
            "model_deterring_persistence_buffer_s": 60.0,
            "model_deterring_max_persistence_lifetime_s": 420.0,
            "model_deterring_lock_near_goal_radius_m": 10.0,
            "protect_active_model_deterring_goal_preemption": True,
            "protect_locked_model_deterring_from_patrol_assignment": True,
        },
        "rationale": {
            "preventive_policy": (
                "Makes the thesis proposed condition explicit while routing preventive "
                "admission through the legacy heuristic gate."
            ),
            "use_frozen_calibration": (
                "Freezes the winning SESTPP sweep configuration so downstream runtime "
                "results are tied to a reproducible calibration stage."
            ),
            "model_deterring_window_s": (
                "Uses a 120 s preventive evidence window, matching the production selective-gate sweeps."
            ),
            "model_deterring_chance_threshold": (
                "Retained as a documented tuning parameter, but the heuristic gate no longer "
                "uses the later selective chance-threshold stage."
            ),
            "model_deterring_min_deltaJ_per_cost": (
                "Retained as a documented tuning parameter, but the heuristic gate no longer "
                "uses the later selective deltaJ-per-cost stage."
            ),
            "model_deterring_min_selection_weight": (
                "Retained for compatibility only; the heuristic gate does not use SPRT-derived selection weights."
            ),
            "protect_direct_detection_from_model_deterring": (
                "Preserves direct-detection priority protections so preventive work cannot displace immediate detections."
            ),
        },
    },
}


def planner_profile_names() -> tuple[str, ...]:
    return tuple(sorted(PLANNER_PROFILES.keys()))


def canonicalize_planner_profile_name(profile_name: str | None) -> str:
    raw = str(profile_name or "").strip().lower()
    if not raw:
        return ""
    normalized = raw.replace("-", "_").replace(" ", "_")
    canonical = PLANNER_PROFILE_ALIASES.get(normalized, normalized)
    if canonical not in PLANNER_PROFILES:
        choices = ", ".join(planner_profile_names())
        raise ValueError(f"Unknown planner profile {profile_name!r}. Expected one of: {choices}")
    return canonical


def get_planner_profile_values(profile_name: str | None) -> Dict[str, Any]:
    canonical = canonicalize_planner_profile_name(profile_name)
    if not canonical:
        return {}
    return dict(PLANNER_PROFILES[canonical]["values"])


def get_planner_profile_details(profile_name: str | None) -> Dict[str, Any]:
    canonical = canonicalize_planner_profile_name(profile_name)
    if not canonical:
        return {}
    payload = dict(PLANNER_PROFILES[canonical])
    payload["id"] = canonical
    payload["values"] = dict(payload.get("values", {}))
    payload["rationale"] = dict(payload.get("rationale", {}))
    return payload


def explicit_cli_dests(parser, argv: list[str] | None = None) -> set[str]:
    argv = list(sys.argv[1:] if argv is None else argv)
    action_by_option = {}
    for action in getattr(parser, "_actions", []):
        for option in getattr(action, "option_strings", []):
            action_by_option[str(option)] = str(action.dest)

    explicit = set()
    for token in argv:
        if token == "--":
            break
        if not isinstance(token, str) or not token.startswith("-"):
            continue
        option = token.split("=", 1)[0]
        dest = action_by_option.get(option)
        if dest and dest != "help":
            explicit.add(dest)
    return explicit


def apply_planner_profile_defaults(
    target: MutableMapping[str, Any],
    profile_name: str | None,
    *,
    dest_map: Mapping[str, str],
    protected_dests: Iterable[str] = (),
    stringify: bool = False,
) -> tuple[str, Dict[str, Any]]:
    canonical = canonicalize_planner_profile_name(profile_name)
    if not canonical:
        return "", {}

    protected = {str(dest) for dest in protected_dests}
    values = get_planner_profile_values(canonical)
    for profile_key, dest in dest_map.items():
        if dest in protected or profile_key not in values:
            continue
        value = values[profile_key]
        target[dest] = str(value) if stringify else value
    return canonical, values
