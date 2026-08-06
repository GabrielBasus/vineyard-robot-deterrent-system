from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from itertools import product
from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from experiments import compare_field_divergence_lab as cfd
from experiments import run_field_divergence_confirm_lab as confirm_lab
from diagnostics.diagnostic_field_truth_compare import SubsystemConfig, simulate_one_run
from experiments.thesis_experiment_workflow import (
    render_execution_order_lines,
    render_stage_readme_lines,
    stage_manifest,
)
import labs.DeterrentSystem_assignment_lab as ds


SHARED_METRICS = (
    "prediction_only_field_logloss",
    "prediction_only_field_brier",
    "prediction_only_nll",
    "proposed_field_logloss",
    "proposed_field_brier",
    "proposed_nll",
    "delta_field_logloss_proposed_minus_prediction",
    "delta_field_brier_proposed_minus_prediction",
    "delta_nll_proposed_minus_prediction",
    "logloss_improvement_pct",
    "brier_improvement_pct",
    "nll_improvement_pct",
)

PROPOSED_METRICS = (
    "prediction_only_field_logloss",
    "prediction_only_field_brier",
    "prediction_only_nll",
    "proposed_field_logloss",
    "proposed_field_brier",
    "proposed_nll",
    "delta_field_logloss_proposed_minus_prediction",
    "delta_field_brier_proposed_minus_prediction",
    "delta_nll_proposed_minus_prediction",
    "logloss_improvement_pct",
    "brier_improvement_pct",
    "nll_improvement_pct",
)

FEEDBACK_METRICS = (
    "prediction_only_field_logloss",
    "prediction_only_field_brier",
    "prediction_only_nll",
    "proposed_field_logloss",
    "proposed_field_brier",
    "proposed_nll",
    "delta_field_logloss_proposed_minus_prediction",
    "delta_field_brier_proposed_minus_prediction",
    "delta_nll_proposed_minus_prediction",
    "logloss_improvement_pct",
    "brier_improvement_pct",
    "nll_improvement_pct",
)

GUARDRAIL_METRICS = (
    "delta_field_logloss_proposed_minus_prediction_mean",
    "delta_field_brier_proposed_minus_prediction_mean",
    "delta_nll_proposed_minus_prediction_mean",
)

DIVERGENCE_RERANK_THRESHOLD = 0.10
MODEL_PARAMETER_KEYS = (
    "model_sigma",
    "model_omega",
    "model_omega_inhib",
    "model_alpha_in",
    "model_alpha_cross",
    "model_alpha_inhib",
    "model_mu_base",
    "model_bg_ema",
    "model_feedback_sigma_scale",
    "model_feedback_omega_scale",
)
MODE_CONFIG_ID_KEYS = ("prediction_only_config_id", "proposed_config_id")


def _parse_float_list(raw: str):
    return [float(x.strip()) for x in str(raw).split(",") if str(x).strip()]


def _parse_int_list(raw: str):
    return [int(x.strip()) for x in str(raw).split(",") if str(x).strip()]


def _stats(arr):
    vals = np.asarray(arr, dtype=float)
    vals = vals[np.isfinite(vals)]
    n = int(vals.size)
    if n == 0:
        return {"mean": float("nan"), "std": float("nan"), "ci95": float("nan"), "n": 0}
    mean = float(np.mean(vals))
    std = float(np.std(vals))
    ci95 = float(1.96 * std / math.sqrt(n)) if n > 1 else 0.0
    return {"mean": mean, "std": std, "ci95": ci95, "n": n}


def _format_metric(value: object) -> str:
    try:
        num = float(value)
    except Exception:
        return "nan"
    if not np.isfinite(num):
        return "nan"
    return f"{num:.4f}" if abs(num) >= 1e-3 else f"{num:.3e}"


def _plain_value(value):
    return value.item() if hasattr(value, "item") else value


def _base_cfg_kwargs(args) -> dict[str, float | int | str]:
    return {
        "runs": int(args.runs),
        "seed_start": int(args.seed_start),
        "T_end": float(args.T_end),
        "warmup_s": float(args.warmup_s),
        "dt": float(args.dt),
        "forecast_horizon_s": float(args.forecast_horizon_s),
        "eval_period_s": float(args.eval_period_s),
        "intervention_prob": float(args.intervention_prob),
        "intervention_cooldown_s": float(args.intervention_cooldown_s),
        "intervention_delay_s": float(args.intervention_delay_s),
        "intervention_shuffle": str(args.intervention_shuffle),
        "shuffle_time_window_s": float(args.shuffle_time_window_s),
        "beta_true": float(args.beta_true),
        "model_omega_inhib": float(args.model_omega_inhib),
    }


def _summarize_configs(run_df: pd.DataFrame, *, metric_names: tuple[str, ...]) -> pd.DataFrame:
    if run_df.empty:
        return pd.DataFrame()

    summary_rows = []
    for config_id, group in run_df.groupby("config_id", sort=False):
        first = group.iloc[0]
        row = {
            key: _plain_value(first[key])
            for key in group.columns
            if (
                key == "config_id"
                or key in MODE_CONFIG_ID_KEYS
                or key in MODEL_PARAMETER_KEYS
                or key.startswith("prediction_only_model_")
                or key.startswith("proposed_model_")
            )
        }
        for metric in metric_names:
            stats = _stats(group[metric].to_numpy(dtype=float))
            row[f"{metric}_mean"] = stats["mean"]
            row[f"{metric}_std"] = stats["std"]
            row[f"{metric}_ci95"] = stats["ci95"]
            row[f"{metric}_n"] = stats["n"]
        summary_rows.append(row)
    return pd.DataFrame(summary_rows)


def _rank_shared_summary(summary_df: pd.DataFrame) -> pd.DataFrame:
    if summary_df.empty:
        return summary_df.copy()
    ranked = summary_df.sort_values(
        by=[
            "prediction_only_field_logloss_mean",
            "prediction_only_field_brier_mean",
            "prediction_only_nll_mean",
            "config_id",
        ],
        ascending=[True, True, True, True],
    ).reset_index(drop=True)
    ranked.insert(0, "rank", np.arange(1, len(ranked) + 1))
    return ranked


def _guardrail_satisfied(row: pd.Series) -> bool:
    for metric in GUARDRAIL_METRICS:
        try:
            value = float(row.get(metric, float("nan")))
        except Exception:
            return False
        if not np.isfinite(value) or value > 1e-12:
            return False
    return True


def _rank_feedback_summary(summary_df: pd.DataFrame) -> pd.DataFrame:
    if summary_df.empty:
        return summary_df.copy()
    ranked = summary_df.copy()
    ranked["guardrail_satisfied"] = ranked.apply(_guardrail_satisfied, axis=1)
    ranked = ranked.sort_values(
        by=[
            "guardrail_satisfied",
            "proposed_field_logloss_mean",
            "proposed_field_brier_mean",
            "proposed_nll_mean",
            "config_id",
        ],
        ascending=[False, True, True, True, True],
    ).reset_index(drop=True)
    ranked.insert(0, "rank", np.arange(1, len(ranked) + 1))
    return ranked


def _rank_proposed_summary(summary_df: pd.DataFrame) -> pd.DataFrame:
    if summary_df.empty:
        return summary_df.copy()
    ranked = summary_df.sort_values(
        by=[
            "proposed_field_logloss_mean",
            "proposed_field_brier_mean",
            "proposed_nll_mean",
            "config_id",
        ],
        ascending=[True, True, True, True],
    ).reset_index(drop=True)
    ranked.insert(0, "rank", np.arange(1, len(ranked) + 1))
    return ranked


def _shared_grid(args):
    sigma_vals = _parse_float_list(args.model_sigma_values)
    omega_vals = _parse_float_list(args.model_omega_values)
    alpha_in_vals = _parse_float_list(args.model_alpha_in_values)
    alpha_cross_vals = _parse_float_list(args.model_alpha_cross_values)
    mu_vals = _parse_float_list(args.model_mu_base_values)
    bg_vals = _parse_float_list(args.model_bg_ema_values)
    grid = list(product(sigma_vals, omega_vals, alpha_in_vals, alpha_cross_vals, mu_vals, bg_vals))
    if int(args.limit_settings) > 0:
        grid = grid[: int(args.limit_settings)]
    return grid


def _proposed_grid(args):
    sigma_vals = _parse_float_list(args.proposed_model_sigma_values or args.model_sigma_values)
    omega_vals = _parse_float_list(args.proposed_model_omega_values or args.model_omega_values)
    alpha_in_vals = _parse_float_list(args.proposed_model_alpha_in_values or args.model_alpha_in_values)
    alpha_cross_vals = _parse_float_list(args.proposed_model_alpha_cross_values or args.model_alpha_cross_values)
    mu_vals = _parse_float_list(args.proposed_model_mu_base_values or args.model_mu_base_values)
    bg_vals = _parse_float_list(args.proposed_model_bg_ema_values or args.model_bg_ema_values)
    alpha_inhib_vals = _parse_float_list(args.proposed_model_alpha_inhib_values or args.model_alpha_inhib_values)
    sigma_scale_vals = _parse_float_list(
        args.proposed_model_feedback_sigma_scale_values or args.model_feedback_sigma_scale_values
    )
    omega_scale_vals = _parse_float_list(
        args.proposed_model_feedback_omega_scale_values or args.model_feedback_omega_scale_values
    )
    grid = list(
        product(
            sigma_vals,
            omega_vals,
            alpha_in_vals,
            alpha_cross_vals,
            mu_vals,
            bg_vals,
            alpha_inhib_vals,
            sigma_scale_vals,
            omega_scale_vals,
        )
    )
    if int(args.limit_settings) > 0:
        grid = grid[: int(args.limit_settings)]
    return grid


def _mode_param_entry(prefix: str, *, sigma: float, omega: float, omega_inhib: float, alpha_in: float, alpha_cross: float, alpha_inhib: float, mu_base: float, bg_ema: float, feedback_sigma_scale: float, feedback_omega_scale: float) -> dict[str, float]:
    return {
        f"{prefix}_model_sigma": float(sigma),
        f"{prefix}_model_omega": float(omega),
        f"{prefix}_model_omega_inhib": float(omega_inhib),
        f"{prefix}_model_alpha_in": float(alpha_in),
        f"{prefix}_model_alpha_cross": float(alpha_cross),
        f"{prefix}_model_alpha_inhib": float(alpha_inhib),
        f"{prefix}_model_mu_base": float(mu_base),
        f"{prefix}_model_bg_ema": float(bg_ema),
        f"{prefix}_model_feedback_sigma_scale": float(feedback_sigma_scale),
        f"{prefix}_model_feedback_omega_scale": float(feedback_omega_scale),
    }


def _candidate_mode_overrides(row: pd.Series | dict, mode: str) -> dict[str, float]:
    payload = row if isinstance(row, dict) else row.to_dict()
    prefix = f"{mode}_"
    mode_keys = {
        "sigma": payload.get(f"{prefix}model_sigma"),
        "omega": payload.get(f"{prefix}model_omega"),
        "omega_inhib": payload.get(f"{prefix}model_omega_inhib"),
        "alpha_in": payload.get(f"{prefix}model_alpha_in"),
        "alpha_cross": payload.get(f"{prefix}model_alpha_cross"),
        "alpha_inhib": payload.get(f"{prefix}model_alpha_inhib"),
        "mu_base": payload.get(f"{prefix}model_mu_base"),
        "bg_ema": payload.get(f"{prefix}model_bg_ema"),
        "model_feedback_sigma_scale": payload.get(f"{prefix}model_feedback_sigma_scale"),
        "model_feedback_omega_scale": payload.get(f"{prefix}model_feedback_omega_scale"),
    }
    if mode_keys["mu_base"] is None and "model_mu_base" in payload:
        mode_keys = {
            "sigma": payload.get("model_sigma"),
            "omega": payload.get("model_omega"),
            "omega_inhib": payload.get("model_omega_inhib"),
            "alpha_in": payload.get("model_alpha_in"),
            "alpha_cross": payload.get("model_alpha_cross"),
            "alpha_inhib": payload.get("model_alpha_inhib"),
            "mu_base": payload.get("model_mu_base"),
            "bg_ema": payload.get("model_bg_ema"),
            "model_feedback_sigma_scale": payload.get("model_feedback_sigma_scale"),
            "model_feedback_omega_scale": payload.get("model_feedback_omega_scale"),
        }
    return {
        key: float(value)
        for key, value in mode_keys.items()
        if value is not None and value != ""
    }


def _build_divergence_rerank_sim_kwargs(args, row: pd.Series) -> dict[str, float | int | str | bool | dict | None]:
    deterring_modes = {
        "formation": {"beta": 0.30, "omega": 800.0, "sigma": 18.0, "w_eta": 1.0, "fixed_cost": 0.0},
        "laser": {"beta": 0.45, "omega": 400.0, "sigma": 10.0, "w_eta": 1.5, "fixed_cost": 0.0},
        "biosonic": {"beta": 0.25, "omega": 600.0, "sigma": 20.0, "w_eta": 1.2, "fixed_cost": 0.0},
    }
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
        "forecast_top_k": int(args.divergence_rerank_hotspot_top_k),
        "forecast_eval_period_s": 30.0,
        "task_replan_period_s": float(args.divergence_rerank_task_replan_period_s),
        "assignment_method": str(args.divergence_rerank_assignment_method),
        "assignment_distance_cost_per_m": float(args.divergence_rerank_assignment_distance_cost_per_m),
        "assignment_switch_penalty": float(args.divergence_rerank_assignment_switch_penalty),
        "assigner_w_task_value": float(args.divergence_rerank_assigner_w_task_value),
        "patrol_min_hotspot_score": float(args.divergence_rerank_patrol_min_hotspot_score),
        "patrol_hotspot_filter_mode": str(args.divergence_rerank_patrol_hotspot_filter_mode),
        "patrol_hotspot_score_percentile": float(args.divergence_rerank_patrol_hotspot_score_percentile),
        "patrol_hotspot_keep_top_k": int(args.divergence_rerank_patrol_hotspot_keep_top_k),
        "model_deterring_window_s": float(args.divergence_rerank_model_deterring_window_s),
        "model_deterring_min_persistence_replans": int(args.divergence_rerank_model_deterring_min_persistence_replans),
        "model_deterring_max_eta_s": float(args.divergence_rerank_model_deterring_max_eta_s),
        "model_deterring_score_margin": float(args.divergence_rerank_model_deterring_score_margin),
        "model_deterring_budget_per_robot_per_hr": int(args.divergence_rerank_model_deterring_budget_per_robot_per_hr),
        "model_deterring_budget_mode": str(args.divergence_rerank_model_deterring_budget_mode),
        "model_deterring_budget_utility_per_robot_per_hr": float(args.divergence_rerank_model_deterring_budget_utility_per_robot_per_hr),
        "model_deterring_gate_policy": str(args.divergence_rerank_model_deterring_gate_policy),
        "model_deterring_sprt_alpha": float(args.divergence_rerank_model_deterring_sprt_alpha),
        "model_deterring_sprt_beta": float(args.divergence_rerank_model_deterring_sprt_beta),
        "model_deterring_chance_threshold": float(args.divergence_rerank_model_deterring_chance_threshold),
        "model_deterring_min_deltaJ_per_cost": float(args.divergence_rerank_model_deterring_min_deltaj_per_cost),
        "beta_true": 0.35,
        "omega_true": 600.0,
        "sigma_true": 12.0,
        "deterring_modes": deterring_modes,
        "use_frozen_calibration": False,
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
        "T_end": float(args.divergence_rerank_t_end),
        "dt": float(args.divergence_rerank_dt),
        "prediction_only_model_overrides": _candidate_mode_overrides(row, "prediction_only"),
        "proposed_model_overrides": _candidate_mode_overrides(row, "proposed"),
    }


def _summarize_divergence_seed(
    *,
    seed: int,
    sim_kwargs: dict,
    sample_period_s: float,
    hotspot_top_k: int,
    hotspot_match_radius_m: float,
    patrol_match_radius_m: float,
    recent_deterrence_window_s: float,
    recent_deterrence_radius_m: float,
    local_patch_radius_m: float,
) -> dict:
    baseline_samples: dict[str, dict[int, dict]] = {}
    final_metrics_by_baseline: dict[str, dict] = {}
    for baseline in ("prediction_only", "proposed"):
        samples, final_metrics = cfd._collect_sampled_frames(
            baseline=baseline,
            seed=int(seed),
            sim_kwargs=sim_kwargs,
            sample_period_s=float(sample_period_s),
            hotspot_top_k=int(hotspot_top_k),
        )
        baseline_samples[baseline] = samples
        final_metrics_by_baseline[baseline] = final_metrics

    common_ts = sorted(set(baseline_samples["prediction_only"].keys()) & set(baseline_samples["proposed"].keys()))
    per_time_rows = []
    prev_pred = None
    prev_prop = None
    for t_key in common_ts:
        pred_snap = baseline_samples["prediction_only"][t_key]
        prop_snap = baseline_samples["proposed"][t_key]
        lam_pred = np.array(pred_snap.get("field_lam", []), dtype=float)
        lam_prop = np.array(prop_snap.get("field_lam", []), dtype=float)
        if lam_pred.size == 0 or lam_prop.size == 0:
            continue

        diff = lam_prop - lam_pred
        hs_pred = [(x, y) for (x, y, _s) in pred_snap.get("global_hotspots", [])[: int(hotspot_top_k)]]
        hs_prop = [(x, y) for (x, y, _s) in prop_snap.get("global_hotspots", [])[: int(hotspot_top_k)]]
        hs_matches, hs_dist = cfd._greedy_match(hs_pred, hs_prop, float(hotspot_match_radius_m))
        pred_score_stats = pred_snap.get("local_hotspot_score_stats", [])
        prop_score_stats = prop_snap.get("local_hotspot_score_stats", [])
        pred_threshold = cfd._stats_mean(pred_score_stats, "threshold_applied")
        prop_threshold = cfd._stats_mean(prop_score_stats, "threshold_applied")
        pred_score_p90 = cfd._score_quantile(pred_snap.get("local_hotspots_raw", []), 90.0)
        prop_score_p90 = cfd._score_quantile(prop_snap.get("local_hotspots_raw", []), 90.0)

        local_raw_pred = cfd._xy_points(pred_snap.get("local_hotspots_raw", []))
        local_raw_prop = cfd._xy_points(prop_snap.get("local_hotspots_raw", []))
        local_raw_matches, local_raw_dist = cfd._greedy_match(local_raw_pred, local_raw_prop, float(hotspot_match_radius_m))
        local_raw_denom = max(len(local_raw_pred), len(local_raw_prop), 1)

        local_filtered_pred = cfd._xy_points(pred_snap.get("local_hotspots_score_filtered", []))
        local_filtered_prop = cfd._xy_points(prop_snap.get("local_hotspots_score_filtered", []))
        local_filtered_matches, local_filtered_dist = cfd._greedy_match(
            local_filtered_pred, local_filtered_prop, float(hotspot_match_radius_m)
        )
        local_filtered_denom = max(len(local_filtered_pred), len(local_filtered_prop), 1)

        local_spaced_pred = cfd._xy_points(pred_snap.get("local_hotspots_spaced", []))
        local_spaced_prop = cfd._xy_points(prop_snap.get("local_hotspots_spaced", []))
        local_spaced_matches, local_spaced_dist = cfd._greedy_match(
            local_spaced_pred, local_spaced_prop, float(hotspot_match_radius_m)
        )
        local_spaced_denom = max(len(local_spaced_pred), len(local_spaced_prop), 1)

        raw_patrol_pred = cfd._xy_points(pred_snap.get("raw_patrol_candidates", []))
        raw_patrol_prop = cfd._xy_points(prop_snap.get("raw_patrol_candidates", []))
        raw_matches, raw_dist = cfd._greedy_match(raw_patrol_pred, raw_patrol_prop, float(patrol_match_radius_m))
        raw_denom = max(len(raw_patrol_pred), len(raw_patrol_prop), 1)

        selected_patrol_pred = cfd._xy_points(pred_snap.get("selected_patrol_tasks", []))
        selected_patrol_prop = cfd._xy_points(prop_snap.get("selected_patrol_tasks", []))
        sel_matches, sel_dist = cfd._greedy_match(selected_patrol_pred, selected_patrol_prop, float(patrol_match_radius_m))
        sel_denom = max(len(selected_patrol_pred), len(selected_patrol_prop), 1)

        patrol_pred = cfd._patrol_points(pred_snap.get("tasks_active", []))
        patrol_prop = cfd._patrol_points(prop_snap.get("tasks_active", []))
        patrol_matches, patrol_dist = cfd._greedy_match(patrol_pred, patrol_prop, float(patrol_match_radius_m))
        patrol_denom = max(len(patrol_pred), len(patrol_prop), 1)

        pred_recent_patrol = cfd._recent_deterrence_patrol_fraction(
            pred_snap.get("tasks_active", []),
            pred_snap.get("tasks_done", []),
            float(pred_snap["t_s"]),
            float(recent_deterrence_window_s),
            float(recent_deterrence_radius_m),
        )
        prop_recent_patrol = cfd._recent_deterrence_patrol_fraction(
            prop_snap.get("tasks_active", []),
            prop_snap.get("tasks_done", []),
            float(prop_snap["t_s"]),
            float(recent_deterrence_window_s),
            float(recent_deterrence_radius_m),
        )

        pred_local_drop, pred_local_excess = cfd._local_drop_metrics(prev_pred, pred_snap, float(local_patch_radius_m))
        prop_local_drop, prop_local_excess = cfd._local_drop_metrics(prev_prop, prop_snap, float(local_patch_radius_m))

        per_time_rows.append(
            {
                "t_s": float(pred_snap["t_s"]),
                "lambda_l1_mean": float(np.mean(np.abs(diff))),
                "lambda_l2_mean": float(np.sqrt(np.mean(diff ** 2))),
                "lambda_max_abs_diff": float(np.max(np.abs(diff))),
                "suppressed_area_fraction": float(np.mean((lam_prop + 1e-12) < (lam_pred - 1e-6))),
                "hotspot_overlap_at_k": float(hs_matches) / float(max(int(hotspot_top_k), 1)),
                "hotspot_mean_match_distance_m": hs_dist,
                "local_hotspot_filter_threshold_mean_prediction_only": pred_threshold,
                "local_hotspot_filter_threshold_mean_proposed": prop_threshold,
                "local_hotspots_raw_score_p90_prediction_only": pred_score_p90,
                "local_hotspots_raw_score_p90_proposed": prop_score_p90,
                "local_hotspots_raw_overlap": float(local_raw_matches) / float(local_raw_denom),
                "local_hotspots_raw_mean_match_distance_m": local_raw_dist,
                "local_hotspots_score_filtered_overlap": float(local_filtered_matches) / float(local_filtered_denom),
                "local_hotspots_score_filtered_mean_match_distance_m": local_filtered_dist,
                "local_hotspots_spaced_overlap": float(local_spaced_matches) / float(local_spaced_denom),
                "local_hotspots_spaced_mean_match_distance_m": local_spaced_dist,
                "raw_patrol_candidate_overlap": float(raw_matches) / float(raw_denom),
                "raw_patrol_candidate_mean_match_distance_m": raw_dist,
                "selected_patrol_overlap": float(sel_matches) / float(sel_denom),
                "selected_patrol_mean_match_distance_m": sel_dist,
                "patrol_overlap": float(patrol_matches) / float(patrol_denom),
                "patrol_mean_match_distance_m": patrol_dist,
                "recent_deterrence_patrol_fraction_prediction_only": pred_recent_patrol,
                "recent_deterrence_patrol_fraction_proposed": prop_recent_patrol,
                "local_lambda_drop_mean_prediction_only": pred_local_drop,
                "local_lambda_drop_mean_proposed": prop_local_drop,
                "local_excess_drop_mean_prediction_only": pred_local_excess,
                "local_excess_drop_mean_proposed": prop_local_excess,
            }
        )
        prev_pred = pred_snap
        prev_prop = prop_snap

    per_time_df = pd.DataFrame(per_time_rows)
    summary_df = cfd._summary_row(per_time_df, final_metrics_by_baseline)
    if summary_df.empty:
        return {"seed": int(seed)}
    row = summary_df.iloc[0].to_dict()
    row["seed"] = int(seed)
    return row


def _divergence_status(mean: float, ci95: float, threshold: float = DIVERGENCE_RERANK_THRESHOLD) -> str:
    if not np.isfinite(mean):
        return "WARN"
    lower = float(mean - ci95) if np.isfinite(ci95) else float(mean)
    upper = float(mean + ci95) if np.isfinite(ci95) else float(mean)
    if lower >= float(threshold):
        return "PASS"
    if upper < float(threshold):
        return "FAIL"
    return "WARN"


def _resolve_divergence_rerank_confirm_context(args) -> dict | None:
    config_path = str(getattr(args, "divergence_rerank_confirm_config", "")).strip()
    if not config_path:
        return None
    _parser, confirm_args, config_meta, planner_profile, planner_profile_values = confirm_lab._resolve_cli_args(
        ["--config", config_path]
    )
    return {
        "config_path": config_path,
        "args": confirm_args,
        "config_meta": config_meta,
        "planner_profile": planner_profile,
        "planner_profile_values": planner_profile_values,
        "seeds": confirm_lab._parse_int_list(confirm_args.seeds),
    }


def _build_divergence_rerank_confirm_sim_kwargs(
    confirm_args,
    row: pd.Series,
) -> dict[str, float | int | str | bool | dict | None]:
    sim_kwargs = dict(confirm_lab._build_sim_kwargs(confirm_args))
    sim_kwargs.update(
        {
            "use_frozen_calibration": False,
            "calibration_ranking_path": None,
            "calibration_manifest_path": None,
            "calibration_config_id": None,
            "prediction_only_model_overrides": _candidate_mode_overrides(row, "prediction_only"),
            "proposed_model_overrides": _candidate_mode_overrides(row, "proposed"),
        }
    )
    return sim_kwargs


def _rank_divergence_rerank_summary(summary_df: pd.DataFrame) -> pd.DataFrame:
    if summary_df.empty:
        return summary_df.copy()
    ranked = summary_df.copy()
    ranked["passes_divergence_floor_ci95"] = (
        pd.to_numeric(ranked["suppressed_area_fraction_lower_ci95"], errors="coerce") >= float(DIVERGENCE_RERANK_THRESHOLD)
    )
    ranked["passes_divergence_floor_mean"] = (
        pd.to_numeric(ranked["suppressed_area_fraction_mean"], errors="coerce") >= float(DIVERGENCE_RERANK_THRESHOLD)
    )
    ranked = ranked.sort_values(
        by=[
            "passes_divergence_floor_ci95",
            "passes_divergence_floor_mean",
            "suppressed_area_fraction_lower_ci95",
            "suppressed_area_fraction_mean",
            "final_response_improve_pct_mean",
            "final_exposure_improve_pct_mean",
            "calibration_rank",
            "config_id",
        ],
        ascending=[False, False, False, False, False, False, True, True],
    ).reset_index(drop=True)
    ranked.insert(0, "divergence_rerank_rank", np.arange(1, len(ranked) + 1))
    return ranked


def _run_divergence_rerank(args, feedback_summary_df: pd.DataFrame):
    if feedback_summary_df.empty or int(args.divergence_rerank_top_k) <= 0:
        return pd.DataFrame(), pd.DataFrame()

    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    candidate_df = feedback_summary_df.copy()
    if "guardrail_satisfied" in candidate_df.columns:
        candidate_df = candidate_df.loc[candidate_df["guardrail_satisfied"].astype(bool)].copy()
    candidate_df = candidate_df.head(int(args.divergence_rerank_top_k)).reset_index(drop=True)
    if candidate_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    confirm_context = _resolve_divergence_rerank_confirm_context(args)
    if confirm_context is not None:
        seeds = list(confirm_context["seeds"])
        confirm_args = confirm_context["args"]
        per_seed_frames = []
        summary_rows = []
        metric_names = (
            "suppressed_area_fraction_mean",
            "final_exposure_improve_pct",
            "final_response_improve_pct",
            "local_hotspots_score_filtered_overlap_mean",
            "raw_patrol_candidate_overlap_mean",
            "selected_patrol_overlap_mean",
            "patrol_overlap_mean",
        )

        for candidate in candidate_df.to_dict("records"):
            sim_kwargs = _build_divergence_rerank_confirm_sim_kwargs(confirm_args, pd.Series(candidate))
            print(
                f"[divergence-rerank {candidate['config_id']}] "
                f"confirm_config={confirm_context['config_path']} "
                f"seeds={','.join(str(s) for s in seeds)}"
            )
            _per_time_all, candidate_per_seed_df, aggregate_df, acceptance_df, bottleneck_hint = confirm_lab._run_confirm_evaluation(
                confirm_args,
                seeds=seeds,
                sim_kwargs=sim_kwargs,
            )
            if candidate_per_seed_df.empty:
                continue

            candidate_per_seed_df = candidate_per_seed_df.copy()
            candidate_per_seed_df.insert(0, "calibration_rank", int(candidate["rank"]))
            candidate_per_seed_df.insert(0, "proposed_config_id", str(candidate["proposed_config_id"]))
            candidate_per_seed_df.insert(0, "prediction_only_config_id", str(candidate["prediction_only_config_id"]))
            candidate_per_seed_df.insert(0, "config_id", str(candidate["config_id"]))
            per_seed_frames.append(candidate_per_seed_df)

            aggregate_by_metric = {
                str(row["metric"]): row for row in aggregate_df.to_dict("records")
            }
            acceptance_by_mode = {
                str(row["failure_mode"]): row for row in acceptance_df.to_dict("records")
            }
            row = {
                "config_id": str(candidate["config_id"]),
                "prediction_only_config_id": str(candidate["prediction_only_config_id"]),
                "proposed_config_id": str(candidate["proposed_config_id"]),
                "calibration_rank": int(candidate["rank"]),
                "confirm_bottleneck_hint": str(bottleneck_hint),
                **{
                    key: _plain_value(value)
                    for key, value in candidate.items()
                    if str(key).startswith("prediction_only_model_") or str(key).startswith("proposed_model_")
                },
            }
            for metric in metric_names:
                stats = aggregate_by_metric.get(metric, {})
                metric_base = str(metric[:-5]) if str(metric).endswith("_mean") else str(metric)
                row[f"{metric_base}_mean"] = cfd._safe_float(stats.get("mean", float("nan")))
                row[f"{metric_base}_ci95"] = cfd._safe_float(stats.get("ci95", float("nan")))
                row[f"{metric_base}_lower_ci95"] = cfd._safe_float(stats.get("lower_ci95", float("nan")))
                row[f"{metric_base}_upper_ci95"] = cfd._safe_float(stats.get("upper_ci95", float("nan")))
                row[f"{metric_base}_n"] = int(stats.get("n", 0) or 0)
            divergence_acceptance = acceptance_by_mode.get("no_meaningful_field_divergence", {})
            row["divergence_status"] = str(
                divergence_acceptance.get(
                    "status",
                    _divergence_status(
                        float(row["suppressed_area_fraction_mean"]),
                        float(row["suppressed_area_fraction_ci95"]),
                    ),
                )
            )
            summary_rows.append(row)

        per_seed_df = pd.concat(per_seed_frames, ignore_index=True) if per_seed_frames else pd.DataFrame()
        summary_df = pd.DataFrame(summary_rows)
        summary_df = _rank_divergence_rerank_summary(summary_df) if not summary_df.empty else summary_df
        return per_seed_df, summary_df

    seeds = _parse_int_list(args.divergence_rerank_seeds)
    per_seed_rows = []
    for candidate in candidate_df.to_dict("records"):
        sim_kwargs = _build_divergence_rerank_sim_kwargs(args, pd.Series(candidate))
        print(
            f"[divergence-rerank {candidate['config_id']}] "
            f"seeds={','.join(str(s) for s in seeds)}"
        )
        for seed in seeds:
            row = {
                "config_id": str(candidate["config_id"]),
                "prediction_only_config_id": str(candidate["prediction_only_config_id"]),
                "proposed_config_id": str(candidate["proposed_config_id"]),
                "calibration_rank": int(candidate["rank"]),
                "seed": int(seed),
                **{
                    key: _plain_value(value)
                    for key, value in candidate.items()
                    if str(key).startswith("prediction_only_model_") or str(key).startswith("proposed_model_")
                },
            }
            row.update(
                _summarize_divergence_seed(
                    seed=int(seed),
                    sim_kwargs=sim_kwargs,
                    sample_period_s=float(args.divergence_rerank_sample_period_s),
                    hotspot_top_k=int(args.divergence_rerank_hotspot_top_k),
                    hotspot_match_radius_m=float(args.divergence_rerank_hotspot_match_radius_m),
                    patrol_match_radius_m=float(args.divergence_rerank_patrol_match_radius_m),
                    recent_deterrence_window_s=float(args.divergence_rerank_recent_deterrence_window_s),
                    recent_deterrence_radius_m=float(args.divergence_rerank_recent_deterrence_radius_m),
                    local_patch_radius_m=float(args.divergence_rerank_local_patch_radius_m),
                )
            )
            per_seed_rows.append(row)

    per_seed_df = pd.DataFrame(per_seed_rows)
    if per_seed_df.empty:
        return per_seed_df, pd.DataFrame()

    summary_rows = []
    metric_names = (
        "suppressed_area_fraction_mean",
        "final_exposure_improve_pct",
        "final_response_improve_pct",
        "local_hotspots_score_filtered_overlap_mean",
        "raw_patrol_candidate_overlap_mean",
        "selected_patrol_overlap_mean",
        "patrol_overlap_mean",
    )
    id_cols = tuple(
        [
            "config_id",
            "prediction_only_config_id",
            "proposed_config_id",
            "calibration_rank",
            *[col for col in per_seed_df.columns if str(col).startswith("prediction_only_model_")],
            *[col for col in per_seed_df.columns if str(col).startswith("proposed_model_")],
        ]
    )
    for config_id, group in per_seed_df.groupby("config_id", sort=False):
        first = group.iloc[0]
        row = {key: _plain_value(first[key]) for key in id_cols}
        for metric in metric_names:
            stats = _stats(group[metric].to_numpy(dtype=float))
            row[f"{metric}_mean"] = stats["mean"]
            row[f"{metric}_ci95"] = stats["ci95"]
            row[f"{metric}_lower_ci95"] = (
                float(stats["mean"] - stats["ci95"]) if np.isfinite(stats["mean"]) and np.isfinite(stats["ci95"]) else stats["mean"]
            )
            row[f"{metric}_upper_ci95"] = (
                float(stats["mean"] + stats["ci95"]) if np.isfinite(stats["mean"]) and np.isfinite(stats["ci95"]) else stats["mean"]
            )
            row[f"{metric}_n"] = stats["n"]
        row["divergence_status"] = _divergence_status(
            float(row["suppressed_area_fraction_mean_mean"]),
            float(row["suppressed_area_fraction_mean_ci95"]),
        )
        row["suppressed_area_fraction_mean"] = float(row.pop("suppressed_area_fraction_mean_mean"))
        row["suppressed_area_fraction_ci95"] = float(row.pop("suppressed_area_fraction_mean_ci95"))
        row["suppressed_area_fraction_lower_ci95"] = float(row.pop("suppressed_area_fraction_mean_lower_ci95"))
        row["suppressed_area_fraction_upper_ci95"] = float(row.pop("suppressed_area_fraction_mean_upper_ci95"))
        row["suppressed_area_fraction_n"] = int(row.pop("suppressed_area_fraction_mean_n"))
        summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows)
    summary_df = _rank_divergence_rerank_summary(summary_df)
    return per_seed_df, summary_df


def _select_deployment_row(
    calibration_ranking_df: pd.DataFrame,
    divergence_summary_df: pd.DataFrame,
) -> tuple[str, dict]:
    if not divergence_summary_df.empty:
        top = divergence_summary_df.iloc[0]
        return "divergence_rerank", {key: _plain_value(value) for key, value in top.to_dict().items()}
    if not calibration_ranking_df.empty:
        top = calibration_ranking_df.iloc[0]
        return "calibration", {key: _plain_value(value) for key, value in top.to_dict().items()}
    return "none", {}


def _plot_ranking(summary_df: pd.DataFrame, out_png: Path):
    if summary_df.empty:
        return
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    colors = ["#2ca02c" if bool(v) else "#d62728" for v in summary_df.get("guardrail_satisfied", pd.Series(False, index=summary_df.index))]
    axes[0].scatter(
        summary_df["proposed_field_logloss_mean"],
        summary_df["proposed_field_brier_mean"],
        c=colors,
        s=55,
        alpha=0.85,
    )
    axes[0].set_xlabel("Proposed field log loss (mean)")
    axes[0].set_ylabel("Proposed field Brier (mean)")
    axes[0].set_title("Full calibration tradeoff")
    axes[0].grid(alpha=0.25)

    top = summary_df.nsmallest(min(10, len(summary_df)), "rank")
    ypos = np.arange(len(top))
    bar_colors = ["#2ca02c" if bool(v) else "#d62728" for v in top.get("guardrail_satisfied", pd.Series(False, index=top.index))]
    axes[1].barh(ypos, top["proposed_field_logloss_mean"], color=bar_colors, alpha=0.85)
    axes[1].set_yticks(ypos)
    axes[1].set_yticklabels(top["config_id"].tolist())
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Proposed field log loss (mean)")
    axes[1].set_title("Top-ranked full configs")
    axes[1].grid(axis="x", alpha=0.25)

    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def _write_readme(
    outdir: Path,
    *,
    prediction_summary_csv: Path,
    proposed_summary_csv: Path,
    joint_summary_csv: Path,
    divergence_summary_csv: Path | None,
    run_csv: Path,
    summary_csv: Path,
    ranking_csv: Path,
    manifest_json: Path,
    prediction_summary_df: pd.DataFrame,
    proposed_summary_df: pd.DataFrame,
    ranking_df: pd.DataFrame,
    divergence_summary_df: pd.DataFrame,
    guardrail_satisfied: bool,
    deployment_selection_policy: str,
    deployment_row: dict,
) -> Path:
    lines = [
        "# SESTPP Calibration Sweep",
        "",
        *render_stage_readme_lines("model_calibration"),
        "",
        "## Key Outputs",
        f"- Prediction-only stage summary CSV: `{prediction_summary_csv.name}`",
        f"- Proposed stage summary CSV: `{proposed_summary_csv.name}`",
        f"- Joint pairing stage summary CSV: `{joint_summary_csv.name}`",
        f"- Canonical per-run CSV: `{run_csv.name}`",
        f"- Canonical summary CSV: `{summary_csv.name}`",
        f"- Canonical ranking CSV: `{ranking_csv.name}`",
        f"- Manifest: `{manifest_json.name}`",
        "- Ranking plot: `sestpp_calibration_sweep_tradeoff.png`",
    ]
    if divergence_summary_csv is not None:
        lines.append(f"- Divergence-rerank summary CSV: `{divergence_summary_csv.name}`")
    if not prediction_summary_df.empty:
        prediction_best = prediction_summary_df.iloc[0]
        lines.extend(
            [
                "",
                "## Best Prediction-Only Config",
                f"- Config id: `{prediction_best['config_id']}`",
                f"- Prediction-only field log loss mean +/- CI95: {_format_metric(prediction_best['prediction_only_field_logloss_mean'])} +/- {_format_metric(prediction_best['prediction_only_field_logloss_ci95'])}",
                f"- Prediction-only field Brier mean +/- CI95: {_format_metric(prediction_best['prediction_only_field_brier_mean'])} +/- {_format_metric(prediction_best['prediction_only_field_brier_ci95'])}",
                f"- Prediction-only NLL mean +/- CI95: {_format_metric(prediction_best['prediction_only_nll_mean'])} +/- {_format_metric(prediction_best['prediction_only_nll_ci95'])}",
            ]
        )
    if not proposed_summary_df.empty:
        proposed_best = proposed_summary_df.iloc[0]
        lines.extend(
            [
                "",
                "## Best Proposed Config",
                f"- Config id: `{proposed_best['config_id']}`",
                f"- Proposed field log loss mean +/- CI95: {_format_metric(proposed_best['proposed_field_logloss_mean'])} +/- {_format_metric(proposed_best['proposed_field_logloss_ci95'])}",
                f"- Proposed field Brier mean +/- CI95: {_format_metric(proposed_best['proposed_field_brier_mean'])} +/- {_format_metric(proposed_best['proposed_field_brier_ci95'])}",
                f"- Proposed NLL mean +/- CI95: {_format_metric(proposed_best['proposed_nll_mean'])} +/- {_format_metric(proposed_best['proposed_nll_ci95'])}",
            ]
        )
    if not ranking_df.empty:
        top = ranking_df.iloc[0]
        lines.extend(
            [
                "",
                "## Best Joint Pair",
                f"- Config id: `{top['config_id']}`",
                f"- Prediction-only config id: `{top['prediction_only_config_id']}`",
                f"- Proposed config id: `{top['proposed_config_id']}`",
                f"- Guardrail satisfied: `{bool(top.get('guardrail_satisfied', False))}`",
                f"- Proposed field log loss mean +/- CI95: {_format_metric(top['proposed_field_logloss_mean'])} +/- {_format_metric(top['proposed_field_logloss_ci95'])}",
                f"- Proposed field Brier mean +/- CI95: {_format_metric(top['proposed_field_brier_mean'])} +/- {_format_metric(top['proposed_field_brier_ci95'])}",
                f"- Proposed NLL mean +/- CI95: {_format_metric(top['proposed_nll_mean'])} +/- {_format_metric(top['proposed_nll_ci95'])}",
                f"- NLL improvement mean: {_format_metric(top['nll_improvement_pct_mean'])}%",
                "",
                "### Saved Parameter Blocks",
                f"- Prediction-only sigma/omega/alpha_in/mu_base: `{_format_metric(top['prediction_only_model_sigma'])}` / `{_format_metric(top['prediction_only_model_omega'])}` / `{_format_metric(top['prediction_only_model_alpha_in'])}` / `{_format_metric(top['prediction_only_model_mu_base'])}`",
                f"- Proposed sigma/omega/alpha_in/alpha_inhib/mu_base: `{_format_metric(top['proposed_model_sigma'])}` / `{_format_metric(top['proposed_model_omega'])}` / `{_format_metric(top['proposed_model_alpha_in'])}` / `{_format_metric(top['proposed_model_alpha_inhib'])}` / `{_format_metric(top['proposed_model_mu_base'])}`",
            ]
        )
    if divergence_summary_csv is not None and not divergence_summary_df.empty:
        top = divergence_summary_df.iloc[0]
        lines.extend(
            [
                "",
                "## Deployment Recommendation",
                f"- Selection policy: `{deployment_selection_policy}`",
                f"- Recommended config id: `{deployment_row.get('config_id', '')}`",
                f"- Calibration rank: `{deployment_row.get('calibration_rank', '')}`",
                f"- Divergence status: `{top.get('divergence_status', '')}`",
                f"- Suppressed-area mean +/- CI95: {_format_metric(top['suppressed_area_fraction_mean'])} +/- {_format_metric(top['suppressed_area_fraction_ci95'])}",
                f"- Final exposure improve mean +/- CI95: {_format_metric(top['final_exposure_improve_pct_mean'])} +/- {_format_metric(top['final_exposure_improve_pct_ci95'])}",
                f"- Final response improve mean +/- CI95: {_format_metric(top['final_response_improve_pct_mean'])} +/- {_format_metric(top['final_response_improve_pct_ci95'])}",
            ]
        )
    lines.extend(
        [
            "",
            "## Guardrail",
            f"- Any full config satisfied paired non-worsening guardrails: `{bool(guardrail_satisfied)}`",
            "",
            *render_execution_order_lines(),
        ]
    )
    readme_path = outdir / "SESTPP_CALIBRATION_README.md"
    readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return readme_path


def _run_shared_stage(args):
    base_cfg = _base_cfg_kwargs(args)
    run_rows = []
    grid_entries = []
    grid = _shared_grid(args)

    for idx, (sigma, omega, alpha_in, alpha_cross, mu_base, bg_ema) in enumerate(grid, start=1):
        config_id = f"P{idx:02d}"
        prediction_entry = _mode_param_entry(
            "prediction_only",
            sigma=float(sigma),
            omega=float(omega),
            omega_inhib=float(args.prediction_only_model_omega_inhib),
            alpha_in=float(alpha_in),
            alpha_cross=float(alpha_cross),
            alpha_inhib=float(args.prediction_only_model_alpha_inhib),
            mu_base=float(mu_base),
            bg_ema=float(bg_ema),
            feedback_sigma_scale=1.0,
            feedback_omega_scale=1.0,
        )
        grid_entries.append({"config_id": config_id, "prediction_only_config_id": config_id, **prediction_entry})

        cfg = SubsystemConfig(
            **base_cfg,
            prediction_only_model_sigma=float(sigma),
            prediction_only_model_omega=float(omega),
            prediction_only_model_omega_inhib=float(args.prediction_only_model_omega_inhib),
            prediction_only_model_alpha_in=float(alpha_in),
            prediction_only_model_alpha_cross=float(alpha_cross),
            prediction_only_model_alpha_inhib=float(args.prediction_only_model_alpha_inhib),
            prediction_only_model_mu_base=float(mu_base),
            prediction_only_model_bg_ema=float(bg_ema),
            prediction_only_model_feedback_sigma_scale=1.0,
            prediction_only_model_feedback_omega_scale=1.0,
            proposed_model_sigma=float(sigma),
            proposed_model_omega=float(omega),
            proposed_model_omega_inhib=float(args.proposed_model_omega_inhib),
            proposed_model_alpha_in=float(alpha_in),
            proposed_model_alpha_cross=float(alpha_cross),
            proposed_model_alpha_inhib=float(args.prediction_only_model_alpha_inhib),
            proposed_model_mu_base=float(mu_base),
            proposed_model_bg_ema=float(bg_ema),
            proposed_model_feedback_sigma_scale=1.0,
            proposed_model_feedback_omega_scale=1.0,
        )

        print(
            f"[prediction {idx}/{len(grid)} {config_id}] "
            f"sigma={sigma} omega={omega} alpha_in={alpha_in} alpha_cross={alpha_cross} "
            f"mu_base={mu_base} bg_ema={bg_ema}"
        )
        for run_idx in range(cfg.runs):
            seed = cfg.seed_start + run_idx
            res = simulate_one_run(run_idx, seed, cfg)
            row = {
                "config_id": config_id,
                "prediction_only_config_id": config_id,
                **prediction_entry,
                "seed": int(seed),
                **res["paired_metrics"],
            }
            run_rows.append(row)

    run_df = pd.DataFrame(run_rows)
    summary_df = _rank_shared_summary(_summarize_configs(run_df, metric_names=SHARED_METRICS))
    return run_df, summary_df, grid_entries


def _run_proposed_stage(args):
    base_cfg = _base_cfg_kwargs(args)
    run_rows = []
    grid_entries = []
    proposed_grid = _proposed_grid(args)

    for idx, (sigma, omega, alpha_in, alpha_cross, mu_base, bg_ema, alpha_inhib, sigma_scale, omega_scale) in enumerate(proposed_grid, start=1):
        config_id = f"R{idx:02d}"
        proposed_entry = _mode_param_entry(
            "proposed",
            sigma=float(sigma),
            omega=float(omega),
            omega_inhib=float(args.proposed_model_omega_inhib),
            alpha_in=float(alpha_in),
            alpha_cross=float(alpha_cross),
            alpha_inhib=float(alpha_inhib),
            mu_base=float(mu_base),
            bg_ema=float(bg_ema),
            feedback_sigma_scale=float(sigma_scale),
            feedback_omega_scale=float(omega_scale),
        )
        grid_entries.append({"config_id": config_id, "proposed_config_id": config_id, **proposed_entry})

        cfg = SubsystemConfig(
            **base_cfg,
            prediction_only_model_sigma=float(sigma),
            prediction_only_model_omega=float(omega),
            prediction_only_model_omega_inhib=float(args.prediction_only_model_omega_inhib),
            prediction_only_model_alpha_in=float(alpha_in),
            prediction_only_model_alpha_cross=float(alpha_cross),
            prediction_only_model_alpha_inhib=float(alpha_inhib),
            prediction_only_model_mu_base=float(mu_base),
            prediction_only_model_bg_ema=float(bg_ema),
            prediction_only_model_feedback_sigma_scale=float(sigma_scale),
            prediction_only_model_feedback_omega_scale=float(omega_scale),
            proposed_model_sigma=float(sigma),
            proposed_model_omega=float(omega),
            proposed_model_omega_inhib=float(args.proposed_model_omega_inhib),
            proposed_model_alpha_in=float(alpha_in),
            proposed_model_alpha_cross=float(alpha_cross),
            proposed_model_alpha_inhib=float(alpha_inhib),
            proposed_model_mu_base=float(mu_base),
            proposed_model_bg_ema=float(bg_ema),
            proposed_model_feedback_sigma_scale=float(sigma_scale),
            proposed_model_feedback_omega_scale=float(omega_scale),
        )

        print(
            f"[proposed {idx}/{len(proposed_grid)} {config_id}] "
            f"sigma={sigma} omega={omega} alpha_in={alpha_in} alpha_cross={alpha_cross} "
            f"alpha_inhib={alpha_inhib} sigma_scale={sigma_scale} omega_scale={omega_scale}"
        )
        for run_idx in range(cfg.runs):
            seed = cfg.seed_start + run_idx
            res = simulate_one_run(run_idx, seed, cfg)
            row = {
                "config_id": config_id,
                "proposed_config_id": config_id,
                **proposed_entry,
                "seed": int(seed),
                **res["paired_metrics"],
            }
            run_rows.append(row)

    run_df = pd.DataFrame(run_rows)
    summary_df = _rank_proposed_summary(_summarize_configs(run_df, metric_names=PROPOSED_METRICS))
    return run_df, summary_df, grid_entries


def _run_joint_stage(args, prediction_summary_df: pd.DataFrame, proposed_summary_df: pd.DataFrame):
    base_cfg = _base_cfg_kwargs(args)
    run_rows = []
    grid_entries = []
    prediction_shortlist = prediction_summary_df.head(max(int(args.shortlist_size), 0))
    proposed_shortlist = proposed_summary_df.head(max(int(args.shortlist_size), 0))
    config_counter = 0

    for pred_row in prediction_shortlist.itertuples(index=False):
        pred_entry = _mode_param_entry(
            "prediction_only",
            sigma=float(pred_row.prediction_only_model_sigma),
            omega=float(pred_row.prediction_only_model_omega),
            omega_inhib=float(pred_row.prediction_only_model_omega_inhib),
            alpha_in=float(pred_row.prediction_only_model_alpha_in),
            alpha_cross=float(pred_row.prediction_only_model_alpha_cross),
            alpha_inhib=float(pred_row.prediction_only_model_alpha_inhib),
            mu_base=float(pred_row.prediction_only_model_mu_base),
            bg_ema=float(pred_row.prediction_only_model_bg_ema),
            feedback_sigma_scale=float(pred_row.prediction_only_model_feedback_sigma_scale),
            feedback_omega_scale=float(pred_row.prediction_only_model_feedback_omega_scale),
        )
        for prop_row in proposed_shortlist.itertuples(index=False):
            config_counter += 1
            config_id = f"C{config_counter:03d}"
            prop_entry = _mode_param_entry(
                "proposed",
                sigma=float(prop_row.proposed_model_sigma),
                omega=float(prop_row.proposed_model_omega),
                omega_inhib=float(prop_row.proposed_model_omega_inhib),
                alpha_in=float(prop_row.proposed_model_alpha_in),
                alpha_cross=float(prop_row.proposed_model_alpha_cross),
                alpha_inhib=float(prop_row.proposed_model_alpha_inhib),
                mu_base=float(prop_row.proposed_model_mu_base),
                bg_ema=float(prop_row.proposed_model_bg_ema),
                feedback_sigma_scale=float(prop_row.proposed_model_feedback_sigma_scale),
                feedback_omega_scale=float(prop_row.proposed_model_feedback_omega_scale),
            )
            grid_entries.append(
                {
                    "config_id": config_id,
                    "prediction_only_config_id": str(pred_row.config_id),
                    "proposed_config_id": str(prop_row.config_id),
                    **pred_entry,
                    **prop_entry,
                }
            )

            cfg = SubsystemConfig(
                **base_cfg,
                prediction_only_model_sigma=float(pred_row.prediction_only_model_sigma),
                prediction_only_model_omega=float(pred_row.prediction_only_model_omega),
                prediction_only_model_omega_inhib=float(pred_row.prediction_only_model_omega_inhib),
                prediction_only_model_alpha_in=float(pred_row.prediction_only_model_alpha_in),
                prediction_only_model_alpha_cross=float(pred_row.prediction_only_model_alpha_cross),
                prediction_only_model_alpha_inhib=float(pred_row.prediction_only_model_alpha_inhib),
                prediction_only_model_mu_base=float(pred_row.prediction_only_model_mu_base),
                prediction_only_model_bg_ema=float(pred_row.prediction_only_model_bg_ema),
                prediction_only_model_feedback_sigma_scale=float(pred_row.prediction_only_model_feedback_sigma_scale),
                prediction_only_model_feedback_omega_scale=float(pred_row.prediction_only_model_feedback_omega_scale),
                proposed_model_sigma=float(prop_row.proposed_model_sigma),
                proposed_model_omega=float(prop_row.proposed_model_omega),
                proposed_model_omega_inhib=float(prop_row.proposed_model_omega_inhib),
                proposed_model_alpha_in=float(prop_row.proposed_model_alpha_in),
                proposed_model_alpha_cross=float(prop_row.proposed_model_alpha_cross),
                proposed_model_alpha_inhib=float(prop_row.proposed_model_alpha_inhib),
                proposed_model_mu_base=float(prop_row.proposed_model_mu_base),
                proposed_model_bg_ema=float(prop_row.proposed_model_bg_ema),
                proposed_model_feedback_sigma_scale=float(prop_row.proposed_model_feedback_sigma_scale),
                proposed_model_feedback_omega_scale=float(prop_row.proposed_model_feedback_omega_scale),
            )

            print(
                f"[joint {config_counter} {config_id}] "
                f"prediction={pred_row.config_id} proposed={prop_row.config_id}"
            )
            for run_idx in range(cfg.runs):
                seed = cfg.seed_start + run_idx
                res = simulate_one_run(run_idx, seed, cfg)
                row = {
                    "config_id": config_id,
                    "prediction_only_config_id": str(pred_row.config_id),
                    "proposed_config_id": str(prop_row.config_id),
                    **pred_entry,
                    **prop_entry,
                    "seed": int(seed),
                    **res["paired_metrics"],
                }
                run_rows.append(row)

    run_df = pd.DataFrame(run_rows)
    summary_df = _rank_feedback_summary(_summarize_configs(run_df, metric_names=FEEDBACK_METRICS))
    return run_df, summary_df, grid_entries


def main():
    parser = argparse.ArgumentParser(description="Joint SESTPP forecast-model calibration sweep")
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--seed-start", type=int, default=2026)
    parser.add_argument("--T-end", type=float, default=10800.0)
    parser.add_argument("--warmup-s", type=float, default=1800.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--forecast-horizon-s", type=float, default=300.0)
    parser.add_argument("--eval-period-s", type=float, default=30.0)
    parser.add_argument("--outdir", type=str, default="results/sestpp_calibration_sweep")
    parser.add_argument("--limit-settings", type=int, default=0, help="0 => all shared-stage configs")
    parser.add_argument("--shortlist-size", type=int, default=3)
    parser.add_argument("--intervention-prob", type=float, default=0.45)
    parser.add_argument("--intervention-cooldown-s", type=float, default=40.0)
    parser.add_argument("--intervention-delay-s", type=float, default=10.0)
    parser.add_argument("--intervention-shuffle", choices=["none", "space", "time", "spacetime"], default="none")
    parser.add_argument("--shuffle-time-window-s", type=float, default=300.0)
    parser.add_argument("--beta-true", type=float, default=0.30)
    parser.add_argument("--model-omega-inhib", type=float, default=SubsystemConfig.model_omega_inhib)
    parser.add_argument("--stage1-model-alpha-inhib", type=float, default=SubsystemConfig.model_alpha_inhib)
    parser.add_argument("--prediction-only-model-omega-inhib", type=float, default=None)
    parser.add_argument("--prediction-only-model-alpha-inhib", type=float, default=None)
    parser.add_argument("--proposed-model-omega-inhib", type=float, default=None)
    parser.add_argument("--model-sigma-values", type=str, default="12,16")
    parser.add_argument("--model-omega-values", type=str, default="600,900")
    parser.add_argument("--model-alpha-in-values", type=str, default="0.20,0.30")
    parser.add_argument("--model-alpha-cross-values", type=str, default="0.0,0.05")
    parser.add_argument("--model-mu-base-values", type=str, default="5e-5,1e-4,2e-4")
    parser.add_argument("--model-bg-ema-values", type=str, default="1e-7,1e-6")
    parser.add_argument("--model-alpha-inhib-values", type=str, default="0.25,0.35,0.45,0.60")
    parser.add_argument("--model-feedback-sigma-scale-values", type=str, default="0.75,1.0,1.25")
    parser.add_argument("--model-feedback-omega-scale-values", type=str, default="0.75,1.0,1.50")
    parser.add_argument("--proposed-model-sigma-values", type=str, default="")
    parser.add_argument("--proposed-model-omega-values", type=str, default="")
    parser.add_argument("--proposed-model-alpha-in-values", type=str, default="")
    parser.add_argument("--proposed-model-alpha-cross-values", type=str, default="")
    parser.add_argument("--proposed-model-mu-base-values", type=str, default="")
    parser.add_argument("--proposed-model-bg-ema-values", type=str, default="")
    parser.add_argument("--proposed-model-alpha-inhib-values", type=str, default="")
    parser.add_argument("--proposed-model-feedback-sigma-scale-values", type=str, default="")
    parser.add_argument("--proposed-model-feedback-omega-scale-values", type=str, default="")
    parser.add_argument("--divergence-rerank", action="store_true")
    parser.add_argument("--divergence-rerank-top-k", type=int, default=0)
    parser.add_argument(
        "--divergence-rerank-confirm-config",
        type=str,
        default="configs/run_field_divergence_confirm_lab.yaml",
        help="When set, rerank candidates with the exact confirm runner config instead of the legacy inline rerank defaults.",
    )
    parser.add_argument("--divergence-rerank-seeds", type=str, default="2000,2001,2002,2003,2004")
    parser.add_argument("--divergence-rerank-t-end", type=float, default=3600.0)
    parser.add_argument("--divergence-rerank-dt", type=float, default=5.0)
    parser.add_argument("--divergence-rerank-sample-period-s", type=float, default=300.0)
    parser.add_argument("--divergence-rerank-hotspot-top-k", type=int, default=5)
    parser.add_argument("--divergence-rerank-hotspot-match-radius-m", type=float, default=25.0)
    parser.add_argument("--divergence-rerank-patrol-match-radius-m", type=float, default=25.0)
    parser.add_argument("--divergence-rerank-recent-deterrence-window-s", type=float, default=300.0)
    parser.add_argument("--divergence-rerank-recent-deterrence-radius-m", type=float, default=25.0)
    parser.add_argument("--divergence-rerank-local-patch-radius-m", type=float, default=20.0)
    parser.add_argument("--divergence-rerank-assignment-method", type=str, default="hungarian")
    parser.add_argument("--divergence-rerank-assignment-distance-cost-per-m", type=float, default=0.006)
    parser.add_argument("--divergence-rerank-assignment-switch-penalty", type=float, default=1.0)
    parser.add_argument("--divergence-rerank-task-replan-period-s", type=float, default=90.0)
    parser.add_argument("--divergence-rerank-assigner-w-task-value", type=float, default=0.0)
    parser.add_argument("--divergence-rerank-patrol-min-hotspot-score", type=float, default=1e-4)
    parser.add_argument("--divergence-rerank-patrol-hotspot-filter-mode", type=str, default="percentile")
    parser.add_argument("--divergence-rerank-patrol-hotspot-score-percentile", type=float, default=90.0)
    parser.add_argument("--divergence-rerank-patrol-hotspot-keep-top-k", type=int, default=6)
    parser.add_argument("--divergence-rerank-model-deterring-window-s", type=float, default=90.0)
    parser.add_argument("--divergence-rerank-model-deterring-min-persistence-replans", type=int, default=2)
    parser.add_argument("--divergence-rerank-model-deterring-max-eta-s", type=float, default=120.0)
    parser.add_argument("--divergence-rerank-model-deterring-score-margin", type=float, default=0.05)
    parser.add_argument("--divergence-rerank-model-deterring-budget-per-robot-per-hr", type=int, default=4)
    parser.add_argument("--divergence-rerank-model-deterring-budget-mode", type=str, default="count_per_hour")
    parser.add_argument("--divergence-rerank-model-deterring-budget-utility-per-robot-per-hr", type=float, default=5.0)
    parser.add_argument("--divergence-rerank-model-deterring-gate-policy", type=str, default="heuristic")
    parser.add_argument("--divergence-rerank-model-deterring-sprt-alpha", type=float, default=0.05)
    parser.add_argument("--divergence-rerank-model-deterring-sprt-beta", type=float, default=0.20)
    parser.add_argument("--divergence-rerank-model-deterring-chance-threshold", type=float, default=0.20)
    parser.add_argument("--divergence-rerank-model-deterring-min-deltaj-per-cost", type=float, default=0.15)
    args = parser.parse_args()
    args.prediction_only_model_omega_inhib = float(
        args.model_omega_inhib if args.prediction_only_model_omega_inhib in (None, "") else args.prediction_only_model_omega_inhib
    )
    args.prediction_only_model_alpha_inhib = float(
        args.stage1_model_alpha_inhib if args.prediction_only_model_alpha_inhib in (None, "") else args.prediction_only_model_alpha_inhib
    )
    args.proposed_model_omega_inhib = float(
        args.model_omega_inhib if args.proposed_model_omega_inhib in (None, "") else args.proposed_model_omega_inhib
    )

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    prediction_run_df, prediction_summary_df, prediction_grid_entries = _run_shared_stage(args)
    proposed_run_df, proposed_summary_df, proposed_grid_entries = _run_proposed_stage(args)
    joint_run_df, joint_summary_df, joint_grid_entries = _run_joint_stage(
        args,
        prediction_summary_df,
        proposed_summary_df,
    )
    divergence_run_df = pd.DataFrame()
    divergence_summary_df = pd.DataFrame()
    if bool(args.divergence_rerank):
        divergence_run_df, divergence_summary_df = _run_divergence_rerank(args, joint_summary_df)

    ranking_cols = [
        "rank",
        "config_id",
        "prediction_only_config_id",
        "proposed_config_id",
        "guardrail_satisfied",
        "prediction_only_model_sigma",
        "prediction_only_model_omega",
        "prediction_only_model_omega_inhib",
        "prediction_only_model_alpha_in",
        "prediction_only_model_alpha_cross",
        "prediction_only_model_alpha_inhib",
        "prediction_only_model_mu_base",
        "prediction_only_model_bg_ema",
        "prediction_only_model_feedback_sigma_scale",
        "prediction_only_model_feedback_omega_scale",
        "proposed_model_sigma",
        "proposed_model_omega",
        "proposed_model_omega_inhib",
        "proposed_model_alpha_in",
        "proposed_model_alpha_cross",
        "proposed_model_alpha_inhib",
        "proposed_model_mu_base",
        "proposed_model_bg_ema",
        "proposed_model_feedback_sigma_scale",
        "proposed_model_feedback_omega_scale",
        "proposed_field_logloss_mean",
        "proposed_field_logloss_ci95",
        "proposed_field_brier_mean",
        "proposed_field_brier_ci95",
        "proposed_nll_mean",
        "proposed_nll_ci95",
        "delta_field_logloss_proposed_minus_prediction_mean",
        "delta_field_brier_proposed_minus_prediction_mean",
        "delta_nll_proposed_minus_prediction_mean",
        "logloss_improvement_pct_mean",
        "brier_improvement_pct_mean",
        "nll_improvement_pct_mean",
    ]
    ranking_df = (
        joint_summary_df[ranking_cols].copy()
        if not joint_summary_df.empty
        else pd.DataFrame(columns=ranking_cols)
    )

    prediction_runs_csv = outdir / "sestpp_prediction_only_calibration_runs.csv"
    prediction_summary_csv = outdir / "sestpp_prediction_only_calibration_summary.csv"
    proposed_runs_csv = outdir / "sestpp_proposed_calibration_runs.csv"
    proposed_summary_csv = outdir / "sestpp_proposed_calibration_summary.csv"
    joint_runs_csv = outdir / "sestpp_joint_calibration_runs.csv"
    joint_summary_csv = outdir / "sestpp_joint_calibration_summary.csv"
    divergence_runs_csv = outdir / "sestpp_divergence_rerank_per_seed.csv"
    divergence_summary_csv = outdir / "sestpp_divergence_rerank_summary.csv"
    run_csv = outdir / "sestpp_calibration_sweep_per_run.csv"
    summary_csv = outdir / "sestpp_calibration_sweep_summary.csv"
    ranking_csv = outdir / "sestpp_calibration_sweep_ranking.csv"
    manifest_json = outdir / "sestpp_calibration_sweep_manifest.json"

    prediction_run_df.to_csv(prediction_runs_csv, index=False)
    prediction_summary_df.to_csv(prediction_summary_csv, index=False)
    proposed_run_df.to_csv(proposed_runs_csv, index=False)
    proposed_summary_df.to_csv(proposed_summary_csv, index=False)
    joint_run_df.to_csv(joint_runs_csv, index=False)
    joint_summary_df.to_csv(joint_summary_csv, index=False)
    if not divergence_run_df.empty:
        divergence_run_df.to_csv(divergence_runs_csv, index=False)
    if not divergence_summary_df.empty:
        divergence_summary_df.to_csv(divergence_summary_csv, index=False)
    joint_run_df.to_csv(run_csv, index=False)
    joint_summary_df.to_csv(summary_csv, index=False)
    ranking_df.to_csv(ranking_csv, index=False)

    guardrail_satisfied = bool(
        (joint_summary_df["guardrail_satisfied"].any()) if "guardrail_satisfied" in joint_summary_df.columns else False
    )
    deployment_selection_policy, deployment_row = _select_deployment_row(ranking_df, divergence_summary_df)

    def _best_models_from_row(row_like: pd.Series | dict) -> dict[str, dict[str, float]]:
        payload = row_like if isinstance(row_like, dict) else row_like.to_dict()
        return {
            "prediction_only": {
                key.replace("prediction_only_", "", 1): _plain_value(value)
                for key, value in payload.items()
                if key.startswith("prediction_only_model_")
            },
            "proposed": {
                key.replace("proposed_", "", 1): _plain_value(value)
                for key, value in payload.items()
                if key.startswith("proposed_model_")
            },
        }

    manifest = {
        "base_args": vars(args),
        "num_configs": int(len(joint_grid_entries)),
        "guardrail_satisfied": guardrail_satisfied,
        "prediction_only_best_config_id": (
            str(prediction_summary_df.iloc[0]["config_id"]) if not prediction_summary_df.empty else ""
        ),
        "proposed_best_config_id": (
            str(proposed_summary_df.iloc[0]["config_id"]) if not proposed_summary_df.empty else ""
        ),
        "deployment_selection_policy": str(deployment_selection_policy),
        "workflow_stage": stage_manifest("model_calibration"),
        "stages": {
            "prediction_only": {
                "num_configs": int(len(prediction_grid_entries)),
                "grid": prediction_grid_entries,
                "shortlist_size": int(min(max(int(args.shortlist_size), 0), len(prediction_summary_df))),
                "best_config_id": (str(prediction_summary_df.iloc[0]["config_id"]) if not prediction_summary_df.empty else ""),
            },
            "proposed": {
                "num_configs": int(len(proposed_grid_entries)),
                "grid": proposed_grid_entries,
                "shortlist_size": int(min(max(int(args.shortlist_size), 0), len(proposed_summary_df))),
                "best_config_id": (str(proposed_summary_df.iloc[0]["config_id"]) if not proposed_summary_df.empty else ""),
            },
            "joint_pairing": {
                "num_configs": int(len(joint_grid_entries)),
                "grid": joint_grid_entries,
            },
        },
        "grid": joint_grid_entries,
        "outputs": {
            "prediction_only_runs_csv": prediction_runs_csv.name,
            "prediction_only_summary_csv": prediction_summary_csv.name,
            "proposed_runs_csv": proposed_runs_csv.name,
            "proposed_summary_csv": proposed_summary_csv.name,
            "joint_runs_csv": joint_runs_csv.name,
            "joint_summary_csv": joint_summary_csv.name,
            "per_run_csv": run_csv.name,
            "summary_csv": summary_csv.name,
            "ranking_csv": ranking_csv.name,
            "tradeoff_png": "sestpp_calibration_sweep_tradeoff.png",
            "readme_md": "SESTPP_CALIBRATION_README.md",
        },
    }
    if not divergence_summary_df.empty:
        divergence_context = _resolve_divergence_rerank_confirm_context(args)
        manifest["stages"]["divergence_rerank"] = {
            "enabled": True,
            "top_k": int(args.divergence_rerank_top_k),
            "seeds": (
                list(divergence_context["seeds"])
                if divergence_context is not None
                else _parse_int_list(args.divergence_rerank_seeds)
            ),
            "confirm_config": (
                str(divergence_context["config_path"])
                if divergence_context is not None
                else ""
            ),
            "best_config_id": str(divergence_summary_df.iloc[0]["config_id"]),
        }
        manifest["outputs"]["divergence_rerank_runs_csv"] = divergence_runs_csv.name
        manifest["outputs"]["divergence_rerank_summary_csv"] = divergence_summary_csv.name
    if not ranking_df.empty:
        manifest["best_config_id"] = str(ranking_df.iloc[0]["config_id"])
        manifest["best_config"] = {
            key: _plain_value(value)
            for key, value in joint_summary_df.iloc[0].to_dict().items()
        }
        manifest["best_models"] = _best_models_from_row(joint_summary_df.iloc[0])
    if deployment_row:
        manifest["deployment_best_config_id"] = str(deployment_row.get("config_id", ""))
        manifest["deployment_best_config"] = dict(deployment_row)
        manifest["deployment_best_models"] = _best_models_from_row(deployment_row)
    if not prediction_summary_df.empty:
        manifest["prediction_only_best_config"] = {
            key: _plain_value(value)
            for key, value in prediction_summary_df.iloc[0].to_dict().items()
        }
    if not proposed_summary_df.empty:
        manifest["proposed_best_config"] = {
            key: _plain_value(value)
            for key, value in proposed_summary_df.iloc[0].to_dict().items()
        }
    with open(manifest_json, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    _plot_ranking(joint_summary_df, outdir / "sestpp_calibration_sweep_tradeoff.png")
    readme_path = _write_readme(
        outdir,
        prediction_summary_csv=prediction_summary_csv,
        proposed_summary_csv=proposed_summary_csv,
        joint_summary_csv=joint_summary_csv,
        divergence_summary_csv=(divergence_summary_csv if not divergence_summary_df.empty else None),
        run_csv=run_csv,
        summary_csv=summary_csv,
        ranking_csv=ranking_csv,
        manifest_json=manifest_json,
        prediction_summary_df=prediction_summary_df,
        proposed_summary_df=proposed_summary_df,
        ranking_df=joint_summary_df,
        divergence_summary_df=divergence_summary_df,
        guardrail_satisfied=guardrail_satisfied,
        deployment_selection_policy=deployment_selection_policy,
        deployment_row=deployment_row,
    )

    print("Saved:")
    print(f"- {prediction_runs_csv}")
    print(f"- {prediction_summary_csv}")
    print(f"- {proposed_runs_csv}")
    print(f"- {proposed_summary_csv}")
    print(f"- {joint_runs_csv}")
    print(f"- {joint_summary_csv}")
    if not divergence_run_df.empty:
        print(f"- {divergence_runs_csv}")
    if not divergence_summary_df.empty:
        print(f"- {divergence_summary_csv}")
    print(f"- {run_csv}")
    print(f"- {summary_csv}")
    print(f"- {ranking_csv}")
    print(f"- {manifest_json}")
    print(f"- {outdir / 'sestpp_calibration_sweep_tradeoff.png'}")
    print(f"- {readme_path}")


if __name__ == "__main__":
    main()
