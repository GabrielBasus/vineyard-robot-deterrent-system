from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, Iterable

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
    _safe_mean,
    _task_group,
)


def _robot_command_for_frame(snap: dict, robot_id: str) -> dict | None:
    for cmd in snap.get("motion_commands", []):
        if str(cmd.get("robot_id", "")) == str(robot_id):
            return cmd
    return None


def _active_task_for_frame(snap: dict, task_id: int) -> dict | None:
    for task in snap.get("tasks_active", []):
        if int(task.get("id", -1)) == int(task_id):
            return task
    return None


def _replacement_context(snap: dict, robot_id: str, dropped_task_id: int) -> dict:
    cmd = _robot_command_for_frame(snap, robot_id)
    active_other = None
    for task in snap.get("tasks_active", []):
        if str(task.get("assigned_primary", "")) != str(robot_id):
            continue
        if int(task.get("id", -1)) == int(dropped_task_id):
            continue
        if str(task.get("state", "")).strip().lower() != "active":
            continue
        active_other = task
        break
    replacement_group = "none"
    replacement_task_id = np.nan
    replacement_task_type = ""
    replacement_task_mode = ""
    if active_other is not None:
        replacement_group = _task_group(active_other)
        replacement_task_id = int(active_other.get("id", -1))
        replacement_task_type = str(active_other.get("type", ""))
        replacement_task_mode = "" if active_other.get("mode") in (None, "", "none") else str(active_other.get("mode"))
    elif cmd is not None and cmd.get("assigned_task_id") not in (None, dropped_task_id):
        replacement_task_id = int(cmd.get("assigned_task_id"))
        replacement_task_type = str(cmd.get("assigned_task_type") or "")
        replacement_task_mode = str(cmd.get("assigned_task_mode") or "")
        temp_task = {
            "type": replacement_task_type,
            "mode": (None if replacement_task_mode == "" else replacement_task_mode),
            "origin": "",
        }
        replacement_group = _task_group(temp_task)
    return {
        "replacement_group": str(replacement_group),
        "replacement_task_id": replacement_task_id,
        "replacement_task_type": replacement_task_type,
        "replacement_task_mode": replacement_task_mode,
        "replacement_command_source": "" if cmd is None else str(cmd.get("source", "")),
    }


def _classify_lifecycle(row: pd.Series, arrival_radius_m: float) -> str:
    status = str(row.get("status", ""))
    replacement_group = str(row.get("replacement_group", "none"))
    command_match_fraction = float(row.get("command_match_fraction", 0.0))
    min_distance_m = float(row.get("min_distance_m", float("nan")))

    if status == "completed":
        return "completed"
    if status == "still_active":
        if np.isfinite(min_distance_m) and min_distance_m <= float(arrival_radius_m):
            return "still_active_near_goal"
        if command_match_fraction <= 0.05:
            return "still_active_never_commanded"
        return "still_active_in_progress"

    if replacement_group == "direct_detection_deterring":
        return "dropped_for_direct_detection"
    if replacement_group == "patrolling":
        return "dropped_for_patrol"
    if replacement_group == "model_scored_deterring":
        return "dropped_for_model_scored"
    if command_match_fraction <= 0.05:
        return "dropped_without_command"
    if np.isfinite(min_distance_m) and min_distance_m <= float(arrival_radius_m):
        return "dropped_near_goal"
    return "dropped_in_transit"


def _summarize(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "count": 0,
            "future_truth_hit_rate": float("nan"),
            "future_truth_count_mean": float("nan"),
            "recent_truth_count_mean": float("nan"),
            "p_event_mean": float("nan"),
            "deltaJ_per_cost_mean": float("nan"),
            "command_match_fraction_mean": float("nan"),
            "min_distance_mean_m": float("nan"),
            "time_in_system_mean_s": float("nan"),
        }
    return {
        "count": int(len(df)),
        "future_truth_hit_rate": float(df["future_truth_hit"].mean()),
        "future_truth_count_mean": float(df["future_truth_count"].mean()),
        "recent_truth_count_mean": float(df["recent_truth_count"].mean()),
        "p_event_mean": _safe_mean(df["p_event"]),
        "deltaJ_per_cost_mean": _safe_mean(df["deltaJ_per_cost"]),
        "command_match_fraction_mean": _safe_mean(df["command_match_fraction"]),
        "min_distance_mean_m": _safe_mean(df["min_distance_m"]),
        "time_in_system_mean_s": _safe_mean(df["time_in_system_s"]),
    }


def _reason_counts(df: pd.DataFrame) -> dict[str, int]:
    if df.empty:
        return {}
    vc = df["lifecycle_reason"].value_counts(dropna=False)
    return {str(idx): int(val) for idx, val in vc.items()}


def _build_recommendations(summary: dict) -> list[str]:
    out: list[str] = []
    incomplete = summary.get("incomplete_model_scored", {})
    completed = summary.get("completed_model_scored", {})
    reason_counts = summary.get("incomplete_reason_counts", {})

    incomplete_count = int(incomplete.get("count", 0))
    if incomplete_count == 0:
        out.append("All accepted model-scored preventive tasks completed in this run; the completion bottleneck did not reproduce here.")
        return out

    if reason_counts.get("dropped_without_command", 0) > 0 or reason_counts.get("still_active_never_commanded", 0) > 0:
        out.append("Some accepted preventive tasks are not being actively commanded; dispatch/goal churn is still displacing work after admission.")
    if reason_counts.get("dropped_for_direct_detection", 0) > 0:
        out.append("Direct-detection work is taking over accepted preventive tasks; this is probably correct in emergencies but it explains part of the completion loss.")
    if reason_counts.get("dropped_for_patrol", 0) > 0:
        out.append("Accepted preventive tasks are still being replaced by patrol work; patrol replacement is too aggressive for admitted preventive tasks.")
    if reason_counts.get("dropped_in_transit", 0) > 0:
        out.append("Several accepted preventive tasks are dropped before the robot gets close; ETA/travel assumptions or task persistence need tightening.")
    if reason_counts.get("dropped_near_goal", 0) > 0 or reason_counts.get("still_active_near_goal", 0) > 0:
        out.append("Some preventive tasks reach the target area but still do not finish cleanly; hold/completion logic or task aging needs review.")

    incomplete_hit = float(incomplete.get("future_truth_hit_rate", float("nan")))
    completed_hit = float(completed.get("future_truth_hit_rate", float("nan")))
    if np.isfinite(incomplete_hit) and incomplete_hit >= 0.6:
        out.append("Incomplete preventive tasks still have strong future-truth support; the remaining loss is execution/persistence, not candidate quality.")
    if np.isfinite(completed_hit) and np.isfinite(incomplete_hit) and incomplete_hit > completed_hit + 0.05:
        out.append("Incomplete preventive tasks look stronger than completed ones on future-truth hit rate; completion is selecting against good work.")

    if not out:
        out.append("Incomplete preventive tasks are not obviously higher-value than completed ones; the current admission policy may already be near its useful limit.")
    return out


def _plot_drop_reasons(df: pd.DataFrame, out_png: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    if df.empty:
        for ax in axes:
            ax.text(0.5, 0.5, "No incomplete model-scored tasks", ha="center", va="center")
            ax.set_axis_off()
    else:
        grouped = df.groupby("lifecycle_reason")
        labels = list(grouped.groups.keys())
        counts = [int(len(grouped.get_group(k))) for k in labels]
        hit_rates = [float(grouped.get_group(k)["future_truth_hit"].mean()) for k in labels]
        axes[0].bar(labels, counts, color="#1f77b4")
        axes[0].set_title("Incomplete Preventive Tasks by Lifecycle Reason")
        axes[0].tick_params(axis="x", rotation=30)
        axes[0].grid(alpha=0.25)
        axes[1].bar(labels, hit_rates, color="#ff7f0e")
        axes[1].set_title("Future-Truth Hit Rate by Lifecycle Reason")
        axes[1].tick_params(axis="x", rotation=30)
        axes[1].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _plot_execution_scatter(completed_df: pd.DataFrame, incomplete_df: pd.DataFrame, out_png: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    if completed_df.empty and incomplete_df.empty:
        for ax in axes:
            ax.text(0.5, 0.5, "No accepted model-scored tasks", ha="center", va="center")
            ax.set_axis_off()
    else:
        if not completed_df.empty:
            axes[0].scatter(
                completed_df["command_match_fraction"],
                completed_df["min_distance_m"],
                c="#2ca02c",
                alpha=0.8,
                label="completed",
            )
        if not incomplete_df.empty:
            axes[0].scatter(
                incomplete_df["command_match_fraction"],
                incomplete_df["min_distance_m"],
                c="#d62728",
                alpha=0.8,
                label="incomplete",
            )
        axes[0].set_title("Execution Quality: Command Match vs Min Distance")
        axes[0].set_xlabel("command-match fraction")
        axes[0].set_ylabel("min distance to task (m)")
        axes[0].grid(alpha=0.25)
        axes[0].legend(loc="best", fontsize=8)

        if not completed_df.empty:
            axes[1].scatter(
                completed_df["deltaJ_per_cost"],
                completed_df["time_in_system_s"],
                c="#2ca02c",
                alpha=0.8,
                label="completed",
            )
        if not incomplete_df.empty:
            axes[1].scatter(
                incomplete_df["deltaJ_per_cost"],
                incomplete_df["time_in_system_s"],
                c="#d62728",
                alpha=0.8,
                label="incomplete",
            )
        axes[1].set_title("Value Signal vs Time in System")
        axes[1].set_xlabel("deltaJ_per_cost")
        axes[1].set_ylabel("time in system (s)")
        axes[1].grid(alpha=0.25)
        axes[1].legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _plot_step_timeseries(step_df: pd.DataFrame, out_png: Path) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    if step_df.empty:
        for ax in axes:
            ax.text(0.5, 0.5, "No step data", ha="center", va="center")
            ax.set_axis_off()
    else:
        axes[0].plot(step_df["t"], step_df["active_model_scored_deterring"], label="active model-scored", lw=1.4)
        axes[0].plot(step_df["t"], step_df["new_model_scored_accepted"], label="new accepted", lw=1.2)
        axes[0].plot(step_df["t"], step_df["new_model_scored_completed"], label="new completed", lw=1.2)
        axes[0].plot(step_df["t"], step_df["new_model_scored_dropped"], label="new dropped", lw=1.2)
        axes[0].set_title("Preventive Task Flow")
        axes[0].grid(alpha=0.25)
        axes[0].legend(loc="best", fontsize=8)

        axes[1].plot(step_df["t"], step_df["dropped_patrol_for_model_scored"], label="patrol dropped", lw=1.2)
        axes[1].plot(step_df["t"], step_df["dropped_direct_for_model_scored"], label="direct dropped", lw=1.2)
        axes[1].plot(step_df["t"], step_df["model_scored_preempt_commands"], label="preempt commands", lw=1.2)
        axes[1].set_title("Displacement / Preemption")
        axes[1].grid(alpha=0.25)
        axes[1].legend(loc="best", fontsize=8)

        axes[2].plot(step_df["t"], step_df["value_weighted_exposure"], label="exposure", lw=1.4)
        axes[2].set_title("Exposure Over Time")
        axes[2].grid(alpha=0.25)
        axes[2].legend(loc="best", fontsize=8)
        axes[2].set_xlabel("time (s)")
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _analyze_task_lifecycle(task_row: pd.Series, frames: list[dict], arrival_radius_m: float) -> dict:
    task_id = int(task_row["task_id"])
    robot_id = str(task_row["assigned_primary"])
    x = float(task_row["x"])
    y = float(task_row["y"])
    accepted_t_raw = float(task_row["accepted_t"])
    t_done_raw = float(task_row["t_done"]) if np.isfinite(float(task_row["t_done"])) else float("nan")
    t_dropped_raw = float(task_row["t_dropped"]) if np.isfinite(float(task_row["t_dropped"])) else float("nan")

    first_active_t = float("nan")
    first_done_t = float("nan")
    first_drop_t = float("nan")
    prev_active = False
    for snap in frames:
        now_t = float(snap["t"])
        active_present = _active_task_for_frame(snap, task_id) is not None
        done_present = any(int(task.get("id", -1)) == task_id for task in snap.get("tasks_done", []))
        if active_present and (not np.isfinite(first_active_t)):
            first_active_t = now_t
        if done_present and (not np.isfinite(first_done_t)):
            first_done_t = now_t
        if prev_active and (not active_present) and (not done_present) and (not np.isfinite(first_drop_t)):
            first_drop_t = now_t
        prev_active = active_present

    accepted_t = first_active_t if np.isfinite(first_active_t) else accepted_t_raw
    done_t = first_done_t if np.isfinite(first_done_t) else t_done_raw
    dropped_t = first_drop_t if np.isfinite(first_drop_t) else t_dropped_raw
    end_t = done_t if int(task_row["completed"]) == 1 else (dropped_t if np.isfinite(dropped_t) else float(frames[-1]["t"]))

    live_snaps = [snap for snap in frames if float(snap["t"]) + 1e-9 >= accepted_t and float(snap["t"]) <= end_t + 1e-9]
    distances: list[tuple[float, float]] = []
    live_frame_count = 0
    active_present_count = 0
    command_match_count = 0
    command_other_task_count = 0
    preempt_command_count = 0
    moving_count = 0
    holding_count = 0
    idle_count = 0
    first_command_t = float("nan")
    first_within_radius_t = float("nan")
    last_command_source = ""

    for snap in live_snaps:
        live_frame_count += 1
        now_t = float(snap["t"])
        pose = snap.get("poses", {}).get(robot_id)
        if pose is not None:
            dist = float(math.hypot(float(pose[0]) - x, float(pose[1]) - y))
            distances.append((now_t, dist))
            if (not np.isfinite(first_within_radius_t)) and dist <= float(arrival_radius_m):
                first_within_radius_t = now_t

        active_task = _active_task_for_frame(snap, task_id)
        if active_task is not None and str(active_task.get("state", "")).strip().lower() == "active":
            active_present_count += 1

        state = str(snap.get("robot_states", {}).get(robot_id, ""))
        if state == "moving":
            moving_count += 1
        elif state == "holding":
            holding_count += 1
        elif state == "idle":
            idle_count += 1

        cmd = _robot_command_for_frame(snap, robot_id)
        if cmd is not None:
            last_command_source = str(cmd.get("source", ""))
            if int(cmd.get("assigned_task_id", -999999) or -999999) == task_id:
                command_match_count += 1
                if not np.isfinite(first_command_t):
                    first_command_t = now_t
            elif cmd.get("assigned_task_id") is not None:
                command_other_task_count += 1
            if str(cmd.get("source", "")) == "deterring_preempt":
                preempt_command_count += 1

    start_distance_m = float(distances[0][1]) if distances else float("nan")
    min_distance_m = float(min((d for _, d in distances), default=float("nan")))
    last_distance_m = float(distances[-1][1]) if distances else float("nan")

    replacement = {
        "replacement_group": "none",
        "replacement_task_id": float("nan"),
        "replacement_task_type": "",
        "replacement_task_mode": "",
        "replacement_command_source": "",
    }
    if str(task_row["status"]) == "dropped":
        drop_snap = next((snap for snap in frames if abs(float(snap["t"]) - float(dropped_t)) <= 1e-9), None)
        if drop_snap is not None:
            replacement = _replacement_context(drop_snap, robot_id=robot_id, dropped_task_id=task_id)

    lifecycle = dict(task_row.to_dict())
    lifecycle.update(replacement)
    lifecycle.update(
        {
            "accepted_t_raw": accepted_t_raw,
            "t_done_raw": t_done_raw,
            "t_dropped_raw": t_dropped_raw,
            "accepted_t_frame": accepted_t,
            "t_done_frame": done_t,
            "t_dropped_frame": dropped_t,
            "accepted_t": accepted_t,
            "t_done": done_t,
            "t_dropped": dropped_t,
            "live_frame_count": int(live_frame_count),
            "active_present_count": int(active_present_count),
            "command_match_count": int(command_match_count),
            "command_other_task_count": int(command_other_task_count),
            "preempt_command_count": int(preempt_command_count),
            "active_present_fraction": float(active_present_count / max(live_frame_count, 1)),
            "command_match_fraction": float(command_match_count / max(live_frame_count, 1)),
            "command_other_task_fraction": float(command_other_task_count / max(live_frame_count, 1)),
            "preempt_command_fraction": float(preempt_command_count / max(live_frame_count, 1)),
            "moving_fraction": float(moving_count / max(live_frame_count, 1)),
            "holding_fraction": float(holding_count / max(live_frame_count, 1)),
            "idle_fraction": float(idle_count / max(live_frame_count, 1)),
            "start_distance_m": start_distance_m,
            "min_distance_m": min_distance_m,
            "last_distance_m": last_distance_m,
            "distance_closed_m": (
                float(start_distance_m - min_distance_m)
                if np.isfinite(start_distance_m) and np.isfinite(min_distance_m)
                else float("nan")
            ),
            "time_to_first_command_s": (
                float(first_command_t - accepted_t) if np.isfinite(first_command_t) else float("nan")
            ),
            "time_to_first_within_radius_s": (
                float(first_within_radius_t - accepted_t) if np.isfinite(first_within_radius_t) else float("nan")
            ),
            "time_in_system_s": float(end_t - accepted_t),
            "last_command_source": last_command_source,
        }
    )
    lifecycle["lifecycle_reason"] = _classify_lifecycle(pd.Series(lifecycle), arrival_radius_m=float(arrival_radius_m))
    return lifecycle


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose accepted preventive tasks that fail to complete.")
    parser.add_argument("--T-end", type=float, default=3 * 3600.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--eval-horizon-s", type=float, default=300.0)
    parser.add_argument("--spatial-radius-m", type=float, default=25.0)
    parser.add_argument("--recent-window-s", type=float, default=180.0)
    parser.add_argument("--arrival-radius-m", type=float, default=3.0)
    parser.add_argument("--outdir", type=str, default="results/diagnostic_incomplete_preventive")
    parser.add_argument("--task-replan-period-s", type=float, default=60.0)
    parser.add_argument("--model-deterring-gate-policy", type=str, default="sprt_capacity")
    parser.add_argument("--model-deterring-sprt-alpha", type=float, default=0.25)
    parser.add_argument("--model-deterring-sprt-beta", type=float, default=0.40)
    parser.add_argument("--model-deterring-sprt-patch-radius-m", type=float, default=30.0)
    parser.add_argument("--model-deterring-min-sprt-margin", type=float, default=0.0)
    parser.add_argument("--model-deterring-chance-threshold", type=float, default=0.35)
    parser.add_argument("--model-deterring-min-deltaj-per-cost", type=float, default=100000.0)
    parser.add_argument("--model-deterring-min-selection-weight", type=float, default=0.0)
    parser.add_argument("--model-deterring-capacity-rho-max", type=float, default=0.85)
    parser.add_argument("--model-deterring-score-margin", type=float, default=0.10)
    parser.add_argument("--model-deterring-global-admission-cap-per-cycle", type=int, default=1)
    parser.add_argument("--model-deterring-require-idle-robot-for-admission", type=int, default=0)
    parser.add_argument("--model-deterring-prefer-idle-robots-for-assignment", type=int, default=1)
    parser.add_argument("--model-deterring-busy-fallback-p-event-min", type=float, default=0.90)
    parser.add_argument("--model-deterring-busy-fallback-deltaj-per-cost-min", type=float, default=1000000.0)
    parser.add_argument("--model-deterring-busy-fallback-eta-s-max", type=float, default=1.25)
    parser.add_argument("--protect-direct-detection-from-model-deterring", type=int, default=1)
    parser.add_argument("--protect-locked-model-deterring-from-patrol-assignment", type=int, default=1)
    parser.add_argument("--protect-active-model-deterring-persistence", type=int, default=1)
    parser.add_argument("--model-deterring-min-persistence-lifetime-s", type=float, default=180.0)
    parser.add_argument("--model-deterring-persistence-eta-multiplier", type=float, default=2.0)
    parser.add_argument("--model-deterring-persistence-buffer-s", type=float, default=60.0)
    parser.add_argument("--model-deterring-max-persistence-lifetime-s", type=float, default=420.0)
    parser.add_argument("--model-deterring-lock-near-goal-radius-m", type=float, default=10.0)
    parser.add_argument("--protect-active-model-deterring-goal-preemption", type=int, default=1)
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
        "model_deterring_min_sprt_margin": float(args.model_deterring_min_sprt_margin),
        "model_deterring_chance_threshold": float(args.model_deterring_chance_threshold),
        "model_deterring_min_deltaJ_per_cost": float(args.model_deterring_min_deltaj_per_cost),
        "model_deterring_min_selection_weight": float(args.model_deterring_min_selection_weight),
        "model_deterring_capacity_rho_max": float(args.model_deterring_capacity_rho_max),
        "model_deterring_score_margin": float(args.model_deterring_score_margin),
        "model_deterring_global_admission_cap_per_cycle": int(args.model_deterring_global_admission_cap_per_cycle),
        "model_deterring_require_idle_robot_for_admission": bool(int(args.model_deterring_require_idle_robot_for_admission)),
        "model_deterring_prefer_idle_robots_for_assignment": bool(int(args.model_deterring_prefer_idle_robots_for_assignment)),
        "model_deterring_busy_fallback_p_event_min": float(args.model_deterring_busy_fallback_p_event_min),
        "model_deterring_busy_fallback_deltaJ_per_cost_min": float(args.model_deterring_busy_fallback_deltaj_per_cost_min),
        "model_deterring_busy_fallback_eta_s_max": float(args.model_deterring_busy_fallback_eta_s_max),
        "protect_direct_detection_from_model_deterring": bool(int(args.protect_direct_detection_from_model_deterring)),
        "protect_locked_model_deterring_from_patrol_assignment": bool(
            int(args.protect_locked_model_deterring_from_patrol_assignment)
        ),
        "protect_active_model_deterring_persistence": bool(int(args.protect_active_model_deterring_persistence)),
        "model_deterring_min_persistence_lifetime_s": float(args.model_deterring_min_persistence_lifetime_s),
        "model_deterring_persistence_eta_multiplier": float(args.model_deterring_persistence_eta_multiplier),
        "model_deterring_persistence_buffer_s": float(args.model_deterring_persistence_buffer_s),
        "model_deterring_max_persistence_lifetime_s": float(args.model_deterring_max_persistence_lifetime_s),
        "model_deterring_lock_near_goal_radius_m": float(args.model_deterring_lock_near_goal_radius_m),
        "protect_active_model_deterring_goal_preemption": bool(
            int(args.protect_active_model_deterring_goal_preemption)
        ),
        "model_deterring_direct_conflict_radius_m": float(args.model_deterring_direct_conflict_radius_m),
        "model_deterring_direct_conflict_window_s": float(args.model_deterring_direct_conflict_window_s),
        "patrol_hotspot_filter_mode": str(args.patrol_hotspot_filter_mode),
        "patrol_hotspot_score_percentile": float(args.patrol_hotspot_score_percentile),
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
    }

    frames = list(ds.run_simulation_frames_persistent(simulation_mode="proposed", **run_params))
    truth_events = _extract_event_stream(frames, "truth_pts")
    detection_events = _extract_event_stream(frames, "det_pts")
    accepted_task_df, step_df, analysis_meta = _analyze_proposed_run(
        frames,
        truth_events=truth_events,
        detection_events=detection_events,
        eval_horizon_s=float(args.eval_horizon_s),
        spatial_radius_m=float(args.spatial_radius_m),
        recent_window_s=float(args.recent_window_s),
    )
    model_df = accepted_task_df[accepted_task_df["task_group"] == "model_scored_deterring"].copy()

    lifecycle_rows = [
        _analyze_task_lifecycle(task_row=row, frames=frames, arrival_radius_m=float(args.arrival_radius_m))
        for _, row in model_df.iterrows()
    ]
    lifecycle_df = pd.DataFrame(lifecycle_rows)
    completed_df = lifecycle_df[lifecycle_df["completed"] == 1].copy() if not lifecycle_df.empty else pd.DataFrame()
    incomplete_df = lifecycle_df[lifecycle_df["completed"] != 1].copy() if not lifecycle_df.empty else pd.DataFrame()

    summary = {
        "parameters": run_params,
        "analysis_meta": analysis_meta,
        "final_metrics": _final_metrics(frames[-1]),
        "accepted_model_scored": _summarize(lifecycle_df),
        "completed_model_scored": _summarize(completed_df),
        "incomplete_model_scored": _summarize(incomplete_df),
        "incomplete_reason_counts": _reason_counts(incomplete_df),
    }
    summary["critical_recommendations"] = _build_recommendations(summary)

    lifecycle_df.to_csv(outdir / "preventive_lifecycle_all.csv", index=False)
    completed_df.to_csv(outdir / "completed_preventive_tasks.csv", index=False)
    incomplete_df.to_csv(outdir / "incomplete_preventive_tasks.csv", index=False)
    step_df.to_csv(outdir / "preventive_lifecycle_timeseries.csv", index=False)
    with open(outdir / "preventive_execution_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    _plot_drop_reasons(incomplete_df, outdir / "preventive_drop_reasons.png")
    _plot_execution_scatter(completed_df, incomplete_df, outdir / "preventive_execution_scatter.png")
    _plot_step_timeseries(step_df, outdir / "preventive_execution_timeseries.png")

    with open(outdir / "preventive_execution_report.md", "w", encoding="utf-8") as f:
        f.write("# Incomplete Preventive Task Diagnostic\n\n")
        f.write("## Parameters\n\n")
        for key, value in run_params.items():
            f.write(f"- `{key}`: `{value}`\n")
        f.write("\n## Final Metrics\n\n")
        for key, value in summary["final_metrics"].items():
            f.write(f"- `{key}`: `{value}`\n")
        f.write("\n## Accepted Model-Scored Summary\n\n")
        for key, value in summary["accepted_model_scored"].items():
            f.write(f"- `{key}`: `{value}`\n")
        f.write("\n## Completed Model-Scored Summary\n\n")
        for key, value in summary["completed_model_scored"].items():
            f.write(f"- `{key}`: `{value}`\n")
        f.write("\n## Incomplete Model-Scored Summary\n\n")
        for key, value in summary["incomplete_model_scored"].items():
            f.write(f"- `{key}`: `{value}`\n")
        f.write("\n## Incomplete Reasons\n\n")
        for key, value in summary["incomplete_reason_counts"].items():
            f.write(f"- `{key}`: `{value}`\n")
        f.write("\n## Critical Recommendations\n\n")
        for rec in summary["critical_recommendations"]:
            f.write(f"- {rec}\n")


if __name__ == "__main__":
    main()
