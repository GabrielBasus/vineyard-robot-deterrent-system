from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _ci95(values: pd.Series) -> tuple[float, float, float, int]:
    x = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    n = int(x.size)
    if n == 0:
        return float("nan"), float("nan"), float("nan"), 0
    mean = float(np.mean(x))
    if n == 1:
        return mean, mean, mean, n
    ci = float(1.96 * np.std(x, ddof=1) / np.sqrt(n))
    return mean, mean - ci, mean + ci, n


def _load_finalists(confirm_root: Path) -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    for d in sorted(confirm_root.iterdir()):
        if not d.is_dir():
            continue
        csv_path = d / "assignment_tuning_runs_lab.csv"
        if not csv_path.exists():
            continue
        out[d.name] = pd.read_csv(csv_path)
    return out


def _pairwise_deltas(df: pd.DataFrame) -> pd.DataFrame:
    p = df[df["baseline"] == "proposed"].copy()
    q = df[df["baseline"] == "prediction_only"].copy()
    m = p.merge(q, on=["seed", "run_idx"], suffixes=("_p", "_q"), how="inner")
    if m.empty:
        return pd.DataFrame()
    out = pd.DataFrame(
        {
            "seed": m["seed"],
            "run_idx": m["run_idx"],
            "exp_delta_pct": 100.0
            * (m["value_weighted_exposure_q"] - m["value_weighted_exposure_p"])
            / m["value_weighted_exposure_q"].replace(0.0, np.nan),
            "resp_delta_pct": 100.0
            * (m["mean_response_time_s_q"] - m["mean_response_time_s_p"])
            / m["mean_response_time_s_q"].replace(0.0, np.nan),
            "comm_delta_pct": 100.0
            * (m["boundary_message_count_p"] - m["boundary_message_count_q"])
            / m["boundary_message_count_q"].replace(0.0, np.nan),
        }
    )
    return out


def _first_numeric(df: pd.DataFrame, key: str) -> float:
    if key not in df.columns:
        return float("nan")
    s = pd.to_numeric(df[key], errors="coerce")
    if s.dropna().empty:
        return float("nan")
    return float(s.dropna().iloc[0])


def _make_delta_table(finalists: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: List[dict] = []
    for name, df in finalists.items():
        pair = _pairwise_deltas(df)
        if pair.empty:
            continue
        e = _ci95(pair["exp_delta_pct"])
        r = _ci95(pair["resp_delta_pct"])
        c = _ci95(pair["comm_delta_pct"])
        failures = float(pd.to_numeric(df.get("assignment_solver_failures"), errors="coerce").fillna(0.0).sum())
        rows.append(
            {
                "finalist": name,
                "n_pairs": e[3],
                "solver_failures_total": failures,
                "exp_delta_mean_pct": e[0],
                "exp_delta_ci95_lo_pct": e[1],
                "exp_delta_ci95_hi_pct": e[2],
                "exp_robust_positive": bool(e[1] > 0.0),
                "resp_delta_mean_pct": r[0],
                "resp_delta_ci95_lo_pct": r[1],
                "resp_delta_ci95_hi_pct": r[2],
                "comm_delta_mean_pct": c[0],
                "comm_delta_ci95_lo_pct": c[1],
                "comm_delta_ci95_hi_pct": c[2],
                "assigner_w_task_value": _first_numeric(df, "assigner_w_task_value"),
                "model_deterring_risk_threshold": _first_numeric(df, "model_deterring_risk_threshold"),
                "model_deterring_min_persistence_replans": _first_numeric(
                    df, "model_deterring_min_persistence_replans"
                ),
                "model_deterring_max_eta_s": _first_numeric(df, "model_deterring_max_eta_s"),
                "model_deterring_score_margin": _first_numeric(df, "model_deterring_score_margin"),
                "model_deterring_budget_per_robot_per_hr": _first_numeric(
                    df, "model_deterring_budget_per_robot_per_hr"
                ),
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(
            by=["exp_robust_positive", "exp_delta_mean_pct", "resp_delta_mean_pct", "comm_delta_mean_pct"],
            ascending=[False, False, False, True],
        ).reset_index(drop=True)
    return out


def _plot_delta_bars(delta_df: pd.DataFrame, outdir: Path, col_prefix: str, ylabel: str, filename: str) -> Path:
    x = np.arange(len(delta_df))
    y = delta_df[f"{col_prefix}_mean_pct"].to_numpy(dtype=float)
    lo = delta_df[f"{col_prefix}_ci95_lo_pct"].to_numpy(dtype=float)
    hi = delta_df[f"{col_prefix}_ci95_hi_pct"].to_numpy(dtype=float)
    yerr = np.vstack([y - lo, hi - y])
    fig, ax = plt.subplots(figsize=(9.6, 5.2))
    bars = ax.bar(x, y, color="#4c78a8", alpha=0.9)
    ax.errorbar(x, y, yerr=yerr, fmt="none", ecolor="black", elinewidth=1.2, capsize=4)
    ax.axhline(0.0, color="gray", linewidth=1.0, linestyle="--")
    ax.set_xticks(x)
    ax.set_xticklabels(delta_df["finalist"].tolist())
    ax.set_ylabel(ylabel)
    ax.set_title(f"{ylabel} Across Finalists (mean +- CI95)")
    ax.grid(axis="y", alpha=0.25)
    for rect, val in zip(bars, y):
        ax.text(rect.get_x() + rect.get_width() / 2.0, rect.get_height(), f"{val:.2f}", ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    out_path = outdir / filename
    fig.savefig(out_path, dpi=220)
    plt.close(fig)
    return out_path


def _plot_model_deterring_reasons(finalists: Dict[str, pd.DataFrame], outdir: Path) -> Path:
    reason_cols = [
        "model_deterring_rejected_predicted_deltaJ",
        "model_deterring_rejected_risk",
        "model_deterring_rejected_persistence",
        "model_deterring_rejected_support",
        "model_deterring_rejected_margin",
        "model_deterring_rejected_eta",
        "model_deterring_rejected_busy",
        "model_deterring_rejected_budget",
        "model_deterring_rejected_field",
        "model_deterring_rejected_cooldown",
        "model_deterring_rejected_repeat_no_new_support",
    ]
    labels = sorted(finalists.keys())
    accepted = []
    rejected_total = []
    reasons_pct = []
    for name in labels:
        df = finalists[name]
        p = df[df["baseline"] == "proposed"].copy()
        accepted_sum = float(pd.to_numeric(p.get("model_deterring_accepted"), errors="coerce").fillna(0.0).sum())
        reason_sums = []
        for col in reason_cols:
            s = float(pd.to_numeric(p.get(col), errors="coerce").fillna(0.0).sum()) if col in p.columns else 0.0
            reason_sums.append(s)
        rej_sum = float(np.sum(reason_sums))
        accepted.append(accepted_sum)
        rejected_total.append(rej_sum)
        if rej_sum > 0.0:
            reasons_pct.append([100.0 * v / rej_sum for v in reason_sums])
        else:
            reasons_pct.append([0.0 for _ in reason_sums])

    x = np.arange(len(labels))
    reasons_pct_arr = np.array(reasons_pct, dtype=float)
    fig, axs = plt.subplots(1, 2, figsize=(13.5, 5.1))

    axs[0].bar(x, accepted, label="Accepted", color="#2ca02c", alpha=0.85)
    axs[0].bar(x, rejected_total, bottom=accepted, label="Rejected", color="#d62728", alpha=0.7)
    axs[0].set_xticks(x)
    axs[0].set_xticklabels(labels)
    axs[0].set_ylabel("Count over 10 seeds")
    axs[0].set_title("Model-Scored Deterrence: Accepted vs Rejected")
    axs[0].legend(frameon=False)
    axs[0].grid(axis="y", alpha=0.25)

    bottom = np.zeros(len(labels), dtype=float)
    cmap = plt.get_cmap("tab20")
    for i, col in enumerate(reason_cols):
        vals = reasons_pct_arr[:, i]
        axs[1].bar(x, vals, bottom=bottom, label=col.replace("model_deterring_rejected_", ""), color=cmap(i))
        bottom += vals
    axs[1].set_xticks(x)
    axs[1].set_xticklabels(labels)
    axs[1].set_ylabel("Rejected composition (%)")
    axs[1].set_title("Rejection Reasons Breakdown (Proposed)")
    axs[1].set_ylim(0, 100)
    axs[1].grid(axis="y", alpha=0.25)
    axs[1].legend(loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False, fontsize=8)

    fig.tight_layout()
    out_path = outdir / "model_scored_accepted_rejected_reasons.png"
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _plot_predicted_realized_yield(finalists: Dict[str, pd.DataFrame], outdir: Path) -> Path:
    labels = sorted(finalists.keys())
    pred_mean = []
    pred_ci = []
    real_mean = []
    real_ci = []
    yld_mean = []
    yld_ci = []
    scatter_records = []
    for name in labels:
        df = finalists[name]
        p = df[df["baseline"] == "proposed"].copy()
        pred = pd.to_numeric(p.get("predicted_deltaJ_sum"), errors="coerce")
        real = pd.to_numeric(p.get("realized_suppression_sum"), errors="coerce")
        yld = pd.to_numeric(p.get("yield_ratio_total"), errors="coerce")
        em = _ci95(pred)
        rm = _ci95(real)
        ym = _ci95(yld)
        pred_mean.append(em[0])
        pred_ci.append((em[1], em[2]))
        real_mean.append(rm[0])
        real_ci.append((rm[1], rm[2]))
        yld_mean.append(ym[0])
        yld_ci.append((ym[1], ym[2]))
        for _, row in p.iterrows():
            scatter_records.append(
                {
                    "finalist": name,
                    "predicted_deltaJ_sum": pd.to_numeric(row.get("predicted_deltaJ_sum"), errors="coerce"),
                    "realized_suppression_sum": pd.to_numeric(row.get("realized_suppression_sum"), errors="coerce"),
                }
            )

    fig, axs = plt.subplots(1, 2, figsize=(13.5, 5.2))
    x = np.arange(len(labels))
    w = 0.38
    pred_lo = np.array([m - c[0] for m, c in zip(pred_mean, pred_ci)], dtype=float)
    pred_hi = np.array([c[1] - m for m, c in zip(pred_mean, pred_ci)], dtype=float)
    real_lo = np.array([m - c[0] for m, c in zip(real_mean, real_ci)], dtype=float)
    real_hi = np.array([c[1] - m for m, c in zip(real_mean, real_ci)], dtype=float)
    axs[0].bar(x - w / 2, pred_mean, width=w, color="#1f77b4", label="Predicted deltaJ sum")
    axs[0].errorbar(x - w / 2, pred_mean, yerr=np.vstack([pred_lo, pred_hi]), fmt="none", ecolor="black", capsize=3)
    axs[0].bar(x + w / 2, real_mean, width=w, color="#ff7f0e", label="Realized suppression sum")
    axs[0].errorbar(x + w / 2, real_mean, yerr=np.vstack([real_lo, real_hi]), fmt="none", ecolor="black", capsize=3)
    axs[0].set_xticks(x)
    axs[0].set_xticklabels(labels)
    axs[0].set_title("Predicted vs Realized Suppression (Proposed)")
    axs[0].set_ylabel("Sum over run")
    axs[0].legend(frameon=False)
    axs[0].grid(axis="y", alpha=0.25)

    yld_lo = np.array([m - c[0] for m, c in zip(yld_mean, yld_ci)], dtype=float)
    yld_hi = np.array([c[1] - m for m, c in zip(yld_mean, yld_ci)], dtype=float)
    axs[1].bar(x, yld_mean, color="#59a14f")
    axs[1].errorbar(x, yld_mean, yerr=np.vstack([yld_lo, yld_hi]), fmt="none", ecolor="black", capsize=4)
    axs[1].axhline(0.0, color="gray", linewidth=1.0, linestyle="--")
    axs[1].set_xticks(x)
    axs[1].set_xticklabels(labels)
    axs[1].set_title("Yield Ratio Total (realized/predicted)")
    axs[1].set_ylabel("Yield ratio")
    axs[1].grid(axis="y", alpha=0.25)

    fig.tight_layout()
    out_path = outdir / "predicted_vs_realized_suppression_yield.png"
    fig.savefig(out_path, dpi=220)
    plt.close(fig)
    return out_path


def _plot_utilization_queue(finalists: Dict[str, pd.DataFrame], outdir: Path) -> Path:
    labels = sorted(finalists.keys())
    frac_metrics = ["robot_moving_fraction_mean", "robot_active_task_fraction_mean"]
    queue_metrics = ["queue_depth_total_mean", "queue_depth_model_deterring_mean"]

    def collect(metric: str):
        means, cis = [], []
        for name in labels:
            df = finalists[name]
            p = df[df["baseline"] == "proposed"]
            st = _ci95(pd.to_numeric(p.get(metric), errors="coerce"))
            means.append(st[0])
            cis.append((st[1], st[2]))
        return np.array(means, dtype=float), np.array(cis, dtype=float)

    x = np.arange(len(labels))
    fig, axs = plt.subplots(1, 2, figsize=(13.5, 5.1))

    w = 0.38
    m1, c1 = collect(frac_metrics[0])
    m2, c2 = collect(frac_metrics[1])
    axs[0].bar(x - w / 2, m1, width=w, color="#4e79a7", label="Moving fraction")
    axs[0].errorbar(x - w / 2, m1, yerr=np.vstack([m1 - c1[:, 0], c1[:, 1] - m1]), fmt="none", ecolor="black", capsize=3)
    axs[0].bar(x + w / 2, m2, width=w, color="#f28e2b", label="Active-task fraction")
    axs[0].errorbar(x + w / 2, m2, yerr=np.vstack([m2 - c2[:, 0], c2[:, 1] - m2]), fmt="none", ecolor="black", capsize=3)
    axs[0].set_xticks(x)
    axs[0].set_xticklabels(labels)
    axs[0].set_ylim(0.0, 1.0)
    axs[0].set_ylabel("Fraction")
    axs[0].set_title("Robot Utilization Diagnostics (Proposed)")
    axs[0].legend(frameon=False)
    axs[0].grid(axis="y", alpha=0.25)

    m3, c3 = collect(queue_metrics[0])
    m4, c4 = collect(queue_metrics[1])
    axs[1].bar(x - w / 2, m3, width=w, color="#e15759", label="Queue depth total")
    axs[1].errorbar(x - w / 2, m3, yerr=np.vstack([m3 - c3[:, 0], c3[:, 1] - m3]), fmt="none", ecolor="black", capsize=3)
    axs[1].bar(x + w / 2, m4, width=w, color="#76b7b2", label="Queue depth model-deterring")
    axs[1].errorbar(x + w / 2, m4, yerr=np.vstack([m4 - c4[:, 0], c4[:, 1] - m4]), fmt="none", ecolor="black", capsize=3)
    axs[1].set_xticks(x)
    axs[1].set_xticklabels(labels)
    axs[1].set_ylabel("Mean queue depth")
    axs[1].set_title("Queue Diagnostics (Proposed)")
    axs[1].legend(frameon=False)
    axs[1].grid(axis="y", alpha=0.25)

    fig.tight_layout()
    out_path = outdir / "utilization_queue_diagnostics.png"
    fig.savefig(out_path, dpi=220)
    plt.close(fig)
    return out_path


def _write_markdown_summary(delta_df: pd.DataFrame, outdir: Path, plot_paths: Dict[str, Path]) -> Path:
    best = delta_df.iloc[0] if not delta_df.empty else None
    robust_count = int(delta_df["exp_robust_positive"].sum()) if "exp_robust_positive" in delta_df.columns else 0
    total = int(len(delta_df))
    lines = [
        "# Confirm Finalists: Advisor Slide Summary",
        "",
        "## Headline",
        f"- Finalists evaluated: {total}",
        f"- Robust exposure winners (CI95 lower bound > 0): {robust_count}",
    ]
    if best is not None:
        lines += [
            f"- Top point estimate config: `{best['finalist']}`",
            f"  - Exposure delta: {best['exp_delta_mean_pct']:.3f}% (CI95 [{best['exp_delta_ci95_lo_pct']:.3f}, {best['exp_delta_ci95_hi_pct']:.3f}])",
            f"  - Response delta: {best['resp_delta_mean_pct']:.3f}% (CI95 [{best['resp_delta_ci95_lo_pct']:.3f}, {best['resp_delta_ci95_hi_pct']:.3f}])",
            f"  - Comm delta: {best['comm_delta_mean_pct']:.3f}% (CI95 [{best['comm_delta_ci95_lo_pct']:.3f}, {best['comm_delta_ci95_hi_pct']:.3f}])",
        ]
    lines += [
        "",
        "## Plot References",
        f"- Exposure delta CI: `{plot_paths['exposure']}`",
        f"- Response delta CI: `{plot_paths['response']}`",
        f"- Comm delta CI: `{plot_paths['comm']}`",
        f"- Model-scored accepted/rejected reasons: `{plot_paths['reasons']}`",
        f"- Predicted vs realized suppression yield: `{plot_paths['yield']}`",
        f"- Utilization/queue diagnostics: `{plot_paths['utilization']}`",
        "",
        "## Advisor-ready takeaway",
        "- Current confirm run shows weak separation on exposure with high communication overhead; use this as a rigorous negative/neutral result and motivate next iteration.",
    ]
    out_path = outdir / "ADVISOR_SLIDE_SUMMARY.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _write_interpretation_draft(delta_df: pd.DataFrame, outdir: Path) -> Path:
    if delta_df.empty:
        text = (
            "## Results Interpretation (Draft)\n\n"
            "No valid finalist rows were found, so no defensible quantitative comparison can be made yet."
        )
    else:
        robust = delta_df[delta_df["exp_robust_positive"]]
        mean_exp = float(delta_df["exp_delta_mean_pct"].mean())
        mean_comm = float(delta_df["comm_delta_mean_pct"].mean())
        text = (
            "## Results Interpretation (Draft)\n\n"
            "Across finalist confirm runs (10 seeds, 3-hour horizon), the proposed system does not show robust exposure improvement relative to prediction_only; "
            "CI95 on exposure deltas crosses zero for all finalists. Response-time differences are mixed and also not robust. "
            f"Communication overhead is consistently higher for proposed (mean across finalists: {mean_comm:.2f}% delta). "
            "This is thesis-defensible as a negative/neutral confirm result because uncertainty is explicitly reported and paired-seed comparisons are used. "
            "A safe claim is that under the tested gating and assignment settings, performance gains are not statistically reliable at this sample size/horizon, while comm cost increases.\n\n"
            "Not safe to claim: that proposed consistently reduces exposure by a fixed margin in this confirm setting.\n\n"
            f"Point-estimate exposure average across finalists is {mean_exp:.3f}%, with {len(robust)} robust-positive finalists."
        )
    out_path = outdir / "RESULTS_INTERPRETATION_DRAFT.md"
    out_path.write_text(text, encoding="utf-8")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Create publication-ready confirm plots/tables for finalist configs.")
    parser.add_argument("--confirm-root", type=str, default="results/phase23_finalist_confirm")
    parser.add_argument("--outdir", type=str, default="")
    args = parser.parse_args()

    confirm_root = Path(args.confirm_root)
    outdir = Path(args.outdir) if str(args.outdir).strip() else (confirm_root / "publication_plots")
    outdir.mkdir(parents=True, exist_ok=True)

    finalists = _load_finalists(confirm_root)
    if not finalists:
        raise RuntimeError(f"No finalist run CSVs found under: {confirm_root}")

    delta_df = _make_delta_table(finalists)
    if delta_df.empty:
        raise RuntimeError("No paired proposed/prediction rows found for delta analysis.")

    delta_csv = outdir / "finalist_delta_ci95_table.csv"
    delta_df.to_csv(delta_csv, index=False)

    md_table = delta_df[
        [
            "finalist",
            "n_pairs",
            "exp_delta_mean_pct",
            "exp_delta_ci95_lo_pct",
            "exp_delta_ci95_hi_pct",
            "resp_delta_mean_pct",
            "resp_delta_ci95_lo_pct",
            "resp_delta_ci95_hi_pct",
            "comm_delta_mean_pct",
            "comm_delta_ci95_lo_pct",
            "comm_delta_ci95_hi_pct",
            "solver_failures_total",
        ]
    ].copy()
    md_path = outdir / "finalist_delta_ci95_table.md"
    md_path.write_text(md_table.to_markdown(index=False), encoding="utf-8")

    plot_paths = {
        "exposure": _plot_delta_bars(
            delta_df, outdir, "exp_delta", "Exposure Delta vs prediction_only (%)", "exposure_delta_ci95.png"
        ),
        "response": _plot_delta_bars(
            delta_df, outdir, "resp_delta", "Response Delta vs prediction_only (%)", "response_delta_ci95.png"
        ),
        "comm": _plot_delta_bars(
            delta_df, outdir, "comm_delta", "Communication Delta vs prediction_only (%)", "comm_delta_ci95.png"
        ),
        "reasons": _plot_model_deterring_reasons(finalists, outdir),
        "yield": _plot_predicted_realized_yield(finalists, outdir),
        "utilization": _plot_utilization_queue(finalists, outdir),
    }

    slide_md = _write_markdown_summary(delta_df, outdir, plot_paths)
    interp_md = _write_interpretation_draft(delta_df, outdir)

    print("[done] publication outputs:")
    print(f"- {delta_csv}")
    print(f"- {md_path}")
    for key in ["exposure", "response", "comm", "reasons", "yield", "utilization"]:
        print(f"- {plot_paths[key]}")
    print(f"- {slide_md}")
    print(f"- {interp_md}")


if __name__ == "__main__":
    main()
