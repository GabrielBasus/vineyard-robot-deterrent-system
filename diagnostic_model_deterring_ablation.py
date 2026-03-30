from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

import DeterrentSystem as ds
from diagnostic_compare_systems import run_collect


matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _pct_improve(baseline_value: float, candidate_value: float, lower_is_better: bool = True) -> float:
    if not np.isfinite(baseline_value) or abs(float(baseline_value)) <= 1e-12:
        return float("nan")
    if lower_is_better:
        return float(100.0 * (float(baseline_value) - float(candidate_value)) / float(baseline_value))
    return float(100.0 * (float(candidate_value) - float(baseline_value)) / abs(float(baseline_value)))


def _final_metrics(last: dict) -> dict:
    m = last.get("metrics", {})
    return {
        "value_weighted_exposure": float(m.get("value_weighted_exposure", np.nan)),
        "mean_response_time_s": float(m.get("mean_response_time_s", np.nan)),
        "boundary_message_count": float(m.get("boundary_message_count", np.nan)),
        "forecast_recall_at_k": float(m.get("forecast_recall_at_k", np.nan)),
        "forecast_precision_at_k": float(m.get("forecast_precision_at_k", np.nan)),
        "model_deterring_generated": float(m.get("model_deterring_generated", np.nan)),
        "model_deterring_accepted": float(m.get("model_deterring_accepted", np.nan)),
        "deterring_actions_completed_model_scored": float(
            m.get("deterring_actions_completed_model_scored", np.nan)
        ),
        "deterring_actions_completed_total": float(m.get("deterring_actions_completed_total", np.nan)),
        "patrolling_actions_completed": float(m.get("patrolling_actions_completed", np.nan)),
    }


def _build_comparisons(results: dict[str, dict]) -> dict[str, dict[str, float]]:
    pred = results["prediction_only"]["final_metrics"]
    prop = results["proposed_full"]["final_metrics"]
    prop_no_det = results["proposed_no_model_deterring"]["final_metrics"]
    return {
        "proposed_full_vs_prediction_only": {
            "exposure_improve_pct": _pct_improve(pred["value_weighted_exposure"], prop["value_weighted_exposure"]),
            "response_improve_pct": _pct_improve(pred["mean_response_time_s"], prop["mean_response_time_s"]),
            "comm_increase_pct": _pct_improve(
                pred["boundary_message_count"], prop["boundary_message_count"], lower_is_better=False
            ),
        },
        "proposed_no_model_deterring_vs_prediction_only": {
            "exposure_improve_pct": _pct_improve(
                pred["value_weighted_exposure"], prop_no_det["value_weighted_exposure"]
            ),
            "response_improve_pct": _pct_improve(pred["mean_response_time_s"], prop_no_det["mean_response_time_s"]),
            "comm_increase_pct": _pct_improve(
                pred["boundary_message_count"], prop_no_det["boundary_message_count"], lower_is_better=False
            ),
        },
        "proposed_full_vs_proposed_no_model_deterring": {
            "exposure_improve_pct": _pct_improve(
                prop_no_det["value_weighted_exposure"], prop["value_weighted_exposure"]
            ),
            "response_improve_pct": _pct_improve(
                prop_no_det["mean_response_time_s"], prop["mean_response_time_s"]
            ),
            "comm_increase_pct": _pct_improve(
                prop_no_det["boundary_message_count"], prop["boundary_message_count"], lower_is_better=False
            ),
        },
    }


def _build_conclusion(comparisons: dict[str, dict[str, float]]) -> list[str]:
    full_vs_pred = comparisons["proposed_full_vs_prediction_only"]
    no_det_vs_pred = comparisons["proposed_no_model_deterring_vs_prediction_only"]
    full_vs_no_det = comparisons["proposed_full_vs_proposed_no_model_deterring"]
    conclusions: list[str] = []

    if no_det_vs_pred["exposure_improve_pct"] > 0.0 and full_vs_no_det["exposure_improve_pct"] < 0.0:
        conclusions.append(
            "The intervention-aware field helps on its own, but model-scored preventive deterring is reducing net exposure performance."
        )
    elif no_det_vs_pred["exposure_improve_pct"] > 0.0 and full_vs_no_det["exposure_improve_pct"] > 0.0:
        conclusions.append(
            "Both the intervention-aware field and model-scored preventive deterring contribute positively to exposure reduction."
        )
    elif no_det_vs_pred["exposure_improve_pct"] <= 0.0 and full_vs_pred["exposure_improve_pct"] <= 0.0:
        conclusions.append(
            "Neither the field-only proposed variant nor the full proposed system currently beats prediction_only on exposure."
        )
    else:
        conclusions.append(
            "The field-only and full proposed variants differ materially; use the pairwise exposure delta to isolate whether preventive deterring is helping or hurting."
        )

    if full_vs_no_det["response_improve_pct"] < 0.0:
        conclusions.append("Model-scored preventive deterring is currently hurting response time relative to the same proposed field without it.")
    elif full_vs_no_det["response_improve_pct"] > 0.0:
        conclusions.append("Model-scored preventive deterring is currently improving response time relative to the same proposed field without it.")

    return conclusions


def _plot_ablation_timeseries(run_map: dict[str, pd.DataFrame], out_png: Path) -> None:
    fig, axes = plt.subplots(3, 2, figsize=(13, 10), sharex=True)
    plots = [
        ("value_weighted_exposure", "Exposure"),
        ("mean_response_time_s", "Mean Response Time (s)"),
        ("active_patrolling", "Active Patrol Tasks"),
        ("active_deterring_model_scored", "Active Model-Scored Deterring"),
        ("done_deterring_model_scored", "Completed Model-Scored Deterring"),
        ("inhib_sum_total", "Total Inhibition Mass"),
    ]
    colors = {
        "prediction_only": "#1f77b4",
        "proposed_full": "#d62728",
        "proposed_no_model_deterring": "#2ca02c",
    }
    labels = {
        "prediction_only": "prediction_only",
        "proposed_full": "proposed_full",
        "proposed_no_model_deterring": "proposed_no_model_deterring",
    }
    for ax, (col, title) in zip(axes.flat, plots):
        for name, df in run_map.items():
            if col not in df.columns:
                continue
            ax.plot(df["t"], df[col], label=labels.get(name, name), lw=1.4, color=colors.get(name))
        ax.set_title(title)
        ax.grid(alpha=0.25)
    axes[0, 0].legend(loc="best", fontsize=8)
    for ax in axes[-1]:
        ax.set_xlabel("time (s)")
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _plot_final_metrics(results: dict[str, dict], out_png: Path) -> None:
    labels = ["prediction_only", "proposed_no_model_deterring", "proposed_full"]
    exposure = [results[name]["final_metrics"]["value_weighted_exposure"] for name in labels]
    response = [results[name]["final_metrics"]["mean_response_time_s"] for name in labels]
    completed_model = [results[name]["final_metrics"]["deterring_actions_completed_model_scored"] for name in labels]

    x = np.arange(len(labels))
    w = 0.25
    fig, ax1 = plt.subplots(figsize=(12, 5))
    ax1.bar(x - w, exposure, width=w, label="Exposure")
    ax1.bar(x, response, width=w, label="Response Time (s)")
    ax1.bar(x + w, completed_model, width=w, label="Completed Model-Scored")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=10)
    ax1.grid(axis="y", alpha=0.25)
    ax1.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Three-way control: prediction_only vs proposed_full vs proposed without model-scored deterring."
    )
    parser.add_argument("--T-end", type=float, default=3 * 3600.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--sample-every-s", type=float, default=30.0)
    parser.add_argument("--outdir", type=str, default="results/diagnostic_model_deterring_ablation")
    parser.add_argument("--task-replan-period-s", type=float, default=60.0)
    parser.add_argument("--model-deterring-window-s", type=float, default=120.0)
    parser.add_argument("--model-deterring-gate-policy", type=str, default="sprt_capacity")
    parser.add_argument("--model-deterring-sprt-alpha", type=float, default=0.25)
    parser.add_argument("--model-deterring-sprt-beta", type=float, default=0.40)
    parser.add_argument("--model-deterring-sprt-patch-radius-m", type=float, default=30.0)
    parser.add_argument("--model-deterring-min-sprt-margin", type=float, default=1.25)
    parser.add_argument("--model-deterring-chance-threshold", type=float, default=0.35)
    parser.add_argument("--model-deterring-min-deltaj-per-cost", type=float, default=100000.0)
    parser.add_argument("--model-deterring-min-selection-weight", type=float, default=0.0)
    parser.add_argument("--model-deterring-capacity-rho-max", type=float, default=0.85)
    parser.add_argument("--model-deterring-global-admission-cap-per-cycle", type=int, default=1)
    parser.add_argument(
        "--model-deterring-prefer-idle-robots-for-assignment",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--model-deterring-busy-fallback-p-event-min", type=float, default=0.90)
    parser.add_argument("--model-deterring-busy-fallback-deltaj-per-cost-min", type=float, default=1000000.0)
    parser.add_argument("--model-deterring-busy-fallback-eta-s-max", type=float, default=1.25)
    parser.add_argument(
        "--protect-direct-detection-from-model-deterring",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--protect-locked-model-deterring-from-patrol-assignment",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--model-deterring-persistence-eta-multiplier", type=float, default=2.0)
    parser.add_argument("--model-deterring-persistence-buffer-s", type=float, default=60.0)
    parser.add_argument("--model-deterring-max-persistence-lifetime-s", type=float, default=420.0)
    parser.add_argument("--patrol-hotspot-filter-mode", type=str, default="percentile")
    parser.add_argument("--patrol-hotspot-score-percentile", type=float, default=97.0)
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    run_params = {
        "T_end": float(args.T_end),
        "dt": float(args.dt),
        "seed": int(args.seed),
        "W": 500.0,
        "H": 500.0,
        "NX": 80,
        "NY": 64,
        "Nrobots": 6,
        "uav_fraction": 0.0,
        "warmup_s": 1800.0,
        "task_replan_period_s": float(args.task_replan_period_s),
        "model_deterring_window_s": float(args.model_deterring_window_s),
        "model_deterring_gate_policy": str(args.model_deterring_gate_policy),
        "model_deterring_sprt_alpha": float(args.model_deterring_sprt_alpha),
        "model_deterring_sprt_beta": float(args.model_deterring_sprt_beta),
        "model_deterring_sprt_patch_radius_m": float(args.model_deterring_sprt_patch_radius_m),
        "model_deterring_min_sprt_margin": float(args.model_deterring_min_sprt_margin),
        "model_deterring_chance_threshold": float(args.model_deterring_chance_threshold),
        "model_deterring_min_deltaJ_per_cost": float(args.model_deterring_min_deltaj_per_cost),
        "model_deterring_min_selection_weight": float(args.model_deterring_min_selection_weight),
        "model_deterring_capacity_rho_max": float(args.model_deterring_capacity_rho_max),
        "model_deterring_global_admission_cap_per_cycle": int(
            args.model_deterring_global_admission_cap_per_cycle
        ),
        "model_deterring_prefer_idle_robots_for_assignment": bool(
            args.model_deterring_prefer_idle_robots_for_assignment
        ),
        "model_deterring_busy_fallback_p_event_min": float(args.model_deterring_busy_fallback_p_event_min),
        "model_deterring_busy_fallback_deltaJ_per_cost_min": float(
            args.model_deterring_busy_fallback_deltaj_per_cost_min
        ),
        "model_deterring_busy_fallback_eta_s_max": float(args.model_deterring_busy_fallback_eta_s_max),
        "protect_direct_detection_from_model_deterring": bool(
            args.protect_direct_detection_from_model_deterring
        ),
        "protect_locked_model_deterring_from_patrol_assignment": bool(
            args.protect_locked_model_deterring_from_patrol_assignment
        ),
        "model_deterring_persistence_eta_multiplier": float(args.model_deterring_persistence_eta_multiplier),
        "model_deterring_persistence_buffer_s": float(args.model_deterring_persistence_buffer_s),
        "model_deterring_max_persistence_lifetime_s": float(args.model_deterring_max_persistence_lifetime_s),
        "patrol_hotspot_filter_mode": str(args.patrol_hotspot_filter_mode),
        "patrol_hotspot_score_percentile": float(args.patrol_hotspot_score_percentile),
        "forecast_horizon_s": 300.0,
        "forecast_match_radius_m": 20.0,
        "forecast_top_k": 5,
        "forecast_eval_period_s": 30.0,
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
    }

    run_specs = [
        ("prediction_only", "prediction_only", {}),
        ("proposed_full", "proposed", {}),
        ("proposed_no_model_deterring", "proposed", {"enable_model_scored_deterring": False}),
    ]

    results: dict[str, dict] = {}
    run_map: dict[str, pd.DataFrame] = {}
    metrics_rows: list[dict] = []

    for label, sim_mode, overrides in run_specs:
        params = dict(run_params)
        params.update(overrides)
        df, last, _pose = run_collect(sim_mode, params, sample_every_s=float(args.sample_every_s))
        run_map[label] = df
        final_metrics = _final_metrics(last)
        results[label] = {
            "simulation_mode": sim_mode,
            "overrides": overrides,
            "final_metrics": final_metrics,
        }
        metrics_rows.append({"run_label": label, **final_metrics})
        df.to_csv(outdir / f"diagnostic_timeseries_{label}.csv", index=False)

    comparisons = _build_comparisons(results)
    conclusions = _build_conclusion(comparisons)

    pd.DataFrame(metrics_rows).to_csv(outdir / "diagnostic_model_deterring_ablation_summary.csv", index=False)
    _plot_ablation_timeseries(run_map, outdir / "diagnostic_model_deterring_ablation_timeseries.png")
    _plot_final_metrics(results, outdir / "diagnostic_model_deterring_ablation_final_metrics.png")

    report = {
        "parameters": run_params,
        "runs": results,
        "comparisons": comparisons,
        "conclusions": conclusions,
    }
    with open(outdir / "diagnostic_model_deterring_ablation.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    with open(outdir / "diagnostic_model_deterring_ablation.md", "w", encoding="utf-8") as f:
        f.write("# Model-Scored Deterring Ablation\n\n")
        f.write("## Parameters\n\n")
        for k, v in run_params.items():
            f.write(f"- `{k}`: `{v}`\n")
        f.write("\n## Final Metrics\n\n")
        for label in ["prediction_only", "proposed_no_model_deterring", "proposed_full"]:
            f.write(f"### {label}\n\n")
            for k, v in results[label]["final_metrics"].items():
                f.write(f"- `{k}`: `{v}`\n")
            f.write("\n")
        f.write("## Pairwise Comparisons\n\n")
        for label, vals in comparisons.items():
            f.write(f"### {label}\n\n")
            for k, v in vals.items():
                f.write(f"- `{k}`: `{v}`\n")
            f.write("\n")
        f.write("## Conclusions\n\n")
        for line in conclusions:
            f.write(f"- {line}\n")

    print(f"[done] model-deterring ablation saved to: {outdir}")


if __name__ == "__main__":
    main()
