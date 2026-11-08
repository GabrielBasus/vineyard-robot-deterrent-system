from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from itertools import product
import argparse
import json
import os
import time

import pandas as pd

import DeterrentSystem as ds
from config_loader import add_config_argument, parse_args_with_config, write_resolved_config_manifest
from planner_profiles import canonicalize_planner_profile_name, get_planner_profile_values


EXPERIMENT_RUNNER_CONFIG_ALIASES = {
    "runner.profile": "profile",
    "runner.max_workers": "max_workers",
    "runner.num_runs": "num_runs",
    "runner.seed_start": "seed_start",
    "runner.limit_settings": "limit_settings",
    "runner.scenario_scope": "scenario_scope",
    "runner.time_metrics_period_s": "time_metrics_period_s",
    "simulation.dt": "dt",
    "simulation.nx": "nx",
    "simulation.ny": "ny",
    "simulation.time_horizons_h": "time_horizons_h",
    "sweep.tune_preset": "tune_preset",
    "planner.profile": "planner_profile",
    "planner.proposed_preventive_policy": "proposed_preventive_policy",
    "calibration.use_frozen_calibration": "use_frozen_calibration",
    "calibration.ranking_path": "calibration_ranking_path",
    "calibration.manifest_path": "calibration_manifest_path",
    "calibration.config_id": "calibration_config_id",
    "winner.enable_winner_profile": "enable_winner_profile",
    "winner.winner_profile_id": "winner_profile_id",
}

VALID_PREVENTIVE_POLICIES = ("off", "heuristic", "sprt_capacity")


def _clean_optional_text(value) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip()


def _resolve_requested_runtime_controls(args: argparse.Namespace) -> dict:
    planner_profile = _clean_optional_text(getattr(args, "planner_profile", ""))
    if planner_profile:
        planner_profile = canonicalize_planner_profile_name(planner_profile)
    planner_profile_values = get_planner_profile_values(planner_profile)

    proposed_preventive_policy = _clean_optional_text(getattr(args, "proposed_preventive_policy", "")).lower()
    calibration_ranking_path = _clean_optional_text(getattr(args, "calibration_ranking_path", ""))
    calibration_manifest_path = _clean_optional_text(getattr(args, "calibration_manifest_path", ""))
    calibration_config_id = _clean_optional_text(getattr(args, "calibration_config_id", ""))
    explicit_calibration_selector = bool(
        calibration_ranking_path or calibration_manifest_path or calibration_config_id
    )
    use_frozen_calibration = bool(getattr(args, "use_frozen_calibration", False) or explicit_calibration_selector)

    # Fail fast by reusing the production runtime's own preventive-policy validation.
    ds._resolve_preventive_policy_settings(
        simulation_mode="proposed",
        preventive_policy=(proposed_preventive_policy or None),
        planner_profile=planner_profile,
        planner_profile_values=planner_profile_values,
        enable_model_scored_deterring=True,
        enable_predicted_deltaJ_gate=bool(planner_profile_values.get("enable_predicted_deltaJ_gate", False)),
        model_deterring_gate_policy=str(planner_profile_values.get("model_deterring_gate_policy", "heuristic")),
    )

    # Validate frozen-calibration requests with the production resolver instead of duplicating lookup logic here.
    if use_frozen_calibration or bool(planner_profile_values.get("use_frozen_calibration", False)):
        ds._resolve_calibration_runtime_overrides(
            simulation_mode="proposed",
            use_frozen_calibration=bool(use_frozen_calibration),
            calibration_ranking_path=(calibration_ranking_path or None),
            calibration_manifest_path=(calibration_manifest_path or None),
            calibration_config_id=(calibration_config_id or None),
            planner_profile=planner_profile,
            planner_profile_values=planner_profile_values,
            prediction_only_model_overrides=None,
            proposed_model_overrides=None,
            sigma=0.0,
            omega=1.0,
            alpha_in=None,
            alpha_cross=None,
            alpha_inhib=0.0,
            omega_inhib=0.0,
            mu_base=0.0,
            bg_ema=0.0,
            model_feedback_sigma_scale=1.0,
            model_feedback_omega_scale=1.0,
        )

    return {
        "planner_profile": str(planner_profile),
        "proposed_preventive_policy": str(proposed_preventive_policy),
        "use_frozen_calibration": bool(use_frozen_calibration),
        "calibration_ranking_path": str(calibration_ranking_path),
        "calibration_manifest_path": str(calibration_manifest_path),
        "calibration_config_id": str(calibration_config_id),
    }


def _mode_pack(scale_beta=1.0, scale_cost=1.0):
    return {
        "formation": {"beta": 0.30 * scale_beta, "omega": 800.0, "sigma": 18.0, "w_eta": 1.0 * scale_cost, "fixed_cost": 0.0},
        "laser": {"beta": 0.45 * scale_beta, "omega": 400.0, "sigma": 10.0, "w_eta": 1.5 * scale_cost, "fixed_cost": 0.0},
        "biosonic": {"beta": 0.25 * scale_beta, "omega": 600.0, "sigma": 20.0, "w_eta": 1.2 * scale_cost, "fixed_cost": 0.0},
    }


def _normalize_tune_entry(tune: dict) -> dict:
    out = dict(tune)
    out.setdefault("assigner_w_load", 0.8)
    out.setdefault("preempt_deterring_goals", True)
    out.setdefault("preempt_direct_detection_goals", True)
    out.setdefault("preempt_model_scored_goals", False)
    out.setdefault("intervention_boundary_min_interval_s", 60.0)
    out.setdefault("intervention_boundary_spatial_quant_m", 20.0)
    out.setdefault("intervention_boundary_min_weight", 0.35)

    out.setdefault("tune_assigner_w_load", float(out["assigner_w_load"]))
    out.setdefault("tune_preempt_deterring_goals", int(bool(out["preempt_deterring_goals"])))
    out.setdefault("tune_preempt_direct_detection_goals", int(bool(out["preempt_direct_detection_goals"])))
    out.setdefault("tune_preempt_model_scored_goals", int(bool(out["preempt_model_scored_goals"])))
    out.setdefault(
        "tune_intervention_boundary_min_interval_s",
        float(out["intervention_boundary_min_interval_s"]),
    )
    out.setdefault(
        "tune_intervention_boundary_spatial_quant_m",
        float(out["intervention_boundary_spatial_quant_m"]),
    )
    out.setdefault(
        "tune_intervention_boundary_min_weight",
        float(out["intervention_boundary_min_weight"]),
    )
    return out


def _flatten_run_metrics(result, seed_start, exp_id, scenario_id, tune_id, time_horizon_h):
    rows = []
    baselines = result.get("baselines", {})
    for baseline_name, baseline_result in baselines.items():
        run_list = baseline_result.get("runs", [])
        for run_idx, m in enumerate(run_list):
            seed = seed_start + run_idx
            travel_by_type = m.get("travel_distance_by_type", {})
            energy_by_type = m.get("energy_by_type", {})
            completed_by_type = m.get("completed_tasks_by_type", {})
            rows.append(
                {
                    "exp_id": exp_id,
                    "scenario_id": scenario_id,
                    "tune_id": tune_id,
                    "time_horizon_h": float(time_horizon_h),
                    "baseline": baseline_name,
                    "run_idx": int(run_idx),
                    "seed": int(seed),
                    "value_weighted_exposure": float(m.get("value_weighted_exposure", float("nan"))),
                    "mean_response_time_s": float(m.get("mean_response_time_s", float("nan"))),
                    "response_samples": int(m.get("response_samples", 0)),
                    "completed_tasks_total": int(m.get("completed_tasks_total", 0)),
                    "completed_tasks_deterring": int(completed_by_type.get("deterring", 0)),
                    "completed_tasks_patrolling": int(completed_by_type.get("patrolling", 0)),
                    "tasks_per_unit_distance": float(m.get("tasks_per_unit_distance", float("nan"))),
                    "exposure_per_completed_task": float(m.get("exposure_per_completed_task", float("nan"))),
                    "score_per_completed_task": float(m.get("score_per_completed_task", float("nan"))),
                    "travel_distance_ugv": float(travel_by_type.get("UGV", float("nan"))),
                    "travel_distance_uav": float(travel_by_type.get("UAV", float("nan"))),
                    "energy_ugv": float(energy_by_type.get("UGV", float("nan"))),
                    "energy_uav": float(energy_by_type.get("UAV", float("nan"))),
                    "boundary_message_count": int(m.get("boundary_message_count", 0)),
                    "boundary_bytes_sent": int(m.get("boundary_bytes_sent", 0)),
                    "intervention_msg_dropped_debounce": int(m.get("intervention_msg_dropped_debounce", 0)),
                    "intervention_msg_dropped_low_weight": int(m.get("intervention_msg_dropped_low_weight", 0)),
                    "forecast_recall_at_k": float(m.get("forecast_recall_at_k", float("nan"))),
                    "forecast_precision_at_k": float(m.get("forecast_precision_at_k", float("nan"))),
                    "forecast_hotspot_hit_rate": float(m.get("forecast_hotspot_hit_rate", float("nan"))),
                    "forecast_lead_time_s": float(m.get("forecast_lead_time_s", float("nan"))),
                    "forecast_samples": int(m.get("forecast_samples", 0)),
                    "model_deterring_generated": int(m.get("model_deterring_generated", 0)),
                    "model_deterring_candidates_total": int(m.get("model_deterring_candidates_total", 0)),
                    "model_deterring_rejected_cooldown": int(m.get("model_deterring_rejected_cooldown", 0)),
                    "model_deterring_rejected_field": int(m.get("model_deterring_rejected_field", 0)),
                    "model_deterring_pass_field": int(m.get("model_deterring_pass_field", 0)),
                    "model_deterring_pass_risk": int(m.get("model_deterring_pass_risk", 0)),
                    "model_deterring_pass_support": int(m.get("model_deterring_pass_support", 0)),
                    "model_deterring_not_selected": int(m.get("model_deterring_not_selected", 0)),
                    "model_deterring_accepted": int(m.get("model_deterring_accepted", 0)),
                    "model_deterring_rejected_budget": int(m.get("model_deterring_rejected_budget", 0)),
                    "model_deterring_rejected_risk": int(m.get("model_deterring_rejected_risk", 0)),
                    "model_deterring_rejected_support": int(m.get("model_deterring_rejected_support", 0)),
                    "model_deterring_rejected_persistence": int(m.get("model_deterring_rejected_persistence", 0)),
                    "model_deterring_rejected_repeat_no_new_support": int(m.get("model_deterring_rejected_repeat_no_new_support", 0)),
                    "model_deterring_rejected_eta": int(m.get("model_deterring_rejected_eta", 0)),
                    "model_deterring_rejected_busy": int(m.get("model_deterring_rejected_busy", 0)),
                    "model_deterring_rejected_margin": int(m.get("model_deterring_rejected_margin", 0)),
                    "preventive_policy": str(m.get("preventive_policy", "")),
                    "preventive_policy_source": str(m.get("preventive_policy_source", "")),
                    "selective_preventive_enabled": int(m.get("selective_preventive_enabled", 0)),
                    "use_frozen_calibration": int(m.get("use_frozen_calibration", 0)),
                    "selected_calibration_config_id": str(m.get("selected_calibration_config_id", "")),
                    "selected_calibration_source": str(m.get("selected_calibration_source", "")),
                    "calibrated_model_alpha_inhib": float(m.get("calibrated_model_alpha_inhib", float("nan"))),
                    "calibrated_model_omega_inhib": float(m.get("calibrated_model_omega_inhib", float("nan"))),
                    "calibrated_model_mu_base": float(m.get("calibrated_model_mu_base", float("nan"))),
                    "calibrated_model_bg_ema": float(m.get("calibrated_model_bg_ema", float("nan"))),
                    "selected_calibration_rank": float(m.get("selected_calibration_rank", float("nan"))),
                    "selected_calibration_proposed_field_logloss_mean": float(
                        m.get("selected_calibration_proposed_field_logloss_mean", float("nan"))
                    ),
                    "selected_calibration_proposed_field_brier_mean": float(
                        m.get("selected_calibration_proposed_field_brier_mean", float("nan"))
                    ),
                    "selected_calibration_proposed_nll_mean": float(
                        m.get("selected_calibration_proposed_nll_mean", float("nan"))
                    ),
                    "selected_calibration_nll_improvement_pct_mean": float(
                        m.get("selected_calibration_nll_improvement_pct_mean", float("nan"))
                    ),
                    "model_deterring_gate_policy": str(m.get("model_deterring_gate_policy", "")),
                    "model_deterring_pass_sprt": int(m.get("model_deterring_pass_sprt", 0)),
                    "model_deterring_rejected_sprt_pending": int(m.get("model_deterring_rejected_sprt_pending", 0)),
                    "model_deterring_rejected_sprt_negative": int(m.get("model_deterring_rejected_sprt_negative", 0)),
                    "model_deterring_rejected_sprt_margin": int(m.get("model_deterring_rejected_sprt_margin", 0)),
                    "model_deterring_pass_chance": int(m.get("model_deterring_pass_chance", 0)),
                    "model_deterring_rejected_chance": int(m.get("model_deterring_rejected_chance", 0)),
                    "model_deterring_pass_utility_ratio": int(m.get("model_deterring_pass_utility_ratio", 0)),
                    "model_deterring_rejected_utility_ratio": int(m.get("model_deterring_rejected_utility_ratio", 0)),
                    "model_deterring_pass_selection_weight": int(m.get("model_deterring_pass_selection_weight", 0)),
                    "model_deterring_rejected_selection_weight": int(m.get("model_deterring_rejected_selection_weight", 0)),
                    "model_deterring_pass_capacity": int(m.get("model_deterring_pass_capacity", 0)),
                    "model_deterring_capacity_pending": int(m.get("model_deterring_capacity_pending", 0)),
                    "model_deterring_rejected_capacity": int(m.get("model_deterring_rejected_capacity", 0)),
                    "model_deterring_llr_mean": float(m.get("model_deterring_llr_mean", float("nan"))),
                    "model_deterring_llr_max": float(m.get("model_deterring_llr_max", float("nan"))),
                    "model_deterring_llr_p50": float(m.get("model_deterring_llr_p50", float("nan"))),
                    "model_deterring_llr_p75": float(m.get("model_deterring_llr_p75", float("nan"))),
                    "model_deterring_llr_p90": float(m.get("model_deterring_llr_p90", float("nan"))),
                    "model_deterring_p_event_mean": float(m.get("model_deterring_p_event_mean", float("nan"))),
                    "model_deterring_deltaJ_per_cost_mean": float(m.get("model_deterring_deltaJ_per_cost_mean", float("nan"))),
                    "model_deterring_cluster_key_total": int(m.get("model_deterring_cluster_key_total", 0)),
                    "model_deterring_cluster_key_reused": int(m.get("model_deterring_cluster_key_reused", 0)),
                    "model_deterring_cluster_key_churn": int(m.get("model_deterring_cluster_key_churn", 0)),
                    "model_deterring_cluster_key_new": int(m.get("model_deterring_cluster_key_new", 0)),
                    "preventive_service_rate_per_robot_mean": float(m.get("preventive_service_rate_per_robot_mean", float("nan"))),
                    "preventive_direct_arrival_rate_per_robot_mean": float(m.get("preventive_direct_arrival_rate_per_robot_mean", float("nan"))),
                    "preventive_capacity_remaining_per_robot_mean": float(m.get("preventive_capacity_remaining_per_robot_mean", float("nan"))),
                    "planner_rejected_unassigned": int(m.get("planner_rejected_unassigned", 0)),
                    "planner_rejected_task_cap": int(m.get("planner_rejected_task_cap", 0)),
                    "planner_rejected_patrol_cap": int(m.get("planner_rejected_patrol_cap", 0)),
                    "planner_rejected_model_det_cap": int(m.get("planner_rejected_model_det_cap", 0)),
                    "planner_rejected_model_det_cycle_cap": int(m.get("planner_rejected_model_det_cycle_cap", 0)),
                    "planner_rejected_model_det_busy_primary": int(m.get("planner_rejected_model_det_busy_primary", 0)),
                    "planner_rejected_model_det_busy_fallback_quality": int(m.get("planner_rejected_model_det_busy_fallback_quality", 0)),
                    "planner_rejected_model_det_direct_conflict": int(m.get("planner_rejected_model_det_direct_conflict", 0)),
                    "planner_accepted_model_det_idle_primary": int(m.get("planner_accepted_model_det_idle_primary", 0)),
                    "planner_accepted_model_det_busy_primary": int(m.get("planner_accepted_model_det_busy_primary", 0)),
                    "planner_replaced_patrol": int(m.get("planner_replaced_patrol", 0)),
                    "truth_candidate_events": int(m.get("truth_candidate_events", 0)),
                    "truth_accepted_events": int(m.get("truth_accepted_events", 0)),
                    "truth_suppressed_events": int(m.get("truth_suppressed_events", 0)),
                    "truth_suppression_rate": float(m.get("truth_suppression_rate", float("nan"))),
                    "truth_suppression_effect_mean": float(m.get("truth_suppression_effect_mean", float("nan"))),
                    "deterring_actions_completed_total": int(m.get("deterring_actions_completed_total", 0)),
                    "deterring_actions_completed_direct_detection": int(m.get("deterring_actions_completed_direct_detection", 0)),
                    "deterring_actions_completed_model_scored": int(m.get("deterring_actions_completed_model_scored", 0)),
                    "deterring_action_precision": float(m.get("deterring_action_precision", float("nan"))),
                    "deterring_action_precision_direct_detection": float(m.get("deterring_action_precision_direct_detection", float("nan"))),
                    "deterring_action_precision_model_scored": float(m.get("deterring_action_precision_model_scored", float("nan"))),
                    "suppression_per_deterring_action": float(m.get("suppression_per_deterring_action", float("nan"))),
                    "suppression_per_direct_deterring_action": float(m.get("suppression_per_direct_deterring_action", float("nan"))),
                    "suppression_per_model_deterring_action": float(m.get("suppression_per_model_deterring_action", float("nan"))),
                    "model_vs_direct_suppression_yield_ratio": float(m.get("model_vs_direct_suppression_yield_ratio", float("nan"))),
                    "fleet_task_engagement_fraction_so_far": float(m.get("fleet_task_engagement_fraction_so_far", float("nan"))),
                    "fleet_moving_fraction_so_far": float(m.get("fleet_moving_fraction_so_far", float("nan"))),
                    "fleet_idle_no_task_fraction_so_far": float(m.get("fleet_idle_no_task_fraction_so_far", float("nan"))),
                    "robot_task_utilization_mean": float(m.get("robot_task_utilization_mean", float("nan"))),
                    "robot_idle_fraction_mean": float(m.get("robot_idle_fraction_mean", float("nan"))),
                    "robot_moving_with_task_fraction_mean": float(m.get("robot_moving_with_task_fraction_mean", float("nan"))),
                    "robot_longest_idle_s_max": float(m.get("robot_longest_idle_s_max", float("nan"))),
                    "robot_tail_idle_s_max": float(m.get("robot_tail_idle_s_max", float("nan"))),
                    "robots_zero_distance_count": int(m.get("robots_zero_distance_count", 0)),
                    "stale_goal_clears": int(m.get("stale_goal_clears", 0)),
                    "direct_detection_task_refresh_active": int(m.get("direct_detection_task_refresh_active", 0)),
                    "direct_detection_task_refresh_skipped_unassigned": int(m.get("direct_detection_task_refresh_skipped_unassigned", 0)),
                    "direct_detection_task_refresh_skipped_eta": int(m.get("direct_detection_task_refresh_skipped_eta", 0)),
                    "direct_detection_task_cluster_groups": int(m.get("direct_detection_task_cluster_groups", 0)),
                    "direct_detection_task_cluster_merged": int(m.get("direct_detection_task_cluster_merged", 0)),
                    "direct_detection_task_response_matches": int(m.get("direct_detection_task_response_matches", 0)),
                }
            )
    return rows


def _run_one_experiment(job):
    # Worker-side headless mode.
    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    exp_tag = job["exp_tag"]
    scenario_id = job["scenario_id"]
    tune_id = job["tune_id"]
    time_horizon_h = float(job["time_horizon_h"])
    num_runs = int(job["num_runs"])
    seed_start = int(job["seed_start"])
    run_kwargs = deepcopy(job["run_kwargs"])
    started = time.time()

    result = ds.run_baseline_suite(
        num_runs=num_runs,
        seed_start=seed_start,
        report_each_run=False,
        csv_path=None,
        collect_time_metrics=True,
        time_metrics_period_s=float(job["time_metrics_period_s"]),
        proposed_enable_model_scored_deterring=bool(job.get("tune_proposed_enable_model_scored_deterring", 1)),
        proposed_enable_intervention_feedback=bool(job.get("tune_proposed_enable_intervention_feedback", 1)),
        proposed_preventive_policy=(job.get("proposed_preventive_policy") or None),
        use_frozen_calibration=bool(job.get("use_frozen_calibration", False)),
        calibration_ranking_path=(job.get("calibration_ranking_path") or None),
        calibration_manifest_path=(job.get("calibration_manifest_path") or None),
        calibration_config_id=(job.get("calibration_config_id") or None),
        **run_kwargs,
    )

    cmp_df = result["comparison"].copy()
    cmp_df.insert(0, "exp_id", exp_tag)
    cmp_df.insert(1, "scenario_id", scenario_id)
    cmp_df.insert(2, "tune_id", tune_id)
    cmp_df.insert(3, "time_horizon_h", time_horizon_h)
    cmp_df["tune_beta_scale"] = float(job["tune_beta_scale"])
    cmp_df["tune_cost_scale"] = float(job["tune_cost_scale"])
    cmp_df["tune_det_window_s"] = float(job["tune_det_window_s"])
    cmp_df["tune_risk_threshold"] = float(job["tune_risk_threshold"])
    cmp_df["tune_risk_scale"] = float(job["tune_risk_scale"])
    cmp_df["tune_budget_per_hr"] = int(job["tune_budget_per_hr"])
    cmp_df["tune_min_recent_points"] = int(job["tune_min_recent_points"])
    cmp_df["tune_min_persistence_replans"] = int(job["tune_min_persistence_replans"])
    cmp_df["tune_score_margin"] = float(job["tune_score_margin"])
    cmp_df["tune_repeat_window_s"] = float(job["tune_repeat_window_s"])
    cmp_df["tune_repeat_radius_m"] = float(job["tune_repeat_radius_m"])
    cmp_df["tune_max_eta_s"] = float(job["tune_max_eta_s"])
    cmp_df["tune_busy_min_support_override"] = int(job["tune_busy_min_support_override"])
    cmp_df["tune_busy_risk_override"] = float(job["tune_busy_risk_override"])
    cmp_df["tune_max_active_tasks_per_robot"] = int(job["tune_max_active_tasks_per_robot"])
    cmp_df["tune_max_active_patrolling_per_robot"] = int(job["tune_max_active_patrolling_per_robot"])
    cmp_df["tune_max_active_model_deterring_per_robot"] = int(job["tune_max_active_model_deterring_per_robot"])
    cmp_df["tune_preempt_deterring_goals"] = int(job["tune_preempt_deterring_goals"])
    cmp_df["tune_preempt_direct_detection_goals"] = int(job["tune_preempt_direct_detection_goals"])
    cmp_df["tune_preempt_model_scored_goals"] = int(job["tune_preempt_model_scored_goals"])
    cmp_df["tune_intervention_boundary_min_interval_s"] = float(job["tune_intervention_boundary_min_interval_s"])
    cmp_df["tune_intervention_boundary_spatial_quant_m"] = float(job["tune_intervention_boundary_spatial_quant_m"])
    cmp_df["tune_intervention_boundary_min_weight"] = float(job["tune_intervention_boundary_min_weight"])
    cmp_df["tune_assigner_w_load"] = float(job["tune_assigner_w_load"])
    cmp_df["tune_gate_policy"] = str(job["tune_gate_policy"])
    cmp_df["tune_patrol_hotspot_filter_mode"] = str(job["tune_patrol_hotspot_filter_mode"])
    cmp_df["tune_patrol_hotspot_score_percentile"] = float(job["tune_patrol_hotspot_score_percentile"])
    cmp_df["tune_patrol_hotspot_keep_top_k"] = str(job["tune_patrol_hotspot_keep_top_k"])
    cmp_df["tune_patrol_feedback_inhibition_retention"] = float(
        job.get("tune_patrol_feedback_inhibition_retention", float("nan"))
    )
    cmp_df["tune_model_deterring_sprt_alpha"] = float(job["tune_model_deterring_sprt_alpha"])
    cmp_df["tune_model_deterring_sprt_beta"] = float(job["tune_model_deterring_sprt_beta"])
    cmp_df["tune_model_deterring_sprt_patch_radius_m"] = float(job["tune_model_deterring_sprt_patch_radius_m"])
    cmp_df["tune_model_deterring_min_sprt_margin"] = float(job.get("tune_model_deterring_min_sprt_margin", float("nan")))
    cmp_df["tune_model_deterring_chance_threshold"] = float(job["tune_model_deterring_chance_threshold"])
    cmp_df["tune_model_deterring_min_deltaJ_per_cost"] = float(job["tune_model_deterring_min_deltaJ_per_cost"])
    cmp_df["tune_model_deterring_min_selection_weight"] = float(job.get("tune_model_deterring_min_selection_weight", float("nan")))
    cmp_df["tune_model_deterring_capacity_rho_max"] = float(job["tune_model_deterring_capacity_rho_max"])
    cmp_df["tune_model_deterring_global_admission_cap_per_cycle"] = int(job.get("tune_model_deterring_global_admission_cap_per_cycle", 0))
    cmp_df["tune_model_deterring_require_idle_robot_for_admission"] = int(job.get("tune_model_deterring_require_idle_robot_for_admission", 0))
    cmp_df["tune_model_deterring_prefer_idle_robots_for_assignment"] = int(job.get("tune_model_deterring_prefer_idle_robots_for_assignment", 0))
    cmp_df["tune_model_deterring_busy_fallback_p_event_min"] = float(job.get("tune_model_deterring_busy_fallback_p_event_min", float("nan")))
    cmp_df["tune_model_deterring_busy_fallback_deltaJ_per_cost_min"] = float(job.get("tune_model_deterring_busy_fallback_deltaJ_per_cost_min", float("nan")))
    cmp_df["tune_model_deterring_busy_fallback_eta_s_max"] = float(job.get("tune_model_deterring_busy_fallback_eta_s_max", float("nan")))
    cmp_df["tune_protect_direct_detection_from_model_deterring"] = int(job.get("tune_protect_direct_detection_from_model_deterring", 0))
    cmp_df["tune_proposed_enable_model_scored_deterring"] = int(job.get("tune_proposed_enable_model_scored_deterring", 1))
    cmp_df["tune_proposed_enable_intervention_feedback"] = int(job.get("tune_proposed_enable_intervention_feedback", 1))
    cmp_df["tune_enable_direct_detection_task_clustering"] = int(job.get("tune_enable_direct_detection_task_clustering", 1))
    cmp_df["tune_direct_detection_task_cluster_radius_m"] = float(
        job.get("tune_direct_detection_task_cluster_radius_m", float("nan"))
    )
    cmp_df["tune_direct_detection_task_cluster_window_s"] = float(
        job.get("tune_direct_detection_task_cluster_window_s", float("nan"))
    )
    cmp_df["tune_direct_detection_task_active_refresh_radius_m"] = float(
        job.get("tune_direct_detection_task_active_refresh_radius_m", float("nan"))
    )
    cmp_df["tune_direct_detection_task_active_refresh_window_s"] = float(
        job.get("tune_direct_detection_task_active_refresh_window_s", float("nan"))
    )
    cmp_df["tune_direct_detection_task_queued_cluster_radius_m"] = float(
        job.get("tune_direct_detection_task_queued_cluster_radius_m", float("nan"))
    )
    cmp_df["tune_direct_detection_task_queued_cluster_window_s"] = float(
        job.get("tune_direct_detection_task_queued_cluster_window_s", float("nan"))
    )
    cmp_df["tune_alpha_inhib"] = float(job.get("tune_alpha_inhib", float("nan")))
    cmp_df["tune_omega_inhib"] = float(job.get("tune_omega_inhib", float("nan")))
    cmp_df["tune_enable_winner_profile"] = int(job.get("tune_enable_winner_profile", 0))
    cmp_df["tune_winner_profile_id"] = str(job.get("tune_winner_profile_id", "F1"))

    run_rows = _flatten_run_metrics(result, seed_start, exp_tag, scenario_id, tune_id, time_horizon_h)
    time_df = result.get("comparison_over_time", pd.DataFrame()).copy()
    if not time_df.empty:
        time_df.insert(0, "exp_id", exp_tag)
        time_df.insert(1, "scenario_id", scenario_id)
        time_df.insert(2, "tune_id", tune_id)
        time_df.insert(3, "time_horizon_h", time_horizon_h)
    manifest_row = {
        "exp_id": exp_tag,
        "scenario_id": scenario_id,
        "tune_id": tune_id,
        "num_runs": num_runs,
        "seed_start": seed_start,
        "time_horizon_h": time_horizon_h,
        "planner_profile": str(run_kwargs.get("planner_profile", "")),
        "proposed_preventive_policy": str(job.get("proposed_preventive_policy", "")),
        "use_frozen_calibration": int(bool(job.get("use_frozen_calibration", False))),
        "calibration_ranking_path": str(job.get("calibration_ranking_path", "")),
        "calibration_manifest_path": str(job.get("calibration_manifest_path", "")),
        "calibration_config_id": str(job.get("calibration_config_id", "")),
        "params": str(run_kwargs),
        "tune_enable_winner_profile": int(job.get("tune_enable_winner_profile", 0)),
        "tune_winner_profile_id": str(job.get("tune_winner_profile_id", "F1")),
        "wall_s": float(time.time() - started),
    }

    return {
        "exp_tag": exp_tag,
        "comparison_records": cmp_df.to_dict(orient="records"),
        "run_rows": run_rows,
        "time_rows": time_df.to_dict(orient="records") if not time_df.empty else [],
        "manifest_row": manifest_row,
    }


def _build_grids(profile: str, tune_preset: str = "full", scenario_scope: str = "all"):
    scenario_grid = [
        {
            "scenario_id": "S1_low_pressure_short_range",
            "mu_true": 7.5e-7,
            "alpha_true": 0.20,
            "omega_true": 700.0,
            "sigma_true": 10.0,
            "beta_true": 0.30,
            "detect_range_m": 25.0,
            "row_gain": 1.2,
            "edge_gain": 0.5,
        },
        {
            "scenario_id": "S2_nominal",
            "mu_true": 1.0e-6,
            "alpha_true": 0.30,
            "omega_true": 600.0,
            "sigma_true": 12.0,
            "beta_true": 0.25,
            "detect_range_m": 30.0,
            "row_gain": 1.5,
            "edge_gain": 0.6,
        },
        {
            "scenario_id": "S3_high_pressure_long_range",
            "mu_true": 1.5e-6,
            "alpha_true": 0.45,
            "omega_true": 500.0,
            "sigma_true": 14.0,
            "beta_true": 0.22,
            "detect_range_m": 35.0,
            "row_gain": 1.8,
            "edge_gain": 0.8,
        },
    ]

    if profile == "fast":
        prio_list = [1.8, 2.2]
        beta_list = [0.90, 1.10]
        cost_list = [1.0]
        replan_list = [60.0]
        det_window_list = [60.0, 120.0]
        risk_thr_list = [0.30, 0.45]
        budget_list = [2, 4]
        if scenario_scope == "all":
            scenario_grid = scenario_grid[:2]
    else:
        prio_list = [1.8, 2.2]
        beta_list = [0.85, 1.00, 1.15]
        cost_list = [0.9, 1.0]
        replan_list = [45.0, 60.0]
        det_window_list = [60.0, 120.0]
        risk_thr_list = [0.25, 0.40, 0.55]
        budget_list = [2, 4, 6]

    if scenario_scope == "s23":
        scenario_grid = [s for s in scenario_grid if s["scenario_id"] in {"S2_nominal", "S3_high_pressure_long_range"}]
    elif scenario_scope == "s2":
        scenario_grid = [s for s in scenario_grid if s["scenario_id"] == "S2_nominal"]
    elif scenario_scope == "s3":
        scenario_grid = [s for s in scenario_grid if s["scenario_id"] == "S3_high_pressure_long_range"]

    if tune_preset == "diagnostic_like":
        # Mirror diagnostic_compare_systems.py planner/task settings so results are directly comparable.
        # Scenario truth parameters (mu/alpha/omega/sigma/beta) still come from scenario_grid.
        tune_grid = [
            {
                "tune_id": "D01",
                "prio_deterring": 2.0,
                "prio_patrolling": 0.2,
                "assigner_w_load": 0.8,
                "task_replan_period_s": 45.0,
                "model_deterring_window_s": 90.0,
                "model_deterring_risk_threshold": 0.35,
                "model_deterring_risk_scale": 1.0e-4,
                "model_deterring_budget_per_robot_per_hr": 4,
                "model_deterring_min_recent_points": 1,
                "model_deterring_field_threshold": None,
                "model_deterring_min_persistence_replans": 2,
                "model_deterring_persistence_max_gap_s": 120.0,
                "model_deterring_score_margin": 0.05,
                "model_deterring_repeat_block_window_s": 120.0,
                "model_deterring_repeat_block_radius_m": 25.0,
                "model_deterring_max_eta_s": 120.0,
                "model_deterring_busy_min_support_override": 1,
                "model_deterring_busy_risk_override": 0.20,
                "max_active_tasks_per_robot": 4,
                "max_active_patrolling_per_robot": 2,
                "max_active_model_deterring_per_robot": 1,
                "preempt_deterring_goals": True,
                "preempt_direct_detection_goals": True,
                "preempt_model_scored_goals": False,
                "intervention_boundary_min_interval_s": 60.0,
                "intervention_boundary_spatial_quant_m": 20.0,
                "intervention_boundary_min_weight": 0.40,
                # Traceable tune metadata used downstream.
                "tune_beta_scale": 1.0,
                "tune_cost_scale": 1.0,
                "tune_det_window_s": 90.0,
                "tune_risk_threshold": 0.35,
                "tune_risk_scale": 1.0e-4,
                "tune_budget_per_hr": 4,
                "tune_min_recent_points": 1,
                "tune_min_persistence_replans": 2,
                "tune_score_margin": 0.05,
                "tune_repeat_window_s": 120.0,
                "tune_repeat_radius_m": 25.0,
                "tune_max_eta_s": 120.0,
                "tune_busy_min_support_override": 1,
                "tune_busy_risk_override": 0.20,
                "tune_max_active_tasks_per_robot": 4,
                "tune_max_active_patrolling_per_robot": 2,
                "tune_max_active_model_deterring_per_robot": 1,
                "tune_preempt_deterring_goals": 1,
                "tune_preempt_direct_detection_goals": 1,
                "tune_preempt_model_scored_goals": 0,
                "tune_intervention_boundary_min_interval_s": 60.0,
                "tune_intervention_boundary_spatial_quant_m": 20.0,
                "tune_intervention_boundary_min_weight": 0.40,
                "tune_assigner_w_load": 0.8,
            }
        ]
        return scenario_grid, tune_grid

    if tune_preset == "planner_tune":
        # Hold core IA/scoring controls fixed, vary planner/dispatch knobs.
        planner_grid = [
            ("P01", 4, 2, 1, True, 0.80, 0.05),
            ("P02", 6, 3, 1, True, 0.80, 0.05),
            ("P03", 6, 3, 2, True, 0.80, 0.05),
            ("P04", 8, 4, 2, True, 0.80, 0.05),
            ("P05", 6, 3, 2, True, 0.60, 0.05),
            ("P06", 6, 3, 2, True, 0.40, 0.05),
            ("P07", 6, 3, 2, True, 0.60, 0.10),
            ("P08", 6, 3, 2, False, 0.60, 0.05),
        ]
        tune_grid = []
        for (tid, max_tasks, max_patrol, max_model_det, preempt, w_load, margin) in planner_grid:
            tune_grid.append(
                {
                    "tune_id": tid,
                    "prio_deterring": 2.4,
                    "prio_patrolling": 0.25,
                    "assigner_w_load": float(w_load),
                    "task_replan_period_s": 45.0,
                    "deterring_modes": _mode_pack(scale_beta=1.55, scale_cost=1.0),
                    "model_deterring_window_s": 120.0,
                    "model_deterring_risk_threshold": 0.55,
                    "model_deterring_risk_scale": 1.0e-4,
                    "model_deterring_budget_per_robot_per_hr": 3,
                    "model_deterring_min_recent_points": 2,
                    "model_deterring_field_threshold": None,
                    "model_deterring_min_persistence_replans": 2,
                    "model_deterring_persistence_max_gap_s": 120.0,
                    "model_deterring_score_margin": float(margin),
                    "model_deterring_repeat_block_window_s": 120.0,
                    "model_deterring_repeat_block_radius_m": 25.0,
                    "model_deterring_max_eta_s": 120.0,
                    "model_deterring_busy_min_support_override": 1,
                    "model_deterring_busy_risk_override": 0.20,
                    "max_active_tasks_per_robot": int(max_tasks),
                    "max_active_patrolling_per_robot": int(max_patrol),
                    "max_active_model_deterring_per_robot": int(max_model_det),
                    "preempt_deterring_goals": bool(preempt),
                    "tune_beta_scale": 1.55,
                    "tune_cost_scale": 1.0,
                    "tune_det_window_s": 120.0,
                    "tune_risk_threshold": 0.55,
                    "tune_risk_scale": 1.0e-4,
                    "tune_budget_per_hr": 3,
                    "tune_min_recent_points": 2,
                    "tune_min_persistence_replans": 2,
                    "tune_score_margin": float(margin),
                    "tune_repeat_window_s": 120.0,
                    "tune_repeat_radius_m": 25.0,
                    "tune_max_eta_s": 120.0,
                    "tune_busy_min_support_override": 1,
                    "tune_busy_risk_override": 0.20,
                    "tune_max_active_tasks_per_robot": int(max_tasks),
                    "tune_max_active_patrolling_per_robot": int(max_patrol),
                    "tune_max_active_model_deterring_per_robot": int(max_model_det),
                    "tune_preempt_deterring_goals": int(bool(preempt)),
                    "tune_assigner_w_load": float(w_load),
                }
            )
        return scenario_grid, tune_grid

    if tune_preset == "gate_refine":
        # Stage-2 production gate refinement:
        # hold the working SPRT configuration fixed and sweep the downstream
        # chance / utility / capacity controls that now dominate admissions.
        gate_grid = list(product([0.10, 0.15, 0.20], [1.0e5, 1.5e5, 2.0e5], [0.75, 0.85, 0.95]))
        tune_grid = []
        for i, (chance_thr, min_ratio, capacity_rho) in enumerate(gate_grid, start=1):
            tune_grid.append(
                {
                    "tune_id": f"G{i:02d}",
                    "prio_deterring": 2.0,
                    "prio_patrolling": 0.25,
                    "assigner_w_load": 0.8,
                    "task_replan_period_s": 60.0,
                    "patrol_hotspot_filter_mode": "percentile",
                    "patrol_hotspot_score_percentile": 97.0,
                    "patrol_hotspot_keep_top_k": None,
                    "deterring_modes": _mode_pack(scale_beta=1.0, scale_cost=1.0),
                    "model_deterring_window_s": 120.0,
                    "model_deterring_gate_policy": "sprt_capacity",
                    "model_deterring_sprt_alpha": 0.25,
                    "model_deterring_sprt_beta": 0.40,
                    "model_deterring_sprt_patch_radius_m": 30.0,
                    "model_deterring_chance_threshold": float(chance_thr),
                    "model_deterring_min_deltaJ_per_cost": float(min_ratio),
                    "model_deterring_capacity_rho_max": float(capacity_rho),
                    "model_deterring_capacity_history_window_s": 3600.0,
                    "model_deterring_capacity_min_completed_tasks": 3,
                    "model_deterring_capacity_fallback_budget_per_hr": 4,
                    "model_deterring_risk_threshold": 0.35,
                    "model_deterring_risk_scale": 1.0e-4,
                    "model_deterring_budget_per_robot_per_hr": 4,
                    "model_deterring_min_recent_points": 1,
                    "model_deterring_field_threshold": None,
                    "model_deterring_min_persistence_replans": 2,
                    "model_deterring_persistence_max_gap_s": 120.0,
                    "model_deterring_score_margin": 0.05,
                    "model_deterring_repeat_block_window_s": 120.0,
                    "model_deterring_repeat_block_radius_m": 25.0,
                    "model_deterring_max_eta_s": 120.0,
                    "model_deterring_busy_min_support_override": 1,
                    "model_deterring_busy_risk_override": 0.20,
                    "max_active_tasks_per_robot": 4,
                    "max_active_patrolling_per_robot": 2,
                    "max_active_model_deterring_per_robot": 1,
                    "preempt_deterring_goals": True,
                    "preempt_direct_detection_goals": True,
                    "preempt_model_scored_goals": False,
                    "tune_beta_scale": 1.0,
                    "tune_cost_scale": 1.0,
                    "tune_det_window_s": 120.0,
                    "tune_risk_threshold": 0.35,
                    "tune_risk_scale": 1.0e-4,
                    "tune_budget_per_hr": 4,
                    "tune_min_recent_points": 1,
                    "tune_min_persistence_replans": 2,
                    "tune_score_margin": 0.05,
                    "tune_repeat_window_s": 120.0,
                    "tune_repeat_radius_m": 25.0,
                    "tune_max_eta_s": 120.0,
                    "tune_busy_min_support_override": 1,
                    "tune_busy_risk_override": 0.20,
                    "tune_max_active_tasks_per_robot": 4,
                    "tune_max_active_patrolling_per_robot": 2,
                    "tune_max_active_model_deterring_per_robot": 1,
                    "tune_preempt_deterring_goals": 1,
                    "tune_preempt_direct_detection_goals": 1,
                    "tune_preempt_model_scored_goals": 0,
                    "tune_intervention_boundary_min_interval_s": 60.0,
                    "tune_intervention_boundary_spatial_quant_m": 20.0,
                    "tune_intervention_boundary_min_weight": 0.35,
                    "tune_assigner_w_load": 0.8,
                    "tune_gate_policy": "sprt_capacity",
                    "tune_patrol_hotspot_filter_mode": "percentile",
                    "tune_patrol_hotspot_score_percentile": 97.0,
                    "tune_patrol_hotspot_keep_top_k": "",
                    "tune_model_deterring_sprt_alpha": 0.25,
                    "tune_model_deterring_sprt_beta": 0.40,
                    "tune_model_deterring_sprt_patch_radius_m": 30.0,
                    "tune_model_deterring_chance_threshold": float(chance_thr),
                    "tune_model_deterring_min_deltaJ_per_cost": float(min_ratio),
                    "tune_model_deterring_capacity_rho_max": float(capacity_rho),
                }
            )
        return scenario_grid, tune_grid

    if tune_preset == "gate_selective":
        # Stage-3 production gate refinement:
        # keep the working SPRT configuration fixed and tune the selectivity
        # of admitted preventive actions via chance-of-event and patrol margin.
        gate_grid = list(product([0.25, 0.30, 0.35, 0.40], [0.10, 0.20, 0.30]))
        tune_grid = []
        for i, (chance_thr, score_margin) in enumerate(gate_grid, start=1):
            tune_grid.append(
                {
                    "tune_id": f"GS{i:02d}",
                    "prio_deterring": 2.0,
                    "prio_patrolling": 0.25,
                    "assigner_w_load": 0.8,
                    "task_replan_period_s": 60.0,
                    "patrol_hotspot_filter_mode": "percentile",
                    "patrol_hotspot_score_percentile": 97.0,
                    "patrol_hotspot_keep_top_k": None,
                    "deterring_modes": _mode_pack(scale_beta=1.0, scale_cost=1.0),
                    "model_deterring_window_s": 120.0,
                    "model_deterring_gate_policy": "sprt_capacity",
                    "model_deterring_sprt_alpha": 0.25,
                    "model_deterring_sprt_beta": 0.40,
                    "model_deterring_sprt_patch_radius_m": 30.0,
                    "model_deterring_chance_threshold": float(chance_thr),
                    "model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "model_deterring_capacity_rho_max": 0.85,
                    "model_deterring_capacity_history_window_s": 3600.0,
                    "model_deterring_capacity_min_completed_tasks": 3,
                    "model_deterring_capacity_fallback_budget_per_hr": 4,
                    "model_deterring_risk_threshold": 0.35,
                    "model_deterring_risk_scale": 1.0e-4,
                    "model_deterring_budget_per_robot_per_hr": 4,
                    "model_deterring_min_recent_points": 1,
                    "model_deterring_field_threshold": None,
                    "model_deterring_min_persistence_replans": 2,
                    "model_deterring_persistence_max_gap_s": 120.0,
                    "model_deterring_score_margin": float(score_margin),
                    "model_deterring_repeat_block_window_s": 120.0,
                    "model_deterring_repeat_block_radius_m": 25.0,
                    "model_deterring_max_eta_s": 120.0,
                    "model_deterring_busy_min_support_override": 1,
                    "model_deterring_busy_risk_override": 0.20,
                    "max_active_tasks_per_robot": 4,
                    "max_active_patrolling_per_robot": 2,
                    "max_active_model_deterring_per_robot": 1,
                    "preempt_deterring_goals": True,
                    "preempt_direct_detection_goals": True,
                    "preempt_model_scored_goals": False,
                    "tune_beta_scale": 1.0,
                    "tune_cost_scale": 1.0,
                    "tune_det_window_s": 120.0,
                    "tune_risk_threshold": 0.35,
                    "tune_risk_scale": 1.0e-4,
                    "tune_budget_per_hr": 4,
                    "tune_min_recent_points": 1,
                    "tune_min_persistence_replans": 2,
                    "tune_score_margin": float(score_margin),
                    "tune_repeat_window_s": 120.0,
                    "tune_repeat_radius_m": 25.0,
                    "tune_max_eta_s": 120.0,
                    "tune_busy_min_support_override": 1,
                    "tune_busy_risk_override": 0.20,
                    "tune_max_active_tasks_per_robot": 4,
                    "tune_max_active_patrolling_per_robot": 2,
                    "tune_max_active_model_deterring_per_robot": 1,
                    "tune_preempt_deterring_goals": 1,
                    "tune_preempt_direct_detection_goals": 1,
                    "tune_preempt_model_scored_goals": 0,
                    "tune_intervention_boundary_min_interval_s": 5.0,
                    "tune_intervention_boundary_spatial_quant_m": 8.0,
                    "tune_intervention_boundary_min_weight": 0.2,
                    "tune_assigner_w_load": 0.8,
                    "tune_gate_policy": "sprt_capacity",
                    "tune_patrol_hotspot_filter_mode": "percentile",
                    "tune_patrol_hotspot_score_percentile": 97.0,
                    "tune_patrol_hotspot_keep_top_k": "None",
                    "tune_model_deterring_sprt_alpha": 0.25,
                    "tune_model_deterring_sprt_beta": 0.40,
                    "tune_model_deterring_sprt_patch_radius_m": 30.0,
                    "tune_model_deterring_chance_threshold": float(chance_thr),
                    "tune_model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "tune_model_deterring_capacity_rho_max": 0.85,
                }
            )
        return scenario_grid, tune_grid

    if tune_preset == "gate_busy_fallback":
        # Stage-4 production gate refinement:
        # keep the working gate fixed and tune only the busy-primary fallback
        # quality thresholds for model-scored preventive tasks.
        fallback_grid = list(product([0.90, 0.95], [5.0e5, 1.0e6, 2.0e6], [1.25, 1.75]))
        tune_grid = []
        for i, (p_event_min, deltaJ_per_cost_min, eta_s_max) in enumerate(fallback_grid, start=1):
            tune_grid.append(
                {
                    "tune_id": f"GB{i:02d}",
                    "prio_deterring": 2.0,
                    "prio_patrolling": 0.25,
                    "assigner_w_load": 0.8,
                    "task_replan_period_s": 60.0,
                    "patrol_hotspot_filter_mode": "percentile",
                    "patrol_hotspot_score_percentile": 97.0,
                    "patrol_hotspot_keep_top_k": None,
                    "deterring_modes": _mode_pack(scale_beta=1.0, scale_cost=1.0),
                    "model_deterring_window_s": 120.0,
                    "model_deterring_gate_policy": "sprt_capacity",
                    "model_deterring_sprt_alpha": 0.25,
                    "model_deterring_sprt_beta": 0.40,
                    "model_deterring_sprt_patch_radius_m": 30.0,
                    "model_deterring_chance_threshold": 0.35,
                    "model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "model_deterring_capacity_rho_max": 0.85,
                    "model_deterring_capacity_history_window_s": 3600.0,
                    "model_deterring_capacity_min_completed_tasks": 3,
                    "model_deterring_capacity_fallback_budget_per_hr": 4,
                    "model_deterring_risk_threshold": 0.35,
                    "model_deterring_risk_scale": 1.0e-4,
                    "model_deterring_budget_per_robot_per_hr": 4,
                    "model_deterring_min_recent_points": 1,
                    "model_deterring_field_threshold": None,
                    "model_deterring_min_persistence_replans": 2,
                    "model_deterring_persistence_max_gap_s": 120.0,
                    "model_deterring_score_margin": 0.10,
                    "model_deterring_repeat_block_window_s": 120.0,
                    "model_deterring_repeat_block_radius_m": 25.0,
                    "model_deterring_max_eta_s": 120.0,
                    "model_deterring_busy_min_support_override": 1,
                    "model_deterring_busy_risk_override": 0.20,
                    "model_deterring_global_admission_cap_per_cycle": 1,
                    "model_deterring_require_idle_robot_for_admission": False,
                    "model_deterring_prefer_idle_robots_for_assignment": True,
                    "model_deterring_busy_fallback_p_event_min": float(p_event_min),
                    "model_deterring_busy_fallback_deltaJ_per_cost_min": float(deltaJ_per_cost_min),
                    "model_deterring_busy_fallback_eta_s_max": float(eta_s_max),
                    "protect_direct_detection_from_model_deterring": True,
                    "model_deterring_direct_conflict_radius_m": 35.0,
                    "model_deterring_direct_conflict_window_s": 120.0,
                    "max_active_tasks_per_robot": 4,
                    "max_active_patrolling_per_robot": 2,
                    "max_active_model_deterring_per_robot": 1,
                    "preempt_deterring_goals": True,
                    "preempt_direct_detection_goals": True,
                    "preempt_model_scored_goals": False,
                    "tune_beta_scale": 1.0,
                    "tune_cost_scale": 1.0,
                    "tune_det_window_s": 120.0,
                    "tune_risk_threshold": 0.35,
                    "tune_risk_scale": 1.0e-4,
                    "tune_budget_per_hr": 4,
                    "tune_min_recent_points": 1,
                    "tune_min_persistence_replans": 2,
                    "tune_score_margin": 0.10,
                    "tune_repeat_window_s": 120.0,
                    "tune_repeat_radius_m": 25.0,
                    "tune_max_eta_s": 120.0,
                    "tune_busy_min_support_override": 1,
                    "tune_busy_risk_override": 0.20,
                    "tune_max_active_tasks_per_robot": 4,
                    "tune_max_active_patrolling_per_robot": 2,
                    "tune_max_active_model_deterring_per_robot": 1,
                    "tune_preempt_deterring_goals": 1,
                    "tune_preempt_direct_detection_goals": 1,
                    "tune_preempt_model_scored_goals": 0,
                    "tune_intervention_boundary_min_interval_s": 5.0,
                    "tune_intervention_boundary_spatial_quant_m": 8.0,
                    "tune_intervention_boundary_min_weight": 0.2,
                    "tune_assigner_w_load": 0.8,
                    "tune_gate_policy": "sprt_capacity",
                    "tune_patrol_hotspot_filter_mode": "percentile",
                    "tune_patrol_hotspot_score_percentile": 97.0,
                    "tune_patrol_hotspot_keep_top_k": "None",
                    "tune_model_deterring_sprt_alpha": 0.25,
                    "tune_model_deterring_sprt_beta": 0.40,
                    "tune_model_deterring_sprt_patch_radius_m": 30.0,
                    "tune_model_deterring_chance_threshold": 0.35,
                    "tune_model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "tune_model_deterring_capacity_rho_max": 0.85,
                    "tune_model_deterring_global_admission_cap_per_cycle": 1,
                    "tune_model_deterring_require_idle_robot_for_admission": 0,
                    "tune_model_deterring_prefer_idle_robots_for_assignment": 1,
                    "tune_model_deterring_busy_fallback_p_event_min": float(p_event_min),
                    "tune_model_deterring_busy_fallback_deltaJ_per_cost_min": float(deltaJ_per_cost_min),
                    "tune_model_deterring_busy_fallback_eta_s_max": float(eta_s_max),
                    "tune_protect_direct_detection_from_model_deterring": 1,
                }
            )
        return scenario_grid, tune_grid

    if tune_preset == "gate_selection_weight":
        # Stage-5 production refinement:
        # keep the repaired gate/execution path fixed and tune only the
        # evidence-weighted preventive selection floor.
        selection_grid = [0.20, 0.24, 0.25, 0.26, 0.28, 0.30]
        tune_grid = []
        for i, min_selection_weight in enumerate(selection_grid, start=1):
            tune_grid.append(
                {
                    "tune_id": f"GW{i:02d}",
                    "prio_deterring": 2.0,
                    "prio_patrolling": 0.25,
                    "assigner_w_load": 0.8,
                    "task_replan_period_s": 60.0,
                    "patrol_hotspot_filter_mode": "percentile",
                    "patrol_hotspot_score_percentile": 97.0,
                    "patrol_hotspot_keep_top_k": None,
                    "deterring_modes": _mode_pack(scale_beta=1.0, scale_cost=1.0),
                    "model_deterring_window_s": 120.0,
                    "model_deterring_gate_policy": "sprt_capacity",
                    "model_deterring_sprt_alpha": 0.25,
                    "model_deterring_sprt_beta": 0.40,
                    "model_deterring_sprt_patch_radius_m": 30.0,
                    "model_deterring_chance_threshold": 0.35,
                    "model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "model_deterring_min_selection_weight": float(min_selection_weight),
                    "model_deterring_capacity_rho_max": 0.85,
                    "model_deterring_capacity_history_window_s": 3600.0,
                    "model_deterring_capacity_min_completed_tasks": 3,
                    "model_deterring_capacity_fallback_budget_per_hr": 4,
                    "model_deterring_risk_threshold": 0.35,
                    "model_deterring_risk_scale": 1.0e-4,
                    "model_deterring_budget_per_robot_per_hr": 4,
                    "model_deterring_min_recent_points": 1,
                    "model_deterring_field_threshold": None,
                    "model_deterring_min_persistence_replans": 2,
                    "model_deterring_persistence_max_gap_s": 120.0,
                    "model_deterring_score_margin": 0.10,
                    "model_deterring_repeat_block_window_s": 120.0,
                    "model_deterring_repeat_block_radius_m": 25.0,
                    "model_deterring_max_eta_s": 120.0,
                    "model_deterring_busy_min_support_override": 1,
                    "model_deterring_busy_risk_override": 0.20,
                    "model_deterring_global_admission_cap_per_cycle": 1,
                    "model_deterring_require_idle_robot_for_admission": False,
                    "model_deterring_prefer_idle_robots_for_assignment": True,
                    "model_deterring_busy_fallback_p_event_min": 0.90,
                    "model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "model_deterring_busy_fallback_eta_s_max": 1.25,
                    "protect_direct_detection_from_model_deterring": True,
                    "model_deterring_direct_conflict_radius_m": 35.0,
                    "model_deterring_direct_conflict_window_s": 120.0,
                    "max_active_tasks_per_robot": 4,
                    "max_active_patrolling_per_robot": 2,
                    "max_active_model_deterring_per_robot": 1,
                    "preempt_deterring_goals": True,
                    "preempt_direct_detection_goals": True,
                    "preempt_model_scored_goals": False,
                    "tune_beta_scale": 1.0,
                    "tune_cost_scale": 1.0,
                    "tune_det_window_s": 120.0,
                    "tune_risk_threshold": 0.35,
                    "tune_risk_scale": 1.0e-4,
                    "tune_budget_per_hr": 4,
                    "tune_min_recent_points": 1,
                    "tune_min_persistence_replans": 2,
                    "tune_score_margin": 0.10,
                    "tune_repeat_window_s": 120.0,
                    "tune_repeat_radius_m": 25.0,
                    "tune_max_eta_s": 120.0,
                    "tune_busy_min_support_override": 1,
                    "tune_busy_risk_override": 0.20,
                    "tune_max_active_tasks_per_robot": 4,
                    "tune_max_active_patrolling_per_robot": 2,
                    "tune_max_active_model_deterring_per_robot": 1,
                    "tune_preempt_deterring_goals": 1,
                    "tune_preempt_direct_detection_goals": 1,
                    "tune_preempt_model_scored_goals": 0,
                    "tune_intervention_boundary_min_interval_s": 5.0,
                    "tune_intervention_boundary_spatial_quant_m": 8.0,
                    "tune_intervention_boundary_min_weight": 0.2,
                    "tune_assigner_w_load": 0.8,
                    "tune_gate_policy": "sprt_capacity",
                    "tune_patrol_hotspot_filter_mode": "percentile",
                    "tune_patrol_hotspot_score_percentile": 97.0,
                    "tune_patrol_hotspot_keep_top_k": "None",
                    "tune_model_deterring_sprt_alpha": 0.25,
                    "tune_model_deterring_sprt_beta": 0.40,
                    "tune_model_deterring_sprt_patch_radius_m": 30.0,
                    "tune_model_deterring_chance_threshold": 0.35,
                    "tune_model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "tune_model_deterring_min_selection_weight": float(min_selection_weight),
                    "tune_model_deterring_capacity_rho_max": 0.85,
                    "tune_model_deterring_global_admission_cap_per_cycle": 1,
                    "tune_model_deterring_require_idle_robot_for_admission": 0,
                    "tune_model_deterring_prefer_idle_robots_for_assignment": 1,
                    "tune_model_deterring_busy_fallback_p_event_min": 0.90,
                    "tune_model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "tune_model_deterring_busy_fallback_eta_s_max": 1.25,
                    "tune_protect_direct_detection_from_model_deterring": 1,
                }
            )
        return scenario_grid, tune_grid

    if tune_preset == "gate_evidence_margin":
        # Stage-6 production refinement:
        # disable the experimental selection-weight floor and tune only the
        # extra evidence margin above the SPRT accept boundary.
        margin_grid = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25]
        tune_grid = []
        for i, sprt_margin in enumerate(margin_grid, start=1):
            tune_grid.append(
                {
                    "tune_id": f"GE{i:02d}",
                    "prio_deterring": 2.0,
                    "prio_patrolling": 0.25,
                    "assigner_w_load": 0.8,
                    "task_replan_period_s": 60.0,
                    "patrol_hotspot_filter_mode": "percentile",
                    "patrol_hotspot_score_percentile": 97.0,
                    "patrol_hotspot_keep_top_k": None,
                    "deterring_modes": _mode_pack(scale_beta=1.0, scale_cost=1.0),
                    "model_deterring_window_s": 120.0,
                    "model_deterring_gate_policy": "sprt_capacity",
                    "model_deterring_sprt_alpha": 0.25,
                    "model_deterring_sprt_beta": 0.40,
                    "model_deterring_sprt_patch_radius_m": 30.0,
                    "model_deterring_min_sprt_margin": float(sprt_margin),
                    "model_deterring_chance_threshold": 0.35,
                    "model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "model_deterring_min_selection_weight": 0.0,
                    "model_deterring_capacity_rho_max": 0.85,
                    "model_deterring_capacity_history_window_s": 3600.0,
                    "model_deterring_capacity_min_completed_tasks": 3,
                    "model_deterring_capacity_fallback_budget_per_hr": 4,
                    "model_deterring_risk_threshold": 0.35,
                    "model_deterring_risk_scale": 1.0e-4,
                    "model_deterring_budget_per_robot_per_hr": 4,
                    "model_deterring_min_recent_points": 1,
                    "model_deterring_field_threshold": None,
                    "model_deterring_min_persistence_replans": 2,
                    "model_deterring_persistence_max_gap_s": 120.0,
                    "model_deterring_score_margin": 0.10,
                    "model_deterring_repeat_block_window_s": 120.0,
                    "model_deterring_repeat_block_radius_m": 25.0,
                    "model_deterring_max_eta_s": 120.0,
                    "model_deterring_busy_min_support_override": 1,
                    "model_deterring_busy_risk_override": 0.20,
                    "model_deterring_global_admission_cap_per_cycle": 1,
                    "model_deterring_require_idle_robot_for_admission": False,
                    "model_deterring_prefer_idle_robots_for_assignment": True,
                    "model_deterring_busy_fallback_p_event_min": 0.90,
                    "model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "model_deterring_busy_fallback_eta_s_max": 1.25,
                    "protect_direct_detection_from_model_deterring": True,
                    "model_deterring_direct_conflict_radius_m": 35.0,
                    "model_deterring_direct_conflict_window_s": 120.0,
                    "max_active_tasks_per_robot": 4,
                    "max_active_patrolling_per_robot": 2,
                    "max_active_model_deterring_per_robot": 1,
                    "preempt_deterring_goals": True,
                    "preempt_direct_detection_goals": True,
                    "preempt_model_scored_goals": False,
                    "tune_beta_scale": 1.0,
                    "tune_cost_scale": 1.0,
                    "tune_det_window_s": 120.0,
                    "tune_risk_threshold": 0.35,
                    "tune_risk_scale": 1.0e-4,
                    "tune_budget_per_hr": 4,
                    "tune_min_recent_points": 1,
                    "tune_min_persistence_replans": 2,
                    "tune_score_margin": 0.10,
                    "tune_repeat_window_s": 120.0,
                    "tune_repeat_radius_m": 25.0,
                    "tune_max_eta_s": 120.0,
                    "tune_busy_min_support_override": 1,
                    "tune_busy_risk_override": 0.20,
                    "tune_max_active_tasks_per_robot": 4,
                    "tune_max_active_patrolling_per_robot": 2,
                    "tune_max_active_model_deterring_per_robot": 1,
                    "tune_preempt_deterring_goals": 1,
                    "tune_preempt_direct_detection_goals": 1,
                    "tune_preempt_model_scored_goals": 0,
                    "tune_intervention_boundary_min_interval_s": 5.0,
                    "tune_intervention_boundary_spatial_quant_m": 8.0,
                    "tune_intervention_boundary_min_weight": 0.2,
                    "tune_assigner_w_load": 0.8,
                    "tune_gate_policy": "sprt_capacity",
                    "tune_patrol_hotspot_filter_mode": "percentile",
                    "tune_patrol_hotspot_score_percentile": 97.0,
                    "tune_patrol_hotspot_keep_top_k": "None",
                    "tune_model_deterring_sprt_alpha": 0.25,
                    "tune_model_deterring_sprt_beta": 0.40,
                    "tune_model_deterring_sprt_patch_radius_m": 30.0,
                    "tune_model_deterring_min_sprt_margin": float(sprt_margin),
                    "tune_model_deterring_chance_threshold": 0.35,
                    "tune_model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "tune_model_deterring_min_selection_weight": 0.0,
                    "tune_model_deterring_capacity_rho_max": 0.85,
                    "tune_model_deterring_global_admission_cap_per_cycle": 1,
                    "tune_model_deterring_require_idle_robot_for_admission": 0,
                    "tune_model_deterring_prefer_idle_robots_for_assignment": 1,
                    "tune_model_deterring_busy_fallback_p_event_min": 0.90,
                    "tune_model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "tune_model_deterring_busy_fallback_eta_s_max": 1.25,
                    "tune_protect_direct_detection_from_model_deterring": 1,
                }
            )
        return scenario_grid, tune_grid

    if tune_preset == "model_deterring_ablation":
        tune_grid = []
        for tune_id, enable_model_det in [("MA01", 1), ("MA02", 0)]:
            tune_grid.append(
                {
                    "tune_id": tune_id,
                    "prio_deterring": 2.0,
                    "prio_patrolling": 0.25,
                    "assigner_w_load": 0.8,
                    "task_replan_period_s": 60.0,
                    "patrol_hotspot_filter_mode": "percentile",
                    "patrol_hotspot_score_percentile": 97.0,
                    "patrol_hotspot_keep_top_k": None,
                    "deterring_modes": _mode_pack(scale_beta=1.0, scale_cost=1.0),
                    "model_deterring_window_s": 120.0,
                    "model_deterring_gate_policy": "sprt_capacity",
                    "model_deterring_sprt_alpha": 0.25,
                    "model_deterring_sprt_beta": 0.40,
                    "model_deterring_sprt_patch_radius_m": 30.0,
                    "model_deterring_min_sprt_margin": 1.25,
                    "model_deterring_chance_threshold": 0.35,
                    "model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "model_deterring_min_selection_weight": 0.0,
                    "model_deterring_capacity_rho_max": 0.85,
                    "model_deterring_capacity_history_window_s": 3600.0,
                    "model_deterring_capacity_min_completed_tasks": 3,
                    "model_deterring_capacity_fallback_budget_per_hr": 4,
                    "model_deterring_risk_threshold": 0.35,
                    "model_deterring_risk_scale": 1.0e-4,
                    "model_deterring_budget_per_robot_per_hr": 4,
                    "model_deterring_min_recent_points": 1,
                    "model_deterring_field_threshold": None,
                    "model_deterring_min_persistence_replans": 2,
                    "model_deterring_persistence_max_gap_s": 120.0,
                    "model_deterring_score_margin": 0.10,
                    "model_deterring_repeat_block_window_s": 120.0,
                    "model_deterring_repeat_block_radius_m": 25.0,
                    "model_deterring_max_eta_s": 120.0,
                    "model_deterring_busy_min_support_override": 1,
                    "model_deterring_busy_risk_override": 0.20,
                    "model_deterring_global_admission_cap_per_cycle": 1,
                    "model_deterring_require_idle_robot_for_admission": False,
                    "model_deterring_prefer_idle_robots_for_assignment": True,
                    "model_deterring_busy_fallback_p_event_min": 0.90,
                    "model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "model_deterring_busy_fallback_eta_s_max": 1.25,
                    "protect_direct_detection_from_model_deterring": True,
                    "model_deterring_direct_conflict_radius_m": 35.0,
                    "model_deterring_direct_conflict_window_s": 120.0,
                    "max_active_tasks_per_robot": 4,
                    "max_active_patrolling_per_robot": 2,
                    "max_active_model_deterring_per_robot": 1,
                    "preempt_deterring_goals": True,
                    "preempt_direct_detection_goals": True,
                    "preempt_model_scored_goals": False,
                    "proposed_enable_model_scored_deterring": bool(enable_model_det),
                    "tune_beta_scale": 1.0,
                    "tune_cost_scale": 1.0,
                    "tune_det_window_s": 120.0,
                    "tune_risk_threshold": 0.35,
                    "tune_risk_scale": 1.0e-4,
                    "tune_budget_per_hr": 4,
                    "tune_min_recent_points": 1,
                    "tune_min_persistence_replans": 2,
                    "tune_score_margin": 0.10,
                    "tune_repeat_window_s": 120.0,
                    "tune_repeat_radius_m": 25.0,
                    "tune_max_eta_s": 120.0,
                    "tune_busy_min_support_override": 1,
                    "tune_busy_risk_override": 0.20,
                    "tune_max_active_tasks_per_robot": 4,
                    "tune_max_active_patrolling_per_robot": 2,
                    "tune_max_active_model_deterring_per_robot": 1,
                    "tune_preempt_deterring_goals": 1,
                    "tune_preempt_direct_detection_goals": 1,
                    "tune_preempt_model_scored_goals": 0,
                    "tune_intervention_boundary_min_interval_s": 5.0,
                    "tune_intervention_boundary_spatial_quant_m": 8.0,
                    "tune_intervention_boundary_min_weight": 0.2,
                    "tune_assigner_w_load": 0.8,
                    "tune_gate_policy": "sprt_capacity",
                    "tune_patrol_hotspot_filter_mode": "percentile",
                    "tune_patrol_hotspot_score_percentile": 97.0,
                    "tune_patrol_hotspot_keep_top_k": "None",
                    "tune_model_deterring_sprt_alpha": 0.25,
                    "tune_model_deterring_sprt_beta": 0.40,
                    "tune_model_deterring_sprt_patch_radius_m": 30.0,
                    "tune_model_deterring_min_sprt_margin": 1.25,
                    "tune_model_deterring_chance_threshold": 0.35,
                    "tune_model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "tune_model_deterring_min_selection_weight": 0.0,
                    "tune_model_deterring_capacity_rho_max": 0.85,
                    "tune_model_deterring_global_admission_cap_per_cycle": 1,
                    "tune_model_deterring_require_idle_robot_for_admission": 0,
                    "tune_model_deterring_prefer_idle_robots_for_assignment": 1,
                    "tune_model_deterring_busy_fallback_p_event_min": 0.90,
                    "tune_model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "tune_model_deterring_busy_fallback_eta_s_max": 1.25,
                    "tune_protect_direct_detection_from_model_deterring": 1,
                    "tune_proposed_enable_model_scored_deterring": int(enable_model_det),
                }
            )
        return scenario_grid, tune_grid

    if tune_preset == "feedback_ablation":
        tune_grid = []
        for tune_id, enable_feedback in [("FA01", 1), ("FA02", 0)]:
            tune_grid.append(
                {
                    "tune_id": tune_id,
                    "prio_deterring": 2.0,
                    "prio_patrolling": 0.25,
                    "assigner_w_load": 0.8,
                    "task_replan_period_s": 60.0,
                    "patrol_hotspot_filter_mode": "percentile",
                    "patrol_hotspot_score_percentile": 97.0,
                    "patrol_hotspot_keep_top_k": None,
                    "deterring_modes": _mode_pack(scale_beta=1.0, scale_cost=1.0),
                    "model_deterring_window_s": 120.0,
                    "model_deterring_gate_policy": "sprt_capacity",
                    "model_deterring_sprt_alpha": 0.25,
                    "model_deterring_sprt_beta": 0.40,
                    "model_deterring_sprt_patch_radius_m": 30.0,
                    "model_deterring_min_sprt_margin": 1.25,
                    "model_deterring_chance_threshold": 0.35,
                    "model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "model_deterring_min_selection_weight": 0.0,
                    "model_deterring_capacity_rho_max": 0.85,
                    "model_deterring_capacity_history_window_s": 3600.0,
                    "model_deterring_capacity_min_completed_tasks": 3,
                    "model_deterring_capacity_fallback_budget_per_hr": 4,
                    "model_deterring_risk_threshold": 0.35,
                    "model_deterring_risk_scale": 1.0e-4,
                    "model_deterring_budget_per_robot_per_hr": 4,
                    "model_deterring_min_recent_points": 1,
                    "model_deterring_field_threshold": None,
                    "model_deterring_min_persistence_replans": 2,
                    "model_deterring_persistence_max_gap_s": 120.0,
                    "model_deterring_score_margin": 0.10,
                    "model_deterring_repeat_block_window_s": 120.0,
                    "model_deterring_repeat_block_radius_m": 25.0,
                    "model_deterring_max_eta_s": 120.0,
                    "model_deterring_busy_min_support_override": 1,
                    "model_deterring_busy_risk_override": 0.20,
                    "model_deterring_global_admission_cap_per_cycle": 1,
                    "model_deterring_require_idle_robot_for_admission": False,
                    "model_deterring_prefer_idle_robots_for_assignment": True,
                    "model_deterring_busy_fallback_p_event_min": 0.90,
                    "model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "model_deterring_busy_fallback_eta_s_max": 1.25,
                    "protect_direct_detection_from_model_deterring": True,
                    "model_deterring_direct_conflict_radius_m": 35.0,
                    "model_deterring_direct_conflict_window_s": 120.0,
                    "max_active_tasks_per_robot": 4,
                    "max_active_patrolling_per_robot": 2,
                    "max_active_model_deterring_per_robot": 1,
                    "preempt_deterring_goals": True,
                    "preempt_direct_detection_goals": True,
                    "preempt_model_scored_goals": False,
                    "proposed_enable_model_scored_deterring": False,
                    "proposed_enable_intervention_feedback": bool(enable_feedback),
                    "tune_beta_scale": 1.0,
                    "tune_cost_scale": 1.0,
                    "tune_det_window_s": 120.0,
                    "tune_risk_threshold": 0.35,
                    "tune_risk_scale": 1.0e-4,
                    "tune_budget_per_hr": 4,
                    "tune_min_recent_points": 1,
                    "tune_min_persistence_replans": 2,
                    "tune_score_margin": 0.10,
                    "tune_repeat_window_s": 120.0,
                    "tune_repeat_radius_m": 25.0,
                    "tune_max_eta_s": 120.0,
                    "tune_busy_min_support_override": 1,
                    "tune_busy_risk_override": 0.20,
                    "tune_max_active_tasks_per_robot": 4,
                    "tune_max_active_patrolling_per_robot": 2,
                    "tune_max_active_model_deterring_per_robot": 1,
                    "tune_preempt_deterring_goals": 1,
                    "tune_preempt_direct_detection_goals": 1,
                    "tune_preempt_model_scored_goals": 0,
                    "tune_intervention_boundary_min_interval_s": 5.0,
                    "tune_intervention_boundary_spatial_quant_m": 8.0,
                    "tune_intervention_boundary_min_weight": 0.2,
                    "tune_assigner_w_load": 0.8,
                    "tune_gate_policy": "sprt_capacity",
                    "tune_patrol_hotspot_filter_mode": "percentile",
                    "tune_patrol_hotspot_score_percentile": 97.0,
                    "tune_patrol_hotspot_keep_top_k": "None",
                    "tune_model_deterring_sprt_alpha": 0.25,
                    "tune_model_deterring_sprt_beta": 0.40,
                    "tune_model_deterring_sprt_patch_radius_m": 30.0,
                    "tune_model_deterring_min_sprt_margin": 1.25,
                    "tune_model_deterring_chance_threshold": 0.35,
                    "tune_model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "tune_model_deterring_min_selection_weight": 0.0,
                    "tune_model_deterring_capacity_rho_max": 0.85,
                    "tune_model_deterring_global_admission_cap_per_cycle": 1,
                    "tune_model_deterring_require_idle_robot_for_admission": 0,
                    "tune_model_deterring_prefer_idle_robots_for_assignment": 1,
                    "tune_model_deterring_busy_fallback_p_event_min": 0.90,
                    "tune_model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "tune_model_deterring_busy_fallback_eta_s_max": 1.25,
                    "tune_protect_direct_detection_from_model_deterring": 1,
                    "tune_proposed_enable_model_scored_deterring": 0,
                    "tune_proposed_enable_intervention_feedback": int(enable_feedback),
                }
            )
        return scenario_grid, tune_grid

    if tune_preset == "feedback_refine":
        # Narrow feedback-only production sweep:
        # keep model-scored preventive deterring off and tune only the
        # intervention-feedback broadcast throttling/filtering controls.
        feedback_grid = list(product([15.0, 30.0, 60.0], [8.0, 16.0], [0.35, 0.50]))
        tune_grid = []
        for i, (min_interval_s, spatial_quant_m, min_weight) in enumerate(feedback_grid, start=1):
            tune_grid.append(
                {
                    "tune_id": f"FF{i:02d}",
                    "prio_deterring": 2.0,
                    "prio_patrolling": 0.25,
                    "assigner_w_load": 0.8,
                    "task_replan_period_s": 60.0,
                    "patrol_hotspot_filter_mode": "percentile",
                    "patrol_hotspot_score_percentile": 97.0,
                    "patrol_hotspot_keep_top_k": None,
                    "deterring_modes": _mode_pack(scale_beta=1.0, scale_cost=1.0),
                    "model_deterring_window_s": 120.0,
                    "model_deterring_gate_policy": "sprt_capacity",
                    "model_deterring_sprt_alpha": 0.25,
                    "model_deterring_sprt_beta": 0.40,
                    "model_deterring_sprt_patch_radius_m": 30.0,
                    "model_deterring_min_sprt_margin": 1.25,
                    "model_deterring_chance_threshold": 0.35,
                    "model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "model_deterring_min_selection_weight": 0.0,
                    "model_deterring_capacity_rho_max": 0.85,
                    "model_deterring_capacity_history_window_s": 3600.0,
                    "model_deterring_capacity_min_completed_tasks": 3,
                    "model_deterring_capacity_fallback_budget_per_hr": 4,
                    "model_deterring_risk_threshold": 0.35,
                    "model_deterring_risk_scale": 1.0e-4,
                    "model_deterring_budget_per_robot_per_hr": 4,
                    "model_deterring_min_recent_points": 1,
                    "model_deterring_field_threshold": None,
                    "model_deterring_min_persistence_replans": 2,
                    "model_deterring_persistence_max_gap_s": 120.0,
                    "model_deterring_score_margin": 0.10,
                    "model_deterring_repeat_block_window_s": 120.0,
                    "model_deterring_repeat_block_radius_m": 25.0,
                    "model_deterring_max_eta_s": 120.0,
                    "model_deterring_busy_min_support_override": 1,
                    "model_deterring_busy_risk_override": 0.20,
                    "model_deterring_global_admission_cap_per_cycle": 1,
                    "model_deterring_require_idle_robot_for_admission": False,
                    "model_deterring_prefer_idle_robots_for_assignment": True,
                    "model_deterring_busy_fallback_p_event_min": 0.90,
                    "model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "model_deterring_busy_fallback_eta_s_max": 1.25,
                    "protect_direct_detection_from_model_deterring": True,
                    "model_deterring_direct_conflict_radius_m": 35.0,
                    "model_deterring_direct_conflict_window_s": 120.0,
                    "max_active_tasks_per_robot": 4,
                    "max_active_patrolling_per_robot": 2,
                    "max_active_model_deterring_per_robot": 1,
                    "preempt_deterring_goals": True,
                    "preempt_direct_detection_goals": True,
                    "preempt_model_scored_goals": False,
                    "intervention_boundary_min_interval_s": float(min_interval_s),
                    "intervention_boundary_spatial_quant_m": float(spatial_quant_m),
                    "intervention_boundary_min_weight": float(min_weight),
                    "proposed_enable_model_scored_deterring": False,
                    "proposed_enable_intervention_feedback": True,
                    "tune_beta_scale": 1.0,
                    "tune_cost_scale": 1.0,
                    "tune_det_window_s": 120.0,
                    "tune_risk_threshold": 0.35,
                    "tune_risk_scale": 1.0e-4,
                    "tune_budget_per_hr": 4,
                    "tune_min_recent_points": 1,
                    "tune_min_persistence_replans": 2,
                    "tune_score_margin": 0.10,
                    "tune_repeat_window_s": 120.0,
                    "tune_repeat_radius_m": 25.0,
                    "tune_max_eta_s": 120.0,
                    "tune_busy_min_support_override": 1,
                    "tune_busy_risk_override": 0.20,
                    "tune_max_active_tasks_per_robot": 4,
                    "tune_max_active_patrolling_per_robot": 2,
                    "tune_max_active_model_deterring_per_robot": 1,
                    "tune_preempt_deterring_goals": 1,
                    "tune_preempt_direct_detection_goals": 1,
                    "tune_preempt_model_scored_goals": 0,
                    "tune_intervention_boundary_min_interval_s": float(min_interval_s),
                    "tune_intervention_boundary_spatial_quant_m": float(spatial_quant_m),
                    "tune_intervention_boundary_min_weight": float(min_weight),
                    "tune_assigner_w_load": 0.8,
                    "tune_gate_policy": "sprt_capacity",
                    "tune_patrol_hotspot_filter_mode": "percentile",
                    "tune_patrol_hotspot_score_percentile": 97.0,
                    "tune_patrol_hotspot_keep_top_k": "None",
                    "tune_model_deterring_sprt_alpha": 0.25,
                    "tune_model_deterring_sprt_beta": 0.40,
                    "tune_model_deterring_sprt_patch_radius_m": 30.0,
                    "tune_model_deterring_min_sprt_margin": 1.25,
                    "tune_model_deterring_chance_threshold": 0.35,
                    "tune_model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "tune_model_deterring_min_selection_weight": 0.0,
                    "tune_model_deterring_capacity_rho_max": 0.85,
                    "tune_model_deterring_global_admission_cap_per_cycle": 1,
                    "tune_model_deterring_require_idle_robot_for_admission": 0,
                    "tune_model_deterring_prefer_idle_robots_for_assignment": 1,
                    "tune_model_deterring_busy_fallback_p_event_min": 0.90,
                    "tune_model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "tune_model_deterring_busy_fallback_eta_s_max": 1.25,
                    "tune_protect_direct_detection_from_model_deterring": 1,
                    "tune_proposed_enable_model_scored_deterring": 0,
                    "tune_proposed_enable_intervention_feedback": 1,
                }
            )
        return scenario_grid, tune_grid

    if tune_preset == "feedback_model_refine":
        # Narrow closed-loop feedback-model sweep:
        # keep model-scored preventive deterring off and tune only the
        # intervention inhibition magnitude and persistence.
        feedback_model_grid = list(product([0.20, 0.30, 0.45], [450.0, 600.0, 900.0]))
        tune_grid = []
        for i, (alpha_inhib, omega_inhib) in enumerate(feedback_model_grid, start=1):
            tune_grid.append(
                {
                    "tune_id": f"FM{i:02d}",
                    "prio_deterring": 2.0,
                    "prio_patrolling": 0.25,
                    "assigner_w_load": 0.8,
                    "task_replan_period_s": 60.0,
                    "patrol_hotspot_filter_mode": "percentile",
                    "patrol_hotspot_score_percentile": 97.0,
                    "patrol_hotspot_keep_top_k": None,
                    "deterring_modes": _mode_pack(scale_beta=1.0, scale_cost=1.0),
                    "alpha_inhib": float(alpha_inhib),
                    "omega_inhib": float(omega_inhib),
                    "model_deterring_window_s": 120.0,
                    "model_deterring_gate_policy": "sprt_capacity",
                    "model_deterring_sprt_alpha": 0.25,
                    "model_deterring_sprt_beta": 0.40,
                    "model_deterring_sprt_patch_radius_m": 30.0,
                    "model_deterring_min_sprt_margin": 1.25,
                    "model_deterring_chance_threshold": 0.35,
                    "model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "model_deterring_min_selection_weight": 0.0,
                    "model_deterring_capacity_rho_max": 0.85,
                    "model_deterring_capacity_history_window_s": 3600.0,
                    "model_deterring_capacity_min_completed_tasks": 3,
                    "model_deterring_capacity_fallback_budget_per_hr": 4,
                    "model_deterring_risk_threshold": 0.35,
                    "model_deterring_risk_scale": 1.0e-4,
                    "model_deterring_budget_per_robot_per_hr": 4,
                    "model_deterring_min_recent_points": 1,
                    "model_deterring_field_threshold": None,
                    "model_deterring_min_persistence_replans": 2,
                    "model_deterring_persistence_max_gap_s": 120.0,
                    "model_deterring_score_margin": 0.10,
                    "model_deterring_repeat_block_window_s": 120.0,
                    "model_deterring_repeat_block_radius_m": 25.0,
                    "model_deterring_max_eta_s": 120.0,
                    "model_deterring_busy_min_support_override": 1,
                    "model_deterring_busy_risk_override": 0.20,
                    "model_deterring_global_admission_cap_per_cycle": 1,
                    "model_deterring_require_idle_robot_for_admission": False,
                    "model_deterring_prefer_idle_robots_for_assignment": True,
                    "model_deterring_busy_fallback_p_event_min": 0.90,
                    "model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "model_deterring_busy_fallback_eta_s_max": 1.25,
                    "protect_direct_detection_from_model_deterring": True,
                    "model_deterring_direct_conflict_radius_m": 35.0,
                    "model_deterring_direct_conflict_window_s": 120.0,
                    "max_active_tasks_per_robot": 4,
                    "max_active_patrolling_per_robot": 2,
                    "max_active_model_deterring_per_robot": 1,
                    "preempt_deterring_goals": True,
                    "preempt_direct_detection_goals": True,
                    "preempt_model_scored_goals": False,
                    "proposed_enable_model_scored_deterring": False,
                    "proposed_enable_intervention_feedback": True,
                    "tune_beta_scale": 1.0,
                    "tune_cost_scale": 1.0,
                    "tune_det_window_s": 120.0,
                    "tune_risk_threshold": 0.35,
                    "tune_risk_scale": 1.0e-4,
                    "tune_budget_per_hr": 4,
                    "tune_min_recent_points": 1,
                    "tune_min_persistence_replans": 2,
                    "tune_score_margin": 0.10,
                    "tune_repeat_window_s": 120.0,
                    "tune_repeat_radius_m": 25.0,
                    "tune_max_eta_s": 120.0,
                    "tune_busy_min_support_override": 1,
                    "tune_busy_risk_override": 0.20,
                    "tune_max_active_tasks_per_robot": 4,
                    "tune_max_active_patrolling_per_robot": 2,
                    "tune_max_active_model_deterring_per_robot": 1,
                    "tune_preempt_deterring_goals": 1,
                    "tune_preempt_direct_detection_goals": 1,
                    "tune_preempt_model_scored_goals": 0,
                    "tune_intervention_boundary_min_interval_s": 60.0,
                    "tune_intervention_boundary_spatial_quant_m": 16.0,
                    "tune_intervention_boundary_min_weight": 0.50,
                    "tune_assigner_w_load": 0.8,
                    "tune_gate_policy": "sprt_capacity",
                    "tune_patrol_hotspot_filter_mode": "percentile",
                    "tune_patrol_hotspot_score_percentile": 97.0,
                    "tune_patrol_hotspot_keep_top_k": "None",
                    "tune_model_deterring_sprt_alpha": 0.25,
                    "tune_model_deterring_sprt_beta": 0.40,
                    "tune_model_deterring_sprt_patch_radius_m": 30.0,
                    "tune_model_deterring_min_sprt_margin": 1.25,
                    "tune_model_deterring_chance_threshold": 0.35,
                    "tune_model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "tune_model_deterring_min_selection_weight": 0.0,
                    "tune_model_deterring_capacity_rho_max": 0.85,
                    "tune_model_deterring_global_admission_cap_per_cycle": 1,
                    "tune_model_deterring_require_idle_robot_for_admission": 0,
                    "tune_model_deterring_prefer_idle_robots_for_assignment": 1,
                    "tune_model_deterring_busy_fallback_p_event_min": 0.90,
                    "tune_model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "tune_model_deterring_busy_fallback_eta_s_max": 1.25,
                    "tune_protect_direct_detection_from_model_deterring": 1,
                    "tune_proposed_enable_model_scored_deterring": 0,
                    "tune_proposed_enable_intervention_feedback": 1,
                    "tune_alpha_inhib": float(alpha_inhib),
                    "tune_omega_inhib": float(omega_inhib),
                }
            )
        return scenario_grid, tune_grid

    if tune_preset == "feedback_patrol_ablation":
        # Patrol-selection ablation:
        # keep feedback on and model-scored preventive deterring off, then
        # reduce how strongly intervention inhibition reshapes patrol scoring only.
        patrol_blend_grid = [1.0, 0.75, 0.50, 0.25, 0.0]
        tune_grid = []
        for i, patrol_inhib_retention in enumerate(patrol_blend_grid, start=1):
            tune_grid.append(
                {
                    "tune_id": f"FP{i:02d}",
                    "prio_deterring": 2.0,
                    "prio_patrolling": 0.25,
                    "assigner_w_load": 0.8,
                    "task_replan_period_s": 60.0,
                    "patrol_hotspot_filter_mode": "percentile",
                    "patrol_hotspot_score_percentile": 97.0,
                    "patrol_hotspot_keep_top_k": None,
                    "patrol_feedback_inhibition_retention": float(patrol_inhib_retention),
                    "deterring_modes": _mode_pack(scale_beta=1.0, scale_cost=1.0),
                    "alpha_inhib": 0.45,
                    "omega_inhib": 600.0,
                    "model_deterring_window_s": 120.0,
                    "model_deterring_gate_policy": "sprt_capacity",
                    "model_deterring_sprt_alpha": 0.25,
                    "model_deterring_sprt_beta": 0.40,
                    "model_deterring_sprt_patch_radius_m": 30.0,
                    "model_deterring_min_sprt_margin": 1.25,
                    "model_deterring_chance_threshold": 0.35,
                    "model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "model_deterring_min_selection_weight": 0.0,
                    "model_deterring_capacity_rho_max": 0.85,
                    "model_deterring_capacity_history_window_s": 3600.0,
                    "model_deterring_capacity_min_completed_tasks": 3,
                    "model_deterring_capacity_fallback_budget_per_hr": 4,
                    "model_deterring_risk_threshold": 0.35,
                    "model_deterring_risk_scale": 1.0e-4,
                    "model_deterring_budget_per_robot_per_hr": 4,
                    "model_deterring_min_recent_points": 1,
                    "model_deterring_field_threshold": None,
                    "model_deterring_min_persistence_replans": 2,
                    "model_deterring_persistence_max_gap_s": 120.0,
                    "model_deterring_score_margin": 0.10,
                    "model_deterring_repeat_block_window_s": 120.0,
                    "model_deterring_repeat_block_radius_m": 25.0,
                    "model_deterring_max_eta_s": 120.0,
                    "model_deterring_busy_min_support_override": 1,
                    "model_deterring_busy_risk_override": 0.20,
                    "model_deterring_global_admission_cap_per_cycle": 1,
                    "model_deterring_require_idle_robot_for_admission": False,
                    "model_deterring_prefer_idle_robots_for_assignment": True,
                    "model_deterring_busy_fallback_p_event_min": 0.90,
                    "model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "model_deterring_busy_fallback_eta_s_max": 1.25,
                    "protect_direct_detection_from_model_deterring": True,
                    "model_deterring_direct_conflict_radius_m": 35.0,
                    "model_deterring_direct_conflict_window_s": 120.0,
                    "max_active_tasks_per_robot": 4,
                    "max_active_patrolling_per_robot": 2,
                    "max_active_model_deterring_per_robot": 1,
                    "preempt_deterring_goals": True,
                    "preempt_direct_detection_goals": True,
                    "preempt_model_scored_goals": False,
                    "proposed_enable_model_scored_deterring": False,
                    "proposed_enable_intervention_feedback": True,
                    "intervention_boundary_min_interval_s": 60.0,
                    "intervention_boundary_spatial_quant_m": 16.0,
                    "intervention_boundary_min_weight": 0.50,
                    "tune_beta_scale": 1.0,
                    "tune_cost_scale": 1.0,
                    "tune_det_window_s": 120.0,
                    "tune_risk_threshold": 0.35,
                    "tune_risk_scale": 1.0e-4,
                    "tune_budget_per_hr": 4,
                    "tune_min_recent_points": 1,
                    "tune_min_persistence_replans": 2,
                    "tune_score_margin": 0.10,
                    "tune_repeat_window_s": 120.0,
                    "tune_repeat_radius_m": 25.0,
                    "tune_max_eta_s": 120.0,
                    "tune_busy_min_support_override": 1,
                    "tune_busy_risk_override": 0.20,
                    "tune_max_active_tasks_per_robot": 4,
                    "tune_max_active_patrolling_per_robot": 2,
                    "tune_max_active_model_deterring_per_robot": 1,
                    "tune_preempt_deterring_goals": 1,
                    "tune_preempt_direct_detection_goals": 1,
                    "tune_preempt_model_scored_goals": 0,
                    "tune_intervention_boundary_min_interval_s": 60.0,
                    "tune_intervention_boundary_spatial_quant_m": 16.0,
                    "tune_intervention_boundary_min_weight": 0.50,
                    "tune_assigner_w_load": 0.8,
                    "tune_gate_policy": "sprt_capacity",
                    "tune_patrol_hotspot_filter_mode": "percentile",
                    "tune_patrol_hotspot_score_percentile": 97.0,
                    "tune_patrol_hotspot_keep_top_k": "None",
                    "tune_patrol_feedback_inhibition_retention": float(patrol_inhib_retention),
                    "tune_model_deterring_sprt_alpha": 0.25,
                    "tune_model_deterring_sprt_beta": 0.40,
                    "tune_model_deterring_sprt_patch_radius_m": 30.0,
                    "tune_model_deterring_min_sprt_margin": 1.25,
                    "tune_model_deterring_chance_threshold": 0.35,
                    "tune_model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "tune_model_deterring_min_selection_weight": 0.0,
                    "tune_model_deterring_capacity_rho_max": 0.85,
                    "tune_model_deterring_global_admission_cap_per_cycle": 1,
                    "tune_model_deterring_require_idle_robot_for_admission": 0,
                    "tune_model_deterring_prefer_idle_robots_for_assignment": 1,
                    "tune_model_deterring_busy_fallback_p_event_min": 0.90,
                    "tune_model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "tune_model_deterring_busy_fallback_eta_s_max": 1.25,
                    "tune_protect_direct_detection_from_model_deterring": 1,
                    "tune_proposed_enable_model_scored_deterring": 0,
                    "tune_proposed_enable_intervention_feedback": 1,
                    "tune_alpha_inhib": 0.45,
                    "tune_omega_inhib": 600.0,
                }
            )
        return scenario_grid, tune_grid

    if tune_preset == "reactive_dedup_refine":
        # Direct-detection dedup refinement:
        # keep feedback on, keep model-scored preventive deterring off, and
        # tune only the spatiotemporal clustering applied to reactive tasks.
        dedup_grid = list(product([10.0, 15.0, 20.0], [20.0, 40.0, 60.0]))
        tune_grid = []
        for i, (cluster_radius_m, cluster_window_s) in enumerate(dedup_grid, start=1):
            tune_grid.append(
                {
                    "tune_id": f"RD{i:02d}",
                    "prio_deterring": 2.0,
                    "prio_patrolling": 0.25,
                    "assigner_w_load": 0.8,
                    "task_replan_period_s": 60.0,
                    "patrol_hotspot_filter_mode": "percentile",
                    "patrol_hotspot_score_percentile": 97.0,
                    "patrol_hotspot_keep_top_k": None,
                    "patrol_feedback_inhibition_retention": 1.0,
                    "enable_direct_detection_task_clustering": True,
                    "direct_detection_task_cluster_radius_m": float(cluster_radius_m),
                    "direct_detection_task_cluster_window_s": float(cluster_window_s),
                    "deterring_modes": _mode_pack(scale_beta=1.0, scale_cost=1.0),
                    "alpha_inhib": 0.45,
                    "omega_inhib": 600.0,
                    "model_deterring_window_s": 120.0,
                    "model_deterring_gate_policy": "sprt_capacity",
                    "model_deterring_sprt_alpha": 0.25,
                    "model_deterring_sprt_beta": 0.40,
                    "model_deterring_sprt_patch_radius_m": 30.0,
                    "model_deterring_min_sprt_margin": 1.25,
                    "model_deterring_chance_threshold": 0.35,
                    "model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "model_deterring_min_selection_weight": 0.0,
                    "model_deterring_capacity_rho_max": 0.85,
                    "model_deterring_capacity_history_window_s": 3600.0,
                    "model_deterring_capacity_min_completed_tasks": 3,
                    "model_deterring_capacity_fallback_budget_per_hr": 4,
                    "model_deterring_risk_threshold": 0.35,
                    "model_deterring_risk_scale": 1.0e-4,
                    "model_deterring_budget_per_robot_per_hr": 4,
                    "model_deterring_min_recent_points": 1,
                    "model_deterring_field_threshold": None,
                    "model_deterring_min_persistence_replans": 2,
                    "model_deterring_persistence_max_gap_s": 120.0,
                    "model_deterring_score_margin": 0.10,
                    "model_deterring_repeat_block_window_s": 120.0,
                    "model_deterring_repeat_block_radius_m": 25.0,
                    "model_deterring_max_eta_s": 120.0,
                    "model_deterring_busy_min_support_override": 1,
                    "model_deterring_busy_risk_override": 0.20,
                    "model_deterring_global_admission_cap_per_cycle": 1,
                    "model_deterring_require_idle_robot_for_admission": False,
                    "model_deterring_prefer_idle_robots_for_assignment": True,
                    "model_deterring_busy_fallback_p_event_min": 0.90,
                    "model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "model_deterring_busy_fallback_eta_s_max": 1.25,
                    "protect_direct_detection_from_model_deterring": True,
                    "model_deterring_direct_conflict_radius_m": 35.0,
                    "model_deterring_direct_conflict_window_s": 120.0,
                    "max_active_tasks_per_robot": 4,
                    "max_active_patrolling_per_robot": 2,
                    "max_active_model_deterring_per_robot": 1,
                    "preempt_deterring_goals": True,
                    "preempt_direct_detection_goals": True,
                    "preempt_model_scored_goals": False,
                    "proposed_enable_model_scored_deterring": False,
                    "proposed_enable_intervention_feedback": True,
                    "intervention_boundary_min_interval_s": 60.0,
                    "intervention_boundary_spatial_quant_m": 16.0,
                    "intervention_boundary_min_weight": 0.50,
                    "tune_beta_scale": 1.0,
                    "tune_cost_scale": 1.0,
                    "tune_det_window_s": 120.0,
                    "tune_risk_threshold": 0.35,
                    "tune_risk_scale": 1.0e-4,
                    "tune_budget_per_hr": 4,
                    "tune_min_recent_points": 1,
                    "tune_min_persistence_replans": 2,
                    "tune_score_margin": 0.10,
                    "tune_repeat_window_s": 120.0,
                    "tune_repeat_radius_m": 25.0,
                    "tune_max_eta_s": 120.0,
                    "tune_busy_min_support_override": 1,
                    "tune_busy_risk_override": 0.20,
                    "tune_max_active_tasks_per_robot": 4,
                    "tune_max_active_patrolling_per_robot": 2,
                    "tune_max_active_model_deterring_per_robot": 1,
                    "tune_preempt_deterring_goals": 1,
                    "tune_preempt_direct_detection_goals": 1,
                    "tune_preempt_model_scored_goals": 0,
                    "tune_intervention_boundary_min_interval_s": 60.0,
                    "tune_intervention_boundary_spatial_quant_m": 16.0,
                    "tune_intervention_boundary_min_weight": 0.50,
                    "tune_assigner_w_load": 0.8,
                    "tune_gate_policy": "sprt_capacity",
                    "tune_patrol_hotspot_filter_mode": "percentile",
                    "tune_patrol_hotspot_score_percentile": 97.0,
                    "tune_patrol_hotspot_keep_top_k": "None",
                    "tune_patrol_feedback_inhibition_retention": 1.0,
                    "tune_model_deterring_sprt_alpha": 0.25,
                    "tune_model_deterring_sprt_beta": 0.40,
                    "tune_model_deterring_sprt_patch_radius_m": 30.0,
                    "tune_model_deterring_min_sprt_margin": 1.25,
                    "tune_model_deterring_chance_threshold": 0.35,
                    "tune_model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "tune_model_deterring_min_selection_weight": 0.0,
                    "tune_model_deterring_capacity_rho_max": 0.85,
                    "tune_model_deterring_global_admission_cap_per_cycle": 1,
                    "tune_model_deterring_require_idle_robot_for_admission": 0,
                    "tune_model_deterring_prefer_idle_robots_for_assignment": 1,
                    "tune_model_deterring_busy_fallback_p_event_min": 0.90,
                    "tune_model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "tune_model_deterring_busy_fallback_eta_s_max": 1.25,
                    "tune_protect_direct_detection_from_model_deterring": 1,
                    "tune_proposed_enable_model_scored_deterring": 0,
                    "tune_proposed_enable_intervention_feedback": 1,
                    "tune_enable_direct_detection_task_clustering": 1,
                    "tune_direct_detection_task_cluster_radius_m": float(cluster_radius_m),
                    "tune_direct_detection_task_cluster_window_s": float(cluster_window_s),
                    "tune_alpha_inhib": 0.45,
                    "tune_omega_inhib": 600.0,
                }
            )
        return scenario_grid, tune_grid

    if tune_preset == "reactive_dedup_split_refine":
        # Split direct-detection dedup refinement:
        # active-task refresh can be more permissive than queued-task clustering.
        active_refresh_grid = [(15.0, 40.0), (15.0, 60.0), (20.0, 40.0), (20.0, 60.0)]
        queued_cluster_grid = [(10.0, 20.0), (10.0, 40.0), (15.0, 20.0), (15.0, 40.0)]
        tune_grid = []
        for i, ((active_radius_m, active_window_s), (queued_radius_m, queued_window_s)) in enumerate(
            product(active_refresh_grid, queued_cluster_grid), start=1
        ):
            tune_grid.append(
                {
                    "tune_id": f"RS{i:02d}",
                    "prio_deterring": 2.0,
                    "prio_patrolling": 0.25,
                    "assigner_w_load": 0.8,
                    "task_replan_period_s": 60.0,
                    "patrol_hotspot_filter_mode": "percentile",
                    "patrol_hotspot_score_percentile": 97.0,
                    "patrol_hotspot_keep_top_k": None,
                    "patrol_feedback_inhibition_retention": 1.0,
                    "enable_direct_detection_task_clustering": True,
                    "direct_detection_task_active_refresh_radius_m": float(active_radius_m),
                    "direct_detection_task_active_refresh_window_s": float(active_window_s),
                    "direct_detection_task_queued_cluster_radius_m": float(queued_radius_m),
                    "direct_detection_task_queued_cluster_window_s": float(queued_window_s),
                    "deterring_modes": _mode_pack(scale_beta=1.0, scale_cost=1.0),
                    "alpha_inhib": 0.45,
                    "omega_inhib": 600.0,
                    "model_deterring_window_s": 120.0,
                    "model_deterring_gate_policy": "sprt_capacity",
                    "model_deterring_sprt_alpha": 0.25,
                    "model_deterring_sprt_beta": 0.40,
                    "model_deterring_sprt_patch_radius_m": 30.0,
                    "model_deterring_min_sprt_margin": 1.25,
                    "model_deterring_chance_threshold": 0.35,
                    "model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "model_deterring_min_selection_weight": 0.0,
                    "model_deterring_capacity_rho_max": 0.85,
                    "model_deterring_capacity_history_window_s": 3600.0,
                    "model_deterring_capacity_min_completed_tasks": 3,
                    "model_deterring_capacity_fallback_budget_per_hr": 4,
                    "model_deterring_risk_threshold": 0.35,
                    "model_deterring_risk_scale": 1.0e-4,
                    "model_deterring_budget_per_robot_per_hr": 4,
                    "model_deterring_min_recent_points": 1,
                    "model_deterring_field_threshold": None,
                    "model_deterring_min_persistence_replans": 2,
                    "model_deterring_persistence_max_gap_s": 120.0,
                    "model_deterring_score_margin": 0.10,
                    "model_deterring_repeat_block_window_s": 120.0,
                    "model_deterring_repeat_block_radius_m": 25.0,
                    "model_deterring_max_eta_s": 120.0,
                    "model_deterring_busy_min_support_override": 1,
                    "model_deterring_busy_risk_override": 0.20,
                    "model_deterring_global_admission_cap_per_cycle": 1,
                    "model_deterring_require_idle_robot_for_admission": False,
                    "model_deterring_prefer_idle_robots_for_assignment": True,
                    "model_deterring_busy_fallback_p_event_min": 0.90,
                    "model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "model_deterring_busy_fallback_eta_s_max": 1.25,
                    "protect_direct_detection_from_model_deterring": True,
                    "model_deterring_direct_conflict_radius_m": 35.0,
                    "model_deterring_direct_conflict_window_s": 120.0,
                    "max_active_tasks_per_robot": 4,
                    "max_active_patrolling_per_robot": 2,
                    "max_active_model_deterring_per_robot": 1,
                    "preempt_deterring_goals": True,
                    "preempt_direct_detection_goals": True,
                    "preempt_model_scored_goals": False,
                    "proposed_enable_model_scored_deterring": False,
                    "proposed_enable_intervention_feedback": True,
                    "intervention_boundary_min_interval_s": 60.0,
                    "intervention_boundary_spatial_quant_m": 16.0,
                    "intervention_boundary_min_weight": 0.50,
                    "tune_beta_scale": 1.0,
                    "tune_cost_scale": 1.0,
                    "tune_det_window_s": 120.0,
                    "tune_risk_threshold": 0.35,
                    "tune_risk_scale": 1.0e-4,
                    "tune_budget_per_hr": 4,
                    "tune_min_recent_points": 1,
                    "tune_min_persistence_replans": 2,
                    "tune_score_margin": 0.10,
                    "tune_repeat_window_s": 120.0,
                    "tune_repeat_radius_m": 25.0,
                    "tune_max_eta_s": 120.0,
                    "tune_busy_min_support_override": 1,
                    "tune_busy_risk_override": 0.20,
                    "tune_max_active_tasks_per_robot": 4,
                    "tune_max_active_patrolling_per_robot": 2,
                    "tune_max_active_model_deterring_per_robot": 1,
                    "tune_preempt_deterring_goals": 1,
                    "tune_preempt_direct_detection_goals": 1,
                    "tune_preempt_model_scored_goals": 0,
                    "tune_intervention_boundary_min_interval_s": 60.0,
                    "tune_intervention_boundary_spatial_quant_m": 16.0,
                    "tune_intervention_boundary_min_weight": 0.50,
                    "tune_assigner_w_load": 0.8,
                    "tune_gate_policy": "sprt_capacity",
                    "tune_patrol_hotspot_filter_mode": "percentile",
                    "tune_patrol_hotspot_score_percentile": 97.0,
                    "tune_patrol_hotspot_keep_top_k": "None",
                    "tune_patrol_feedback_inhibition_retention": 1.0,
                    "tune_model_deterring_sprt_alpha": 0.25,
                    "tune_model_deterring_sprt_beta": 0.40,
                    "tune_model_deterring_sprt_patch_radius_m": 30.0,
                    "tune_model_deterring_min_sprt_margin": 1.25,
                    "tune_model_deterring_chance_threshold": 0.35,
                    "tune_model_deterring_min_deltaJ_per_cost": 1.0e5,
                    "tune_model_deterring_min_selection_weight": 0.0,
                    "tune_model_deterring_capacity_rho_max": 0.85,
                    "tune_model_deterring_global_admission_cap_per_cycle": 1,
                    "tune_model_deterring_require_idle_robot_for_admission": 0,
                    "tune_model_deterring_prefer_idle_robots_for_assignment": 1,
                    "tune_model_deterring_busy_fallback_p_event_min": 0.90,
                    "tune_model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
                    "tune_model_deterring_busy_fallback_eta_s_max": 1.25,
                    "tune_protect_direct_detection_from_model_deterring": 1,
                    "tune_proposed_enable_model_scored_deterring": 0,
                    "tune_proposed_enable_intervention_feedback": 1,
                    "tune_enable_direct_detection_task_clustering": 1,
                    "tune_direct_detection_task_active_refresh_radius_m": float(active_radius_m),
                    "tune_direct_detection_task_active_refresh_window_s": float(active_window_s),
                    "tune_direct_detection_task_queued_cluster_radius_m": float(queued_radius_m),
                    "tune_direct_detection_task_queued_cluster_window_s": float(queued_window_s),
                    "tune_alpha_inhib": 0.45,
                    "tune_omega_inhib": 600.0,
                }
            )
        return scenario_grid, tune_grid

    tune_grid = []
    if tune_preset == "targeted":
        # Small high-impact set focused on gating/budget/suppression for quick iteration.
        targeted = [
            (2.2, 1.15, 0.9, 45.0, 120.0, 0.25, 6, 1),
            (2.2, 1.15, 1.0, 45.0, 120.0, 0.30, 6, 1),
            (2.0, 1.10, 1.0, 60.0, 120.0, 0.30, 4, 1),
            (2.0, 1.10, 1.0, 45.0, 90.0, 0.35, 4, 1),
            (1.8, 1.00, 1.0, 60.0, 120.0, 0.35, 4, 1),
            (2.2, 1.15, 0.9, 60.0, 90.0, 0.25, 6, 1),
            (2.0, 1.10, 0.9, 45.0, 120.0, 0.25, 4, 1),
            (2.2, 1.00, 0.9, 45.0, 120.0, 0.30, 6, 1),
            (2.0, 1.15, 1.0, 60.0, 120.0, 0.40, 4, 1),
            (1.8, 1.10, 1.0, 45.0, 90.0, 0.30, 2, 1),
            (2.2, 1.15, 0.9, 45.0, 60.0, 0.25, 6, 1),
            (2.0, 1.00, 1.0, 60.0, 90.0, 0.40, 2, 1),
        ]
        iterator = targeted
    elif tune_preset == "tuesday_focus":
        # Focused pass: stricter confidence + support gating with stronger effect per accepted action.
        iterator = [
            (2.2, 1.30, 1.0, 60.0, 120.0, 0.50, 3, 2),
            (2.2, 1.40, 1.0, 60.0, 120.0, 0.55, 4, 2),
            (2.2, 1.50, 1.0, 45.0, 90.0, 0.50, 2, 3),
            (2.2, 1.45, 1.0, 45.0, 90.0, 0.45, 3, 2),
            (2.2, 1.60, 1.0, 60.0, 120.0, 0.60, 3, 3),
            (2.2, 1.50, 1.0, 45.0, 60.0, 0.50, 2, 2),
            (2.2, 1.55, 1.0, 60.0, 120.0, 0.40, 2, 2),
            (2.2, 1.35, 1.0, 60.0, 90.0, 0.60, 4, 3),
        ]
    elif tune_preset == "tuesday_focus_v2":
        # Higher-separation set for S2/S3: stronger deterrence effect + stricter preventive gating.
        # Tuple: (prio_det, beta_scale, cost_scale, replan_s, det_win_s, risk_thr, budget_hr, min_recent_points, risk_scale)
        iterator = [
            (2.4, 1.45, 1.0, 45.0, 120.0, 0.50, 3, 2, 1.0e-4),
            (2.4, 1.55, 1.0, 45.0, 120.0, 0.55, 3, 3, 1.0e-4),
            (2.5, 1.60, 1.0, 45.0, 90.0,  0.60, 2, 3, 1.0e-4),
            (2.3, 1.40, 1.0, 60.0, 120.0, 0.50, 4, 2, 1.0e-4),
            (2.4, 1.70, 1.0, 45.0, 90.0,  0.65, 2, 3, 8.0e-5),
            (2.2, 1.45, 1.0, 60.0, 120.0, 0.55, 4, 2, 8.0e-5),
            (2.5, 1.80, 1.0, 30.0, 90.0,  0.70, 2, 3, 1.2e-4),
            (2.3, 1.50, 1.0, 60.0, 180.0, 0.50, 3, 2, 1.0e-4),
            (2.4, 1.60, 1.0, 45.0, 180.0, 0.60, 3, 3, 1.0e-4),
            (2.2, 1.35, 1.0, 60.0, 120.0, 0.45, 5, 2, 1.0e-4),
        ]
    else:
        iterator = product(prio_list, beta_list, cost_list, replan_list, det_window_list, risk_thr_list, budget_list)

    for i, row in enumerate(iterator, start=1):
        if len(row) == 7:
            prio_det, beta_scale, cost_scale, replan_s, det_win_s, risk_thr, budget_hr = row
            min_recent_points = 1
            risk_scale = 1.0e-4
        else:
            if len(row) == 8:
                prio_det, beta_scale, cost_scale, replan_s, det_win_s, risk_thr, budget_hr, min_recent_points = row
                risk_scale = 1.0e-4
            else:
                prio_det, beta_scale, cost_scale, replan_s, det_win_s, risk_thr, budget_hr, min_recent_points, risk_scale = row
        tune_grid.append(
            {
                "tune_id": f"T{i:02d}",
                "prio_deterring": float(prio_det),
                "prio_patrolling": 0.25,
                "task_replan_period_s": float(replan_s),
                "deterring_modes": _mode_pack(scale_beta=float(beta_scale), scale_cost=float(cost_scale)),
                "model_deterring_window_s": float(det_win_s),
                "model_deterring_risk_threshold": float(risk_thr),
                "model_deterring_risk_scale": float(risk_scale),
                "model_deterring_budget_per_robot_per_hr": int(budget_hr),
                "model_deterring_min_recent_points": int(min_recent_points),
                "model_deterring_min_persistence_replans": 2,
                "model_deterring_persistence_max_gap_s": 120.0,
                "model_deterring_score_margin": 0.05,
                "model_deterring_repeat_block_window_s": 120.0,
                "model_deterring_repeat_block_radius_m": 25.0,
                "model_deterring_max_eta_s": 120.0,
                "model_deterring_busy_min_support_override": 1,
                "model_deterring_busy_risk_override": 0.20,
                "max_active_tasks_per_robot": 4,
                "max_active_patrolling_per_robot": 2,
                "max_active_model_deterring_per_robot": 1,
                "preempt_deterring_goals": True,
                "tune_beta_scale": float(beta_scale),
                "tune_cost_scale": float(cost_scale),
                "tune_det_window_s": float(det_win_s),
                "tune_risk_threshold": float(risk_thr),
                "tune_risk_scale": float(risk_scale),
                "tune_budget_per_hr": int(budget_hr),
                "tune_min_recent_points": int(min_recent_points),
                "tune_min_persistence_replans": 2,
                "tune_score_margin": 0.05,
                "tune_repeat_window_s": 120.0,
                "tune_repeat_radius_m": 25.0,
                "tune_max_eta_s": 120.0,
                "tune_busy_min_support_override": 1,
                "tune_busy_risk_override": 0.20,
                "tune_max_active_tasks_per_robot": 4,
                "tune_max_active_patrolling_per_robot": 2,
                "tune_max_active_model_deterring_per_robot": 1,
            }
        )
    return scenario_grid, tune_grid


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        description="Parallel 24h experiment sweep",
        epilog=(
            "Example thesis selective proposed run:\n"
            "  python -m experiments.run_24h_experiment_parallel --profile final --scenario-scope s23 "
            "--time-horizons-h 24 --max-workers 8 --planner-profile thesis_calibrated_selective_proposed "
            "--proposed-preventive-policy sprt_capacity --use-frozen-calibration --calibration-config-id C37"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_config_argument(parser)
    parser.add_argument("--profile", choices=["fast", "final"], default="final")
    parser.add_argument("--max-workers", type=int, default=0, help="0 => auto")
    parser.add_argument("--num-runs", type=int, default=0, help="0 => profile default")
    parser.add_argument("--seed-start", type=int, default=1000)
    parser.add_argument("--dt", type=float, default=0.0, help="0 => profile default")
    parser.add_argument("--nx", type=int, default=0, help="0 => profile default")
    parser.add_argument("--ny", type=int, default=0, help="0 => profile default")
    parser.add_argument("--limit-settings", type=int, default=0, help="0 => all")
    parser.add_argument("--tune-preset", choices=["full", "targeted", "tuesday_focus", "tuesday_focus_v2", "planner_tune", "diagnostic_like", "gate_refine", "gate_selective", "gate_busy_fallback", "gate_selection_weight", "gate_evidence_margin", "model_deterring_ablation", "feedback_ablation", "feedback_refine", "feedback_model_refine", "feedback_patrol_ablation", "reactive_dedup_refine", "reactive_dedup_split_refine"], default="full")
    parser.add_argument("--scenario-scope", choices=["all", "s23", "s2", "s3"], default="all")
    parser.add_argument(
        "--time-horizons-h",
        type=str,
        default="24",
        help="Comma-separated simulation horizons in hours, e.g. 6,24,72",
    )
    parser.add_argument("--time-metrics-period-s", type=float, default=900.0, help="Sampling period for over-time metrics")
    parser.add_argument(
        "--planner-profile",
        default="",
        help="Optional production planner profile, e.g. thesis_calibrated_selective_proposed.",
    )
    parser.add_argument(
        "--proposed-preventive-policy",
        choices=VALID_PREVENTIVE_POLICIES,
        default="",
        help="Explicit preventive policy override for the proposed baseline only.",
    )
    parser.add_argument(
        "--use-frozen-calibration",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable frozen SESTPP calibration for the proposed baseline only.",
    )
    parser.add_argument(
        "--calibration-ranking-path",
        default="",
        help="Optional frozen-calibration ranking CSV path.",
    )
    parser.add_argument(
        "--calibration-manifest-path",
        default="",
        help="Optional frozen-calibration manifest JSON path.",
    )
    parser.add_argument(
        "--calibration-config-id",
        default="",
        help="Optional frozen-calibration config id, e.g. C37.",
    )
    parser.add_argument(
        "--enable-winner-profile",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Explicitly enable opt-in winner profile migration flags in production simulation.",
    )
    parser.add_argument(
        "--winner-profile-id",
        choices=["F1"],
        default="F1",
        help="Winner profile variant to apply when --enable-winner-profile is set.",
    )
    args, config_meta = parse_args_with_config(parser, aliases=EXPERIMENT_RUNNER_CONFIG_ALIASES, argv=argv)
    requested_runtime_controls = _resolve_requested_runtime_controls(args)
    for key, value in requested_runtime_controls.items():
        setattr(args, key, value)

    seed_start = int(args.seed_start)
    if args.max_workers > 0:
        max_workers = int(args.max_workers)
    else:
        auto_cap = 12 if args.profile == "fast" else 8
        max_workers = max(1, min((os.cpu_count() or 2) - 1, auto_cap))

    profile_defaults = {
        "fast": {"num_runs": 5, "dt": 10.0, "NX": 64, "NY": 48},
        "final": {"num_runs": 12, "dt": 5.0, "NX": 80, "NY": 64},
    }
    dflt = profile_defaults[args.profile]
    num_runs = int(args.num_runs if args.num_runs > 0 else dflt["num_runs"])
    dt = float(args.dt if args.dt > 0 else dflt["dt"])
    nx = int(args.nx if args.nx > 0 else dflt["NX"])
    ny = int(args.ny if args.ny > 0 else dflt["NY"])

    base_params = {
        "dt": dt,
        "task_replan_period_s": 60.0,
        "NX": nx,
        "NY": ny,
        "W": 500.0,
        "H": 500.0,
        "Nrobots": 6,
        "uav_fraction": 0.0,
        # unique telemetry folder per worker prevents file contention
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
    }
    if args.planner_profile:
        base_params["planner_profile"] = str(args.planner_profile)
    if args.tune_preset == "diagnostic_like":
        # Match diagnostic_compare_systems defaults for fair A/B validation.
        base_params["dt"] = 5.0 if args.dt <= 0 else float(args.dt)
        base_params["NX"] = 80 if args.nx <= 0 else int(args.nx)
        base_params["NY"] = 64 if args.ny <= 0 else int(args.ny)
        base_params["task_replan_period_s"] = 45.0
        base_params["warmup_s"] = 1800.0
        base_params["forecast_horizon_s"] = 300.0
        base_params["forecast_match_radius_m"] = 20.0
        base_params["forecast_top_k"] = 5
        base_params["forecast_eval_period_s"] = 30.0

    winner_profile_overrides = {}
    if bool(args.enable_winner_profile):
        # Minimal-risk migration profile from lab finalist F1.
        winner_profile_overrides = {
            "enable_winner_profile": True,
        }
    scenario_grid, tune_grid = _build_grids(
        args.profile,
        tune_preset=str(args.tune_preset),
        scenario_scope=str(args.scenario_scope),
    )
    tune_grid = [_normalize_tune_entry(t) for t in tune_grid]
    horizons_h = [float(x.strip()) for x in str(args.time_horizons_h).split(",") if x.strip()]
    if not horizons_h:
        horizons_h = [24.0]

    jobs = []
    exp_id = 0
    for s in scenario_grid:
        for horizon_h in horizons_h:
            for t in tune_grid:
                exp_id += 1
                exp_tag = f"E{exp_id:03d}"
                run_kwargs = deepcopy(base_params)
                run_kwargs["T_end"] = float(horizon_h) * 3600.0
                run_kwargs.update({k: v for k, v in s.items() if k != "scenario_id"})
                run_kwargs.update({
                    k: v for k, v in t.items()
                    if k not in {
                        "tune_id",
                        "tune_beta_scale",
                        "tune_cost_scale",
                        "tune_det_window_s",
                        "tune_risk_threshold",
                        "tune_risk_scale",
                        "tune_budget_per_hr",
                        "tune_min_recent_points",
                        "tune_min_persistence_replans",
                        "tune_score_margin",
                        "tune_repeat_window_s",
                        "tune_repeat_radius_m",
                        "tune_max_eta_s",
                        "tune_busy_min_support_override",
                        "tune_busy_risk_override",
                        "tune_max_active_tasks_per_robot",
                        "tune_max_active_patrolling_per_robot",
                        "tune_max_active_model_deterring_per_robot",
                        "tune_preempt_deterring_goals",
                        "tune_preempt_direct_detection_goals",
                        "tune_preempt_model_scored_goals",
                        "tune_intervention_boundary_min_interval_s",
                        "tune_intervention_boundary_spatial_quant_m",
                        "tune_intervention_boundary_min_weight",
                        "tune_assigner_w_load",
                        "tune_gate_policy",
                        "tune_patrol_hotspot_filter_mode",
                        "tune_patrol_hotspot_score_percentile",
                        "tune_patrol_hotspot_keep_top_k",
                        "tune_patrol_feedback_inhibition_retention",
                        "tune_model_deterring_sprt_alpha",
                        "tune_model_deterring_sprt_beta",
                        "tune_model_deterring_sprt_patch_radius_m",
                        "tune_model_deterring_min_sprt_margin",
                        "tune_model_deterring_chance_threshold",
                        "tune_model_deterring_min_deltaJ_per_cost",
                        "tune_model_deterring_min_selection_weight",
                        "tune_model_deterring_capacity_rho_max",
                        "tune_model_deterring_global_admission_cap_per_cycle",
                        "tune_model_deterring_require_idle_robot_for_admission",
                        "tune_model_deterring_prefer_idle_robots_for_assignment",
                        "tune_model_deterring_busy_fallback_p_event_min",
                        "tune_model_deterring_busy_fallback_deltaJ_per_cost_min",
                        "tune_model_deterring_busy_fallback_eta_s_max",
                        "tune_protect_direct_detection_from_model_deterring",
                        "tune_proposed_enable_model_scored_deterring",
                        "tune_proposed_enable_intervention_feedback",
                        "tune_enable_direct_detection_task_clustering",
                        "tune_direct_detection_task_cluster_radius_m",
                        "tune_direct_detection_task_cluster_window_s",
                        "tune_direct_detection_task_active_refresh_radius_m",
                        "tune_direct_detection_task_active_refresh_window_s",
                        "tune_direct_detection_task_queued_cluster_radius_m",
                        "tune_direct_detection_task_queued_cluster_window_s",
                        "tune_alpha_inhib",
                        "tune_omega_inhib",
                        "proposed_enable_model_scored_deterring",
                        "proposed_enable_intervention_feedback",
                    }
                })
                run_kwargs.update(winner_profile_overrides)
                run_kwargs["telemetry_dir"] = f"telemetry_live_{exp_tag}"
                scenario_label = s["scenario_id"] if len(horizons_h) == 1 else f"{s['scenario_id']}_H{int(round(horizon_h)):02d}"
                jobs.append(
                    {
                        "exp_tag": exp_tag,
                        "scenario_id": scenario_label,
                        "tune_id": t["tune_id"],
                        "time_horizon_h": float(horizon_h),
                        "num_runs": num_runs,
                        "seed_start": seed_start,
                        "run_kwargs": run_kwargs,
                        "tune_beta_scale": t["tune_beta_scale"],
                        "tune_cost_scale": t["tune_cost_scale"],
                        "tune_det_window_s": t["tune_det_window_s"],
                        "tune_risk_threshold": t["tune_risk_threshold"],
                        "tune_risk_scale": t["tune_risk_scale"],
                        "tune_budget_per_hr": t["tune_budget_per_hr"],
                        "tune_min_recent_points": t["tune_min_recent_points"],
                        "tune_min_persistence_replans": t["tune_min_persistence_replans"],
                        "tune_score_margin": t["tune_score_margin"],
                        "tune_repeat_window_s": t["tune_repeat_window_s"],
                        "tune_repeat_radius_m": t["tune_repeat_radius_m"],
                        "tune_max_eta_s": t["tune_max_eta_s"],
                        "tune_busy_min_support_override": t["tune_busy_min_support_override"],
                        "tune_busy_risk_override": t["tune_busy_risk_override"],
                        "tune_max_active_tasks_per_robot": t["tune_max_active_tasks_per_robot"],
                        "tune_max_active_patrolling_per_robot": t["tune_max_active_patrolling_per_robot"],
                        "tune_max_active_model_deterring_per_robot": t["tune_max_active_model_deterring_per_robot"],
                        "tune_preempt_deterring_goals": t["tune_preempt_deterring_goals"],
                        "tune_preempt_direct_detection_goals": t.get("tune_preempt_direct_detection_goals", 1),
                        "tune_preempt_model_scored_goals": t.get("tune_preempt_model_scored_goals", 0),
                        "tune_intervention_boundary_min_interval_s": t.get("tune_intervention_boundary_min_interval_s", 60.0),
                        "tune_intervention_boundary_spatial_quant_m": t.get("tune_intervention_boundary_spatial_quant_m", 20.0),
                        "tune_intervention_boundary_min_weight": t.get("tune_intervention_boundary_min_weight", 0.35),
                        "tune_assigner_w_load": t["tune_assigner_w_load"],
                        "tune_gate_policy": str(t.get("tune_gate_policy", t.get("model_deterring_gate_policy", "heuristic"))),
                        "tune_patrol_hotspot_filter_mode": str(t.get("tune_patrol_hotspot_filter_mode", t.get("patrol_hotspot_filter_mode", "absolute"))),
                        "tune_patrol_hotspot_score_percentile": float(t.get("tune_patrol_hotspot_score_percentile", t.get("patrol_hotspot_score_percentile", float("nan")))),
                        "tune_patrol_hotspot_keep_top_k": str(t.get("tune_patrol_hotspot_keep_top_k", t.get("patrol_hotspot_keep_top_k", ""))),
                        "tune_patrol_feedback_inhibition_retention": float(t.get("tune_patrol_feedback_inhibition_retention", t.get("patrol_feedback_inhibition_retention", float("nan")))),
                        "tune_model_deterring_sprt_alpha": float(t.get("tune_model_deterring_sprt_alpha", t.get("model_deterring_sprt_alpha", float("nan")))),
                        "tune_model_deterring_sprt_beta": float(t.get("tune_model_deterring_sprt_beta", t.get("model_deterring_sprt_beta", float("nan")))),
                        "tune_model_deterring_sprt_patch_radius_m": float(t.get("tune_model_deterring_sprt_patch_radius_m", t.get("model_deterring_sprt_patch_radius_m", float("nan")))),
                        "tune_model_deterring_min_sprt_margin": float(t.get("tune_model_deterring_min_sprt_margin", t.get("model_deterring_min_sprt_margin", float("nan")))),
                        "tune_model_deterring_chance_threshold": float(t.get("tune_model_deterring_chance_threshold", t.get("model_deterring_chance_threshold", float("nan")))),
                        "tune_model_deterring_min_deltaJ_per_cost": float(t.get("tune_model_deterring_min_deltaJ_per_cost", t.get("model_deterring_min_deltaJ_per_cost", float("nan")))),
                        "tune_model_deterring_min_selection_weight": float(t.get("tune_model_deterring_min_selection_weight", t.get("model_deterring_min_selection_weight", float("nan")))),
                        "tune_model_deterring_capacity_rho_max": float(t.get("tune_model_deterring_capacity_rho_max", t.get("model_deterring_capacity_rho_max", float("nan")))),
                        "tune_model_deterring_global_admission_cap_per_cycle": int(t.get("tune_model_deterring_global_admission_cap_per_cycle", t.get("model_deterring_global_admission_cap_per_cycle", 0))),
                        "tune_model_deterring_require_idle_robot_for_admission": int(t.get("tune_model_deterring_require_idle_robot_for_admission", int(bool(t.get("model_deterring_require_idle_robot_for_admission", False))))),
                        "tune_model_deterring_prefer_idle_robots_for_assignment": int(t.get("tune_model_deterring_prefer_idle_robots_for_assignment", int(bool(t.get("model_deterring_prefer_idle_robots_for_assignment", False))))),
                        "tune_model_deterring_busy_fallback_p_event_min": float(t.get("tune_model_deterring_busy_fallback_p_event_min", t.get("model_deterring_busy_fallback_p_event_min", float("nan")))),
                        "tune_model_deterring_busy_fallback_deltaJ_per_cost_min": float(t.get("tune_model_deterring_busy_fallback_deltaJ_per_cost_min", t.get("model_deterring_busy_fallback_deltaJ_per_cost_min", float("nan")))),
                        "tune_model_deterring_busy_fallback_eta_s_max": float(t.get("tune_model_deterring_busy_fallback_eta_s_max", t.get("model_deterring_busy_fallback_eta_s_max", float("nan")))),
                        "tune_protect_direct_detection_from_model_deterring": int(t.get("tune_protect_direct_detection_from_model_deterring", int(bool(t.get("protect_direct_detection_from_model_deterring", False))))),
                        "tune_proposed_enable_model_scored_deterring": int(t.get("tune_proposed_enable_model_scored_deterring", int(bool(t.get("proposed_enable_model_scored_deterring", True))))),
                        "tune_proposed_enable_intervention_feedback": int(t.get("tune_proposed_enable_intervention_feedback", int(bool(t.get("proposed_enable_intervention_feedback", True))))),
                        "tune_enable_direct_detection_task_clustering": int(t.get("tune_enable_direct_detection_task_clustering", int(bool(t.get("enable_direct_detection_task_clustering", True))))),
                        "tune_direct_detection_task_cluster_radius_m": float(t.get("tune_direct_detection_task_cluster_radius_m", t.get("direct_detection_task_cluster_radius_m", float("nan")))),
                        "tune_direct_detection_task_cluster_window_s": float(t.get("tune_direct_detection_task_cluster_window_s", t.get("direct_detection_task_cluster_window_s", float("nan")))),
                        "tune_direct_detection_task_active_refresh_radius_m": float(t.get("tune_direct_detection_task_active_refresh_radius_m", t.get("direct_detection_task_active_refresh_radius_m", float("nan")))),
                        "tune_direct_detection_task_active_refresh_window_s": float(t.get("tune_direct_detection_task_active_refresh_window_s", t.get("direct_detection_task_active_refresh_window_s", float("nan")))),
                        "tune_direct_detection_task_queued_cluster_radius_m": float(t.get("tune_direct_detection_task_queued_cluster_radius_m", t.get("direct_detection_task_queued_cluster_radius_m", float("nan")))),
                        "tune_direct_detection_task_queued_cluster_window_s": float(t.get("tune_direct_detection_task_queued_cluster_window_s", t.get("direct_detection_task_queued_cluster_window_s", float("nan")))),
                        "tune_alpha_inhib": float(t.get("tune_alpha_inhib", t.get("alpha_inhib", float("nan")))),
                        "tune_omega_inhib": float(t.get("tune_omega_inhib", t.get("omega_inhib", float("nan")))),
                        "tune_enable_winner_profile": int(bool(args.enable_winner_profile)),
                        "tune_winner_profile_id": str(args.winner_profile_id),
                        "proposed_preventive_policy": str(args.proposed_preventive_policy),
                        "use_frozen_calibration": bool(args.use_frozen_calibration),
                        "calibration_ranking_path": str(args.calibration_ranking_path),
                        "calibration_manifest_path": str(args.calibration_manifest_path),
                        "calibration_config_id": str(args.calibration_config_id),
                        "time_metrics_period_s": float(args.time_metrics_period_s),
                    }
                )

    if args.limit_settings > 0:
        jobs = jobs[: int(args.limit_settings)]

    if not jobs:
        print(
            f"No jobs to run (profile={args.profile}, preset={args.tune_preset}, "
            f"scope={args.scenario_scope}, limit_settings={args.limit_settings})."
        )
        return

    run_dt = float(base_params.get("dt", dt))
    run_nx = int(base_params.get("NX", nx))
    run_ny = int(base_params.get("NY", ny))
    print(
        f"Launching {len(jobs)} settings | profile={args.profile} "
        f"| preset={args.tune_preset} | scope={args.scenario_scope} "
        f"| workers={max_workers} | runs={num_runs} | dt={run_dt} | grid={run_nx}x{run_ny}"
    )
    started = time.time()

    comparison_rows = []
    run_rows = []
    time_rows = []
    manifest_rows = []
    done = 0
    total = len(jobs)

    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_run_one_experiment, job) for job in jobs]
        for fut in as_completed(futures):
            out = fut.result()
            done += 1
            comparison_rows.extend(out["comparison_records"])
            run_rows.extend(out["run_rows"])
            time_rows.extend(out.get("time_rows", []))
            manifest_rows.append(out["manifest_row"])
            pct = 100.0 * done / max(total, 1)
            print(f"[parallel] {done}/{total} ({pct:.1f}%) complete: {out['exp_tag']}")

    comparison_df = pd.DataFrame(comparison_rows)
    runs_df = pd.DataFrame(run_rows)
    timeseries_df = pd.DataFrame(time_rows)
    manifest_df = pd.DataFrame(manifest_rows)

    profile_suffix = "_fast" if args.profile == "fast" else ""
    preset_suffix = "" if args.tune_preset == "full" else f"_{args.tune_preset}"
    suffix = f"{profile_suffix}{preset_suffix}"
    comparison_csv = f"baseline_comparison_24h_sweep_parallel{suffix}.csv"
    per_run_csv = f"baseline_runs_24h_sweep_parallel{suffix}.csv"
    time_csv = f"baseline_over_time_24h_sweep_parallel{suffix}.csv"
    manifest_csv = f"experiment_manifest_24h_sweep_parallel{suffix}.csv"
    resolved_config_json = f"resolved_config_24h_sweep_parallel{suffix}.json"
    comparison_df.to_csv(comparison_csv, index=False)
    runs_df.to_csv(per_run_csv, index=False)
    if not timeseries_df.empty:
        timeseries_df.to_csv(time_csv, index=False)
    manifest_df.to_csv(manifest_csv, index=False)
    write_resolved_config_manifest(
        resolved_config_json,
        script="experiments.run_24h_experiment_parallel.py",
        args=args,
        config_meta=config_meta,
        extra={
            "base_params": json.loads(json.dumps(base_params, default=str)),
            "requested_runtime_controls": dict(requested_runtime_controls),
            "winner_profile_overrides": json.loads(json.dumps(winner_profile_overrides, default=str)),
            "job_count": int(len(jobs)),
        },
    )

    # Match sequential pipeline: produce a combined summary + markdown report.
    summary_df = comparison_df.copy()
    if not runs_df.empty:
        run_counts = (
            runs_df.groupby(["exp_id", "scenario_id", "tune_id", "baseline"], as_index=False)
            .agg(
                n_runs=("run_idx", "nunique"),
                n_samples_response=("response_samples", "sum"),
                mean_completed_tasks=("completed_tasks_total", "mean"),
                mean_travel_ugv=("travel_distance_ugv", "mean"),
                mean_energy_ugv=("energy_ugv", "mean"),
            )
        )
        summary_df = summary_df.merge(
            run_counts,
            on=["exp_id", "scenario_id", "tune_id", "baseline"],
            how="left",
        )
        # Robustness stats (std + 95% CI) from per-run data.
        ci_group_cols = ["exp_id", "scenario_id", "tune_id", "time_horizon_h", "baseline"]
        ci_metrics = [
            "value_weighted_exposure",
            "mean_response_time_s",
            "boundary_message_count",
            "deterring_actions_completed_model_scored",
        ]
        for metric in ci_metrics:
            if metric not in runs_df.columns:
                continue
            stat = (
                runs_df.groupby(ci_group_cols, as_index=False)[metric]
                .agg(n="count", std="std")
                .rename(columns={"n": f"{metric}_n", "std": f"{metric}_std"})
            )
            stat[f"{metric}_ci95"] = 1.96 * stat[f"{metric}_std"] / stat[f"{metric}_n"].clip(lower=1).pow(0.5)
            summary_df = summary_df.merge(stat, on=ci_group_cols, how="left")
            mean_col = f"{metric}_mean"
            if mean_col in summary_df.columns:
                summary_df[f"{metric}_ci95_low"] = summary_df[mean_col] - summary_df[f"{metric}_ci95"]
                summary_df[f"{metric}_ci95_high"] = summary_df[mean_col] + summary_df[f"{metric}_ci95"]

        # Paired proposed-vs-prediction deltas with 95% CI (seed/run-index aligned).
        pair_metrics = [
            "value_weighted_exposure",
            "mean_response_time_s",
            "boundary_message_count",
            "deterring_actions_completed_model_scored",
        ]
        req_cols = {"exp_id", "scenario_id", "tune_id", "time_horizon_h", "baseline", "run_idx", "seed"} | set(pair_metrics)
        if req_cols.issubset(set(runs_df.columns)):
            pair = (
                runs_df[
                    ["exp_id", "scenario_id", "tune_id", "time_horizon_h", "baseline", "run_idx", "seed"] + pair_metrics
                ]
                .pivot_table(
                    index=["exp_id", "scenario_id", "tune_id", "time_horizon_h", "run_idx", "seed"],
                    columns="baseline",
                    values=pair_metrics,
                    aggfunc="first",
                )
                .reset_index()
            )
            pair.columns = [
                "_".join([str(c) for c in col if c != ""]).strip("_") if isinstance(col, tuple) else str(col)
                for col in pair.columns
            ]
            req_pair_cols = [
                "value_weighted_exposure_prediction_only",
                "value_weighted_exposure_proposed",
                "mean_response_time_s_prediction_only",
                "mean_response_time_s_proposed",
                "boundary_message_count_prediction_only",
                "boundary_message_count_proposed",
                "deterring_actions_completed_model_scored_prediction_only",
                "deterring_actions_completed_model_scored_proposed",
            ]
            if all(c in pair.columns for c in req_pair_cols):
                den_e = pair["value_weighted_exposure_prediction_only"].replace(0.0, pd.NA)
                den_r = pair["mean_response_time_s_prediction_only"].replace(0.0, pd.NA)
                den_c = pair["boundary_message_count_prediction_only"].replace(0.0, pd.NA)
                pair["delta_exp_improve_pct"] = (
                    100.0
                    * (pair["value_weighted_exposure_prediction_only"] - pair["value_weighted_exposure_proposed"])
                    / den_e
                )
                pair["delta_resp_improve_pct"] = (
                    100.0
                    * (pair["mean_response_time_s_prediction_only"] - pair["mean_response_time_s_proposed"])
                    / den_r
                )
                pair["delta_comm_increase_pct"] = (
                    100.0
                    * (pair["boundary_message_count_proposed"] - pair["boundary_message_count_prediction_only"])
                    / den_c
                )
                pair["delta_model_done_gain"] = (
                    pair["deterring_actions_completed_model_scored_proposed"]
                    - pair["deterring_actions_completed_model_scored_prediction_only"]
                )
                delta_cols = [
                    "delta_exp_improve_pct",
                    "delta_resp_improve_pct",
                    "delta_comm_increase_pct",
                    "delta_model_done_gain",
                ]
                delta_stat = (
                    pair.groupby(["exp_id", "scenario_id", "tune_id", "time_horizon_h"], as_index=False)[delta_cols]
                    .agg(["mean", "std", "count"])
                )
                delta_stat.columns = [
                    "_".join([str(c) for c in col if c != ""]).strip("_") if isinstance(col, tuple) else str(col)
                    for col in delta_stat.columns
                ]
                for dc in delta_cols:
                    ncol = f"{dc}_count"
                    stdcol = f"{dc}_std"
                    cicol = f"{dc}_ci95"
                    if ncol in delta_stat.columns and stdcol in delta_stat.columns:
                        delta_stat[cicol] = 1.96 * delta_stat[stdcol] / delta_stat[ncol].clip(lower=1).pow(0.5)
                        delta_stat[f"{dc}_ci95_low"] = delta_stat[f"{dc}_mean"] - delta_stat[cicol]
                        delta_stat[f"{dc}_ci95_high"] = delta_stat[f"{dc}_mean"] + delta_stat[cicol]
                summary_df = summary_df.merge(
                    delta_stat,
                    on=["exp_id", "scenario_id", "tune_id", "time_horizon_h"],
                    how="left",
                )

    summary_df["rank_exposure"] = (
        summary_df.groupby(["exp_id"])["value_weighted_exposure_mean"].rank(method="min", ascending=True).astype(int)
    )
    summary_df["rank_response"] = (
        summary_df.groupby(["exp_id"])["mean_response_time_s_mean"].rank(method="min", ascending=True).astype(int)
    )
    summary_df["rank_task_eff"] = (
        summary_df.groupby(["exp_id"])["tasks_per_unit_distance_mean"].rank(method="min", ascending=False).astype(int)
    )
    summary_df["rank_comm"] = (
        summary_df.groupby(["exp_id"])["boundary_message_count_mean"].rank(method="min", ascending=True).astype(int)
    )
    summary_df["composite_rank_score"] = (
        summary_df["rank_exposure"]
        + summary_df["rank_response"]
        + summary_df["rank_task_eff"]
        + summary_df["rank_comm"]
    )
    summary_df["rank_overall"] = (
        summary_df.groupby(["exp_id"])["composite_rank_score"].rank(method="min", ascending=True).astype(int)
    )

    final_summary_csv = f"thesis_summary_24h_sweep_parallel{suffix}.csv"
    final_summary_md = f"thesis_summary_24h_sweep_parallel{suffix}.md"
    summary_df = summary_df.sort_values(["exp_id", "rank_overall", "baseline"]).reset_index(drop=True)
    summary_df.to_csv(final_summary_csv, index=False)

    lines = []
    lines.append("# 24h Parallel Experiment Sweep Summary")
    lines.append("")
    lines.append(f"- Profile: {args.profile}")
    lines.append(f"- Total settings: {len(jobs)}")
    lines.append(f"- Runs per setting (per baseline): {num_runs}")
    lines.append(f"- Time horizons (h): {', '.join(str(int(h)) if float(h).is_integer() else f'{h:g}' for h in horizons_h)}")
    lines.append("")
    lines.append("## Best baseline per experiment setting")
    lines.append("")
    if not summary_df.empty:
        winners = summary_df[summary_df["rank_overall"] == 1].copy()
        winners = winners[
            [
                "exp_id",
                "scenario_id",
                "tune_id",
                "baseline",
                "value_weighted_exposure_mean",
                "mean_response_time_s_mean",
                "tasks_per_unit_distance_mean",
                "boundary_message_count_mean",
                "composite_rank_score",
            ]
        ]
        lines.append(winners.to_markdown(index=False))
    else:
        lines.append("_No data available._")
    lines.append("")
    if not summary_df.empty:
        lines.append("## Proposed vs Prediction-Only (Exposure Delta)")
        lines.append("")
        key_cols = ["exp_id", "scenario_id", "tune_id", "time_horizon_h"]
        p = summary_df[summary_df["baseline"] == "proposed"]
        q = summary_df[summary_df["baseline"] == "prediction_only"]
        pq = p.merge(
            q,
            on=key_cols,
            suffixes=("_proposed", "_prediction"),
            how="inner",
        )
        if not pq.empty:
            den = pq["value_weighted_exposure_mean_prediction"].replace(0.0, pd.NA)
            pq["exp_improve_pct_proposed_vs_prediction"] = (
                100.0 * (pq["value_weighted_exposure_mean_prediction"] - pq["value_weighted_exposure_mean_proposed"]) / den
            )
            den_r = pq["mean_response_time_s_mean_prediction"].replace(0.0, pd.NA)
            pq["resp_improve_pct_proposed_vs_prediction"] = (
                100.0 * (pq["mean_response_time_s_mean_prediction"] - pq["mean_response_time_s_mean_proposed"]) / den_r
            )
            den_c = pq["boundary_message_count_mean_prediction"].replace(0.0, pd.NA)
            pq["comm_increase_pct_proposed_vs_prediction"] = (
                100.0 * (pq["boundary_message_count_mean_proposed"] - pq["boundary_message_count_mean_prediction"]) / den_c
            )
            # Include robustness intervals when present (from paired run deltas).
            if "delta_exp_improve_pct_ci95" in p.columns:
                keep_delta = [
                    "exp_id",
                    "scenario_id",
                    "tune_id",
                    "time_horizon_h",
                    "delta_exp_improve_pct_mean",
                    "delta_exp_improve_pct_ci95",
                    "delta_resp_improve_pct_mean",
                    "delta_resp_improve_pct_ci95",
                    "delta_comm_increase_pct_mean",
                    "delta_comm_increase_pct_ci95",
                    "delta_model_done_gain_mean",
                    "delta_model_done_gain_ci95",
                ]
                keep_delta = [c for c in keep_delta if c in p.columns]
                if keep_delta:
                    pq = pq.merge(
                        p[keep_delta],
                        on=["exp_id", "scenario_id", "tune_id", "time_horizon_h"],
                        how="left",
                    )
            show_cols = [
                "exp_id",
                "scenario_id",
                "tune_id",
                "time_horizon_h",
                "exp_improve_pct_proposed_vs_prediction",
                "resp_improve_pct_proposed_vs_prediction",
                "comm_increase_pct_proposed_vs_prediction",
            ]
            ci_show = [
                "delta_exp_improve_pct_mean",
                "delta_exp_improve_pct_ci95",
                "delta_resp_improve_pct_mean",
                "delta_resp_improve_pct_ci95",
                "delta_comm_increase_pct_mean",
                "delta_comm_increase_pct_ci95",
                "delta_model_done_gain_mean",
                "delta_model_done_gain_ci95",
            ]
            show_cols.extend([c for c in ci_show if c in pq.columns])
            lines.append(pq[show_cols].sort_values(["scenario_id", "tune_id"]).round(3).to_markdown(index=False))
        else:
            lines.append("_No proposed/prediction pairing found._")
        lines.append("")
    if not summary_df.empty and ("truth_suppression_rate_mean" in summary_df.columns):
        lines.append("## Truth Suppression Diagnostics")
        lines.append("")
        cols = ["scenario_id", "time_horizon_h", "baseline"]
        agg_cols = {
            "value_weighted_exposure_mean": "mean",
            "mean_response_time_s_mean": "mean",
            "boundary_message_count_mean": "mean",
            "truth_suppression_rate_mean": "mean",
            "truth_suppression_effect_mean_mean": "mean",
            "model_deterring_accepted_mean": "mean",
        }
        for c in list(agg_cols.keys()):
            if c not in summary_df.columns:
                agg_cols.pop(c, None)
        if agg_cols:
            diag = summary_df.groupby(cols, as_index=False).agg(agg_cols).sort_values(cols)
            lines.append(diag.round(4).to_markdown(index=False))
        else:
            lines.append("_Truth suppression columns not available in this run._")
        lines.append("")
    if not summary_df.empty and ("model_deterring_candidates_total_mean" in summary_df.columns):
        lines.append("## Preventive Deterring Funnel (Model-Scored)")
        lines.append("")
        cols = ["scenario_id", "time_horizon_h", "baseline"]
        funnel_cols = [
            "model_deterring_candidates_total_mean",
            "model_deterring_rejected_cooldown_mean",
            "model_deterring_rejected_field_mean",
            "model_deterring_pass_field_mean",
            "model_deterring_rejected_risk_mean",
            "model_deterring_pass_risk_mean",
            "model_deterring_rejected_support_mean",
            "model_deterring_pass_support_mean",
            "model_deterring_rejected_persistence_mean",
            "model_deterring_pass_sprt_mean",
            "model_deterring_rejected_sprt_pending_mean",
            "model_deterring_rejected_sprt_negative_mean",
            "model_deterring_pass_chance_mean",
            "model_deterring_rejected_chance_mean",
            "model_deterring_pass_utility_ratio_mean",
            "model_deterring_rejected_utility_ratio_mean",
            "model_deterring_pass_capacity_mean",
            "model_deterring_rejected_capacity_mean",
            "model_deterring_llr_mean_mean",
            "model_deterring_llr_p50_mean",
            "model_deterring_llr_p75_mean",
            "model_deterring_llr_p90_mean",
            "model_deterring_p_event_mean_mean",
            "model_deterring_deltaJ_per_cost_mean_mean",
            "model_deterring_cluster_key_total_mean",
            "model_deterring_cluster_key_reused_mean",
            "model_deterring_cluster_key_churn_mean",
            "model_deterring_cluster_key_new_mean",
            "model_deterring_rejected_repeat_no_new_support_mean",
            "model_deterring_rejected_eta_mean",
            "model_deterring_rejected_busy_mean",
            "model_deterring_rejected_margin_mean",
            "model_deterring_not_selected_mean",
            "model_deterring_rejected_budget_mean",
            "model_deterring_accepted_mean",
            "model_deterring_generated_mean",
        ]
        keep = [c for c in funnel_cols if c in summary_df.columns]
        if keep:
            ftab = summary_df[cols + keep].sort_values(cols)
            lines.append(ftab.round(3).to_markdown(index=False))
        else:
            lines.append("_Funnel columns not available in this run._")
        lines.append("")
    if not summary_df.empty and ("deterring_action_precision_mean" in summary_df.columns):
        lines.append("## Deterring Action Quality")
        lines.append("")
        cols = ["scenario_id", "time_horizon_h", "baseline"]
        q_cols = [
            "deterring_actions_completed_total_mean",
            "deterring_actions_completed_direct_detection_mean",
            "deterring_actions_completed_model_scored_mean",
            "deterring_action_precision_mean",
            "deterring_action_precision_direct_detection_mean",
            "deterring_action_precision_model_scored_mean",
            "suppression_per_deterring_action_mean",
            "suppression_per_direct_deterring_action_mean",
            "suppression_per_model_deterring_action_mean",
            "model_vs_direct_suppression_yield_ratio_mean",
        ]
        keep = [c for c in q_cols if c in summary_df.columns]
        if keep:
            qtab = summary_df[cols + keep].sort_values(cols)
            lines.append(qtab.round(4).to_markdown(index=False))
        else:
            lines.append("_Action-quality columns not available in this run._")
        lines.append("")
    if not summary_df.empty and ("planner_rejected_task_cap_mean" in summary_df.columns):
        lines.append("## Planner/Dispatch Admission Diagnostics")
        lines.append("")
        cols = ["scenario_id", "time_horizon_h", "baseline"]
        p_cols = [
            "planner_rejected_unassigned_mean",
            "planner_rejected_task_cap_mean",
            "planner_rejected_patrol_cap_mean",
            "planner_rejected_model_det_cap_mean",
            "planner_rejected_model_det_cycle_cap_mean",
            "planner_rejected_model_det_busy_primary_mean",
            "planner_rejected_model_det_busy_fallback_quality_mean",
            "planner_rejected_model_det_direct_conflict_mean",
            "planner_accepted_model_det_idle_primary_mean",
            "planner_accepted_model_det_busy_primary_mean",
            "planner_replaced_patrol_mean",
        ]
        keep = [c for c in p_cols if c in summary_df.columns]
        if keep:
            ptab = summary_df[cols + keep].sort_values(cols)
            lines.append(ptab.round(3).to_markdown(index=False))
        else:
            lines.append("_Planner/dispatch columns not available in this run._")
        lines.append("")
    if not summary_df.empty and ("intervention_msg_dropped_debounce_mean" in summary_df.columns):
        lines.append("## Intervention Boundary Message Gating Diagnostics")
        lines.append("")
        cols = ["scenario_id", "time_horizon_h", "baseline"]
        g_cols = [
            "boundary_message_count_mean",
            "intervention_msg_dropped_debounce_mean",
            "intervention_msg_dropped_low_weight_mean",
        ]
        keep = [c for c in g_cols if c in summary_df.columns]
        if keep:
            gtab = summary_df[cols + keep].sort_values(cols)
            lines.append(gtab.round(3).to_markdown(index=False))
        else:
            lines.append("_Intervention message gating columns not available in this run._")
        lines.append("")
    lines.append("## Output files")
    lines.append("")
    lines.append(f"- `{comparison_csv}`: baseline-level mean/variance per setting")
    lines.append(f"- `{per_run_csv}`: per-run metrics")
    if not timeseries_df.empty:
        lines.append(f"- `{time_csv}`: baseline metrics over time (mean/var curves)")
    lines.append(f"- `{manifest_csv}`: full parameter manifest")
    lines.append(f"- `{resolved_config_json}`: resolved runner config and config-file provenance")
    lines.append(f"- `{final_summary_csv}`: combined thesis-ready summary table")
    with open(final_summary_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("\nSaved files:")
    print(f"- {comparison_csv}")
    print(f"- {per_run_csv}")
    if not timeseries_df.empty:
        print(f"- {time_csv}")
    print(f"- {manifest_csv}")
    print(f"- {resolved_config_json}")
    print(f"- {final_summary_csv}")
    print(f"- {final_summary_md}")
    print(f"Wall time: {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()
