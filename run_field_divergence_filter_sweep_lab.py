from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import compare_field_divergence_lab as cfd
import DeterrentSystem_assignment_lab as ds
from config_loader import add_config_argument, parse_args_with_config


FIELD_DIVERGENCE_FILTER_SWEEP_CONFIG_ALIASES = {
    **cfd.FIELD_DIVERGENCE_CONFIG_ALIASES,
    "runner.seeds": "seeds",
    "sweep.patrol_filter_modes": "patrol_filter_modes",
    "sweep.patrol_percentiles": "patrol_percentiles",
    "sweep.patrol_keep_top_k_values": "patrol_keep_top_k_values",
    "sweep.task_replan_period_values": "task_replan_period_values",
    "sweep.model_deterring_gate_policies": "model_deterring_gate_policies",
    "sweep.model_deterring_sprt_alpha_values": "model_deterring_sprt_alpha_values",
    "sweep.model_deterring_chance_threshold_values": "model_deterring_chance_threshold_values",
    "sweep.model_deterring_min_deltaj_per_cost_values": "model_deterring_min_deltaj_per_cost_values",
}


def _parse_int_list(text: str) -> List[int]:
    out = []
    for chunk in str(text).split(","):
        s = str(chunk).strip()
        if s:
            out.append(int(s))
    return out


def _parse_float_list(text: str) -> List[float]:
    out = []
    for chunk in str(text).split(","):
        s = str(chunk).strip()
        if s:
            out.append(float(s))
    return out


def _parse_str_list(text: str) -> List[str]:
    out = []
    for chunk in str(text).split(","):
        s = str(chunk).strip()
        if s:
            out.append(s)
    return out


def _aggregate(values: pd.Series) -> tuple[float, float, float]:
    arr = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if arr.size == 0:
        return float("nan"), float("nan"), float("nan")
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    ci95 = float(1.96 * std / math.sqrt(arr.size)) if arr.size > 1 else 0.0
    return mean, std, ci95


def _build_sim_kwargs(
    args: argparse.Namespace,
    filter_mode: str,
    percentile: float | None,
    keep_top_k: int | None,
    replan_period_s: float,
    gate_policy: str,
    sprt_alpha: float,
    chance_threshold: float,
    min_deltaj_per_cost: float,
) -> dict:
    deterring_modes = {
        "formation": {"beta": 0.30 * float(args.model_beta_scale), "omega": 800.0, "sigma": 18.0, "w_eta": 1.0, "fixed_cost": 0.0},
        "laser": {"beta": 0.45 * float(args.model_beta_scale), "omega": 400.0, "sigma": 10.0, "w_eta": 1.5, "fixed_cost": 0.0},
        "biosonic": {"beta": 0.25 * float(args.model_beta_scale), "omega": 600.0, "sigma": 20.0, "w_eta": 1.2, "fixed_cost": 0.0},
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
        "forecast_top_k": int(args.hotspot_top_k),
        "forecast_eval_period_s": 30.0,
        "task_replan_period_s": float(replan_period_s),
        "assignment_method": str(args.assignment_method),
        "assignment_distance_cost_per_m": float(args.assignment_distance_cost_per_m),
        "assignment_switch_penalty": float(args.assignment_switch_penalty),
        "assigner_w_task_value": float(args.assigner_w_task_value),
        "patrol_min_hotspot_score": float(args.patrol_min_hotspot_score),
        "patrol_hotspot_filter_mode": str(filter_mode),
        "patrol_hotspot_score_percentile": float(percentile if percentile is not None else args.patrol_hotspot_score_percentile),
        "patrol_hotspot_keep_top_k": int(keep_top_k if keep_top_k is not None else args.patrol_hotspot_keep_top_k),
        "model_deterring_window_s": float(args.model_deterring_window_s),
        "model_deterring_gate_policy": str(gate_policy),
        "model_deterring_sprt_alpha": float(sprt_alpha),
        "model_deterring_sprt_beta": float(args.model_deterring_sprt_beta),
        "model_deterring_chance_threshold": float(chance_threshold),
        "model_deterring_min_deltaJ_per_cost": float(min_deltaj_per_cost),
        "beta_true": 0.35 * float(args.truth_beta_scale),
        "omega_true": 600.0 * float(args.truth_omega_scale),
        "sigma_true": 12.0 * float(args.truth_sigma_scale),
        "deterring_modes": deterring_modes,
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
        "T_end": float(args.t_end),
        "dt": float(args.dt),
    }


def _config_id(
    filter_mode: str,
    percentile: float | None,
    keep_top_k: int | None,
    replan_period_s: float,
    gate_policy: str,
    sprt_alpha: float,
    chance_threshold: float,
    min_deltaj_per_cost: float,
) -> str:
    gate_tag = str(gate_policy).strip().lower()
    gate_suffix = ""
    if gate_tag == "sprt_capacity":
        gate_suffix = (
            f"_a{int(round(float(sprt_alpha) * 100.0))}"
            f"_c{int(round(float(chance_threshold) * 100.0))}"
            f"_u{int(round(float(min_deltaj_per_cost) * 100.0))}"
        )
    if str(filter_mode).strip().lower() == "percentile":
        return f"{gate_tag}_percentile_p{int(round(float(percentile)))}_r{int(round(float(replan_period_s)))}{gate_suffix}"
    return f"{gate_tag}_topk_k{int(keep_top_k)}_r{int(round(float(replan_period_s)))}{gate_suffix}"


def _run_one_seed(seed: int, sim_kwargs: dict, args: argparse.Namespace) -> dict:
    baseline_samples: Dict[str, Dict[int, dict]] = {}
    final_metrics_by_baseline: Dict[str, dict] = {}
    for baseline in ("prediction_only", "proposed"):
        samples, final_metrics = cfd._collect_sampled_frames(
            baseline=baseline,
            seed=int(seed),
            sim_kwargs=sim_kwargs,
            sample_period_s=float(args.sample_period_s),
            hotspot_top_k=int(args.hotspot_top_k),
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
        lam_l1 = float(np.mean(np.abs(diff)))
        lam_l2 = float(np.sqrt(np.mean(diff ** 2)))
        lam_max = float(np.max(np.abs(diff)))
        suppressed_frac = float(np.mean((lam_prop + 1e-12) < (lam_pred - 1e-6)))

        hs_pred = [(x, y) for (x, y, _s) in pred_snap.get("global_hotspots", [])[: int(args.hotspot_top_k)]]
        hs_prop = [(x, y) for (x, y, _s) in prop_snap.get("global_hotspots", [])[: int(args.hotspot_top_k)]]
        hs_matches, hs_dist = cfd._greedy_match(hs_pred, hs_prop, float(args.hotspot_match_radius_m))
        hotspot_overlap = float(hs_matches) / float(max(int(args.hotspot_top_k), 1))

        pred_score_stats = pred_snap.get("local_hotspot_score_stats", [])
        prop_score_stats = prop_snap.get("local_hotspot_score_stats", [])
        pred_threshold = cfd._stats_mean(pred_score_stats, "threshold_applied")
        prop_threshold = cfd._stats_mean(prop_score_stats, "threshold_applied")
        pred_score_p90 = cfd._score_quantile(pred_snap.get("local_hotspots_raw", []), 90.0)
        prop_score_p90 = cfd._score_quantile(prop_snap.get("local_hotspots_raw", []), 90.0)

        local_raw_pred = cfd._xy_points(pred_snap.get("local_hotspots_raw", []))
        local_raw_prop = cfd._xy_points(prop_snap.get("local_hotspots_raw", []))
        local_raw_matches, local_raw_dist = cfd._greedy_match(local_raw_pred, local_raw_prop, float(args.hotspot_match_radius_m))
        local_raw_denom = max(len(local_raw_pred), len(local_raw_prop), 1)
        local_raw_overlap = float(local_raw_matches) / float(local_raw_denom)

        local_filtered_pred = cfd._xy_points(pred_snap.get("local_hotspots_score_filtered", []))
        local_filtered_prop = cfd._xy_points(prop_snap.get("local_hotspots_score_filtered", []))
        local_filtered_matches, local_filtered_dist = cfd._greedy_match(
            local_filtered_pred, local_filtered_prop, float(args.hotspot_match_radius_m)
        )
        local_filtered_denom = max(len(local_filtered_pred), len(local_filtered_prop), 1)
        local_filtered_overlap = float(local_filtered_matches) / float(local_filtered_denom)

        local_spaced_pred = cfd._xy_points(pred_snap.get("local_hotspots_spaced", []))
        local_spaced_prop = cfd._xy_points(prop_snap.get("local_hotspots_spaced", []))
        local_spaced_matches, local_spaced_dist = cfd._greedy_match(
            local_spaced_pred, local_spaced_prop, float(args.hotspot_match_radius_m)
        )
        local_spaced_denom = max(len(local_spaced_pred), len(local_spaced_prop), 1)
        local_spaced_overlap = float(local_spaced_matches) / float(local_spaced_denom)

        raw_patrol_pred = cfd._xy_points(pred_snap.get("raw_patrol_candidates", []))
        raw_patrol_prop = cfd._xy_points(prop_snap.get("raw_patrol_candidates", []))
        raw_matches, raw_dist = cfd._greedy_match(raw_patrol_pred, raw_patrol_prop, float(args.patrol_match_radius_m))
        raw_denom = max(len(raw_patrol_pred), len(raw_patrol_prop), 1)
        raw_overlap = float(raw_matches) / float(raw_denom)

        selected_patrol_pred = cfd._xy_points(pred_snap.get("selected_patrol_tasks", []))
        selected_patrol_prop = cfd._xy_points(prop_snap.get("selected_patrol_tasks", []))
        sel_matches, sel_dist = cfd._greedy_match(selected_patrol_pred, selected_patrol_prop, float(args.patrol_match_radius_m))
        sel_denom = max(len(selected_patrol_pred), len(selected_patrol_prop), 1)
        selected_overlap = float(sel_matches) / float(sel_denom)

        patrol_pred = cfd._patrol_points(pred_snap.get("tasks_active", []))
        patrol_prop = cfd._patrol_points(prop_snap.get("tasks_active", []))
        patrol_matches, patrol_dist = cfd._greedy_match(patrol_pred, patrol_prop, float(args.patrol_match_radius_m))
        patrol_denom = max(len(patrol_pred), len(patrol_prop), 1)
        patrol_overlap = float(patrol_matches) / float(patrol_denom)

        pred_recent_patrol = cfd._recent_deterrence_patrol_fraction(
            pred_snap.get("tasks_active", []),
            pred_snap.get("tasks_done", []),
            float(pred_snap["t_s"]),
            float(args.recent_deterrence_window_s),
            float(args.recent_deterrence_radius_m),
        )
        prop_recent_patrol = cfd._recent_deterrence_patrol_fraction(
            prop_snap.get("tasks_active", []),
            prop_snap.get("tasks_done", []),
            float(prop_snap["t_s"]),
            float(args.recent_deterrence_window_s),
            float(args.recent_deterrence_radius_m),
        )

        pred_local_drop, pred_local_excess = cfd._local_drop_metrics(prev_pred, pred_snap, float(args.local_patch_radius_m))
        prop_local_drop, prop_local_excess = cfd._local_drop_metrics(prev_prop, prop_snap, float(args.local_patch_radius_m))

        per_time_rows.append(
            {
                "t_s": float(pred_snap["t_s"]),
                "lambda_l1_mean": lam_l1,
                "lambda_l2_mean": lam_l2,
                "lambda_max_abs_diff": lam_max,
                "suppressed_area_fraction": suppressed_frac,
                "hotspot_overlap_at_k": hotspot_overlap,
                "hotspot_mean_match_distance_m": hs_dist,
                "local_hotspot_filter_threshold_mean_prediction_only": pred_threshold,
                "local_hotspot_filter_threshold_mean_proposed": prop_threshold,
                "local_hotspots_raw_score_p90_prediction_only": pred_score_p90,
                "local_hotspots_raw_score_p90_proposed": prop_score_p90,
                "local_hotspots_raw_overlap": local_raw_overlap,
                "local_hotspots_raw_mean_match_distance_m": local_raw_dist,
                "local_hotspots_score_filtered_overlap": local_filtered_overlap,
                "local_hotspots_score_filtered_mean_match_distance_m": local_filtered_dist,
                "local_hotspots_spaced_overlap": local_spaced_overlap,
                "local_hotspots_spaced_mean_match_distance_m": local_spaced_dist,
                "raw_patrol_candidate_overlap": raw_overlap,
                "raw_patrol_candidate_mean_match_distance_m": raw_dist,
                "selected_patrol_overlap": selected_overlap,
                "selected_patrol_mean_match_distance_m": sel_dist,
                "patrol_overlap": patrol_overlap,
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
    return summary_df.iloc[0].to_dict()


def _plot_sweep(summary_df: pd.DataFrame, outdir: Path) -> List[Path]:
    out = []
    if summary_df.empty:
        return out
    df = summary_df.copy()
    x = np.arange(len(df))

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    axes[0].bar(x, df["final_exposure_improve_pct_mean"], yerr=df["final_exposure_improve_pct_ci95"], color="#2a9d8f")
    axes[0].axhline(0.0, color="black", linewidth=1.0)
    axes[0].set_ylabel("Exposure improve (%)")
    axes[0].grid(True, axis="y", alpha=0.3)
    axes[1].bar(x, df["final_response_improve_pct_mean"], yerr=df["final_response_improve_pct_ci95"], color="#e76f51")
    axes[1].axhline(0.0, color="black", linewidth=1.0)
    axes[1].set_ylabel("Response improve (%)")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(df["config_id"], rotation=45, ha="right")
    axes[1].grid(True, axis="y", alpha=0.3)
    p1 = outdir / "filter_sweep_end_metrics.png"
    fig.tight_layout()
    fig.savefig(p1, dpi=180)
    plt.close(fig)
    out.append(p1)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.scatter(
        df["final_response_improve_pct_mean"],
        df["final_exposure_improve_pct_mean"],
        s=100,
        c=df["patrol_overlap_mean_mean"],
        cmap="viridis_r",
    )
    for _, row in df.iterrows():
        ax.annotate(str(row["config_id"]), (row["final_response_improve_pct_mean"], row["final_exposure_improve_pct_mean"]), fontsize=8)
    ax.axhline(0.0, color="black", linewidth=1.0)
    ax.axvline(0.0, color="black", linewidth=1.0)
    ax.set_xlabel("Response improve mean (%)")
    ax.set_ylabel("Exposure improve mean (%)")
    ax.grid(True, alpha=0.3)
    p2 = outdir / "filter_sweep_tradeoff_scatter.png"
    fig.tight_layout()
    fig.savefig(p2, dpi=180)
    plt.close(fig)
    out.append(p2)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Narrow sweep for lab-only patrol-filter tuning")
    add_config_argument(parser)
    parser.add_argument("--seeds", type=str, default="2000,2001,2002,2003,2004")
    parser.add_argument("--t-end", type=float, default=3600.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--sample-period-s", type=float, default=300.0)
    parser.add_argument("--hotspot-top-k", type=int, default=5)
    parser.add_argument("--hotspot-match-radius-m", type=float, default=25.0)
    parser.add_argument("--patrol-match-radius-m", type=float, default=25.0)
    parser.add_argument("--recent-deterrence-window-s", type=float, default=300.0)
    parser.add_argument("--recent-deterrence-radius-m", type=float, default=25.0)
    parser.add_argument("--local-patch-radius-m", type=float, default=20.0)
    parser.add_argument("--assignment-method", type=str, default="hungarian")
    parser.add_argument("--assignment-distance-cost-per-m", type=float, default=0.006)
    parser.add_argument("--assignment-switch-penalty", type=float, default=1.0)
    parser.add_argument("--assigner-w-task-value", type=float, default=0.0)
    parser.add_argument("--patrol-min-hotspot-score", type=float, default=1e-4)
    parser.add_argument("--patrol-filter-modes", type=str, default="percentile,top_k")
    parser.add_argument("--patrol-percentiles", type=str, default="92,95,97")
    parser.add_argument("--patrol-keep-top-k-values", type=str, default="4,5,6")
    parser.add_argument("--task-replan-period-values", type=str, default="60,75,90")
    parser.add_argument("--patrol-hotspot-score-percentile", type=float, default=90.0)
    parser.add_argument("--patrol-hotspot-keep-top-k", type=int, default=6)
    parser.add_argument("--model-deterring-window-s", type=float, default=90.0)
    parser.add_argument("--model-deterring-gate-policies", type=str, default="heuristic")
    parser.add_argument("--model-deterring-sprt-alpha", type=float, default=0.05)
    parser.add_argument("--model-deterring-sprt-alpha-values", type=str, default="")
    parser.add_argument("--model-deterring-sprt-beta", type=float, default=0.20)
    parser.add_argument("--model-deterring-chance-threshold", type=float, default=0.20)
    parser.add_argument("--model-deterring-chance-threshold-values", type=str, default="")
    parser.add_argument("--model-deterring-min-deltaj-per-cost", type=float, default=0.15)
    parser.add_argument("--model-deterring-min-deltaj-per-cost-values", type=str, default="")
    parser.add_argument("--truth-beta-scale", type=float, default=1.0)
    parser.add_argument("--truth-omega-scale", type=float, default=1.0)
    parser.add_argument("--truth-sigma-scale", type=float, default=1.0)
    parser.add_argument("--model-beta-scale", type=float, default=1.0)
    parser.add_argument("--outdir", type=str, default="results/field_divergence_filter_sweep")
    args, config_meta = parse_args_with_config(parser, aliases=FIELD_DIVERGENCE_FILTER_SWEEP_CONFIG_ALIASES)

    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    seeds = _parse_int_list(args.seeds)
    filter_modes = _parse_str_list(args.patrol_filter_modes)
    gate_policies = _parse_str_list(args.model_deterring_gate_policies)
    percentiles = _parse_float_list(args.patrol_percentiles)
    keep_top_k_values = _parse_int_list(args.patrol_keep_top_k_values)
    replan_values = _parse_float_list(args.task_replan_period_values)
    sprt_alpha_values = (
        _parse_float_list(args.model_deterring_sprt_alpha_values)
        if str(args.model_deterring_sprt_alpha_values).strip()
        else [float(args.model_deterring_sprt_alpha)]
    )
    chance_threshold_values = (
        _parse_float_list(args.model_deterring_chance_threshold_values)
        if str(args.model_deterring_chance_threshold_values).strip()
        else [float(args.model_deterring_chance_threshold)]
    )
    min_deltaj_values = (
        _parse_float_list(args.model_deterring_min_deltaj_per_cost_values)
        if str(args.model_deterring_min_deltaj_per_cost_values).strip()
        else [float(args.model_deterring_min_deltaj_per_cost)]
    )

    configs = []
    for gate_policy in gate_policies:
        gate = str(gate_policy).strip().lower()
        if gate == "sprt_capacity":
            gate_param_grid = [
                {
                    "sprt_alpha": float(alpha),
                    "chance_threshold": float(chance),
                    "min_deltaj_per_cost": float(min_dj),
                }
                for alpha in sprt_alpha_values
                for chance in chance_threshold_values
                for min_dj in min_deltaj_values
            ]
        else:
            gate_param_grid = [
                {
                    "sprt_alpha": float(args.model_deterring_sprt_alpha),
                    "chance_threshold": float(args.model_deterring_chance_threshold),
                    "min_deltaj_per_cost": float(args.model_deterring_min_deltaj_per_cost),
                }
            ]
        for filter_mode in filter_modes:
            mode = str(filter_mode).strip().lower()
            if mode == "percentile":
                for pct in percentiles:
                    for replan in replan_values:
                        for gate_params in gate_param_grid:
                            configs.append(
                                {
                                    "gate_policy": gate,
                                    "filter_mode": mode,
                                    "percentile": float(pct),
                                    "keep_top_k": None,
                                    "replan": float(replan),
                                    **gate_params,
                                }
                            )
            elif mode == "top_k":
                for keep_top_k in keep_top_k_values:
                    for replan in replan_values:
                        for gate_params in gate_param_grid:
                            configs.append(
                                {
                                    "gate_policy": gate,
                                    "filter_mode": mode,
                                    "percentile": None,
                                    "keep_top_k": int(keep_top_k),
                                    "replan": float(replan),
                                    **gate_params,
                                }
                            )

    per_seed_rows = []
    for cfg in configs:
        cfg_id = _config_id(
            cfg["filter_mode"],
            cfg["percentile"],
            cfg["keep_top_k"],
            cfg["replan"],
            cfg["gate_policy"],
            cfg["sprt_alpha"],
            cfg["chance_threshold"],
            cfg["min_deltaj_per_cost"],
        )
        sim_kwargs = _build_sim_kwargs(
            args,
            cfg["filter_mode"],
            cfg["percentile"],
            cfg["keep_top_k"],
            cfg["replan"],
            cfg["gate_policy"],
            cfg["sprt_alpha"],
            cfg["chance_threshold"],
            cfg["min_deltaj_per_cost"],
        )
        for seed in seeds:
            row = _run_one_seed(int(seed), sim_kwargs, args)
            row["seed"] = int(seed)
            row["config_id"] = cfg_id
            row["model_deterring_gate_policy"] = str(cfg["gate_policy"])
            row["model_deterring_sprt_alpha"] = float(cfg["sprt_alpha"])
            row["model_deterring_chance_threshold"] = float(cfg["chance_threshold"])
            row["model_deterring_min_deltaj_per_cost"] = float(cfg["min_deltaj_per_cost"])
            row["patrol_filter_mode"] = str(cfg["filter_mode"])
            row["patrol_percentile"] = float(cfg["percentile"]) if cfg["percentile"] is not None else float("nan")
            row["patrol_keep_top_k"] = int(cfg["keep_top_k"]) if cfg["keep_top_k"] is not None else -1
            row["task_replan_period_s"] = float(cfg["replan"])
            per_seed_rows.append(row)

    per_seed_df = pd.DataFrame(per_seed_rows)

    summary_rows = []
    for cfg_id, group in per_seed_df.groupby("config_id", sort=False):
        row = {
            "config_id": str(cfg_id),
            "model_deterring_gate_policy": str(group["model_deterring_gate_policy"].iloc[0]),
            "model_deterring_sprt_alpha": float(group["model_deterring_sprt_alpha"].iloc[0]),
            "model_deterring_chance_threshold": float(group["model_deterring_chance_threshold"].iloc[0]),
            "model_deterring_min_deltaj_per_cost": float(group["model_deterring_min_deltaj_per_cost"].iloc[0]),
            "patrol_filter_mode": str(group["patrol_filter_mode"].iloc[0]),
            "patrol_percentile": float(group["patrol_percentile"].iloc[0]),
            "patrol_keep_top_k": int(group["patrol_keep_top_k"].iloc[0]),
            "task_replan_period_s": float(group["task_replan_period_s"].iloc[0]),
            "n_seeds": int(len(group)),
        }
        for metric in (
            "final_exposure_improve_pct",
            "final_response_improve_pct",
            "raw_patrol_candidate_overlap_mean",
            "selected_patrol_overlap_mean",
            "patrol_overlap_mean",
            "recent_deterrence_patrol_fraction_prediction_only_mean",
            "recent_deterrence_patrol_fraction_proposed_mean",
        ):
            mean, std, ci95 = _aggregate(group[metric])
            row[f"{metric}_mean"] = mean
            row[f"{metric}_std"] = std
            row[f"{metric}_ci95"] = ci95
        row["exposure_lb_ci95"] = float(row["final_exposure_improve_pct_mean"] - row["final_exposure_improve_pct_ci95"]) if np.isfinite(row["final_exposure_improve_pct_mean"]) else float("nan")
        row["response_lb_ci95"] = float(row["final_response_improve_pct_mean"] - row["final_response_improve_pct_ci95"]) if np.isfinite(row["final_response_improve_pct_mean"]) else float("nan")
        summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows)
    ranking_df = summary_df.sort_values(
        by=[
            "exposure_lb_ci95",
            "final_exposure_improve_pct_mean",
            "final_response_improve_pct_mean",
            "patrol_overlap_mean_mean",
        ],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)

    manifest = {
        "seeds": seeds,
        "configs": configs,
        "args": vars(args),
        "config": config_meta,
    }

    per_seed_path = outdir / "field_divergence_filter_sweep_per_seed.csv"
    summary_path = outdir / "field_divergence_filter_sweep_summary.csv"
    ranking_path = outdir / "field_divergence_filter_sweep_ranking.csv"
    manifest_path = outdir / "field_divergence_filter_sweep_manifest.json"
    per_seed_df.to_csv(per_seed_path, index=False)
    summary_df.to_csv(summary_path, index=False)
    ranking_df.to_csv(ranking_path, index=False)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    plot_paths = _plot_sweep(ranking_df, outdir)

    readme = outdir / "FIELD_DIVERGENCE_FILTER_SWEEP_README.md"
    readme.write_text(
        "\n".join(
            [
                "# Field Divergence Filter Sweep",
                "",
                f"- Per-seed CSV: `{per_seed_path.name}`",
                f"- Summary CSV: `{summary_path.name}`",
                f"- Ranking CSV: `{ranking_path.name}`",
                f"- Manifest: `{manifest_path.name}`",
                "",
                "Ranking rule:",
                "1. Highest exposure lower-bound (`mean - ci95`)",
                "2. Highest exposure mean",
                "3. Highest response mean",
                "4. Lowest active patrol overlap mean",
            ]
        ),
        encoding="utf-8",
    )

    print(f"[done] wrote outputs to: {outdir}")
    print(f"- {per_seed_path}")
    print(f"- {summary_path}")
    print(f"- {ranking_path}")
    print(f"- {manifest_path}")
    for p in plot_paths:
        print(f"- {p}")
    print(f"- {readme}")


if __name__ == "__main__":
    main()
