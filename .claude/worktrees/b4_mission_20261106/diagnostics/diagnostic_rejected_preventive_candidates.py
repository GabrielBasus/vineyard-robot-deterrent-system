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
from diagnostics.diagnostic_preventive_policy import (
    _analyze_proposed_run,
    _extract_event_stream,
    _final_metrics,
    _future_event_stats,
    _recent_event_count,
    _safe_mean,
)


def _summarize(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "count": 0,
            "future_truth_hit_rate": float("nan"),
            "future_truth_count_mean": float("nan"),
            "recent_truth_count_mean": float("nan"),
            "p_event_mean": float("nan"),
            "predicted_deltaJ_mean": float("nan"),
            "deltaJ_per_cost_mean": float("nan"),
            "eta_s_mean": float("nan"),
        }
    return {
        "count": int(len(df)),
        "future_truth_hit_rate": float(df["future_truth_hit"].mean()),
        "future_truth_count_mean": float(df["future_truth_count"].mean()),
        "recent_truth_count_mean": float(df["recent_truth_count"].mean()),
        "p_event_mean": _safe_mean(df["p_event"]),
        "predicted_deltaJ_mean": _safe_mean(df["predicted_deltaJ"]),
        "deltaJ_per_cost_mean": _safe_mean(df["deltaJ_per_cost"]),
        "eta_s_mean": _safe_mean(df["eta_s"]),
    }


def _plot_reason_quality(df: pd.DataFrame, out_png: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    if df.empty:
        for ax in axes:
            ax.text(0.5, 0.5, "No rejected model-scored candidates", ha="center", va="center")
            ax.set_axis_off()
    else:
        grouped = df.groupby("reason")
        labels = list(grouped.groups.keys())
        hit_rates = [float(grouped.get_group(k)["future_truth_hit"].mean()) for k in labels]
        counts = [int(len(grouped.get_group(k))) for k in labels]
        axes[0].bar(labels, hit_rates, color="#1f77b4")
        axes[0].set_title("Rejected Candidates: Future-Truth Hit Rate by Reason")
        axes[0].tick_params(axis="x", rotation=30)
        axes[0].grid(alpha=0.25)

        axes[1].bar(labels, counts, color="#ff7f0e")
        axes[1].set_title("Rejected Candidates: Count by Reason")
        axes[1].tick_params(axis="x", rotation=30)
        axes[1].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _build_recommendations(rejected_df: pd.DataFrame, accepted_df: pd.DataFrame) -> list[str]:
    out: list[str] = []
    if rejected_df.empty:
        out.append("No model-scored preventive candidates were rejected in dispatch; the current bottleneck is earlier in generation/gating.")
        return out
    by_reason = {reason: grp for reason, grp in rejected_df.groupby("reason")}
    for reason in ("busy_primary", "busy_fallback_quality", "direct_conflict", "cycle_cap", "model_det_cap", "budget"):
        grp = by_reason.get(reason)
        if grp is None or grp.empty:
            continue
        hit_rate = float(grp["future_truth_hit"].mean())
        if hit_rate >= 0.55:
            out.append(f"Rejected `{reason}` candidates have meaningful future-truth support; this filter may be too strict.")
    if not accepted_df.empty:
        accepted_hit = float(accepted_df["future_truth_hit"].mean())
        rejected_hit = float(rejected_df["future_truth_hit"].mean())
        if rejected_hit > accepted_hit + 0.05:
            out.append("Rejected preventive candidates are stronger than accepted ones on future-truth hit rate; ranking and dispatch priority need revision.")
    if not out:
        out.append("Rejected preventive candidates are not obviously higher-yield than accepted ones; keeping the conservative filters is justified for now.")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit generated-but-rejected model-scored preventive candidates.")
    parser.add_argument("--T-end", type=float, default=3 * 3600.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--eval-horizon-s", type=float, default=300.0)
    parser.add_argument("--spatial-radius-m", type=float, default=25.0)
    parser.add_argument("--recent-window-s", type=float, default=180.0)
    parser.add_argument("--outdir", type=str, default="results/diagnostic_rejected_preventive")
    parser.add_argument("--task-replan-period-s", type=float, default=60.0)
    parser.add_argument("--model-deterring-gate-policy", type=str, default="sprt_capacity")
    parser.add_argument("--model-deterring-sprt-alpha", type=float, default=0.25)
    parser.add_argument("--model-deterring-sprt-beta", type=float, default=0.40)
    parser.add_argument("--model-deterring-sprt-patch-radius-m", type=float, default=30.0)
    parser.add_argument("--model-deterring-chance-threshold", type=float, default=0.25)
    parser.add_argument("--model-deterring-min-deltaj-per-cost", type=float, default=100000.0)
    parser.add_argument("--model-deterring-capacity-rho-max", type=float, default=0.85)
    parser.add_argument("--model-deterring-score-margin", type=float, default=0.10)
    parser.add_argument("--model-deterring-global-admission-cap-per-cycle", type=int, default=1)
    parser.add_argument("--model-deterring-require-idle-robot-for-admission", type=int, default=0)
    parser.add_argument("--model-deterring-prefer-idle-robots-for-assignment", type=int, default=1)
    parser.add_argument("--model-deterring-busy-fallback-p-event-min", type=float, default=0.95)
    parser.add_argument("--model-deterring-busy-fallback-deltaj-per-cost-min", type=float, default=2000000.0)
    parser.add_argument("--model-deterring-busy-fallback-eta-s-max", type=float, default=1.25)
    parser.add_argument("--protect-direct-detection-from-model-deterring", type=int, default=1)
    parser.add_argument("--model-deterring-direct-conflict-radius-m", type=float, default=35.0)
    parser.add_argument("--model-deterring-direct-conflict-window-s", type=float, default=120.0)
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
        "event_viz_window_s": max(60.0, 3.0 * float(args.dt)),
        "model_deterring_window_s": 120.0,
        "model_deterring_gate_policy": str(args.model_deterring_gate_policy),
        "model_deterring_sprt_alpha": float(args.model_deterring_sprt_alpha),
        "model_deterring_sprt_beta": float(args.model_deterring_sprt_beta),
        "model_deterring_sprt_patch_radius_m": float(args.model_deterring_sprt_patch_radius_m),
        "model_deterring_chance_threshold": float(args.model_deterring_chance_threshold),
        "model_deterring_min_deltaJ_per_cost": float(args.model_deterring_min_deltaj_per_cost),
        "model_deterring_capacity_rho_max": float(args.model_deterring_capacity_rho_max),
        "model_deterring_score_margin": float(args.model_deterring_score_margin),
        "model_deterring_global_admission_cap_per_cycle": int(args.model_deterring_global_admission_cap_per_cycle),
        "model_deterring_require_idle_robot_for_admission": bool(int(args.model_deterring_require_idle_robot_for_admission)),
        "model_deterring_prefer_idle_robots_for_assignment": bool(int(args.model_deterring_prefer_idle_robots_for_assignment)),
        "model_deterring_busy_fallback_p_event_min": float(args.model_deterring_busy_fallback_p_event_min),
        "model_deterring_busy_fallback_deltaJ_per_cost_min": float(args.model_deterring_busy_fallback_deltaj_per_cost_min),
        "model_deterring_busy_fallback_eta_s_max": float(args.model_deterring_busy_fallback_eta_s_max),
        "protect_direct_detection_from_model_deterring": bool(int(args.protect_direct_detection_from_model_deterring)),
        "model_deterring_direct_conflict_radius_m": float(args.model_deterring_direct_conflict_radius_m),
        "model_deterring_direct_conflict_window_s": float(args.model_deterring_direct_conflict_window_s),
        "patrol_hotspot_filter_mode": str(args.patrol_hotspot_filter_mode),
        "patrol_hotspot_score_percentile": float(args.patrol_hotspot_score_percentile),
        "emit_rejected_model_det_debug": True,
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
    }

    frames = list(ds.run_simulation_frames_persistent(simulation_mode="proposed", **run_params))
    truth_events = _extract_event_stream(frames, "truth_pts")
    detection_events = _extract_event_stream(frames, "det_pts")
    accepted_task_df, _, _ = _analyze_proposed_run(
        frames,
        truth_events=truth_events,
        detection_events=detection_events,
        eval_horizon_s=float(args.eval_horizon_s),
        spatial_radius_m=float(args.spatial_radius_m),
        recent_window_s=float(args.recent_window_s),
    )
    accepted_model_df = accepted_task_df[accepted_task_df["task_group"] == "model_scored_deterring"].copy()

    rejected_rows: list[dict] = []
    processed_dispatch_times: set[float] = set()
    for snap in frames:
        dispatch = snap.get("dispatch_structured", {})
        dispatch_t = float(dispatch.get("now_t", snap["t"]))
        if dispatch_t in processed_dispatch_times:
            continue
        processed_dispatch_times.add(dispatch_t)
        for row in dispatch.get("rejected_model_det_tasks", []) or []:
            item = dict(row)
            t0 = float(item.get("time", dispatch_t))
            x = float(item.get("x", 0.0))
            y = float(item.get("y", 0.0))
            recent_truth = _recent_event_count(x, y, t0, truth_events, float(args.recent_window_s), float(args.spatial_radius_m))
            future_truth_count, future_truth_min_dt, future_truth_min_dist = _future_event_stats(
                x, y, t0, truth_events, float(args.eval_horizon_s), float(args.spatial_radius_m)
            )
            future_det_count, _, _ = _future_event_stats(
                x, y, t0, detection_events, float(args.eval_horizon_s), float(args.spatial_radius_m)
            )
            item["recent_truth_count"] = int(recent_truth)
            item["future_truth_count"] = int(future_truth_count)
            item["future_truth_hit"] = int(future_truth_count > 0)
            item["future_truth_min_dt_s"] = float(future_truth_min_dt)
            item["future_truth_min_dist_m"] = float(future_truth_min_dist)
            item["future_detection_count"] = int(future_det_count)
            rejected_rows.append(item)
    rejected_df = pd.DataFrame(rejected_rows)

    summary = {
        "parameters": run_params,
        "final_metrics": _final_metrics(frames[-1]),
        "accepted_model_scored": _summarize(accepted_model_df),
        "rejected_model_scored_overall": _summarize(rejected_df),
        "rejected_by_reason": {
            reason: _summarize(grp) for reason, grp in rejected_df.groupby("reason")
        } if not rejected_df.empty else {},
    }
    summary["critical_recommendations"] = _build_recommendations(rejected_df, accepted_model_df)

    rejected_df.to_csv(outdir / "rejected_preventive_candidates.csv", index=False)
    accepted_model_df.to_csv(outdir / "accepted_model_scored_candidates.csv", index=False)
    with open(outdir / "rejected_preventive_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    _plot_reason_quality(rejected_df, outdir / "rejected_preventive_by_reason.png")

    with open(outdir / "rejected_preventive_report.md", "w", encoding="utf-8") as f:
        f.write("# Rejected Preventive Candidate Diagnostic\n\n")
        f.write("## Parameters\n\n")
        for key, value in run_params.items():
            f.write(f"- `{key}`: `{value}`\n")
        f.write("\n## Accepted Model-Scored Summary\n\n")
        for key, value in summary["accepted_model_scored"].items():
            f.write(f"- `{key}`: `{value}`\n")
        f.write("\n## Rejected Model-Scored Summary\n\n")
        for key, value in summary["rejected_model_scored_overall"].items():
            f.write(f"- `{key}`: `{value}`\n")
        f.write("\n## Rejected By Reason\n\n")
        for reason, stats in summary["rejected_by_reason"].items():
            f.write(f"### {reason}\n\n")
            for key, value in stats.items():
                f.write(f"- `{key}`: `{value}`\n")
            f.write("\n")
        f.write("## Critical Recommendations\n\n")
        for rec in summary["critical_recommendations"]:
            f.write(f"- {rec}\n")


if __name__ == "__main__":
    main()
