from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


BASELINES = ["reactive", "prediction_only", "proposed"]


def _ci95(values: Iterable[float]) -> Tuple[float, float, float, int]:
    arr = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna().to_numpy(dtype=float)
    n = int(arr.size)
    if n == 0:
        return float("nan"), float("nan"), float("nan"), 0
    mean = float(np.mean(arr))
    if n == 1:
        return mean, mean, mean, n
    ci = float(1.96 * np.std(arr, ddof=1) / np.sqrt(n))
    return mean, mean - ci, mean + ci, n


def _from_runs(runs_df: pd.DataFrame, baseline: str, metric: str) -> Tuple[float, float, float, int]:
    if runs_df is None or metric not in runs_df.columns:
        return float("nan"), float("nan"), float("nan"), 0
    vals = runs_df.loc[runs_df["baseline"] == baseline, metric]
    return _ci95(vals)


def _from_summary(summary_df: pd.DataFrame, baseline: str, metric: str) -> Tuple[float, float, float, int]:
    if summary_df is None:
        return float("nan"), float("nan"), float("nan"), 0
    mcol = f"{metric}_mean"
    vcol = f"{metric}_var"
    if ("baseline" not in summary_df.columns) or (mcol not in summary_df.columns):
        return float("nan"), float("nan"), float("nan"), 0
    sub = summary_df.loc[summary_df["baseline"] == baseline].copy()
    if sub.empty:
        return float("nan"), float("nan"), float("nan"), 0
    # Fallback estimate from between-setting spread (coarse, but usable when per-run CSV is absent).
    vals = pd.to_numeric(sub[mcol], errors="coerce").dropna()
    return _ci95(vals)


def _metric_table(label: str, runs_df: Optional[pd.DataFrame], summary_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    metrics = [
        ("value_weighted_exposure", "Exposure"),
        ("mean_response_time_s", "ResponseTime_s"),
        ("boundary_message_count", "BoundaryMsgs"),
    ]
    rows = []
    for baseline in BASELINES:
        row = {"system": label, "baseline": baseline}
        for metric, alias in metrics:
            s = _from_runs(runs_df, baseline, metric)
            if s[3] == 0:
                s = _from_summary(summary_df, baseline, metric)
            row[f"{alias}_mean"] = s[0]
            row[f"{alias}_ci_lo"] = s[1]
            row[f"{alias}_ci_hi"] = s[2]
            row[f"{alias}_n"] = s[3]
        rows.append(row)
    return pd.DataFrame(rows)


def _pairwise_delta_table(label: str, runs_df: Optional[pd.DataFrame], summary_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    cols = ["ExposureDeltaPct", "ResponseDeltaPct", "CommDeltaPct"]
    empty_row = pd.DataFrame(
        [
            {
                "system": label,
                "ExposureDeltaPct_mean": float("nan"),
                "ExposureDeltaPct_ci_lo": float("nan"),
                "ExposureDeltaPct_ci_hi": float("nan"),
                "ResponseDeltaPct_mean": float("nan"),
                "ResponseDeltaPct_ci_lo": float("nan"),
                "ResponseDeltaPct_ci_hi": float("nan"),
                "CommDeltaPct_mean": float("nan"),
                "CommDeltaPct_ci_lo": float("nan"),
                "CommDeltaPct_ci_hi": float("nan"),
                "n_pairs": 0,
            }
        ]
    )
    if runs_df is None:
        return empty_row

    need_cols = {"baseline", "run_idx", "seed", "value_weighted_exposure", "mean_response_time_s", "boundary_message_count"}
    if not need_cols.issubset(set(runs_df.columns)):
        return empty_row

    p = runs_df[runs_df["baseline"] == "proposed"].copy()
    q = runs_df[runs_df["baseline"] == "prediction_only"].copy()
    merge_keys = [c for c in ["exp_id", "scenario_id", "tune_id", "time_horizon_h", "run_idx", "seed"] if c in runs_df.columns]
    if not merge_keys:
        merge_keys = ["run_idx", "seed"]
    m = p.merge(q, on=merge_keys, suffixes=("_p", "_q"), how="inner")
    if m.empty:
        return empty_row

    d_exp = 100.0 * (m["value_weighted_exposure_q"] - m["value_weighted_exposure_p"]) / m["value_weighted_exposure_q"].replace(0.0, np.nan)
    d_resp = 100.0 * (m["mean_response_time_s_q"] - m["mean_response_time_s_p"]) / m["mean_response_time_s_q"].replace(0.0, np.nan)
    d_comm = 100.0 * (m["boundary_message_count_p"] - m["boundary_message_count_q"]) / m["boundary_message_count_q"].replace(0.0, np.nan)
    s_exp = _ci95(d_exp)
    s_resp = _ci95(d_resp)
    s_comm = _ci95(d_comm)
    return pd.DataFrame(
        [
            {
                "system": label,
                "ExposureDeltaPct_mean": s_exp[0],
                "ExposureDeltaPct_ci_lo": s_exp[1],
                "ExposureDeltaPct_ci_hi": s_exp[2],
                "ResponseDeltaPct_mean": s_resp[0],
                "ResponseDeltaPct_ci_lo": s_resp[1],
                "ResponseDeltaPct_ci_hi": s_resp[2],
                "CommDeltaPct_mean": s_comm[0],
                "CommDeltaPct_ci_lo": s_comm[1],
                "CommDeltaPct_ci_hi": s_comm[2],
                "n_pairs": s_exp[3],
            }
        ]
    )


def _plot_baseline_metrics(tbl: pd.DataFrame, outdir: Path) -> Path:
    metrics = [("Exposure", "Exposure"), ("ResponseTime_s", "Response Time (s)"), ("BoundaryMsgs", "Boundary Messages")]
    systems = tbl["system"].dropna().unique().tolist()
    x = np.arange(len(BASELINES))
    width = 0.36
    fig, axs = plt.subplots(1, 3, figsize=(15.0, 4.8))
    colors = ["#4c78a8", "#f58518"]

    for ax, (key, title) in zip(axs, metrics):
        for i, sys_name in enumerate(systems):
            sub = tbl[tbl["system"] == sys_name].set_index("baseline").reindex(BASELINES)
            y = sub[f"{key}_mean"].to_numpy(dtype=float)
            lo = sub[f"{key}_ci_lo"].to_numpy(dtype=float)
            hi = sub[f"{key}_ci_hi"].to_numpy(dtype=float)
            yerr = np.vstack([y - lo, hi - y])
            pos = x + (i - (len(systems) - 1) / 2.0) * width
            ax.bar(pos, y, width=width, label=sys_name, color=colors[i % len(colors)], alpha=0.9)
            ax.errorbar(pos, y, yerr=yerr, fmt="none", ecolor="black", capsize=3, linewidth=1.0)
        ax.set_xticks(x)
        ax.set_xticklabels(BASELINES, rotation=20)
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.25)
    axs[0].legend(frameon=False)
    fig.tight_layout()
    out = outdir / "baseline_metrics_compare.png"
    fig.savefig(out, dpi=220)
    plt.close(fig)
    return out


def _plot_delta_metrics(delta_tbl: pd.DataFrame, outdir: Path) -> Path:
    metrics = [("ExposureDeltaPct", "Exposure delta (%)"), ("ResponseDeltaPct", "Response delta (%)"), ("CommDeltaPct", "Comm delta (%)")]
    systems = delta_tbl["system"].tolist()
    x = np.arange(len(metrics))
    width = 0.36
    fig, ax = plt.subplots(figsize=(8.8, 5.0))
    colors = ["#54a24b", "#e45756"]
    for i, sys_name in enumerate(systems):
        row = delta_tbl.iloc[i]
        y = np.array([row[f"{m}_mean"] for m, _ in metrics], dtype=float)
        lo = np.array([row[f"{m}_ci_lo"] for m, _ in metrics], dtype=float)
        hi = np.array([row[f"{m}_ci_hi"] for m, _ in metrics], dtype=float)
        yerr = np.vstack([y - lo, hi - y])
        pos = x + (i - (len(systems) - 1) / 2.0) * width
        ax.bar(pos, y, width=width, label=sys_name, color=colors[i % len(colors)], alpha=0.9)
        ax.errorbar(pos, y, yerr=yerr, fmt="none", ecolor="black", capsize=4, linewidth=1.0)
    ax.axhline(0.0, linestyle="--", color="gray", linewidth=1.0)
    ax.set_xticks(x)
    ax.set_xticklabels([t for _, t in metrics], rotation=10)
    ax.set_title("Proposed vs Prediction-Only Deltas (mean +- CI95)")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    out = outdir / "proposed_vs_prediction_deltas_compare.png"
    fig.savefig(out, dpi=220)
    plt.close(fig)
    return out


def _plot_model_deterring_reasons(
    control_runs: Optional[pd.DataFrame], new_runs: Optional[pd.DataFrame], outdir: Path
) -> Optional[Path]:
    reason_cols = [
        "model_deterring_rejected_risk",
        "model_deterring_rejected_persistence",
        "model_deterring_rejected_eta",
        "model_deterring_rejected_budget",
        "model_deterring_rejected_support",
        "model_deterring_rejected_margin",
        "model_deterring_rejected_busy",
    ]
    systems = [("control", control_runs), ("new", new_runs)]
    labels = []
    accepted = []
    reason_matrix = []
    for name, df in systems:
        if df is None or "baseline" not in df.columns:
            continue
        p = df[df["baseline"] == "proposed"].copy()
        if p.empty:
            continue
        labels.append(name)
        accepted.append(float(pd.to_numeric(p.get("model_deterring_accepted"), errors="coerce").fillna(0.0).mean()))
        reason_vals = []
        for col in reason_cols:
            reason_vals.append(float(pd.to_numeric(p.get(col), errors="coerce").fillna(0.0).mean()) if col in p.columns else 0.0)
        reason_matrix.append(reason_vals)
    if not labels:
        return None
    reason_arr = np.array(reason_matrix, dtype=float)
    x = np.arange(len(labels))
    fig, axs = plt.subplots(1, 2, figsize=(12.5, 4.8))
    axs[0].bar(x, accepted, color="#2ca02c", alpha=0.85)
    axs[0].set_xticks(x)
    axs[0].set_xticklabels(labels)
    axs[0].set_title("Model-Scored Accepted (Proposed)")
    axs[0].set_ylabel("Mean count per run")
    axs[0].grid(axis="y", alpha=0.25)

    bottom = np.zeros(len(labels), dtype=float)
    cmap = plt.get_cmap("tab20")
    for i, col in enumerate(reason_cols):
        axs[1].bar(x, reason_arr[:, i], bottom=bottom, label=col.replace("model_deterring_rejected_", ""), color=cmap(i))
        bottom += reason_arr[:, i]
    axs[1].set_xticks(x)
    axs[1].set_xticklabels(labels)
    axs[1].set_title("Model-Scored Rejection Reasons (Proposed)")
    axs[1].set_ylabel("Mean rejected count per run")
    axs[1].grid(axis="y", alpha=0.25)
    axs[1].legend(loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False, fontsize=8)
    fig.tight_layout()
    out = outdir / "model_scored_accept_reject_compare.png"
    fig.savefig(out, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return out


def _plot_yield_metrics(control_runs: Optional[pd.DataFrame], new_runs: Optional[pd.DataFrame], outdir: Path) -> Optional[Path]:
    metrics = [
        ("suppression_per_model_deterring_action", "Suppression/model-action"),
        ("deterring_action_precision_model_scored", "Model deterring precision"),
        ("model_vs_direct_suppression_yield_ratio", "Model vs direct yield ratio"),
    ]
    systems = [("control", control_runs), ("new", new_runs)]
    rows = []
    for name, df in systems:
        if df is None or "baseline" not in df.columns:
            continue
        p = df[df["baseline"] == "proposed"].copy()
        if p.empty:
            continue
        row = {"system": name}
        for m, _ in metrics:
            s = _ci95(pd.to_numeric(p.get(m), errors="coerce"))
            row[f"{m}_mean"] = s[0]
            row[f"{m}_ci_lo"] = s[1]
            row[f"{m}_ci_hi"] = s[2]
        rows.append(row)
    if not rows:
        return None
    tbl = pd.DataFrame(rows)
    x = np.arange(len(metrics))
    width = 0.36
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    colors = ["#4c78a8", "#f58518"]
    for i, (_, sys_name) in enumerate(zip(range(len(tbl)), tbl["system"].tolist())):
        row = tbl.iloc[i]
        y = np.array([row[f"{m}_mean"] for m, _ in metrics], dtype=float)
        lo = np.array([row[f"{m}_ci_lo"] for m, _ in metrics], dtype=float)
        hi = np.array([row[f"{m}_ci_hi"] for m, _ in metrics], dtype=float)
        yerr = np.vstack([y - lo, hi - y])
        pos = x + (i - (len(tbl) - 1) / 2.0) * width
        ax.bar(pos, y, width=width, label=sys_name, color=colors[i % len(colors)], alpha=0.9)
        ax.errorbar(pos, y, yerr=yerr, fmt="none", ecolor="black", capsize=4, linewidth=1.0)
    ax.axhline(0.0, linestyle="--", color="gray", linewidth=1.0)
    ax.set_xticks(x)
    ax.set_xticklabels([t for _, t in metrics], rotation=10)
    ax.set_title("Suppression/Yield Diagnostics (Proposed)")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    out = outdir / "suppression_yield_compare.png"
    fig.savefig(out, dpi=220)
    plt.close(fig)
    return out


def _write_md_summary(
    outdir: Path,
    baseline_tbl: pd.DataFrame,
    delta_tbl: pd.DataFrame,
    plot_paths: Dict[str, Optional[Path]],
) -> Path:
    lines = [
        "# New System vs Control: Meeting Summary",
        "",
        "## Main Results (mean +- CI95)",
        baseline_tbl.to_markdown(index=False),
        "",
        "## Proposed vs Prediction-only Deltas",
        delta_tbl.to_markdown(index=False),
        "",
        "## Plot Paths",
    ]
    for k, p in plot_paths.items():
        if p is not None:
            lines.append(f"- {k}: `{p}`")
    out = outdir / "NEW_SYSTEM_RESULTS_SUMMARY.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def _load_optional(path: str) -> Optional[pd.DataFrame]:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return pd.read_csv(p)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot old-vs-new system comparison for meeting-ready visuals.")
    parser.add_argument("--control-comparison-csv", required=True)
    parser.add_argument("--new-comparison-csv", required=True)
    parser.add_argument("--control-runs-csv", default="")
    parser.add_argument("--new-runs-csv", default="")
    parser.add_argument("--outdir", default="results/new_system_comparison")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    control_cmp = pd.read_csv(args.control_comparison_csv)
    new_cmp = pd.read_csv(args.new_comparison_csv)
    control_runs = _load_optional(args.control_runs_csv)
    new_runs = _load_optional(args.new_runs_csv)

    baseline_tbl = pd.concat(
        [
            _metric_table("control", control_runs, control_cmp),
            _metric_table("new", new_runs, new_cmp),
        ],
        ignore_index=True,
    )
    delta_tbl = pd.concat(
        [
            _pairwise_delta_table("control", control_runs, control_cmp),
            _pairwise_delta_table("new", new_runs, new_cmp),
        ],
        ignore_index=True,
    )

    baseline_tbl.to_csv(outdir / "baseline_metric_ci95_table.csv", index=False)
    delta_tbl.to_csv(outdir / "proposed_vs_prediction_delta_ci95_table.csv", index=False)

    plot_paths: Dict[str, Optional[Path]] = {}
    plot_paths["baseline_metrics"] = _plot_baseline_metrics(baseline_tbl, outdir)
    plot_paths["delta_metrics"] = _plot_delta_metrics(delta_tbl, outdir)
    plot_paths["model_deterring_reasons"] = _plot_model_deterring_reasons(control_runs, new_runs, outdir)
    plot_paths["yield_metrics"] = _plot_yield_metrics(control_runs, new_runs, outdir)

    md = _write_md_summary(outdir, baseline_tbl, delta_tbl, plot_paths)

    print("[done] wrote comparison outputs:")
    print(f"- {outdir / 'baseline_metric_ci95_table.csv'}")
    print(f"- {outdir / 'proposed_vs_prediction_delta_ci95_table.csv'}")
    for k, p in plot_paths.items():
        if p is not None:
            print(f"- {p}")
    print(f"- {md}")


if __name__ == "__main__":
    main()

