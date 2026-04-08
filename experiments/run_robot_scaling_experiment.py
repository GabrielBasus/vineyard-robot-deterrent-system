from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import DeterrentSystem as ds
from experiments.thesis_experiment_workflow import render_execution_order_lines, render_stage_readme_lines


SCENARIOS = {
    "S1_low_pressure_short_range": {
        "mu_true": 7.5e-7,
        "alpha_true": 0.20,
        "omega_true": 700.0,
        "sigma_true": 10.0,
        "beta_true": 0.30,
        "detect_range_m": 25.0,
        "row_gain": 1.2,
        "edge_gain": 0.5,
    },
    "S2_nominal": {
        "mu_true": 1.0e-6,
        "alpha_true": 0.30,
        "omega_true": 600.0,
        "sigma_true": 12.0,
        "beta_true": 0.25,
        "detect_range_m": 30.0,
        "row_gain": 1.5,
        "edge_gain": 0.6,
    },
    "S3_high_pressure_long_range": {
        "mu_true": 1.5e-6,
        "alpha_true": 0.45,
        "omega_true": 500.0,
        "sigma_true": 14.0,
        "beta_true": 0.22,
        "detect_range_m": 35.0,
        "row_gain": 1.8,
        "edge_gain": 0.8,
    },
}


def _parse_int_list(text: str) -> list[int]:
    out = []
    for part in str(text).split(","):
        p = part.strip()
        if not p:
            continue
        out.append(int(p))
    if not out:
        raise ValueError("Expected at least one integer value")
    return out


def _parse_str_list(text: str) -> list[str]:
    out = [s.strip() for s in str(text).split(",") if s.strip()]
    if not out:
        raise ValueError("Expected at least one scenario id")
    return out


def _ci95(series: pd.Series) -> float:
    arr = pd.to_numeric(series, errors="coerce")
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    if arr.size == 1:
        return 0.0
    return float(1.96 * np.std(arr, ddof=1) / np.sqrt(arr.size))


def _build_base_params(profile: str, horizon_h: float) -> dict:
    if profile == "fast":
        dt = 5.0
        nx = 80
        ny = 64
        num_runs = 5
    else:
        dt = 5.0
        nx = 96
        ny = 72
        num_runs = 12
    params = {
        "dt": dt,
        "NX": nx,
        "NY": ny,
        "T_end": float(horizon_h) * 3600.0,
        "W": 500.0,
        "H": 500.0,
        "uav_fraction": 0.0,
        "task_replan_period_s": 45.0,
        "warmup_s": 1800.0,
        # Diagnostic-like gating profile.
        "prio_deterring": 2.0,
        "prio_patrolling": 0.2,
        "assigner_w_load": 0.8,
        "model_deterring_window_s": 90.0,
        "model_deterring_risk_threshold": 0.35,
        "model_deterring_risk_scale": 1.0e-4,
        "model_deterring_budget_per_robot_per_hr": 4,
        "model_deterring_min_recent_points": 1,
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
        # Intervention comm gating.
        "intervention_boundary_min_interval_s": 60.0,
        "intervention_boundary_spatial_quant_m": 20.0,
        "intervention_boundary_min_weight": 0.40,
        # Forecast config used by current diagnostics.
        "forecast_horizon_s": 300.0,
        "forecast_match_radius_m": 20.0,
        "forecast_top_k": 5,
        "forecast_eval_period_s": 30.0,
        # Avoid touching live telemetry directories in experiments.
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
    }
    return params, num_runs


def _flatten_runs(result: dict, scenario_id: str, robot_count: int, seed_start: int) -> list[dict]:
    rows: list[dict] = []
    baselines = result.get("baselines", {})
    for baseline_name, baseline_result in baselines.items():
        run_list = baseline_result.get("runs", [])
        for run_idx, m in enumerate(run_list):
            rows.append(
                {
                    "scenario_id": scenario_id,
                    "robot_count": int(robot_count),
                    "baseline": baseline_name,
                    "run_idx": int(run_idx),
                    "seed": int(seed_start + run_idx),
                    "value_weighted_exposure": float(m.get("value_weighted_exposure", np.nan)),
                    "mean_response_time_s": float(m.get("mean_response_time_s", np.nan)),
                    "boundary_message_count": float(m.get("boundary_message_count", np.nan)),
                    "deterring_actions_completed_model_scored": float(
                        m.get("deterring_actions_completed_model_scored", np.nan)
                    ),
                    "model_deterring_generated": float(m.get("model_deterring_generated", np.nan)),
                    "model_deterring_accepted": float(m.get("model_deterring_accepted", np.nan)),
                    "preventive_policy": str(m.get("preventive_policy", "")),
                    "selective_preventive_enabled": float(m.get("selective_preventive_enabled", np.nan)),
                    "use_frozen_calibration": float(m.get("use_frozen_calibration", np.nan)),
                    "selected_calibration_config_id": str(m.get("selected_calibration_config_id", "")),
                    "calibrated_model_alpha_inhib": float(m.get("calibrated_model_alpha_inhib", np.nan)),
                    "calibrated_model_omega_inhib": float(m.get("calibrated_model_omega_inhib", np.nan)),
                    "calibrated_model_mu_base": float(m.get("calibrated_model_mu_base", np.nan)),
                    "calibrated_model_bg_ema": float(m.get("calibrated_model_bg_ema", np.nan)),
                    "intervention_msg_dropped_debounce": float(
                        m.get("intervention_msg_dropped_debounce", np.nan)
                    ),
                }
            )
    return rows


def _compute_pairwise_deltas(run_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    key = ["scenario_id", "robot_count", "run_idx", "seed"]
    pred = run_df[run_df["baseline"] == "prediction_only"].copy()
    prop = run_df[run_df["baseline"] == "proposed"].copy()
    merged = pred.merge(prop, on=key, suffixes=("_pred", "_prop"), how="inner")
    if merged.empty:
        return merged, pd.DataFrame()
    merged["delta_exp_improve_pct"] = (
        100.0
        * (merged["value_weighted_exposure_pred"] - merged["value_weighted_exposure_prop"])
        / merged["value_weighted_exposure_pred"].replace(0.0, np.nan)
    )
    merged["delta_resp_improve_pct"] = (
        100.0
        * (merged["mean_response_time_s_pred"] - merged["mean_response_time_s_prop"])
        / merged["mean_response_time_s_pred"].replace(0.0, np.nan)
    )
    merged["delta_comm_increase_pct"] = (
        100.0
        * (merged["boundary_message_count_prop"] - merged["boundary_message_count_pred"])
        / merged["boundary_message_count_pred"].replace(0.0, np.nan)
    )
    merged["delta_model_done_gain"] = (
        merged["deterring_actions_completed_model_scored_prop"]
        - merged["deterring_actions_completed_model_scored_pred"]
    )

    grp = merged.groupby(["scenario_id", "robot_count"], as_index=False)
    summary = grp.agg(
        n=("delta_exp_improve_pct", "count"),
        delta_exp_improve_pct_mean=("delta_exp_improve_pct", "mean"),
        delta_resp_improve_pct_mean=("delta_resp_improve_pct", "mean"),
        delta_comm_increase_pct_mean=("delta_comm_increase_pct", "mean"),
        delta_model_done_gain_mean=("delta_model_done_gain", "mean"),
    )
    for col in [
        "delta_exp_improve_pct",
        "delta_resp_improve_pct",
        "delta_comm_increase_pct",
        "delta_model_done_gain",
    ]:
        ci = (
            merged.groupby(["scenario_id", "robot_count"], as_index=False)[col]
            .apply(_ci95)
            .rename(columns={col: f"{col}_ci95"})
        )
        summary = summary.merge(ci, on=["scenario_id", "robot_count"], how="left")
    return merged, summary


def _plot_delta_lines(delta_summary: pd.DataFrame, outdir: Path) -> None:
    if delta_summary.empty:
        return
    scenarios = sorted(delta_summary["scenario_id"].unique())

    def plot_metric(metric: str, ci_col: str, title: str, ylabel: str, out_name: str, target_line: float | None = None):
        fig, ax = plt.subplots(figsize=(8, 5))
        for sc in scenarios:
            d = delta_summary[delta_summary["scenario_id"] == sc].sort_values("robot_count")
            x = d["robot_count"].to_numpy(dtype=float)
            y = d[metric].to_numpy(dtype=float)
            yerr = d[ci_col].to_numpy(dtype=float)
            ax.plot(x, y, marker="o", linewidth=2, label=sc)
            ax.fill_between(x, y - yerr, y + yerr, alpha=0.15)
        ax.axhline(0.0, color="black", linestyle="--", linewidth=1)
        if target_line is not None:
            ax.axhline(target_line, color="red", linestyle="--", linewidth=1)
        ax.set_title(title)
        ax.set_xlabel("Number of robots")
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.25)
        ax.legend(loc="best")
        fig.tight_layout()
        fig.savefig(outdir / out_name, dpi=180)
        plt.close(fig)

    plot_metric(
        "delta_exp_improve_pct_mean",
        "delta_exp_improve_pct_ci95",
        "Exposure Improvement vs Number of Robots",
        "Proposed vs Prediction-Only exposure improvement [%]",
        "01_exposure_improvement_vs_robot_count.png",
    )
    plot_metric(
        "delta_resp_improve_pct_mean",
        "delta_resp_improve_pct_ci95",
        "Response-Time Improvement vs Number of Robots",
        "Proposed vs Prediction-Only response improvement [%]",
        "02_response_improvement_vs_robot_count.png",
    )
    plot_metric(
        "delta_comm_increase_pct_mean",
        "delta_comm_increase_pct_ci95",
        "Communication Increase vs Number of Robots",
        "Proposed vs Prediction-Only communication increase [%]",
        "03_comm_increase_vs_robot_count.png",
        target_line=30.0,
    )
    plot_metric(
        "delta_model_done_gain_mean",
        "delta_model_done_gain_ci95",
        "Model-Scored Completed Deterring Gain vs Number of Robots",
        "Extra completed model-scored deterring tasks (proposed - prediction_only)",
        "04_model_done_gain_vs_robot_count.png",
    )


def _plot_absolute_exposure(summary_df: pd.DataFrame, outdir: Path) -> None:
    if summary_df.empty:
        return
    scenarios = sorted(summary_df["scenario_id"].unique())
    fig, axes = plt.subplots(1, len(scenarios), figsize=(6 * len(scenarios), 4.8), sharey=True)
    if len(scenarios) == 1:
        axes = [axes]

    for ax, sc in zip(axes, scenarios):
        d = summary_df[summary_df["scenario_id"] == sc].copy()
        for baseline in ["reactive", "prediction_only", "proposed"]:
            db = d[d["baseline"] == baseline].sort_values("robot_count")
            if db.empty:
                continue
            ax.plot(
                db["robot_count"],
                db["value_weighted_exposure_mean"],
                marker="o",
                linewidth=2,
                label=baseline,
            )
        ax.set_title(sc)
        ax.set_xlabel("Number of robots")
        ax.grid(alpha=0.25)
    axes[0].set_ylabel("Value-weighted exposure (lower better)")
    axes[0].legend(loc="best")
    fig.tight_layout()
    fig.savefig(outdir / "05_absolute_exposure_by_baseline_vs_robot_count.png", dpi=180)
    plt.close(fig)


def _write_readme(outdir: Path, robot_counts: list[int], scenarios: list[str], num_runs: int, horizon_h: float) -> None:
    lines = []
    lines.append("# Robot Scaling Experiment")
    lines.append("")
    lines.extend(render_stage_readme_lines("robot_scaling"))
    lines.append("")
    lines.append("## Experiment Setup")
    lines.append(f"- Robot counts: {robot_counts}")
    lines.append(f"- Scenarios: {scenarios}")
    lines.append(f"- Runs per setting: {num_runs}")
    lines.append(f"- Horizon [h]: {horizon_h}")
    lines.append("")
    lines.append("## Key outputs")
    lines.append("- `robot_scaling_baseline_summary.csv`")
    lines.append("- `robot_scaling_run_metrics.csv`")
    lines.append("- `robot_scaling_pairwise_deltas.csv`")
    lines.append("- `robot_scaling_delta_summary.csv`")
    lines.append("- `01_exposure_improvement_vs_robot_count.png`")
    lines.append("- `02_response_improvement_vs_robot_count.png`")
    lines.append("- `03_comm_increase_vs_robot_count.png`")
    lines.append("- `04_model_done_gain_vs_robot_count.png`")
    lines.append("- `05_absolute_exposure_by_baseline_vs_robot_count.png`")
    lines.append("")
    lines.append("## Pairwise Scaling Interpretation")
    lines.append("- Every scaling delta is a proposed-vs-prediction comparison on the same scenario, robot count, and seed before CI95 aggregation.")
    lines.append("- Exposure improvement should grow with robot count or at least stay clearly positive.")
    lines.append("- Response should not collapse as the fleet grows.")
    lines.append("- Communication should stay controlled rather than expanding faster than the benefit.")
    lines.append("- Model-scored deterring gain should rise with robot count if planner bottlenecks are removed.")
    lines.append("")
    lines.extend(render_execution_order_lines())
    (outdir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate performance vs number of robots.")
    parser.add_argument("--profile", choices=["fast", "final"], default="fast")
    parser.add_argument("--robot-counts", default="2,4,6,8,10")
    parser.add_argument("--scenarios", default="S2_nominal,S3_high_pressure_long_range")
    parser.add_argument("--time-horizon-h", type=float, default=24.0)
    parser.add_argument("--num-runs", type=int, default=0, help="0 => profile default")
    parser.add_argument("--seed-start", type=int, default=1000)
    parser.add_argument("--outdir", default="results/robot_scaling")
    parser.add_argument("--report-each-run", action="store_true")
    parser.add_argument("--planner-profile", default="")
    parser.add_argument("--proposed-preventive-policy", choices=["off", "heuristic", "sprt_capacity"], default="")
    parser.add_argument("--use-frozen-calibration", action="store_true")
    parser.add_argument("--calibration-ranking-path", default="")
    parser.add_argument("--calibration-manifest-path", default="")
    parser.add_argument("--calibration-config-id", default="")
    args = parser.parse_args()

    robot_counts = _parse_int_list(args.robot_counts)
    scenarios = _parse_str_list(args.scenarios)
    for sc in scenarios:
        if sc not in SCENARIOS:
            raise ValueError(f"Unknown scenario '{sc}'. Known: {sorted(SCENARIOS.keys())}")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    base_params, default_runs = _build_base_params(args.profile, args.time_horizon_h)
    num_runs = int(args.num_runs) if int(args.num_runs) > 0 else int(default_runs)
    if args.planner_profile:
        base_params["planner_profile"] = str(args.planner_profile)

    summary_rows = []
    run_rows = []
    total_jobs = len(robot_counts) * len(scenarios)
    done = 0
    for sc in scenarios:
        sc_params = SCENARIOS[sc]
        for rc in robot_counts:
            done += 1
            print(f"[robot-scaling] {done}/{total_jobs} scenario={sc} robots={rc} runs={num_runs}", flush=True)
            run_kwargs = dict(base_params)
            run_kwargs.update(sc_params)
            run_kwargs["Nrobots"] = int(rc)

            result = ds.run_baseline_suite(
                num_runs=num_runs,
                seed_start=int(args.seed_start),
                report_each_run=bool(args.report_each_run),
                csv_path=None,
                collect_time_metrics=False,
                proposed_preventive_policy=(args.proposed_preventive_policy or None),
                use_frozen_calibration=bool(args.use_frozen_calibration),
                calibration_ranking_path=(args.calibration_ranking_path or None),
                calibration_manifest_path=(args.calibration_manifest_path or None),
                calibration_config_id=(args.calibration_config_id or None),
                **run_kwargs,
            )

            comparison = result.get("comparison", pd.DataFrame()).copy()
            comparison["scenario_id"] = sc
            comparison["robot_count"] = int(rc)
            summary_rows.append(comparison)

            run_rows.extend(_flatten_runs(result, scenario_id=sc, robot_count=int(rc), seed_start=int(args.seed_start)))

    if not summary_rows:
        raise RuntimeError("No experiment results produced")

    summary_df = pd.concat(summary_rows, ignore_index=True)
    runs_df = pd.DataFrame(run_rows)
    pair_df, delta_summary_df = _compute_pairwise_deltas(runs_df)

    summary_df.to_csv(outdir / "robot_scaling_baseline_summary.csv", index=False)
    runs_df.to_csv(outdir / "robot_scaling_run_metrics.csv", index=False)
    pair_df.to_csv(outdir / "robot_scaling_pairwise_deltas.csv", index=False)
    delta_summary_df.to_csv(outdir / "robot_scaling_delta_summary.csv", index=False)

    _plot_delta_lines(delta_summary_df, outdir=outdir)
    _plot_absolute_exposure(summary_df, outdir=outdir)
    _write_readme(
        outdir=outdir,
        robot_counts=robot_counts,
        scenarios=scenarios,
        num_runs=num_runs,
        horizon_h=float(args.time_horizon_h),
    )
    print(f"[done] robot scaling outputs written to: {outdir.resolve()}")


if __name__ == "__main__":
    main()
