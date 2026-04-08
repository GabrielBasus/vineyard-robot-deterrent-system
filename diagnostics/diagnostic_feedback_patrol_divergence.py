from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import DeterrentSystem as ds


def _safe_mean(vals) -> float:
    arr = [float(v) for v in vals if np.isfinite(float(v))]
    return float(np.mean(arr)) if arr else float("nan")


def _xy_points(rows) -> list[tuple[float, float]]:
    pts = []
    for row in rows:
        try:
            pts.append((float(row.get("x", 0.0)), float(row.get("y", 0.0))))
        except Exception:
            continue
    return pts


def _patrol_points(tasks) -> list[tuple[float, float]]:
    pts = []
    for tr in tasks:
        if str(tr.get("state", "")).strip().lower() != "active":
            continue
        if str(tr.get("type", "")).strip().lower() != "patrolling":
            continue
        pts.append((float(tr.get("x", 0.0)), float(tr.get("y", 0.0))))
    return pts


def _greedy_match(points_a, points_b, max_radius_m: float) -> tuple[int, float]:
    if not points_a or not points_b:
        return 0, float("nan")
    max_r2 = float(max_radius_m) ** 2
    used_b = set()
    dists = []
    matches = 0
    for ax, ay in points_a:
        best_j = None
        best_d2 = None
        for j, (bx, by) in enumerate(points_b):
            if j in used_b:
                continue
            d2 = (float(ax) - float(bx)) ** 2 + (float(ay) - float(by)) ** 2
            if d2 > max_r2:
                continue
            if best_d2 is None or d2 < best_d2:
                best_d2 = d2
                best_j = j
        if best_j is not None:
            used_b.add(best_j)
            matches += 1
            dists.append(math.sqrt(best_d2))
    return matches, (_safe_mean(dists) if dists else float("nan"))


def _support_metrics(points, support_points, radius_m: float) -> tuple[float, float]:
    if not points:
        return float("nan"), float("nan")
    if not support_points:
        return 0.0, 0.0
    r2 = float(radius_m) ** 2
    counts = []
    for px, py in points:
        c = 0
        for sx, sy in support_points:
            if (float(px) - float(sx)) ** 2 + (float(py) - float(sy)) ** 2 <= r2:
                c += 1
        counts.append(float(c))
    hit_rate = float(sum(c > 0.0 for c in counts)) / float(len(counts))
    return hit_rate, _safe_mean(counts)


def _collect_sampled_frames(label: str, sim_mode: str, run_params: dict, overrides: dict, sample_every_s: float, hotspot_top_k: int):
    frames = ds.run_simulation_frames_persistent(
        simulation_mode=sim_mode,
        report_metrics_end=False,
        emit_planning_diagnostics=True,
        planning_hotspot_top_k=int(hotspot_top_k),
        **run_params,
        **overrides,
    )
    sampled = {}
    next_sample_t = -1e9
    last = None
    for snap in frames:
        last = snap
        t_s = float(snap.get("t", 0.0))
        if t_s < next_sample_t:
            continue
        next_sample_t = t_s + float(sample_every_s)
        planning = snap.get("planning_diagnostics") or {}
        model_diag = snap.get("model_diag", {})
        inhib_vals = [float(v.get("inhib_sum", float("nan"))) for v in model_diag.values()]
        sampled[int(round(t_s))] = {
            "t_s": t_s,
            "global_hotspots": list(planning.get("global_hotspots", [])),
            "patrol_candidates": list(planning.get("patrol_candidates", [])),
            "accepted_patrol_tasks": list(planning.get("accepted_patrol_tasks", [])),
            "tasks_active": list(snap.get("tasks_active", [])),
            "truth_pts": list(snap.get("truth_pts", [])),
            "det_pts": list(snap.get("det_pts", [])),
            "metrics": dict(snap.get("metrics", {})),
            "inhib_sum_total": float(np.nansum(inhib_vals)) if inhib_vals else float("nan"),
        }
    return {
        "label": label,
        "sampled": sampled,
        "final_metrics": dict((last or {}).get("metrics", {})),
    }


def _plot_timeseries(per_time_df: pd.DataFrame, out_png: Path) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    t = per_time_df["t_s"]

    axes[0].plot(t, per_time_df["hotspot_overlap"], label="Hotspot overlap")
    axes[0].plot(t, per_time_df["patrol_candidate_overlap"], label="Patrol candidate overlap")
    axes[0].plot(t, per_time_df["active_patrol_overlap"], label="Active patrol overlap")
    axes[0].set_ylabel("Overlap")
    axes[0].grid(alpha=0.25)
    axes[0].legend(loc="best", fontsize=8)

    axes[1].plot(t, per_time_df["prediction_hotspot_truth_hit_rate"], label="Pred hotspot truth hit")
    axes[1].plot(t, per_time_df["proposed_hotspot_truth_hit_rate"], label="Prop hotspot truth hit")
    axes[1].plot(t, per_time_df["prediction_active_patrol_truth_hit_rate"], label="Pred active patrol truth hit")
    axes[1].plot(t, per_time_df["proposed_active_patrol_truth_hit_rate"], label="Prop active patrol truth hit")
    axes[1].set_ylabel("Recent truth hit rate")
    axes[1].grid(alpha=0.25)
    axes[1].legend(loc="best", fontsize=8)

    axes[2].plot(t, per_time_df["prediction_inhib_sum_total"], label="Pred inhibition")
    axes[2].plot(t, per_time_df["proposed_inhib_sum_total"], label="Prop inhibition")
    axes[2].plot(t, per_time_df["prediction_boundary_message_count"], label="Pred msgs")
    axes[2].plot(t, per_time_df["proposed_boundary_message_count"], label="Prop msgs")
    axes[2].set_ylabel("Inhibition / messages")
    axes[2].set_xlabel("time (s)")
    axes[2].grid(alpha=0.25)
    axes[2].legend(loc="best", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _plot_support_scatter(per_time_df: pd.DataFrame, out_png: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].scatter(
        per_time_df["prediction_hotspot_truth_count_mean"],
        per_time_df["proposed_hotspot_truth_count_mean"],
        alpha=0.8,
    )
    axes[0].plot([0, 1], [0, 1], transform=axes[0].transAxes, ls="--", c="gray")
    axes[0].set_title("Hotspot Recent-Truth Count")
    axes[0].set_xlabel("prediction_only")
    axes[0].set_ylabel("proposed")
    axes[0].grid(alpha=0.25)

    axes[1].scatter(
        per_time_df["prediction_active_patrol_truth_count_mean"],
        per_time_df["proposed_active_patrol_truth_count_mean"],
        alpha=0.8,
    )
    axes[1].plot([0, 1], [0, 1], transform=axes[1].transAxes, ls="--", c="gray")
    axes[1].set_title("Active Patrol Recent-Truth Count")
    axes[1].set_xlabel("prediction_only")
    axes[1].set_ylabel("proposed")
    axes[1].grid(alpha=0.25)

    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare hotspot/patrol divergence between prediction_only and feedback-only proposed production runs."
    )
    parser.add_argument("--T-end", type=float, default=3 * 3600.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--sample-every-s", type=float, default=30.0)
    parser.add_argument("--hotspot-top-k", type=int, default=5)
    parser.add_argument("--match-radius-m", type=float, default=25.0)
    parser.add_argument("--support-radius-m", type=float, default=25.0)
    parser.add_argument("--outdir", type=str, default="results/diagnostic_feedback_patrol_divergence")
    parser.add_argument("--task-replan-period-s", type=float, default=60.0)
    parser.add_argument("--patrol-hotspot-filter-mode", type=str, default="percentile")
    parser.add_argument("--patrol-hotspot-score-percentile", type=float, default=97.0)
    parser.add_argument("--alpha-inhib", type=float, default=0.45)
    parser.add_argument("--omega-inhib", type=float, default=600.0)
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

    ts = sorted(set(pred["sampled"].keys()) & set(prop["sampled"].keys()))
    rows = []
    for t_key in ts:
        pred_snap = pred["sampled"][t_key]
        prop_snap = prop["sampled"][t_key]

        pred_hotspots = _xy_points(pred_snap["global_hotspots"])
        prop_hotspots = _xy_points(prop_snap["global_hotspots"])
        pred_patrol_candidates = _xy_points(pred_snap["patrol_candidates"])
        prop_patrol_candidates = _xy_points(prop_snap["patrol_candidates"])
        pred_active_patrols = _patrol_points(pred_snap["tasks_active"])
        prop_active_patrols = _patrol_points(prop_snap["tasks_active"])
        pred_truth_pts = [(float(x), float(y)) for x, y in pred_snap["truth_pts"]]
        prop_truth_pts = [(float(x), float(y)) for x, y in prop_snap["truth_pts"]]
        pred_det_pts = [(float(x), float(y)) for x, y in pred_snap["det_pts"]]
        prop_det_pts = [(float(x), float(y)) for x, y in prop_snap["det_pts"]]

        hs_matches, hs_dist = _greedy_match(pred_hotspots, prop_hotspots, float(args.match_radius_m))
        cand_matches, cand_dist = _greedy_match(pred_patrol_candidates, prop_patrol_candidates, float(args.match_radius_m))
        patrol_matches, patrol_dist = _greedy_match(pred_active_patrols, prop_active_patrols, float(args.match_radius_m))

        pred_hs_truth_hit, pred_hs_truth_count = _support_metrics(pred_hotspots, pred_truth_pts, float(args.support_radius_m))
        prop_hs_truth_hit, prop_hs_truth_count = _support_metrics(prop_hotspots, prop_truth_pts, float(args.support_radius_m))
        pred_pat_truth_hit, pred_pat_truth_count = _support_metrics(pred_active_patrols, pred_truth_pts, float(args.support_radius_m))
        prop_pat_truth_hit, prop_pat_truth_count = _support_metrics(prop_active_patrols, prop_truth_pts, float(args.support_radius_m))
        pred_hs_det_hit, pred_hs_det_count = _support_metrics(pred_hotspots, pred_det_pts, float(args.support_radius_m))
        prop_hs_det_hit, prop_hs_det_count = _support_metrics(prop_hotspots, prop_det_pts, float(args.support_radius_m))

        rows.append(
            {
                "t_s": float(pred_snap["t_s"]),
                "hotspot_overlap": float(hs_matches) / float(max(max(len(pred_hotspots), len(prop_hotspots)), 1)),
                "hotspot_mean_match_distance_m": hs_dist,
                "patrol_candidate_overlap": float(cand_matches) / float(max(max(len(pred_patrol_candidates), len(prop_patrol_candidates)), 1)),
                "patrol_candidate_mean_match_distance_m": cand_dist,
                "active_patrol_overlap": float(patrol_matches) / float(max(max(len(pred_active_patrols), len(prop_active_patrols)), 1)),
                "active_patrol_mean_match_distance_m": patrol_dist,
                "prediction_hotspot_truth_hit_rate": pred_hs_truth_hit,
                "proposed_hotspot_truth_hit_rate": prop_hs_truth_hit,
                "prediction_hotspot_truth_count_mean": pred_hs_truth_count,
                "proposed_hotspot_truth_count_mean": prop_hs_truth_count,
                "prediction_active_patrol_truth_hit_rate": pred_pat_truth_hit,
                "proposed_active_patrol_truth_hit_rate": prop_pat_truth_hit,
                "prediction_active_patrol_truth_count_mean": pred_pat_truth_count,
                "proposed_active_patrol_truth_count_mean": prop_pat_truth_count,
                "prediction_hotspot_detection_hit_rate": pred_hs_det_hit,
                "proposed_hotspot_detection_hit_rate": prop_hs_det_hit,
                "prediction_hotspot_detection_count_mean": pred_hs_det_count,
                "proposed_hotspot_detection_count_mean": prop_hs_det_count,
                "prediction_hotspot_count": int(len(pred_hotspots)),
                "proposed_hotspot_count": int(len(prop_hotspots)),
                "prediction_patrol_candidate_count": int(len(pred_patrol_candidates)),
                "proposed_patrol_candidate_count": int(len(prop_patrol_candidates)),
                "prediction_active_patrol_count": int(len(pred_active_patrols)),
                "proposed_active_patrol_count": int(len(prop_active_patrols)),
                "prediction_inhib_sum_total": float(pred_snap["inhib_sum_total"]),
                "proposed_inhib_sum_total": float(prop_snap["inhib_sum_total"]),
                "prediction_boundary_message_count": float(pred_snap["metrics"].get("boundary_message_count", float("nan"))),
                "proposed_boundary_message_count": float(prop_snap["metrics"].get("boundary_message_count", float("nan"))),
                "prediction_exposure": float(pred_snap["metrics"].get("value_weighted_exposure", float("nan"))),
                "proposed_exposure": float(prop_snap["metrics"].get("value_weighted_exposure", float("nan"))),
            }
        )

    per_time_df = pd.DataFrame(rows)
    per_time_df.to_csv(outdir / "feedback_patrol_divergence_per_time.csv", index=False)

    final_pred = pred["final_metrics"]
    final_prop = prop["final_metrics"]
    exposure_improve_pct = float(
        100.0 * (float(final_pred.get("value_weighted_exposure", np.nan)) - float(final_prop.get("value_weighted_exposure", np.nan)))
        / max(float(final_pred.get("value_weighted_exposure", np.nan)), 1e-12)
    )
    response_improve_pct = float(
        100.0 * (float(final_pred.get("mean_response_time_s", np.nan)) - float(final_prop.get("mean_response_time_s", np.nan)))
        / max(float(final_pred.get("mean_response_time_s", np.nan)), 1e-12)
    )
    summary = {
        "parameters": {
            **run_params,
            "hotspot_top_k": int(args.hotspot_top_k),
            "match_radius_m": float(args.match_radius_m),
            "support_radius_m": float(args.support_radius_m),
        },
        "prediction_only_final_metrics": final_pred,
        "proposed_feedback_only_final_metrics": final_prop,
        "comparisons": {
            "exposure_improve_pct": exposure_improve_pct,
            "response_improve_pct": response_improve_pct,
            "hotspot_overlap_mean": _safe_mean(per_time_df["hotspot_overlap"].tolist()),
            "patrol_candidate_overlap_mean": _safe_mean(per_time_df["patrol_candidate_overlap"].tolist()),
            "active_patrol_overlap_mean": _safe_mean(per_time_df["active_patrol_overlap"].tolist()),
            "prediction_hotspot_truth_hit_rate_mean": _safe_mean(per_time_df["prediction_hotspot_truth_hit_rate"].tolist()),
            "proposed_hotspot_truth_hit_rate_mean": _safe_mean(per_time_df["proposed_hotspot_truth_hit_rate"].tolist()),
            "prediction_active_patrol_truth_hit_rate_mean": _safe_mean(per_time_df["prediction_active_patrol_truth_hit_rate"].tolist()),
            "proposed_active_patrol_truth_hit_rate_mean": _safe_mean(per_time_df["proposed_active_patrol_truth_hit_rate"].tolist()),
            "prediction_hotspot_detection_hit_rate_mean": _safe_mean(per_time_df["prediction_hotspot_detection_hit_rate"].tolist()),
            "proposed_hotspot_detection_hit_rate_mean": _safe_mean(per_time_df["proposed_hotspot_detection_hit_rate"].tolist()),
            "prediction_inhib_sum_total_mean": _safe_mean(per_time_df["prediction_inhib_sum_total"].tolist()),
            "proposed_inhib_sum_total_mean": _safe_mean(per_time_df["proposed_inhib_sum_total"].tolist()),
        },
    }

    conclusions = []
    if summary["comparisons"]["proposed_hotspot_truth_hit_rate_mean"] < summary["comparisons"]["prediction_hotspot_truth_hit_rate_mean"]:
        conclusions.append("Proposed feedback hotspots align with recent truth less often than prediction_only hotspots.")
    if summary["comparisons"]["proposed_active_patrol_truth_hit_rate_mean"] < summary["comparisons"]["prediction_active_patrol_truth_hit_rate_mean"]:
        conclusions.append("Proposed active patrols align with recent truth less often than prediction_only patrols.")
    if summary["comparisons"]["active_patrol_overlap_mean"] < 0.5:
        conclusions.append("Feedback is materially reshaping active patrol placement relative to prediction_only.")
    if not conclusions:
        conclusions.append("Feedback changes patrol/hotspot placement, but this diagnostic does not show a clear evidence-alignment failure.")
    summary["conclusions"] = conclusions

    with open(outdir / "feedback_patrol_divergence_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with open(outdir / "feedback_patrol_divergence_report.md", "w", encoding="utf-8") as f:
        f.write("# Feedback Patrol Divergence Diagnostic\n\n")
        f.write("## Parameters\n\n")
        for k, v in summary["parameters"].items():
            f.write(f"- `{k}`: `{v}`\n")
        f.write("\n## Final Metrics\n\n")
        f.write("### prediction_only\n\n")
        for k, v in final_pred.items():
            f.write(f"- `{k}`: `{v}`\n")
        f.write("\n### proposed_feedback_only\n\n")
        for k, v in final_prop.items():
            f.write(f"- `{k}`: `{v}`\n")
        f.write("\n## Aggregate Comparisons\n\n")
        for k, v in summary["comparisons"].items():
            f.write(f"- `{k}`: `{v}`\n")
        f.write("\n## Conclusions\n\n")
        for line in conclusions:
            f.write(f"- {line}\n")

    _plot_timeseries(per_time_df, outdir / "feedback_patrol_divergence_timeseries.png")
    _plot_support_scatter(per_time_df, outdir / "feedback_patrol_divergence_support_scatter.png")
    print(f"[done] feedback patrol divergence saved to: {outdir}")


if __name__ == "__main__":
    main()
