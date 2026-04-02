from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import itertools
import json
import os
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

import DeterrentSystem_assignment_lab as ds
from config_loader import add_config_argument, parse_args_with_config
from planner_profiles import apply_planner_profile_defaults, explicit_cli_dests
from run_assignment_method_comparison_lab import _baseline_cfg
from thesis_experiment_workflow import render_execution_order_lines, render_stage_readme_lines, stage_manifest


DEFAULT_BASELINES = ["prediction_only", "proposed"]
DEFAULT_METHODS = ["hungarian"]
METHOD_DELTA_COLUMNS = [
    "scenario_id",
    "baseline",
    "assignment_method",
    "delta_exposure_pct_mean",
    "delta_response_pct_mean",
    "delta_comm_pct_mean",
]
ASSIGNMENT_TUNING_CONFIG_ALIASES = {
    "runner.stage": "stage",
    "runner.num_runs": "num_runs",
    "runner.seed_start": "seed_start",
    "runner.t_end": "t_end",
    "runner.dt": "dt",
    "runner.baselines": "baselines",
    "runner.methods": "methods",
    "runner.outdir": "outdir",
    "runner.resume": "resume",
    "runner.checkpoint_path": "checkpoint_path",
    "runner.max_workers": "max_workers",
    "planner.profile": "planner_profile",
    "planner.distance_costs": "distance_costs",
    "planner.switch_penalties": "switch_penalties",
    "planner.replan_periods": "replan_periods",
    "planner.assigner_w_task_values": "assigner_w_task_values",
    "gating.gate_policies": "gate_policies",
    "gating.sprt_alpha_values": "sprt_alpha_values",
    "gating.sprt_beta_values": "sprt_beta_values",
    "gating.chance_threshold_values": "chance_threshold_values",
    "gating.min_deltaj_per_cost_values": "min_deltaj_per_cost_values",
    "gating.capacity_rho_max_values": "capacity_rho_max_values",
    "gating.risk_thresholds": "risk_thresholds",
    "gating.min_persistence_replans": "min_persistence_replans",
    "gating.max_eta_values": "max_eta_values",
    "gating.score_margin_values": "score_margin_values",
    "gating.budget_per_hr": "budget_per_hr",
    "gating.budget_modes": "budget_modes",
    "gating.budget_utility_per_hr": "budget_utility_per_hr",
    "gating.deterring_windows": "deterring_windows",
    "gating.min_predicted_deltaj_values": "min_predicted_deltaj_values",
    "ground_truth.beta_true_values": "beta_true_values",
    "inputs.phase1_manifest": "phase1_manifest",
    "inputs.use_phase1_winner": "use_phase1_winner",
}


ASSIGNMENT_TUNING_PROFILE_DEST_MAP = {
    "assigner_w_task_value": "assigner_w_task_values",
    "model_deterring_window_s": "deterring_windows",
    "model_deterring_min_persistence_replans": "min_persistence_replans",
    "model_deterring_max_eta_s": "max_eta_values",
    "model_deterring_score_margin": "score_margin_values",
    "model_deterring_budget_per_robot_per_hr": "budget_per_hr",
    "model_deterring_budget_mode": "budget_modes",
    "model_deterring_budget_utility_per_robot_per_hr": "budget_utility_per_hr",
    "model_deterring_gate_policy": "gate_policies",
    "model_deterring_chance_threshold": "chance_threshold_values",
    "model_deterring_min_deltaJ_per_cost": "min_deltaj_per_cost_values",
}


ASSIGNMENT_TUNING_SUBSTAGE_NOTES = {
    "phase1": "Screen dispatch distance cost, switch penalty, and replan cadence to pick the fixed Hungarian dispatch setting.",
    "phase2": "Hold the phase-1 Hungarian dispatch fixed and sweep persistence, ETA, budget, and support controls for robust planner behavior.",
    "phase4": "Compare gate-policy families with the tuned dispatch frozen so only the downstream planner logic changes.",
    "phase4_refine": "Refine the final SPRT / chance / utility thresholds around the best gated planner region.",
}


def _parse_float_list(txt: str) -> List[float]:
    return [float(x.strip()) for x in str(txt).split(",") if x.strip()]


def _parse_int_list(txt: str) -> List[int]:
    return [int(float(x.strip())) for x in str(txt).split(",") if x.strip()]


def _parse_str_list(txt: str) -> List[str]:
    return [x.strip() for x in str(txt).split(",") if x.strip()]


def _ci95(series: pd.Series) -> float:
    x = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    n = x.size
    if n <= 1:
        return float("nan")
    return float(1.96 * np.std(x, ddof=1) / np.sqrt(n))


def _stats(df: pd.DataFrame, col: str) -> dict:
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    if len(s) == 0:
        return {"mean": float("nan"), "std": float("nan"), "ci95": float("nan"), "n": 0}
    return {
        "mean": float(s.mean()),
        "std": float(s.std(ddof=1)) if len(s) > 1 else 0.0,
        "ci95": _ci95(s),
        "n": int(len(s)),
    }


def _nanmean_or_nan(values) -> float:
    s = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    if len(s) == 0:
        return float("nan")
    return float(s.mean())


def _build_base_params(t_end: float, dt: float) -> dict:
    return {
        "W": 500.0,
        "H": 500.0,
        "NX": 80,
        "NY": 64,
        "Nrobots": 6,
        "uav_fraction": 0.0,
        "warmup_s": 1800.0,
        "forecast_horizon_s": 300.0,
        "forecast_match_radius_m": 20.0,
        "forecast_top_k": 5,
        "forecast_eval_period_s": 30.0,
        "task_replan_period_s": 45.0,
        "model_deterring_window_s": 90.0,
        "model_deterring_risk_threshold": 0.35,
        "model_deterring_min_persistence_replans": 2,
        "model_deterring_max_eta_s": 120.0,
        "model_deterring_score_margin": 0.05,
        "model_deterring_budget_per_robot_per_hr": 4,
        "model_deterring_min_recent_points": 1,
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
        "collect_time_metrics": False,
        "T_end": float(t_end),
        "dt": float(dt),
    }


def _empty_runs_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "scenario_id",
            "assignment_distance_cost_per_m",
            "assignment_switch_penalty",
            "task_replan_period_s",
            "assigner_w_task_value",
            "model_deterring_gate_policy",
            "model_deterring_sprt_alpha",
            "model_deterring_sprt_beta",
            "model_deterring_chance_threshold",
            "model_deterring_min_deltaJ_per_cost",
            "model_deterring_capacity_rho_max",
            "model_deterring_budget_mode",
            "model_deterring_budget_utility_per_robot_per_hr",
            "model_deterring_risk_threshold",
            "model_deterring_min_persistence_replans",
            "model_deterring_max_eta_s",
            "model_deterring_score_margin",
            "model_deterring_budget_per_robot_per_hr",
            "model_deterring_window_s",
            "min_predicted_deltaJ_for_model_deterring",
            "beta_true",
            "baseline",
            "assignment_method",
            "seed",
            "run_idx",
            "value_weighted_exposure",
            "mean_response_time_s",
            "boundary_message_count",
            "boundary_bytes_sent",
            "tasks_per_unit_distance",
            "predicted_deltaJ_sum",
            "realized_suppression_sum",
            "yield_ratio_total",
            "yield_ratio_direct_detection",
            "yield_ratio_model_scored",
            "queue_depth_total_mean",
            "queue_depth_patrolling_mean",
            "queue_depth_deterring_mean",
            "queue_depth_model_deterring_mean",
            "queue_depth_total_max",
            "queue_depth_patrolling_max",
            "queue_depth_deterring_max",
            "queue_depth_model_deterring_max",
            "stale_task_evictions_count",
            "robot_moving_fraction_mean",
            "robot_active_task_fraction_mean",
            "model_deterring_accepted",
            "model_deterring_generated",
            "model_deterring_candidates_total",
            "model_deterring_rejected_cooldown",
            "model_deterring_rejected_field",
            "model_deterring_pass_field",
            "model_deterring_pass_predicted_deltaJ",
            "model_deterring_pass_risk",
            "model_deterring_pass_support",
            "model_deterring_rejected_risk",
            "model_deterring_rejected_support",
            "model_deterring_rejected_persistence",
            "model_deterring_rejected_repeat_no_new_support",
            "model_deterring_rejected_margin",
            "model_deterring_rejected_eta",
            "model_deterring_rejected_busy",
            "model_deterring_rejected_budget",
            "model_deterring_rejected_predicted_deltaJ",
            "model_deterring_rejected_budget_count_mode",
            "model_deterring_rejected_budget_utility_mode",
            "model_deterring_pass_sprt",
            "model_deterring_rejected_sprt_pending",
            "model_deterring_rejected_sprt_negative",
            "model_deterring_pass_chance",
            "model_deterring_rejected_chance",
            "model_deterring_pass_utility_ratio",
            "model_deterring_rejected_utility_ratio",
            "model_deterring_pass_capacity",
            "model_deterring_rejected_capacity",
            "model_deterring_llr_mean",
            "model_deterring_llr_max",
            "model_deterring_p_event_mean",
            "model_deterring_deltaJ_per_cost_mean",
            "preventive_service_rate_per_robot_mean",
            "preventive_direct_arrival_rate_per_robot_mean",
            "preventive_capacity_remaining_per_robot_mean",
            "model_deterring_budget_spent_count_per_robot_hr_mean",
            "model_deterring_budget_spent_count_per_robot_hr_max",
            "model_deterring_budget_spent_utility_per_robot_hr_mean",
            "model_deterring_budget_spent_utility_per_robot_hr_max",
            "planner_replaced_low_utility_count",
            "assigned_task_value_mean",
            "assignment_solver_runtime_ms",
            "assignment_solver_assigned_mean",
            "assignment_solver_objective_mean",
            "assignment_solver_calls",
            "assignment_solver_conflicts_resolved",
            "assignment_solver_unassigned",
            "assignment_solver_rounds_mean",
            "assignment_solver_bid_updates",
            "assignment_solver_message_passes",
            "assignment_solver_failures",
            "assignment_solver_feasible_edge_rate",
            "model_deterring_calibration_bin_0_count",
            "model_deterring_calibration_bin_0_hits",
            "model_deterring_calibration_bin_0_hit_rate",
            "model_deterring_calibration_bin_1_count",
            "model_deterring_calibration_bin_1_hits",
            "model_deterring_calibration_bin_1_hit_rate",
            "model_deterring_calibration_bin_2_count",
            "model_deterring_calibration_bin_2_hits",
            "model_deterring_calibration_bin_2_hit_rate",
            "model_deterring_calibration_bin_3_count",
            "model_deterring_calibration_bin_3_hits",
            "model_deterring_calibration_bin_3_hit_rate",
            "model_deterring_calibration_bin_4_count",
            "model_deterring_calibration_bin_4_hits",
            "model_deterring_calibration_bin_4_hit_rate",
        ]
    )


def _load_checkpoint(path: Path) -> pd.DataFrame:
    if path.exists():
        try:
            df = pd.read_csv(path)
            return df
        except Exception:
            return _empty_runs_df()
    return _empty_runs_df()


def _write_checkpoint(path: Path, runs_df: pd.DataFrame, progress: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    runs_df.to_csv(path, index=False)
    progress_path = path.with_suffix(".progress.json")
    progress_path.write_text(json.dumps(progress, indent=2), encoding="utf-8")


def _pair_complete(
    runs_df: pd.DataFrame,
    scenario_id: str,
    baseline: str,
    method: str,
    num_runs: int,
) -> bool:
    if runs_df.empty:
        return False
    sub = runs_df[
        (runs_df["scenario_id"] == scenario_id)
        & (runs_df["baseline"] == baseline)
        & (runs_df["assignment_method"] == method)
    ]
    if len(sub) < int(num_runs):
        return False
    seeds = sorted(pd.to_numeric(sub["seed"], errors="coerce").dropna().astype(int).unique().tolist())
    return len(seeds) >= int(num_runs)


def _drop_pair_rows(runs_df: pd.DataFrame, scenario_id: str, baseline: str, method: str) -> pd.DataFrame:
    if runs_df.empty:
        return runs_df
    keep = ~(
        (runs_df["scenario_id"] == scenario_id)
        & (runs_df["baseline"] == baseline)
        & (runs_df["assignment_method"] == method)
    )
    return runs_df[keep].copy()


def _run_combo_job(payload: dict) -> dict:
    # Worker entrypoint: keep top-level for Windows multiprocessing pickling.
    baseline = str(payload["baseline"])
    method = str(payload["method"])
    c_dist = float(payload["assignment_distance_cost_per_m"])
    c_switch = float(payload["assignment_switch_penalty"])
    replan_s = float(payload["task_replan_period_s"])
    w_task_value = float(payload["assigner_w_task_value"])
    gate_policy = str(payload["model_deterring_gate_policy"])
    sprt_alpha = float(payload["model_deterring_sprt_alpha"])
    sprt_beta = float(payload["model_deterring_sprt_beta"])
    chance_threshold = float(payload["model_deterring_chance_threshold"])
    min_deltaj_per_cost = float(payload["model_deterring_min_deltaJ_per_cost"])
    capacity_rho_max = float(payload["model_deterring_capacity_rho_max"])
    risk_th = float(payload["model_deterring_risk_threshold"])
    min_persist = int(payload["model_deterring_min_persistence_replans"])
    max_eta_s = float(payload["model_deterring_max_eta_s"])
    score_margin = float(payload["model_deterring_score_margin"])
    budget_hr = int(payload["model_deterring_budget_per_robot_per_hr"])
    budget_mode = str(payload["model_deterring_budget_mode"])
    budget_utility_hr = float(payload["model_deterring_budget_utility_per_robot_per_hr"])
    det_window_s = float(payload["model_deterring_window_s"])
    min_pred_dj = float(payload["min_predicted_deltaJ_for_model_deterring"])
    beta_true = float(payload["beta_true"])
    scenario_id = str(payload["scenario_id"])

    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    kwargs = dict(payload["base_params"])
    kwargs.update(_baseline_cfg(baseline))
    kwargs.update(
        {
            "assignment_method": method,
            "assignment_distance_cost_per_m": c_dist,
            "assignment_switch_penalty": c_switch,
            "task_replan_period_s": replan_s,
            "assigner_w_task_value": w_task_value,
            "model_deterring_gate_policy": gate_policy,
            "model_deterring_sprt_alpha": sprt_alpha,
            "model_deterring_sprt_beta": sprt_beta,
            "model_deterring_chance_threshold": chance_threshold,
            "model_deterring_min_deltaJ_per_cost": min_deltaj_per_cost,
            "model_deterring_capacity_rho_max": capacity_rho_max,
            "model_deterring_risk_threshold": risk_th,
            "model_deterring_min_persistence_replans": min_persist,
            "model_deterring_max_eta_s": max_eta_s,
            "model_deterring_score_margin": score_margin,
            "model_deterring_budget_per_robot_per_hr": budget_hr,
            "model_deterring_budget_mode": budget_mode,
            "model_deterring_budget_utility_per_robot_per_hr": budget_utility_hr,
            "model_deterring_window_s": det_window_s,
            "min_predicted_deltaJ_for_model_deterring": min_pred_dj,
            "beta_true": beta_true,
        }
    )

    out = ds.run_metrics_experiments(
        num_runs=int(payload["num_runs"]),
        seed_start=int(payload["seed_start"]),
        report_each_run=False,
        **kwargs,
    )

    rows: List[dict] = []
    run_list = list(out.get("runs", []))
    for run_i, m in enumerate(run_list):
        seed = int(payload["seed_start"]) + int(run_i)
        rows.append(
            {
                "scenario_id": scenario_id,
                "assignment_distance_cost_per_m": c_dist,
                "assignment_switch_penalty": c_switch,
                "task_replan_period_s": replan_s,
                "assigner_w_task_value": w_task_value,
                "model_deterring_gate_policy": gate_policy,
                "model_deterring_sprt_alpha": sprt_alpha,
                "model_deterring_sprt_beta": sprt_beta,
                "model_deterring_chance_threshold": chance_threshold,
                "model_deterring_min_deltaJ_per_cost": min_deltaj_per_cost,
                "model_deterring_capacity_rho_max": capacity_rho_max,
                "model_deterring_risk_threshold": risk_th,
                "model_deterring_min_persistence_replans": min_persist,
                "model_deterring_max_eta_s": max_eta_s,
                "model_deterring_score_margin": score_margin,
                "model_deterring_budget_per_robot_per_hr": budget_hr,
                "model_deterring_budget_mode": budget_mode,
                "model_deterring_budget_utility_per_robot_per_hr": budget_utility_hr,
                "model_deterring_window_s": det_window_s,
                "min_predicted_deltaJ_for_model_deterring": min_pred_dj,
                "beta_true": beta_true,
                "baseline": baseline,
                "assignment_method": method,
                "seed": int(seed),
                "run_idx": int(run_i),
                "value_weighted_exposure": float(m.get("value_weighted_exposure", np.nan)),
                "mean_response_time_s": float(m.get("mean_response_time_s", np.nan)),
                "boundary_message_count": float(m.get("boundary_message_count", np.nan)),
                "boundary_bytes_sent": float(m.get("boundary_bytes_sent", np.nan)),
                "tasks_per_unit_distance": float(m.get("tasks_per_unit_distance", np.nan)),
                "predicted_deltaJ_sum": float(m.get("predicted_deltaJ_sum", np.nan)),
                "realized_suppression_sum": float(m.get("realized_suppression_sum", np.nan)),
                "yield_ratio_total": float(m.get("yield_ratio_total", np.nan)),
                "yield_ratio_direct_detection": float(m.get("yield_ratio_direct_detection", np.nan)),
                "yield_ratio_model_scored": float(m.get("yield_ratio_model_scored", np.nan)),
                "queue_depth_total_mean": float(m.get("queue_depth_total_mean", np.nan)),
                "queue_depth_patrolling_mean": float(m.get("queue_depth_patrolling_mean", np.nan)),
                "queue_depth_deterring_mean": float(m.get("queue_depth_deterring_mean", np.nan)),
                "queue_depth_model_deterring_mean": float(m.get("queue_depth_model_deterring_mean", np.nan)),
                "queue_depth_total_max": float(m.get("queue_depth_total_max", np.nan)),
                "queue_depth_patrolling_max": float(m.get("queue_depth_patrolling_max", np.nan)),
                "queue_depth_deterring_max": float(m.get("queue_depth_deterring_max", np.nan)),
                "queue_depth_model_deterring_max": float(m.get("queue_depth_model_deterring_max", np.nan)),
                "stale_task_evictions_count": float(m.get("stale_task_evictions_count", np.nan)),
                "robot_moving_fraction_mean": float(m.get("robot_moving_fraction_mean", np.nan)),
                "robot_active_task_fraction_mean": float(m.get("robot_active_task_fraction_mean", np.nan)),
                "model_deterring_accepted": float(m.get("model_deterring_accepted", np.nan)),
                "model_deterring_generated": float(m.get("model_deterring_generated", np.nan)),
                "model_deterring_candidates_total": float(m.get("model_deterring_candidates_total", np.nan)),
                "model_deterring_rejected_cooldown": float(m.get("model_deterring_rejected_cooldown", np.nan)),
                "model_deterring_rejected_field": float(m.get("model_deterring_rejected_field", np.nan)),
                "model_deterring_pass_field": float(m.get("model_deterring_pass_field", np.nan)),
                "model_deterring_rejected_predicted_deltaJ": float(
                    m.get("model_deterring_rejected_predicted_deltaJ", np.nan)
                ),
                "model_deterring_pass_predicted_deltaJ": float(m.get("model_deterring_pass_predicted_deltaJ", np.nan)),
                "model_deterring_pass_risk": float(m.get("model_deterring_pass_risk", np.nan)),
                "model_deterring_pass_support": float(m.get("model_deterring_pass_support", np.nan)),
                "model_deterring_rejected_risk": float(m.get("model_deterring_rejected_risk", np.nan)),
                "model_deterring_rejected_support": float(m.get("model_deterring_rejected_support", np.nan)),
                "model_deterring_rejected_persistence": float(m.get("model_deterring_rejected_persistence", np.nan)),
                "model_deterring_rejected_repeat_no_new_support": float(m.get("model_deterring_rejected_repeat_no_new_support", np.nan)),
                "model_deterring_rejected_margin": float(m.get("model_deterring_rejected_margin", np.nan)),
                "model_deterring_rejected_eta": float(m.get("model_deterring_rejected_eta", np.nan)),
                "model_deterring_rejected_busy": float(m.get("model_deterring_rejected_busy", np.nan)),
                "model_deterring_rejected_budget": float(m.get("model_deterring_rejected_budget", np.nan)),
                "model_deterring_pass_sprt": float(m.get("model_deterring_pass_sprt", np.nan)),
                "model_deterring_rejected_sprt_pending": float(m.get("model_deterring_rejected_sprt_pending", np.nan)),
                "model_deterring_rejected_sprt_negative": float(m.get("model_deterring_rejected_sprt_negative", np.nan)),
                "model_deterring_pass_chance": float(m.get("model_deterring_pass_chance", np.nan)),
                "model_deterring_rejected_chance": float(m.get("model_deterring_rejected_chance", np.nan)),
                "model_deterring_pass_utility_ratio": float(m.get("model_deterring_pass_utility_ratio", np.nan)),
                "model_deterring_rejected_utility_ratio": float(m.get("model_deterring_rejected_utility_ratio", np.nan)),
                "model_deterring_pass_capacity": float(m.get("model_deterring_pass_capacity", np.nan)),
                "model_deterring_rejected_capacity": float(m.get("model_deterring_rejected_capacity", np.nan)),
                "model_deterring_llr_mean": float(m.get("model_deterring_llr_mean", np.nan)),
                "model_deterring_llr_max": float(m.get("model_deterring_llr_max", np.nan)),
                "model_deterring_p_event_mean": float(m.get("model_deterring_p_event_mean", np.nan)),
                "model_deterring_deltaJ_per_cost_mean": float(m.get("model_deterring_deltaJ_per_cost_mean", np.nan)),
                "preventive_service_rate_per_robot_mean": float(m.get("preventive_service_rate_per_robot_mean", np.nan)),
                "preventive_direct_arrival_rate_per_robot_mean": float(m.get("preventive_direct_arrival_rate_per_robot_mean", np.nan)),
                "preventive_capacity_remaining_per_robot_mean": float(m.get("preventive_capacity_remaining_per_robot_mean", np.nan)),
                "planner_replaced_low_utility_count": float(m.get("planner_replaced_low_utility_count", np.nan)),
                "assigned_task_value_mean": float(m.get("assigned_task_value_mean", np.nan)),
                "model_deterring_rejected_budget_count_mode": float(
                    m.get("model_deterring_rejected_budget_count_mode", np.nan)
                ),
                "model_deterring_rejected_budget_utility_mode": float(
                    m.get("model_deterring_rejected_budget_utility_mode", np.nan)
                ),
                "model_deterring_budget_spent_count_per_robot_hr_mean": float(
                    m.get("model_deterring_budget_spent_count_per_robot_hr_mean", np.nan)
                ),
                "model_deterring_budget_spent_count_per_robot_hr_max": float(
                    m.get("model_deterring_budget_spent_count_per_robot_hr_max", np.nan)
                ),
                "model_deterring_budget_spent_utility_per_robot_hr_mean": float(
                    m.get("model_deterring_budget_spent_utility_per_robot_hr_mean", np.nan)
                ),
                "model_deterring_budget_spent_utility_per_robot_hr_max": float(
                    m.get("model_deterring_budget_spent_utility_per_robot_hr_max", np.nan)
                ),
                "assignment_solver_runtime_ms": float(m.get("assignment_solver_runtime_ms", np.nan)),
                "assignment_solver_assigned_mean": float(m.get("assignment_solver_assigned_mean", np.nan)),
                "assignment_solver_objective_mean": float(m.get("assignment_solver_objective_mean", np.nan)),
                "assignment_solver_calls": float(m.get("assignment_solver_calls", np.nan)),
                "assignment_solver_conflicts_resolved": float(m.get("assignment_solver_conflicts_resolved", np.nan)),
                "assignment_solver_unassigned": float(m.get("assignment_solver_unassigned", np.nan)),
                "assignment_solver_rounds_mean": float(m.get("assignment_solver_rounds_mean", np.nan)),
                "assignment_solver_bid_updates": float(m.get("assignment_solver_bid_updates", np.nan)),
                "assignment_solver_message_passes": float(m.get("assignment_solver_message_passes", np.nan)),
                "assignment_solver_failures": float(m.get("assignment_solver_failures", np.nan)),
                "assignment_solver_feasible_edge_rate": float(m.get("assignment_solver_feasible_edge_rate", np.nan)),
                "model_deterring_calibration_bin_0_count": float(m.get("model_deterring_calibration_bin_0_count", np.nan)),
                "model_deterring_calibration_bin_0_hits": float(m.get("model_deterring_calibration_bin_0_hits", np.nan)),
                "model_deterring_calibration_bin_0_hit_rate": float(m.get("model_deterring_calibration_bin_0_hit_rate", np.nan)),
                "model_deterring_calibration_bin_1_count": float(m.get("model_deterring_calibration_bin_1_count", np.nan)),
                "model_deterring_calibration_bin_1_hits": float(m.get("model_deterring_calibration_bin_1_hits", np.nan)),
                "model_deterring_calibration_bin_1_hit_rate": float(m.get("model_deterring_calibration_bin_1_hit_rate", np.nan)),
                "model_deterring_calibration_bin_2_count": float(m.get("model_deterring_calibration_bin_2_count", np.nan)),
                "model_deterring_calibration_bin_2_hits": float(m.get("model_deterring_calibration_bin_2_hits", np.nan)),
                "model_deterring_calibration_bin_2_hit_rate": float(m.get("model_deterring_calibration_bin_2_hit_rate", np.nan)),
                "model_deterring_calibration_bin_3_count": float(m.get("model_deterring_calibration_bin_3_count", np.nan)),
                "model_deterring_calibration_bin_3_hits": float(m.get("model_deterring_calibration_bin_3_hits", np.nan)),
                "model_deterring_calibration_bin_3_hit_rate": float(m.get("model_deterring_calibration_bin_3_hit_rate", np.nan)),
                "model_deterring_calibration_bin_4_count": float(m.get("model_deterring_calibration_bin_4_count", np.nan)),
                "model_deterring_calibration_bin_4_hits": float(m.get("model_deterring_calibration_bin_4_hits", np.nan)),
                "model_deterring_calibration_bin_4_hit_rate": float(m.get("model_deterring_calibration_bin_4_hit_rate", np.nan)),
            }
        )
    return {
        "scenario_id": scenario_id,
        "baseline": baseline,
        "assignment_method": method,
        "rows": rows,
    }


def run_sweep(
    num_runs: int,
    seed_start: int,
    baselines: List[str],
    methods: List[str],
    distance_costs: List[float],
    switch_penalties: List[float],
    replan_periods_s: List[int],
    assigner_w_task_values: List[float],
    gate_policies: List[str],
    sprt_alpha_values: List[float],
    sprt_beta_values: List[float],
    chance_threshold_values: List[float],
    min_deltaj_per_cost_values: List[float],
    capacity_rho_max_values: List[float],
    risk_thresholds: List[float],
    min_persistence_replans: List[int],
    max_eta_s_values: List[float],
    score_margin_values: List[float],
    budget_per_hr: List[int],
    budget_modes: List[str],
    budget_utility_per_hr: List[float],
    deterring_window_s: List[float],
    min_predicted_deltaJ_values: List[float],
    beta_true_values: List[float],
    base_params: dict,
    checkpoint_path: Path | None = None,
    resume: bool = True,
    max_workers: int = 1,
) -> pd.DataFrame:
    if checkpoint_path is not None and resume:
        runs_df = _load_checkpoint(checkpoint_path)
    else:
        runs_df = _empty_runs_df()

    combos = list(
        itertools.product(
            distance_costs,
            switch_penalties,
            replan_periods_s,
            assigner_w_task_values,
            gate_policies,
            sprt_alpha_values,
            sprt_beta_values,
            chance_threshold_values,
            min_deltaj_per_cost_values,
            capacity_rho_max_values,
            risk_thresholds,
            min_persistence_replans,
            max_eta_s_values,
            score_margin_values,
            budget_per_hr,
            budget_modes,
            budget_utility_per_hr,
            deterring_window_s,
            min_predicted_deltaJ_values,
            beta_true_values,
        )
    )
    total = len(combos) * len(baselines) * len(methods)
    idx = 0

    if int(max_workers) <= 0:
        max_workers = max(1, int(os.cpu_count() or 1) - 1)
    worker_count = int(max_workers)

    for (
        c_dist,
        c_switch,
        replan_s,
        w_task_value,
        gate_policy,
        sprt_alpha,
        sprt_beta,
        chance_threshold,
        min_deltaj_per_cost,
        capacity_rho_max,
        risk_th,
        min_persist,
        max_eta_s,
        score_margin,
        budget_hr,
        budget_mode,
        budget_utility_hr,
        det_window_s,
        min_pred_dj,
        beta_true,
    ) in combos:
        budget_mode_short = "cph" if str(budget_mode).strip().lower() == "count_per_hour" else "uph"
        scenario_id = (
            f"d{c_dist:g}_s{c_switch:g}_rp{int(replan_s)}"
            f"_tv{w_task_value:g}"
            f"_gp{gate_policy}"
            f"_sa{sprt_alpha:g}_sb{sprt_beta:g}"
            f"_ct{chance_threshold:g}_ucr{min_deltaj_per_cost:g}_rho{capacity_rho_max:g}"
            f"_rt{risk_th:g}_mp{int(min_persist)}_eta{max_eta_s:g}_sm{score_margin:g}"
            f"_bh{int(budget_hr)}_bm{budget_mode_short}"
            f"_bu{budget_utility_hr:g}"
            f"_dw{det_window_s:g}_mdj{min_pred_dj:g}_bt{beta_true:g}"
        )
        jobs = []
        for baseline in baselines:
            for method in methods:
                idx += 1
                if _pair_complete(runs_df, scenario_id, baseline, method, int(num_runs)):
                    print(
                        f"[skip] {idx}/{total} scenario={scenario_id} baseline={baseline} "
                        f"method={method} (checkpoint complete)"
                    )
                    continue
                print(f"[queue] {idx}/{total} scenario={scenario_id} baseline={baseline} method={method}")
                jobs.append(
                    {
                        "scenario_id": scenario_id,
                        "baseline": str(baseline),
                        "method": str(method),
                        "assignment_distance_cost_per_m": float(c_dist),
                        "assignment_switch_penalty": float(c_switch),
                        "task_replan_period_s": float(replan_s),
                        "assigner_w_task_value": float(w_task_value),
                        "model_deterring_gate_policy": str(gate_policy),
                        "model_deterring_sprt_alpha": float(sprt_alpha),
                        "model_deterring_sprt_beta": float(sprt_beta),
                        "model_deterring_chance_threshold": float(chance_threshold),
                        "model_deterring_min_deltaJ_per_cost": float(min_deltaj_per_cost),
                        "model_deterring_capacity_rho_max": float(capacity_rho_max),
                        "model_deterring_risk_threshold": float(risk_th),
                        "model_deterring_min_persistence_replans": int(min_persist),
                        "model_deterring_max_eta_s": float(max_eta_s),
                        "model_deterring_score_margin": float(score_margin),
                        "model_deterring_budget_per_robot_per_hr": int(budget_hr),
                        "model_deterring_budget_mode": str(budget_mode),
                        "model_deterring_budget_utility_per_robot_per_hr": float(budget_utility_hr),
                        "model_deterring_window_s": float(det_window_s),
                        "min_predicted_deltaJ_for_model_deterring": float(min_pred_dj),
                        "beta_true": float(beta_true),
                        "base_params": dict(base_params),
                        "num_runs": int(num_runs),
                        "seed_start": int(seed_start),
                    }
                )

        if not jobs:
            continue

        if worker_count == 1:
            results = [(_run_combo_job(job), job) for job in jobs]
        else:
            with ProcessPoolExecutor(max_workers=worker_count) as executor:
                future_to_job = {executor.submit(_run_combo_job, job): job for job in jobs}
                results = []
                for fut in as_completed(future_to_job):
                    results.append((fut.result(), future_to_job[fut]))

        for res, job in results:
            rows = list(res.get("rows", []))
            if rows:
                baseline = str(res["baseline"])
                method = str(res["assignment_method"])
                runs_df = _drop_pair_rows(runs_df, scenario_id, baseline, method)
                add_df = pd.DataFrame(rows)
                if runs_df.empty:
                    runs_df = add_df.copy()
                else:
                    runs_df = pd.concat([runs_df, add_df], ignore_index=True)

            if checkpoint_path is not None:
                progress = {
                    "checkpoint_version": 3,
                    "num_rows": int(len(runs_df)),
                    "last_completed_scenario": str(scenario_id),
                    "last_completed_pair": {
                        "baseline": str(job["baseline"]),
                        "assignment_method": str(job["method"]),
                    },
                    "num_runs": int(num_runs),
                    "seed_start": int(seed_start),
                    "baselines": list(baselines),
                    "methods": list(methods),
                    "max_workers": int(worker_count),
                }
                _write_checkpoint(checkpoint_path, runs_df, progress)
                print(
                    f"[checkpoint] scenario={scenario_id} baseline={job['baseline']} "
                    f"method={job['method']} total_rows={len(runs_df)}"
                )

    if not runs_df.empty:
        runs_df = runs_df.sort_values(
            by=["scenario_id", "baseline", "assignment_method", "seed", "run_idx"],
            ascending=[True, True, True, True, True],
        ).reset_index(drop=True)

    return runs_df


def build_summary(runs_df: pd.DataFrame) -> pd.DataFrame:
    if runs_df.empty:
        return pd.DataFrame()
    metrics = [
        "value_weighted_exposure",
        "mean_response_time_s",
        "boundary_message_count",
        "tasks_per_unit_distance",
        "predicted_deltaJ_sum",
        "realized_suppression_sum",
        "yield_ratio_total",
        "yield_ratio_direct_detection",
        "yield_ratio_model_scored",
        "queue_depth_total_mean",
        "queue_depth_patrolling_mean",
        "queue_depth_deterring_mean",
        "queue_depth_model_deterring_mean",
        "queue_depth_total_max",
        "queue_depth_patrolling_max",
        "queue_depth_deterring_max",
        "queue_depth_model_deterring_max",
        "stale_task_evictions_count",
        "robot_moving_fraction_mean",
        "robot_active_task_fraction_mean",
        "model_deterring_pass_sprt",
        "model_deterring_rejected_sprt_pending",
        "model_deterring_rejected_sprt_negative",
        "model_deterring_pass_chance",
        "model_deterring_rejected_chance",
        "model_deterring_pass_utility_ratio",
        "model_deterring_rejected_utility_ratio",
        "model_deterring_pass_capacity",
        "model_deterring_rejected_capacity",
        "model_deterring_llr_mean",
        "model_deterring_llr_max",
        "model_deterring_p_event_mean",
        "model_deterring_deltaJ_per_cost_mean",
        "preventive_service_rate_per_robot_mean",
        "preventive_direct_arrival_rate_per_robot_mean",
        "preventive_capacity_remaining_per_robot_mean",
        "model_deterring_accepted",
        "model_deterring_generated",
        "model_deterring_candidates_total",
        "model_deterring_rejected_cooldown",
        "model_deterring_rejected_field",
        "model_deterring_pass_field",
        "model_deterring_rejected_predicted_deltaJ",
        "model_deterring_pass_predicted_deltaJ",
        "model_deterring_pass_risk",
        "model_deterring_pass_support",
        "model_deterring_rejected_risk",
        "model_deterring_rejected_support",
        "model_deterring_rejected_persistence",
        "model_deterring_rejected_repeat_no_new_support",
        "model_deterring_rejected_margin",
        "model_deterring_rejected_eta",
        "model_deterring_rejected_busy",
        "model_deterring_rejected_budget",
        "model_deterring_rejected_budget_count_mode",
        "model_deterring_rejected_budget_utility_mode",
        "model_deterring_budget_spent_count_per_robot_hr_mean",
        "model_deterring_budget_spent_count_per_robot_hr_max",
        "model_deterring_budget_spent_utility_per_robot_hr_mean",
        "model_deterring_budget_spent_utility_per_robot_hr_max",
        "planner_replaced_low_utility_count",
        "assigned_task_value_mean",
        "assignment_solver_runtime_ms",
        "assignment_solver_assigned_mean",
        "assignment_solver_objective_mean",
        "assignment_solver_rounds_mean",
        "assignment_solver_message_passes",
        "assignment_solver_failures",
    ]
    for ii in range(5):
        metrics.extend(
            [
                f"model_deterring_calibration_bin_{ii}_count",
                f"model_deterring_calibration_bin_{ii}_hits",
                f"model_deterring_calibration_bin_{ii}_hit_rate",
            ]
        )
    out = []
    gcols = [
        "scenario_id",
        "assignment_distance_cost_per_m",
        "assignment_switch_penalty",
        "task_replan_period_s",
        "assigner_w_task_value",
        "model_deterring_gate_policy",
        "model_deterring_sprt_alpha",
        "model_deterring_sprt_beta",
        "model_deterring_chance_threshold",
        "model_deterring_min_deltaJ_per_cost",
        "model_deterring_capacity_rho_max",
        "model_deterring_risk_threshold",
        "model_deterring_min_persistence_replans",
        "model_deterring_max_eta_s",
        "model_deterring_score_margin",
        "model_deterring_budget_per_robot_per_hr",
        "model_deterring_budget_mode",
        "model_deterring_budget_utility_per_robot_per_hr",
        "model_deterring_window_s",
        "min_predicted_deltaJ_for_model_deterring",
        "beta_true",
        "baseline",
        "assignment_method",
    ]
    for keys, g in runs_df.groupby(gcols, as_index=False):
        row = {name: val for name, val in zip(gcols, keys)}
        row["n_runs"] = int(len(g))
        for m in metrics:
            st = _stats(g, m)
            row[f"{m}_mean"] = st["mean"]
            row[f"{m}_std"] = st["std"]
            row[f"{m}_ci95"] = st["ci95"]
        out.append(row)
    return pd.DataFrame(out)


def build_method_deltas_vs_frozen(runs_df: pd.DataFrame) -> pd.DataFrame:
    if runs_df.empty:
        return pd.DataFrame(columns=METHOD_DELTA_COLUMNS)
    keys = ["scenario_id", "baseline", "seed", "run_idx"]
    base = runs_df[runs_df["assignment_method"] == "frozen_greedy"].copy()
    if base.empty:
        return pd.DataFrame(columns=METHOD_DELTA_COLUMNS)
    methods = sorted({m for m in runs_df["assignment_method"].unique() if m != "frozen_greedy"})
    out = []
    for method in methods:
        cur = runs_df[runs_df["assignment_method"] == method].copy()
        pair = cur.merge(base, on=keys, suffixes=("_m", "_f"), how="inner")
        if pair.empty:
            continue
        pair["assignment_method"] = method
        den_e = pair["value_weighted_exposure_f"].replace(0.0, np.nan)
        den_r = pair["mean_response_time_s_f"].replace(0.0, np.nan)
        den_c = pair["boundary_message_count_f"].replace(0.0, np.nan)
        pair["delta_exposure_pct"] = 100.0 * (pair["value_weighted_exposure_f"] - pair["value_weighted_exposure_m"]) / den_e
        pair["delta_response_pct"] = 100.0 * (pair["mean_response_time_s_f"] - pair["mean_response_time_s_m"]) / den_r
        pair["delta_comm_pct"] = 100.0 * (pair["boundary_message_count_m"] - pair["boundary_message_count_f"]) / den_c
        g = pair.groupby(["scenario_id", "baseline", "assignment_method"], as_index=False).agg(
            delta_exposure_pct_mean=("delta_exposure_pct", "mean"),
            delta_response_pct_mean=("delta_response_pct", "mean"),
            delta_comm_pct_mean=("delta_comm_pct", "mean"),
        )
        out.append(g)
    if not out:
        return pd.DataFrame(columns=METHOD_DELTA_COLUMNS)
    return pd.concat(out, ignore_index=True)


def build_proposed_vs_prediction_deltas(runs_df: pd.DataFrame) -> pd.DataFrame:
    if runs_df.empty:
        return pd.DataFrame()
    out = []
    methods = sorted({str(m) for m in runs_df["assignment_method"].dropna().unique()})
    scenarios = sorted({str(s) for s in runs_df["scenario_id"].dropna().unique()})
    for scenario in scenarios:
        for method in methods:
            p = runs_df[
                (runs_df["scenario_id"] == scenario)
                & (runs_df["assignment_method"] == method)
                & (runs_df["baseline"] == "proposed")
            ]
            q = runs_df[
                (runs_df["scenario_id"] == scenario)
                & (runs_df["assignment_method"] == method)
                & (runs_df["baseline"] == "prediction_only")
            ]
            pair = p.merge(q, on=["scenario_id", "assignment_method", "seed", "run_idx"], suffixes=("_p", "_q"), how="inner")
            if pair.empty:
                continue
            den_e = pair["value_weighted_exposure_q"].replace(0.0, np.nan)
            den_r = pair["mean_response_time_s_q"].replace(0.0, np.nan)
            den_c = pair["boundary_message_count_q"].replace(0.0, np.nan)
            exp_imp = 100.0 * (pair["value_weighted_exposure_q"] - pair["value_weighted_exposure_p"]) / den_e
            resp_imp = 100.0 * (pair["mean_response_time_s_q"] - pair["mean_response_time_s_p"]) / den_r
            comm_inc = 100.0 * (pair["boundary_message_count_p"] - pair["boundary_message_count_q"]) / den_c
            p0 = p.iloc[0]
            out.append(
                {
                    "scenario_id": scenario,
                    "assignment_method": method,
                    "assignment_distance_cost_per_m": float(p0.get("assignment_distance_cost_per_m", np.nan)),
                    "assignment_switch_penalty": float(p0.get("assignment_switch_penalty", np.nan)),
                    "task_replan_period_s": float(p0.get("task_replan_period_s", np.nan)),
                    "assigner_w_task_value": float(p0.get("assigner_w_task_value", np.nan)),
                    "model_deterring_gate_policy": str(p0.get("model_deterring_gate_policy", "")),
                    "model_deterring_sprt_alpha": float(p0.get("model_deterring_sprt_alpha", np.nan)),
                    "model_deterring_sprt_beta": float(p0.get("model_deterring_sprt_beta", np.nan)),
                    "model_deterring_chance_threshold": float(p0.get("model_deterring_chance_threshold", np.nan)),
                    "model_deterring_min_deltaJ_per_cost": float(
                        p0.get("model_deterring_min_deltaJ_per_cost", np.nan)
                    ),
                    "model_deterring_capacity_rho_max": float(
                        p0.get("model_deterring_capacity_rho_max", np.nan)
                    ),
                    "model_deterring_risk_threshold": float(p0.get("model_deterring_risk_threshold", np.nan)),
                    "model_deterring_min_persistence_replans": float(
                        p0.get("model_deterring_min_persistence_replans", np.nan)
                    ),
                    "model_deterring_max_eta_s": float(p0.get("model_deterring_max_eta_s", np.nan)),
                    "model_deterring_score_margin": float(p0.get("model_deterring_score_margin", np.nan)),
                    "model_deterring_budget_per_robot_per_hr": float(
                        p0.get("model_deterring_budget_per_robot_per_hr", np.nan)
                    ),
                    "model_deterring_budget_mode": str(p0.get("model_deterring_budget_mode", "")),
                    "model_deterring_budget_utility_per_robot_per_hr": float(
                        p0.get("model_deterring_budget_utility_per_robot_per_hr", np.nan)
                    ),
                    "model_deterring_window_s": float(p0.get("model_deterring_window_s", np.nan)),
                    "min_predicted_deltaJ_for_model_deterring": float(
                        p0.get("min_predicted_deltaJ_for_model_deterring", np.nan)
                    ),
                    "beta_true": float(p0.get("beta_true", np.nan)),
                    "exp_improve_pct_mean": _nanmean_or_nan(exp_imp),
                    "resp_improve_pct_mean": _nanmean_or_nan(resp_imp),
                    "comm_increase_pct_mean": _nanmean_or_nan(comm_inc),
                    "proposed_yield_ratio_model_scored_mean": _nanmean_or_nan(p["yield_ratio_model_scored"]),
                    "proposed_queue_depth_total_mean": _nanmean_or_nan(p["queue_depth_total_mean"]),
                    "proposed_stale_task_evictions_count_mean": _nanmean_or_nan(p["stale_task_evictions_count"]),
                    "runtime_ms_mean": _nanmean_or_nan(p["assignment_solver_runtime_ms"]),
                    "failures_mean": _nanmean_or_nan(p["assignment_solver_failures"]),
                }
            )
    return pd.DataFrame(out)


def choose_best_hungarian(deltas_df: pd.DataFrame) -> dict:
    if deltas_df.empty:
        return {"best_scenario": None, "reason": "empty deltas"}
    h = deltas_df[deltas_df["assignment_method"] == "hungarian"].copy()
    if h.empty:
        return {"best_scenario": None, "reason": "no hungarian rows"}

    h["hard_reject"] = (h["failures_mean"] > 0.0) | ((h["comm_increase_pct_mean"] > 100.0) & (h["exp_improve_pct_mean"] < 0.5))
    cand = h[~h["hard_reject"]].copy()
    if cand.empty:
        return {"best_scenario": None, "reason": "all hungarian scenarios hard-rejected"}
    cand = cand.sort_values(
        by=["exp_improve_pct_mean", "resp_improve_pct_mean", "comm_increase_pct_mean", "runtime_ms_mean", "scenario_id"],
        ascending=[False, False, True, True, True],
    )
    best = cand.iloc[0].to_dict()
    return {"best_scenario": str(best["scenario_id"]), "row": best}


def build_phase1_summary(deltas_df: pd.DataFrame) -> pd.DataFrame:
    if deltas_df.empty:
        return pd.DataFrame()
    cols = [
        "scenario_id",
        "assignment_method",
        "exp_improve_pct_mean",
        "resp_improve_pct_mean",
        "comm_increase_pct_mean",
        "runtime_ms_mean",
        "failures_mean",
    ]
    out = deltas_df[cols].copy()
    out["hard_reject"] = (out["failures_mean"] > 0.0) | (
        (out["comm_increase_pct_mean"] > 100.0) & (out["exp_improve_pct_mean"] < 0.5)
    )
    out = out.sort_values(
        by=[
            "assignment_method",
            "hard_reject",
            "exp_improve_pct_mean",
            "resp_improve_pct_mean",
            "comm_increase_pct_mean",
            "runtime_ms_mean",
            "scenario_id",
        ],
        ascending=[True, True, False, False, True, True, True],
    )
    return out


def build_phase2_ranking(deltas_df: pd.DataFrame) -> pd.DataFrame:
    if deltas_df.empty:
        return pd.DataFrame()
    cols = [
        "scenario_id",
        "assignment_method",
        "assignment_distance_cost_per_m",
        "assignment_switch_penalty",
        "task_replan_period_s",
        "assigner_w_task_value",
        "model_deterring_risk_threshold",
        "model_deterring_min_persistence_replans",
        "model_deterring_max_eta_s",
        "model_deterring_score_margin",
        "model_deterring_budget_per_robot_per_hr",
        "model_deterring_budget_mode",
        "model_deterring_budget_utility_per_robot_per_hr",
        "model_deterring_window_s",
        "min_predicted_deltaJ_for_model_deterring",
        "beta_true",
        "exp_improve_pct_mean",
        "resp_improve_pct_mean",
        "comm_increase_pct_mean",
        "runtime_ms_mean",
        "failures_mean",
    ]
    out = deltas_df[cols].copy()
    out["hard_reject"] = out["failures_mean"] > 0.0
    out = out.sort_values(
        by=[
            "hard_reject",
            "exp_improve_pct_mean",
            "resp_improve_pct_mean",
            "comm_increase_pct_mean",
            "runtime_ms_mean",
            "scenario_id",
        ],
        ascending=[True, False, False, True, True, True],
    ).reset_index(drop=True)
    out["rank"] = 0
    ok = ~out["hard_reject"]
    out.loc[ok, "rank"] = np.arange(1, int(ok.sum()) + 1, dtype=int)
    return out


def build_phase4_ranking(deltas_df: pd.DataFrame) -> pd.DataFrame:
    if deltas_df.empty:
        return pd.DataFrame()
    cols = [
        "scenario_id",
        "assignment_method",
        "assignment_distance_cost_per_m",
        "assignment_switch_penalty",
        "task_replan_period_s",
        "assigner_w_task_value",
        "model_deterring_gate_policy",
        "model_deterring_sprt_alpha",
        "model_deterring_sprt_beta",
        "model_deterring_chance_threshold",
        "model_deterring_min_deltaJ_per_cost",
        "model_deterring_capacity_rho_max",
        "model_deterring_risk_threshold",
        "model_deterring_min_persistence_replans",
        "model_deterring_max_eta_s",
        "model_deterring_score_margin",
        "model_deterring_budget_per_robot_per_hr",
        "model_deterring_budget_mode",
        "model_deterring_budget_utility_per_robot_per_hr",
        "model_deterring_window_s",
        "min_predicted_deltaJ_for_model_deterring",
        "beta_true",
        "exp_improve_pct_mean",
        "resp_improve_pct_mean",
        "comm_increase_pct_mean",
        "proposed_yield_ratio_model_scored_mean",
        "proposed_queue_depth_total_mean",
        "proposed_stale_task_evictions_count_mean",
        "runtime_ms_mean",
        "failures_mean",
    ]
    out = deltas_df[cols].copy()
    out["hard_reject"] = out["failures_mean"] > 0.0
    out = out.sort_values(
        by=[
            "hard_reject",
            "exp_improve_pct_mean",
            "resp_improve_pct_mean",
            "proposed_yield_ratio_model_scored_mean",
            "proposed_queue_depth_total_mean",
            "proposed_stale_task_evictions_count_mean",
            "comm_increase_pct_mean",
            "runtime_ms_mean",
            "scenario_id",
        ],
        ascending=[True, False, False, False, True, True, True, True, True],
    ).reset_index(drop=True)
    out["rank"] = 0
    ok = ~out["hard_reject"]
    out.loc[ok, "rank"] = np.arange(1, int(ok.sum()) + 1, dtype=int)
    return out


def _parse_phase1_scenario_id(s: str) -> dict | None:
    """
    Parses phase1 scenario id pattern:
      d<dist>_s<switch>_rp<replan>
    optionally with extra suffixes.
    """
    import re

    m = re.search(r"d(?P<d>[-+]?[0-9]*\.?[0-9]+)_s(?P<s>[-+]?[0-9]*\.?[0-9]+)_rp(?P<rp>[0-9]+)", str(s))
    if not m:
        return None
    return {
        "assignment_distance_cost_per_m": float(m.group("d")),
        "assignment_switch_penalty": float(m.group("s")),
        "task_replan_period_s": int(m.group("rp")),
    }


def _load_phase1_winner_config(manifest_path: Path) -> dict:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    winner = data.get("best_hungarian_scenario", {})
    scenario = winner.get("best_scenario")
    row = winner.get("row", {})
    parsed = _parse_phase1_scenario_id(str(scenario))
    if parsed is None:
        raise ValueError(f"Could not parse phase1 winner scenario_id: {scenario}")
    method = str(row.get("assignment_method", "hungarian")).strip().lower()
    if method != "hungarian":
        raise ValueError(f"Phase1 winner method is not hungarian: {method}")
    return parsed


def build_calibration_summary(runs_df: pd.DataFrame) -> pd.DataFrame:
    if runs_df.empty:
        return pd.DataFrame()
    gcols = [
        "scenario_id",
        "baseline",
        "assignment_method",
        "model_deterring_gate_policy",
    ]
    out = []
    for keys, g in runs_df.groupby(gcols, as_index=False):
        row = {name: val for name, val in zip(gcols, keys)}
        for ii in range(5):
            count_col = f"model_deterring_calibration_bin_{ii}_count"
            hits_col = f"model_deterring_calibration_bin_{ii}_hits"
            total_count = float(pd.to_numeric(g[count_col], errors='coerce').fillna(0.0).sum())
            total_hits = float(pd.to_numeric(g[hits_col], errors='coerce').fillna(0.0).sum())
            row[f"bin_{ii}_count"] = total_count
            row[f"bin_{ii}_hits"] = total_hits
            row[f"bin_{ii}_hit_rate"] = (total_hits / total_count) if total_count > 0.0 else float("nan")
        out.append(row)
    return pd.DataFrame(out)


def _fmt_metric(value: object) -> str:
    try:
        num = float(value)
    except Exception:
        return "nan"
    if not np.isfinite(num):
        return "nan"
    return f"{num:.4f}" if abs(num) >= 1e-3 else f"{num:.3e}"


def _write_readme(
    outdir: Path,
    stage: str,
    planner_profile: str,
    best: dict,
    runs_path: Path,
    summary_path: Path,
    method_deltas_path: Path,
    baseline_deltas_path: Path,
    phase1_summary_path: Path,
    phase2_ranking_path: Path,
    phase4_ranking_path: Path,
    calibration_path: Path,
    manifest_path: Path,
) -> Path:
    lines = [
        "# Assignment Tuning Sweep Lab",
        "",
        *render_stage_readme_lines("assignment_tuning", substage=stage),
        "",
        "## Current Sweep Intent",
        f"- {ASSIGNMENT_TUNING_SUBSTAGE_NOTES.get(stage, 'Planner tuning sweep.')}",
        f"- Planner profile seed defaults: `{planner_profile or 'manual'}`",
        "- The proposed-vs-prediction CSV is built from matched seed/run pairs so the tradeoff rows stay comparable.",
        "",
        "## Key Outputs",
        f"- Runs CSV: `{runs_path.name}`",
        f"- Summary CSV: `{summary_path.name}`",
        f"- Method deltas vs optional frozen baseline: `{method_deltas_path.name}`",
        f"- Proposed-vs-prediction deltas: `{baseline_deltas_path.name}`",
        f"- Phase-1 summary: `{phase1_summary_path.name}`",
        f"- Phase-2 ranking: `{phase2_ranking_path.name}`",
        f"- Phase-4 ranking: `{phase4_ranking_path.name}`",
        f"- Calibration CSV: `{calibration_path.name}`",
        f"- Manifest: `{manifest_path.name}`",
        "",
        "## Hard Reject Logic",
        "- Reject any scenario with assignment solver failures.",
        "- In phase-1 selection, also reject scenarios with communication increase above 100% when exposure gain stays below 0.5%.",
    ]
    best_row = dict(best.get("row", {}))
    best_scenario = str(best.get("best_scenario") or "")
    if best_scenario:
        lines.extend(
            [
                "",
                "## Current Best Hungarian Scenario",
                f"- Scenario id: `{best_scenario}`",
                f"- Exposure improve mean: {_fmt_metric(best_row.get('exp_improve_pct_mean'))}%",
                f"- Response improve mean: {_fmt_metric(best_row.get('resp_improve_pct_mean'))}%",
                f"- Communication increase mean: {_fmt_metric(best_row.get('comm_increase_pct_mean'))}%",
                f"- Runtime mean: {_fmt_metric(best_row.get('runtime_ms_mean'))} ms",
            ]
        )
    lines.extend(["", *render_execution_order_lines()])
    readme_path = outdir / "ASSIGNMENT_TUNING_README.md"
    readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return readme_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hungarian-focused assignment tuning sweep (lab only)")
    add_config_argument(parser)
    parser.add_argument("--stage", type=str, choices=["phase1", "phase2", "phase4", "phase4_refine"], default="phase1")
    parser.add_argument("--num-runs", type=int, default=8)
    parser.add_argument("--seed-start", type=int, default=2000)
    parser.add_argument("--t-end", type=float, default=3 * 3600.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--baselines", type=str, default=",".join(DEFAULT_BASELINES))
    parser.add_argument("--methods", type=str, default=",".join(DEFAULT_METHODS))
    parser.add_argument("--distance-costs", type=str, default="0.004,0.005,0.006,0.008")
    parser.add_argument("--switch-penalties", type=str, default="0.4,0.5,0.7,1.0")
    parser.add_argument("--replan-periods", type=str, default="75,90,105")
    parser.add_argument("--assigner-w-task-values", type=str, default="0.0")
    parser.add_argument(
        "--planner-profile",
        type=str,
        default="",
        help="Optional named planner preset. Example: thesis_confirm",
    )
    parser.add_argument("--gate-policies", type=str, default="")
    parser.add_argument("--sprt-alpha-values", type=str, default="")
    parser.add_argument("--sprt-beta-values", type=str, default="")
    parser.add_argument("--chance-threshold-values", type=str, default="")
    parser.add_argument("--min-deltaj-per-cost-values", type=str, default="")
    parser.add_argument("--capacity-rho-max-values", type=str, default="")
    parser.add_argument("--risk-thresholds", type=str, default="")
    parser.add_argument("--min-persistence-replans", type=str, default="")
    parser.add_argument("--max-eta-values", type=str, default="")
    parser.add_argument("--score-margin-values", type=str, default="")
    parser.add_argument("--budget-per-hr", type=str, default="")
    parser.add_argument("--budget-modes", type=str, default="")
    parser.add_argument("--budget-utility-per-hr", type=str, default="")
    parser.add_argument("--deterring-windows", type=str, default="")
    parser.add_argument("--min-predicted-deltaj-values", type=str, default="")
    parser.add_argument("--beta-true-values", type=str, default="")
    parser.add_argument("--phase1-manifest", type=str, default="")
    parser.add_argument(
        "--use-phase1-winner",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="For stage=phase2, load fixed Hungarian dispatch config from phase1 manifest.",
    )
    parser.add_argument("--outdir", type=str, default="results/assignment_tuning_sweep_lab")
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Resume from scenario-level checkpoint (default: enabled).",
    )
    parser.add_argument(
        "--checkpoint-path",
        type=str,
        default="",
        help="Optional checkpoint CSV path. Default: <outdir>/assignment_tuning_runs_lab.checkpoint.csv",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="Process workers for parallel scenario execution; use 0 for auto (cpu_count-1).",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args, config_meta = parse_args_with_config(
        parser,
        aliases=ASSIGNMENT_TUNING_CONFIG_ALIASES,
        argv=argv,
    )
    protected_profile_dests = explicit_cli_dests(parser) | set(config_meta.get("config_overrides", {}).keys())
    planner_profile, planner_profile_values = apply_planner_profile_defaults(
        vars(args),
        getattr(args, "planner_profile", ""),
        dest_map=ASSIGNMENT_TUNING_PROFILE_DEST_MAP,
        protected_dests=protected_profile_dests,
        stringify=True,
    )
    args.planner_profile = planner_profile

    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    baselines = _parse_str_list(args.baselines)
    methods = _parse_str_list(args.methods)
    distance_costs = _parse_float_list(args.distance_costs)
    switch_penalties = _parse_float_list(args.switch_penalties)
    replan_periods_s = _parse_int_list(args.replan_periods)
    assigner_w_task_values = _parse_float_list(args.assigner_w_task_values)
    if not assigner_w_task_values:
        assigner_w_task_values = [0.0]
    gate_policies = [str(x).strip().lower() for x in _parse_str_list(args.gate_policies)]
    gate_policies = [x for x in gate_policies if x in ("heuristic", "sprt_capacity")]
    sprt_alpha_values = _parse_float_list(args.sprt_alpha_values)
    sprt_beta_values = _parse_float_list(args.sprt_beta_values)
    chance_threshold_values = _parse_float_list(args.chance_threshold_values)
    min_deltaj_per_cost_values = _parse_float_list(args.min_deltaj_per_cost_values)
    capacity_rho_max_values = _parse_float_list(args.capacity_rho_max_values)
    risk_thresholds = _parse_float_list(args.risk_thresholds)
    min_persistence_replans = _parse_int_list(args.min_persistence_replans)
    max_eta_s_values = _parse_float_list(args.max_eta_values)
    score_margin_values = _parse_float_list(args.score_margin_values)
    budget_per_hr = _parse_int_list(args.budget_per_hr)
    budget_modes = [str(x).strip().lower() for x in _parse_str_list(args.budget_modes)]
    budget_modes = [x for x in budget_modes if x in ("count_per_hour", "utility_per_hour")]
    budget_utility_per_hr = _parse_float_list(args.budget_utility_per_hr)
    deterring_window_s = _parse_float_list(args.deterring_windows)
    min_predicted_deltaJ_values = _parse_float_list(args.min_predicted_deltaj_values)
    beta_true_values = _parse_float_list(args.beta_true_values)

    stage = str(args.stage).strip().lower()
    if stage == "phase1":
        if not gate_policies:
            gate_policies = ["heuristic"]
        if not sprt_alpha_values:
            sprt_alpha_values = [0.05]
        if not sprt_beta_values:
            sprt_beta_values = [0.20]
        if not chance_threshold_values:
            chance_threshold_values = [0.20]
        if not min_deltaj_per_cost_values:
            min_deltaj_per_cost_values = [0.15]
        if not capacity_rho_max_values:
            capacity_rho_max_values = [0.85]
        if not risk_thresholds:
            risk_thresholds = [0.35]
        if not min_persistence_replans:
            min_persistence_replans = [2]
        if not max_eta_s_values:
            max_eta_s_values = [120.0]
        if not score_margin_values:
            score_margin_values = [0.05]
        if not budget_per_hr:
            budget_per_hr = [4]
        if not budget_modes:
            budget_modes = ["count_per_hour"]
        if not budget_utility_per_hr:
            budget_utility_per_hr = [5.0]
        if not deterring_window_s:
            deterring_window_s = [90.0]
        if not min_predicted_deltaJ_values:
            min_predicted_deltaJ_values = [0.0]
        if not beta_true_values:
            beta_true_values = [0.35]

    if stage == "phase2":
        # Force phase2 comparison to fixed Hungarian assignment as requested.
        methods = ["hungarian"]
        if not gate_policies:
            gate_policies = ["heuristic"]
        if not sprt_alpha_values:
            sprt_alpha_values = [0.05]
        if not sprt_beta_values:
            sprt_beta_values = [0.20]
        if not chance_threshold_values:
            chance_threshold_values = [0.20]
        if not min_deltaj_per_cost_values:
            min_deltaj_per_cost_values = [0.15]
        if not capacity_rho_max_values:
            capacity_rho_max_values = [0.85]
        if bool(args.use_phase1_winner):
            if str(args.phase1_manifest).strip():
                p1_manifest = Path(args.phase1_manifest)
            else:
                p1_manifest = Path("results/assignment_tuning_sweep_lab_phase1_fast/assignment_tuning_manifest_lab.json")
            cfg = _load_phase1_winner_config(p1_manifest)
            distance_costs = [float(cfg["assignment_distance_cost_per_m"])]
            switch_penalties = [float(cfg["assignment_switch_penalty"])]
            replan_periods_s = [int(cfg["task_replan_period_s"])]
            print(
                "[phase2] fixed dispatch from phase1 winner: "
                f"d={distance_costs[0]} s={switch_penalties[0]} rp={replan_periods_s[0]} "
                f"(manifest={p1_manifest})"
            )
        # Phase2 required sweep knobs defaults.
        if not risk_thresholds:
            risk_thresholds = [0.25, 0.35, 0.45]
        if not min_persistence_replans:
            min_persistence_replans = [2, 3, 4]
        if not max_eta_s_values:
            max_eta_s_values = [60.0, 90.0]
        if not score_margin_values:
            score_margin_values = [0.10, 0.20, 0.30]
        if not budget_per_hr:
            budget_per_hr = [3, 5, 7]
        if not budget_modes:
            budget_modes = ["count_per_hour", "utility_per_hour"]
        if not budget_utility_per_hr:
            budget_utility_per_hr = [4.0, 6.0, 8.0]
        if not deterring_window_s:
            deterring_window_s = [90.0, 120.0]
        if not min_predicted_deltaJ_values:
            min_predicted_deltaJ_values = [0.0, 0.25, 0.5]
        if not beta_true_values:
            beta_true_values = [0.25, 0.35, 0.45]

    if stage == "phase4":
        methods = ["hungarian"]
        baselines = ["prediction_only", "proposed"]
        if bool(args.use_phase1_winner):
            if str(args.phase1_manifest).strip():
                p1_manifest = Path(args.phase1_manifest)
            else:
                p1_manifest = Path("results/assignment_tuning_sweep_lab_phase1_fast/assignment_tuning_manifest_lab.json")
            cfg = _load_phase1_winner_config(p1_manifest)
            distance_costs = [float(cfg["assignment_distance_cost_per_m"])]
            switch_penalties = [float(cfg["assignment_switch_penalty"])]
            replan_periods_s = [int(cfg["task_replan_period_s"])]
            print(
                "[phase4] fixed dispatch from phase1 winner: "
                f"d={distance_costs[0]} s={switch_penalties[0]} rp={replan_periods_s[0]} "
                f"(manifest={p1_manifest})"
            )
        if not gate_policies:
            gate_policies = ["heuristic", "sprt_capacity"]
        if not sprt_alpha_values:
            sprt_alpha_values = [0.05]
        if not sprt_beta_values:
            sprt_beta_values = [0.20]
        if not chance_threshold_values:
            chance_threshold_values = [0.15, 0.20, 0.30]
        if not min_deltaj_per_cost_values:
            min_deltaj_per_cost_values = [0.10, 0.15, 0.25]
        if not capacity_rho_max_values:
            capacity_rho_max_values = [0.75, 0.85, 0.95]
        if not risk_thresholds:
            risk_thresholds = [0.35]
        if not min_persistence_replans:
            min_persistence_replans = [2]
        if not max_eta_s_values:
            max_eta_s_values = [120.0]
        if not score_margin_values:
            score_margin_values = [0.05]
        if not budget_per_hr:
            budget_per_hr = [4]
        if not budget_modes:
            budget_modes = ["count_per_hour"]
        if not budget_utility_per_hr:
            budget_utility_per_hr = [5.0]
        if not deterring_window_s:
            deterring_window_s = [90.0]
        if not min_predicted_deltaJ_values:
            min_predicted_deltaJ_values = [0.0]
        if not beta_true_values:
            beta_true_values = [0.35]

    if stage == "phase4_refine":
        methods = ["hungarian"]
        baselines = ["prediction_only", "proposed"]
        if bool(args.use_phase1_winner):
            if str(args.phase1_manifest).strip():
                p1_manifest = Path(args.phase1_manifest)
            else:
                p1_manifest = Path("results/assignment_tuning_sweep_lab_phase1_fast/assignment_tuning_manifest_lab.json")
            cfg = _load_phase1_winner_config(p1_manifest)
            distance_costs = [float(cfg["assignment_distance_cost_per_m"])]
            switch_penalties = [float(cfg["assignment_switch_penalty"])]
            replan_periods_s = [int(cfg["task_replan_period_s"])]
            print(
                "[phase4_refine] fixed dispatch from phase1 winner: "
                f"d={distance_costs[0]} s={switch_penalties[0]} rp={replan_periods_s[0]} "
                f"(manifest={p1_manifest})"
            )
        if not gate_policies:
            gate_policies = ["sprt_capacity"]
        if not sprt_alpha_values:
            sprt_alpha_values = [0.05, 0.10, 0.15]
        if not sprt_beta_values:
            sprt_beta_values = [0.20, 0.30]
        if not chance_threshold_values:
            chance_threshold_values = [0.10, 0.15, 0.20]
        if not min_deltaj_per_cost_values:
            min_deltaj_per_cost_values = [0.05, 0.10, 0.15]
        if not capacity_rho_max_values:
            capacity_rho_max_values = [0.85, 0.95]
        if not risk_thresholds:
            risk_thresholds = [0.35]
        if not min_persistence_replans:
            min_persistence_replans = [2]
        if not max_eta_s_values:
            max_eta_s_values = [120.0]
        if not score_margin_values:
            score_margin_values = [0.05]
        if not budget_per_hr:
            budget_per_hr = [4]
        if not budget_modes:
            budget_modes = ["count_per_hour"]
        if not budget_utility_per_hr:
            budget_utility_per_hr = [5.0]
        if not deterring_window_s:
            deterring_window_s = [90.0]
        if not min_predicted_deltaJ_values:
            min_predicted_deltaJ_values = [0.0]
        if not beta_true_values:
            beta_true_values = [0.35]

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = Path(args.checkpoint_path) if str(args.checkpoint_path).strip() else (
        outdir / "assignment_tuning_runs_lab.checkpoint.csv"
    )

    base_params = _build_base_params(float(args.t_end), float(args.dt))
    runs_df = run_sweep(
        num_runs=int(args.num_runs),
        seed_start=int(args.seed_start),
        baselines=baselines,
        methods=methods,
        distance_costs=distance_costs,
        switch_penalties=switch_penalties,
        replan_periods_s=replan_periods_s,
        assigner_w_task_values=assigner_w_task_values,
        gate_policies=gate_policies,
        sprt_alpha_values=sprt_alpha_values,
        sprt_beta_values=sprt_beta_values,
        chance_threshold_values=chance_threshold_values,
        min_deltaj_per_cost_values=min_deltaj_per_cost_values,
        capacity_rho_max_values=capacity_rho_max_values,
        risk_thresholds=risk_thresholds,
        min_persistence_replans=min_persistence_replans,
        max_eta_s_values=max_eta_s_values,
        score_margin_values=score_margin_values,
        budget_per_hr=budget_per_hr,
        budget_modes=budget_modes,
        budget_utility_per_hr=budget_utility_per_hr,
        deterring_window_s=deterring_window_s,
        min_predicted_deltaJ_values=min_predicted_deltaJ_values,
        beta_true_values=beta_true_values,
        base_params=base_params,
        checkpoint_path=checkpoint_path,
        resume=bool(args.resume),
        max_workers=int(args.max_workers),
    )
    summary_df = build_summary(runs_df)
    method_deltas_df = build_method_deltas_vs_frozen(runs_df)
    baseline_deltas_df = build_proposed_vs_prediction_deltas(runs_df)
    phase1_summary_df = build_phase1_summary(baseline_deltas_df)
    phase2_ranking_df = build_phase2_ranking(baseline_deltas_df)
    phase4_ranking_df = build_phase4_ranking(baseline_deltas_df)
    calibration_df = build_calibration_summary(runs_df)
    best = choose_best_hungarian(baseline_deltas_df)

    runs_path = outdir / "assignment_tuning_runs_lab.csv"
    summary_path = outdir / "assignment_tuning_summary_lab.csv"
    method_deltas_path = outdir / "assignment_tuning_method_deltas_lab.csv"
    baseline_deltas_path = outdir / "assignment_tuning_proposed_vs_prediction_lab.csv"
    phase1_summary_path = outdir / "assignment_tuning_phase1_summary_lab.csv"
    phase2_ranking_path = outdir / "assignment_tuning_phase2_ranking_lab.csv"
    phase4_ranking_path = outdir / "assignment_tuning_phase4_ranking_lab.csv"
    calibration_path = outdir / "model_deterring_calibration_lab.csv"
    manifest_path = outdir / "assignment_tuning_manifest_lab.json"

    runs_df.to_csv(runs_path, index=False)
    summary_df.to_csv(summary_path, index=False)
    method_deltas_df.to_csv(method_deltas_path, index=False)
    baseline_deltas_df.to_csv(baseline_deltas_path, index=False)
    phase1_summary_df.to_csv(phase1_summary_path, index=False)
    phase2_ranking_df.to_csv(phase2_ranking_path, index=False)
    phase4_ranking_df.to_csv(phase4_ranking_path, index=False)
    calibration_df.to_csv(calibration_path, index=False)

    manifest = {
        "num_runs": int(args.num_runs),
        "seed_start": int(args.seed_start),
        "seed_list": [int(args.seed_start) + i for i in range(int(args.num_runs))],
        "t_end": float(args.t_end),
        "dt": float(args.dt),
        "baselines": baselines,
        "methods": methods,
        "stage": stage,
        "distance_costs": distance_costs,
        "switch_penalties": switch_penalties,
        "replan_periods_s": replan_periods_s,
        "assigner_w_task_values": assigner_w_task_values,
        "model_deterring_gate_policy": gate_policies,
        "model_deterring_sprt_alpha": sprt_alpha_values,
        "model_deterring_sprt_beta": sprt_beta_values,
        "model_deterring_chance_threshold": chance_threshold_values,
        "model_deterring_min_deltaJ_per_cost": min_deltaj_per_cost_values,
        "model_deterring_capacity_rho_max": capacity_rho_max_values,
        "model_deterring_risk_thresholds": risk_thresholds,
        "model_deterring_min_persistence_replans": min_persistence_replans,
        "model_deterring_max_eta_s": max_eta_s_values,
        "model_deterring_score_margin": score_margin_values,
        "model_deterring_budget_per_robot_per_hr": budget_per_hr,
        "model_deterring_budget_mode": budget_modes,
        "model_deterring_budget_utility_per_robot_per_hr": budget_utility_per_hr,
        "model_deterring_window_s": deterring_window_s,
        "min_predicted_deltaJ_for_model_deterring": min_predicted_deltaJ_values,
        "beta_true_values": beta_true_values,
        "phase1_manifest": str(args.phase1_manifest),
        "use_phase1_winner": bool(args.use_phase1_winner),
        "planner_profile": planner_profile,
        "planner_profile_values": planner_profile_values,
        "workflow_stage": stage_manifest("assignment_tuning"),
        "tuning_substage": stage,
        "tuning_substage_note": ASSIGNMENT_TUNING_SUBSTAGE_NOTES.get(stage, "Planner tuning sweep."),
        "resume": bool(args.resume),
        "checkpoint_path": str(checkpoint_path),
        "max_workers": int(args.max_workers),
        "config": config_meta,
        "best_hungarian_scenario": best,
        "diagnostic_metrics_exported": [
            "predicted_deltaJ_sum",
            "realized_suppression_sum",
            "yield_ratio_total",
            "yield_ratio_direct_detection",
            "yield_ratio_model_scored",
            "queue_depth_total_mean",
            "queue_depth_patrolling_mean",
            "queue_depth_deterring_mean",
            "queue_depth_model_deterring_mean",
            "queue_depth_total_max",
            "queue_depth_patrolling_max",
            "queue_depth_deterring_max",
            "queue_depth_model_deterring_max",
            "stale_task_evictions_count",
            "robot_moving_fraction_mean",
            "robot_active_task_fraction_mean",
            "model_deterring_accepted",
            "model_deterring_generated",
            "model_deterring_candidates_total",
            "model_deterring_rejected_cooldown",
            "model_deterring_rejected_field",
            "model_deterring_pass_field",
            "model_deterring_rejected_predicted_deltaJ",
            "model_deterring_pass_predicted_deltaJ",
            "model_deterring_pass_sprt",
            "model_deterring_rejected_sprt_pending",
            "model_deterring_rejected_sprt_negative",
            "model_deterring_pass_chance",
            "model_deterring_rejected_chance",
            "model_deterring_pass_utility_ratio",
            "model_deterring_rejected_utility_ratio",
            "model_deterring_pass_capacity",
            "model_deterring_rejected_capacity",
            "model_deterring_pass_risk",
            "model_deterring_pass_support",
            "model_deterring_rejected_risk",
            "model_deterring_rejected_support",
            "model_deterring_rejected_persistence",
            "model_deterring_rejected_repeat_no_new_support",
            "model_deterring_rejected_margin",
            "model_deterring_rejected_eta",
            "model_deterring_rejected_busy",
            "model_deterring_rejected_budget",
            "model_deterring_rejected_budget_count_mode",
            "model_deterring_rejected_budget_utility_mode",
            "model_deterring_budget_spent_count_per_robot_hr_mean",
            "model_deterring_budget_spent_count_per_robot_hr_max",
            "model_deterring_budget_spent_utility_per_robot_hr_mean",
            "model_deterring_budget_spent_utility_per_robot_hr_max",
            "model_deterring_llr_mean",
            "model_deterring_llr_max",
            "model_deterring_p_event_mean",
            "model_deterring_deltaJ_per_cost_mean",
            "preventive_service_rate_per_robot_mean",
            "preventive_direct_arrival_rate_per_robot_mean",
            "preventive_capacity_remaining_per_robot_mean",
            "planner_replaced_low_utility_count",
            "assigned_task_value_mean",
            "assignment_solver_assigned_mean",
            "assignment_solver_objective_mean",
        ],
        "output_files": {
            "runs_csv": str(runs_path),
            "summary_csv": str(summary_path),
            "method_deltas_csv": str(method_deltas_path),
            "proposed_vs_prediction_csv": str(baseline_deltas_path),
            "phase1_summary_csv": str(phase1_summary_path),
            "phase2_ranking_csv": str(phase2_ranking_path),
            "phase4_ranking_csv": str(phase4_ranking_path),
            "calibration_csv": str(calibration_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    readme_path = _write_readme(
        outdir=outdir,
        stage=stage,
        planner_profile=planner_profile,
        best=best,
        runs_path=runs_path,
        summary_path=summary_path,
        method_deltas_path=method_deltas_path,
        baseline_deltas_path=baseline_deltas_path,
        phase1_summary_path=phase1_summary_path,
        phase2_ranking_path=phase2_ranking_path,
        phase4_ranking_path=phase4_ranking_path,
        calibration_path=calibration_path,
        manifest_path=manifest_path,
    )

    print(f"[done] wrote outputs to: {outdir}")
    print(f"- {runs_path}")
    print(f"- {summary_path}")
    print(f"- {method_deltas_path}")
    print(f"- {baseline_deltas_path}")
    print(f"- {phase1_summary_path}")
    print(f"- {phase2_ranking_path}")
    print(f"- {phase4_ranking_path}")
    print(f"- {calibration_path}")
    print(f"- {manifest_path}")
    print(f"- {readme_path}")


if __name__ == "__main__":
    main()
