from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from itertools import product
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from diagnostics.diagnostic_field_truth_compare import SubsystemConfig, simulate_one_run
from experiments.thesis_experiment_workflow import render_execution_order_lines, render_stage_readme_lines, stage_manifest


def _parse_float_list(raw: str):
    return [float(x.strip()) for x in str(raw).split(",") if str(x).strip()]


def _stats(arr):
    vals = np.asarray(arr, dtype=float)
    vals = vals[np.isfinite(vals)]
    n = int(vals.size)
    if n == 0:
        return {"mean": float("nan"), "std": float("nan"), "ci95": float("nan"), "n": 0}
    mean = float(np.mean(vals))
    std = float(np.std(vals))
    ci95 = float(1.96 * std / math.sqrt(n)) if n > 1 else 0.0
    return {"mean": mean, "std": std, "ci95": ci95, "n": n}


def _plot_ranking(summary_df: pd.DataFrame, out_png: Path):
    if summary_df.empty:
        return
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].scatter(
        summary_df["proposed_field_logloss_mean"],
        summary_df["proposed_field_brier_mean"],
        c=summary_df["nll_improvement_pct_mean"],
        cmap="viridis",
        s=50,
    )
    axes[0].set_xlabel("Proposed field log loss (mean)")
    axes[0].set_ylabel("Proposed field Brier (mean)")
    axes[0].set_title("Calibration tradeoff")
    axes[0].grid(alpha=0.25)

    top = summary_df.nsmallest(min(10, len(summary_df)), "rank")
    labels = top["config_id"].tolist()
    ypos = np.arange(len(labels))
    axes[1].barh(ypos, top["proposed_field_logloss_mean"], color="#3366cc", alpha=0.85)
    axes[1].set_yticks(ypos)
    axes[1].set_yticklabels(labels)
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Proposed field log loss (mean)")
    axes[1].set_title("Top-ranked configs")
    axes[1].grid(axis="x", alpha=0.25)

    cbar = fig.colorbar(axes[0].collections[0], ax=axes[0], shrink=0.9)
    cbar.set_label("NLL improvement (%)")
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def _format_metric(value: object) -> str:
    try:
        num = float(value)
    except Exception:
        return "nan"
    if not np.isfinite(num):
        return "nan"
    return f"{num:.4f}" if abs(num) >= 1e-3 else f"{num:.3e}"


def _write_readme(
    outdir: Path,
    run_csv: Path,
    summary_csv: Path,
    ranking_csv: Path,
    manifest_json: Path,
    summary_df: pd.DataFrame,
) -> Path:
    lines = [
        "# SESTPP Calibration Sweep",
        "",
        *render_stage_readme_lines("model_calibration"),
        "",
        "## Key Outputs",
        f"- Per-run CSV: `{run_csv.name}`",
        f"- Summary CSV: `{summary_csv.name}`",
        f"- Ranking CSV: `{ranking_csv.name}`",
        f"- Manifest: `{manifest_json.name}`",
        "- Ranking plot: `sestpp_calibration_sweep_tradeoff.png`",
    ]
    if not summary_df.empty:
        top = summary_df.iloc[0]
        lines.extend(
            [
                "",
                "## Current Best-Ranked Config",
                f"- Config id: `{top['config_id']}`",
                f"- Proposed field log loss mean +/- CI95: {_format_metric(top['proposed_field_logloss_mean'])} +/- {_format_metric(top['proposed_field_logloss_ci95'])}",
                f"- Proposed field Brier mean +/- CI95: {_format_metric(top['proposed_field_brier_mean'])} +/- {_format_metric(top['proposed_field_brier_ci95'])}",
                f"- Proposed NLL mean +/- CI95: {_format_metric(top['proposed_nll_mean'])} +/- {_format_metric(top['proposed_nll_ci95'])}",
                f"- NLL improvement mean: {_format_metric(top['nll_improvement_pct_mean'])}%",
            ]
        )
    lines.extend(["", *render_execution_order_lines()])
    readme_path = outdir / "SESTPP_CALIBRATION_README.md"
    readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return readme_path


def main():
    parser = argparse.ArgumentParser(description="SESTPP-only calibration sweep")
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--seed-start", type=int, default=2026)
    parser.add_argument("--T-end", type=float, default=10800.0)
    parser.add_argument("--warmup-s", type=float, default=1800.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--forecast-horizon-s", type=float, default=300.0)
    parser.add_argument("--eval-period-s", type=float, default=30.0)
    parser.add_argument("--outdir", type=str, default="results/sestpp_calibration_sweep")
    parser.add_argument("--limit-settings", type=int, default=0, help="0 => all")
    parser.add_argument("--intervention-prob", type=float, default=0.45)
    parser.add_argument("--intervention-cooldown-s", type=float, default=40.0)
    parser.add_argument("--intervention-delay-s", type=float, default=10.0)
    parser.add_argument("--intervention-shuffle", choices=["none", "space", "time", "spacetime"], default="none")
    parser.add_argument("--shuffle-time-window-s", type=float, default=300.0)
    parser.add_argument("--beta-true", type=float, default=0.30)
    parser.add_argument("--model-alpha-inhib-values", type=str, default="0.25,0.35,0.45")
    parser.add_argument("--model-omega-inhib-values", type=str, default="450,600,900")
    parser.add_argument("--model-mu-base-values", type=str, default="5e-5,1e-4,2e-4")
    parser.add_argument("--model-bg-ema-values", type=str, default="1e-7,1e-6")
    args = parser.parse_args()

    alpha_vals = _parse_float_list(args.model_alpha_inhib_values)
    omega_vals = _parse_float_list(args.model_omega_inhib_values)
    mu_vals = _parse_float_list(args.model_mu_base_values)
    bg_vals = _parse_float_list(args.model_bg_ema_values)

    grid = list(product(alpha_vals, omega_vals, mu_vals, bg_vals))
    if int(args.limit_settings) > 0:
        grid = grid[: int(args.limit_settings)]

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    run_rows = []
    manifest = {
        "base_args": vars(args),
        "num_configs": int(len(grid)),
        "grid": [],
        "workflow_stage": stage_manifest("model_calibration"),
    }

    for idx, (alpha_inhib, omega_inhib, mu_base, bg_ema) in enumerate(grid, start=1):
        config_id = f"C{idx:02d}"
        manifest["grid"].append(
            {
                "config_id": config_id,
                "model_alpha_inhib": float(alpha_inhib),
                "model_omega_inhib": float(omega_inhib),
                "model_mu_base": float(mu_base),
                "model_bg_ema": float(bg_ema),
            }
        )

        cfg = SubsystemConfig(
            runs=int(args.runs),
            seed_start=int(args.seed_start),
            T_end=float(args.T_end),
            warmup_s=float(args.warmup_s),
            dt=float(args.dt),
            forecast_horizon_s=float(args.forecast_horizon_s),
            eval_period_s=float(args.eval_period_s),
            intervention_prob=float(args.intervention_prob),
            intervention_cooldown_s=float(args.intervention_cooldown_s),
            intervention_delay_s=float(args.intervention_delay_s),
            intervention_shuffle=str(args.intervention_shuffle),
            shuffle_time_window_s=float(args.shuffle_time_window_s),
            beta_true=float(args.beta_true),
            model_alpha_inhib=float(alpha_inhib),
            model_omega_inhib=float(omega_inhib),
            model_mu_base=float(mu_base),
            model_bg_ema=float(bg_ema),
        )

        print(
            f"[config {idx}/{len(grid)} {config_id}] "
            f"alpha_inhib={alpha_inhib} omega_inhib={omega_inhib} mu_base={mu_base} bg_ema={bg_ema}"
        )
        for run_idx in range(cfg.runs):
            seed = cfg.seed_start + run_idx
            res = simulate_one_run(run_idx, seed, cfg)
            row = {
                "config_id": config_id,
                "seed": int(seed),
                "model_alpha_inhib": float(alpha_inhib),
                "model_omega_inhib": float(omega_inhib),
                "model_mu_base": float(mu_base),
                "model_bg_ema": float(bg_ema),
                **res["paired_metrics"],
            }
            run_rows.append(row)

    run_df = pd.DataFrame(run_rows)

    summary_rows = []
    for config_id, g in run_df.groupby("config_id", sort=False):
        first = g.iloc[0]
        row = {
            "config_id": str(config_id),
            "model_alpha_inhib": float(first["model_alpha_inhib"]),
            "model_omega_inhib": float(first["model_omega_inhib"]),
            "model_mu_base": float(first["model_mu_base"]),
            "model_bg_ema": float(first["model_bg_ema"]),
        }
        for metric in [
            "proposed_field_logloss",
            "proposed_field_brier",
            "proposed_nll",
            "delta_field_logloss_proposed_minus_prediction",
            "delta_field_brier_proposed_minus_prediction",
            "delta_nll_proposed_minus_prediction",
            "brier_improvement_pct",
            "logloss_improvement_pct",
            "nll_improvement_pct",
        ]:
            stats = _stats(g[metric].to_numpy(dtype=float))
            row[f"{metric}_mean"] = stats["mean"]
            row[f"{metric}_std"] = stats["std"]
            row[f"{metric}_ci95"] = stats["ci95"]
            row[f"{metric}_n"] = stats["n"]
        summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows)
    if not summary_df.empty:
        summary_df = summary_df.sort_values(
            by=[
                "proposed_field_logloss_mean",
                "proposed_field_brier_mean",
                "proposed_nll_mean",
                "delta_field_logloss_proposed_minus_prediction_mean",
            ],
            ascending=[True, True, True, True],
        ).reset_index(drop=True)
        summary_df.insert(0, "rank", np.arange(1, len(summary_df) + 1))

    ranking_cols = [
        "rank",
        "config_id",
        "model_alpha_inhib",
        "model_omega_inhib",
        "model_mu_base",
        "model_bg_ema",
        "proposed_field_logloss_mean",
        "proposed_field_logloss_ci95",
        "proposed_field_brier_mean",
        "proposed_field_brier_ci95",
        "proposed_nll_mean",
        "proposed_nll_ci95",
        "delta_field_logloss_proposed_minus_prediction_mean",
        "delta_field_brier_proposed_minus_prediction_mean",
        "delta_nll_proposed_minus_prediction_mean",
        "logloss_improvement_pct_mean",
        "brier_improvement_pct_mean",
        "nll_improvement_pct_mean",
    ]
    ranking_df = summary_df[ranking_cols].copy() if not summary_df.empty else pd.DataFrame(columns=ranking_cols)

    run_csv = outdir / "sestpp_calibration_sweep_per_run.csv"
    summary_csv = outdir / "sestpp_calibration_sweep_summary.csv"
    ranking_csv = outdir / "sestpp_calibration_sweep_ranking.csv"
    manifest_json = outdir / "sestpp_calibration_sweep_manifest.json"

    run_df.to_csv(run_csv, index=False)
    summary_df.to_csv(summary_csv, index=False)
    ranking_df.to_csv(ranking_csv, index=False)
    manifest["outputs"] = {
        "per_run_csv": run_csv.name,
        "summary_csv": summary_csv.name,
        "ranking_csv": ranking_csv.name,
        "tradeoff_png": "sestpp_calibration_sweep_tradeoff.png",
        "readme_md": "SESTPP_CALIBRATION_README.md",
    }
    if not summary_df.empty:
        manifest["best_config_id"] = str(summary_df.iloc[0]["config_id"])
        manifest["best_config"] = {
            key: value.item() if hasattr(value, "item") else value
            for key, value in summary_df.iloc[0].to_dict().items()
        }
    with open(manifest_json, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    _plot_ranking(summary_df, outdir / "sestpp_calibration_sweep_tradeoff.png")
    readme_path = _write_readme(outdir, run_csv, summary_csv, ranking_csv, manifest_json, summary_df)

    print("Saved:")
    print(f"- {run_csv}")
    print(f"- {summary_csv}")
    print(f"- {ranking_csv}")
    print(f"- {manifest_json}")
    print(f"- {outdir / 'sestpp_calibration_sweep_tradeoff.png'}")
    print(f"- {readme_path}")


if __name__ == "__main__":
    main()
