from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


METHODS = ["frozen_greedy", "hungarian", "auction", "cbba"]
BASELINES = ["reactive", "prediction_only", "proposed"]


def _ci95(series: pd.Series) -> float:
    x = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    n = x.size
    if n <= 1:
        return float("nan")
    return float(1.96 * np.std(x, ddof=1) / np.sqrt(n))


def _plot_metric_by_baseline(summary_df: pd.DataFrame, metric: str, ylabel: str, outpath: Path) -> None:
    fig, axes = plt.subplots(1, len(BASELINES), figsize=(15, 4), sharey=False)
    if len(BASELINES) == 1:
        axes = [axes]

    for ax, baseline in zip(axes, BASELINES):
        sub = summary_df[summary_df["baseline"] == baseline].copy()
        means = []
        errs = []
        for method in METHODS:
            row = sub[sub["assignment_method"] == method]
            means.append(float(row[f"{metric}_mean"].iloc[0]) if not row.empty else np.nan)
            errs.append(float(row[f"{metric}_ci95"].iloc[0]) if not row.empty else np.nan)

        x = np.arange(len(METHODS))
        ax.bar(x, means, yerr=errs, capsize=3)
        ax.set_xticks(x)
        ax.set_xticklabels(METHODS, rotation=20)
        ax.set_title(baseline)
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.2)

    fig.tight_layout()
    fig.savefig(outpath, dpi=160)
    plt.close(fig)


def _plot_proposed_minus_prediction(runs_df: pd.DataFrame, outpath: Path) -> pd.DataFrame:
    rows = []
    for method in METHODS:
        p = runs_df[(runs_df["baseline"] == "proposed") & (runs_df["assignment_method"] == method)]
        q = runs_df[(runs_df["baseline"] == "prediction_only") & (runs_df["assignment_method"] == method)]
        pair = p.merge(q, on=["seed", "run_idx", "assignment_method"], suffixes=("_p", "_q"), how="inner")
        if pair.empty:
            continue
        den_e = pair["value_weighted_exposure_q"].replace(0.0, np.nan)
        den_r = pair["mean_response_time_s_q"].replace(0.0, np.nan)
        den_c = pair["boundary_message_count_q"].replace(0.0, np.nan)
        exposure_imp = 100.0 * (pair["value_weighted_exposure_q"] - pair["value_weighted_exposure_p"]) / den_e
        response_imp = 100.0 * (pair["mean_response_time_s_q"] - pair["mean_response_time_s_p"]) / den_r
        comm_inc = 100.0 * (pair["boundary_message_count_p"] - pair["boundary_message_count_q"]) / den_c
        rows.append(
            {
                "assignment_method": method,
                "exposure_improve_pct": float(np.nanmean(exposure_imp)),
                "exposure_improve_ci95": _ci95(exposure_imp),
                "response_improve_pct": float(np.nanmean(response_imp)),
                "response_improve_ci95": _ci95(response_imp),
                "comm_increase_pct": float(np.nanmean(comm_inc)),
                "comm_increase_ci95": _ci95(comm_inc),
            }
        )

    df = pd.DataFrame(rows)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    metrics = [
        ("exposure_improve_pct", "exposure_improve_ci95", "Exposure improve (%)"),
        ("response_improve_pct", "response_improve_ci95", "Response improve (%)"),
        ("comm_increase_pct", "comm_increase_ci95", "Comm increase (%)"),
    ]

    for ax, (m, e, title) in zip(axes, metrics):
        vals = []
        errs = []
        for method in METHODS:
            row = df[df["assignment_method"] == method]
            vals.append(float(row[m].iloc[0]) if not row.empty else np.nan)
            errs.append(float(row[e].iloc[0]) if not row.empty else np.nan)
        x = np.arange(len(METHODS))
        ax.bar(x, vals, yerr=errs, capsize=3)
        ax.set_xticks(x)
        ax.set_xticklabels(METHODS, rotation=20)
        ax.set_title(title)
        ax.grid(alpha=0.2)

    fig.suptitle("Proposed minus Prediction-only")
    fig.tight_layout()
    fig.savefig(outpath, dpi=160)
    plt.close(fig)

    return df


def _plot_tradeoff_scatter(summary_df: pd.DataFrame, outpath: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 6))

    marker_by_baseline = {
        "reactive": "o",
        "prediction_only": "s",
        "proposed": "^",
    }
    color_by_method = {
        "frozen_greedy": "tab:blue",
        "hungarian": "tab:orange",
        "auction": "tab:green",
        "cbba": "tab:red",
    }

    for _, row in summary_df.iterrows():
        baseline = str(row["baseline"])
        method = str(row["assignment_method"])
        x = float(row["boundary_message_count_mean"])
        y = float(row["value_weighted_exposure_mean"])
        resp = float(row["mean_response_time_s_mean"])
        size = max(20.0, min(500.0, 20.0 + 4.0 * resp))
        ax.scatter(
            x,
            y,
            s=size,
            alpha=0.7,
            marker=marker_by_baseline.get(baseline, "o"),
            color=color_by_method.get(method, "gray"),
            edgecolors="k",
            linewidths=0.5,
        )
        ax.text(x, y, f"{baseline}:{method}", fontsize=8)

    ax.set_xlabel("Communication overhead (message count)")
    ax.set_ylabel("Value-weighted exposure")
    ax.set_title("Tradeoff: exposure vs communication (bubble=response)")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(outpath, dpi=160)
    plt.close(fig)


def _plot_rank_heatmaps(summary_df: pd.DataFrame, outdir: Path) -> None:
    metrics = [
        ("value_weighted_exposure_mean", True, "Exposure"),
        ("mean_response_time_s_mean", True, "Response"),
        ("boundary_message_count_mean", True, "Comm"),
        ("assignment_solver_runtime_ms_mean", True, "Solver ms"),
    ]

    for baseline in BASELINES:
        sub = summary_df[summary_df["baseline"] == baseline].copy()
        if sub.empty:
            continue

        rank_df = pd.DataFrame(index=METHODS)
        for col, lower_better, name in metrics:
            vals = []
            for m in METHODS:
                row = sub[sub["assignment_method"] == m]
                vals.append(float(row[col].iloc[0]) if not row.empty else np.nan)
            s = pd.Series(vals, index=METHODS)
            if lower_better:
                rank_df[name] = s.rank(method="min", ascending=True)
            else:
                rank_df[name] = s.rank(method="min", ascending=False)

        fig, ax = plt.subplots(figsize=(6, 3.8))
        data = rank_df.to_numpy(dtype=float)
        im = ax.imshow(data, cmap="viridis", aspect="auto")
        ax.set_xticks(np.arange(rank_df.shape[1]))
        ax.set_xticklabels(rank_df.columns, rotation=20)
        ax.set_yticks(np.arange(rank_df.shape[0]))
        ax.set_yticklabels(rank_df.index)
        for i in range(rank_df.shape[0]):
            for j in range(rank_df.shape[1]):
                ax.text(j, i, f"{data[i, j]:.0f}", ha="center", va="center", color="white", fontsize=9)
        ax.set_title(f"Rank heatmap: {baseline}")
        fig.colorbar(im, ax=ax, fraction=0.05, pad=0.04, label="Rank (1=best)")
        fig.tight_layout()
        fig.savefig(outdir / f"rank_heatmap_{baseline}.png", dpi=160)
        plt.close(fig)


def _write_summary_md(outdir: Path, pp_df: pd.DataFrame, manifest: dict) -> None:
    lines = []
    lines.append("# Assignment Method Comparison Lab - Plot Summary")
    lines.append("")
    winner = manifest.get("winner_selection", {}).get("winner", {}).get("winner")
    lines.append(f"- Selected winner (from manifest rule): `{winner}`")
    lines.append(f"- Baselines: {', '.join(BASELINES)}")
    lines.append(f"- Methods: {', '.join(METHODS)}")
    lines.append("")

    if not pp_df.empty:
        lines.append("## Proposed minus Prediction-only (mean %) by method")
        lines.append("")
        lines.append("| method | exposure improve % | response improve % | comm increase % |")
        lines.append("|---|---:|---:|---:|")
        for _, r in pp_df.iterrows():
            lines.append(
                f"| {r['assignment_method']} | {r['exposure_improve_pct']:.3f} | {r['response_improve_pct']:.3f} | {r['comm_increase_pct']:.3f} |"
            )
        lines.append("")

    lines.append("## Generated Plots")
    lines.append("")
    lines.append("- `exposure_by_method.png`")
    lines.append("- `response_by_method.png`")
    lines.append("- `comm_by_method.png`")
    lines.append("- `proposed_minus_prediction_by_method.png`")
    lines.append("- `tradeoff_scatter_exposure_comm.png`")
    lines.append("- `rank_heatmap_reactive.png`")
    lines.append("- `rank_heatmap_prediction_only.png`")
    lines.append("- `rank_heatmap_proposed.png`")

    (outdir / "assignment_method_plots_summary_lab.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot assignment-method lab outputs")
    parser.add_argument("--outdir", type=str, default="results/assignment_method_lab")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    runs_path = outdir / "assignment_method_runs_lab.csv"
    summary_path = outdir / "assignment_method_summary_lab.csv"
    manifest_path = outdir / "assignment_method_manifest_lab.json"

    if not runs_path.exists() or not summary_path.exists():
        raise FileNotFoundError("Missing lab outputs. Run run_assignment_method_comparison_lab.py first.")

    runs_df = pd.read_csv(runs_path)
    summary_df = pd.read_csv(summary_path)
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    plots_dir = outdir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    _plot_metric_by_baseline(
        summary_df, "value_weighted_exposure", "Value-weighted exposure", plots_dir / "exposure_by_method.png"
    )
    _plot_metric_by_baseline(
        summary_df, "mean_response_time_s", "Mean response time (s)", plots_dir / "response_by_method.png"
    )
    _plot_metric_by_baseline(
        summary_df,
        "boundary_message_count",
        "Communication overhead (message count)",
        plots_dir / "comm_by_method.png",
    )
    pp_df = _plot_proposed_minus_prediction(runs_df, plots_dir / "proposed_minus_prediction_by_method.png")
    _plot_tradeoff_scatter(summary_df, plots_dir / "tradeoff_scatter_exposure_comm.png")
    _plot_rank_heatmaps(summary_df, plots_dir)

    _write_summary_md(plots_dir, pp_df, manifest)
    print(f"[done] wrote plots to: {plots_dir}")


if __name__ == "__main__":
    main()
