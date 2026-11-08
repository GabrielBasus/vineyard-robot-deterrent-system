from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import DeterrentSystem as ds


def _task_source(tr: dict) -> str:
    ttype = str(tr.get("type", "")).strip().lower()
    if ttype != "deterring":
        return "-"
    mode = tr.get("mode")
    if mode not in (None, "", "none"):
        return "model_scored"
    origin = str(tr.get("origin", "")).strip().lower()
    return "direct_detection" if origin in ("", "detection") else "model_scored"


def _count_tasks(tasks: list[dict]) -> dict:
    out = {
        "deterring_total": 0,
        "patrolling_total": 0,
        "deterring_model_scored": 0,
        "deterring_direct_detection": 0,
    }
    for tr in tasks:
        ttype = str(tr.get("type", "")).strip().lower()
        if ttype == "deterring":
            out["deterring_total"] += 1
            src = _task_source(tr)
            if src == "model_scored":
                out["deterring_model_scored"] += 1
            else:
                out["deterring_direct_detection"] += 1
        elif ttype == "patrolling":
            out["patrolling_total"] += 1
    return out


def run_collect(sim_mode: str, params: dict, sample_every_s: float = 30.0):
    frames = ds.run_simulation_frames_persistent(simulation_mode=sim_mode, **params)
    rows = []
    pose_hist = {}
    last = None
    next_sample_t = -1e9
    for snap in frames:
        last = snap
        t = float(snap["t"])
        if t < next_sample_t:
            continue
        next_sample_t = t + float(sample_every_s)

        m = snap.get("metrics", {})
        model_diag = snap.get("model_diag", {})
        lam_means = [v.get("lam_mean", np.nan) for v in model_diag.values()]
        trig_sums = [v.get("trigger_sum", np.nan) for v in model_diag.values()]
        inhib_sums = [v.get("inhib_sum", np.nan) for v in model_diag.values()]

        active_c = _count_tasks(snap.get("tasks_active", []))
        done_c = _count_tasks(snap.get("tasks_done", []))

        for rid, (x, y) in snap.get("poses", {}).items():
            pose_hist.setdefault(rid, []).append((t, float(x), float(y)))

        rows.append(
            {
                "t": t,
                "value_weighted_exposure": float(m.get("value_weighted_exposure", np.nan)),
                "mean_response_time_s": float(m.get("mean_response_time_s", np.nan)),
                "tasks_per_unit_distance": float(m.get("tasks_per_unit_distance", np.nan)),
                "boundary_message_count": float(m.get("boundary_message_count", np.nan)),
                "forecast_recall_at_k": float(m.get("forecast_recall_at_k", np.nan)),
                "forecast_precision_at_k": float(m.get("forecast_precision_at_k", np.nan)),
                "forecast_lead_time_s": float(m.get("forecast_lead_time_s", np.nan)),
                "active_deterring": int(active_c["deterring_total"]),
                "active_patrolling": int(active_c["patrolling_total"]),
                "active_deterring_model_scored": int(active_c["deterring_model_scored"]),
                "active_deterring_direct_detection": int(active_c["deterring_direct_detection"]),
                "done_deterring": int(done_c["deterring_total"]),
                "done_patrolling": int(done_c["patrolling_total"]),
                "done_deterring_model_scored": int(done_c["deterring_model_scored"]),
                "done_deterring_direct_detection": int(done_c["deterring_direct_detection"]),
                "lam_mean_avg": float(np.nanmean(lam_means)) if lam_means else np.nan,
                "trigger_sum_total": float(np.nansum(trig_sums)) if trig_sums else np.nan,
                "inhib_sum_total": float(np.nansum(inhib_sums)) if inhib_sums else np.nan,
            }
        )
    return pd.DataFrame(rows), last, pose_hist


def _plot_side_by_side_map(pred_last, prop_last, pred_pose_hist, prop_pose_hist, out_png: Path):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharex=True, sharey=True)
    for ax, snap, pose_hist, title in [
        (axes[0], pred_last, pred_pose_hist, "Prediction-Only"),
        (axes[1], prop_last, prop_pose_hist, "Proposed"),
    ]:
        W, H = snap["W"], snap["H"]
        ax.set_title(title)
        ax.set_xlim(0, W)
        ax.set_ylim(0, H)
        ax.set_aspect("equal", adjustable="box")
        bx, by = zip(*(snap["boundary"] + [snap["boundary"][0]]))
        ax.plot(bx, by, "k-", lw=1.0)
        for cell in snap["cells"]:
            if not cell:
                continue
            xs = [p[0] for p in cell] + [cell[0][0]]
            ys = [p[1] for p in cell] + [cell[0][1]]
            ax.plot(xs, ys, "-", color="#999999", lw=0.7, alpha=0.8)
        # trajectories
        for rid, hist in pose_hist.items():
            if not hist:
                continue
            xs = [h[1] for h in hist]
            ys = [h[2] for h in hist]
            ax.plot(xs, ys, alpha=0.4, lw=0.8)
        # latest poses
        px = [p[0] for p in snap["poses"].values()]
        py = [p[1] for p in snap["poses"].values()]
        ax.scatter(px, py, c="black", s=20, label="robots")
        tp = snap.get("truth_pts", [])
        dp = snap.get("det_pts", [])
        if tp:
            ax.scatter([p[0] for p in tp], [p[1] for p in tp], c="#2ca02c", marker="x", s=36, label="truth")
        if dp:
            ax.scatter([p[0] for p in dp], [p[1] for p in dp], c="#d62728", marker="x", s=36, label="detections")
        a = snap.get("tasks_active", [])
        det = [tr for tr in a if str(tr.get("type", "")).lower() == "deterring"]
        pat = [tr for tr in a if str(tr.get("type", "")).lower() == "patrolling"]
        if det:
            ax.scatter([tr["x"] for tr in det], [tr["y"] for tr in det], c="#ff7f0e", s=32, label="deterring tasks")
        if pat:
            ax.scatter([tr["x"] for tr in pat], [tr["y"] for tr in pat], c="#1f77b4", marker="D", s=26, label="patrol tasks")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
    handles, labels = axes[1].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="upper center", ncol=5, fontsize=8)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _plot_timeseries(pred_df: pd.DataFrame, prop_df: pd.DataFrame, out_png: Path):
    fig, axes = plt.subplots(3, 2, figsize=(13, 10))
    pairs = [
        ("value_weighted_exposure", "Exposure (lower better)"),
        ("mean_response_time_s", "Mean Response Time (s)"),
        ("tasks_per_unit_distance", "Task Efficiency"),
        ("forecast_recall_at_k", "Forecast Recall@K"),
        ("forecast_precision_at_k", "Forecast Precision@K"),
        ("inhib_sum_total", "Total Inhibition Mass"),
    ]
    for ax, (col, ttl) in zip(axes.flat, pairs):
        if col in pred_df.columns:
            ax.plot(pred_df["t"], pred_df[col], label="prediction_only", lw=1.4)
        if col in prop_df.columns:
            ax.plot(prop_df["t"], prop_df[col], label="proposed", lw=1.4)
        ax.set_title(ttl)
        ax.grid(alpha=0.25)
    axes[0, 0].legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _plot_task_flow(pred_df: pd.DataFrame, prop_df: pd.DataFrame, out_png: Path):
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), sharex=True)
    plots = [
        ("active_deterring", "Active Deterring Tasks"),
        ("active_patrolling", "Active Patrol Tasks"),
        ("done_deterring_model_scored", "Completed Model-Scored Deterring"),
        ("done_deterring_direct_detection", "Completed Direct-Detection Deterring"),
    ]
    for ax, (col, ttl) in zip(axes.flat, plots):
        ax.plot(pred_df["t"], pred_df[col], label="prediction_only")
        ax.plot(prop_df["t"], prop_df[col], label="proposed")
        ax.set_title(ttl)
        ax.grid(alpha=0.25)
    axes[0, 0].legend(loc="best", fontsize=8)
    for ax in axes[1]:
        ax.set_xlabel("time (s)")
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _critical_recommendations(pred_last: dict, prop_last: dict) -> list[str]:
    rec = []
    p = pred_last.get("metrics", {})
    q = prop_last.get("metrics", {})
    # Critical gap checks.
    if np.isfinite(p.get("forecast_recall_at_k", np.nan)) and np.isfinite(q.get("forecast_recall_at_k", np.nan)):
        if q["forecast_recall_at_k"] <= p["forecast_recall_at_k"] + 1e-6:
            rec.append("Proposed forecast recall is not better: increase intervention impact (beta_true/mode beta) or reduce replan interval.")
    if np.isfinite(p.get("value_weighted_exposure", np.nan)) and np.isfinite(q.get("value_weighted_exposure", np.nan)):
        if q["value_weighted_exposure"] >= p["value_weighted_exposure"]:
            rec.append("Proposed exposure is not lower: verify model-scored deterrence generation and alignment of sigma_true with intervention footprint.")
    if np.isfinite(q.get("boundary_message_count", np.nan)) and np.isfinite(p.get("boundary_message_count", np.nan)):
        if q["boundary_message_count"] > 1.5 * max(p["boundary_message_count"], 1.0):
            rec.append("Proposed communication is much higher: tighten boundary broadcast conditions or raise deterrence task admission threshold.")
    if not rec:
        rec.append("Proposed shows expected advantage; next step is confidence intervals on held-out seeds/scenarios.")
    return rec


def main():
    parser = argparse.ArgumentParser(description="Subsystem diagnostics: proposed vs prediction-only")
    parser.add_argument("--T-end", type=float, default=3 * 3600.0, help="diagnostic horizon (s)")
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--sample-every-s", type=float, default=30.0)
    parser.add_argument("--outdir", type=str, default="results/diagnostic_compare")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # Headless diagnostics.
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
        "task_replan_period_s": 45.0,
        "model_deterring_window_s": 90.0,
        "model_deterring_risk_threshold": 0.35,
        "model_deterring_budget_per_robot_per_hr": 4,
        "model_deterring_min_recent_points": 1,
        "forecast_horizon_s": 300.0,
        "forecast_match_radius_m": 20.0,
        "forecast_top_k": 5,
        "forecast_eval_period_s": 30.0,
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
    }

    pred_df, pred_last, pred_pose = run_collect("prediction_only", run_params, sample_every_s=float(args.sample_every_s))
    prop_df, prop_last, prop_pose = run_collect("proposed", run_params, sample_every_s=float(args.sample_every_s))

    pred_df.to_csv(outdir / "diagnostic_timeseries_prediction_only.csv", index=False)
    prop_df.to_csv(outdir / "diagnostic_timeseries_proposed.csv", index=False)

    _plot_side_by_side_map(pred_last, prop_last, pred_pose, prop_pose, outdir / "map_side_by_side.png")
    _plot_timeseries(pred_df, prop_df, outdir / "timeseries_subsystems.png")
    _plot_task_flow(pred_df, prop_df, outdir / "task_flow_compare.png")

    recommendations = _critical_recommendations(pred_last, prop_last)
    report = {
        "parameters": run_params,
        "prediction_only_final_metrics": pred_last.get("metrics", {}),
        "proposed_final_metrics": prop_last.get("metrics", {}),
        "critical_recommendations": recommendations,
    }
    with open(outdir / "diagnostic_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    with open(outdir / "diagnostic_report.md", "w", encoding="utf-8") as f:
        f.write("# Proposed vs Prediction-Only Diagnostic Report\n\n")
        f.write("## Parameters Used\n\n")
        for k, v in run_params.items():
            f.write(f"- `{k}`: `{v}`\n")
        f.write("\n## Critical Recommendations\n\n")
        for r in recommendations:
            f.write(f"- {r}\n")

    print(f"[done] diagnostics saved to: {outdir}")


if __name__ == "__main__":
    main()
