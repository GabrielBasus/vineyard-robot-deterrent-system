from __future__ import annotations

from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import pandas as pd


RESULTS_DIR = Path("results")


def _pick_existing(candidates: Iterable[str]) -> Path | None:
    for c in candidates:
        p = Path(c)
        if p.exists():
            return p
    return None


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
    g = (
        runs.groupby(["scenario_id", "baseline"], as_index=False)[metric]
        .mean()
        .pivot(index="baseline", columns="scenario_id", values=metric)
    )
    if g.empty:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    g = g.reindex(["reactive", "prediction_only", "proposed"]).dropna(how="all")
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


def main() -> None:
    runs_path = _pick_existing(
        [
            "baseline_runs_24h_sweep_parallel.csv",
            "baseline_runs_24h_sweep_parallel_fast.csv",
            "baseline_runs_24h_sweep.csv",
        ]
    )
    summary_path = _pick_existing(
        [
            "thesis_summary_24h_sweep_parallel.csv",
            "thesis_summary_24h_sweep_parallel_fast.csv",
            "thesis_summary_24h_sweep.csv",
        ]
    )

    if runs_path is None:
        raise FileNotFoundError("Could not find any baseline_runs CSV.")
    if summary_path is None:
        raise FileNotFoundError("Could not find any thesis_summary CSV.")

    runs = pd.read_csv(runs_path)
    summary = pd.read_csv(summary_path)
    print(f"[info] runs source: {runs_path}")
    print(f"[info] summary source: {summary_path}")
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

    # Tradeoff scatter per scenario.
    for sc in sorted(runs["scenario_id"].dropna().unique()):
        safe = sc.replace(" ", "_").replace("/", "_")
        _scatter_tradeoff(runs, sc, f"tradeoff_exposure_vs_response_{safe}.png")

    # Summary-driven plots.
    _winner_counts(summary, "winner_count_by_baseline.png")
    _rank_heatmap(summary, "mean_rank_heatmap.png")

    print(f"[done] plots written to: {RESULTS_DIR.resolve()}")


if __name__ == "__main__":
    main()
