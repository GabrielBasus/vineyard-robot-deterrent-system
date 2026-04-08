from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import DeterrentSystem as ds
from diagnostics.diagnostic_feedback_patrol_divergence import (
    _greedy_match,
    _patrol_points,
    _safe_mean,
    _support_metrics,
    _xy_points,
)
from diagnostics.diagnostic_feedback_reactive_pipeline import (
    _add_share_columns as _add_reactive_share_columns,
    _build_cluster_tables,
    _bin_start,
    _point_to_zone,
    _summarize_mode as _summarize_reactive_modes,
)
from diagnostics.diagnostic_feedback_workload_allocation import (
    _add_share_columns as _add_workload_share_columns,
    _allocation_rows,
    _summarize_mode as _summarize_workload_modes,
)
from diagnostics.diagnostic_field_truth_compare import simulate_one_run as simulate_field_truth_run
from diagnostics.diagnostic_sestpp_subsystem import SubsystemConfig


def _safe_std(vals) -> float:
    arr = np.asarray([float(v) for v in vals if np.isfinite(float(v))], dtype=float)
    return float(np.std(arr)) if arr.size else float("nan")


def _pct_improve(baseline: float, candidate: float) -> float:
    if not np.isfinite(float(baseline)) or abs(float(baseline)) <= 1e-12:
        return float("nan")
    return 100.0 * (float(baseline) - float(candidate)) / abs(float(baseline))


def _safe_corr(x_vals, y_vals) -> tuple[float, int]:
    x = np.asarray(x_vals, dtype=float)
    y = np.asarray(y_vals, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x = x[mask]
    y = y[mask]
    if x.size < 3:
        return float("nan"), int(x.size)
    if float(np.std(x)) <= 1e-12 or float(np.std(y)) <= 1e-12:
        return float("nan"), int(x.size)
    return float(np.corrcoef(x, y)[0, 1]), int(x.size)


def _safe_spearman(x_vals, y_vals) -> tuple[float, int]:
    x = np.asarray(x_vals, dtype=float)
    y = np.asarray(y_vals, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x = x[mask]
    y = y[mask]
    if x.size < 3:
        return float("nan"), int(x.size)
    xr = pd.Series(x).rank(method="average").to_numpy(dtype=float)
    yr = pd.Series(y).rank(method="average").to_numpy(dtype=float)
    if float(np.std(xr)) <= 1e-12 or float(np.std(yr)) <= 1e-12:
        return float("nan"), int(x.size)
    return float(np.corrcoef(xr, yr)[0, 1]), int(x.size)


def _build_field_cfg(args: argparse.Namespace) -> SubsystemConfig:
    return SubsystemConfig(
        dt=float(args.dt),
        T_end=float(args.T_end),
        warmup_s=float(args.warmup_s),
        eval_period_s=float(args.eval_period_s),
        forecast_horizon_s=float(args.forecast_horizon_s),
        runs=int(args.runs),
        seed_start=int(args.seed_start),
        model_alpha_inhib=float(args.alpha_inhib),
        model_omega_inhib=float(args.omega_inhib),
        model_mu_base=float(args.mu_base),
        model_bg_ema=float(args.bg_ema),
        intervention_shuffle=str(args.intervention_shuffle),
    )


def _run_production_case(
    label: str,
    sim_mode: str,
    run_params: dict,
    overrides: dict,
    sample_every_s: float,
    hotspot_top_k: int,
) -> dict:
    frames = list(
        ds.run_simulation_frames_persistent(
            simulation_mode=sim_mode,
            report_metrics_end=False,
            emit_planning_diagnostics=True,
            planning_hotspot_top_k=int(hotspot_top_k),
            **run_params,
            **overrides,
        )
    )
    first = frames[0] if frames else {}
    last = frames[-1] if frames else {}
    sampled = {}
    next_sample_t = -1e18
    for snap in frames:
        t_s = float(snap.get("t", 0.0))
        if t_s < next_sample_t:
            continue
        next_sample_t = t_s + float(sample_every_s)
        planning = snap.get("planning_diagnostics") or {}
        model_diag = snap.get("model_diag", {}) or {}
        inhib_vals = [float(v.get("inhib_sum", float("nan"))) for v in model_diag.values()]
        sampled[int(round(t_s))] = {
            "t_s": t_s,
            "poses": dict(snap.get("poses", {})),
            "robot_states": dict(snap.get("robot_states", {})),
            "global_hotspots": list(planning.get("global_hotspots", [])),
            "patrol_candidates": list(planning.get("patrol_candidates", [])),
            "accepted_patrol_tasks": list(planning.get("accepted_patrol_tasks", [])),
            "tasks_active": list(snap.get("tasks_active", [])),
            "truth_pts": list(snap.get("truth_pts", [])),
            "det_pts": list(snap.get("det_pts", [])),
            "metrics": dict(snap.get("metrics", {})),
            "inhib_sum_total": float(np.nansum(inhib_vals)) if inhib_vals else float("nan"),
        }
    return {
        "label": label,
        "frames": frames,
        "cells": list(first.get("cells", [])),
        "sampled": sampled,
        "final_metrics": dict(last.get("metrics", {})),
    }


def _build_divergence_rows(pred_run: dict, prop_run: dict, match_radius_m: float, support_radius_m: float) -> pd.DataFrame:
    ts = sorted(set(pred_run["sampled"].keys()) & set(prop_run["sampled"].keys()))
    rows = []
    for t_key in ts:
        pred_snap = pred_run["sampled"][t_key]
        prop_snap = prop_run["sampled"][t_key]

        pred_hotspots = _xy_points(pred_snap["global_hotspots"])
        prop_hotspots = _xy_points(prop_snap["global_hotspots"])
        pred_patrol_candidates = _xy_points(pred_snap["patrol_candidates"])
        prop_patrol_candidates = _xy_points(prop_snap["patrol_candidates"])
        pred_accepted_patrol = _xy_points(pred_snap["accepted_patrol_tasks"])
        prop_accepted_patrol = _xy_points(prop_snap["accepted_patrol_tasks"])
        pred_active_patrol = _patrol_points(pred_snap["tasks_active"])
        prop_active_patrol = _patrol_points(prop_snap["tasks_active"])

        pred_truth = [(float(x), float(y)) for x, y in pred_snap["truth_pts"]]
        prop_truth = [(float(x), float(y)) for x, y in prop_snap["truth_pts"]]
        pred_det = [(float(x), float(y)) for x, y in pred_snap["det_pts"]]
        prop_det = [(float(x), float(y)) for x, y in prop_snap["det_pts"]]

        hs_matches, _ = _greedy_match(pred_hotspots, prop_hotspots, match_radius_m)
        cand_matches, _ = _greedy_match(pred_patrol_candidates, prop_patrol_candidates, match_radius_m)
        acc_matches, _ = _greedy_match(pred_accepted_patrol, prop_accepted_patrol, match_radius_m)
        active_matches, _ = _greedy_match(pred_active_patrol, prop_active_patrol, match_radius_m)

        pred_hotspot_truth_hit, pred_hotspot_truth_count = _support_metrics(pred_hotspots, pred_truth, support_radius_m)
        prop_hotspot_truth_hit, prop_hotspot_truth_count = _support_metrics(prop_hotspots, prop_truth, support_radius_m)
        pred_hotspot_det_hit, pred_hotspot_det_count = _support_metrics(pred_hotspots, pred_det, support_radius_m)
        prop_hotspot_det_hit, prop_hotspot_det_count = _support_metrics(prop_hotspots, prop_det, support_radius_m)
        pred_active_truth_hit, pred_active_truth_count = _support_metrics(pred_active_patrol, pred_truth, support_radius_m)
        prop_active_truth_hit, prop_active_truth_count = _support_metrics(prop_active_patrol, prop_truth, support_radius_m)

        rows.append(
            {
                "t_s": float(pred_snap["t_s"]),
                "hotspot_overlap": float(hs_matches) / float(max(max(len(pred_hotspots), len(prop_hotspots)), 1)),
                "patrol_candidate_overlap": float(cand_matches) / float(max(max(len(pred_patrol_candidates), len(prop_patrol_candidates)), 1)),
                "accepted_patrol_overlap": float(acc_matches) / float(max(max(len(pred_accepted_patrol), len(prop_accepted_patrol)), 1)),
                "active_patrol_overlap": float(active_matches) / float(max(max(len(pred_active_patrol), len(prop_active_patrol)), 1)),
                "prediction_hotspot_truth_hit_rate": pred_hotspot_truth_hit,
                "proposed_hotspot_truth_hit_rate": prop_hotspot_truth_hit,
                "prediction_hotspot_truth_count_mean": pred_hotspot_truth_count,
                "proposed_hotspot_truth_count_mean": prop_hotspot_truth_count,
                "prediction_hotspot_detection_hit_rate": pred_hotspot_det_hit,
                "proposed_hotspot_detection_hit_rate": prop_hotspot_det_hit,
                "prediction_hotspot_detection_count_mean": pred_hotspot_det_count,
                "proposed_hotspot_detection_count_mean": prop_hotspot_det_count,
                "prediction_active_patrol_truth_hit_rate": pred_active_truth_hit,
                "proposed_active_patrol_truth_hit_rate": prop_active_truth_hit,
                "prediction_active_patrol_truth_count_mean": pred_active_truth_count,
                "proposed_active_patrol_truth_count_mean": prop_active_truth_count,
                "prediction_inhib_sum_total": float(pred_snap["inhib_sum_total"]),
                "proposed_inhib_sum_total": float(prop_snap["inhib_sum_total"]),
            }
        )
    return pd.DataFrame(rows)


def _summarize_divergence(div_df: pd.DataFrame) -> dict:
    if div_df.empty:
        return {}
    return {
        "hotspot_overlap_mean": _safe_mean(div_df["hotspot_overlap"].tolist()),
        "patrol_candidate_overlap_mean": _safe_mean(div_df["patrol_candidate_overlap"].tolist()),
        "accepted_patrol_overlap_mean": _safe_mean(div_df["accepted_patrol_overlap"].tolist()),
        "active_patrol_overlap_mean": _safe_mean(div_df["active_patrol_overlap"].tolist()),
        "hotspot_truth_hit_delta": _safe_mean(
            (div_df["proposed_hotspot_truth_hit_rate"] - div_df["prediction_hotspot_truth_hit_rate"]).tolist()
        ),
        "hotspot_detection_hit_delta": _safe_mean(
            (div_df["proposed_hotspot_detection_hit_rate"] - div_df["prediction_hotspot_detection_hit_rate"]).tolist()
        ),
        "hotspot_truth_count_delta": _safe_mean(
            (div_df["proposed_hotspot_truth_count_mean"] - div_df["prediction_hotspot_truth_count_mean"]).tolist()
        ),
        "hotspot_detection_count_delta": _safe_mean(
            (div_df["proposed_hotspot_detection_count_mean"] - div_df["prediction_hotspot_detection_count_mean"]).tolist()
        ),
        "active_patrol_truth_hit_delta": _safe_mean(
            (div_df["proposed_active_patrol_truth_hit_rate"] - div_df["prediction_active_patrol_truth_hit_rate"]).tolist()
        ),
        "active_patrol_truth_count_delta": _safe_mean(
            (div_df["proposed_active_patrol_truth_count_mean"] - div_df["prediction_active_patrol_truth_count_mean"]).tolist()
        ),
        "inhib_sum_total_delta": _safe_mean(
            (div_df["proposed_inhib_sum_total"] - div_df["prediction_inhib_sum_total"]).tolist()
        ),
    }


def _build_workload_summary(pred_run: dict, prop_run: dict) -> dict:
    cells = pred_run["cells"] or prop_run["cells"]
    rows = _allocation_rows("prediction_only", pred_run["sampled"], cells)
    rows.extend(_allocation_rows("proposed_feedback_only", prop_run["sampled"], cells))
    work_df = _add_workload_share_columns(pd.DataFrame(rows))
    mode_summary = _summarize_workload_modes(work_df)
    pred_mode = mode_summary["prediction_only"]
    prop_mode = mode_summary["proposed_feedback_only"]
    return {
        "robot_truth_l1_delta": float(prop_mode["robot_truth_l1_mean"] - pred_mode["robot_truth_l1_mean"]),
        "patrol_truth_l1_delta": float(prop_mode["patrol_truth_l1_mean"] - pred_mode["patrol_truth_l1_mean"]),
        "deterring_detection_l1_delta": float(
            prop_mode["deterring_detection_l1_mean"] - pred_mode["deterring_detection_l1_mean"]
        ),
        "fleet_moving_fraction_delta": float(
            prop_mode["fleet_moving_fraction_mean"] - pred_mode["fleet_moving_fraction_mean"]
        ),
        "fleet_idle_fraction_delta": float(
            prop_mode["fleet_idle_fraction_mean"] - pred_mode["fleet_idle_fraction_mean"]
        ),
        "fleet_holding_fraction_delta": float(
            prop_mode["fleet_holding_fraction_mean"] - pred_mode["fleet_holding_fraction_mean"]
        ),
    }


def _reactive_tables_from_frames(label: str, frames: list[dict], cells, bin_s: float) -> dict:
    zone_count = int(len(cells))
    zone_bin = {}
    global_bin = {}
    assign_rows = []
    done_rows = []
    seen_assigned_ids = set()
    seen_done_ids = set()
    last = None

    for snap in frames:
        last = snap
        t_s = float(snap.get("t", 0.0))
        b = _bin_start(t_s, bin_s)
        fb = snap.get("feedback_structured", {}) or {}

        g = global_bin.setdefault(
            b,
            {
                "mode": label,
                "t_bin_s": b,
                "frame_count": 0,
                "boundary_messages_sent": 0,
                "intervention_messages_sent": 0,
                "detection_count": 0,
                "truth_count": 0,
                "new_direct_det_assignment_count": 0,
                "new_direct_det_completion_count": 0,
                "active_direct_det_count_sum": 0,
            },
        )
        g["frame_count"] += 1
        g["boundary_messages_sent"] += int(fb.get("boundary_messages_sent_this_step", 0) or 0)
        g["intervention_messages_sent"] += int(fb.get("intervention_messages_sent_this_step", 0) or 0)

        for zi in range(zone_count):
            zone_bin.setdefault(
                (b, zi),
                {
                    "mode": label,
                    "t_bin_s": b,
                    "zone_idx": int(zi),
                    "frame_count": 0,
                    "detection_count": 0,
                    "truth_count": 0,
                    "new_direct_det_assignment_count": 0,
                    "new_direct_det_completion_count": 0,
                    "active_direct_det_count_sum": 0,
                },
            )["frame_count"] += 1

        for x, y in snap.get("det_pts", []):
            zi = _point_to_zone(float(x), float(y), cells)
            zone_bin[(b, zi)]["detection_count"] += 1
            g["detection_count"] += 1
        for x, y in snap.get("truth_pts", []):
            zi = _point_to_zone(float(x), float(y), cells)
            zone_bin[(b, zi)]["truth_count"] += 1
            g["truth_count"] += 1

        active_direct = []
        for tr in snap.get("tasks_active", []):
            if str(tr.get("state", "")).strip().lower() != "active":
                continue
            if str(tr.get("type", "")).strip().lower() != "deterring":
                continue
            if str(tr.get("origin", "")).strip().lower() != "detection":
                continue
            active_direct.append(tr)
            tid = tr.get("id")
            if tid in seen_assigned_ids:
                continue
            seen_assigned_ids.add(tid)
            t_assigned = float(tr.get("t_assigned", t_s))
            detect_t = float(tr.get("time", float("nan")))
            zi = _point_to_zone(float(tr.get("x", 0.0)), float(tr.get("y", 0.0)), cells)
            bb = _bin_start(t_assigned, bin_s)
            zone_bin.setdefault((bb, zi), {"mode": label, "t_bin_s": bb, "zone_idx": int(zi), "frame_count": 0, "detection_count": 0, "truth_count": 0, "new_direct_det_assignment_count": 0, "new_direct_det_completion_count": 0, "active_direct_det_count_sum": 0})["new_direct_det_assignment_count"] += 1
            global_bin.setdefault(bb, {"mode": label, "t_bin_s": bb, "frame_count": 0, "boundary_messages_sent": 0, "intervention_messages_sent": 0, "detection_count": 0, "truth_count": 0, "new_direct_det_assignment_count": 0, "new_direct_det_completion_count": 0, "active_direct_det_count_sum": 0})["new_direct_det_assignment_count"] += 1
            assign_rows.append(
                {
                    "mode": label,
                    "task_id": tid,
                    "zone_idx": int(zi),
                    "detect_t": detect_t,
                    "t_assigned": t_assigned,
                    "assign_lag_s": float(t_assigned - detect_t) if np.isfinite(detect_t) else float("nan"),
                    "x": float(tr.get("x", 0.0)),
                    "y": float(tr.get("y", 0.0)),
                    "assigned_primary": tr.get("assigned_primary"),
                }
            )

        for tr in active_direct:
            zi = _point_to_zone(float(tr.get("x", 0.0)), float(tr.get("y", 0.0)), cells)
            zone_bin[(b, zi)]["active_direct_det_count_sum"] += 1
            g["active_direct_det_count_sum"] += 1

        for tr in snap.get("tasks_done", []):
            if str(tr.get("state", "")).strip().lower() != "done":
                continue
            if str(tr.get("type", "")).strip().lower() != "deterring":
                continue
            if str(tr.get("origin", "")).strip().lower() != "detection":
                continue
            tid = tr.get("id")
            if tid in seen_done_ids:
                continue
            seen_done_ids.add(tid)
            t_done = float(tr.get("t_done", t_s))
            detect_t = float(tr.get("time", float("nan")))
            zi = _point_to_zone(float(tr.get("x", 0.0)), float(tr.get("y", 0.0)), cells)
            bb = _bin_start(t_done, bin_s)
            zone_bin.setdefault((bb, zi), {"mode": label, "t_bin_s": bb, "zone_idx": int(zi), "frame_count": 0, "detection_count": 0, "truth_count": 0, "new_direct_det_assignment_count": 0, "new_direct_det_completion_count": 0, "active_direct_det_count_sum": 0})["new_direct_det_completion_count"] += 1
            global_bin.setdefault(bb, {"mode": label, "t_bin_s": bb, "frame_count": 0, "boundary_messages_sent": 0, "intervention_messages_sent": 0, "detection_count": 0, "truth_count": 0, "new_direct_det_assignment_count": 0, "new_direct_det_completion_count": 0, "active_direct_det_count_sum": 0})["new_direct_det_completion_count"] += 1
            done_rows.append(
                {
                    "mode": label,
                    "task_id": tid,
                    "zone_idx": int(zi),
                    "detect_t": detect_t,
                    "t_done": t_done,
                    "completion_lag_s": float(t_done - detect_t) if np.isfinite(detect_t) else float("nan"),
                    "x": float(tr.get("x", 0.0)),
                    "y": float(tr.get("y", 0.0)),
                    "assigned_primary": tr.get("assigned_primary"),
                }
            )

    return {
        "zone_df": pd.DataFrame(list(zone_bin.values())),
        "global_df": pd.DataFrame(list(global_bin.values())).sort_values("t_bin_s").reset_index(drop=True),
        "assign_df": pd.DataFrame(assign_rows),
        "done_df": pd.DataFrame(done_rows),
        "final_metrics": dict((last or {}).get("metrics", {})),
    }


def _build_reactive_summary(pred_run: dict, prop_run: dict, bin_s: float) -> dict:
    cells = pred_run["cells"] or prop_run["cells"]
    pred = _reactive_tables_from_frames("prediction_only", pred_run["frames"], cells, bin_s)
    prop = _reactive_tables_from_frames("proposed_feedback_only", prop_run["frames"], cells, bin_s)
    zone_df = _add_reactive_share_columns(pd.concat([pred["zone_df"], prop["zone_df"]], ignore_index=True))
    global_df = pd.concat([pred["global_df"], prop["global_df"]], ignore_index=True).sort_values(["mode", "t_bin_s"])
    assign_df = pd.concat([pred["assign_df"], prop["assign_df"]], ignore_index=True)
    done_df = pd.concat([pred["done_df"], prop["done_df"]], ignore_index=True)
    mode_summary = _summarize_reactive_modes(zone_df, global_df, assign_df, done_df)
    cluster_df, cluster_summary = _build_cluster_tables(
        assign_df,
        done_df,
        spatial_quant_m=20.0,
        time_quant_s=max(float(bin_s), 1.0),
    )
    pred_mode = mode_summary["prediction_only"]
    prop_mode = mode_summary["proposed_feedback_only"]
    pred_cluster = cluster_summary.get("prediction_only", {})
    prop_cluster = cluster_summary.get("proposed_feedback_only", {})
    return {
        "boundary_messages_per_detection_delta": float(
            prop_mode["boundary_messages_per_detection"] - pred_mode["boundary_messages_per_detection"]
        ),
        "intervention_messages_per_detection_delta": float(
            prop_mode["intervention_messages_per_detection"] - pred_mode["intervention_messages_per_detection"]
        ),
        "assignment_detection_l1_delta": float(
            prop_mode["assignment_detection_l1_mean"] - pred_mode["assignment_detection_l1_mean"]
        ),
        "completion_detection_l1_delta": float(
            prop_mode["completion_detection_l1_mean"] - pred_mode["completion_detection_l1_mean"]
        ),
        "active_detection_l1_delta": float(
            prop_mode["active_detection_l1_mean"] - pred_mode["active_detection_l1_mean"]
        ),
        "assign_lag_delta_s": float(prop_mode["mean_assign_lag_s"] - pred_mode["mean_assign_lag_s"]),
        "completion_lag_delta_s": float(prop_mode["mean_completion_lag_s"] - pred_mode["mean_completion_lag_s"]),
        "p90_assign_lag_delta_s": float(prop_mode["p90_assign_lag_s"] - pred_mode["p90_assign_lag_s"]),
        "p90_completion_lag_delta_s": float(prop_mode["p90_completion_lag_s"] - pred_mode["p90_completion_lag_s"]),
        "direct_assignment_ratio_delta": float(
            prop_mode["assignment_detection_ratio"] - pred_mode["assignment_detection_ratio"]
        ),
        "direct_completion_ratio_delta": float(
            prop_mode["completion_detection_ratio"] - pred_mode["completion_detection_ratio"]
        ),
        "detection_fano_delta": float(prop_mode["detection_fano"] - pred_mode["detection_fano"]),
        "boundary_message_fano_delta": float(
            prop_mode["boundary_message_fano"] - pred_mode["boundary_message_fano"]
        ),
        "assignment_fano_delta": float(prop_mode["assignment_fano"] - pred_mode["assignment_fano"]),
        "completion_fano_delta": float(prop_mode["completion_fano"] - pred_mode["completion_fano"]),
        "active_direct_fano_delta": float(prop_mode["active_direct_fano"] - pred_mode["active_direct_fano"]),
        "detection_boundary_corr_delta": float(
            prop_mode["detection_boundary_corr"] - pred_mode["detection_boundary_corr"]
        ),
        "detection_assignment_corr_delta": float(
            prop_mode["detection_assignment_corr"] - pred_mode["detection_assignment_corr"]
        ),
        "detection_completion_corr_delta": float(
            prop_mode["detection_completion_corr"] - pred_mode["detection_completion_corr"]
        ),
        "reactive_clusters_total_delta": float(
            prop_cluster.get("reactive_clusters_total", 0.0) - pred_cluster.get("reactive_clusters_total", 0.0)
        ),
        "assignments_per_cluster_mean_delta": float(
            prop_cluster.get("assignments_per_cluster_mean", float("nan"))
            - pred_cluster.get("assignments_per_cluster_mean", float("nan"))
        ),
        "clusters_with_multi_assign_fraction_delta": float(
            prop_cluster.get("clusters_with_multi_assign_fraction", float("nan"))
            - pred_cluster.get("clusters_with_multi_assign_fraction", float("nan"))
        ),
        "redundant_assignment_fraction_delta": float(
            prop_cluster.get("redundant_assignment_fraction", float("nan"))
            - pred_cluster.get("redundant_assignment_fraction", float("nan"))
        ),
        "redundant_completion_fraction_delta": float(
            prop_cluster.get("redundant_completion_fraction", float("nan"))
            - pred_cluster.get("redundant_completion_fraction", float("nan"))
        ),
        "mean_cluster_completion_to_assignment_ratio_delta": float(
            prop_cluster.get("mean_cluster_completion_to_assignment_ratio", float("nan"))
            - pred_cluster.get("mean_cluster_completion_to_assignment_ratio", float("nan"))
        ),
    }


def _build_run_row(args: argparse.Namespace, field_cfg: SubsystemConfig, run_idx: int, seed: int) -> dict:
    field_res = simulate_field_truth_run(run_idx, seed, field_cfg)
    field_pair = dict(field_res["paired_metrics"])

    run_params = {
        "T_end": float(args.T_end),
        "dt": float(args.dt),
        "seed": int(seed),
        "W": 500.0,
        "H": 500.0,
        "NX": 80,
        "NY": 64,
        "Nrobots": 6,
        "uav_fraction": 0.0,
        "warmup_s": float(args.warmup_s),
        "task_replan_period_s": float(args.task_replan_period_s),
        "patrol_hotspot_filter_mode": str(args.patrol_hotspot_filter_mode),
        "patrol_hotspot_score_percentile": float(args.patrol_hotspot_score_percentile),
        "alpha_inhib": float(args.alpha_inhib),
        "omega_inhib": float(args.omega_inhib),
        "mu_base": float(args.mu_base),
        "bg_ema": float(args.bg_ema),
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
    }
    pred_run = _run_production_case(
        label="prediction_only",
        sim_mode="prediction_only",
        run_params=run_params,
        overrides={"enable_intervention_feedback": False, "enable_model_scored_deterring": False},
        sample_every_s=float(args.sample_every_s),
        hotspot_top_k=int(args.hotspot_top_k),
    )
    prop_run = _run_production_case(
        label="proposed_feedback_only",
        sim_mode="proposed",
        run_params=run_params,
        overrides={"enable_intervention_feedback": True, "enable_model_scored_deterring": False},
        sample_every_s=float(args.sample_every_s),
        hotspot_top_k=int(args.hotspot_top_k),
    )

    div_summary = _summarize_divergence(
        _build_divergence_rows(pred_run, prop_run, float(args.match_radius_m), float(args.support_radius_m))
    )
    workload_summary = _build_workload_summary(pred_run, prop_run)
    reactive_summary = _build_reactive_summary(pred_run, prop_run, float(args.bin_s))

    pred_metrics = pred_run["final_metrics"]
    prop_metrics = prop_run["final_metrics"]
    pred_completed = pred_metrics.get("completed_tasks_by_type", {}) or {}
    prop_completed = prop_metrics.get("completed_tasks_by_type", {}) or {}

    row = {
        "run_idx": int(run_idx),
        "seed": int(seed),
        "prediction_exposure": float(pred_metrics.get("value_weighted_exposure", float("nan"))),
        "proposed_exposure": float(prop_metrics.get("value_weighted_exposure", float("nan"))),
        "prediction_response_s": float(pred_metrics.get("mean_response_time_s", float("nan"))),
        "proposed_response_s": float(prop_metrics.get("mean_response_time_s", float("nan"))),
        "prediction_boundary_messages": float(pred_metrics.get("boundary_message_count", float("nan"))),
        "proposed_boundary_messages": float(prop_metrics.get("boundary_message_count", float("nan"))),
        "exposure_improve_pct": _pct_improve(
            float(pred_metrics.get("value_weighted_exposure", float("nan"))),
            float(prop_metrics.get("value_weighted_exposure", float("nan"))),
        ),
        "response_improve_pct": _pct_improve(
            float(pred_metrics.get("mean_response_time_s", float("nan"))),
            float(prop_metrics.get("mean_response_time_s", float("nan"))),
        ),
        "comm_increase_pct": 100.0
        * (
            float(prop_metrics.get("boundary_message_count", float("nan")))
            - float(pred_metrics.get("boundary_message_count", float("nan")))
        )
        / max(float(pred_metrics.get("boundary_message_count", 0.0)), 1.0),
        "direct_det_completion_delta": float(
            prop_metrics.get("deterring_actions_completed_direct_detection", 0.0)
        ) - float(pred_metrics.get("deterring_actions_completed_direct_detection", 0.0)),
        "patrol_completion_delta": float(prop_completed.get("patrolling", 0.0)) - float(pred_completed.get("patrolling", 0.0)),
        "model_det_completion_delta": float(
            prop_metrics.get("deterring_actions_completed_model_scored", 0.0)
        ) - float(pred_metrics.get("deterring_actions_completed_model_scored", 0.0)),
        "truth_suppression_rate_delta": float(
            prop_metrics.get("truth_suppression_rate", float("nan"))
        ) - float(pred_metrics.get("truth_suppression_rate", float("nan"))),
    }
    row.update(field_pair)
    row.update(div_summary)
    row.update(workload_summary)
    row.update(reactive_summary)
    return row


def _correlation_table(per_run_df: pd.DataFrame, outcome_col: str, exclude_cols: set[str]) -> pd.DataFrame:
    rows = []
    for col in per_run_df.columns:
        if col in exclude_cols:
            continue
        if not pd.api.types.is_numeric_dtype(per_run_df[col]):
            continue
        pearson_r, n_p = _safe_corr(per_run_df[col].to_numpy(dtype=float), per_run_df[outcome_col].to_numpy(dtype=float))
        spearman_r, n_s = _safe_spearman(per_run_df[col].to_numpy(dtype=float), per_run_df[outcome_col].to_numpy(dtype=float))
        rows.append(
            {
                "metric": col,
                "pearson_r": pearson_r,
                "spearman_r": spearman_r,
                "has_finite_correlation": bool(np.isfinite(pearson_r) or np.isfinite(spearman_r)),
                "abs_score": float(
                    max(abs(pearson_r) if np.isfinite(pearson_r) else 0.0, abs(spearman_r) if np.isfinite(spearman_r) else 0.0)
                ),
                "valid_n": int(max(n_p, n_s)),
                "metric_mean": _safe_mean(per_run_df[col].tolist()),
                "metric_std": _safe_std(per_run_df[col].tolist()),
            }
        )
    return pd.DataFrame(rows).sort_values(["abs_score", "metric"], ascending=[False, True]).reset_index(drop=True)


def _plot_failure_slicing(per_run_df: pd.DataFrame, corr_exposure_df: pd.DataFrame, corr_response_df: pd.DataFrame, out_png: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    plots = [
        ("field_brier_improvement_pct", "exposure_improve_pct", "Field Brier vs Exposure"),
        (
            str((corr_exposure_df["metric"].iloc[0] if not corr_exposure_df.empty else "field_brier_improvement_pct")),
            "exposure_improve_pct",
            "Top Exposure Correlate",
        ),
        (
            str((corr_response_df["metric"].iloc[0] if not corr_response_df.empty else "field_brier_improvement_pct")),
            "response_improve_pct",
            "Top Response Correlate",
        ),
    ]
    for ax, (xcol, ycol, title) in zip(axes, plots):
        if xcol in per_run_df.columns and ycol in per_run_df.columns:
            ax.scatter(per_run_df[xcol], per_run_df[ycol], alpha=0.85)
            for _, row in per_run_df.iterrows():
                ax.annotate(str(int(row["seed"])), (row[xcol], row[ycol]), fontsize=7, alpha=0.8)
            ax.set_xlabel(xcol)
            ax.set_ylabel(ycol)
        ax.set_title(title)
        ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Slice feedback-on failures across seeds by joining closed-loop outcomes with field, divergence, workload, and reactive diagnostics."
    )
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--seed-start", type=int, default=2026)
    parser.add_argument("--T-end", type=float, default=3 * 3600.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--warmup-s", type=float, default=1800.0)
    parser.add_argument("--eval-period-s", type=float, default=30.0)
    parser.add_argument("--forecast-horizon-s", type=float, default=300.0)
    parser.add_argument("--sample-every-s", type=float, default=30.0)
    parser.add_argument("--bin-s", type=float, default=30.0)
    parser.add_argument("--task-replan-period-s", type=float, default=60.0)
    parser.add_argument("--hotspot-top-k", type=int, default=5)
    parser.add_argument("--match-radius-m", type=float, default=25.0)
    parser.add_argument("--support-radius-m", type=float, default=25.0)
    parser.add_argument("--patrol-hotspot-filter-mode", type=str, default="percentile")
    parser.add_argument("--patrol-hotspot-score-percentile", type=float, default=97.0)
    parser.add_argument("--alpha-inhib", type=float, default=0.45)
    parser.add_argument("--omega-inhib", type=float, default=600.0)
    parser.add_argument("--mu-base", type=float, default=5.0e-5)
    parser.add_argument("--bg-ema", type=float, default=1.0e-6)
    parser.add_argument("--intervention-shuffle", type=str, default="none")
    parser.add_argument("--outdir", type=str, default="results/diagnostic_feedback_failure_slicing")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    field_cfg = _build_field_cfg(args)
    run_rows = []
    for run_idx in range(int(args.runs)):
        seed = int(args.seed_start) + run_idx
        row = _build_run_row(args, field_cfg, run_idx, seed)
        run_rows.append(row)
        print(
            f"[run {run_idx + 1}/{int(args.runs)}] seed={seed} "
            f"exp_improve={row.get('exposure_improve_pct', float('nan')):.3f}% "
            f"resp_improve={row.get('response_improve_pct', float('nan')):.3f}% "
            f"field_brier_improve={row.get('brier_improvement_pct', float('nan')):.3f}%"
        )

    per_run_df = pd.DataFrame(run_rows).sort_values("seed").reset_index(drop=True)
    per_run_df.to_csv(outdir / "feedback_failure_slicing_per_run.csv", index=False)

    exclude_cols = {
        "run_idx",
        "seed",
        "prediction_exposure",
        "proposed_exposure",
        "prediction_response_s",
        "proposed_response_s",
        "prediction_boundary_messages",
        "proposed_boundary_messages",
        "exposure_improve_pct",
        "response_improve_pct",
        "comm_increase_pct",
    }
    corr_exposure_df = _correlation_table(per_run_df, "exposure_improve_pct", exclude_cols)
    corr_response_df = _correlation_table(per_run_df, "response_improve_pct", exclude_cols)
    corr_exposure_df.to_csv(outdir / "feedback_failure_slicing_corr_exposure.csv", index=False)
    corr_response_df.to_csv(outdir / "feedback_failure_slicing_corr_response.csv", index=False)

    top_exp_df = corr_exposure_df[corr_exposure_df["has_finite_correlation"]].head(min(5, len(corr_exposure_df)))
    top_resp_df = corr_response_df[corr_response_df["has_finite_correlation"]].head(min(5, len(corr_response_df)))
    top_exp = top_exp_df.to_dict(orient="records")
    top_resp = top_resp_df.to_dict(orient="records")
    summary = {
        "parameters": {
            "runs": int(args.runs),
            "seed_start": int(args.seed_start),
            "T_end": float(args.T_end),
            "dt": float(args.dt),
            "warmup_s": float(args.warmup_s),
            "eval_period_s": float(args.eval_period_s),
            "forecast_horizon_s": float(args.forecast_horizon_s),
            "sample_every_s": float(args.sample_every_s),
            "bin_s": float(args.bin_s),
            "task_replan_period_s": float(args.task_replan_period_s),
            "hotspot_top_k": int(args.hotspot_top_k),
            "match_radius_m": float(args.match_radius_m),
            "support_radius_m": float(args.support_radius_m),
            "patrol_hotspot_filter_mode": str(args.patrol_hotspot_filter_mode),
            "patrol_hotspot_score_percentile": float(args.patrol_hotspot_score_percentile),
            "alpha_inhib": float(args.alpha_inhib),
            "omega_inhib": float(args.omega_inhib),
            "mu_base": float(args.mu_base),
            "bg_ema": float(args.bg_ema),
            "intervention_shuffle": str(args.intervention_shuffle),
        },
        "outcome_summary": {
            "exposure_improve_pct_mean": _safe_mean(per_run_df["exposure_improve_pct"].tolist()),
            "exposure_improve_pct_std": _safe_std(per_run_df["exposure_improve_pct"].tolist()),
            "response_improve_pct_mean": _safe_mean(per_run_df["response_improve_pct"].tolist()),
            "response_improve_pct_std": _safe_std(per_run_df["response_improve_pct"].tolist()),
            "comm_increase_pct_mean": _safe_mean(per_run_df["comm_increase_pct"].tolist()),
            "runs_exposure_positive": int((per_run_df["exposure_improve_pct"] > 0.0).sum()),
            "runs_response_positive": int((per_run_df["response_improve_pct"] > 0.0).sum()),
            "runs_both_positive": int(
                ((per_run_df["exposure_improve_pct"] > 0.0) & (per_run_df["response_improve_pct"] > 0.0)).sum()
            ),
        },
        "top_exposure_correlates": top_exp,
        "top_response_correlates": top_resp,
    }

    conclusions = []
    if summary["outcome_summary"]["runs_exposure_positive"] < int(args.runs):
        conclusions.append("Feedback-on proposed is not robust across seeds on exposure.")
    if _safe_mean(per_run_df["brier_improvement_pct"].tolist()) > 0.0:
        conclusions.append("Field-level feedback benefit remains positive on average across the same seeds.")
    if top_exp:
        conclusions.append(
            f"Strongest exposure correlate: `{top_exp[0]['metric']}` "
            f"(pearson `{top_exp[0]['pearson_r']}`, spearman `{top_exp[0]['spearman_r']}`)."
        )
    if top_resp:
        conclusions.append(
            f"Strongest response correlate: `{top_resp[0]['metric']}` "
            f"(pearson `{top_resp[0]['pearson_r']}`, spearman `{top_resp[0]['spearman_r']}`)."
        )
    summary["conclusions"] = conclusions

    with open(outdir / "feedback_failure_slicing_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with open(outdir / "feedback_failure_slicing_report.md", "w", encoding="utf-8") as f:
        f.write("# Feedback Failure Slicing Diagnostic\n\n")
        f.write("## Parameters\n\n")
        for k, v in summary["parameters"].items():
            f.write(f"- `{k}`: `{v}`\n")
        f.write("\n## Outcome Summary\n\n")
        for k, v in summary["outcome_summary"].items():
            f.write(f"- `{k}`: `{v}`\n")
        f.write("\n## Top Exposure Correlates\n\n")
        for row in top_exp:
            f.write(f"- `{row['metric']}`: pearson `{row['pearson_r']}`, spearman `{row['spearman_r']}`, n `{row['valid_n']}`\n")
        f.write("\n## Top Response Correlates\n\n")
        for row in top_resp:
            f.write(f"- `{row['metric']}`: pearson `{row['pearson_r']}`, spearman `{row['spearman_r']}`, n `{row['valid_n']}`\n")
        f.write("\n## Conclusions\n\n")
        for line in conclusions:
            f.write(f"- {line}\n")

    _plot_failure_slicing(
        per_run_df,
        corr_exposure_df,
        corr_response_df,
        outdir / "feedback_failure_slicing_scatter.png",
    )
    print(f"[done] feedback failure-slicing diagnostic saved to: {outdir}")


if __name__ == "__main__":
    main()
