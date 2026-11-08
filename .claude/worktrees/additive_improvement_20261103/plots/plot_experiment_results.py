from __future__ import annotations

from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import pandas as pd
import numpy as np


RESULTS_DIR = Path("results")
ARCHIVE_OUTPUTS_DIR = Path("etc/archive_outputs")


def _pick_existing(candidates: Iterable[str]) -> Path | None:
    for c in candidates:
        for base in (Path("."), ARCHIVE_OUTPUTS_DIR):
            p = base / c
            if p.exists():
                return p
    return None


def _pick_latest_by_glob(pattern: str) -> Path | None:
    matches: list[Path] = []
    for base in (Path("."), ARCHIVE_OUTPUTS_DIR):
        matches.extend(base.glob(pattern))
    matches = sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _suffix_from_runs_path(runs_path: Path) -> str:
    name = runs_path.name
    prefix = "baseline_runs_24h_sweep_parallel"
    if not name.startswith(prefix):
        return ""
    suffix = name[len(prefix):]
    if suffix.endswith(".csv"):
        suffix = suffix[:-4]
    return suffix


def _ensure_results_dir() -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    return RESULTS_DIR


def _save(fig, out_name: str) -> None:
    out = _ensure_results_dir() / out_name
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    plt.close(fig)
    print(f"[saved] {out}")


def _boxplot_by_baseline_and_scenario(runs: pd.DataFrame, metric: str, title: str, out_name: str) -> None:
    if metric not in runs.columns:
        print(f"[skip] missing metric column: {metric}")
        return
    scenarios = sorted(runs["scenario_id"].dropna().unique())
    if not scenarios:
        return

    fig, axes = plt.subplots(1, len(scenarios), figsize=(5 * len(scenarios), 4), sharey=True)
    if len(scenarios) == 1:
        axes = [axes]

    for ax, sc in zip(axes, scenarios):
        d = runs[runs["scenario_id"] == sc]
        data = []
        labels = []
        for b in ["reactive", "prediction_only", "proposed"]:
            v = d[d["baseline"] == b][metric].dropna()
            if len(v) > 0:
                data.append(v.values)
                labels.append(b)
        if data:
            ax.boxplot(data, tick_labels=labels, showfliers=False)
        ax.set_title(sc)
        ax.set_xlabel("baseline")
    axes[0].set_ylabel(metric)
    fig.suptitle(title)
    _save(fig, out_name)


def _bar_mean_by_baseline_and_scenario(runs: pd.DataFrame, metric: str, title: str, out_name: str) -> None:
    if metric not in runs.columns:
        print(f"[skip] missing metric column: {metric}")
        return
    g = (
        runs.groupby(["scenario_id", "baseline"], as_index=False)[metric]
        .mean()
        .pivot(index="baseline", columns="scenario_id", values=metric)
    )
    if g.empty:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    g = g.reindex(["reactive", "prediction_only", "proposed"]).dropna(how="all")
    if g.empty or len(g.columns) == 0:
        plt.close(fig)
        print(f"[skip] no plottable values for metric: {metric}")
        return
    g.plot(kind="bar", ax=ax)
    ax.set_title(title)
    ax.set_ylabel(f"mean {metric}")
    ax.set_xlabel("baseline")
    ax.legend(title="scenario", loc="best")
    _save(fig, out_name)


def _scatter_tradeoff(runs: pd.DataFrame, scenario: str, out_name: str) -> None:
    d = runs[runs["scenario_id"] == scenario]
    if d.empty:
        return
    agg = d.groupby("baseline", as_index=False).agg(
        exposure=("value_weighted_exposure", "mean"),
        response=("mean_response_time_s", "mean"),
        comm=("boundary_message_count", "mean"),
    )

    fig, ax = plt.subplots(figsize=(6, 5))
    for _, r in agg.iterrows():
        ax.scatter(r["exposure"], r["response"], s=max(20.0, r["comm"] / 8.0), label=r["baseline"], alpha=0.8)
        ax.annotate(r["baseline"], (r["exposure"], r["response"]), textcoords="offset points", xytext=(5, 3), fontsize=9)
    ax.set_title(f"Tradeoff: Exposure vs Response ({scenario})")
    ax.set_xlabel("value_weighted_exposure (mean)")
    ax.set_ylabel("mean_response_time_s (mean)")
    ax.grid(True, alpha=0.3)
    _save(fig, out_name)


def _winner_counts(summary: pd.DataFrame, out_name: str) -> None:
    d = summary[summary["rank_overall"] == 1].copy()
    if d.empty:
        return
    c = d["baseline"].value_counts().reindex(["reactive", "prediction_only", "proposed"]).fillna(0)
    fig, ax = plt.subplots(figsize=(6, 4))
    c.plot(kind="bar", ax=ax)
    ax.set_title("Winner Count (rank_overall = 1)")
    ax.set_xlabel("baseline")
    ax.set_ylabel("count")
    _save(fig, out_name)


def _rank_heatmap(summary: pd.DataFrame, out_name: str) -> None:
    p = summary.pivot_table(
        index="scenario_id",
        columns="baseline",
        values="rank_overall",
        aggfunc="mean",
    )
    if p.empty:
        return
    p = p.reindex(columns=["reactive", "prediction_only", "proposed"])
    fig, ax = plt.subplots(figsize=(7, 3.8))
    im = ax.imshow(p.values, aspect="auto")
    ax.set_xticks(range(len(p.columns)))
    ax.set_xticklabels(p.columns)
    ax.set_yticks(range(len(p.index)))
    ax.set_yticklabels(p.index)
    ax.set_title("Mean rank_overall (lower is better)")
    for i in range(p.shape[0]):
        for j in range(p.shape[1]):
            v = p.values[i, j]
            if pd.notna(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=9)
    fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    _save(fig, out_name)


def _line_metric_over_time(over_time: pd.DataFrame, metric_col: str, title: str, out_name: str) -> None:
    if metric_col not in over_time.columns:
        print(f"[skip] missing over-time metric column: {metric_col}")
        return
    d = over_time.copy()
    d = d.dropna(subset=["scenario_id", "baseline", "t_s"])
    if d.empty:
        return

    scenarios = sorted(d["scenario_id"].unique())
    fig, axes = plt.subplots(1, len(scenarios), figsize=(6 * len(scenarios), 4), sharey=True)
    if len(scenarios) == 1:
        axes = [axes]

    for ax, sc in zip(axes, scenarios):
        ds = d[d["scenario_id"] == sc]
        for b in ["reactive", "prediction_only", "proposed"]:
            db = ds[ds["baseline"] == b]
            if db.empty:
                continue
            x = db["t_s"].values / 3600.0
            y = db[metric_col].values
            ax.plot(x, y, label=b, linewidth=1.8)
        ax.set_title(sc)
        ax.set_xlabel("time [hours]")
        ax.grid(True, alpha=0.3)
    axes[0].set_ylabel(metric_col)
    axes[0].legend(loc="best")
    fig.suptitle(title)
    _save(fig, out_name)


def _improvement_over_time(over_time: pd.DataFrame, out_name: str) -> None:
    d = over_time.copy()
    col = "proposed_vs_prediction_only_exposure_improvement_pct"
    if col not in d.columns:
        print(f"[skip] missing over-time improvement column: {col}")
        return
    d = d.dropna(subset=["scenario_id", "t_s", col])
    if d.empty:
        return

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for sc in sorted(d["scenario_id"].unique()):
        ds = d[d["scenario_id"] == sc]
        x = ds["t_s"].values / 3600.0
        y = ds[col].values
        # Over-time output repeats the same curve for each baseline row; keep one baseline for clean plot.
        if "baseline" in ds.columns:
            ds = ds[ds["baseline"] == "proposed"]
            x = ds["t_s"].values / 3600.0
            y = ds[col].values
        if len(x) > 0:
            ax.plot(x, y, label=sc, linewidth=1.8)
    ax.axhline(0.0, color="k", linestyle="--", linewidth=1.0, alpha=0.7)
    ax.set_title("Exposure Improvement of Proposed vs Prediction-Only Over Time")
    ax.set_xlabel("time [hours]")
    ax.set_ylabel("improvement [%]")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    _save(fig, out_name)


def _rolling_improvement_from_runs(runs: pd.DataFrame, out_name: str) -> None:
    req = {"scenario_id", "time_horizon_h", "baseline", "value_weighted_exposure"}
    if not req.issubset(runs.columns):
        print("[skip] missing columns for horizon improvement plot")
        return
    g = runs.groupby(["scenario_id", "time_horizon_h", "baseline"], as_index=False)["value_weighted_exposure"].mean()
    piv = g.pivot_table(index=["scenario_id", "time_horizon_h"], columns="baseline", values="value_weighted_exposure", aggfunc="first")
    if not {"proposed", "prediction_only"}.issubset(piv.columns):
        return
    piv = piv.reset_index()
    piv["improvement_pct"] = 100.0 * (piv["prediction_only"] - piv["proposed"]) / piv["prediction_only"].replace(0.0, np.nan)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for sc in sorted(piv["scenario_id"].unique()):
        ds = piv[piv["scenario_id"] == sc].sort_values("time_horizon_h")
        ax.plot(ds["time_horizon_h"], ds["improvement_pct"], marker="o", linewidth=1.8, label=sc)
    ax.axhline(0.0, color="k", linestyle="--", linewidth=1.0, alpha=0.7)
    ax.set_title("Proposed vs Prediction-Only Exposure Improvement by Horizon")
    ax.set_xlabel("simulation horizon [hours]")
    ax.set_ylabel("improvement [%]")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    _save(fig, out_name)


def main() -> None:
    runs_path = _pick_latest_by_glob("baseline_runs_24h_sweep_parallel*.csv")
    if runs_path is None:
        runs_path = _pick_existing(["baseline_runs_24h_sweep.csv"])

    if runs_path is None:
        raise FileNotFoundError("Could not find any baseline_runs CSV.")

    summary_path = None
    over_time_path = None
    if "baseline_runs_24h_sweep_parallel" in runs_path.name:
        suffix = _suffix_from_runs_path(runs_path)
        summary_path = _pick_existing([f"thesis_summary_24h_sweep_parallel{suffix}.csv"])
        over_time_path = _pick_existing([f"baseline_over_time_24h_sweep_parallel{suffix}.csv"])
    if summary_path is None:
        summary_path = _pick_latest_by_glob("thesis_summary_24h_sweep_parallel*.csv")
    if summary_path is None:
        summary_path = _pick_existing(["thesis_summary_24h_sweep.csv"])
    if summary_path is None:
        raise FileNotFoundError("Could not find any thesis_summary CSV.")

    runs = pd.read_csv(runs_path)
    summary = pd.read_csv(summary_path)
    over_time = pd.read_csv(over_time_path) if over_time_path is not None else pd.DataFrame()
    print(f"[info] runs source: {runs_path}")
    print(f"[info] summary source: {summary_path}")
    if over_time_path is not None:
        print(f"[info] over-time source: {over_time_path}")
    print(f"[info] runs rows={len(runs)} summary rows={len(summary)}")

    # Boxplots for key metrics.
    _boxplot_by_baseline_and_scenario(
        runs, "value_weighted_exposure",
        "Distribution of Value-Weighted Exposure by Baseline",
        "boxplot_exposure.png",
    )
    _boxplot_by_baseline_and_scenario(
        runs, "mean_response_time_s",
        "Distribution of Mean Response Time by Baseline",
        "boxplot_response_time.png",
    )
    _boxplot_by_baseline_and_scenario(
        runs, "tasks_per_unit_distance",
        "Distribution of Task Efficiency by Baseline",
        "boxplot_task_efficiency.png",
    )
    _boxplot_by_baseline_and_scenario(
        runs, "boundary_message_count",
        "Distribution of Communication Overhead by Baseline",
        "boxplot_comm_overhead.png",
    )
    _boxplot_by_baseline_and_scenario(
        runs, "robot_task_utilization_mean",
        "Distribution of Robot Task Utilization (Fraction of Time with Assigned Task)",
        "boxplot_robot_task_utilization.png",
    )
    _boxplot_by_baseline_and_scenario(
        runs, "robot_idle_fraction_mean",
        "Distribution of Robot Idle Fraction",
        "boxplot_robot_idle_fraction.png",
    )
    _boxplot_by_baseline_and_scenario(
        runs, "robots_zero_distance_count",
        "Distribution of Zero-Distance Robots per Run",
        "boxplot_robots_zero_distance_count.png",
    )

    # Mean bar charts by scenario.
    _bar_mean_by_baseline_and_scenario(
        runs, "value_weighted_exposure",
        "Mean Exposure by Baseline and Scenario",
        "bar_mean_exposure.png",
    )
    _bar_mean_by_baseline_and_scenario(
        runs, "mean_response_time_s",
        "Mean Response Time by Baseline and Scenario",
        "bar_mean_response_time.png",
    )
    _bar_mean_by_baseline_and_scenario(
        runs, "tasks_per_unit_distance",
        "Mean Task Efficiency by Baseline and Scenario",
        "bar_mean_task_efficiency.png",
    )
    _bar_mean_by_baseline_and_scenario(
        runs, "boundary_message_count",
        "Mean Communication Overhead by Baseline and Scenario",
        "bar_mean_comm_overhead.png",
    )
    _bar_mean_by_baseline_and_scenario(
        runs, "robot_task_utilization_mean",
        "Mean Robot Task Utilization by Baseline and Scenario",
        "bar_mean_robot_task_utilization.png",
    )
    _bar_mean_by_baseline_and_scenario(
        runs, "robot_idle_fraction_mean",
        "Mean Robot Idle Fraction by Baseline and Scenario",
        "bar_mean_robot_idle_fraction.png",
    )
    _bar_mean_by_baseline_and_scenario(
        runs, "robots_zero_distance_count",
        "Mean Zero-Distance Robots by Baseline and Scenario",
        "bar_mean_robots_zero_distance_count.png",
    )

    # Forecast quality plots (if forecast metrics are available in run CSV).
    _boxplot_by_baseline_and_scenario(
        runs, "forecast_recall_at_k",
        "Distribution of Forecast Recall@K by Baseline",
        "boxplot_forecast_recall_at_k.png",
    )
    _boxplot_by_baseline_and_scenario(
        runs, "forecast_precision_at_k",
        "Distribution of Forecast Precision@K by Baseline",
        "boxplot_forecast_precision_at_k.png",
    )
    _boxplot_by_baseline_and_scenario(
        runs, "forecast_lead_time_s",
        "Distribution of Forecast Lead Time by Baseline",
        "boxplot_forecast_lead_time_s.png",
    )
    _bar_mean_by_baseline_and_scenario(
        runs, "forecast_recall_at_k",
        "Mean Forecast Recall@K by Baseline and Scenario",
        "bar_mean_forecast_recall_at_k.png",
    )
    _bar_mean_by_baseline_and_scenario(
        runs, "forecast_precision_at_k",
        "Mean Forecast Precision@K by Baseline and Scenario",
        "bar_mean_forecast_precision_at_k.png",
    )
    _bar_mean_by_baseline_and_scenario(
        runs, "forecast_lead_time_s",
        "Mean Forecast Lead Time by Baseline and Scenario",
        "bar_mean_forecast_lead_time_s.png",
    )

    # Tradeoff scatter per scenario.
    for sc in sorted(runs["scenario_id"].dropna().unique()):
        safe = sc.replace(" ", "_").replace("/", "_")
        _scatter_tradeoff(runs, sc, f"tradeoff_exposure_vs_response_{safe}.png")

    # Summary-driven plots.
    _winner_counts(summary, "winner_count_by_baseline.png")
    _rank_heatmap(summary, "mean_rank_heatmap.png")

    # Time-variation plots (if over-time CSV exists).
    if not over_time.empty:
        _line_metric_over_time(
            over_time,
            "value_weighted_exposure_mean",
            "Cumulative Value-Weighted Exposure Over Time",
            "line_exposure_over_time.png",
        )
        _line_metric_over_time(
            over_time,
            "exposure_rate_per_hour_so_far_mean",
            "Exposure Rate (So Far) Over Time",
            "line_exposure_rate_over_time.png",
        )
        _line_metric_over_time(
            over_time,
            "tasks_per_hour_so_far_mean",
            "Task Throughput (So Far) Over Time",
            "line_tasks_per_hour_over_time.png",
        )
        _line_metric_over_time(
            over_time,
            "model_deterring_accepted_mean",
            "Accepted Model-Scored Deterring Tasks Over Time",
            "line_model_deterring_accepted_over_time.png",
        )
        _line_metric_over_time(
            over_time,
            "fleet_task_assigned_fraction_mean",
            "Fleet Task Assignment Fraction Over Time",
            "line_fleet_task_assigned_fraction_over_time.png",
        )
        _line_metric_over_time(
            over_time,
            "fleet_moving_fraction_mean",
            "Fleet Moving Fraction Over Time",
            "line_fleet_moving_fraction_over_time.png",
        )
        _line_metric_over_time(
            over_time,
            "fleet_idle_no_task_fraction_mean",
            "Fleet Idle-with-No-Task Fraction Over Time",
            "line_fleet_idle_no_task_fraction_over_time.png",
        )
        _line_metric_over_time(
            over_time,
            "fleet_task_engagement_fraction_so_far_mean",
            "Fleet Task Engagement (Cumulative) Over Time",
            "line_fleet_task_engagement_so_far_over_time.png",
        )
        _improvement_over_time(over_time, "line_proposed_vs_prediction_improvement_over_time.png")

    _rolling_improvement_from_runs(runs, "line_improvement_by_horizon.png")

    print(f"[done] plots written to: {RESULTS_DIR.resolve()}")


if __name__ == "__main__":
    main()
