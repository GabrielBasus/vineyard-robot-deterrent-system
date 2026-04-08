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
from diagnostics.diagnostic_feedback_patrol_divergence import _collect_sampled_frames, _safe_mean, _xy_points


def _score_sorted_rows(rows):
    out = []
    cleaned = []
    for row in rows:
        try:
            cleaned.append(
                {
                    "id": row.get("id"),
                    "x": float(row.get("x", 0.0)),
                    "y": float(row.get("y", 0.0)),
                    "score": float(row.get("score", 0.0)),
                    "utility": float(row.get("utility", 0.0)),
                    "eta_s": float(row.get("eta_s", float("nan"))),
                    "origin": row.get("origin"),
                    "mode": row.get("mode"),
                    "robot_id": row.get("robot_id"),
                }
            )
        except Exception:
            continue
    cleaned.sort(key=lambda r: (float(r["score"]), float(r["utility"])), reverse=True)
    for idx, row in enumerate(cleaned, start=1):
        rr = dict(row)
        rr["rank"] = int(idx)
        out.append(rr)
    return out


def _match_row_pairs(rows_a, rows_b, max_radius_m: float):
    if not rows_a or not rows_b:
        return []
    used_b = set()
    max_r2 = float(max_radius_m) ** 2
    pairs = []
    for ra in rows_a:
        best_j = None
        best_d2 = None
        for j, rb in enumerate(rows_b):
            if j in used_b:
                continue
            d2 = (float(ra["x"]) - float(rb["x"])) ** 2 + (float(ra["y"]) - float(rb["y"])) ** 2
            if d2 > max_r2:
                continue
            if best_d2 is None or d2 < best_d2:
                best_d2 = d2
                best_j = j
        if best_j is None:
            continue
        used_b.add(best_j)
        pairs.append((ra, rows_b[best_j], math.sqrt(best_d2)))
    return pairs


def _support_count(x: float, y: float, support_points, radius_m: float) -> int:
    if not support_points:
        return 0
    r2 = float(radius_m) ** 2
    c = 0
    for sx, sy in support_points:
        if (float(x) - float(sx)) ** 2 + (float(y) - float(sy)) ** 2 <= r2:
            c += 1
    return int(c)


def _build_pair_rows(pred_snap, prop_snap, key: str, match_radius_m: float, support_radius_m: float):
    pred_rows = _score_sorted_rows(pred_snap.get(key, []))
    prop_rows = _score_sorted_rows(prop_snap.get(key, []))
    pred_truth_pts = [(float(x), float(y)) for x, y in pred_snap.get("truth_pts", [])]
    prop_truth_pts = [(float(x), float(y)) for x, y in prop_snap.get("truth_pts", [])]
    pred_det_pts = [(float(x), float(y)) for x, y in pred_snap.get("det_pts", [])]
    prop_det_pts = [(float(x), float(y)) for x, y in prop_snap.get("det_pts", [])]

    pair_rows = []
    for ra, rb, dist_m in _match_row_pairs(pred_rows, prop_rows, match_radius_m):
        pair_rows.append(
            {
                "t_s": float(pred_snap["t_s"]),
                "prediction_x": float(ra["x"]),
                "prediction_y": float(ra["y"]),
                "proposed_x": float(rb["x"]),
                "proposed_y": float(rb["y"]),
                "match_distance_m": float(dist_m),
                "prediction_score": float(ra["score"]),
                "proposed_score": float(rb["score"]),
                "delta_score_proposed_minus_prediction": float(rb["score"] - ra["score"]),
                "prediction_utility": float(ra["utility"]),
                "proposed_utility": float(rb["utility"]),
                "delta_utility_proposed_minus_prediction": float(rb["utility"] - ra["utility"]),
                "prediction_eta_s": float(ra["eta_s"]),
                "proposed_eta_s": float(rb["eta_s"]),
                "prediction_rank": int(ra["rank"]),
                "proposed_rank": int(rb["rank"]),
                "delta_rank_proposed_minus_prediction": int(rb["rank"] - ra["rank"]),
                "prediction_truth_support_count": int(_support_count(ra["x"], ra["y"], pred_truth_pts, support_radius_m)),
                "proposed_truth_support_count": int(_support_count(rb["x"], rb["y"], prop_truth_pts, support_radius_m)),
                "prediction_detection_support_count": int(_support_count(ra["x"], ra["y"], pred_det_pts, support_radius_m)),
                "proposed_detection_support_count": int(_support_count(rb["x"], rb["y"], prop_det_pts, support_radius_m)),
            }
        )
    return pair_rows, len(pred_rows), len(prop_rows)


def _summarize_pairs(pair_df: pd.DataFrame, pred_counts, prop_counts):
    if pair_df.empty:
        return {
            "overlap_mean": 0.0,
            "mean_match_distance_m": float("nan"),
            "mean_delta_score_proposed_minus_prediction": float("nan"),
            "mean_abs_rank_shift": float("nan"),
            "downrank_fraction": float("nan"),
            "uprank_fraction": float("nan"),
            "prediction_truth_support_mean": float("nan"),
            "proposed_truth_support_mean": float("nan"),
            "prediction_detection_support_mean": float("nan"),
            "proposed_detection_support_mean": float("nan"),
        }

    overlap_series = []
    for a, b, matched in zip(pred_counts, prop_counts, pair_df.groupby("t_s").size().reindex(sorted(set(pair_df["t_s"])), fill_value=0).tolist()):
        overlap_series.append(float(matched) / float(max(max(a, b), 1)))

    delta_rank = pair_df["delta_rank_proposed_minus_prediction"].to_numpy(dtype=float)
    return {
        "overlap_mean": _safe_mean(overlap_series),
        "mean_match_distance_m": _safe_mean(pair_df["match_distance_m"].tolist()),
        "mean_delta_score_proposed_minus_prediction": _safe_mean(pair_df["delta_score_proposed_minus_prediction"].tolist()),
        "mean_abs_rank_shift": _safe_mean(np.abs(delta_rank).tolist()),
        "downrank_fraction": float(np.mean(delta_rank > 0.0)),
        "uprank_fraction": float(np.mean(delta_rank < 0.0)),
        "prediction_truth_support_mean": _safe_mean(pair_df["prediction_truth_support_count"].tolist()),
        "proposed_truth_support_mean": _safe_mean(pair_df["proposed_truth_support_count"].tolist()),
        "prediction_detection_support_mean": _safe_mean(pair_df["prediction_detection_support_count"].tolist()),
        "proposed_detection_support_mean": _safe_mean(pair_df["proposed_detection_support_count"].tolist()),
    }


def _plot_rank_scatter(pair_df: pd.DataFrame, out_png: Path, title: str) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].scatter(pair_df["prediction_score"], pair_df["proposed_score"], alpha=0.5)
    axes[0].plot([0, 1], [0, 1], transform=axes[0].transAxes, ls="--", c="gray")
    axes[0].set_xlabel("prediction_only score")
    axes[0].set_ylabel("proposed score")
    axes[0].set_title(f"{title}: score")
    axes[0].grid(alpha=0.25)

    axes[1].scatter(pair_df["prediction_rank"], pair_df["proposed_rank"], alpha=0.5)
    axes[1].plot([0, 1], [0, 1], transform=axes[1].transAxes, ls="--", c="gray")
    axes[1].set_xlabel("prediction_only rank")
    axes[1].set_ylabel("proposed rank")
    axes[1].set_title(f"{title}: rank")
    axes[1].grid(alpha=0.25)

    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare score/rank changes for matched patrol candidates and accepted patrol tasks under prediction_only vs feedback-only proposed."
    )
    parser.add_argument("--T-end", type=float, default=3 * 3600.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--sample-every-s", type=float, default=30.0)
    parser.add_argument("--task-replan-period-s", type=float, default=60.0)
    parser.add_argument("--patrol-hotspot-filter-mode", type=str, default="percentile")
    parser.add_argument("--patrol-hotspot-score-percentile", type=float, default=97.0)
    parser.add_argument("--alpha-inhib", type=float, default=0.45)
    parser.add_argument("--omega-inhib", type=float, default=600.0)
    parser.add_argument("--hotspot-top-k", type=int, default=5)
    parser.add_argument("--match-radius-m", type=float, default=25.0)
    parser.add_argument("--support-radius-m", type=float, default=25.0)
    parser.add_argument("--outdir", type=str, default="results/diagnostic_feedback_patrol_rank_compare")
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
        overrides={"enable_intervention_feedback": False, "enable_model_scored_deterring": False},
        sample_every_s=float(args.sample_every_s),
        hotspot_top_k=int(args.hotspot_top_k),
    )
    prop = _collect_sampled_frames(
        label="proposed_feedback_only",
        sim_mode="proposed",
        run_params=run_params,
        overrides={"enable_intervention_feedback": True, "enable_model_scored_deterring": False},
        sample_every_s=float(args.sample_every_s),
        hotspot_top_k=int(args.hotspot_top_k),
    )

    ts = sorted(set(pred["sampled"].keys()) & set(prop["sampled"].keys()))
    hotspot_rows = []
    hotspot_pred_counts = []
    hotspot_prop_counts = []
    candidate_rows = []
    candidate_pred_counts = []
    candidate_prop_counts = []
    accepted_rows = []
    accepted_pred_counts = []
    accepted_prop_counts = []

    for t_key in ts:
        pred_snap = pred["sampled"][t_key]
        prop_snap = prop["sampled"][t_key]

        hs_rows, hs_pred_n, hs_prop_n = _build_pair_rows(
            pred_snap, prop_snap, "global_hotspots", float(args.match_radius_m), float(args.support_radius_m)
        )
        hotspot_rows.extend(hs_rows)
        hotspot_pred_counts.append(hs_pred_n)
        hotspot_prop_counts.append(hs_prop_n)

        cand_rows, cand_pred_n, cand_prop_n = _build_pair_rows(
            pred_snap, prop_snap, "patrol_candidates", float(args.match_radius_m), float(args.support_radius_m)
        )
        candidate_rows.extend(cand_rows)
        candidate_pred_counts.append(cand_pred_n)
        candidate_prop_counts.append(cand_prop_n)

        acc_rows, acc_pred_n, acc_prop_n = _build_pair_rows(
            pred_snap, prop_snap, "accepted_patrol_tasks", float(args.match_radius_m), float(args.support_radius_m)
        )
        accepted_rows.extend(acc_rows)
        accepted_pred_counts.append(acc_pred_n)
        accepted_prop_counts.append(acc_prop_n)

    hotspot_df = pd.DataFrame(hotspot_rows)
    candidate_df = pd.DataFrame(candidate_rows)
    accepted_df = pd.DataFrame(accepted_rows)
    hotspot_df.to_csv(outdir / "feedback_hotspot_rank_compare.csv", index=False)
    candidate_df.to_csv(outdir / "feedback_patrol_candidate_rank_compare.csv", index=False)
    accepted_df.to_csv(outdir / "feedback_accepted_patrol_rank_compare.csv", index=False)

    summary = {
        "parameters": {
            **run_params,
            "hotspot_top_k": int(args.hotspot_top_k),
            "match_radius_m": float(args.match_radius_m),
            "support_radius_m": float(args.support_radius_m),
        },
        "hotspot_summary": _summarize_pairs(hotspot_df, hotspot_pred_counts, hotspot_prop_counts),
        "patrol_candidate_summary": _summarize_pairs(candidate_df, candidate_pred_counts, candidate_prop_counts),
        "accepted_patrol_summary": _summarize_pairs(accepted_df, accepted_pred_counts, accepted_prop_counts),
        "prediction_only_final_metrics": pred["final_metrics"],
        "proposed_feedback_only_final_metrics": prop["final_metrics"],
    }

    conclusions = []
    if summary["hotspot_summary"]["mean_abs_rank_shift"] > 1.0:
        conclusions.append("Feedback is materially re-ranking matched hotspots.")
    if summary["patrol_candidate_summary"]["mean_abs_rank_shift"] > 1.0:
        conclusions.append("Feedback is materially re-ranking matched patrol candidates.")
    if summary["accepted_patrol_summary"]["mean_abs_rank_shift"] > summary["patrol_candidate_summary"]["mean_abs_rank_shift"]:
        conclusions.append("Patrol divergence increases after acceptance/selection, not just at candidate generation.")
    if summary["patrol_candidate_summary"]["proposed_detection_support_mean"] < summary["patrol_candidate_summary"]["prediction_detection_support_mean"]:
        conclusions.append("Matched proposed patrol candidates have weaker recent-detection support than prediction_only candidates on average.")
    if not conclusions:
        conclusions.append("This diagnostic does not show a strong score/rank distortion for matched patrol tasks.")
    summary["conclusions"] = conclusions

    with open(outdir / "feedback_patrol_rank_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with open(outdir / "feedback_patrol_rank_report.md", "w", encoding="utf-8") as f:
        f.write("# Feedback Patrol Rank Compare Diagnostic\n\n")
        f.write("## Parameters\n\n")
        for k, v in summary["parameters"].items():
            f.write(f"- `{k}`: `{v}`\n")
        for section in ("hotspot_summary", "patrol_candidate_summary", "accepted_patrol_summary"):
            f.write(f"\n## {section}\n\n")
            for k, v in summary[section].items():
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

    if not hotspot_df.empty:
        _plot_rank_scatter(hotspot_df, outdir / "feedback_hotspot_rank_scatter.png", "Matched hotspots")
    if not candidate_df.empty:
        _plot_rank_scatter(candidate_df, outdir / "feedback_patrol_candidate_rank_scatter.png", "Matched patrol candidates")
    if not accepted_df.empty:
        _plot_rank_scatter(accepted_df, outdir / "feedback_accepted_patrol_rank_scatter.png", "Matched accepted patrols")

    print(f"[done] feedback patrol rank diagnostic saved to: {outdir}")


if __name__ == "__main__":
    main()
