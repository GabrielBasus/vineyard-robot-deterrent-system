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


def _safe_std(vals) -> float:
    arr = [float(v) for v in vals if np.isfinite(float(v))]
    return float(np.std(arr)) if arr else float("nan")


def _corr(a, b) -> float:
    aa = np.asarray(a, dtype=float)
    bb = np.asarray(b, dtype=float)
    mask = np.isfinite(aa) & np.isfinite(bb)
    aa = aa[mask]
    bb = bb[mask]
    if aa.size < 2:
        return float("nan")
    if np.std(aa) <= 1e-12 or np.std(bb) <= 1e-12:
        return float("nan")
    return float(np.corrcoef(aa, bb)[0, 1])


def _poly_area(poly) -> float:
    if not poly:
        return 0.0
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += float(x1) * float(y2) - float(x2) * float(y1)
    return abs(0.5 * s)


def _mode_overrides(mode_suite: str) -> tuple[str, dict]:
    key = str(mode_suite).strip().lower()
    if key == "prediction_only":
        return "prediction_only", {
            "enable_intervention_feedback": False,
            "enable_model_scored_deterring": False,
        }
    if key == "proposed_feedback_only":
        return "proposed", {
            "enable_intervention_feedback": True,
            "enable_model_scored_deterring": False,
        }
    if key == "proposed_no_feedback":
        return "proposed", {
            "enable_intervention_feedback": False,
            "enable_model_scored_deterring": False,
        }
    raise ValueError(f"Unsupported mode suite: {mode_suite}")


def _partition_variants(scale: float, gamma: float):
    return [
        {
            "partition_label": "weighted_current",
            "mode": "direct",
            "scale": float(scale),
            "gamma": float(gamma),
        },
        {
            "partition_label": "neutral_voronoi",
            "mode": "direct",
            "scale": 0.0,
            "gamma": float(gamma),
        },
    ]


def _run_case(sim_mode: str, overrides: dict, run_params: dict):
    frames = ds.run_simulation_frames_persistent(
        simulation_mode=sim_mode,
        report_metrics_end=False,
        **run_params,
        **overrides,
    )
    first = None
    last = None
    for snap in frames:
        if first is None:
            first = snap
        last = snap
    if first is None or last is None:
        raise RuntimeError("Simulation produced no frames")
    return first, last


def _extract_case_row(run_idx: int, seed: int, mode_label: str, partition_label: str, first: dict, last: dict, run_params: dict) -> dict:
    profiles = first.get("profiles", {})
    ugv_ids = [rid for rid, prof in profiles.items() if getattr(prof, "type", None) == "UGV"]
    cells = list(first.get("cells", []))
    zone_areas = [_poly_area(poly) for poly in cells]
    zone_area_mean = _safe_mean(zone_areas)
    zone_area_std = _safe_std(zone_areas)
    zone_area_cv = float(zone_area_std / max(zone_area_mean, 1e-12)) if zone_areas else float("nan")
    ugv_healths = [float(getattr(profiles[rid], "health", float("nan"))) for rid in ugv_ids[: len(zone_areas)]]

    metrics = dict(last.get("metrics", {}))
    util = dict(metrics.get("robot_task_utilization_by_robot", {}))
    idle = dict(metrics.get("robot_idle_fraction_by_robot", {}))
    ugv_util = [float(util[rid]) for rid in ugv_ids if rid in util]
    ugv_idle = [float(idle[rid]) for rid in ugv_ids if rid in idle]

    row = {
        "run_idx": int(run_idx),
        "seed": int(seed),
        "mode_label": str(mode_label),
        "partition_label": str(partition_label),
        "partition_mode": str(run_params["mode"]),
        "partition_scale": float(run_params["scale"]),
        "partition_gamma": float(run_params["gamma"]),
        "value_weighted_exposure": float(metrics.get("value_weighted_exposure", float("nan"))),
        "mean_response_time_s": float(metrics.get("mean_response_time_s", float("nan"))),
        "boundary_message_count": float(metrics.get("boundary_message_count", float("nan"))),
        "completed_tasks_total": float(metrics.get("completed_tasks_total", float("nan"))),
        "deterring_actions_completed_total": float(metrics.get("deterring_actions_completed_total", float("nan"))),
        "deterring_actions_completed_direct_detection": float(metrics.get("deterring_actions_completed_direct_detection", float("nan"))),
        "fleet_task_engagement_fraction_so_far": float(metrics.get("fleet_task_engagement_fraction_so_far", float("nan"))),
        "fleet_moving_fraction_so_far": float(metrics.get("fleet_moving_fraction_so_far", float("nan"))),
        "fleet_idle_no_task_fraction_so_far": float(metrics.get("fleet_idle_no_task_fraction_so_far", float("nan"))),
        "robot_task_utilization_mean": _safe_mean(ugv_util),
        "robot_task_utilization_std": _safe_std(ugv_util),
        "robot_idle_fraction_mean": _safe_mean(ugv_idle),
        "robot_idle_fraction_std": _safe_std(ugv_idle),
        "zone_count": int(len(zone_areas)),
        "zone_area_mean": zone_area_mean,
        "zone_area_std": zone_area_std,
        "zone_area_cv": zone_area_cv,
        "zone_area_min": float(np.min(zone_areas)) if zone_areas else float("nan"),
        "zone_area_max": float(np.max(zone_areas)) if zone_areas else float("nan"),
        "zone_area_health_corr": _corr(zone_areas, ugv_healths),
        "zone_area_util_corr": _corr(zone_areas, ugv_util[: len(zone_areas)]),
        "zone_area_idle_corr": _corr(zone_areas, ugv_idle[: len(zone_areas)]),
    }
    return row


def _paired_compare(case_df: pd.DataFrame) -> pd.DataFrame:
    weighted = case_df[case_df["partition_label"] == "weighted_current"].copy()
    neutral = case_df[case_df["partition_label"] == "neutral_voronoi"].copy()
    merged = weighted.merge(neutral, on=["run_idx", "seed", "mode_label"], suffixes=("_weighted", "_neutral"))
    merged["exposure_improve_pct_weighted_vs_neutral"] = 100.0 * (
        merged["value_weighted_exposure_neutral"] - merged["value_weighted_exposure_weighted"]
    ) / np.maximum(merged["value_weighted_exposure_neutral"], 1e-12)
    merged["response_improve_pct_weighted_vs_neutral"] = 100.0 * (
        merged["mean_response_time_s_neutral"] - merged["mean_response_time_s_weighted"]
    ) / np.maximum(merged["mean_response_time_s_neutral"], 1e-12)
    merged["comm_increase_pct_weighted_vs_neutral"] = 100.0 * (
        merged["boundary_message_count_weighted"] - merged["boundary_message_count_neutral"]
    ) / np.maximum(merged["boundary_message_count_neutral"], 1e-12)
    merged["delta_zone_area_cv_weighted_minus_neutral"] = (
        merged["zone_area_cv_weighted"] - merged["zone_area_cv_neutral"]
    )
    merged["delta_robot_util_std_weighted_minus_neutral"] = (
        merged["robot_task_utilization_std_weighted"] - merged["robot_task_utilization_std_neutral"]
    )
    return merged


def _summary_by_mode(paired_df: pd.DataFrame) -> dict:
    out = {}
    for mode, sub in paired_df.groupby("mode_label"):
        exp = sub["exposure_improve_pct_weighted_vs_neutral"].to_numpy(dtype=float)
        resp = sub["response_improve_pct_weighted_vs_neutral"].to_numpy(dtype=float)
        comm = sub["comm_increase_pct_weighted_vs_neutral"].to_numpy(dtype=float)
        area = sub["delta_zone_area_cv_weighted_minus_neutral"].to_numpy(dtype=float)
        util = sub["delta_robot_util_std_weighted_minus_neutral"].to_numpy(dtype=float)
        out[str(mode)] = {
            "runs": int(len(sub)),
            "exposure_improve_pct_mean": _safe_mean(exp.tolist()),
            "exposure_improve_pct_std": _safe_std(exp.tolist()),
            "response_improve_pct_mean": _safe_mean(resp.tolist()),
            "response_improve_pct_std": _safe_std(resp.tolist()),
            "comm_increase_pct_mean": _safe_mean(comm.tolist()),
            "delta_zone_area_cv_mean": _safe_mean(area.tolist()),
            "delta_robot_util_std_mean": _safe_mean(util.tolist()),
            "weighted_better_on_exposure_runs": int(np.sum(exp > 0.0)),
            "weighted_better_on_response_runs": int(np.sum(resp > 0.0)),
        }
    return out


def _plot_paired_deltas(paired_df: pd.DataFrame, out_png: Path) -> None:
    modes = list(paired_df["mode_label"].unique())
    fig, axes = plt.subplots(len(modes), 2, figsize=(12, 4 * max(len(modes), 1)), squeeze=False)
    for row_i, mode in enumerate(modes):
        sub = paired_df[paired_df["mode_label"] == mode].sort_values("seed")
        x = np.arange(len(sub))
        axes[row_i, 0].bar(x, sub["exposure_improve_pct_weighted_vs_neutral"], label="Exposure")
        axes[row_i, 0].bar(x, sub["response_improve_pct_weighted_vs_neutral"], alpha=0.6, label="Response")
        axes[row_i, 0].axhline(0.0, color="gray", ls="--")
        axes[row_i, 0].set_title(f"{mode}: weighted vs neutral improvements")
        axes[row_i, 0].set_ylabel("improvement %")
        axes[row_i, 0].set_xticks(x)
        axes[row_i, 0].set_xticklabels([str(int(s)) for s in sub["seed"]], rotation=45)
        axes[row_i, 0].grid(alpha=0.25)
        axes[row_i, 0].legend(loc="best", fontsize=8)

        axes[row_i, 1].scatter(sub["delta_zone_area_cv_weighted_minus_neutral"], sub["exposure_improve_pct_weighted_vs_neutral"])
        axes[row_i, 1].set_title(f"{mode}: zone imbalance vs exposure delta")
        axes[row_i, 1].set_xlabel("delta zone area CV")
        axes[row_i, 1].set_ylabel("exposure improvement %")
        axes[row_i, 1].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ablation diagnostic for zone partitioning: compare current weighted zones against neutral Voronoi zones."
    )
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--seed-start", type=int, default=2026)
    parser.add_argument(
        "--mode-suite",
        type=str,
        default="both",
        choices=["both", "prediction_only", "proposed_feedback_only", "proposed_no_feedback"],
    )
    parser.add_argument("--T-end", type=float, default=3 * 3600.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--Nrobots", type=int, default=6)
    parser.add_argument("--uav-fraction", type=float, default=0.0)
    parser.add_argument("--warmup-s", type=float, default=1800.0)
    parser.add_argument("--task-replan-period-s", type=float, default=60.0)
    parser.add_argument("--patrol-hotspot-filter-mode", type=str, default="percentile")
    parser.add_argument("--patrol-hotspot-score-percentile", type=float, default=97.0)
    parser.add_argument("--alpha-inhib", type=float, default=0.45)
    parser.add_argument("--omega-inhib", type=float, default=600.0)
    parser.add_argument("--partition-scale", type=float, default=1500.0)
    parser.add_argument("--partition-gamma", type=float, default=1.0)
    parser.add_argument("--outdir", type=str, default="results/diagnostic_zone_partitioning_ablation")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    suites = ["prediction_only", "proposed_feedback_only"] if args.mode_suite == "both" else [args.mode_suite]
    case_rows = []

    common_run = {
        "T_end": float(args.T_end),
        "dt": float(args.dt),
        "Nrobots": int(args.Nrobots),
        "uav_fraction": float(args.uav_fraction),
        "warmup_s": float(args.warmup_s),
        "task_replan_period_s": float(args.task_replan_period_s),
        "patrol_hotspot_filter_mode": str(args.patrol_hotspot_filter_mode),
        "patrol_hotspot_score_percentile": float(args.patrol_hotspot_score_percentile),
        "alpha_inhib": float(args.alpha_inhib),
        "omega_inhib": float(args.omega_inhib),
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
        "W": 500.0,
        "H": 500.0,
        "NX": 80,
        "NY": 64,
    }

    for run_idx in range(int(args.runs)):
        seed = int(args.seed_start) + run_idx
        for mode_suite in suites:
            sim_mode, overrides = _mode_overrides(mode_suite)
            for variant in _partition_variants(float(args.partition_scale), float(args.partition_gamma)):
                run_params = dict(common_run)
                run_params["seed"] = int(seed)
                run_params["mode"] = variant["mode"]
                run_params["scale"] = float(variant["scale"])
                run_params["gamma"] = float(variant["gamma"])
                first, last = _run_case(sim_mode=sim_mode, overrides=overrides, run_params=run_params)
                case_rows.append(
                    _extract_case_row(
                        run_idx=run_idx,
                        seed=seed,
                        mode_label=mode_suite,
                        partition_label=variant["partition_label"],
                        first=first,
                        last=last,
                        run_params=run_params,
                    )
                )

    case_df = pd.DataFrame(case_rows)
    case_df.to_csv(outdir / "zone_partitioning_ablation_per_case.csv", index=False)
    paired_df = _paired_compare(case_df)
    paired_df.to_csv(outdir / "zone_partitioning_ablation_paired.csv", index=False)
    summary = {
        "parameters": {
            "runs": int(args.runs),
            "seed_start": int(args.seed_start),
            "mode_suite": str(args.mode_suite),
            "T_end": float(args.T_end),
            "dt": float(args.dt),
            "Nrobots": int(args.Nrobots),
            "uav_fraction": float(args.uav_fraction),
            "warmup_s": float(args.warmup_s),
            "task_replan_period_s": float(args.task_replan_period_s),
            "patrol_hotspot_filter_mode": str(args.patrol_hotspot_filter_mode),
            "patrol_hotspot_score_percentile": float(args.patrol_hotspot_score_percentile),
            "alpha_inhib": float(args.alpha_inhib),
            "omega_inhib": float(args.omega_inhib),
            "partition_scale": float(args.partition_scale),
            "partition_gamma": float(args.partition_gamma),
        },
        "summary_by_mode": _summary_by_mode(paired_df),
    }

    conclusions = []
    for mode, vals in summary["summary_by_mode"].items():
        exp = float(vals["exposure_improve_pct_mean"])
        resp = float(vals["response_improve_pct_mean"])
        if exp < 0.0 and resp < 0.0:
            conclusions.append(f"{mode}: current weighted partitioning is worse than neutral Voronoi on both exposure and response on average.")
        elif exp > 0.0 and resp > 0.0:
            conclusions.append(f"{mode}: current weighted partitioning is better than neutral Voronoi on both exposure and response on average.")
        else:
            conclusions.append(f"{mode}: current weighted partitioning has mixed effect relative to neutral Voronoi.")
    summary["conclusions"] = conclusions

    with open(outdir / "zone_partitioning_ablation_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with open(outdir / "zone_partitioning_ablation_report.md", "w", encoding="utf-8") as f:
        f.write("# Zone Partitioning Ablation Diagnostic\n\n")
        f.write("## Parameters\n\n")
        for k, v in summary["parameters"].items():
            f.write(f"- `{k}`: `{v}`\n")
        f.write("\n## Summary By Mode\n\n")
        for mode, vals in summary["summary_by_mode"].items():
            f.write(f"### {mode}\n\n")
            for k, v in vals.items():
                f.write(f"- `{k}`: `{v}`\n")
            f.write("\n")
        f.write("## Conclusions\n\n")
        for line in conclusions:
            f.write(f"- {line}\n")

    if not paired_df.empty:
        _plot_paired_deltas(paired_df, outdir / "zone_partitioning_ablation_deltas.png")

    print(f"[done] zone partitioning ablation saved to: {outdir}")


if __name__ == "__main__":
    main()
