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


def _safe_median(vals) -> float:
    arr = [float(v) for v in vals if np.isfinite(float(v))]
    return float(np.median(arr)) if arr else float("nan")


def _is_replan_frame(t_s: float, period_s: float, dt: float) -> bool:
    if period_s <= 0.0:
        return False
    rem = float(t_s) % float(period_s)
    tol = max(float(dt) * 0.51, 1e-6)
    return rem <= tol or abs(rem - float(period_s)) <= tol


def _collect_run(
    label: str,
    sim_mode: str,
    run_params: dict,
    overrides: dict,
) -> list[dict]:
    return list(
        ds.run_simulation_frames_persistent(
            simulation_mode=sim_mode,
            report_metrics_end=False,
            emit_planning_diagnostics=True,
            **run_params,
            **overrides,
        )
    )


def _active_task_maps(snap: dict) -> tuple[dict[str, str], dict[str, str]]:
    patrol_by_robot = {}
    nonpatrol_by_robot = {}
    for tr in snap.get("tasks_active", []):
        if str(tr.get("state", "")).strip().lower() != "active":
            continue
        rid = str(tr.get("assigned_primary", ""))
        if not rid:
            continue
        ttype = str(tr.get("type", "")).strip().lower()
        if ttype == "patrolling":
            patrol_by_robot[rid] = str(tr.get("id"))
        else:
            nonpatrol_by_robot[rid] = str(tr.get("id"))
    return patrol_by_robot, nonpatrol_by_robot


def _new_done_patrol_ids(prev_done_ids: set[str], snap: dict) -> tuple[set[str], dict[str, float]]:
    current = set()
    done_t = {}
    for tr in snap.get("tasks_done", []):
        if str(tr.get("state", "")).strip().lower() != "done":
            continue
        if str(tr.get("type", "")).strip().lower() != "patrolling":
            continue
        tid = str(tr.get("id"))
        current.add(tid)
        try:
            done_t[tid] = float(tr.get("t_done", snap.get("t", 0.0)))
        except Exception:
            done_t[tid] = float(snap.get("t", 0.0))
    return current - prev_done_ids, done_t


def _ensure_task(hist: dict, tid: str, rid: str | None = None) -> dict:
    if tid not in hist:
        hist[tid] = {
            "task_id": str(tid),
            "assigned_primary": (None if rid is None else str(rid)),
            "accepted_t": float("nan"),
            "first_active_t": float("nan"),
            "last_active_t": float("nan"),
            "end_t": float("nan"),
            "end_reason": "",
            "active_frame_count": 0,
            "replan_presence_count": 0,
            "accepted_score": float("nan"),
            "accepted_x": float("nan"),
            "accepted_y": float("nan"),
        }
    if rid is not None and not hist[tid].get("assigned_primary"):
        hist[tid]["assigned_primary"] = str(rid)
    return hist[tid]


def _finalize_mode(
    run_idx: int,
    seed: int,
    mode_label: str,
    frames: list[dict],
    task_replan_period_s: float,
    dt: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    task_hist = {}
    accepted_ids = set()
    prev_patrol_by_robot = {}
    prev_done_ids = set()
    prev_replan_patrol_by_robot = None
    replan_rows = []

    for snap in frames:
        t_s = float(snap.get("t", 0.0))
        planning = snap.get("planning_diagnostics") or {}
        accepted_patrol = planning.get("accepted_patrol_tasks", []) or []
        current_done_new, done_t_map = _new_done_patrol_ids(prev_done_ids, snap)
        current_done_ids = prev_done_ids | current_done_new
        patrol_by_robot, nonpatrol_by_robot = _active_task_maps(snap)

        for row in accepted_patrol:
            tid = str(row.get("id"))
            rid = str(row.get("assigned_primary", ""))
            tr = _ensure_task(task_hist, tid, rid)
            accepted_ids.add(tid)
            if not np.isfinite(float(tr["accepted_t"])):
                tr["accepted_t"] = float(t_s)
            tr["accepted_score"] = float(row.get("score", float("nan")))
            tr["accepted_x"] = float(row.get("x", float("nan")))
            tr["accepted_y"] = float(row.get("y", float("nan")))

        for rid, tid in patrol_by_robot.items():
            tr = _ensure_task(task_hist, str(tid), str(rid))
            if not np.isfinite(float(tr["first_active_t"])):
                tr["first_active_t"] = float(t_s)
            tr["last_active_t"] = float(t_s)
            tr["active_frame_count"] = int(tr["active_frame_count"]) + 1
            if not np.isfinite(float(tr["accepted_t"])):
                tr["accepted_t"] = float(t_s)

        for rid, prev_tid in prev_patrol_by_robot.items():
            curr_tid = patrol_by_robot.get(rid)
            if curr_tid == prev_tid:
                continue
            tr = _ensure_task(task_hist, str(prev_tid), str(rid))
            if tr.get("end_reason"):
                continue
            if str(prev_tid) in current_done_ids:
                tr["end_t"] = float(done_t_map.get(str(prev_tid), t_s))
                tr["end_reason"] = "completed"
            elif curr_tid:
                tr["end_t"] = float(t_s)
                tr["end_reason"] = "replaced_by_patrol"
            elif rid in nonpatrol_by_robot:
                tr["end_t"] = float(t_s)
                tr["end_reason"] = "preempted_for_nonpatrol"
            else:
                tr["end_t"] = float(t_s)
                tr["end_reason"] = "dropped_no_replacement"

        if _is_replan_frame(t_s, task_replan_period_s, dt):
            for tid in patrol_by_robot.values():
                _ensure_task(task_hist, str(tid))["replan_presence_count"] = (
                    int(_ensure_task(task_hist, str(tid))["replan_presence_count"]) + 1
                )

            curr_active_count = int(len(patrol_by_robot))
            curr_ids = set(patrol_by_robot.values())
            if prev_replan_patrol_by_robot is not None:
                prev_active_count = int(len(prev_replan_patrol_by_robot))
                carry_count = int(
                    sum(
                        1
                        for rid, prev_tid in prev_replan_patrol_by_robot.items()
                        if patrol_by_robot.get(rid) == prev_tid
                    )
                )
                same_robot_replacements = int(
                    sum(
                        1
                        for rid, prev_tid in prev_replan_patrol_by_robot.items()
                        if patrol_by_robot.get(rid) is not None and patrol_by_robot.get(rid) != prev_tid
                    )
                )
                nonpatrol_preemptions = int(
                    sum(
                        1
                        for rid, prev_tid in prev_replan_patrol_by_robot.items()
                        if patrol_by_robot.get(rid) is None and rid in nonpatrol_by_robot
                    )
                )
                removed_count = int(
                    sum(1 for rid in prev_replan_patrol_by_robot if patrol_by_robot.get(rid) is None)
                )
                replan_rows.append(
                    {
                        "run_idx": int(run_idx),
                        "seed": int(seed),
                        "mode": mode_label,
                        "t_s": float(t_s),
                        "prev_active_patrol_count": int(prev_active_count),
                        "active_patrol_count": int(curr_active_count),
                        "carryover_count": int(carry_count),
                        "carryover_fraction": float(carry_count) / float(max(prev_active_count, 1)),
                        "turnover_fraction": float(max(prev_active_count - carry_count, 0)) / float(max(prev_active_count, 1)),
                        "same_robot_replacements": int(same_robot_replacements),
                        "nonpatrol_preemptions": int(nonpatrol_preemptions),
                        "removed_fraction": float(removed_count) / float(max(prev_active_count, 1)),
                        "set_jaccard": float(len(set(prev_replan_patrol_by_robot.values()) & curr_ids))
                        / float(max(len(set(prev_replan_patrol_by_robot.values()) | curr_ids), 1)),
                    }
                )
            prev_replan_patrol_by_robot = dict(patrol_by_robot)

        prev_patrol_by_robot = dict(patrol_by_robot)
        prev_done_ids = current_done_ids

    final_t = float(frames[-1].get("t", 0.0)) if frames else 0.0
    active_last, _nonpatrol_last = _active_task_maps(frames[-1] if frames else {})
    for tid, tr in task_hist.items():
        if tr.get("end_reason"):
            continue
        if tid in prev_done_ids:
            tr["end_t"] = float(final_t)
            tr["end_reason"] = "completed"
        elif tid in set(active_last.values()):
            tr["end_t"] = float(final_t)
            tr["end_reason"] = "still_active"
        else:
            tr["end_t"] = float(tr.get("last_active_t", final_t))
            tr["end_reason"] = "dropped_unobserved"

    task_rows = []
    for tid, tr in task_hist.items():
        accepted_t = float(tr.get("accepted_t", float("nan")))
        first_active_t = float(tr.get("first_active_t", float("nan")))
        start_t = accepted_t if np.isfinite(accepted_t) else first_active_t
        end_t = float(tr.get("end_t", float("nan")))
        lifetime_s = float(end_t - start_t) if (np.isfinite(start_t) and np.isfinite(end_t)) else float("nan")
        task_rows.append(
            {
                "run_idx": int(run_idx),
                "seed": int(seed),
                "mode": mode_label,
                "task_id": tid,
                "assigned_primary": tr.get("assigned_primary"),
                "accepted_t": accepted_t,
                "first_active_t": first_active_t,
                "last_active_t": float(tr.get("last_active_t", float("nan"))),
                "end_t": end_t,
                "lifetime_s": lifetime_s,
                "active_frame_count": int(tr.get("active_frame_count", 0)),
                "replan_presence_count": int(tr.get("replan_presence_count", 0)),
                "accepted_score": float(tr.get("accepted_score", float("nan"))),
                "accepted_x": float(tr.get("accepted_x", float("nan"))),
                "accepted_y": float(tr.get("accepted_y", float("nan"))),
                "end_reason": str(tr.get("end_reason", "")),
                "was_accepted": bool(tid in accepted_ids),
                "completed": bool(str(tr.get("end_reason", "")) == "completed"),
            }
        )

    task_df = pd.DataFrame(task_rows).sort_values(["seed", "mode", "accepted_t", "task_id"]).reset_index(drop=True)
    replan_df = pd.DataFrame(replan_rows).sort_values(["seed", "mode", "t_s"]).reset_index(drop=True)

    summary = {
        "run_idx": int(run_idx),
        "seed": int(seed),
        "mode": mode_label,
        "accepted_patrol_total": int(sum(bool(v) for v in task_df["was_accepted"])) if not task_df.empty else 0,
        "completed_patrol_total": int(sum(bool(v) for v in task_df["completed"])) if not task_df.empty else 0,
        "replaced_by_patrol_total": int((task_df["end_reason"] == "replaced_by_patrol").sum()) if not task_df.empty else 0,
        "preempted_for_nonpatrol_total": int((task_df["end_reason"] == "preempted_for_nonpatrol").sum()) if not task_df.empty else 0,
        "dropped_total": int(
            task_df["end_reason"].isin(["dropped_no_replacement", "dropped_unobserved"]).sum()
        )
        if not task_df.empty
        else 0,
        "still_active_total": int((task_df["end_reason"] == "still_active").sum()) if not task_df.empty else 0,
        "mean_patrol_lifetime_s": _safe_mean(task_df["lifetime_s"].tolist()) if not task_df.empty else float("nan"),
        "median_patrol_lifetime_s": _safe_median(task_df["lifetime_s"].tolist()) if not task_df.empty else float("nan"),
        "mean_replan_presence_count": _safe_mean(task_df["replan_presence_count"].tolist()) if not task_df.empty else float("nan"),
        "median_replan_presence_count": _safe_median(task_df["replan_presence_count"].tolist()) if not task_df.empty else float("nan"),
        "carryover_fraction_mean": _safe_mean(replan_df["carryover_fraction"].tolist()) if not replan_df.empty else float("nan"),
        "turnover_fraction_mean": _safe_mean(replan_df["turnover_fraction"].tolist()) if not replan_df.empty else float("nan"),
        "same_robot_replacements_per_replan": _safe_mean(replan_df["same_robot_replacements"].tolist()) if not replan_df.empty else float("nan"),
        "nonpatrol_preemptions_per_replan": _safe_mean(replan_df["nonpatrol_preemptions"].tolist()) if not replan_df.empty else float("nan"),
        "jaccard_mean": _safe_mean(replan_df["set_jaccard"].tolist()) if not replan_df.empty else float("nan"),
        "prediction_final_exposure": float("nan"),
        "prediction_final_response_s": float("nan"),
    }
    accepted_total = max(int(summary["accepted_patrol_total"]), 1)
    summary["completed_fraction"] = float(summary["completed_patrol_total"]) / float(accepted_total)
    summary["replaced_fraction"] = float(summary["replaced_by_patrol_total"]) / float(accepted_total)
    summary["preempted_fraction"] = float(summary["preempted_for_nonpatrol_total"]) / float(accepted_total)
    summary["dropped_fraction"] = float(summary["dropped_total"]) / float(accepted_total)
    return task_df, replan_df, summary


def _plot_summary(per_run_df: pd.DataFrame, out_png: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))
    metrics = [
        ("carryover_fraction_mean", "Carryover"),
        ("mean_patrol_lifetime_s", "Lifetime (s)"),
        ("same_robot_replacements_per_replan", "Replacements / replan"),
    ]
    modes = sorted(per_run_df["mode"].unique())
    for ax, (col, title) in zip(axes, metrics):
        for mode in modes:
            sub = per_run_df[per_run_df["mode"] == mode]
            ax.scatter(np.full(len(sub), modes.index(mode)), sub[col], label=mode if col == metrics[0][0] else None, alpha=0.85)
        ax.set_xticks(range(len(modes)))
        ax.set_xticklabels(modes, rotation=15)
        ax.set_title(title)
        ax.grid(alpha=0.25)
    axes[0].legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare patrol carry-over, turnover, and replacement stability between prediction_only and feedback-only proposed runs."
    )
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--seed-start", type=int, default=2026)
    parser.add_argument("--T-end", type=float, default=3 * 3600.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--warmup-s", type=float, default=1800.0)
    parser.add_argument("--task-replan-period-s", type=float, default=60.0)
    parser.add_argument("--patrol-hotspot-filter-mode", type=str, default="percentile")
    parser.add_argument("--patrol-hotspot-score-percentile", type=float, default=97.0)
    parser.add_argument("--alpha-inhib", type=float, default=0.45)
    parser.add_argument("--omega-inhib", type=float, default=600.0)
    parser.add_argument("--mu-base", type=float, default=5.0e-5)
    parser.add_argument("--bg-ema", type=float, default=1.0e-6)
    parser.add_argument("--outdir", type=str, default="results/diagnostic_feedback_patrol_stability")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    run_params = {
        "T_end": float(args.T_end),
        "dt": float(args.dt),
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
        "mu_base": float(args.mu_base),
        "bg_ema": float(args.bg_ema),
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
    }

    all_task_rows = []
    all_replan_rows = []
    summary_rows = []

    for run_idx in range(int(args.runs)):
        seed = int(args.seed_start) + run_idx
        pred_frames = _collect_run(
            "prediction_only",
            "prediction_only",
            run_params | {"seed": int(seed)},
            {"enable_intervention_feedback": False, "enable_model_scored_deterring": False},
        )
        prop_frames = _collect_run(
            "proposed_feedback_only",
            "proposed",
            run_params | {"seed": int(seed)},
            {"enable_intervention_feedback": True, "enable_model_scored_deterring": False},
        )

        for mode_label, frames in [
            ("prediction_only", pred_frames),
            ("proposed_feedback_only", prop_frames),
        ]:
            task_df, replan_df, summary = _finalize_mode(
                run_idx=run_idx,
                seed=seed,
                mode_label=mode_label,
                frames=frames,
                task_replan_period_s=float(args.task_replan_period_s),
                dt=float(args.dt),
            )
            final_metrics = dict((frames[-1] if frames else {}).get("metrics", {}))
            summary["final_exposure"] = float(final_metrics.get("value_weighted_exposure", float("nan")))
            summary["final_response_s"] = float(final_metrics.get("mean_response_time_s", float("nan")))
            all_task_rows.append(task_df)
            all_replan_rows.append(replan_df)
            summary_rows.append(summary)

        print(f"[run {run_idx + 1}/{int(args.runs)}] seed={seed} patrol stability collected")

    task_all_df = pd.concat(all_task_rows, ignore_index=True) if all_task_rows else pd.DataFrame()
    replan_all_df = pd.concat(all_replan_rows, ignore_index=True) if all_replan_rows else pd.DataFrame()
    per_run_df = pd.DataFrame(summary_rows).sort_values(["seed", "mode"]).reset_index(drop=True)

    task_all_df.to_csv(outdir / "feedback_patrol_stability_tasks.csv", index=False)
    replan_all_df.to_csv(outdir / "feedback_patrol_stability_per_replan.csv", index=False)
    per_run_df.to_csv(outdir / "feedback_patrol_stability_per_run.csv", index=False)

    pred = per_run_df[per_run_df["mode"] == "prediction_only"].copy()
    prop = per_run_df[per_run_df["mode"] == "proposed_feedback_only"].copy()
    paired = pred.merge(prop, on="seed", suffixes=("_pred", "_prop"))
    paired_rows = []
    for _, row in paired.iterrows():
        paired_rows.append(
            {
                "seed": int(row["seed"]),
                "delta_carryover_fraction_mean_prop_minus_pred": float(row["carryover_fraction_mean_prop"] - row["carryover_fraction_mean_pred"]),
                "delta_turnover_fraction_mean_prop_minus_pred": float(row["turnover_fraction_mean_prop"] - row["turnover_fraction_mean_pred"]),
                "delta_mean_patrol_lifetime_s_prop_minus_pred": float(row["mean_patrol_lifetime_s_prop"] - row["mean_patrol_lifetime_s_pred"]),
                "delta_same_robot_replacements_per_replan_prop_minus_pred": float(
                    row["same_robot_replacements_per_replan_prop"] - row["same_robot_replacements_per_replan_pred"]
                ),
                "delta_nonpatrol_preemptions_per_replan_prop_minus_pred": float(
                    row["nonpatrol_preemptions_per_replan_prop"] - row["nonpatrol_preemptions_per_replan_pred"]
                ),
                "delta_completed_fraction_prop_minus_pred": float(row["completed_fraction_prop"] - row["completed_fraction_pred"]),
                "delta_dropped_fraction_prop_minus_pred": float(row["dropped_fraction_prop"] - row["dropped_fraction_pred"]),
                "delta_final_exposure_prop_minus_pred": float(row["final_exposure_prop"] - row["final_exposure_pred"]),
                "delta_final_response_s_prop_minus_pred": float(row["final_response_s_prop"] - row["final_response_s_pred"]),
            }
        )
    paired_df = pd.DataFrame(paired_rows).sort_values("seed").reset_index(drop=True)
    paired_df.to_csv(outdir / "feedback_patrol_stability_paired.csv", index=False)

    mode_summary = {}
    for mode in sorted(per_run_df["mode"].unique()):
        sub = per_run_df[per_run_df["mode"] == mode]
        mode_summary[mode] = {
            "carryover_fraction_mean": _safe_mean(sub["carryover_fraction_mean"].tolist()),
            "turnover_fraction_mean": _safe_mean(sub["turnover_fraction_mean"].tolist()),
            "same_robot_replacements_per_replan_mean": _safe_mean(sub["same_robot_replacements_per_replan"].tolist()),
            "nonpatrol_preemptions_per_replan_mean": _safe_mean(sub["nonpatrol_preemptions_per_replan"].tolist()),
            "mean_patrol_lifetime_s": _safe_mean(sub["mean_patrol_lifetime_s"].tolist()),
            "mean_replan_presence_count": _safe_mean(sub["mean_replan_presence_count"].tolist()),
            "completed_fraction_mean": _safe_mean(sub["completed_fraction"].tolist()),
            "replaced_fraction_mean": _safe_mean(sub["replaced_fraction"].tolist()),
            "preempted_fraction_mean": _safe_mean(sub["preempted_fraction"].tolist()),
            "dropped_fraction_mean": _safe_mean(sub["dropped_fraction"].tolist()),
            "final_exposure_mean": _safe_mean(sub["final_exposure"].tolist()),
            "final_response_s_mean": _safe_mean(sub["final_response_s"].tolist()),
        }

    summary = {
        "parameters": {
            "runs": int(args.runs),
            "seed_start": int(args.seed_start),
            "T_end": float(args.T_end),
            "dt": float(args.dt),
            "warmup_s": float(args.warmup_s),
            "task_replan_period_s": float(args.task_replan_period_s),
            "patrol_hotspot_filter_mode": str(args.patrol_hotspot_filter_mode),
            "patrol_hotspot_score_percentile": float(args.patrol_hotspot_score_percentile),
            "alpha_inhib": float(args.alpha_inhib),
            "omega_inhib": float(args.omega_inhib),
            "mu_base": float(args.mu_base),
            "bg_ema": float(args.bg_ema),
        },
        "mode_summary": mode_summary,
        "paired_delta_summary": {
            col: _safe_mean(paired_df[col].tolist()) for col in paired_df.columns if col != "seed"
        },
    }

    conclusions = []
    paired_summary = summary["paired_delta_summary"]
    if np.isfinite(paired_summary.get("delta_carryover_fraction_mean_prop_minus_pred", float("nan"))):
        if paired_summary["delta_carryover_fraction_mean_prop_minus_pred"] < 0.0:
            conclusions.append("Feedback reduces patrol carry-over across replans on average.")
        else:
            conclusions.append("Feedback does not reduce patrol carry-over on average.")
    if np.isfinite(paired_summary.get("delta_same_robot_replacements_per_replan_prop_minus_pred", float("nan"))):
        if paired_summary["delta_same_robot_replacements_per_replan_prop_minus_pred"] > 0.0:
            conclusions.append("Feedback increases same-robot patrol replacements per replan.")
        else:
            conclusions.append("Feedback does not increase same-robot patrol replacements per replan.")
    if np.isfinite(paired_summary.get("delta_mean_patrol_lifetime_s_prop_minus_pred", float("nan"))):
        if paired_summary["delta_mean_patrol_lifetime_s_prop_minus_pred"] < 0.0:
            conclusions.append("Feedback shortens patrol-task lifetime on average.")
        else:
            conclusions.append("Feedback does not shorten patrol-task lifetime on average.")
    summary["conclusions"] = conclusions

    with open(outdir / "feedback_patrol_stability_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with open(outdir / "feedback_patrol_stability_report.md", "w", encoding="utf-8") as f:
        f.write("# Feedback Patrol Stability Diagnostic\n\n")
        f.write("## Parameters\n\n")
        for k, v in summary["parameters"].items():
            f.write(f"- `{k}`: `{v}`\n")
        f.write("\n## Mode Summary\n\n")
        for mode, vals in mode_summary.items():
            f.write(f"### {mode}\n\n")
            for k, v in vals.items():
                f.write(f"- `{k}`: `{v}`\n")
        f.write("\n## Paired Delta Summary\n\n")
        for k, v in summary["paired_delta_summary"].items():
            f.write(f"- `{k}`: `{v}`\n")
        f.write("\n## Conclusions\n\n")
        for line in conclusions:
            f.write(f"- {line}\n")

    _plot_summary(per_run_df, outdir / "feedback_patrol_stability_summary.png")
    print(f"[done] patrol stability diagnostic saved to: {outdir}")


if __name__ == "__main__":
    main()
