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


def _safe_mean(vals) -> float:
    arr = [float(v) for v in vals if np.isfinite(float(v))]
    return float(np.mean(arr)) if arr else float("nan")


def _safe_quantile(vals, q: float) -> float:
    arr = np.asarray([float(v) for v in vals if np.isfinite(float(v))], dtype=float)
    return float(np.quantile(arr, float(q))) if arr.size else float("nan")


def _safe_corr(x_vals, y_vals) -> float:
    x = np.asarray([float(v) for v in x_vals], dtype=float)
    y = np.asarray([float(v) for v in y_vals], dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x = x[mask]
    y = y[mask]
    if x.size < 3:
        return float("nan")
    if float(np.std(x)) <= 1e-12 or float(np.std(y)) <= 1e-12:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def _fano_factor(vals) -> float:
    arr = np.asarray([float(v) for v in vals if np.isfinite(float(v))], dtype=float)
    if not arr.size:
        return float("nan")
    mu = float(np.mean(arr))
    if mu <= 1e-12:
        return float("nan")
    return float(np.var(arr) / mu)


def _point_to_zone(x: float, y: float, cells) -> int:
    for i, poly in enumerate(cells):
        try:
            if ds.point_in_polygon(float(x), float(y), poly):
                return int(i)
        except Exception:
            continue
    best_i = 0
    best_d = float("inf")
    for i, poly in enumerate(cells):
        try:
            d = float(ds.point_to_poly_distance((float(x), float(y)), poly))
        except Exception:
            continue
        if d < best_d:
            best_d = d
            best_i = int(i)
    return best_i


def _bin_start(t_s: float, bin_s: float) -> float:
    if bin_s <= 0:
        return float(t_s)
    return float(math.floor(float(t_s) / float(bin_s)) * float(bin_s))


def _collect_reactive_run(label: str, sim_mode: str, run_params: dict, overrides: dict, bin_s: float):
    frames = ds.run_simulation_frames_persistent(
        simulation_mode=sim_mode,
        report_metrics_end=False,
        **run_params,
        **overrides,
    )

    first = None
    last = None
    cells = None
    zone_count = 0
    zone_bin = {}
    global_bin = {}
    assign_rows = []
    done_rows = []
    seen_assigned_ids = set()
    seen_done_ids = set()

    for snap in frames:
        if first is None:
            first = snap
            cells = list(snap.get("cells", []))
            zone_count = int(len(cells))
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
            zone_bin.setdefault(
                (bb, zi),
                {
                    "mode": label,
                    "t_bin_s": bb,
                    "zone_idx": int(zi),
                    "frame_count": 0,
                    "detection_count": 0,
                    "truth_count": 0,
                    "new_direct_det_assignment_count": 0,
                    "new_direct_det_completion_count": 0,
                    "active_direct_det_count_sum": 0,
                },
            )["new_direct_det_assignment_count"] += 1
            global_bin.setdefault(
                bb,
                {
                    "mode": label,
                    "t_bin_s": bb,
                    "frame_count": 0,
                    "boundary_messages_sent": 0,
                    "intervention_messages_sent": 0,
                    "detection_count": 0,
                    "truth_count": 0,
                    "new_direct_det_assignment_count": 0,
                    "new_direct_det_completion_count": 0,
                    "active_direct_det_count_sum": 0,
                },
            )["new_direct_det_assignment_count"] += 1
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
            zone_bin.setdefault(
                (bb, zi),
                {
                    "mode": label,
                    "t_bin_s": bb,
                    "zone_idx": int(zi),
                    "frame_count": 0,
                    "detection_count": 0,
                    "truth_count": 0,
                    "new_direct_det_assignment_count": 0,
                    "new_direct_det_completion_count": 0,
                    "active_direct_det_count_sum": 0,
                },
            )["new_direct_det_completion_count"] += 1
            global_bin.setdefault(
                bb,
                {
                    "mode": label,
                    "t_bin_s": bb,
                    "frame_count": 0,
                    "boundary_messages_sent": 0,
                    "intervention_messages_sent": 0,
                    "detection_count": 0,
                    "truth_count": 0,
                    "new_direct_det_assignment_count": 0,
                    "new_direct_det_completion_count": 0,
                    "active_direct_det_count_sum": 0,
                },
            )["new_direct_det_completion_count"] += 1
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

    zone_df = pd.DataFrame(list(zone_bin.values()))
    global_df = pd.DataFrame(list(global_bin.values())).sort_values("t_bin_s").reset_index(drop=True)
    assign_df = pd.DataFrame(assign_rows)
    done_df = pd.DataFrame(done_rows)
    return {
        "label": label,
        "cells": cells,
        "zone_df": zone_df,
        "global_df": global_df,
        "assign_df": assign_df,
        "done_df": done_df,
        "final_metrics": dict((last or {}).get("metrics", {})),
    }


def _add_share_columns(zone_df: pd.DataFrame) -> pd.DataFrame:
    out = zone_df.copy()
    share_map = {
        "detection_count": "detection_share",
        "truth_count": "truth_share",
        "new_direct_det_assignment_count": "new_direct_det_assignment_share",
        "new_direct_det_completion_count": "new_direct_det_completion_share",
        "active_direct_det_count_sum": "active_direct_det_share",
    }
    for col, share_col in share_map.items():
        totals = out.groupby(["mode", "t_bin_s"])[col].transform("sum").astype(float)
        out[share_col] = np.where(totals > 0.0, out[col].astype(float) / totals, 0.0)

    out["assignment_detection_l1_component"] = np.abs(
        out["new_direct_det_assignment_share"] - out["detection_share"]
    )
    out["completion_detection_l1_component"] = np.abs(
        out["new_direct_det_completion_share"] - out["detection_share"]
    )
    out["active_detection_l1_component"] = np.abs(
        out["active_direct_det_share"] - out["detection_share"]
    )
    out["assignment_detection_gap"] = out["new_direct_det_assignment_share"] - out["detection_share"]
    out["completion_detection_gap"] = out["new_direct_det_completion_share"] - out["detection_share"]
    out["active_detection_gap"] = out["active_direct_det_share"] - out["detection_share"]
    return out


def _summarize_mode(zone_df: pd.DataFrame, global_df: pd.DataFrame, assign_df: pd.DataFrame, done_df: pd.DataFrame) -> dict:
    per_t = (
        zone_df.groupby(["mode", "t_bin_s"], as_index=False)
        .agg(
            assignment_detection_l1=("assignment_detection_l1_component", lambda s: 0.5 * float(np.sum(s))),
            completion_detection_l1=("completion_detection_l1_component", lambda s: 0.5 * float(np.sum(s))),
            active_detection_l1=("active_detection_l1_component", lambda s: 0.5 * float(np.sum(s))),
        )
    )
    out = {}
    for mode in sorted(zone_df["mode"].unique()):
        subg = global_df[global_df["mode"] == mode]
        subt = per_t[per_t["mode"] == mode]
        suba = assign_df[assign_df["mode"] == mode]
        subd = done_df[done_df["mode"] == mode]
        detections_total = float(subg["detection_count"].sum())
        out[mode] = {
            "detections_total": int(subg["detection_count"].sum()),
            "truth_points_total": int(subg["truth_count"].sum()),
            "direct_det_assignments_total": int(subg["new_direct_det_assignment_count"].sum()),
            "direct_det_completions_total": int(subg["new_direct_det_completion_count"].sum()),
            "boundary_messages_total": int(subg["boundary_messages_sent"].sum()),
            "intervention_messages_total": int(subg["intervention_messages_sent"].sum()),
            "boundary_messages_per_detection": float(subg["boundary_messages_sent"].sum() / max(detections_total, 1.0)),
            "intervention_messages_per_detection": float(subg["intervention_messages_sent"].sum() / max(detections_total, 1.0)),
            "assignment_detection_ratio": float(subg["new_direct_det_assignment_count"].sum() / max(detections_total, 1.0)),
            "completion_detection_ratio": float(subg["new_direct_det_completion_count"].sum() / max(detections_total, 1.0)),
            "mean_assign_lag_s": _safe_mean(suba["assign_lag_s"].tolist()),
            "mean_completion_lag_s": _safe_mean(subd["completion_lag_s"].tolist()),
            "p90_assign_lag_s": _safe_quantile(suba["assign_lag_s"].tolist(), 0.90),
            "p90_completion_lag_s": _safe_quantile(subd["completion_lag_s"].tolist(), 0.90),
            "assignment_detection_l1_mean": _safe_mean(subt["assignment_detection_l1"].tolist()),
            "completion_detection_l1_mean": _safe_mean(subt["completion_detection_l1"].tolist()),
            "active_detection_l1_mean": _safe_mean(subt["active_detection_l1"].tolist()),
            "detections_p95_per_bin": _safe_quantile(subg["detection_count"].tolist(), 0.95),
            "boundary_messages_p95_per_bin": _safe_quantile(subg["boundary_messages_sent"].tolist(), 0.95),
            "intervention_messages_p95_per_bin": _safe_quantile(subg["intervention_messages_sent"].tolist(), 0.95),
            "assignments_p95_per_bin": _safe_quantile(subg["new_direct_det_assignment_count"].tolist(), 0.95),
            "completions_p95_per_bin": _safe_quantile(subg["new_direct_det_completion_count"].tolist(), 0.95),
            "active_direct_p95_per_bin": _safe_quantile(subg["active_direct_det_count_sum"].tolist(), 0.95),
            "detection_fano": _fano_factor(subg["detection_count"].tolist()),
            "boundary_message_fano": _fano_factor(subg["boundary_messages_sent"].tolist()),
            "assignment_fano": _fano_factor(subg["new_direct_det_assignment_count"].tolist()),
            "completion_fano": _fano_factor(subg["new_direct_det_completion_count"].tolist()),
            "active_direct_fano": _fano_factor(subg["active_direct_det_count_sum"].tolist()),
            "detection_boundary_corr": _safe_corr(
                subg["detection_count"].tolist(),
                subg["boundary_messages_sent"].tolist(),
            ),
            "detection_assignment_corr": _safe_corr(
                subg["detection_count"].tolist(),
                subg["new_direct_det_assignment_count"].tolist(),
            ),
            "detection_completion_corr": _safe_corr(
                subg["detection_count"].tolist(),
                subg["new_direct_det_completion_count"].tolist(),
            ),
        }
    return out


def _clusterize_rows(df: pd.DataFrame, spatial_quant_m: float, time_quant_s: float) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    q_space = max(float(spatial_quant_m), 1.0)
    q_time = max(float(time_quant_s), 1.0)
    out["cluster_t_bin_s"] = np.floor(out["detect_t"].astype(float) / q_time) * q_time
    out["cluster_x_bin"] = np.floor(out["x"].astype(float) / q_space).astype(int)
    out["cluster_y_bin"] = np.floor(out["y"].astype(float) / q_space).astype(int)
    return out


def _build_cluster_tables(
    assign_df: pd.DataFrame,
    done_df: pd.DataFrame,
    spatial_quant_m: float,
    time_quant_s: float,
) -> tuple[pd.DataFrame, dict]:
    assign_c = _clusterize_rows(assign_df, spatial_quant_m, time_quant_s)
    done_c = _clusterize_rows(done_df, spatial_quant_m, time_quant_s)

    group_cols = ["mode", "cluster_t_bin_s", "cluster_x_bin", "cluster_y_bin"]
    if assign_c.empty:
        assign_grp = pd.DataFrame(columns=group_cols + ["zone_idx", "assignments", "assign_lag_mean_s", "assign_lag_p90_s", "x_mean", "y_mean"])
    else:
        assign_grp = (
            assign_c.groupby(group_cols, as_index=False)
            .agg(
                zone_idx=("zone_idx", "median"),
                assignments=("task_id", "nunique"),
                assign_lag_mean_s=("assign_lag_s", "mean"),
                assign_lag_p90_s=("assign_lag_s", lambda s: _safe_quantile(s.tolist(), 0.90)),
                x_mean=("x", "mean"),
                y_mean=("y", "mean"),
            )
        )
        assign_grp["zone_idx"] = assign_grp["zone_idx"].fillna(0).astype(int)

    if done_c.empty:
        done_grp = pd.DataFrame(columns=group_cols + ["completions", "completion_lag_mean_s", "completion_lag_p90_s"])
    else:
        done_grp = (
            done_c.groupby(group_cols, as_index=False)
            .agg(
                completions=("task_id", "nunique"),
                completion_lag_mean_s=("completion_lag_s", "mean"),
                completion_lag_p90_s=("completion_lag_s", lambda s: _safe_quantile(s.tolist(), 0.90)),
            )
        )

    cluster_df = assign_grp.merge(done_grp, on=group_cols, how="outer")
    for col in ["assignments", "completions"]:
        cluster_df[col] = cluster_df[col].fillna(0).astype(int)
    cluster_df["zone_idx"] = cluster_df["zone_idx"].fillna(0).astype(int)
    cluster_df["assign_lag_mean_s"] = cluster_df["assign_lag_mean_s"].astype(float)
    cluster_df["completion_lag_mean_s"] = cluster_df["completion_lag_mean_s"].astype(float)
    cluster_df["assign_lag_p90_s"] = cluster_df["assign_lag_p90_s"].astype(float)
    cluster_df["completion_lag_p90_s"] = cluster_df["completion_lag_p90_s"].astype(float)
    cluster_df["x_mean"] = cluster_df["x_mean"].astype(float)
    cluster_df["y_mean"] = cluster_df["y_mean"].astype(float)
    cluster_df["excess_assignments"] = np.maximum(cluster_df["assignments"] - 1, 0)
    cluster_df["excess_completions"] = np.maximum(cluster_df["completions"] - 1, 0)
    cluster_df["completion_to_assignment_ratio"] = np.where(
        cluster_df["assignments"] > 0,
        cluster_df["completions"].astype(float) / cluster_df["assignments"].astype(float),
        np.nan,
    )

    summary = {}
    for mode in sorted(cluster_df["mode"].dropna().unique()):
        sub = cluster_df[cluster_df["mode"] == mode]
        assignments_total = float(sub["assignments"].sum())
        completions_total = float(sub["completions"].sum())
        cluster_count = int(len(sub))
        summary[mode] = {
            "reactive_clusters_total": cluster_count,
            "assignments_per_cluster_mean": _safe_mean(sub["assignments"].tolist()),
            "assignments_per_cluster_p90": _safe_quantile(sub["assignments"].tolist(), 0.90),
            "max_assignments_per_cluster": int(sub["assignments"].max()) if cluster_count else 0,
            "completion_per_cluster_mean": _safe_mean(sub["completions"].tolist()),
            "completion_per_cluster_p90": _safe_quantile(sub["completions"].tolist(), 0.90),
            "max_completions_per_cluster": int(sub["completions"].max()) if cluster_count else 0,
            "clusters_with_multi_assign_fraction": float((sub["assignments"] > 1).mean()) if cluster_count else float("nan"),
            "clusters_with_multi_completion_fraction": float((sub["completions"] > 1).mean()) if cluster_count else float("nan"),
            "redundant_assignment_fraction": float(sub["excess_assignments"].sum() / max(assignments_total, 1.0)),
            "redundant_completion_fraction": float(sub["excess_completions"].sum() / max(completions_total, 1.0)),
            "mean_cluster_completion_to_assignment_ratio": _safe_mean(sub["completion_to_assignment_ratio"].tolist()),
        }
    return cluster_df.sort_values(group_cols).reset_index(drop=True), summary


def _build_zone_summary(zone_df: pd.DataFrame) -> pd.DataFrame:
    zone_mode = (
        zone_df.groupby(["mode", "zone_idx"], as_index=False)
        .agg(
            detection_share_mean=("detection_share", "mean"),
            truth_share_mean=("truth_share", "mean"),
            assignment_share_mean=("new_direct_det_assignment_share", "mean"),
            completion_share_mean=("new_direct_det_completion_share", "mean"),
            active_share_mean=("active_direct_det_share", "mean"),
            assignment_detection_gap_mean=("assignment_detection_gap", "mean"),
            completion_detection_gap_mean=("completion_detection_gap", "mean"),
            active_detection_gap_mean=("active_detection_gap", "mean"),
            detection_count_mean=("detection_count", "mean"),
            assignment_count_mean=("new_direct_det_assignment_count", "mean"),
            completion_count_mean=("new_direct_det_completion_count", "mean"),
            active_count_mean=("active_direct_det_count_sum", "mean"),
        )
    )
    pred = zone_mode[zone_mode["mode"] == "prediction_only"].copy()
    prop = zone_mode[zone_mode["mode"] == "proposed_feedback_only"].copy()
    merged = pred.merge(prop, on="zone_idx", suffixes=("_pred", "_prop"))
    for base in [
        "detection_share_mean",
        "truth_share_mean",
        "assignment_share_mean",
        "completion_share_mean",
        "active_share_mean",
        "assignment_detection_gap_mean",
        "completion_detection_gap_mean",
        "active_detection_gap_mean",
        "detection_count_mean",
        "assignment_count_mean",
        "completion_count_mean",
        "active_count_mean",
    ]:
        merged[f"delta_{base}_prop_minus_pred"] = merged[f"{base}_prop"] - merged[f"{base}_pred"]
    return merged.sort_values("zone_idx").reset_index(drop=True)


def _plot_global_timeseries(global_df: pd.DataFrame, out_png: Path) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    for mode, sub in global_df.groupby("mode"):
        axes[0].plot(sub["t_bin_s"], sub["detection_count"], label=f"{mode} detections")
        axes[0].plot(sub["t_bin_s"], sub["new_direct_det_assignment_count"], ls="--", label=f"{mode} assignments")
        axes[1].plot(sub["t_bin_s"], sub["new_direct_det_completion_count"], label=f"{mode} completions")
        axes[1].plot(sub["t_bin_s"], sub["active_direct_det_count_sum"], ls="--", label=f"{mode} active burden")
        axes[2].plot(sub["t_bin_s"], sub["boundary_messages_sent"], label=f"{mode} boundary msgs")
        axes[2].plot(sub["t_bin_s"], sub["intervention_messages_sent"], ls="--", label=f"{mode} intervention msgs")
    axes[0].set_ylabel("Detections / assignments")
    axes[1].set_ylabel("Completions / active")
    axes[2].set_ylabel("Messages")
    axes[2].set_xlabel("time (s)")
    for ax in axes:
        ax.grid(alpha=0.25)
        ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _plot_zone_gap_bars(zone_df: pd.DataFrame, out_png: Path) -> None:
    z = zone_df["zone_idx"].to_numpy()
    w = 0.35
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    axes[0].bar(z - w / 2, zone_df["assignment_detection_gap_mean_pred"], width=w, label="prediction_only")
    axes[0].bar(z + w / 2, zone_df["assignment_detection_gap_mean_prop"], width=w, label="proposed_feedback_only")
    axes[0].set_ylabel("Assignment share - detection share")
    axes[0].grid(alpha=0.25)
    axes[0].legend(loc="best", fontsize=8)

    axes[1].bar(z - w / 2, zone_df["active_detection_gap_mean_pred"], width=w, label="prediction_only")
    axes[1].bar(z + w / 2, zone_df["active_detection_gap_mean_prop"], width=w, label="proposed_feedback_only")
    axes[1].set_ylabel("Active direct-det share - detection share")
    axes[1].set_xlabel("zone index")
    axes[1].grid(alpha=0.25)
    axes[1].legend(loc="best", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _plot_detection_message_scatter(global_df: pd.DataFrame, out_png: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharex=False, sharey=False)
    for mode, sub in global_df.groupby("mode"):
        axes[0].scatter(
            sub["detection_count"],
            sub["boundary_messages_sent"],
            s=24,
            alpha=0.75,
            label=mode,
        )
        axes[1].scatter(
            sub["detection_count"],
            sub["new_direct_det_assignment_count"],
            s=24,
            alpha=0.75,
            label=mode,
        )
    axes[0].set_xlabel("detections / bin")
    axes[0].set_ylabel("boundary messages / bin")
    axes[1].set_xlabel("detections / bin")
    axes[1].set_ylabel("reactive assignments / bin")
    for ax in axes:
        ax.grid(alpha=0.25)
        ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _plot_cluster_hist(cluster_df: pd.DataFrame, out_png: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for mode, sub in cluster_df.groupby("mode"):
        axes[0].hist(sub["assignments"], bins=np.arange(1, max(int(sub["assignments"].max()) + 2, 3)) - 0.5, alpha=0.6, label=mode)
        axes[1].hist(sub["completions"], bins=np.arange(0, max(int(sub["completions"].max()) + 2, 3)) - 0.5, alpha=0.6, label=mode)
    axes[0].set_xlabel("assignments per reactive cluster")
    axes[1].set_xlabel("completions per reactive cluster")
    axes[0].set_ylabel("cluster count")
    for ax in axes:
        ax.grid(alpha=0.25)
        ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare direct-detection reactive workload between prediction_only and feedback-only proposed runs."
    )
    parser.add_argument("--T-end", type=float, default=3 * 3600.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--bin-s", type=float, default=30.0)
    parser.add_argument("--task-replan-period-s", type=float, default=60.0)
    parser.add_argument("--patrol-hotspot-filter-mode", type=str, default="percentile")
    parser.add_argument("--patrol-hotspot-score-percentile", type=float, default=97.0)
    parser.add_argument("--alpha-inhib", type=float, default=0.45)
    parser.add_argument("--omega-inhib", type=float, default=600.0)
    parser.add_argument("--cluster-spatial-quant-m", type=float, default=20.0)
    parser.add_argument("--cluster-time-s", type=float, default=60.0)
    parser.add_argument("--outdir", type=str, default="results/diagnostic_feedback_reactive_pipeline")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    run_params = {
        "T_end": float(args.T_end),
        "dt": float(args.dt),
        "seed": int(args.seed),
        "W": 500.0,
        "H": 500.0,
        "NX": 80,
        "NY": 64,
        "Nrobots": 6,
        "uav_fraction": 0.0,
        "warmup_s": 1800.0,
        "task_replan_period_s": float(args.task_replan_period_s),
        "patrol_hotspot_filter_mode": str(args.patrol_hotspot_filter_mode),
        "patrol_hotspot_score_percentile": float(args.patrol_hotspot_score_percentile),
        "alpha_inhib": float(args.alpha_inhib),
        "omega_inhib": float(args.omega_inhib),
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
    }

    pred = _collect_reactive_run(
        label="prediction_only",
        sim_mode="prediction_only",
        run_params=run_params,
        overrides={"enable_intervention_feedback": False, "enable_model_scored_deterring": False},
        bin_s=float(args.bin_s),
    )
    prop = _collect_reactive_run(
        label="proposed_feedback_only",
        sim_mode="proposed",
        run_params=run_params,
        overrides={"enable_intervention_feedback": True, "enable_model_scored_deterring": False},
        bin_s=float(args.bin_s),
    )

    zone_df = _add_share_columns(pd.concat([pred["zone_df"], prop["zone_df"]], ignore_index=True))
    global_df = pd.concat([pred["global_df"], prop["global_df"]], ignore_index=True).sort_values(["mode", "t_bin_s"])
    assign_df = pd.concat([pred["assign_df"], prop["assign_df"]], ignore_index=True)
    done_df = pd.concat([pred["done_df"], prop["done_df"]], ignore_index=True)

    zone_df.to_csv(outdir / "feedback_reactive_pipeline_per_time_zone.csv", index=False)
    global_df.to_csv(outdir / "feedback_reactive_pipeline_global_timeseries.csv", index=False)
    assign_df.to_csv(outdir / "feedback_reactive_pipeline_assignments.csv", index=False)
    done_df.to_csv(outdir / "feedback_reactive_pipeline_completions.csv", index=False)

    mode_summary = _summarize_mode(zone_df, global_df, assign_df, done_df)
    cluster_df, cluster_summary = _build_cluster_tables(
        assign_df,
        done_df,
        spatial_quant_m=float(args.cluster_spatial_quant_m),
        time_quant_s=float(args.cluster_time_s),
    )
    cluster_df.to_csv(outdir / "feedback_reactive_pipeline_cluster_summary.csv", index=False)
    zone_summary_df = _build_zone_summary(zone_df)
    zone_summary_df.to_csv(outdir / "feedback_reactive_pipeline_zone_summary.csv", index=False)

    worst_assign = (
        zone_summary_df.sort_values("delta_assignment_detection_gap_mean_prop_minus_pred")
        .head(min(3, len(zone_summary_df)))
        [[
            "zone_idx",
            "delta_assignment_detection_gap_mean_prop_minus_pred",
            "detection_share_mean_pred",
            "detection_share_mean_prop",
            "assignment_share_mean_pred",
            "assignment_share_mean_prop",
        ]]
        .to_dict(orient="records")
    )
    worst_active = (
        zone_summary_df.sort_values("delta_active_detection_gap_mean_prop_minus_pred")
        .head(min(3, len(zone_summary_df)))
        [[
            "zone_idx",
            "delta_active_detection_gap_mean_prop_minus_pred",
            "detection_share_mean_pred",
            "detection_share_mean_prop",
            "active_share_mean_pred",
            "active_share_mean_prop",
        ]]
        .to_dict(orient="records")
    )

    summary = {
        "parameters": run_params
        | {
            "bin_s": float(args.bin_s),
            "cluster_spatial_quant_m": float(args.cluster_spatial_quant_m),
            "cluster_time_s": float(args.cluster_time_s),
        },
        "mode_summary": mode_summary,
        "cluster_summary": cluster_summary,
        "prediction_only_final_metrics": pred["final_metrics"],
        "proposed_feedback_only_final_metrics": prop["final_metrics"],
        "worst_assignment_gap_zones": worst_assign,
        "worst_active_gap_zones": worst_active,
    }

    conclusions = []
    pred_mode = mode_summary["prediction_only"]
    prop_mode = mode_summary["proposed_feedback_only"]
    if prop_mode["boundary_messages_per_detection"] > pred_mode["boundary_messages_per_detection"]:
        conclusions.append("Feedback increases boundary-message overhead per detection.")
    if prop_mode["assignment_detection_l1_mean"] > pred_mode["assignment_detection_l1_mean"]:
        conclusions.append("Feedback worsens the spatial match between direct-detection assignments and detections.")
    if prop_mode["active_detection_l1_mean"] > pred_mode["active_detection_l1_mean"]:
        conclusions.append("Feedback worsens the spatial match between active direct-detection workload and detections.")
    if prop_mode["mean_completion_lag_s"] > pred_mode["mean_completion_lag_s"]:
        conclusions.append("Feedback increases reactive completion lag.")
    pred_cluster = cluster_summary.get("prediction_only", {})
    prop_cluster = cluster_summary.get("proposed_feedback_only", {})
    if (
        np.isfinite(float(pred_cluster.get("redundant_assignment_fraction", float("nan"))))
        and np.isfinite(float(prop_cluster.get("redundant_assignment_fraction", float("nan"))))
        and float(prop_cluster.get("redundant_assignment_fraction", 0.0))
        > float(pred_cluster.get("redundant_assignment_fraction", 0.0))
    ):
        conclusions.append("Feedback increases clustered redundant reactive assignments.")
    if (
        np.isfinite(float(pred_mode.get("boundary_message_fano", float("nan"))))
        and np.isfinite(float(prop_mode.get("boundary_message_fano", float("nan"))))
        and float(prop_mode.get("boundary_message_fano", 0.0))
        > float(pred_mode.get("boundary_message_fano", 0.0))
    ):
        conclusions.append("Feedback makes boundary-message traffic burstier.")
    if not conclusions:
        conclusions.append("This diagnostic does not show a clear reactive-pipeline regression under feedback.")
    summary["conclusions"] = conclusions

    with open(outdir / "feedback_reactive_pipeline_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with open(outdir / "feedback_reactive_pipeline_report.md", "w", encoding="utf-8") as f:
        f.write("# Feedback Reactive Pipeline Diagnostic\n\n")
        f.write("## Parameters\n\n")
        for k, v in summary["parameters"].items():
            f.write(f"- `{k}`: `{v}`\n")
        f.write("\n## Mode Summary\n\n")
        for mode, vals in mode_summary.items():
            f.write(f"### {mode}\n\n")
            for k, v in vals.items():
                f.write(f"- `{k}`: `{v}`\n")
            f.write("\n")
        f.write("## Reactive Cluster Summary\n\n")
        for mode, vals in cluster_summary.items():
            f.write(f"### {mode}\n\n")
            for k, v in vals.items():
                f.write(f"- `{k}`: `{v}`\n")
            f.write("\n")
        f.write("## Worst Assignment-Gap Zones\n\n")
        for row in worst_assign:
            f.write(f"- zone `{row['zone_idx']}`: `{row}`\n")
        f.write("\n## Worst Active-Gap Zones\n\n")
        for row in worst_active:
            f.write(f"- zone `{row['zone_idx']}`: `{row}`\n")
        f.write("\n## Final Production Metrics\n\n")
        f.write("### prediction_only\n\n")
        for k, v in pred["final_metrics"].items():
            f.write(f"- `{k}`: `{v}`\n")
        f.write("\n### proposed_feedback_only\n\n")
        for k, v in prop["final_metrics"].items():
            f.write(f"- `{k}`: `{v}`\n")
        f.write("\n## Conclusions\n\n")
        for line in conclusions:
            f.write(f"- {line}\n")

    _plot_global_timeseries(global_df, outdir / "feedback_reactive_pipeline_timeseries.png")
    _plot_zone_gap_bars(zone_summary_df, outdir / "feedback_reactive_pipeline_zone_gaps.png")
    _plot_detection_message_scatter(global_df, outdir / "feedback_reactive_pipeline_detection_scatter.png")
    if not cluster_df.empty:
        _plot_cluster_hist(cluster_df, outdir / "feedback_reactive_pipeline_cluster_hist.png")
    print(f"[done] feedback reactive pipeline saved to: {outdir}")


if __name__ == "__main__":
    main()
