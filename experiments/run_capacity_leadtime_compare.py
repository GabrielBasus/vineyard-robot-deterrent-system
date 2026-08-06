from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import testbench.run_testbench as bench


DEFAULT_CONFIG = Path("testbench/thesis_compare_unc_vs_capacity_leadtime_nominal_24h.json")
DEFAULT_METRICS: tuple[str, ...] = (
    "native_value_weighted_exposure",
    "native_mean_response_time_s",
    "native_predictive_completed_fraction",
    "native_robot_predictive_fraction_mean",
    "native_reactive_load_factor_estimate",
    "native_urgent_reactive_override_total",
    "native_reactive_completed_fraction",
    "native_predictive_generated_total",
    "native_predictive_admitted_total",
    "native_predictive_completed_total",
    "native_predictive_distinct_generated_total",
    "native_predictive_distinct_admitted_total",
    "native_predictive_distinct_completed_total",
    "native_predictive_expired_total",
    "native_predictive_expired_fraction",
    "native_predictive_risk_adjusted_candidates_total",
    "native_predictive_risk_adjusted_rejected_confidence_total",
    "native_predictive_risk_adjusted_rejected_slack_total",
    "native_predictive_risk_adjusted_rejected_utility_total",
    "native_predictive_risk_adjusted_rejected_cost_ratio_total",
    "native_predictive_risk_adjusted_mean_confidence",
    "native_predictive_risk_adjusted_mean_utility",
    "native_predictive_risk_adjusted_rho_eff_mean",
)
COLOR_MAP = {
    "unc": "#1f77b4",
    "res_0p25": "#d62728",
    "res_0p25_leadtime": "#2ca02c",
    "res_adaptive_leadtime_0p25": "#ff7f0e",
    "res_adaptive_leadtime_gate_025": "#ff7f0e",
    "res_adaptive_leadtime_gate_035": "#8c564b",
    "res_adaptive_leadtime_gate_045": "#e377c2",
    "res_feasible_0p25": "#2ca02c",
    "res_idle_feasible_0p25": "#ff7f0e",
    "res_confidence_0p25": "#9467bd",
    "res_idle_feasible_confidence_0p25": "#8c564b",
    "res_risk_adjusted_0p25": "#7f7f7f",
    "res_time_score_0p25": "#17becf",
    "res_time_score_v2_0p25": "#bcbd22",
}


def _load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _metric_spec(metric_name: str) -> bench.MetricSpec:
    spec = bench.METRIC_LIBRARY.get(metric_name)
    if spec is None:
        raise KeyError(f"Unknown metric {metric_name!r}")
    return spec


def _resolve_outdir(config: dict[str, Any]) -> Path:
    outputs = dict(config.get("outputs") or {})
    return Path(str(outputs.get("outdir") or "results/testbench/capacity_leadtime_compare"))


def _run_testbench(config_path: Path, *, max_workers: int) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "testbench.run_testbench",
            "--config",
            str(config_path),
            "--max-workers",
            str(int(max_workers)),
        ],
        check=True,
    )


def _plot_per_run_final_metrics(
    per_run_df: pd.DataFrame,
    *,
    systems: list[str],
    metrics: list[str],
    output_path: Path,
    title: str,
) -> None:
    available_metrics = [metric for metric in metrics if metric in per_run_df.columns]
    if not available_metrics:
        raise ValueError("No requested metrics were found in per_run_metrics.csv")

    nplots = len(available_metrics)
    ncols = 2
    nrows = int(np.ceil(float(nplots) / float(ncols)))
    fig, axes = plt.subplots(nrows, ncols, figsize=(16, 4.5 * nrows), squeeze=False)
    axes_flat = axes.ravel()

    x_tick_labels = [str(int(seed)) for seed in per_run_df["seed"].drop_duplicates().tolist()]
    x_positions = np.arange(len(x_tick_labels), dtype=float)
    offsets = np.linspace(-0.18, 0.18, max(len(systems), 2))

    for ax, metric_name in zip(axes_flat, available_metrics):
        spec = _metric_spec(metric_name)
        for idx, system_name in enumerate(systems):
            sub = per_run_df.loc[per_run_df["system"] == system_name, ["seed", metric_name]].copy()
            if sub.empty:
                continue
            sub = sub.sort_values("seed")
            values = pd.to_numeric(sub[metric_name], errors="coerce").to_numpy(dtype=float)
            seeds = [str(int(seed)) for seed in sub["seed"].tolist()]
            pos = np.array([x_tick_labels.index(seed) for seed in seeds], dtype=float) + offsets[idx]
            color = COLOR_MAP.get(system_name)
            ax.scatter(
                pos,
                values,
                color=color,
                s=50,
                alpha=0.9,
                label=system_name if metric_name == available_metrics[0] else None,
            )
            ax.plot(pos, values, color=color, linewidth=1.3, alpha=0.7)
            finite_values = values[np.isfinite(values)]
            if finite_values.size > 0:
                ax.axhline(
                    float(np.mean(finite_values)),
                    color=color,
                    linestyle="--",
                    linewidth=1.0,
                    alpha=0.45,
                )
        ax.set_title(f"{spec.label}\n({spec.goal} better)")
        ax.set_xticks(x_positions)
        ax.set_xticklabels(x_tick_labels)
        ax.set_xlabel("Seed / Run")
        ax.grid(alpha=0.25)

    for ax in axes_flat[nplots:]:
        ax.axis("off")

    handles, labels = axes_flat[0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="upper center", ncol=len(handles), frameon=False)
    fig.suptitle(title, fontsize=14, y=0.995)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.97))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run and plot a comparison between UNC and one or more capacity-aware formulations."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--skip-run", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    config = _load_config(config_path)
    outdir = _resolve_outdir(config)

    if not args.skip_run:
        _run_testbench(config_path, max_workers=int(args.max_workers))

    per_run_csv = outdir / "per_run_metrics.csv"
    if not per_run_csv.exists():
        raise FileNotFoundError(f"Expected per-run metrics at {per_run_csv}")
    per_run_df = pd.read_csv(per_run_csv)

    systems = [str(system.get("key")) for system in list(config.get("systems") or [])]
    scenario = dict(config.get("scenario") or {})
    system_titles = [str(system.get("title") or system.get("key")) for system in list(config.get("systems") or [])]
    title = (
        "Capacity-Aware Comparison Final Metrics\n"
        + ", ".join(system_titles)
        + "\n"
        + f"{int(scenario.get('num_runs', 0))} runs, horizon={scenario.get('duration_s', 'n/a')} s, "
        + f"warmup={scenario.get('warmup_s', 'n/a')} s"
    )
    plot_path = outdir / "per_run_final_metric_compare.png"
    _plot_per_run_final_metrics(
        per_run_df,
        systems=systems,
        metrics=list(DEFAULT_METRICS),
        output_path=plot_path,
        title=title,
    )
    print(f"[capacity-leadtime-compare] wrote {plot_path}")
    print(f"[capacity-leadtime-compare] source {per_run_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
