from __future__ import annotations

import argparse
import json
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


def _collect_workload_frames(label: str, sim_mode: str, run_params: dict, overrides: dict, sample_every_s: float):
    frames = ds.run_simulation_frames_persistent(
        simulation_mode=sim_mode,
        report_metrics_end=False,
        **run_params,
        **overrides,
    )
    sampled = {}
    next_sample_t = -1e9
    first = None
    last = None
    for snap in frames:
        if first is None:
            first = snap
        last = snap
        t_s = float(snap.get("t", 0.0))
        if t_s < next_sample_t:
            continue
        next_sample_t = t_s + float(sample_every_s)
        sampled[int(round(t_s))] = {
            "t_s": t_s,
            "poses": dict(snap.get("poses", {})),
            "robot_states": dict(snap.get("robot_states", {})),
            "tasks_active": list(snap.get("tasks_active", [])),
            "truth_pts": list(snap.get("truth_pts", [])),
            "det_pts": list(snap.get("det_pts", [])),
            "metrics": dict(snap.get("metrics", {})),
        }
    return {
        "label": label,
        "cells": list((first or {}).get("cells", [])),
        "sampled": sampled,
        "final_metrics": dict((last or {}).get("metrics", {})),
    }


def _allocation_rows(mode_label: str, sample_dict: dict, cells) -> list[dict]:
    zone_count = int(len(cells))
    rows = []
    for t_key in sorted(sample_dict.keys()):
        snap = sample_dict[t_key]
        robot_count = [0] * zone_count
        moving_count = [0] * zone_count
        idle_count = [0] * zone_count
        holding_count = [0] * zone_count
        patrol_active_count = [0] * zone_count
        deterring_active_count = [0] * zone_count
        truth_count = [0] * zone_count
        detection_count = [0] * zone_count

        for rid, pos in snap["poses"].items():
            try:
                x, y = pos
                z = _point_to_zone(float(x), float(y), cells)
            except Exception:
                continue
            robot_count[z] += 1
            state = str(snap["robot_states"].get(rid, "")).strip().lower()
            if state == "moving":
                moving_count[z] += 1
            elif state == "holding":
                holding_count[z] += 1
            else:
                idle_count[z] += 1

        for tr in snap["tasks_active"]:
            if str(tr.get("state", "")).strip().lower() != "active":
                continue
            try:
                z = _point_to_zone(float(tr.get("x", 0.0)), float(tr.get("y", 0.0)), cells)
            except Exception:
                continue
            ttype = str(tr.get("type", "")).strip().lower()
            if ttype == "patrolling":
                patrol_active_count[z] += 1
            elif ttype == "deterring":
                deterring_active_count[z] += 1

        for x, y in snap["truth_pts"]:
            z = _point_to_zone(float(x), float(y), cells)
            truth_count[z] += 1
        for x, y in snap["det_pts"]:
            z = _point_to_zone(float(x), float(y), cells)
            detection_count[z] += 1

        for zi in range(zone_count):
            rows.append(
                {
                    "mode": mode_label,
                    "t_s": float(snap["t_s"]),
                    "zone_idx": int(zi),
                    "robot_count": int(robot_count[zi]),
                    "moving_count": int(moving_count[zi]),
                    "idle_count": int(idle_count[zi]),
                    "holding_count": int(holding_count[zi]),
                    "patrol_active_count": int(patrol_active_count[zi]),
                    "deterring_active_count": int(deterring_active_count[zi]),
                    "truth_count": int(truth_count[zi]),
                    "detection_count": int(detection_count[zi]),
                }
            )
    return rows


def _add_share_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in [
        "robot_count",
        "moving_count",
        "idle_count",
        "holding_count",
        "patrol_active_count",
        "deterring_active_count",
        "truth_count",
        "detection_count",
    ]:
        total_col = f"{col}_total"
        share_col = col.replace("_count", "_share")
        totals = out.groupby(["mode", "t_s"])[col].transform("sum").astype(float)
        out[total_col] = totals
        out[share_col] = np.where(totals > 0.0, out[col].astype(float) / totals, 0.0)

    out["robot_truth_l1_component"] = np.abs(out["robot_share"] - out["truth_share"])
    out["patrol_truth_l1_component"] = np.abs(out["patrol_active_share"] - out["truth_share"])
    out["deterring_detection_l1_component"] = np.abs(out["deterring_active_share"] - out["detection_share"])
    out["robot_truth_gap"] = out["robot_share"] - out["truth_share"]
    out["patrol_truth_gap"] = out["patrol_active_share"] - out["truth_share"]
    out["deterring_detection_gap"] = out["deterring_active_share"] - out["detection_share"]
    return out


def _summarize_mode(df: pd.DataFrame) -> dict:
    per_t = (
        df.groupby(["mode", "t_s"], as_index=False)
        .agg(
            robot_truth_l1=("robot_truth_l1_component", lambda s: 0.5 * float(np.sum(s))),
            patrol_truth_l1=("patrol_truth_l1_component", lambda s: 0.5 * float(np.sum(s))),
            deterring_detection_l1=("deterring_detection_l1_component", lambda s: 0.5 * float(np.sum(s))),
        )
    )

    mode_summary = {}
    for mode in sorted(df["mode"].unique()):
        sub = df[df["mode"] == mode]
        sub_t = per_t[per_t["mode"] == mode]
        mode_summary[mode] = {
            "robot_truth_l1_mean": _safe_mean(sub_t["robot_truth_l1"].tolist()),
            "patrol_truth_l1_mean": _safe_mean(sub_t["patrol_truth_l1"].tolist()),
            "deterring_detection_l1_mean": _safe_mean(sub_t["deterring_detection_l1"].tolist()),
            "fleet_moving_fraction_mean": _safe_mean(
                (
                    sub.groupby("t_s")["moving_count"].sum().astype(float)
                    / np.maximum(sub.groupby("t_s")["robot_count"].sum().astype(float), 1.0)
                ).tolist()
            ),
            "fleet_idle_fraction_mean": _safe_mean(
                (
                    sub.groupby("t_s")["idle_count"].sum().astype(float)
                    / np.maximum(sub.groupby("t_s")["robot_count"].sum().astype(float), 1.0)
                ).tolist()
            ),
            "fleet_holding_fraction_mean": _safe_mean(
                (
                    sub.groupby("t_s")["holding_count"].sum().astype(float)
                    / np.maximum(sub.groupby("t_s")["robot_count"].sum().astype(float), 1.0)
                ).tolist()
            ),
        }
    return mode_summary


def _build_zone_summary(df: pd.DataFrame) -> pd.DataFrame:
    zone_mode = (
        df.groupby(["mode", "zone_idx"], as_index=False)
        .agg(
            robot_share_mean=("robot_share", "mean"),
            patrol_share_mean=("patrol_active_share", "mean"),
            deterring_share_mean=("deterring_active_share", "mean"),
            truth_share_mean=("truth_share", "mean"),
            detection_share_mean=("detection_share", "mean"),
            robot_truth_gap_mean=("robot_truth_gap", "mean"),
            patrol_truth_gap_mean=("patrol_truth_gap", "mean"),
            deterring_detection_gap_mean=("deterring_detection_gap", "mean"),
            robot_count_mean=("robot_count", "mean"),
            patrol_active_count_mean=("patrol_active_count", "mean"),
            deterring_active_count_mean=("deterring_active_count", "mean"),
            truth_count_mean=("truth_count", "mean"),
            detection_count_mean=("detection_count", "mean"),
        )
    )
    pred = zone_mode[zone_mode["mode"] == "prediction_only"].copy()
    prop = zone_mode[zone_mode["mode"] == "proposed_feedback_only"].copy()
    merged = pred.merge(prop, on="zone_idx", suffixes=("_pred", "_prop"))
    for base in [
        "robot_share_mean",
        "patrol_share_mean",
        "deterring_share_mean",
        "truth_share_mean",
        "detection_share_mean",
        "robot_truth_gap_mean",
        "patrol_truth_gap_mean",
        "deterring_detection_gap_mean",
        "robot_count_mean",
        "patrol_active_count_mean",
        "deterring_active_count_mean",
        "truth_count_mean",
        "detection_count_mean",
    ]:
        merged[f"delta_{base}_prop_minus_pred"] = merged[f"{base}_prop"] - merged[f"{base}_pred"]
    return merged.sort_values("zone_idx").reset_index(drop=True)


def _plot_l1_timeseries(df: pd.DataFrame, out_png: Path) -> None:
    per_t = (
        df.groupby(["mode", "t_s"], as_index=False)
        .agg(
            robot_truth_l1=("robot_truth_l1_component", lambda s: 0.5 * float(np.sum(s))),
            patrol_truth_l1=("patrol_truth_l1_component", lambda s: 0.5 * float(np.sum(s))),
            deterring_detection_l1=("deterring_detection_l1_component", lambda s: 0.5 * float(np.sum(s))),
        )
    )
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    for mode, sub in per_t.groupby("mode"):
        axes[0].plot(sub["t_s"], sub["robot_truth_l1"], label=mode)
        axes[1].plot(sub["t_s"], sub["patrol_truth_l1"], label=mode)
        axes[2].plot(sub["t_s"], sub["deterring_detection_l1"], label=mode)
    axes[0].set_ylabel("Robot vs truth L1")
    axes[1].set_ylabel("Patrol vs truth L1")
    axes[2].set_ylabel("Deterring vs detection L1")
    axes[2].set_xlabel("time (s)")
    for ax in axes:
        ax.grid(alpha=0.25)
        ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _plot_zone_gap_bars(zone_df: pd.DataFrame, out_png: Path) -> None:
    z = zone_df["zone_idx"].to_numpy()
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    w = 0.35
    axes[0].bar(z - w / 2, zone_df["patrol_truth_gap_mean_pred"], width=w, label="prediction_only")
    axes[0].bar(z + w / 2, zone_df["patrol_truth_gap_mean_prop"], width=w, label="proposed_feedback_only")
    axes[0].set_ylabel("Patrol share - truth share")
    axes[0].grid(alpha=0.25)
    axes[0].legend(loc="best", fontsize=8)

    axes[1].bar(z - w / 2, zone_df["robot_truth_gap_mean_pred"], width=w, label="prediction_only")
    axes[1].bar(z + w / 2, zone_df["robot_truth_gap_mean_prop"], width=w, label="proposed_feedback_only")
    axes[1].set_ylabel("Robot share - truth share")
    axes[1].set_xlabel("zone index")
    axes[1].grid(alpha=0.25)
    axes[1].legend(loc="best", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare spatiotemporal workload allocation between prediction_only and feedback-only proposed runs."
    )
    parser.add_argument("--T-end", type=float, default=3 * 3600.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--sample-every-s", type=float, default=30.0)
    parser.add_argument("--task-replan-period-s", type=float, default=60.0)
    parser.add_argument("--patrol-hotspot-filter-mode", type=str, default="percentile")
    parser.add_argument("--patrol-hotspot-score-percentile", type=float, default=97.0)
    parser.add_argument("--alpha-inhib", type=float, default=0.45)
    parser.add_argument("--omega-inhib", type=float, default=600.0)
    parser.add_argument("--outdir", type=str, default="results/diagnostic_feedback_workload_allocation")
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

    pred = _collect_workload_frames(
        label="prediction_only",
        sim_mode="prediction_only",
        run_params=run_params,
        overrides={"enable_intervention_feedback": False, "enable_model_scored_deterring": False},
        sample_every_s=float(args.sample_every_s),
    )
    prop = _collect_workload_frames(
        label="proposed_feedback_only",
        sim_mode="proposed",
        run_params=run_params,
        overrides={"enable_intervention_feedback": True, "enable_model_scored_deterring": False},
        sample_every_s=float(args.sample_every_s),
    )

    cells = pred["cells"]
    pred_rows = _allocation_rows("prediction_only", pred["sampled"], cells)
    prop_rows = _allocation_rows("proposed_feedback_only", prop["sampled"], cells)
    alloc_df = _add_share_columns(pd.DataFrame(pred_rows + prop_rows))
    alloc_df.to_csv(outdir / "feedback_workload_allocation_per_time_zone.csv", index=False)

    mode_summary = _summarize_mode(alloc_df)
    zone_summary_df = _build_zone_summary(alloc_df)
    zone_summary_df.to_csv(outdir / "feedback_workload_allocation_zone_summary.csv", index=False)

    worst_patrol = (
        zone_summary_df.sort_values("delta_patrol_truth_gap_mean_prop_minus_pred")
        .head(min(3, len(zone_summary_df)))
        [["zone_idx", "delta_patrol_truth_gap_mean_prop_minus_pred", "truth_share_mean_pred", "truth_share_mean_prop", "patrol_share_mean_pred", "patrol_share_mean_prop"]]
        .to_dict(orient="records")
    )
    worst_robot = (
        zone_summary_df.sort_values("delta_robot_truth_gap_mean_prop_minus_pred")
        .head(min(3, len(zone_summary_df)))
        [["zone_idx", "delta_robot_truth_gap_mean_prop_minus_pred", "truth_share_mean_pred", "truth_share_mean_prop", "robot_share_mean_pred", "robot_share_mean_prop"]]
        .to_dict(orient="records")
    )

    summary = {
        "parameters": run_params,
        "mode_summary": mode_summary,
        "prediction_only_final_metrics": pred["final_metrics"],
        "proposed_feedback_only_final_metrics": prop["final_metrics"],
        "worst_patrol_gap_zones": worst_patrol,
        "worst_robot_gap_zones": worst_robot,
    }

    conclusions = []
    pred_patrol_l1 = float(mode_summary["prediction_only"]["patrol_truth_l1_mean"])
    prop_patrol_l1 = float(mode_summary["proposed_feedback_only"]["patrol_truth_l1_mean"])
    pred_robot_l1 = float(mode_summary["prediction_only"]["robot_truth_l1_mean"])
    prop_robot_l1 = float(mode_summary["proposed_feedback_only"]["robot_truth_l1_mean"])
    if prop_patrol_l1 > pred_patrol_l1:
        conclusions.append("Feedback increases patrol-vs-truth allocation error across zones.")
    if prop_robot_l1 > pred_robot_l1:
        conclusions.append("Feedback increases robot-presence-vs-truth allocation error across zones.")
    if float(mode_summary["proposed_feedback_only"]["deterring_detection_l1_mean"]) > float(mode_summary["prediction_only"]["deterring_detection_l1_mean"]):
        conclusions.append("Feedback increases deterring-vs-detection allocation error across zones.")
    if not conclusions:
        conclusions.append("This diagnostic does not show a clear zone-level allocation regression under feedback.")
    summary["conclusions"] = conclusions

    with open(outdir / "feedback_workload_allocation_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with open(outdir / "feedback_workload_allocation_report.md", "w", encoding="utf-8") as f:
        f.write("# Feedback Workload Allocation Diagnostic\n\n")
        f.write("## Parameters\n\n")
        for k, v in run_params.items():
            f.write(f"- `{k}`: `{v}`\n")
        f.write("\n## Mode Summary\n\n")
        for mode, vals in mode_summary.items():
            f.write(f"### {mode}\n\n")
            for k, v in vals.items():
                f.write(f"- `{k}`: `{v}`\n")
            f.write("\n")
        f.write("## Worst Patrol-Gap Zones\n\n")
        for row in worst_patrol:
            f.write(f"- zone `{row['zone_idx']}`: `{row}`\n")
        f.write("\n## Worst Robot-Gap Zones\n\n")
        for row in worst_robot:
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

    _plot_l1_timeseries(alloc_df, outdir / "feedback_workload_allocation_l1_timeseries.png")
    _plot_zone_gap_bars(zone_summary_df, outdir / "feedback_workload_allocation_zone_gaps.png")
    print(f"[done] feedback workload allocation saved to: {outdir}")


if __name__ == "__main__":
    main()
