from __future__ import annotations

import sys
from typing import Any, Dict, Iterable, Mapping, MutableMapping


THESIS_CONFIRM_PROFILE_ID = "thesis_confirm"
THESIS_CALIBRATED_SELECTIVE_PROPOSED_PROFILE_ID = "thesis_calibrated_selective_proposed"
THESIS_DISPATCH_REACT_PROFILE_ID = "thesis_dispatch_react"
THESIS_DISPATCH_UNC_PROFILE_ID = "thesis_dispatch_unc"
THESIS_DISPATCH_REACTIVE_FIRST_PROFILE_ID = "thesis_dispatch_reactive_first"
THESIS_DISPATCH_RES_0P00_PROFILE_ID = "thesis_dispatch_res_0p00"
THESIS_DISPATCH_RES_0P10_PROFILE_ID = "thesis_dispatch_res_0p10"
THESIS_DISPATCH_RES_0P25_PROFILE_ID = "thesis_dispatch_res_0p25"
THESIS_DISPATCH_RES_0P40_PROFILE_ID = "thesis_dispatch_res_0p40"
THESIS_DISPATCH_RES_RAND_0P25_PROFILE_ID = "thesis_dispatch_res_rand_0p25"
THESIS_DISPATCH_RES_SOFT_0P25_PROFILE_ID = "thesis_dispatch_res_soft_0p25"
THESIS_DISPATCH_RES_ADAPTIVE_0P25_PROFILE_ID = "thesis_dispatch_res_adaptive_0p25"
THESIS_DISPATCH_RES_ADAPTIVE_LEADTIME_0P25_PROFILE_ID = "thesis_dispatch_res_adaptive_leadtime_0p25"
THESIS_DISPATCH_RES_FEASIBLE_0P25_PROFILE_ID = "thesis_dispatch_res_feasible_0p25"
THESIS_DISPATCH_RES_IDLE_FEASIBLE_0P25_PROFILE_ID = "thesis_dispatch_res_idle_feasible_0p25"
THESIS_DISPATCH_RES_CONFIDENCE_0P25_PROFILE_ID = "thesis_dispatch_res_confidence_0p25"
THESIS_DISPATCH_RES_IDLE_FEASIBLE_CONFIDENCE_0P25_PROFILE_ID = "thesis_dispatch_res_idle_feasible_confidence_0p25"
THESIS_DISPATCH_RES_RISK_ADJUSTED_0P25_PROFILE_ID = "thesis_dispatch_res_risk_adjusted_0p25"
THESIS_DISPATCH_RES_TIME_SCORE_0P25_PROFILE_ID = "thesis_dispatch_res_time_score_0p25"
THESIS_DISPATCH_RES_TIME_SCORE_V2_0P25_PROFILE_ID = "thesis_dispatch_res_time_score_v2_0p25"
THESIS_DISPATCH_RES_DEFERRED_TIME_SCORE_0P25_PROFILE_ID = "thesis_dispatch_res_deferred_time_score_0p25"
THESIS_DISPATCH_RES_CENTRALIZED_GLOBAL_0P25_PROFILE_ID = "thesis_dispatch_res_centralized_global_0p25"


PLANNER_PROFILE_ALIASES = {
    "thesis_confirm": THESIS_CONFIRM_PROFILE_ID,
    "post_fix": THESIS_CONFIRM_PROFILE_ID,
    "thesis_calibrated_selective_proposed": THESIS_CALIBRATED_SELECTIVE_PROPOSED_PROFILE_ID,
    "thesis_selective": THESIS_CALIBRATED_SELECTIVE_PROPOSED_PROFILE_ID,
    "calibrated_selective": THESIS_CALIBRATED_SELECTIVE_PROPOSED_PROFILE_ID,
    "selective_proposed": THESIS_CALIBRATED_SELECTIVE_PROPOSED_PROFILE_ID,
    "thesis_dispatch_react": THESIS_DISPATCH_REACT_PROFILE_ID,
    "dispatch_react": THESIS_DISPATCH_REACT_PROFILE_ID,
    "thesis_react": THESIS_DISPATCH_REACT_PROFILE_ID,
    "thesis_dispatch_unc": THESIS_DISPATCH_UNC_PROFILE_ID,
    "dispatch_unc": THESIS_DISPATCH_UNC_PROFILE_ID,
    "thesis_unc": THESIS_DISPATCH_UNC_PROFILE_ID,
    "thesis_dispatch_reactive_first": THESIS_DISPATCH_REACTIVE_FIRST_PROFILE_ID,
    "dispatch_reactive_first": THESIS_DISPATCH_REACTIVE_FIRST_PROFILE_ID,
    "reactive_first": THESIS_DISPATCH_REACTIVE_FIRST_PROFILE_ID,
    "thesis_dispatch_res_0p00": THESIS_DISPATCH_RES_0P00_PROFILE_ID,
    "dispatch_res_0p00": THESIS_DISPATCH_RES_0P00_PROFILE_ID,
    "thesis_res_0p00": THESIS_DISPATCH_RES_0P00_PROFILE_ID,
    "thesis_dispatch_res_0p10": THESIS_DISPATCH_RES_0P10_PROFILE_ID,
    "dispatch_res_0p10": THESIS_DISPATCH_RES_0P10_PROFILE_ID,
    "thesis_res_0p10": THESIS_DISPATCH_RES_0P10_PROFILE_ID,
    "res_0p10": THESIS_DISPATCH_RES_0P10_PROFILE_ID,
    "thesis_dispatch_res_0p25": THESIS_DISPATCH_RES_0P25_PROFILE_ID,
    "dispatch_res_0p25": THESIS_DISPATCH_RES_0P25_PROFILE_ID,
    "thesis_res_0p25": THESIS_DISPATCH_RES_0P25_PROFILE_ID,
    "res_0p25": THESIS_DISPATCH_RES_0P25_PROFILE_ID,
    "thesis_dispatch_res_0p40": THESIS_DISPATCH_RES_0P40_PROFILE_ID,
    "dispatch_res_0p40": THESIS_DISPATCH_RES_0P40_PROFILE_ID,
    "thesis_res_0p40": THESIS_DISPATCH_RES_0P40_PROFILE_ID,
    "res_0p40": THESIS_DISPATCH_RES_0P40_PROFILE_ID,
    "thesis_dispatch_res_rand_0p25": THESIS_DISPATCH_RES_RAND_0P25_PROFILE_ID,
    "dispatch_res_rand_0p25": THESIS_DISPATCH_RES_RAND_0P25_PROFILE_ID,
    "thesis_res_rand_0p25": THESIS_DISPATCH_RES_RAND_0P25_PROFILE_ID,
    "res_rand_0p25": THESIS_DISPATCH_RES_RAND_0P25_PROFILE_ID,
    "thesis_dispatch_res_soft_0p25": THESIS_DISPATCH_RES_SOFT_0P25_PROFILE_ID,
    "dispatch_res_soft_0p25": THESIS_DISPATCH_RES_SOFT_0P25_PROFILE_ID,
    "thesis_res_soft_0p25": THESIS_DISPATCH_RES_SOFT_0P25_PROFILE_ID,
    "res_soft_0p25": THESIS_DISPATCH_RES_SOFT_0P25_PROFILE_ID,
    "thesis_dispatch_res_adaptive_0p25": THESIS_DISPATCH_RES_ADAPTIVE_0P25_PROFILE_ID,
    "dispatch_res_adaptive_0p25": THESIS_DISPATCH_RES_ADAPTIVE_0P25_PROFILE_ID,
    "thesis_res_adaptive_0p25": THESIS_DISPATCH_RES_ADAPTIVE_0P25_PROFILE_ID,
    "res_adaptive_0p25": THESIS_DISPATCH_RES_ADAPTIVE_0P25_PROFILE_ID,
    "thesis_dispatch_res_adaptive_leadtime_0p25": THESIS_DISPATCH_RES_ADAPTIVE_LEADTIME_0P25_PROFILE_ID,
    "dispatch_res_adaptive_leadtime_0p25": THESIS_DISPATCH_RES_ADAPTIVE_LEADTIME_0P25_PROFILE_ID,
    "thesis_res_adaptive_leadtime_0p25": THESIS_DISPATCH_RES_ADAPTIVE_LEADTIME_0P25_PROFILE_ID,
    "res_adaptive_leadtime_0p25": THESIS_DISPATCH_RES_ADAPTIVE_LEADTIME_0P25_PROFILE_ID,
    "thesis_dispatch_res_feasible_0p25": THESIS_DISPATCH_RES_FEASIBLE_0P25_PROFILE_ID,
    "dispatch_res_feasible_0p25": THESIS_DISPATCH_RES_FEASIBLE_0P25_PROFILE_ID,
    "thesis_res_feasible_0p25": THESIS_DISPATCH_RES_FEASIBLE_0P25_PROFILE_ID,
    "res_feasible_0p25": THESIS_DISPATCH_RES_FEASIBLE_0P25_PROFILE_ID,
    "thesis_dispatch_res_idle_feasible_0p25": THESIS_DISPATCH_RES_IDLE_FEASIBLE_0P25_PROFILE_ID,
    "dispatch_res_idle_feasible_0p25": THESIS_DISPATCH_RES_IDLE_FEASIBLE_0P25_PROFILE_ID,
    "thesis_res_idle_feasible_0p25": THESIS_DISPATCH_RES_IDLE_FEASIBLE_0P25_PROFILE_ID,
    "res_idle_feasible_0p25": THESIS_DISPATCH_RES_IDLE_FEASIBLE_0P25_PROFILE_ID,
    "thesis_dispatch_res_confidence_0p25": THESIS_DISPATCH_RES_CONFIDENCE_0P25_PROFILE_ID,
    "dispatch_res_confidence_0p25": THESIS_DISPATCH_RES_CONFIDENCE_0P25_PROFILE_ID,
    "thesis_res_confidence_0p25": THESIS_DISPATCH_RES_CONFIDENCE_0P25_PROFILE_ID,
    "res_confidence_0p25": THESIS_DISPATCH_RES_CONFIDENCE_0P25_PROFILE_ID,
    "thesis_dispatch_res_idle_feasible_confidence_0p25": THESIS_DISPATCH_RES_IDLE_FEASIBLE_CONFIDENCE_0P25_PROFILE_ID,
    "dispatch_res_idle_feasible_confidence_0p25": THESIS_DISPATCH_RES_IDLE_FEASIBLE_CONFIDENCE_0P25_PROFILE_ID,
    "thesis_res_idle_feasible_confidence_0p25": THESIS_DISPATCH_RES_IDLE_FEASIBLE_CONFIDENCE_0P25_PROFILE_ID,
    "res_idle_feasible_confidence_0p25": THESIS_DISPATCH_RES_IDLE_FEASIBLE_CONFIDENCE_0P25_PROFILE_ID,
    "thesis_dispatch_res_risk_adjusted_0p25": THESIS_DISPATCH_RES_RISK_ADJUSTED_0P25_PROFILE_ID,
    "dispatch_res_risk_adjusted_0p25": THESIS_DISPATCH_RES_RISK_ADJUSTED_0P25_PROFILE_ID,
    "thesis_res_risk_adjusted_0p25": THESIS_DISPATCH_RES_RISK_ADJUSTED_0P25_PROFILE_ID,
    "res_risk_adjusted_0p25": THESIS_DISPATCH_RES_RISK_ADJUSTED_0P25_PROFILE_ID,
    "thesis_dispatch_res_opportunity_cost_0p25": THESIS_DISPATCH_RES_RISK_ADJUSTED_0P25_PROFILE_ID,
    "dispatch_res_opportunity_cost_0p25": THESIS_DISPATCH_RES_RISK_ADJUSTED_0P25_PROFILE_ID,
    "thesis_res_opportunity_cost_0p25": THESIS_DISPATCH_RES_RISK_ADJUSTED_0P25_PROFILE_ID,
    "res_opportunity_cost_0p25": THESIS_DISPATCH_RES_RISK_ADJUSTED_0P25_PROFILE_ID,
    "thesis_dispatch_res_time_score_0p25": THESIS_DISPATCH_RES_TIME_SCORE_0P25_PROFILE_ID,
    "dispatch_res_time_score_0p25": THESIS_DISPATCH_RES_TIME_SCORE_0P25_PROFILE_ID,
    "thesis_res_time_score_0p25": THESIS_DISPATCH_RES_TIME_SCORE_0P25_PROFILE_ID,
    "res_time_score_0p25": THESIS_DISPATCH_RES_TIME_SCORE_0P25_PROFILE_ID,
    "res_time_aware_0p25": THESIS_DISPATCH_RES_TIME_SCORE_0P25_PROFILE_ID,
    "thesis_dispatch_res_time_score_v2_0p25": THESIS_DISPATCH_RES_TIME_SCORE_V2_0P25_PROFILE_ID,
    "dispatch_res_time_score_v2_0p25": THESIS_DISPATCH_RES_TIME_SCORE_V2_0P25_PROFILE_ID,
    "thesis_res_time_score_v2_0p25": THESIS_DISPATCH_RES_TIME_SCORE_V2_0P25_PROFILE_ID,
    "res_time_score_v2_0p25": THESIS_DISPATCH_RES_TIME_SCORE_V2_0P25_PROFILE_ID,
    "res_time_aware_v2_0p25": THESIS_DISPATCH_RES_TIME_SCORE_V2_0P25_PROFILE_ID,
    "thesis_dispatch_res_deferred_time_score_0p25": THESIS_DISPATCH_RES_DEFERRED_TIME_SCORE_0P25_PROFILE_ID,
    "dispatch_res_deferred_time_score_0p25": THESIS_DISPATCH_RES_DEFERRED_TIME_SCORE_0P25_PROFILE_ID,
    "thesis_res_deferred_time_score_0p25": THESIS_DISPATCH_RES_DEFERRED_TIME_SCORE_0P25_PROFILE_ID,
    "res_deferred_time_score_0p25": THESIS_DISPATCH_RES_DEFERRED_TIME_SCORE_0P25_PROFILE_ID,
    "res_deferred_mode_0p25": THESIS_DISPATCH_RES_DEFERRED_TIME_SCORE_0P25_PROFILE_ID,
    "thesis_dispatch_res_centralized_global_0p25": THESIS_DISPATCH_RES_CENTRALIZED_GLOBAL_0P25_PROFILE_ID,
    "dispatch_res_centralized_global_0p25": THESIS_DISPATCH_RES_CENTRALIZED_GLOBAL_0P25_PROFILE_ID,
    "thesis_res_centralized_global_0p25": THESIS_DISPATCH_RES_CENTRALIZED_GLOBAL_0P25_PROFILE_ID,
    "res_centralized_global_0p25": THESIS_DISPATCH_RES_CENTRALIZED_GLOBAL_0P25_PROFILE_ID,
    "centralized_global_predictive": THESIS_DISPATCH_RES_CENTRALIZED_GLOBAL_0P25_PROFILE_ID,
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
    THESIS_DISPATCH_REACT_PROFILE_ID: {
        "description": "Thesis dispatch reframe baseline: reactive-only admission over the proposed predictive workload.",
        "values": {
            "dispatch_policy": "react",
            "reservation_fraction": 0.0,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "utility",
        },
        "rationale": {
            "dispatch_policy": "Blocks predictive admissions while still allowing predictive generation for funnel accounting.",
        },
    },
    THESIS_DISPATCH_UNC_PROFILE_ID: {
        "description": "Thesis dispatch reframe baseline: unconstrained priority dispatch over the proposed predictive workload.",
        "values": {
            "dispatch_policy": "unc",
            "reservation_fraction": 0.0,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "utility",
        },
        "rationale": {
            "dispatch_policy": "Preserves the current production admission and ordering path as the thesis unc baseline.",
        },
    },
    THESIS_DISPATCH_REACTIVE_FIRST_PROFILE_ID: {
        "description": (
            "Thesis dispatch baseline: reactive-first dispatch over the proposed "
            "predictive workload. Predictive tasks are used only when no reactive "
            "task is available."
        ),
        "values": {
            "dispatch_policy": "reactive-first",
            "reservation_fraction": 0.0,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "utility",
        },
        "rationale": {
            "dispatch_policy": (
                "Preserves the previous unc behavior as an explicit reactive-first "
                "baseline rather than conflating it with unconstrained mixed greedy."
            ),
        },
    },
    THESIS_DISPATCH_RES_0P00_PROFILE_ID: {
        "description": "Diagnostic reserved-capacity profile with zero predictive reservation.",
        "values": {
            "dispatch_policy": "res",
            "reservation_fraction": 0.0,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "utility",
        },
        "rationale": {
            "reservation_fraction": "Diagnostic edge case showing reserved-capacity logic with no predictive reservation.",
        },
    },
    THESIS_DISPATCH_RES_0P10_PROFILE_ID: {
        "description": "Reserved-capacity thesis profile with rho=0.10.",
        "values": {
            "dispatch_policy": "res",
            "reservation_fraction": 0.10,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "utility",
        },
        "rationale": {
            "reservation_fraction": "Low predictive reservation for the spare-capacity regime.",
        },
    },
    THESIS_DISPATCH_RES_0P25_PROFILE_ID: {
        "description": "Reserved-capacity thesis profile with rho=0.25.",
        "values": {
            "dispatch_policy": "res",
            "reservation_fraction": 0.25,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "utility",
        },
        "rationale": {
            "reservation_fraction": "Nominal thesis reserved-capacity setting used for the main comparison and ablation.",
        },
    },
    THESIS_DISPATCH_RES_0P40_PROFILE_ID: {
        "description": "Reserved-capacity thesis profile with rho=0.40.",
        "values": {
            "dispatch_policy": "res",
            "reservation_fraction": 0.40,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "utility",
        },
        "rationale": {
            "reservation_fraction": "High predictive reservation for the aggressive spare-capacity regime.",
        },
    },
    THESIS_DISPATCH_RES_RAND_0P25_PROFILE_ID: {
        "description": "Reserved-capacity ablation with rho=0.25 and random predictive target selection.",
        "values": {
            "dispatch_policy": "res",
            "reservation_fraction": 0.25,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "random",
        },
        "rationale": {
            "predictive_selection_policy": "Keeps reservation logic fixed while randomizing predictive target choice for the scoring ablation.",
        },
    },
    THESIS_DISPATCH_RES_SOFT_0P25_PROFILE_ID: {
        "description": "Soft reserved-capacity thesis profile with rho=0.25 and load-aware reservation softening.",
        "values": {
            "dispatch_policy": "res-soft",
            "reservation_fraction": 0.25,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "reservation_softening_alpha": 2.0,
            "predictive_selection_policy": "utility",
        },
        "rationale": {
            "dispatch_policy": "Uses the same reserved-capacity framing as hard res, but softens the predictive claim as reactive pressure rises.",
            "reservation_softening_alpha": "Scales how aggressively the predictive reservation target shrinks under reactive pressure.",
        },
    },
    THESIS_DISPATCH_RES_ADAPTIVE_0P25_PROFILE_ID: {
        "description": (
            "Adaptive reserved-capacity thesis profile with rho=0.25, reactive-pressure softening, "
            "and a reactive-age gate that blocks predictive claims before detections become urgent."
        ),
        "values": {
            "dispatch_policy": "res-adaptive",
            "reservation_fraction": 0.25,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "reservation_softening_alpha": 2.0,
            "reservation_age_softening_beta": 2.0,
            "reservation_age_gate": 0.5,
            "predictive_selection_policy": "utility",
        },
        "rationale": {
            "dispatch_policy": (
                "Keeps the capacity-aware reservation framing but shrinks the predictive target under "
                "reactive pressure and disables predictive claims once reactive waiting age crosses a gate."
            ),
            "reservation_softening_alpha": "Scales how aggressively reservation shrinks as reactive competition grows.",
            "reservation_age_softening_beta": "Adds a second shrink term based on normalized reactive waiting age.",
            "reservation_age_gate": "Blocks predictive claims when the oldest reactive task has aged too close to the override horizon.",
        },
    },
    THESIS_DISPATCH_RES_ADAPTIVE_LEADTIME_0P25_PROFILE_ID: {
        "description": (
            "Adaptive reserved-capacity thesis profile with rho=0.25, predictive lead-time release, "
            "and a tighter reactive-age gate to keep predictive claims from delaying aging detections."
        ),
        "values": {
            "dispatch_policy": "res-adaptive",
            "reservation_fraction": 0.25,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "reservation_softening_alpha": 2.0,
            "reservation_age_softening_beta": 5.0,
            "reservation_age_gate": 0.25,
            "predictive_selection_policy": "utility",
            "enable_predictive_lead_time": True,
            "predictive_timing_mode": "arrival_offset",
            "predictive_lead_time_min_s": 30.0,
            "predictive_lead_time_max_eta_s": 120.0,
            "predictive_lead_time_buffer_s": 15.0,
            "predictive_lead_time_risk_power": 1.0,
        },
        "rationale": {
            "dispatch_policy": (
                "Combines adaptive reservation shrinkage with future-event preventive release so "
                "predictive claims only happen while reactive waiting age is still safely low."
            ),
            "reservation_age_softening_beta": (
                "Uses a stronger reactive-age penalty than the earlier adaptive profile so the "
                "effective reservation target decays sooner as detections age."
            ),
            "reservation_age_gate": (
                "Uses a tighter normalized age gate, blocking predictive claims once the oldest "
                "reactive task reaches about 25% of the override horizon."
            ),
            "enable_predictive_lead_time": (
                "Turns on intervention-horizon predictive task timing so preventive tasks target "
                "future bird occupancy instead of immediate hotspots."
            ),
        },
    },
    THESIS_DISPATCH_RES_FEASIBLE_0P25_PROFILE_ID: {
        "description": (
            "Lead-time reserved-capacity profile that only claims predictive work when the "
            "forecast task still has enough intervention slack to be feasible."
        ),
        "values": {
            "dispatch_policy": "res-feasible",
            "reservation_fraction": 0.25,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "utility",
            "enable_predictive_lead_time": True,
            "predictive_timing_mode": "arrival_offset",
            "predictive_lead_time_min_s": 30.0,
            "predictive_lead_time_max_eta_s": 120.0,
            "predictive_lead_time_buffer_s": 15.0,
            "predictive_lead_time_risk_power": 1.0,
            "predictive_slack_min_s": 15.0,
        },
        "rationale": {
            "dispatch_policy": (
                "Preserves reserved-capacity dispatch, but predictive claims are only allowed when the "
                "task can still be completed with at least a small positive deadline slack."
            ),
            "predictive_slack_min_s": (
                "Requires at least 15 s of remaining intervention slack before a predictive task can "
                "consume reserved capacity."
            ),
        },
    },
    THESIS_DISPATCH_RES_IDLE_FEASIBLE_0P25_PROFILE_ID: {
        "description": (
            "Lead-time reserved-capacity profile that only claims predictive work when the robot is "
            "idle, reactive pressure is low, and the predictive task is still feasible."
        ),
        "values": {
            "dispatch_policy": "res-idle-feasible",
            "reservation_fraction": 0.25,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "utility",
            "enable_predictive_lead_time": True,
            "predictive_timing_mode": "arrival_offset",
            "predictive_lead_time_min_s": 30.0,
            "predictive_lead_time_max_eta_s": 120.0,
            "predictive_lead_time_buffer_s": 15.0,
            "predictive_lead_time_risk_power": 1.0,
            "predictive_slack_min_s": 15.0,
            "reactive_pressure_max_for_predictive": 0.5,
        },
        "rationale": {
            "dispatch_policy": (
                "Makes the capacity-aware claim opportunistic instead of intrusive by allowing "
                "predictive reservation only when the robot is idle and reactive pressure is modest."
            ),
            "reactive_pressure_max_for_predictive": (
                "Blocks predictive claims once reactive pressure exceeds 0.5 in the simple queue-pressure proxy."
            ),
        },
    },
    THESIS_DISPATCH_RES_CONFIDENCE_0P25_PROFILE_ID: {
        "description": (
            "Lead-time reserved-capacity profile that ranks predictive work with an explicit confidence-"
            "weighted dispatch score."
        ),
        "values": {
            "dispatch_policy": "res-confidence",
            "reservation_fraction": 0.25,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "confidence-weighted",
            "enable_predictive_lead_time": True,
            "predictive_timing_mode": "arrival_offset",
            "predictive_lead_time_min_s": 30.0,
            "predictive_lead_time_max_eta_s": 120.0,
            "predictive_lead_time_buffer_s": 15.0,
            "predictive_lead_time_risk_power": 1.0,
            "predictive_deadline_weight": 2.0,
            "predictive_eta_penalty_weight": 0.1,
            "predictive_confidence_source": "p_event_times_selection_weight",
        },
        "rationale": {
            "predictive_selection_policy": (
                "Ranks predictive candidates by confidence-weighted predicted benefit rather than raw utility alone."
            ),
            "predictive_confidence_source": (
                "Uses p_event multiplied by selection_weight so predictive claims only get strong priority when "
                "the field is both high value and well supported."
            ),
        },
    },
    THESIS_DISPATCH_RES_IDLE_FEASIBLE_CONFIDENCE_0P25_PROFILE_ID: {
        "description": (
            "Combined lead-time capacity-aware profile with idle/feasibility gating and explicit confidence-"
            "weighted predictive scoring."
        ),
        "values": {
            "dispatch_policy": "res-idle-feasible-confidence",
            "reservation_fraction": 0.25,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "confidence-weighted",
            "enable_predictive_lead_time": True,
            "predictive_timing_mode": "arrival_offset",
            "predictive_lead_time_min_s": 30.0,
            "predictive_lead_time_max_eta_s": 120.0,
            "predictive_lead_time_buffer_s": 15.0,
            "predictive_lead_time_risk_power": 1.0,
            "predictive_slack_min_s": 15.0,
            "reactive_pressure_max_for_predictive": 0.5,
            "predictive_confidence_min": 0.25,
            "predictive_deadline_weight": 2.0,
            "predictive_eta_penalty_weight": 0.1,
            "predictive_confidence_source": "p_event_times_selection_weight",
        },
        "rationale": {
            "dispatch_policy": (
                "Combines the opportunistic idle/pressure gate with confidence-weighted predictive scoring so "
                "capacity is only reserved for feasible, credible preventive work."
            ),
            "predictive_confidence_min": (
                "Filters out weak-confidence predictive tasks before they can consume reserved capacity."
            ),
        },
    },
    THESIS_DISPATCH_RES_RISK_ADJUSTED_0P25_PROFILE_ID: {
        "description": (
            "Risk-adjusted reserved-capacity profile with rho=0.25 that treats predictive work as an "
            "optional investment gated by confidence, deadline slack, net utility, cost ratio, and reactive "
            "opportunity cost."
        ),
        "values": {
            "dispatch_policy": "res-risk-adjusted",
            "reservation_fraction": 0.25,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "reservation_age_gate": 0.5,
            "predictive_selection_policy": "risk-adjusted",
            "enable_predictive_lead_time": True,
            "predictive_timing_mode": "arrival_offset",
            "predictive_lead_time_min_s": 30.0,
            "predictive_lead_time_max_eta_s": 120.0,
            "predictive_lead_time_buffer_s": 15.0,
            "predictive_lead_time_risk_power": 1.0,
            "predictive_slack_min_s": 15.0,
            "predictive_confidence_min": 0.25,
            "predictive_utility_min": 0.0,
            "predictive_cost_ratio_min": 1.0,
            "predictive_opportunity_cost_weight": 0.1,
            "predictive_eta_cost_weight": 0.1,
            "predictive_service_cost_weight": 0.05,
            "risk_adjusted_reservation_alpha": 2.0,
            "risk_adjusted_reservation_beta": 2.0,
            "predictive_confidence_source": "p_event_times_selection_weight",
        },
        "rationale": {
            "dispatch_policy": (
                "Predictive tasks consume reserved capacity only when confidence-weighted expected exposure "
                "reduction exceeds travel, service, and reactive opportunity costs."
            ),
            "predictive_cost_ratio_min": (
                "Requires at least break-even confidence-weighted benefit per dispatch cost before a predictive "
                "candidate can be claimed."
            ),
            "risk_adjusted_reservation_alpha": (
                "Shrinks the effective predictive reservation fraction as the reactive queue pressure rises."
            ),
            "risk_adjusted_reservation_beta": (
                "Further shrinks the reservation as the oldest reactive task approaches the override horizon."
            ),
        },
    },
    THESIS_DISPATCH_RES_TIME_SCORE_0P25_PROFILE_ID: {
        "description": (
            "Lead-time reserved-capacity profile that recomputes predictive deployment value at dispatch time "
            "from current deadline slack, ETA, confidence, and reactive pressure."
        ),
        "values": {
            "dispatch_policy": "res",
            "reservation_fraction": 0.25,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "time-aware",
            "enable_predictive_lead_time": True,
            "predictive_timing_mode": "arrival_offset",
            "predictive_lead_time_min_s": 30.0,
            "predictive_lead_time_max_eta_s": 120.0,
            "predictive_lead_time_buffer_s": 15.0,
            "predictive_lead_time_risk_power": 1.0,
            "predictive_deadline_weight": 2.0,
            "predictive_eta_penalty_weight": 0.1,
            "predictive_confidence_source": "p_event_times_selection_weight",
            "predictive_time_score_deadline_scale_s": 120.0,
            "predictive_time_score_reactive_pressure_weight": 5.0,
            "predictive_time_score_infeasible_penalty": 25.0,
        },
        "rationale": {
            "predictive_selection_policy": (
                "Recomputes predictive attractiveness at deployment time instead of relying mainly on the "
                "generation-time score."
            ),
            "predictive_time_score_deadline_scale_s": (
                "Controls how quickly the deployment score rises as the forecast event gets closer."
            ),
            "predictive_time_score_reactive_pressure_weight": (
                "Penalizes predictive claims when reactive pressure is already elevated."
            ),
            "predictive_time_score_infeasible_penalty": (
                "Strongly demotes predictive tasks that can no longer arrive before the forecast event."
            ),
        },
    },
    THESIS_DISPATCH_RES_TIME_SCORE_V2_0P25_PROFILE_ID: {
        "description": (
            "Lead-time reserved-capacity profile that deduplicates predictive opportunities and "
            "recomputes predictive deployment value at dispatch time from predicted delta-J, "
            "confidence, deadline slack, ETA, and reactive pressure."
        ),
        "values": {
            "dispatch_policy": "res",
            "reservation_fraction": 0.25,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "time-aware-v2",
            "enable_predictive_lead_time": True,
            "predictive_timing_mode": "arrival_offset",
            "predictive_lead_time_min_s": 30.0,
            "predictive_lead_time_max_eta_s": 120.0,
            "predictive_lead_time_buffer_s": 15.0,
            "predictive_lead_time_risk_power": 1.0,
            "predictive_expiry_grace_s": 0.0,
            "predictive_deadline_weight": 2.0,
            "predictive_eta_penalty_weight": 0.1,
            "predictive_confidence_source": "p_event_times_selection_weight",
            "predictive_time_score_deadline_scale_s": 120.0,
            "predictive_time_score_reactive_pressure_weight": 5.0,
            "predictive_time_score_infeasible_penalty": 25.0,
        },
        "rationale": {
            "predictive_selection_policy": (
                "Uses a deployment-time score driven by predicted delta-J rather than the larger of "
                "generation-time utility and delta-J, so stale high-utility tasks do not dominate."
            ),
            "predictive_timing_mode": (
                "Treats forecast timing as a future-event horizon instead of synthesizing the event time "
                "directly from intervention delay."
            ),
            "predictive_expiry_grace_s": (
                "Expires predictive tasks immediately once they can no longer arrive before the forecast event."
            ),
        },
    },
    THESIS_DISPATCH_RES_DEFERRED_TIME_SCORE_0P25_PROFILE_ID: {
        "description": (
            "Lead-time reserved-capacity profile that keeps predictive opportunities mode-agnostic "
            "until dispatch, then selects the best concrete action for each robot using a hybrid ETA basis."
        ),
        "values": {
            "dispatch_policy": "res",
            "reservation_fraction": 0.25,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "time-aware",
            "enable_predictive_lead_time": True,
            "predictive_timing_mode": "arrival_offset",
            "predictive_lead_time_min_s": 30.0,
            "predictive_lead_time_max_eta_s": 120.0,
            "predictive_lead_time_buffer_s": 15.0,
            "predictive_lead_time_risk_power": 1.0,
            "predictive_deadline_weight": 2.0,
            "predictive_eta_penalty_weight": 0.1,
            "predictive_confidence_source": "p_event_times_selection_weight",
            "predictive_time_score_deadline_scale_s": 120.0,
            "predictive_time_score_reactive_pressure_weight": 5.0,
            "predictive_time_score_infeasible_penalty": 25.0,
            "defer_predictive_action_selection": True,
            "assignment_switch_penalty": 1.0,
        },
        "rationale": {
            "defer_predictive_action_selection": (
                "Preserves one predictive opportunity with multiple feasible modes, then resolves a "
                "single concrete action at dispatch time instead of collapsing to one mode during generation."
            ),
            "assignment_switch_penalty": (
                "Penalizes predictive reassignment away from a robot's current committed goal so ETA is not "
                "underestimated for busy robots."
            ),
        },
    },
    THESIS_DISPATCH_RES_CENTRALIZED_GLOBAL_0P25_PROFILE_ID: {
        "description": (
            "Experimental centralized predictive-planning branch with one global SESTPP, one shared "
            "predictive opportunity pool, deferred action resolution, and soft zone-aware assignment."
        ),
        "values": {
            "dispatch_policy": "res",
            "reservation_fraction": 0.25,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "time-aware",
            "predictive_planning_topology": "centralized_global",
            "zone_assignment_mode": "soft",
            "enable_predictive_lead_time": True,
            "predictive_timing_mode": "arrival_offset",
            "predictive_lead_time_min_s": 30.0,
            "predictive_lead_time_max_eta_s": 120.0,
            "predictive_lead_time_buffer_s": 15.0,
            "predictive_lead_time_risk_power": 1.0,
            "predictive_deadline_weight": 2.0,
            "predictive_eta_penalty_weight": 0.1,
            "predictive_confidence_source": "p_event_times_selection_weight",
            "predictive_time_score_deadline_scale_s": 120.0,
            "predictive_time_score_reactive_pressure_weight": 5.0,
            "predictive_time_score_infeasible_penalty": 25.0,
            "defer_predictive_action_selection": True,
            "assignment_switch_penalty": 1.0,
        },
        "rationale": {
            "predictive_planning_topology": (
                "Uses one shared predictive field and one centralized opportunity pool instead of robot-local "
                "predictive planning."
            ),
            "zone_assignment_mode": (
                "Retains zone partitioning as a soft locality bias rather than hard predictive task ownership."
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
