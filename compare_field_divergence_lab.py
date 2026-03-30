from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import DeterrentSystem_assignment_lab as ds
from config_loader import add_config_argument, parse_args_with_config, write_resolved_config_manifest


Point2 = Tuple[float, float]


FIELD_DIVERGENCE_CONFIG_ALIASES = {
    "runner.seed": "seed",
    "runner.outdir": "outdir",
    "simulation.t_end": "t_end",
    "simulation.dt": "dt",
    "analysis.sample_period_s": "sample_period_s",
    "analysis.hotspot_top_k": "hotspot_top_k",
    "analysis.hotspot_match_radius_m": "hotspot_match_radius_m",
    "analysis.patrol_match_radius_m": "patrol_match_radius_m",
    "analysis.recent_deterrence_window_s": "recent_deterrence_window_s",
    "analysis.recent_deterrence_radius_m": "recent_deterrence_radius_m",
    "analysis.local_patch_radius_m": "local_patch_radius_m",
    "planner.assignment_method": "assignment_method",
    "planner.assignment_distance_cost_per_m": "assignment_distance_cost_per_m",
    "planner.assignment_switch_penalty": "assignment_switch_penalty",
    "planner.task_replan_period_s": "task_replan_period_s",
    "planner.assigner_w_task_value": "assigner_w_task_value",
    "patrol_filter.patrol_min_hotspot_score": "patrol_min_hotspot_score",
    "patrol_filter.patrol_hotspot_filter_mode": "patrol_hotspot_filter_mode",
    "patrol_filter.patrol_hotspot_score_percentile": "patrol_hotspot_score_percentile",
    "patrol_filter.patrol_hotspot_keep_top_k": "patrol_hotspot_keep_top_k",
    "gating.model_deterring_window_s": "model_deterring_window_s",
    "gating.model_deterring_gate_policy": "model_deterring_gate_policy",
    "gating.model_deterring_sprt_alpha": "model_deterring_sprt_alpha",
    "gating.model_deterring_sprt_beta": "model_deterring_sprt_beta",
    "gating.model_deterring_chance_threshold": "model_deterring_chance_threshold",
    "gating.model_deterring_min_deltaj_per_cost": "model_deterring_min_deltaj_per_cost",
    "ground_truth.truth_beta_scale": "truth_beta_scale",
    "ground_truth.truth_omega_scale": "truth_omega_scale",
    "ground_truth.truth_sigma_scale": "truth_sigma_scale",
    "model.model_beta_scale": "model_beta_scale",
}


def _safe_mean(values: Sequence[float]) -> float:
    arr = np.array([float(v) for v in values if np.isfinite(v)], dtype=float)
    return float(np.mean(arr)) if arr.size else float("nan")


def _safe_max(values: Sequence[float]) -> float:
    arr = np.array([float(v) for v in values if np.isfinite(v)], dtype=float)
    return float(np.max(arr)) if arr.size else float("nan")


def _score_quantile(rows: Iterable[dict], pct: float) -> float:
    vals = sorted(float(row.get("score", float("nan"))) for row in rows if np.isfinite(float(row.get("score", float("nan")))))
    if not vals:
        return float("nan")
    if len(vals) == 1:
        return float(vals[0])
    pos = (len(vals) - 1) * (float(pct) / 100.0)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(vals[lo])
    frac = pos - lo
    return float(vals[lo] * (1.0 - frac) + vals[hi] * frac)


def _score_max(rows: Iterable[dict]) -> float:
    vals = [float(row.get("score", float("nan"))) for row in rows if np.isfinite(float(row.get("score", float("nan"))))]
    return float(max(vals)) if vals else float("nan")


def _stats_mean(rows: Iterable[dict], key: str) -> float:
    vals = [float(row.get(key, float("nan"))) for row in rows if np.isfinite(float(row.get(key, float("nan"))))]
    return _safe_mean(vals)


def _greedy_match(points_a: Sequence[Point2], points_b: Sequence[Point2], max_radius_m: float) -> Tuple[int, float]:
    if not points_a or not points_b:
        return 0, float("nan")
    max_r2 = float(max_radius_m) ** 2
    used_b = set()
    dists = []
    matches = 0
    for ax, ay in points_a:
        best_j = None
        best_d2 = None
        for j, (bx, by) in enumerate(points_b):
            if j in used_b:
                continue
            d2 = (float(ax) - float(bx)) ** 2 + (float(ay) - float(by)) ** 2
            if d2 > max_r2:
                continue
            if best_d2 is None or d2 < best_d2:
                best_d2 = d2
                best_j = j
        if best_j is not None:
            used_b.add(best_j)
            matches += 1
            dists.append(math.sqrt(best_d2))
    return matches, (_safe_mean(dists) if dists else float("nan"))


def _patch_mask(xs: np.ndarray, ys: np.ndarray, x0: float, y0: float, radius_m: float) -> np.ndarray:
    xx, yy = np.meshgrid(xs, ys)
    return ((xx - float(x0)) ** 2 + (yy - float(y0)) ** 2) <= float(radius_m) ** 2


def _collect_sampled_frames(
    baseline: str,
    seed: int,
    sim_kwargs: dict,
    sample_period_s: float,
    hotspot_top_k: int,
) -> Tuple[Dict[int, dict], dict]:
    frames = ds.run_simulation_frames_persistent(
        seed=int(seed),
        simulation_mode=str(baseline),
        export_field_debug=True,
        export_task_debug=True,
        report_metrics_end=False,
        **sim_kwargs,
    )
    out: Dict[int, dict] = {}
    last = None
    next_sample_s = 0.0
    eps = 1e-9
    for snap in frames:
        last = snap
        t_s = float(snap.get("t", 0.0))
        if t_s + eps < next_sample_s:
            continue
        out[int(round(t_s))] = {
            "t_s": t_s,
            "field_xs": np.array(snap.get("field_xs", []), dtype=float),
            "field_ys": np.array(snap.get("field_ys", []), dtype=float),
            "field_lam": np.array(snap.get("field_lam", []), dtype=float),
            "field_mu": np.array(snap.get("field_mu", []), dtype=float),
            "global_hotspots": [
                (float(h.get("x", 0.0)), float(h.get("y", 0.0)), float(h.get("score", 0.0)))
                for h in list(snap.get("global_hotspots", []))[: int(hotspot_top_k)]
            ],
            "local_hotspot_score_stats": list(snap.get("local_hotspot_score_stats", [])),
            "local_hotspots_raw": list(snap.get("local_hotspots_raw", [])),
            "local_hotspots_score_filtered": list(snap.get("local_hotspots_score_filtered", [])),
            "local_hotspots_spaced": list(snap.get("local_hotspots_spaced", [])),
            "raw_patrol_candidates": list(snap.get("raw_patrol_candidates", [])),
            "selected_patrol_tasks": list(snap.get("selected_patrol_tasks", [])),
            "tasks_active": list(snap.get("tasks_active", [])),
            "tasks_done": list(snap.get("tasks_done", [])),
            "metrics": dict(snap.get("metrics", {})),
        }
        next_sample_s += float(sample_period_s)
    final_metrics = {}
    if last is not None:
        final_metrics = dict(last.get("metrics", {}))
    return out, final_metrics


def _patrol_points(tasks: Iterable[dict]) -> List[Point2]:
    pts = []
    for tr in tasks:
        if str(tr.get("state", "")).strip().lower() != "active":
            continue
        if str(tr.get("type", "")).strip().lower() != "patrolling":
            continue
        pts.append((float(tr.get("x", 0.0)), float(tr.get("y", 0.0))))
    return pts


def _xy_points(rows: Iterable[dict]) -> List[Point2]:
    pts = []
    for row in rows:
        try:
            pts.append((float(row.get("x", 0.0)), float(row.get("y", 0.0))))
        except Exception:
            continue
    return pts


def _recent_deterrence_points(tasks_done: Iterable[dict], t_s: float, recent_window_s: float) -> List[Point2]:
    pts = []
    t0 = float(t_s) - float(recent_window_s)
    for tr in tasks_done:
        if str(tr.get("type", "")).strip().lower() != "deterring":
            continue
        t_done = float(tr.get("t_done", tr.get("time", -1e9)))
        if t_done < t0 or t_done > float(t_s):
            continue
        pts.append((float(tr.get("x", 0.0)), float(tr.get("y", 0.0))))
    return pts


def _recent_deterrence_patrol_fraction(tasks_active: Iterable[dict], tasks_done: Iterable[dict], t_s: float, recent_window_s: float, radius_m: float) -> float:
    patrols = _patrol_points(tasks_active)
    if not patrols:
        return float("nan")
    dets = _recent_deterrence_points(tasks_done, t_s, recent_window_s)
    if not dets:
        return 0.0
    r2 = float(radius_m) ** 2
    near = 0
    for px, py in patrols:
        if any(((px - dx) ** 2 + (py - dy) ** 2) <= r2 for dx, dy in dets):
            near += 1
    return float(near) / float(len(patrols))


def _local_drop_metrics(prev_snap: dict | None, cur_snap: dict, local_patch_radius_m: float) -> Tuple[float, float]:
    if prev_snap is None:
        return float("nan"), float("nan")
    prev_done = {
        int(tr.get("id", -1)): tr
        for tr in prev_snap.get("tasks_done", [])
        if str(tr.get("type", "")).strip().lower() == "deterring"
    }
    new_deterring = [
        tr for tr in cur_snap.get("tasks_done", [])
        if str(tr.get("type", "")).strip().lower() == "deterring"
        and int(tr.get("id", -1)) not in prev_done
    ]
    if not new_deterring:
        return float("nan"), float("nan")
    xs = np.array(cur_snap.get("field_xs", []), dtype=float)
    ys = np.array(cur_snap.get("field_ys", []), dtype=float)
    prev_lam = np.array(prev_snap.get("field_lam", []), dtype=float)
    prev_mu = np.array(prev_snap.get("field_mu", []), dtype=float)
    cur_lam = np.array(cur_snap.get("field_lam", []), dtype=float)
    cur_mu = np.array(cur_snap.get("field_mu", []), dtype=float)
    if prev_lam.size == 0 or cur_lam.size == 0 or xs.size == 0 or ys.size == 0:
        return float("nan"), float("nan")
    lam_drops = []
    excess_drops = []
    prev_excess = prev_lam - prev_mu
    cur_excess = cur_lam - cur_mu
    for tr in new_deterring:
        mask = _patch_mask(xs, ys, float(tr.get("x", 0.0)), float(tr.get("y", 0.0)), float(local_patch_radius_m))
        if not np.any(mask):
            continue
        lam_drops.append(float(np.mean((prev_lam - cur_lam)[mask])))
        excess_drops.append(float(np.mean((prev_excess - cur_excess)[mask])))
    return _safe_mean(lam_drops), _safe_mean(excess_drops)


def _summary_row(per_time_df: pd.DataFrame, final_metrics_by_baseline: Dict[str, dict]) -> pd.DataFrame:
    row = {
        "sample_count": int(len(per_time_df)),
        "lambda_l1_mean_mean": _safe_mean(per_time_df["lambda_l1_mean"].tolist()),
        "lambda_l2_mean_mean": _safe_mean(per_time_df["lambda_l2_mean"].tolist()),
        "lambda_max_abs_diff_max": _safe_max(per_time_df["lambda_max_abs_diff"].tolist()),
        "suppressed_area_fraction_mean": _safe_mean(per_time_df["suppressed_area_fraction"].tolist()),
        "hotspot_overlap_at_k_mean": _safe_mean(per_time_df["hotspot_overlap_at_k"].tolist()),
        "hotspot_mean_match_distance_m_mean": _safe_mean(per_time_df["hotspot_mean_match_distance_m"].tolist()),
        "local_hotspot_filter_threshold_mean_prediction_only_mean": _safe_mean(
            per_time_df["local_hotspot_filter_threshold_mean_prediction_only"].tolist()
        ),
        "local_hotspot_filter_threshold_mean_proposed_mean": _safe_mean(
            per_time_df["local_hotspot_filter_threshold_mean_proposed"].tolist()
        ),
        "local_hotspots_raw_score_p90_prediction_only_mean": _safe_mean(
            per_time_df["local_hotspots_raw_score_p90_prediction_only"].tolist()
        ),
        "local_hotspots_raw_score_p90_proposed_mean": _safe_mean(
            per_time_df["local_hotspots_raw_score_p90_proposed"].tolist()
        ),
        "local_hotspots_raw_overlap_mean": _safe_mean(per_time_df["local_hotspots_raw_overlap"].tolist()),
        "local_hotspots_raw_mean_match_distance_m_mean": _safe_mean(
            per_time_df["local_hotspots_raw_mean_match_distance_m"].tolist()
        ),
        "local_hotspots_score_filtered_overlap_mean": _safe_mean(
            per_time_df["local_hotspots_score_filtered_overlap"].tolist()
        ),
        "local_hotspots_score_filtered_mean_match_distance_m_mean": _safe_mean(
            per_time_df["local_hotspots_score_filtered_mean_match_distance_m"].tolist()
        ),
        "local_hotspots_spaced_overlap_mean": _safe_mean(per_time_df["local_hotspots_spaced_overlap"].tolist()),
        "local_hotspots_spaced_mean_match_distance_m_mean": _safe_mean(
            per_time_df["local_hotspots_spaced_mean_match_distance_m"].tolist()
        ),
        "raw_patrol_candidate_overlap_mean": _safe_mean(per_time_df["raw_patrol_candidate_overlap"].tolist()),
        "raw_patrol_candidate_mean_match_distance_m_mean": _safe_mean(
            per_time_df["raw_patrol_candidate_mean_match_distance_m"].tolist()
        ),
        "selected_patrol_overlap_mean": _safe_mean(per_time_df["selected_patrol_overlap"].tolist()),
        "selected_patrol_mean_match_distance_m_mean": _safe_mean(
            per_time_df["selected_patrol_mean_match_distance_m"].tolist()
        ),
        "patrol_overlap_mean": _safe_mean(per_time_df["patrol_overlap"].tolist()),
        "patrol_mean_match_distance_m_mean": _safe_mean(per_time_df["patrol_mean_match_distance_m"].tolist()),
        "recent_deterrence_patrol_fraction_prediction_only_mean": _safe_mean(
            per_time_df["recent_deterrence_patrol_fraction_prediction_only"].tolist()
        ),
        "recent_deterrence_patrol_fraction_proposed_mean": _safe_mean(
            per_time_df["recent_deterrence_patrol_fraction_proposed"].tolist()
        ),
        "local_lambda_drop_mean_prediction_only_mean": _safe_mean(
            per_time_df["local_lambda_drop_mean_prediction_only"].tolist()
        ),
        "local_lambda_drop_mean_proposed_mean": _safe_mean(
            per_time_df["local_lambda_drop_mean_proposed"].tolist()
        ),
        "local_excess_drop_mean_prediction_only_mean": _safe_mean(
            per_time_df["local_excess_drop_mean_prediction_only"].tolist()
        ),
        "local_excess_drop_mean_proposed_mean": _safe_mean(
            per_time_df["local_excess_drop_mean_proposed"].tolist()
        ),
    }
    m_pred = final_metrics_by_baseline.get("prediction_only", {})
    m_prop = final_metrics_by_baseline.get("proposed", {})
    exp_pred = float(m_pred.get("value_weighted_exposure", np.nan))
    exp_prop = float(m_prop.get("value_weighted_exposure", np.nan))
    resp_pred = float(m_pred.get("mean_response_time_s", np.nan))
    resp_prop = float(m_prop.get("mean_response_time_s", np.nan))
    row["final_value_weighted_exposure_prediction_only"] = exp_pred
    row["final_value_weighted_exposure_proposed"] = exp_prop
    row["final_exposure_improve_pct"] = (
        100.0 * (exp_pred - exp_prop) / exp_pred if np.isfinite(exp_pred) and exp_pred > 0.0 and np.isfinite(exp_prop) else float("nan")
    )
    row["final_mean_response_time_s_prediction_only"] = resp_pred
    row["final_mean_response_time_s_proposed"] = resp_prop
    row["final_response_improve_pct"] = (
        100.0 * (resp_pred - resp_prop) / resp_pred if np.isfinite(resp_pred) and resp_pred > 0.0 and np.isfinite(resp_prop) else float("nan")
    )
    return pd.DataFrame([row])


def _plot_time_series(per_time_df: pd.DataFrame, outdir: Path) -> List[Path]:
    out_paths: List[Path] = []
    t = pd.to_numeric(per_time_df["t_s"], errors="coerce").to_numpy(dtype=float) / 60.0

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(t, per_time_df["lambda_l1_mean"], label="L1 mean")
    axes[0].plot(t, per_time_df["lambda_l2_mean"], label="L2 mean")
    axes[0].set_ylabel("Field divergence")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    axes[1].plot(t, per_time_df["suppressed_area_fraction"], label="Suppressed area fraction")
    axes[1].set_ylabel("Fraction")
    axes[1].set_xlabel("Simulation time (min)")
    axes[1].grid(True, alpha=0.3)
    p1 = outdir / "field_divergence_over_time.png"
    fig.tight_layout()
    fig.savefig(p1, dpi=180)
    plt.close(fig)
    out_paths.append(p1)

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(t, per_time_df["hotspot_overlap_at_k"], label="Hotspot overlap@k")
    axes[0].plot(t, per_time_df["local_hotspots_raw_overlap"], label="Local raw hotspot overlap")
    axes[0].plot(t, per_time_df["local_hotspots_score_filtered_overlap"], label="Score-filtered overlap")
    axes[0].plot(t, per_time_df["local_hotspots_spaced_overlap"], label="Spaced-hotspot overlap")
    axes[0].plot(t, per_time_df["raw_patrol_candidate_overlap"], label="Raw patrol overlap")
    axes[0].plot(t, per_time_df["selected_patrol_overlap"], label="Selected patrol overlap")
    axes[0].plot(t, per_time_df["patrol_overlap"], label="Active patrol overlap")
    axes[0].set_ylabel("Overlap")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    axes[1].plot(t, per_time_df["hotspot_mean_match_distance_m"], label="Hotspot distance")
    axes[1].plot(t, per_time_df["local_hotspots_raw_mean_match_distance_m"], label="Local raw hotspot distance")
    axes[1].plot(
        t,
        per_time_df["local_hotspots_score_filtered_mean_match_distance_m"],
        label="Score-filtered distance",
    )
    axes[1].plot(t, per_time_df["local_hotspots_spaced_mean_match_distance_m"], label="Spaced-hotspot distance")
    axes[1].plot(t, per_time_df["raw_patrol_candidate_mean_match_distance_m"], label="Raw patrol distance")
    axes[1].plot(t, per_time_df["selected_patrol_mean_match_distance_m"], label="Selected patrol distance")
    axes[1].plot(t, per_time_df["patrol_mean_match_distance_m"], label="Active patrol distance")
    axes[1].set_ylabel("Distance (m)")
    axes[1].set_xlabel("Simulation time (min)")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    p2 = outdir / "hotspot_patrol_pipeline_divergence_over_time.png"
    fig.tight_layout()
    fig.savefig(p2, dpi=180)
    plt.close(fig)
    out_paths.append(p2)

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(t, per_time_df["recent_deterrence_patrol_fraction_prediction_only"], label="Pred-only")
    axes[0].plot(t, per_time_df["recent_deterrence_patrol_fraction_proposed"], label="Proposed")
    axes[0].set_ylabel("Patrol near recent deterrence")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    axes[1].plot(t, per_time_df["local_lambda_drop_mean_prediction_only"], label="Pred-only lambda drop")
    axes[1].plot(t, per_time_df["local_lambda_drop_mean_proposed"], label="Proposed lambda drop")
    axes[1].plot(t, per_time_df["local_excess_drop_mean_prediction_only"], linestyle="--", label="Pred-only excess drop")
    axes[1].plot(t, per_time_df["local_excess_drop_mean_proposed"], linestyle="--", label="Proposed excess drop")
    axes[1].set_ylabel("Local drop")
    axes[1].set_xlabel("Simulation time (min)")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    p3 = outdir / "deterrence_local_effects_over_time.png"
    fig.tight_layout()
    fig.savefig(p3, dpi=180)
    plt.close(fig)
    out_paths.append(p3)

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(t, per_time_df["local_hotspots_raw_count_prediction_only"], label="Pred-only raw count")
    axes[0].plot(t, per_time_df["local_hotspots_raw_count_proposed"], label="Proposed raw count")
    axes[0].plot(
        t,
        per_time_df["local_hotspots_score_filtered_count_prediction_only"],
        linestyle="--",
        label="Pred-only filtered count",
    )
    axes[0].plot(
        t,
        per_time_df["local_hotspots_score_filtered_count_proposed"],
        linestyle="--",
        label="Proposed filtered count",
    )
    axes[0].set_ylabel("Hotspot count")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    axes[1].plot(
        t,
        per_time_df["local_hotspots_raw_score_p90_prediction_only"],
        label="Pred-only raw score p90",
    )
    axes[1].plot(
        t,
        per_time_df["local_hotspots_raw_score_p90_proposed"],
        label="Proposed raw score p90",
    )
    axes[1].plot(
        t,
        per_time_df["local_hotspot_filter_threshold_mean_prediction_only"],
        linestyle="--",
        label="Pred-only threshold",
    )
    axes[1].plot(
        t,
        per_time_df["local_hotspot_filter_threshold_mean_proposed"],
        linestyle="--",
        label="Proposed threshold",
    )
    axes[1].set_ylabel("Hotspot score")
    axes[1].set_xlabel("Simulation time (min)")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    p4 = outdir / "local_hotspot_score_diagnostics_over_time.png"
    fig.tight_layout()
    fig.savefig(p4, dpi=180)
    plt.close(fig)
    out_paths.append(p4)

    return out_paths


def _plot_diff_heatmaps(sample_pairs: List[Tuple[dict, dict]], outdir: Path) -> Path | None:
    if not sample_pairs:
        return None
    picks = []
    if len(sample_pairs) >= 1:
        picks.append(sample_pairs[0])
    if len(sample_pairs) >= 3:
        picks.append(sample_pairs[len(sample_pairs) // 2])
    if len(sample_pairs) >= 2:
        picks.append(sample_pairs[-1])
    seen = set()
    uniq = []
    for pred_snap, prop_snap in picks:
        key = int(round(float(pred_snap.get("t_s", 0.0))))
        if key in seen:
            continue
        seen.add(key)
        uniq.append((pred_snap, prop_snap))
    if not uniq:
        return None
    fig, axes = plt.subplots(1, len(uniq), figsize=(5 * len(uniq), 4), squeeze=False)
    axes = axes[0]
    for ax, (pred_snap, prop_snap) in zip(axes, uniq):
        lam_pred = np.array(pred_snap.get("field_lam", []), dtype=float)
        lam_prop = np.array(prop_snap.get("field_lam", []), dtype=float)
        if lam_pred.size == 0 or lam_prop.size == 0:
            ax.set_axis_off()
            continue
        diff = lam_prop - lam_pred
        xs = np.array(pred_snap.get("field_xs", []), dtype=float)
        ys = np.array(pred_snap.get("field_ys", []), dtype=float)
        extent = None
        if xs.size > 0 and ys.size > 0:
            extent = [float(xs.min()), float(xs.max()), float(ys.min()), float(ys.max())]
        im = ax.imshow(diff, origin="lower", extent=extent, aspect="auto", cmap="coolwarm")
        ax.set_title(f"t={pred_snap['t_s'] / 60.0:.1f} min")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    p = outdir / "lambda_difference_heatmaps.png"
    fig.tight_layout()
    fig.savefig(p, dpi=180)
    plt.close(fig)
    return p


def main() -> None:
    parser = argparse.ArgumentParser(description="Lab-only field divergence diagnostic: proposed vs prediction_only")
    add_config_argument(parser)
    parser.add_argument("--seed", type=int, default=2000)
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
    parser.add_argument("--task-replan-period-s", type=float, default=90.0)
    parser.add_argument("--assigner-w-task-value", type=float, default=0.0)
    parser.add_argument("--patrol-min-hotspot-score", type=float, default=1e-4)
    parser.add_argument("--patrol-hotspot-filter-mode", type=str, default="absolute")
    parser.add_argument("--patrol-hotspot-score-percentile", type=float, default=90.0)
    parser.add_argument("--patrol-hotspot-keep-top-k", type=int, default=6)
    parser.add_argument("--model-deterring-window-s", type=float, default=90.0)
    parser.add_argument("--model-deterring-gate-policy", type=str, default="heuristic")
    parser.add_argument("--model-deterring-sprt-alpha", type=float, default=0.05)
    parser.add_argument("--model-deterring-sprt-beta", type=float, default=0.20)
    parser.add_argument("--model-deterring-chance-threshold", type=float, default=0.20)
    parser.add_argument("--model-deterring-min-deltaj-per-cost", type=float, default=0.15)
    parser.add_argument("--truth-beta-scale", type=float, default=1.0)
    parser.add_argument("--truth-omega-scale", type=float, default=1.0)
    parser.add_argument("--truth-sigma-scale", type=float, default=1.0)
    parser.add_argument("--model-beta-scale", type=float, default=1.0)
    parser.add_argument("--outdir", type=str, default="results/field_divergence_lab")
    args, config_meta = parse_args_with_config(parser, aliases=FIELD_DIVERGENCE_CONFIG_ALIASES)

    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    deterring_modes = {
        "formation": {"beta": 0.30 * float(args.model_beta_scale), "omega": 800.0, "sigma": 18.0, "w_eta": 1.0, "fixed_cost": 0.0},
        "laser": {"beta": 0.45 * float(args.model_beta_scale), "omega": 400.0, "sigma": 10.0, "w_eta": 1.5, "fixed_cost": 0.0},
        "biosonic": {"beta": 0.25 * float(args.model_beta_scale), "omega": 600.0, "sigma": 20.0, "w_eta": 1.2, "fixed_cost": 0.0},
    }
    sim_kwargs = {
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
        "task_replan_period_s": float(args.task_replan_period_s),
        "assignment_method": str(args.assignment_method),
        "assignment_distance_cost_per_m": float(args.assignment_distance_cost_per_m),
        "assignment_switch_penalty": float(args.assignment_switch_penalty),
        "assigner_w_task_value": float(args.assigner_w_task_value),
        "patrol_min_hotspot_score": float(args.patrol_min_hotspot_score),
        "patrol_hotspot_filter_mode": str(args.patrol_hotspot_filter_mode),
        "patrol_hotspot_score_percentile": float(args.patrol_hotspot_score_percentile),
        "patrol_hotspot_keep_top_k": int(args.patrol_hotspot_keep_top_k),
        "model_deterring_window_s": float(args.model_deterring_window_s),
        "model_deterring_gate_policy": str(args.model_deterring_gate_policy),
        "model_deterring_sprt_alpha": float(args.model_deterring_sprt_alpha),
        "model_deterring_sprt_beta": float(args.model_deterring_sprt_beta),
        "model_deterring_chance_threshold": float(args.model_deterring_chance_threshold),
        "model_deterring_min_deltaJ_per_cost": float(args.model_deterring_min_deltaj_per_cost),
        "beta_true": 0.35 * float(args.truth_beta_scale),
        "omega_true": 600.0 * float(args.truth_omega_scale),
        "sigma_true": 12.0 * float(args.truth_sigma_scale),
        "deterring_modes": deterring_modes,
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
        "T_end": float(args.t_end),
        "dt": float(args.dt),
    }

    baseline_samples: Dict[str, Dict[int, dict]] = {}
    final_metrics_by_baseline: Dict[str, dict] = {}
    for baseline in ("prediction_only", "proposed"):
        samples, final_metrics = _collect_sampled_frames(
            baseline=baseline,
            seed=int(args.seed),
            sim_kwargs=sim_kwargs,
            sample_period_s=float(args.sample_period_s),
            hotspot_top_k=int(args.hotspot_top_k),
        )
        baseline_samples[baseline] = samples
        final_metrics_by_baseline[baseline] = final_metrics

    common_ts = sorted(set(baseline_samples["prediction_only"].keys()) & set(baseline_samples["proposed"].keys()))
    per_time_rows = []
    sample_pairs_for_heatmap = []
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
        hs_matches, hs_dist = _greedy_match(hs_pred, hs_prop, float(args.hotspot_match_radius_m))
        hotspot_overlap = float(hs_matches) / float(max(int(args.hotspot_top_k), 1))

        pred_score_stats = pred_snap.get("local_hotspot_score_stats", [])
        prop_score_stats = prop_snap.get("local_hotspot_score_stats", [])
        pred_threshold = _stats_mean(pred_score_stats, "threshold_applied")
        prop_threshold = _stats_mean(prop_score_stats, "threshold_applied")
        pred_score_p50 = _score_quantile(pred_snap.get("local_hotspots_raw", []), 50.0)
        prop_score_p50 = _score_quantile(prop_snap.get("local_hotspots_raw", []), 50.0)
        pred_score_p90 = _score_quantile(pred_snap.get("local_hotspots_raw", []), 90.0)
        prop_score_p90 = _score_quantile(prop_snap.get("local_hotspots_raw", []), 90.0)
        pred_score_max = _score_max(pred_snap.get("local_hotspots_raw", []))
        prop_score_max = _score_max(prop_snap.get("local_hotspots_raw", []))

        local_raw_pred = _xy_points(pred_snap.get("local_hotspots_raw", []))
        local_raw_prop = _xy_points(prop_snap.get("local_hotspots_raw", []))
        local_raw_matches, local_raw_dist = _greedy_match(local_raw_pred, local_raw_prop, float(args.hotspot_match_radius_m))
        local_raw_denom = max(len(local_raw_pred), len(local_raw_prop), 1)
        local_raw_overlap = float(local_raw_matches) / float(local_raw_denom)

        local_filtered_pred = _xy_points(pred_snap.get("local_hotspots_score_filtered", []))
        local_filtered_prop = _xy_points(prop_snap.get("local_hotspots_score_filtered", []))
        local_filtered_matches, local_filtered_dist = _greedy_match(
            local_filtered_pred, local_filtered_prop, float(args.hotspot_match_radius_m)
        )
        local_filtered_denom = max(len(local_filtered_pred), len(local_filtered_prop), 1)
        local_filtered_overlap = float(local_filtered_matches) / float(local_filtered_denom)

        local_spaced_pred = _xy_points(pred_snap.get("local_hotspots_spaced", []))
        local_spaced_prop = _xy_points(prop_snap.get("local_hotspots_spaced", []))
        local_spaced_matches, local_spaced_dist = _greedy_match(
            local_spaced_pred, local_spaced_prop, float(args.hotspot_match_radius_m)
        )
        local_spaced_denom = max(len(local_spaced_pred), len(local_spaced_prop), 1)
        local_spaced_overlap = float(local_spaced_matches) / float(local_spaced_denom)

        raw_patrol_pred = _xy_points(pred_snap.get("raw_patrol_candidates", []))
        raw_patrol_prop = _xy_points(prop_snap.get("raw_patrol_candidates", []))
        raw_matches, raw_dist = _greedy_match(raw_patrol_pred, raw_patrol_prop, float(args.patrol_match_radius_m))
        raw_denom = max(len(raw_patrol_pred), len(raw_patrol_prop), 1)
        raw_overlap = float(raw_matches) / float(raw_denom)

        selected_patrol_pred = _xy_points(pred_snap.get("selected_patrol_tasks", []))
        selected_patrol_prop = _xy_points(prop_snap.get("selected_patrol_tasks", []))
        sel_matches, sel_dist = _greedy_match(selected_patrol_pred, selected_patrol_prop, float(args.patrol_match_radius_m))
        sel_denom = max(len(selected_patrol_pred), len(selected_patrol_prop), 1)
        selected_overlap = float(sel_matches) / float(sel_denom)

        patrol_pred = _patrol_points(pred_snap.get("tasks_active", []))
        patrol_prop = _patrol_points(prop_snap.get("tasks_active", []))
        patrol_matches, patrol_dist = _greedy_match(patrol_pred, patrol_prop, float(args.patrol_match_radius_m))
        patrol_denom = max(len(patrol_pred), len(patrol_prop), 1)
        patrol_overlap = float(patrol_matches) / float(patrol_denom)

        pred_recent_patrol = _recent_deterrence_patrol_fraction(
            pred_snap.get("tasks_active", []),
            pred_snap.get("tasks_done", []),
            float(pred_snap["t_s"]),
            float(args.recent_deterrence_window_s),
            float(args.recent_deterrence_radius_m),
        )
        prop_recent_patrol = _recent_deterrence_patrol_fraction(
            prop_snap.get("tasks_active", []),
            prop_snap.get("tasks_done", []),
            float(prop_snap["t_s"]),
            float(args.recent_deterrence_window_s),
            float(args.recent_deterrence_radius_m),
        )

        pred_local_drop, pred_local_excess = _local_drop_metrics(prev_pred, pred_snap, float(args.local_patch_radius_m))
        prop_local_drop, prop_local_excess = _local_drop_metrics(prev_prop, prop_snap, float(args.local_patch_radius_m))

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
                "local_hotspots_raw_score_p50_prediction_only": pred_score_p50,
                "local_hotspots_raw_score_p50_proposed": prop_score_p50,
                "local_hotspots_raw_score_p90_prediction_only": pred_score_p90,
                "local_hotspots_raw_score_p90_proposed": prop_score_p90,
                "local_hotspots_raw_score_max_prediction_only": pred_score_max,
                "local_hotspots_raw_score_max_proposed": prop_score_max,
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
                "active_patrol_count_prediction_only": int(len(patrol_pred)),
                "active_patrol_count_proposed": int(len(patrol_prop)),
                "local_hotspots_raw_count_prediction_only": int(len(local_raw_pred)),
                "local_hotspots_raw_count_proposed": int(len(local_raw_prop)),
                "local_hotspots_score_filtered_count_prediction_only": int(len(local_filtered_pred)),
                "local_hotspots_score_filtered_count_proposed": int(len(local_filtered_prop)),
                "local_hotspots_spaced_count_prediction_only": int(len(local_spaced_pred)),
                "local_hotspots_spaced_count_proposed": int(len(local_spaced_prop)),
                "raw_patrol_candidate_count_prediction_only": int(len(raw_patrol_pred)),
                "raw_patrol_candidate_count_proposed": int(len(raw_patrol_prop)),
                "selected_patrol_count_prediction_only": int(len(selected_patrol_pred)),
                "selected_patrol_count_proposed": int(len(selected_patrol_prop)),
                "hotspot_count_prediction_only": int(len(hs_pred)),
                "hotspot_count_proposed": int(len(hs_prop)),
            }
        )
        sample_pairs_for_heatmap.append((pred_snap, prop_snap))
        prev_pred = pred_snap
        prev_prop = prop_snap

    per_time_df = pd.DataFrame(per_time_rows)
    summary_df = _summary_row(per_time_df, final_metrics_by_baseline)

    per_time_path = outdir / "field_divergence_per_time_lab.csv"
    summary_path = outdir / "field_divergence_summary_lab.csv"
    config_manifest_path = outdir / "field_divergence_resolved_config.json"
    per_time_df.to_csv(per_time_path, index=False)
    summary_df.to_csv(summary_path, index=False)
    write_resolved_config_manifest(
        config_manifest_path,
        script="compare_field_divergence_lab.py",
        args=args,
        config_meta=config_meta,
        extra={
            "sim_kwargs": json.loads(json.dumps(sim_kwargs, default=str)),
            "baselines": ["prediction_only", "proposed"],
        },
    )

    plot_paths = _plot_time_series(per_time_df, outdir) if not per_time_df.empty else []
    heatmap_path = _plot_diff_heatmaps(sample_pairs_for_heatmap, outdir)
    if heatmap_path is not None:
        plot_paths.append(heatmap_path)

    summary_md = outdir / "FIELD_DIVERGENCE_README.md"
    summary_md.write_text(
        "\n".join(
            [
                "# Field Divergence Lab",
                "",
                f"- Per-time CSV: `{per_time_path.name}`",
                f"- Summary CSV: `{summary_path.name}`",
                f"- Resolved config: `{config_manifest_path.name}`",
                "- Metrics:",
                "  - `lambda_l1_mean`: mean absolute difference between merged `lam` fields.",
                "  - `lambda_l2_mean`: RMS difference between merged `lam` fields.",
                "  - `suppressed_area_fraction`: fraction of cells where proposed `lam` is lower than prediction-only.",
                "  - `hotspot_overlap_at_k`: matched hotspot overlap fraction at top-k.",
                "  - `local_hotspot_filter_threshold_mean_*`: average local hotspot score threshold applied across robots.",
                "  - `local_hotspots_raw_score_p50/p90/max_*`: score distribution diagnostics for local raw hotspots.",
                "  - `local_hotspots_raw_overlap`: overlap of zone-masked local hotspots before score filtering.",
                "  - `local_hotspots_score_filtered_overlap`: overlap after local hotspot score thresholding.",
                "  - `local_hotspots_spaced_overlap`: overlap after spacing / thinning.",
                "  - `raw_patrol_candidate_overlap`: overlap of raw patrol candidates before assignment/admission.",
                "  - `selected_patrol_overlap`: overlap of patrol tasks selected by assignment before persistence/queueing.",
                "  - `patrol_overlap`: matched overlap fraction of active patrol tasks.",
                "  - `recent_deterrence_patrol_fraction_*`: fraction of patrol tasks near recently completed deterrence actions.",
                "  - `local_lambda_drop_mean_*`: average local `lam` drop after newly completed deterrence actions.",
                "  - `local_excess_drop_mean_*`: average local `(lam-mu)` drop after newly completed deterrence actions.",
                "",
                "Interpretation:",
                "- If field divergence metrics remain near zero, the IA-SESTPP is not changing the prediction enough to matter.",
                "- If global hotspots diverge but local hotspot overlaps remain high, the zone-masked local planning view is washing out the global difference.",
                "- If the local raw score p90 stays below the applied threshold, the score threshold is too strict for the local patrol generator.",
                "- If local raw hotspots diverge but score-filtered or spaced hotspots do not, local filtering/thinning is collapsing the difference.",
                "- If local spaced hotspots diverge but raw patrol candidates do not, the patrol candidate creation stage is collapsing the difference.",
                "- If hotspots diverge but raw patrol candidates do not, task generation is washing out the field difference.",
                "- If raw patrol candidates diverge but selected patrol tasks do not, assignment/selection is washing out the difference.",
                "- If selected patrol tasks diverge but active patrol queue does not, persistence/queueing is washing out the difference.",
                "- If proposed local suppression drops are larger than prediction-only, intervention feedback is affecting the predicted field.",
            ]
        ),
        encoding="utf-8",
    )

    print(f"[done] wrote outputs to: {outdir}")
    print(f"- {per_time_path}")
    print(f"- {summary_path}")
    print(f"- {config_manifest_path}")
    for p in plot_paths:
        print(f"- {p}")
    print(f"- {summary_md}")


if __name__ == "__main__":
    main()
