from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_CONFIG = Path("testbench/thesis_compare_predictive_utility_calibration_24h.json")
DEFAULT_FINAL_METRICS: tuple[str, ...] = (
    "native_value_weighted_exposure",
    "native_mean_response_time_s",
    "native_reactive_mean_response_time_s",
    "native_predictive_completion_ratio",
    "native_predictive_confidence_mean",
    "native_predictive_success_ratio",
    "native_predictive_false_positive_ratio",
    "native_robot_predictive_fraction_mean",
    "native_urgent_reactive_override_total",
)


def _load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_outdir(config: dict[str, Any]) -> Path:
    outputs = dict(config.get("outputs") or {})
    return Path(str(outputs.get("outdir") or "results/testbench/predictive_utility_calibration"))


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


def _system_metadata(config: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for system in list(config.get("systems") or []):
        params = dict(system.get("params") or {})
        rows.append(
            {
                "system": str(system.get("key")),
                "title": str(system.get("title") or system.get("key")),
                "dispatch_policy": str(params.get("dispatch_policy", "")),
                "predictive_selection_policy": str(params.get("predictive_selection_policy", "")),
                "predictive_utility_mode": str(params.get("predictive_utility_mode", "legacy")),
                "confidence_source": str(
                    params.get(
                        "confidence_source",
                        params.get("predictive_confidence_source", ""),
                    )
                ),
                "confidence_power": _safe_float(params.get("confidence_power", params.get("predictive_confidence_power", np.nan))),
                "reservation_fraction": _safe_float(params.get("reservation_fraction", np.nan)),
            }
        )
    return pd.DataFrame(rows)


def _safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except Exception:
        return float(default)
    return out if np.isfinite(out) else float(default)


def _numeric_mean_columns(df: pd.DataFrame, columns: Iterable[str]) -> list[str]:
    out = []
    for column in columns:
        if column not in df.columns:
            continue
        values = pd.to_numeric(df[column], errors="coerce")
        if values.notna().any():
            df[column] = values
            out.append(column)
    return out


def _summarize_by(df: pd.DataFrame, *, group_cols: list[str], metrics: list[str]) -> pd.DataFrame:
    available = _numeric_mean_columns(df, metrics)
    if not available:
        return pd.DataFrame(columns=group_cols)
    grouped = df.groupby(group_cols, dropna=False)[available]
    summary = grouped.agg(["mean", "std", "count"]).reset_index()
    summary.columns = [
        "_".join(str(part) for part in col if str(part))
        if isinstance(col, tuple)
        else str(col)
        for col in summary.columns
    ]
    return summary


def _ranking_table(df: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    available = _numeric_mean_columns(df, metrics)
    if not available:
        return pd.DataFrame()
    grouped = df.groupby("system", dropna=False)[available].mean(numeric_only=True).reset_index()
    sort_cols = [
        col
        for col in (
            "native_value_weighted_exposure",
            "native_mean_response_time_s",
            "native_predictive_false_positive_ratio",
        )
        if col in grouped.columns
    ]
    ascending = [True for _ in sort_cols]
    if "native_predictive_success_ratio" in grouped.columns:
        grouped["_success_sort"] = -pd.to_numeric(grouped["native_predictive_success_ratio"], errors="coerce")
        sort_cols.append("_success_sort")
        ascending.append(True)
    if sort_cols:
        grouped = grouped.sort_values(sort_cols, ascending=ascending, kind="mergesort")
    grouped.insert(0, "rank", np.arange(1, len(grouped) + 1))
    return grouped.drop(columns=["_success_sort"], errors="ignore")


def _plot_metric_bars(df: pd.DataFrame, *, metrics: list[str], output_path: Path, title: str) -> None:
    available = _numeric_mean_columns(df, metrics)
    if not available:
        return
    systems = [str(v) for v in df["system"].drop_duplicates().tolist()]
    nplots = len(available)
    ncols = 2
    nrows = int(np.ceil(nplots / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(16, 4.2 * nrows), squeeze=False)
    axes_flat = axes.ravel()
    for ax, metric in zip(axes_flat, available):
        means = []
        for system in systems:
            values = pd.to_numeric(df.loc[df["system"] == system, metric], errors="coerce")
            means.append(float(values.mean()) if values.notna().any() else np.nan)
        ax.bar(np.arange(len(systems)), means, color="#4c78a8")
        ax.set_title(metric)
        ax.set_xticks(np.arange(len(systems)))
        ax.set_xticklabels(systems, rotation=55, ha="right")
        ax.grid(axis="y", alpha=0.25)
    for ax in axes_flat[nplots:]:
        ax.axis("off")
    fig.suptitle(title, fontsize=14)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.97))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220)
    plt.close(fig)


def _plot_group_metric(
    df: pd.DataFrame,
    *,
    group_col: str,
    metric: str,
    output_path: Path,
    title: str,
) -> None:
    if group_col not in df.columns or metric not in df.columns:
        return
    work = df[[group_col, metric]].copy()
    work[metric] = pd.to_numeric(work[metric], errors="coerce")
    work = work.dropna(subset=[metric])
    if work.empty:
        return
    means = work.groupby(group_col, dropna=False)[metric].mean().sort_values()
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(np.arange(len(means)), means.to_numpy(dtype=float), color="#59a14f")
    ax.set_xticks(np.arange(len(means)))
    ax.set_xticklabels([str(v) for v in means.index], rotation=35, ha="right")
    ax.set_title(title)
    ax.set_ylabel(metric)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220)
    plt.close(fig)


def _plot_confidence_success_proxy(df: pd.DataFrame, output_path: Path) -> None:
    x_col = "native_predictive_confidence_mean"
    y_col = "native_predictive_success_ratio"
    if x_col not in df.columns or y_col not in df.columns:
        return
    work = df[["system", x_col, y_col]].copy()
    work[x_col] = pd.to_numeric(work[x_col], errors="coerce")
    work[y_col] = pd.to_numeric(work[y_col], errors="coerce")
    work = work.dropna(subset=[x_col, y_col])
    if work.empty:
        return
    fig, ax = plt.subplots(figsize=(8, 6))
    for system, sub in work.groupby("system", dropna=False):
        ax.scatter(sub[x_col], sub[y_col], label=str(system), s=48, alpha=0.85)
    ax.plot([0.0, 1.0], [0.0, 1.0], linestyle="--", color="#999999", linewidth=1.0)
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.set_xlabel("Mean predictive confidence")
    ax.set_ylabel("Realized success proxy ratio")
    ax.set_title("Confidence vs Realized Success Proxy")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7, loc="best")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220)
    plt.close(fig)


def _plot_confidence_histogram(df: pd.DataFrame, output_path: Path) -> None:
    col = "native_predictive_confidence_mean"
    if col not in df.columns:
        return
    values = pd.to_numeric(df[col], errors="coerce").dropna().to_numpy(dtype=float)
    if values.size == 0:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(values, bins=np.linspace(0.0, 1.0, 11), color="#f28e2b", edgecolor="white")
    ax.set_xlabel("Per-run mean predictive confidence")
    ax.set_ylabel("Run count")
    ax.set_title("Predictive Confidence Histogram")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220)
    plt.close(fig)


def _plot_predictive_share_timeseries(timeseries_df: pd.DataFrame, output_path: Path) -> None:
    metric = "native_robot_predictive_fraction_mean"
    if metric not in timeseries_df.columns or "t" not in timeseries_df.columns:
        return
    work = timeseries_df[["system", "t", metric]].copy()
    work[metric] = pd.to_numeric(work[metric], errors="coerce")
    work["t"] = pd.to_numeric(work["t"], errors="coerce")
    work = work.dropna(subset=["t", metric])
    if work.empty:
        return
    fig, ax = plt.subplots(figsize=(11, 5))
    for system, sub in work.groupby("system", dropna=False):
        mean_by_t = sub.groupby("t", dropna=False)[metric].mean().reset_index()
        ax.plot(mean_by_t["t"] / 3600.0, mean_by_t[metric], label=str(system), linewidth=1.4)
    ax.set_xlabel("Simulation time (h)")
    ax.set_ylabel("Mean predictive dispatch share")
    ax.set_title("Predictive Share Over Time")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220)
    plt.close(fig)


def build_analysis_outputs(config: dict[str, Any], outdir: Path) -> dict[str, Path]:
    per_run_csv = outdir / "per_run_metrics.csv"
    if not per_run_csv.exists():
        raise FileNotFoundError(f"Expected per-run metrics at {per_run_csv}")
    per_run_df = pd.read_csv(per_run_csv)
    meta_df = _system_metadata(config)
    per_run_with_meta = per_run_df.merge(meta_df, on="system", how="left")

    metrics = list(dict.fromkeys(DEFAULT_FINAL_METRICS + tuple(config.get("outputs", {}).get("metrics", []))))
    outputs: dict[str, Path] = {}

    metadata_csv = outdir / "predictive_utility_system_metadata.csv"
    mode_csv = outdir / "predictive_utility_mode_summary.csv"
    source_csv = outdir / "confidence_source_summary.csv"
    ranking_csv = outdir / "predictive_utility_calibration_ranking.csv"

    meta_df.to_csv(metadata_csv, index=False)
    _summarize_by(per_run_with_meta, group_cols=["predictive_utility_mode"], metrics=metrics).to_csv(
        mode_csv,
        index=False,
    )
    _summarize_by(per_run_with_meta, group_cols=["confidence_source", "confidence_power"], metrics=metrics).to_csv(
        source_csv,
        index=False,
    )
    _ranking_table(per_run_with_meta, metrics=metrics).to_csv(ranking_csv, index=False)

    outputs["metadata_csv"] = metadata_csv
    outputs["mode_summary_csv"] = mode_csv
    outputs["confidence_source_summary_csv"] = source_csv
    outputs["ranking_csv"] = ranking_csv

    plot_dir = outdir / "plots"
    final_plot = plot_dir / "predictive_utility_final_metrics.png"
    mode_plot = plot_dir / "utility_mode_exposure.png"
    source_plot = plot_dir / "confidence_source_success_proxy.png"
    conf_success_plot = plot_dir / "confidence_vs_success_proxy.png"
    conf_hist_plot = plot_dir / "confidence_histogram.png"
    share_plot = plot_dir / "predictive_share_over_time.png"

    _plot_metric_bars(
        per_run_with_meta,
        metrics=list(DEFAULT_FINAL_METRICS),
        output_path=final_plot,
        title="Predictive Utility Calibration Final Metrics",
    )
    _plot_group_metric(
        per_run_with_meta,
        group_col="predictive_utility_mode",
        metric="native_value_weighted_exposure",
        output_path=mode_plot,
        title="Value-Weighted Exposure by Utility Mode",
    )
    _plot_group_metric(
        per_run_with_meta,
        group_col="confidence_source",
        metric="native_predictive_success_ratio",
        output_path=source_plot,
        title="Success Proxy by Confidence Source",
    )
    _plot_confidence_success_proxy(per_run_with_meta, conf_success_plot)
    _plot_confidence_histogram(per_run_with_meta, conf_hist_plot)

    timeseries_csv = outdir / "per_run_timeseries.csv"
    if timeseries_csv.exists():
        _plot_predictive_share_timeseries(pd.read_csv(timeseries_csv), share_plot)

    outputs["final_metrics_plot"] = final_plot
    outputs["utility_mode_plot"] = mode_plot
    outputs["confidence_source_plot"] = source_plot
    outputs["confidence_success_plot"] = conf_success_plot
    outputs["confidence_histogram_plot"] = conf_hist_plot
    outputs["predictive_share_plot"] = share_plot
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run and analyze the deterministic-vs-Bernoulli predictive utility calibration comparison."
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

    outputs = build_analysis_outputs(config, outdir)
    for label, path in outputs.items():
        exists = "ok" if path.exists() else "skipped"
        print(f"[predictive-utility-calibration] {label}: {path} ({exists})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
