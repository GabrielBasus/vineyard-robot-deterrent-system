from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path
from typing import Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import labs.DeterrentSystem_assignment_lab as ds
from config_loader import add_config_argument, parse_args_with_config, write_resolved_config_manifest


MC_TUNING_SWEEP_CONFIG_ALIASES = {
    "runner.num_runs": "num_runs",
    "runner.seed_start": "seed_start",
    "runner.t_end": "t_end",
    "runner.dt": "dt",
    "runner.assignment_method": "assignment_method",
    "runner.baselines": "baselines",
    "runner.outdir": "outdir",
    "runner.limit_configs": "limit_configs",
    "sweep.mc_rollout_values": "mc_rollout_values",
    "sweep.mc_max_events_values": "mc_max_events_values",
    "sweep.mc_use_excess_values": "mc_use_excess_values",
}


def _parse_csv_list(text: str) -> List[str]:
    return [chunk.strip() for chunk in str(text).split(",") if chunk.strip()]


def _parse_int_list(text: str) -> List[int]:
    return [int(float(chunk.strip())) for chunk in str(text).split(",") if chunk.strip()]


def _parse_bool_list(text: str) -> List[bool]:
    out: List[bool] = []
    for chunk in str(text).split(","):
        s = str(chunk).strip().lower()
        if not s:
            continue
        if s in ("1", "true", "t", "yes", "y", "on"):
            out.append(True)
        elif s in ("0", "false", "f", "no", "n", "off"):
            out.append(False)
        else:
            raise ValueError(f"Invalid boolean list entry: {chunk!r}")
    return out


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
        "export_task_debug": False,
        "T_end": float(args.t_end),
        "dt": float(args.dt),
    }


def _build_grid(args: argparse.Namespace) -> List[dict]:
    rollout_vals = _parse_int_list(args.mc_rollout_values)
    max_event_vals = _parse_int_list(args.mc_max_events_values)
    use_excess_vals = _parse_bool_list(args.mc_use_excess_values)
    configs: List[dict] = []
    for idx, (rollouts, max_events, use_excess) in enumerate(
        itertools.product(rollout_vals, max_event_vals, use_excess_vals),
        start=1,
    ):
        configs.append(
            {
                "config_id": f"MC{idx:02d}",
                "patrol_mc_rollouts": int(rollouts),
                "patrol_mc_max_events_per_rollout": int(max_events),
                "patrol_mc_use_excess": bool(use_excess),
            }
        )
    limit = int(getattr(args, "limit_configs", 0) or 0)
    if limit > 0:
        configs = configs[:limit]
    return configs


def _run_reference(
    *,
    num_runs: int,
    seed_start: int,
    base_params: dict,
    baselines: List[str],
) -> pd.DataFrame:
    rows: List[dict] = []
    for baseline in baselines:
        print(f"[reference] baseline={baseline} generator=hotspots", flush=True)
        kwargs = dict(base_params)
        kwargs.update(_baseline_cfg(baseline))
        kwargs["patrol_point_generation_mode"] = "hotspots"
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
                    "config_id": "HOTSPOT_REF",
                    "patrol_point_generation_mode": "hotspots",
                    "patrol_mc_rollouts": 0,
                    "patrol_mc_max_events_per_rollout": 0,
                    "patrol_mc_use_excess": int(0),
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


def _run_mc_configs(
    *,
    num_runs: int,
    seed_start: int,
    base_params: dict,
    baselines: List[str],
    configs: List[dict],
) -> pd.DataFrame:
    rows: List[dict] = []
    total = len(baselines) * len(configs)
    done = 0
    for baseline in baselines:
        for cfg in configs:
            done += 1
            print(
                (
                    f"[run] {done}/{total} baseline={baseline} config={cfg['config_id']} "
                    f"rollouts={cfg['patrol_mc_rollouts']} "
                    f"max_events={cfg['patrol_mc_max_events_per_rollout']} "
                    f"use_excess={cfg['patrol_mc_use_excess']}"
                ),
                flush=True,
            )
            kwargs = dict(base_params)
            kwargs.update(_baseline_cfg(baseline))
            kwargs["patrol_point_generation_mode"] = "monte_carlo"
            kwargs["patrol_mc_rollouts"] = int(cfg["patrol_mc_rollouts"])
            kwargs["patrol_mc_max_events_per_rollout"] = int(cfg["patrol_mc_max_events_per_rollout"])
            kwargs["patrol_mc_use_excess"] = bool(cfg["patrol_mc_use_excess"])
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
                        "config_id": str(cfg["config_id"]),
                        "patrol_point_generation_mode": "monte_carlo",
                        "patrol_mc_rollouts": int(cfg["patrol_mc_rollouts"]),
                        "patrol_mc_max_events_per_rollout": int(cfg["patrol_mc_max_events_per_rollout"]),
                        "patrol_mc_use_excess": int(bool(cfg["patrol_mc_use_excess"])),
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
        "model_deterring_generated",
        "model_deterring_accepted",
        "deterring_actions_completed_model_scored",
        "truth_suppression_rate",
    ]
    out_rows: List[dict] = []
    for (baseline, config_id), group in runs_df.groupby(["baseline", "config_id"], sort=True):
        row = {
            "baseline": str(baseline),
            "config_id": str(config_id),
            "patrol_point_generation_mode": str(group["patrol_point_generation_mode"].iloc[0]),
            "patrol_mc_rollouts": int(group["patrol_mc_rollouts"].iloc[0]),
            "patrol_mc_max_events_per_rollout": int(group["patrol_mc_max_events_per_rollout"].iloc[0]),
            "patrol_mc_use_excess": int(group["patrol_mc_use_excess"].iloc[0]),
            "n": int(len(group)),
        }
        for metric in metrics:
            stats = _stats(group, metric)
            row[f"{metric}_mean"] = stats["mean"]
            row[f"{metric}_std"] = stats["std"]
            row[f"{metric}_ci95"] = stats["ci95"]
        out_rows.append(row)
    return pd.DataFrame(out_rows)


def build_paired_deltas(reference_df: pd.DataFrame, mc_runs_df: pd.DataFrame) -> pd.DataFrame:
    if reference_df.empty or mc_runs_df.empty:
        return pd.DataFrame()
    merge_cols = ["baseline", "seed", "run_idx"]
    paired = mc_runs_df.merge(reference_df, on=merge_cols, suffixes=("_mc", "_ref"), how="inner")
    if paired.empty:
        return paired

    def _improve(ref: pd.Series, cur: pd.Series) -> pd.Series:
        den = ref.replace(0.0, np.nan)
        return 100.0 * (ref - cur) / den

    paired["exposure_improve_pct_vs_hotspots"] = _improve(
        paired["value_weighted_exposure_ref"], paired["value_weighted_exposure_mc"]
    )
    paired["response_improve_pct_vs_hotspots"] = _improve(
        paired["mean_response_time_s_ref"], paired["mean_response_time_s_mc"]
    )
    den_comm = paired["boundary_message_count_ref"].replace(0.0, np.nan)
    paired["comm_change_pct_vs_hotspots"] = 100.0 * (
        paired["boundary_message_count_mc"] - paired["boundary_message_count_ref"]
    ) / den_comm
    paired["tasks_per_unit_distance_delta"] = (
        paired["tasks_per_unit_distance_mc"] - paired["tasks_per_unit_distance_ref"]
    )
    paired["completed_tasks_total_delta"] = (
        paired["completed_tasks_total_mc"] - paired["completed_tasks_total_ref"]
    )
    paired["truth_suppression_rate_delta"] = (
        paired["truth_suppression_rate_mc"] - paired["truth_suppression_rate_ref"]
    )
    paired["model_deterring_generated_delta"] = (
        paired["model_deterring_generated_mc"] - paired["model_deterring_generated_ref"]
    )
    paired["model_deterring_accepted_delta"] = (
        paired["model_deterring_accepted_mc"] - paired["model_deterring_accepted_ref"]
    )
    paired["deterring_actions_completed_model_scored_delta"] = (
        paired["deterring_actions_completed_model_scored_mc"]
        - paired["deterring_actions_completed_model_scored_ref"]
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
        "completed_tasks_total_delta",
        "truth_suppression_rate_delta",
        "model_deterring_generated_delta",
        "model_deterring_accepted_delta",
        "deterring_actions_completed_model_scored_delta",
    ]
    rows: List[dict] = []
    for (baseline, config_id), group in delta_df.groupby(["baseline", "config_id"], sort=True):
        row = {
            "baseline": str(baseline),
            "config_id": str(config_id),
            "patrol_mc_rollouts": int(group["patrol_mc_rollouts_mc"].iloc[0]),
            "patrol_mc_max_events_per_rollout": int(group["patrol_mc_max_events_per_rollout_mc"].iloc[0]),
            "patrol_mc_use_excess": int(group["patrol_mc_use_excess_mc"].iloc[0]),
            "n": int(len(group)),
        }
        for metric in metrics:
            stats = _stats(group, metric)
            row[f"{metric}_mean"] = stats["mean"]
            row[f"{metric}_std"] = stats["std"]
            row[f"{metric}_ci95"] = stats["ci95"]
        row["both_positive_runs"] = int(
            (
                (pd.to_numeric(group["exposure_improve_pct_vs_hotspots"], errors="coerce") > 0.0)
                & (pd.to_numeric(group["response_improve_pct_vs_hotspots"], errors="coerce") > 0.0)
            ).sum()
        )
        rows.append(row)
    return pd.DataFrame(rows)


def build_ranking(delta_summary_df: pd.DataFrame) -> pd.DataFrame:
    if delta_summary_df.empty:
        return pd.DataFrame()
    frames: List[pd.DataFrame] = []
    for baseline, group in delta_summary_df.groupby("baseline", sort=True):
        ranked = group.sort_values(
            by=[
                "both_positive_runs",
                "exposure_improve_pct_vs_hotspots_mean",
                "response_improve_pct_vs_hotspots_mean",
                "comm_change_pct_vs_hotspots_mean",
            ],
            ascending=[False, False, False, True],
        ).reset_index(drop=True)
        ranked.insert(0, "rank", np.arange(1, len(ranked) + 1))
        frames.append(ranked)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _plot_tradeoff(ranking_df: pd.DataFrame, outdir: Path) -> Path | None:
    if ranking_df.empty:
        return None
    baselines = list(ranking_df["baseline"].dropna().astype(str).unique())
    if not baselines:
        return None
    fig, axes = plt.subplots(1, len(baselines), figsize=(6.0 * len(baselines), 5.0), sharex=True, sharey=True)
    if len(baselines) == 1:
        axes = [axes]
    color_map = {0: "#457b9d", 1: "#d1495b"}
    for ax, baseline in zip(axes, baselines):
        cur = ranking_df[ranking_df["baseline"] == baseline].copy()
        colors = [color_map.get(int(v), "#666666") for v in cur["patrol_mc_use_excess"]]
        ax.scatter(
            cur["exposure_improve_pct_vs_hotspots_mean"],
            cur["response_improve_pct_vs_hotspots_mean"],
            c=colors,
            s=70,
            alpha=0.85,
        )
        for _, row in cur.iterrows():
            ax.annotate(
                str(row["config_id"]),
                (
                    float(row["exposure_improve_pct_vs_hotspots_mean"]),
                    float(row["response_improve_pct_vs_hotspots_mean"]),
                ),
                fontsize=8,
                xytext=(3, 3),
                textcoords="offset points",
            )
        ax.axhline(0.0, color="black", linewidth=1.0)
        ax.axvline(0.0, color="black", linewidth=1.0)
        ax.set_title(str(baseline))
        ax.set_xlabel("Exposure improve vs hotspots (%)")
        ax.grid(True, alpha=0.3)
    axes[0].set_ylabel("Response improve vs hotspots (%)")
    path = outdir / "sestpp_monte_carlo_tuning_tradeoff_lab.png"
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def _write_report(
    *,
    outdir: Path,
    reference_summary_df: pd.DataFrame,
    ranking_df: pd.DataFrame,
    args: argparse.Namespace,
) -> Path:
    lines = [
        "# SESTPP Monte Carlo Point Generation Tuning Sweep",
        "",
        "This sweep compares Monte Carlo patrol-point generation settings against the",
        "hotspot reference separately for each baseline.",
        "",
        "## Sweep",
        f"- Baselines: `{args.baselines}`",
        f"- Runs: `{int(args.num_runs)}` starting at seed `{int(args.seed_start)}`",
        f"- Rollouts: `{args.mc_rollout_values}`",
        f"- Max events / rollout: `{args.mc_max_events_values}`",
        f"- Use excess: `{args.mc_use_excess_values}`",
        "",
        "## Hotspot Reference",
    ]
    if reference_summary_df.empty:
        lines.append("- No hotspot reference rows were generated.")
    else:
        for _, row in reference_summary_df.iterrows():
            lines.append(
                (
                    f"- `{row['baseline']}`: exposure={row['value_weighted_exposure_mean']:.3f}, "
                    f"response={row['mean_response_time_s_mean']:.3f}s, "
                    f"comm={row['boundary_message_count_mean']:.1f}"
                )
            )
    lines.append("")
    lines.append("## Top Configs")
    if ranking_df.empty:
        lines.append("- No ranking rows were generated.")
    else:
        for baseline, group in ranking_df.groupby("baseline", sort=True):
            top = group.iloc[0]
            lines.append(
                (
                    f"- `{baseline}` best `{top['config_id']}`: "
                    f"rollouts={int(top['patrol_mc_rollouts'])}, "
                    f"max_events={int(top['patrol_mc_max_events_per_rollout'])}, "
                    f"use_excess={bool(int(top['patrol_mc_use_excess']))}, "
                    f"exposure_improve={top['exposure_improve_pct_vs_hotspots_mean']:.3f}%, "
                    f"response_improve={top['response_improve_pct_vs_hotspots_mean']:.3f}%, "
                    f"comm_change={top['comm_change_pct_vs_hotspots_mean']:.3f}%"
                )
            )
    report_path = outdir / "SESTPP_MONTE_CARLO_TUNING_SWEEP_README.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def _smoke_configs(configs: List[dict]) -> List[dict]:
    if len(configs) <= 2:
        return list(configs)
    return [configs[0], configs[-1]]


def _run_smoke(args: argparse.Namespace, outdir: Path) -> pd.DataFrame:
    smoke_outdir = outdir / "smoke"
    smoke_outdir.mkdir(parents=True, exist_ok=True)
    smoke_args = argparse.Namespace(**vars(args))
    smoke_args.num_runs = 2
    smoke_args.t_end = 600.0
    base_params = _build_base_params(smoke_args)
    baselines = _parse_csv_list(smoke_args.baselines)
    configs = _smoke_configs(_build_grid(smoke_args))
    reference_df = _run_reference(
        num_runs=int(smoke_args.num_runs),
        seed_start=int(smoke_args.seed_start),
        base_params=base_params,
        baselines=baselines,
    )
    mc_runs_df = _run_mc_configs(
        num_runs=int(smoke_args.num_runs),
        seed_start=int(smoke_args.seed_start),
        base_params=base_params,
        baselines=baselines,
        configs=configs,
    )
    pd.concat([reference_df, mc_runs_df], ignore_index=True).to_csv(
        smoke_outdir / "sestpp_monte_carlo_tuning_runs_lab_smoke.csv",
        index=False,
    )
    return mc_runs_df


def main() -> None:
    parser = argparse.ArgumentParser(description="Lab tuning sweep for Monte Carlo SESTPP patrol-point generation")
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
    parser.add_argument("--mc-rollout-values", type=str, default="32,64,128")
    parser.add_argument("--mc-max-events-values", type=str, default="12,24,36")
    parser.add_argument("--mc-use-excess-values", type=str, default="true,false")
    parser.add_argument("--limit-configs", type=int, default=0)
    parser.add_argument("--outdir", type=str, default="results/sestpp_monte_carlo_tuning_sweep_lab")
    parser.add_argument("--with-smoke-check", action="store_true")
    parser.add_argument("--smoke-only", action="store_true")
    args, config_meta = parse_args_with_config(parser, aliases=MC_TUNING_SWEEP_CONFIG_ALIASES)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    if bool(args.with_smoke_check) or bool(args.smoke_only):
        print("[check] running Monte Carlo tuning sweep smoke", flush=True)
        smoke_df = _run_smoke(args, outdir)
        print(f"[check] smoke completed rows={len(smoke_df)}", flush=True)
        if bool(args.smoke_only):
            print("[done] smoke-only requested; exiting", flush=True)
            return

    baselines = _parse_csv_list(args.baselines)
    if not baselines:
        raise ValueError("No baselines selected.")
    configs = _build_grid(args)
    if not configs:
        raise ValueError("No Monte Carlo configs generated from the sweep grid.")

    base_params = _build_base_params(args)
    reference_df = _run_reference(
        num_runs=int(args.num_runs),
        seed_start=int(args.seed_start),
        base_params=base_params,
        baselines=baselines,
    )
    mc_runs_df = _run_mc_configs(
        num_runs=int(args.num_runs),
        seed_start=int(args.seed_start),
        base_params=base_params,
        baselines=baselines,
        configs=configs,
    )

    all_runs_df = pd.concat([reference_df, mc_runs_df], ignore_index=True)
    summary_df = build_summary(all_runs_df)
    reference_summary_df = summary_df[summary_df["config_id"] == "HOTSPOT_REF"].copy()
    delta_df = build_paired_deltas(reference_df, mc_runs_df)
    delta_summary_df = build_delta_summary(delta_df)
    ranking_df = build_ranking(delta_summary_df)

    runs_path = outdir / "sestpp_monte_carlo_tuning_runs_lab.csv"
    summary_path = outdir / "sestpp_monte_carlo_tuning_summary_lab.csv"
    delta_path = outdir / "sestpp_monte_carlo_tuning_deltas_lab.csv"
    delta_summary_path = outdir / "sestpp_monte_carlo_tuning_delta_summary_lab.csv"
    ranking_path = outdir / "sestpp_monte_carlo_tuning_ranking_lab.csv"
    manifest_path = outdir / "sestpp_monte_carlo_tuning_manifest_lab.json"

    all_runs_df.to_csv(runs_path, index=False)
    summary_df.to_csv(summary_path, index=False)
    delta_df.to_csv(delta_path, index=False)
    delta_summary_df.to_csv(delta_summary_path, index=False)
    ranking_df.to_csv(ranking_path, index=False)

    plot_path = _plot_tradeoff(ranking_df, outdir)
    report_path = _write_report(
        outdir=outdir,
        reference_summary_df=reference_summary_df,
        ranking_df=ranking_df,
        args=args,
    )
    write_resolved_config_manifest(
        manifest_path,
        script="run_sestpp_monte_carlo_tuning_sweep_lab.py",
        args=args,
        config_meta=config_meta,
        extra={
            "baselines": baselines,
            "num_configs": int(len(configs)),
            "plot_path": str(plot_path) if plot_path is not None else "",
            "report_path": str(report_path),
        },
    )

    print(f"[done] wrote outputs to: {outdir}")
    print(f"- {runs_path}")
    print(f"- {summary_path}")
    print(f"- {delta_path}")
    print(f"- {delta_summary_path}")
    print(f"- {ranking_path}")
    print(f"- {manifest_path}")
    print(f"- {report_path}")
    if plot_path is not None:
        print(f"- {plot_path}")


if __name__ == "__main__":
    main()
