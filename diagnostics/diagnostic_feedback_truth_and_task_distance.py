from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import DeterrentSystem as ds
from diagnostics.diagnostic_feedback_patrol_divergence import (
    _collect_sampled_frames,
    _greedy_match,
    _patrol_points,
    _safe_mean,
    _xy_points,
)
from diagnostics.diagnostic_field_truth_compare import simulate_one_run as simulate_field_truth_run
from diagnostics.diagnostic_sestpp_subsystem import SubsystemConfig


def _build_field_cfg(args: argparse.Namespace) -> SubsystemConfig:
    return SubsystemConfig(
        dt=float(args.dt),
        T_end=float(args.T_end),
        warmup_s=float(args.warmup_s),
        eval_period_s=float(args.eval_period_s),
        forecast_horizon_s=float(args.forecast_horizon_s),
        runs=int(args.runs),
        seed_start=int(args.seed_start),
        model_alpha_inhib=float(args.alpha_inhib),
        model_omega_inhib=float(args.omega_inhib),
        model_mu_base=float(args.mu_base),
        model_bg_ema=float(args.bg_ema),
        intervention_shuffle=str(args.intervention_shuffle),
    )


def _summarize_field_runs(run_df: pd.DataFrame) -> dict:
    summary = {}
    metric_pairs = [
        ("delta_field_brier_proposed_minus_prediction", "brier_improvement_pct"),
        ("delta_field_logloss_proposed_minus_prediction", "logloss_improvement_pct"),
        ("delta_nll_proposed_minus_prediction", "nll_improvement_pct"),
    ]
    for delta_col, improve_col in metric_pairs:
        delta_arr = run_df[delta_col].to_numpy(dtype=float)
        delta_arr = delta_arr[np.isfinite(delta_arr)]
        improve_arr = run_df[improve_col].to_numpy(dtype=float)
        improve_arr = improve_arr[np.isfinite(improve_arr)]
        key = delta_col.replace("delta_", "").replace("_proposed_minus_prediction", "")
        summary[key] = {
            "mean_delta": float(np.mean(delta_arr)) if delta_arr.size else float("nan"),
            "std_delta": float(np.std(delta_arr)) if delta_arr.size else float("nan"),
            "mean_improvement_pct": float(np.mean(improve_arr)) if improve_arr.size else float("nan"),
            "std_improvement_pct": float(np.std(improve_arr)) if improve_arr.size else float("nan"),
            "wins_proposed": int(np.sum(delta_arr < 0.0)) if delta_arr.size else 0,
            "runs": int(delta_arr.size),
        }
    return summary


def _build_task_distance_rows(
    pred: dict,
    prop: dict,
    match_radius_m: float,
) -> pd.DataFrame:
    ts = sorted(set(pred["sampled"].keys()) & set(prop["sampled"].keys()))
    rows = []
    for t_key in ts:
        pred_snap = pred["sampled"][t_key]
        prop_snap = prop["sampled"][t_key]

        pred_hotspots = _xy_points(pred_snap["global_hotspots"])
        prop_hotspots = _xy_points(prop_snap["global_hotspots"])
        pred_patrol_candidates = _xy_points(pred_snap["patrol_candidates"])
        prop_patrol_candidates = _xy_points(prop_snap["patrol_candidates"])
        pred_accepted_patrol = _xy_points(pred_snap["accepted_patrol_tasks"])
        prop_accepted_patrol = _xy_points(prop_snap["accepted_patrol_tasks"])
        pred_active_patrol = _patrol_points(pred_snap["tasks_active"])
        prop_active_patrol = _patrol_points(prop_snap["tasks_active"])

        hs_matches, hs_dist = _greedy_match(pred_hotspots, prop_hotspots, match_radius_m)
        cand_matches, cand_dist = _greedy_match(pred_patrol_candidates, prop_patrol_candidates, match_radius_m)
        acc_matches, acc_dist = _greedy_match(pred_accepted_patrol, prop_accepted_patrol, match_radius_m)
        active_matches, active_dist = _greedy_match(pred_active_patrol, prop_active_patrol, match_radius_m)

        rows.append(
            {
                "t_s": float(pred_snap["t_s"]),
                "prediction_hotspot_count": int(len(pred_hotspots)),
                "proposed_hotspot_count": int(len(prop_hotspots)),
                "hotspot_overlap": float(hs_matches) / float(max(max(len(pred_hotspots), len(prop_hotspots)), 1)),
                "hotspot_mean_match_distance_m": hs_dist,
                "prediction_patrol_candidate_count": int(len(pred_patrol_candidates)),
                "proposed_patrol_candidate_count": int(len(prop_patrol_candidates)),
                "patrol_candidate_overlap": float(cand_matches)
                / float(max(max(len(pred_patrol_candidates), len(prop_patrol_candidates)), 1)),
                "patrol_candidate_mean_match_distance_m": cand_dist,
                "prediction_accepted_patrol_count": int(len(pred_accepted_patrol)),
                "proposed_accepted_patrol_count": int(len(prop_accepted_patrol)),
                "accepted_patrol_overlap": float(acc_matches)
                / float(max(max(len(pred_accepted_patrol), len(prop_accepted_patrol)), 1)),
                "accepted_patrol_mean_match_distance_m": acc_dist,
                "prediction_active_patrol_count": int(len(pred_active_patrol)),
                "proposed_active_patrol_count": int(len(prop_active_patrol)),
                "active_patrol_overlap": float(active_matches)
                / float(max(max(len(pred_active_patrol), len(prop_active_patrol)), 1)),
                "active_patrol_mean_match_distance_m": active_dist,
            }
        )
    return pd.DataFrame(rows)


def _summarize_task_distances(task_df: pd.DataFrame) -> dict:
    return {
        "hotspot_overlap_mean": _safe_mean(task_df["hotspot_overlap"].tolist()),
        "hotspot_mean_match_distance_m": _safe_mean(task_df["hotspot_mean_match_distance_m"].tolist()),
        "patrol_candidate_overlap_mean": _safe_mean(task_df["patrol_candidate_overlap"].tolist()),
        "patrol_candidate_mean_match_distance_m": _safe_mean(task_df["patrol_candidate_mean_match_distance_m"].tolist()),
        "accepted_patrol_overlap_mean": _safe_mean(task_df["accepted_patrol_overlap"].tolist()),
        "accepted_patrol_mean_match_distance_m": _safe_mean(task_df["accepted_patrol_mean_match_distance_m"].tolist()),
        "active_patrol_overlap_mean": _safe_mean(task_df["active_patrol_overlap"].tolist()),
        "active_patrol_mean_match_distance_m": _safe_mean(task_df["active_patrol_mean_match_distance_m"].tolist()),
    }


def _plot_task_distances(task_df: pd.DataFrame, out_png: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    t = task_df["t_s"]

    axes[0].plot(t, task_df["hotspot_overlap"], label="Hotspot overlap")
    axes[0].plot(t, task_df["patrol_candidate_overlap"], label="Patrol candidate overlap")
    axes[0].plot(t, task_df["accepted_patrol_overlap"], label="Accepted patrol overlap")
    axes[0].plot(t, task_df["active_patrol_overlap"], label="Active patrol overlap")
    axes[0].set_ylabel("Overlap")
    axes[0].grid(alpha=0.25)
    axes[0].legend(loc="best", fontsize=8)

    axes[1].plot(t, task_df["hotspot_mean_match_distance_m"], label="Hotspot distance")
    axes[1].plot(t, task_df["patrol_candidate_mean_match_distance_m"], label="Patrol candidate distance")
    axes[1].plot(t, task_df["accepted_patrol_mean_match_distance_m"], label="Accepted patrol distance")
    axes[1].plot(t, task_df["active_patrol_mean_match_distance_m"], label="Active patrol distance")
    axes[1].set_ylabel("Mean matched distance (m)")
    axes[1].set_xlabel("time (s)")
    axes[1].grid(alpha=0.25)
    axes[1].legend(loc="best", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify feedback-enabled proposed SESTPP against truth and compare task distances between prediction_only and proposed."
    )
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--seed-start", type=int, default=2026)
    parser.add_argument("--task-seed", type=int, default=2026)
    parser.add_argument("--T-end", type=float, default=3 * 3600.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--warmup-s", type=float, default=1800.0)
    parser.add_argument("--eval-period-s", type=float, default=30.0)
    parser.add_argument("--forecast-horizon-s", type=float, default=300.0)
    parser.add_argument("--sample-every-s", type=float, default=30.0)
    parser.add_argument("--task-replan-period-s", type=float, default=60.0)
    parser.add_argument("--hotspot-top-k", type=int, default=5)
    parser.add_argument("--match-radius-m", type=float, default=25.0)
    parser.add_argument("--alpha-inhib", type=float, default=0.45)
    parser.add_argument("--omega-inhib", type=float, default=600.0)
    parser.add_argument("--mu-base", type=float, default=5.0e-5)
    parser.add_argument("--bg-ema", type=float, default=1.0e-6)
    parser.add_argument("--intervention-shuffle", type=str, default="none")
    parser.add_argument("--patrol-hotspot-filter-mode", type=str, default="percentile")
    parser.add_argument("--patrol-hotspot-score-percentile", type=float, default=97.0)
    parser.add_argument("--outdir", type=str, default="results/diagnostic_feedback_truth_and_task_distance")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    field_cfg = _build_field_cfg(args)
    field_run_rows = []
    field_eval_rows = []
    for run_idx in range(int(args.runs)):
        seed = int(args.seed_start) + run_idx
        res = simulate_field_truth_run(run_idx, seed, field_cfg)
        field_run_rows.append(res["paired_metrics"])
        field_eval_rows.extend(res["eval_rows"])

    field_run_df = pd.DataFrame(field_run_rows)
    field_eval_df = pd.DataFrame(field_eval_rows)
    field_run_df.to_csv(outdir / "feedback_field_verification_per_run.csv", index=False)
    field_eval_df.to_csv(outdir / "feedback_field_verification_per_eval.csv", index=False)
    field_summary = _summarize_field_runs(field_run_df)

    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    run_params = {
        "T_end": float(args.T_end),
        "dt": float(args.dt),
        "seed": int(args.task_seed),
        "W": 500.0,
        "H": 500.0,
        "NX": 80,
        "NY": 64,
        "Nrobots": 6,
        "uav_fraction": 0.0,
        "warmup_s": float(args.warmup_s),
        "task_replan_period_s": float(args.task_replan_period_s),
        "patrol_hotspot_filter_mode": str(args.patrol_hotspot_filter_mode),
        "patrol_hotspot_score_percentile": float(args.patrol_hotspot_score_percentile),
        "alpha_inhib": float(args.alpha_inhib),
        "omega_inhib": float(args.omega_inhib),
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
    }

    pred = _collect_sampled_frames(
        label="prediction_only",
        sim_mode="prediction_only",
        run_params=run_params,
        overrides={
            "enable_intervention_feedback": False,
            "enable_model_scored_deterring": False,
        },
        sample_every_s=float(args.sample_every_s),
        hotspot_top_k=int(args.hotspot_top_k),
    )
    prop = _collect_sampled_frames(
        label="proposed_feedback_only",
        sim_mode="proposed",
        run_params=run_params,
        overrides={
            "enable_intervention_feedback": True,
            "enable_model_scored_deterring": False,
        },
        sample_every_s=float(args.sample_every_s),
        hotspot_top_k=int(args.hotspot_top_k),
    )

    task_df = _build_task_distance_rows(pred, prop, float(args.match_radius_m))
    task_df.to_csv(outdir / "feedback_task_distance_per_time.csv", index=False)
    task_summary = _summarize_task_distances(task_df)

    summary = {
        "parameters": {
            "runs": int(args.runs),
            "seed_start": int(args.seed_start),
            "task_seed": int(args.task_seed),
            "T_end": float(args.T_end),
            "dt": float(args.dt),
            "warmup_s": float(args.warmup_s),
            "eval_period_s": float(args.eval_period_s),
            "forecast_horizon_s": float(args.forecast_horizon_s),
            "sample_every_s": float(args.sample_every_s),
            "task_replan_period_s": float(args.task_replan_period_s),
            "hotspot_top_k": int(args.hotspot_top_k),
            "match_radius_m": float(args.match_radius_m),
            "alpha_inhib": float(args.alpha_inhib),
            "omega_inhib": float(args.omega_inhib),
            "mu_base": float(args.mu_base),
            "bg_ema": float(args.bg_ema),
            "intervention_shuffle": str(args.intervention_shuffle),
            "patrol_hotspot_filter_mode": str(args.patrol_hotspot_filter_mode),
            "patrol_hotspot_score_percentile": float(args.patrol_hotspot_score_percentile),
        },
        "field_verification": field_summary,
        "task_distance": task_summary,
        "prediction_only_final_metrics": pred["final_metrics"],
        "proposed_feedback_only_final_metrics": prop["final_metrics"],
    }

    conclusions = []
    if field_summary["field_brier"]["wins_proposed"] == int(args.runs):
        conclusions.append("Feedback-enabled proposed model beats prediction_only on field Brier in every subsystem run.")
    elif field_summary["field_brier"]["mean_delta"] < 0.0:
        conclusions.append("Feedback-enabled proposed model improves field Brier on average, but not on every run.")
    else:
        conclusions.append("Feedback-enabled proposed model does not improve field Brier in the isolated subsystem.")

    if field_summary["field_logloss"]["mean_delta"] < 0.0 and field_summary["nll"]["mean_delta"] < 0.0:
        conclusions.append("Feedback-enabled proposed model also improves log-loss and event NLL in the isolated subsystem.")
    else:
        conclusions.append("Feedback-enabled proposed model does not consistently improve log-loss/NLL in the isolated subsystem.")

    if task_summary["patrol_candidate_mean_match_distance_m"] > 0.0:
        conclusions.append("Generated patrol tasks diverge spatially between prediction_only and feedback-only proposed runs.")
    if task_summary["accepted_patrol_overlap_mean"] < task_summary["patrol_candidate_overlap_mean"]:
        conclusions.append("The biggest divergence appears after ranking/acceptance, not just candidate generation.")

    summary["conclusions"] = conclusions

    with open(outdir / "feedback_truth_and_task_distance_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with open(outdir / "feedback_truth_and_task_distance_report.md", "w", encoding="utf-8") as f:
        f.write("# Feedback Truth And Task Distance Diagnostic\n\n")
        f.write("## Parameters\n\n")
        for k, v in summary["parameters"].items():
            f.write(f"- `{k}`: `{v}`\n")

        f.write("\n## Isolated Field Verification\n\n")
        for name, vals in field_summary.items():
            f.write(f"- `{name}`: mean delta `{vals['mean_delta']}`, mean improvement `%` `{vals['mean_improvement_pct']}`, wins `{vals['wins_proposed']}/{vals['runs']}`\n")

        f.write("\n## Task Distance Summary\n\n")
        for k, v in task_summary.items():
            f.write(f"- `{k}`: `{v}`\n")

        f.write("\n## Final Production Metrics\n\n")
        f.write("### prediction_only\n\n")
        for k, v in pred["final_metrics"].items():
            f.write(f"- `{k}`: `{v}`\n")
        f.write("\n### proposed_feedback_only\n\n")
        for k, v in prop["final_metrics"].items():
            f.write(f"- `{k}`: `{v}`\n")

        f.write("\n## Conclusions\n\n")
        for line in conclusions:
            f.write(f"- {line}\n")

    _plot_task_distances(task_df, outdir / "feedback_task_distance_timeseries.png")
    print(f"[done] feedback truth/task diagnostic saved to: {outdir}")


if __name__ == "__main__":
    main()
