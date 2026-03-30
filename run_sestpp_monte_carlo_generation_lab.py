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

import DeterrentSystem_assignment_lab as ds
from config_loader import add_config_argument, parse_args_with_config, write_resolved_config_manifest


POINT_GENERATION_CONFIG_ALIASES = {
    "runner.num_runs": "num_runs",
    "runner.seed_start": "seed_start",
    "runner.t_end": "t_end",
    "runner.dt": "dt",
    "runner.assignment_method": "assignment_method",
    "runner.baselines": "baselines",
    "runner.outdir": "outdir",
    "point_generation.mc_rollouts": "patrol_mc_rollouts",
    "point_generation.mc_max_events_per_rollout": "patrol_mc_max_events_per_rollout",
    "point_generation.mc_use_excess": "patrol_mc_use_excess",
}


def _parse_csv_list(text: str) -> List[str]:
    return [chunk.strip() for chunk in str(text).split(",") if chunk.strip()]


def _baseline_cfg(name: str) -> dict:
    key = str(name).strip().lower()
    if key == "reactive":
        return {
            "simulation_mode": "reactive",
            "enable_patrolling": False,
            "enable_intervention_feedback": False,
            "include_fallback_patrol": False,
            "enable_model_scored_deterring": False,
        }
    if key == "prediction_only":
        return {
            "simulation_mode": "prediction_only",
            "enable_patrolling": True,
            "enable_intervention_feedback": False,
            "include_fallback_patrol": True,
            "enable_model_scored_deterring": False,
        }
    if key == "proposed":
        return {
            "simulation_mode": "proposed",
            "enable_patrolling": True,
            "enable_intervention_feedback": True,
            "include_fallback_patrol": True,
            "enable_model_scored_deterring": True,
        }
    raise ValueError(f"Unknown baseline: {name}")


def _ci95(series: pd.Series) -> float:
    arr = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    if arr.size <= 1:
        return float("nan")
    return float(1.96 * np.std(arr, ddof=1) / math.sqrt(arr.size))


def _stats(df: pd.DataFrame, col: str) -> dict:
    series = pd.to_numeric(df[col], errors="coerce").dropna()
    if series.empty:
        return {"mean": float("nan"), "std": float("nan"), "ci95": float("nan"), "n": 0}
    return {
        "mean": float(series.mean()),
        "std": float(series.std(ddof=1)) if len(series) > 1 else 0.0,
        "ci95": _ci95(series),
        "n": int(len(series)),
    }


def _build_base_params(args: argparse.Namespace) -> dict:
    return {
        "W": 500.0,
        "H": 500.0,
        "NX": 80,
        "NY": 64,
        "Nrobots": 6,
        "uav_fraction": 0.0,
        "warmup_s": 1800.0,
        "task_replan_period_s": float(args.task_replan_period_s),
        "forecast_horizon_s": float(args.forecast_horizon_s),
        "forecast_match_radius_m": float(args.forecast_match_radius_m),
        "forecast_top_k": int(args.forecast_top_k),
        "forecast_eval_period_s": float(args.forecast_eval_period_s),
        "assignment_method": str(args.assignment_method),
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
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
        "export_task_debug": bool(args.export_task_debug),
        "T_end": float(args.t_end),
        "dt": float(args.dt),
    }


def run_matrix(
    *,
    num_runs: int,
    seed_start: int,
    base_params: dict,
    baselines: List[str],
    patrol_mc_rollouts: int,
    patrol_mc_max_events_per_rollout: int,
    patrol_mc_use_excess: bool,
) -> pd.DataFrame:
    rows: List[dict] = []
    generation_modes = ["hotspots", "monte_carlo"]

    total = len(baselines) * len(generation_modes)
    done = 0
    for baseline in baselines:
        for generation_mode in generation_modes:
            done += 1
            print(f"[run] {done}/{total} baseline={baseline} generator={generation_mode}", flush=True)
            kwargs = dict(base_params)
            kwargs.update(_baseline_cfg(baseline))
            kwargs["patrol_point_generation_mode"] = str(generation_mode)
            kwargs["patrol_mc_rollouts"] = int(patrol_mc_rollouts)
            kwargs["patrol_mc_max_events_per_rollout"] = int(patrol_mc_max_events_per_rollout)
            kwargs["patrol_mc_use_excess"] = bool(patrol_mc_use_excess)

            result = ds.run_metrics_experiments(
                num_runs=int(num_runs),
                seed_start=int(seed_start),
                report_each_run=False,
                collect_time_metrics=False,
                **kwargs,
            )
            for run_row in result.get("runs", []):
                rows.append(
                    {
                        "baseline": str(baseline),
                        "patrol_point_generation_mode": str(generation_mode),
                        "patrol_mc_rollouts": int(patrol_mc_rollouts),
                        "patrol_mc_max_events_per_rollout": int(patrol_mc_max_events_per_rollout),
                        "patrol_mc_use_excess": int(bool(patrol_mc_use_excess)),
                        "seed": int(run_row.get("seed", -1)),
                        "run_idx": int(run_row.get("run_idx", -1)),
                        "value_weighted_exposure": float(run_row.get("value_weighted_exposure", np.nan)),
                        "mean_response_time_s": float(run_row.get("mean_response_time_s", np.nan)),
                        "boundary_message_count": float(run_row.get("boundary_message_count", np.nan)),
                        "boundary_bytes_sent": float(run_row.get("boundary_bytes_sent", np.nan)),
                        "tasks_per_unit_distance": float(run_row.get("tasks_per_unit_distance", np.nan)),
                        "completed_tasks_total": float(run_row.get("completed_tasks_total", np.nan)),
                        "forecast_recall_at_k": float(run_row.get("forecast_recall_at_k", np.nan)),
                        "forecast_precision_at_k": float(run_row.get("forecast_precision_at_k", np.nan)),
                        "forecast_hotspot_hit_rate": float(run_row.get("forecast_hotspot_hit_rate", np.nan)),
                        "forecast_lead_time_s": float(run_row.get("forecast_lead_time_s", np.nan)),
                        "model_deterring_generated": float(run_row.get("model_deterring_generated", np.nan)),
                        "model_deterring_accepted": float(run_row.get("model_deterring_accepted", np.nan)),
                        "deterring_actions_completed_model_scored": float(
                            run_row.get("deterring_actions_completed_model_scored", np.nan)
                        ),
                        "truth_suppression_rate": float(run_row.get("truth_suppression_rate", np.nan)),
                    }
                )
    return pd.DataFrame(rows)


def build_summary(runs_df: pd.DataFrame) -> pd.DataFrame:
    if runs_df.empty:
        return pd.DataFrame()

    metrics = [
        "value_weighted_exposure",
        "mean_response_time_s",
        "boundary_message_count",
        "tasks_per_unit_distance",
        "completed_tasks_total",
        "forecast_recall_at_k",
        "forecast_precision_at_k",
        "forecast_hotspot_hit_rate",
        "forecast_lead_time_s",
        "model_deterring_generated",
        "model_deterring_accepted",
        "deterring_actions_completed_model_scored",
        "truth_suppression_rate",
    ]
    out_rows: List[dict] = []
    for (baseline, generation_mode), group in runs_df.groupby(
        ["baseline", "patrol_point_generation_mode"], sort=True
    ):
        row = {
            "baseline": str(baseline),
            "patrol_point_generation_mode": str(generation_mode),
            "n": int(len(group)),
        }
        for metric in metrics:
            stats = _stats(group, metric)
            row[f"{metric}_mean"] = stats["mean"]
            row[f"{metric}_std"] = stats["std"]
            row[f"{metric}_ci95"] = stats["ci95"]
        out_rows.append(row)
    return pd.DataFrame(out_rows)


def build_deltas_vs_hotspots(runs_df: pd.DataFrame) -> pd.DataFrame:
    if runs_df.empty:
        return pd.DataFrame()
    hot = runs_df[runs_df["patrol_point_generation_mode"] == "hotspots"].copy()
    mc = runs_df[runs_df["patrol_point_generation_mode"] == "monte_carlo"].copy()
    if hot.empty or mc.empty:
        return pd.DataFrame()

    merge_cols = ["baseline", "seed", "run_idx"]
    paired = hot.merge(mc, on=merge_cols, suffixes=("_hotspots", "_monte_carlo"), how="inner")
    if paired.empty:
        return paired

    def _improve(lower_is_better_hot: pd.Series, lower_is_better_mc: pd.Series) -> pd.Series:
        den = lower_is_better_hot.replace(0.0, np.nan)
        return 100.0 * (lower_is_better_hot - lower_is_better_mc) / den

    paired["exposure_improve_pct_vs_hotspots"] = _improve(
        paired["value_weighted_exposure_hotspots"],
        paired["value_weighted_exposure_monte_carlo"],
    )
    paired["response_improve_pct_vs_hotspots"] = _improve(
        paired["mean_response_time_s_hotspots"],
        paired["mean_response_time_s_monte_carlo"],
    )
    den_comm = paired["boundary_message_count_hotspots"].replace(0.0, np.nan)
    paired["comm_change_pct_vs_hotspots"] = 100.0 * (
        paired["boundary_message_count_monte_carlo"] - paired["boundary_message_count_hotspots"]
    ) / den_comm
    paired["tasks_per_unit_distance_delta"] = (
        paired["tasks_per_unit_distance_monte_carlo"] - paired["tasks_per_unit_distance_hotspots"]
    )
    paired["forecast_recall_delta"] = (
        paired["forecast_recall_at_k_monte_carlo"] - paired["forecast_recall_at_k_hotspots"]
    )
    paired["forecast_precision_delta"] = (
        paired["forecast_precision_at_k_monte_carlo"] - paired["forecast_precision_at_k_hotspots"]
    )
    paired["forecast_hit_rate_delta"] = (
        paired["forecast_hotspot_hit_rate_monte_carlo"] - paired["forecast_hotspot_hit_rate_hotspots"]
    )
    return paired


def build_delta_summary(delta_df: pd.DataFrame) -> pd.DataFrame:
    if delta_df.empty:
        return pd.DataFrame()
    metrics = [
        "exposure_improve_pct_vs_hotspots",
        "response_improve_pct_vs_hotspots",
        "comm_change_pct_vs_hotspots",
        "tasks_per_unit_distance_delta",
        "forecast_recall_delta",
        "forecast_precision_delta",
        "forecast_hit_rate_delta",
    ]
    rows: List[dict] = []
    for baseline, group in delta_df.groupby("baseline", sort=True):
        row = {"baseline": str(baseline), "n": int(len(group))}
        for metric in metrics:
            stats = _stats(group, metric)
            row[f"{metric}_mean"] = stats["mean"]
            row[f"{metric}_std"] = stats["std"]
            row[f"{metric}_ci95"] = stats["ci95"]
        rows.append(row)
    return pd.DataFrame(rows)


def _plot_tradeoff(delta_summary_df: pd.DataFrame, outdir: Path) -> Path | None:
    if delta_summary_df.empty:
        return None
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), sharey=True)
    baselines = delta_summary_df["baseline"].astype(str).tolist()
    xpos = np.arange(len(baselines))

    axes[0].bar(xpos, delta_summary_df["exposure_improve_pct_vs_hotspots_mean"], color="#2a9d8f")
    axes[0].axhline(0.0, color="black", linewidth=1.0)
    axes[0].set_title("Exposure vs Hotspots")
    axes[0].set_ylabel("Improvement (%)")
    axes[0].set_xticks(xpos, baselines)
    axes[0].grid(True, axis="y", alpha=0.3)

    axes[1].bar(xpos, delta_summary_df["response_improve_pct_vs_hotspots_mean"], color="#e76f51")
    axes[1].axhline(0.0, color="black", linewidth=1.0)
    axes[1].set_title("Response vs Hotspots")
    axes[1].set_xticks(xpos, baselines)
    axes[1].grid(True, axis="y", alpha=0.3)

    path = outdir / "sestpp_monte_carlo_generation_tradeoff_lab.png"
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def _write_report(
    outdir: Path,
    summary_df: pd.DataFrame,
    delta_summary_df: pd.DataFrame,
    args: argparse.Namespace,
) -> Path:
    lines = [
        "# SESTPP Monte Carlo Point Generation Lab",
        "",
        "This experiment compares the current hotspot-based patrol-point generator against a",
        "Monte Carlo generator that samples representative points from the SESTPP horizon field.",
        "",
        "## Configuration",
        f"- Baselines: `{args.baselines}`",
        f"- Runs: `{int(args.num_runs)}` starting at seed `{int(args.seed_start)}`",
        f"- Horizon: `{float(args.forecast_horizon_s):.1f}s`",
        f"- Monte Carlo rollouts: `{int(args.patrol_mc_rollouts)}`",
        f"- Monte Carlo max events / rollout: `{int(args.patrol_mc_max_events_per_rollout)}`",
        f"- Monte Carlo uses excess field: `{bool(args.patrol_mc_use_excess)}`",
        "",
        "## Summary",
    ]
    if summary_df.empty:
        lines.append("- No summary rows were generated.")
    else:
        for _, row in summary_df.iterrows():
            lines.extend(
                [
                    (
                        f"- `{row['baseline']}` / `{row['patrol_point_generation_mode']}`: "
                        f"exposure={row['value_weighted_exposure_mean']:.3f}, "
                        f"response={row['mean_response_time_s_mean']:.3f}s, "
                        f"comm={row['boundary_message_count_mean']:.1f}, "
                        f"forecast_hit={row['forecast_hotspot_hit_rate_mean']:.3f}"
                    )
                ]
            )
    lines.append("")
    lines.append("## Monte Carlo vs Hotspots")
    if delta_summary_df.empty:
        lines.append("- No paired deltas were generated.")
    else:
        for _, row in delta_summary_df.iterrows():
            lines.append(
                (
                    f"- `{row['baseline']}`: exposure_improve={row['exposure_improve_pct_vs_hotspots_mean']:.3f}%, "
                    f"response_improve={row['response_improve_pct_vs_hotspots_mean']:.3f}%, "
                    f"comm_change={row['comm_change_pct_vs_hotspots_mean']:.3f}%"
                )
            )
    report_path = outdir / "SESTPP_MONTE_CARLO_GENERATION_README.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def _run_smoke(args: argparse.Namespace, outdir: Path) -> pd.DataFrame:
    smoke_args = argparse.Namespace(**vars(args))
    smoke_args.num_runs = 2
    smoke_args.t_end = 600.0
    smoke_outdir = outdir / "smoke"
    smoke_outdir.mkdir(parents=True, exist_ok=True)
    runs_df = run_matrix(
        num_runs=int(smoke_args.num_runs),
        seed_start=int(smoke_args.seed_start),
        base_params=_build_base_params(smoke_args),
        baselines=_parse_csv_list(smoke_args.baselines),
        patrol_mc_rollouts=int(smoke_args.patrol_mc_rollouts),
        patrol_mc_max_events_per_rollout=int(smoke_args.patrol_mc_max_events_per_rollout),
        patrol_mc_use_excess=bool(smoke_args.patrol_mc_use_excess),
    )
    if runs_df.empty:
        raise RuntimeError("Smoke run produced no rows.")
    runs_df.to_csv(smoke_outdir / "sestpp_monte_carlo_generation_runs_lab_smoke.csv", index=False)
    build_summary(runs_df).to_csv(smoke_outdir / "sestpp_monte_carlo_generation_summary_lab_smoke.csv", index=False)
    build_deltas_vs_hotspots(runs_df).to_csv(
        smoke_outdir / "sestpp_monte_carlo_generation_deltas_lab_smoke.csv", index=False
    )
    return runs_df


def main() -> None:
    parser = argparse.ArgumentParser(description="Lab experiment for Monte Carlo SESTPP patrol-point generation")
    add_config_argument(parser)
    parser.add_argument("--num-runs", type=int, default=8)
    parser.add_argument("--seed-start", type=int, default=2026)
    parser.add_argument("--t-end", type=float, default=3 * 3600.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--assignment-method", type=str, default="hungarian")
    parser.add_argument("--baselines", type=str, default="prediction_only,proposed")
    parser.add_argument("--task-replan-period-s", type=float, default=45.0)
    parser.add_argument("--forecast-horizon-s", type=float, default=300.0)
    parser.add_argument("--forecast-match-radius-m", type=float, default=20.0)
    parser.add_argument("--forecast-top-k", type=int, default=5)
    parser.add_argument("--forecast-eval-period-s", type=float, default=30.0)
    parser.add_argument("--patrol-min-hotspot-score", type=float, default=1e-4)
    parser.add_argument("--patrol-hotspot-filter-mode", type=str, default="percentile")
    parser.add_argument("--patrol-hotspot-score-percentile", type=float, default=90.0)
    parser.add_argument("--patrol-hotspot-keep-top-k", type=int, default=6)
    parser.add_argument("--model-deterring-window-s", type=float, default=90.0)
    parser.add_argument("--model-deterring-gate-policy", type=str, default="heuristic")
    parser.add_argument("--model-deterring-sprt-alpha", type=float, default=0.05)
    parser.add_argument("--model-deterring-sprt-beta", type=float, default=0.20)
    parser.add_argument("--model-deterring-chance-threshold", type=float, default=0.20)
    parser.add_argument("--model-deterring-min-deltaj-per-cost", type=float, default=0.15)
    parser.add_argument("--patrol-mc-rollouts", type=int, default=64)
    parser.add_argument("--patrol-mc-max-events-per-rollout", type=int, default=24)
    parser.add_argument("--patrol-mc-use-excess", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--export-task-debug", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--outdir", type=str, default="results/sestpp_monte_carlo_generation_lab")
    parser.add_argument("--with-smoke-check", action="store_true")
    parser.add_argument("--smoke-only", action="store_true")
    args, config_meta = parse_args_with_config(parser, aliases=POINT_GENERATION_CONFIG_ALIASES)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    if bool(args.with_smoke_check) or bool(args.smoke_only):
        print("[check] running lab smoke")
        smoke_df = _run_smoke(args, outdir)
        print(f"[check] smoke completed rows={len(smoke_df)}")
        if bool(args.smoke_only):
            print("[done] smoke-only requested; exiting")
            return

    baselines = _parse_csv_list(args.baselines)
    if not baselines:
        raise ValueError("No baselines selected.")

    runs_df = run_matrix(
        num_runs=int(args.num_runs),
        seed_start=int(args.seed_start),
        base_params=_build_base_params(args),
        baselines=baselines,
        patrol_mc_rollouts=int(args.patrol_mc_rollouts),
        patrol_mc_max_events_per_rollout=int(args.patrol_mc_max_events_per_rollout),
        patrol_mc_use_excess=bool(args.patrol_mc_use_excess),
    )
    summary_df = build_summary(runs_df)
    delta_df = build_deltas_vs_hotspots(runs_df)
    delta_summary_df = build_delta_summary(delta_df)

    runs_path = outdir / "sestpp_monte_carlo_generation_runs_lab.csv"
    summary_path = outdir / "sestpp_monte_carlo_generation_summary_lab.csv"
    delta_path = outdir / "sestpp_monte_carlo_generation_deltas_lab.csv"
    delta_summary_path = outdir / "sestpp_monte_carlo_generation_delta_summary_lab.csv"
    manifest_path = outdir / "sestpp_monte_carlo_generation_manifest_lab.json"

    runs_df.to_csv(runs_path, index=False)
    summary_df.to_csv(summary_path, index=False)
    delta_df.to_csv(delta_path, index=False)
    delta_summary_df.to_csv(delta_summary_path, index=False)
    plot_path = _plot_tradeoff(delta_summary_df, outdir)
    report_path = _write_report(outdir, summary_df, delta_summary_df, args)

    write_resolved_config_manifest(
        manifest_path,
        script="run_sestpp_monte_carlo_generation_lab.py",
        args=args,
        config_meta=config_meta,
        extra={
            "baselines": baselines,
            "plot_path": str(plot_path) if plot_path is not None else "",
            "report_path": str(report_path),
        },
    )

    print(f"[done] wrote outputs to: {outdir}")
    print(f"- {runs_path}")
    print(f"- {summary_path}")
    print(f"- {delta_path}")
    print(f"- {delta_summary_path}")
    print(f"- {manifest_path}")
    print(f"- {report_path}")
    if plot_path is not None:
        print(f"- {plot_path}")


if __name__ == "__main__":
    main()
