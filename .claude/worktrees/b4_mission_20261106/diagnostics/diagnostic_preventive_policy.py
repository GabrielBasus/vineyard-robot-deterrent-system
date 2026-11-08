from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import DeterrentSystem as ds


def _task_source(task_row: dict) -> str:
    ttype = str(task_row.get("type", "")).strip().lower()
    if ttype != "deterring":
        return "-"
    mode = task_row.get("mode")
    if mode not in (None, "", "none"):
        return "model_scored"
    origin = str(task_row.get("origin", "")).strip().lower()
    return "direct_detection" if origin in ("", "detection") else "model_scored"


def _task_group(task_row: dict) -> str:
    ttype = str(task_row.get("type", "")).strip().lower()
    if ttype == "patrolling":
        return "patrolling"
    if ttype == "deterring":
        return "model_scored_deterring" if _task_source(task_row) == "model_scored" else "direct_detection_deterring"
    return "other"


def _point_counter(points: Iterable[Tuple[float, float]]) -> Counter:
    return Counter((float(x), float(y)) for x, y in points)


def _counter_diff(newer: Counter, older: Counter) -> List[Tuple[float, float]]:
    diff = newer - older
    out: List[Tuple[float, float]] = []
    for pt, count in diff.items():
        out.extend([pt] * int(count))
    return out


def _extract_event_stream(frames: list[dict], key: str) -> list[dict]:
    events: list[dict] = []
    prev_counter: Counter = Counter()
    for snap in frames:
        now_t = float(snap["t"])
        curr_counter = _point_counter(snap.get(key, []))
        for x, y in _counter_diff(curr_counter, prev_counter):
            events.append({"x": float(x), "y": float(y), "t": now_t})
        prev_counter = curr_counter
    return events


def _safe_mean(values: Iterable[float]) -> float:
    vals = [float(v) for v in values if np.isfinite(v)]
    if not vals:
        return float("nan")
    return float(np.mean(vals))


def _future_event_stats(
    x: float,
    y: float,
    t0: float,
    events: list[dict],
    horizon_s: float,
    radius_m: float,
) -> tuple[int, float, float]:
    count = 0
    min_dt = float("nan")
    min_dist = float("nan")
    best_dt = float("inf")
    best_dist = float("inf")
    t1 = float(t0 + horizon_s)
    for ev in events:
        tev = float(ev["t"])
        if tev <= t0 or tev > t1:
            continue
        dist = math.hypot(float(ev["x"]) - x, float(ev["y"]) - y)
        if dist <= radius_m:
            count += 1
            dt = tev - t0
            if dt < best_dt:
                best_dt = dt
                min_dt = float(dt)
            if dist < best_dist:
                best_dist = dist
                min_dist = float(dist)
    return int(count), float(min_dt), float(min_dist)


def _recent_event_count(
    x: float,
    y: float,
    t0: float,
    events: list[dict],
    window_s: float,
    radius_m: float,
) -> int:
    count = 0
    t_min = float(t0 - window_s)
    for ev in events:
        tev = float(ev["t"])
        if tev < t_min or tev > t0:
            continue
        if math.hypot(float(ev["x"]) - x, float(ev["y"]) - y) <= radius_m:
            count += 1
    return int(count)


def _final_metrics(last: dict) -> dict:
    metrics = last.get("metrics", {})
    return {
        "value_weighted_exposure": float(metrics.get("value_weighted_exposure", np.nan)),
        "mean_response_time_s": float(metrics.get("mean_response_time_s", np.nan)),
        "boundary_message_count": float(metrics.get("boundary_message_count", np.nan)),
        "model_deterring_generated": float(metrics.get("model_deterring_generated", np.nan)),
        "model_deterring_accepted": float(metrics.get("model_deterring_accepted", np.nan)),
        "deterring_actions_completed_model_scored": float(
            metrics.get("deterring_actions_completed_model_scored", np.nan)
        ),
    }


def _baseline_step_metrics(frames: list[dict], sample_every_s: float) -> pd.DataFrame:
    rows: list[dict] = []
    next_sample_t = -1e18
    for snap in frames:
        now_t = float(snap["t"])
        if now_t < next_sample_t:
            continue
        next_sample_t = now_t + float(sample_every_s)
        metrics = snap.get("metrics", {})
        active = snap.get("tasks_active", [])
        rows.append(
            {
                "t": now_t,
                "value_weighted_exposure": float(metrics.get("value_weighted_exposure", np.nan)),
                "mean_response_time_s": float(metrics.get("mean_response_time_s", np.nan)),
                "boundary_message_count": float(metrics.get("boundary_message_count", np.nan)),
                "active_patrolling": int(sum(1 for tr in active if _task_group(tr) == "patrolling")),
                "active_model_scored_deterring": int(
                    sum(1 for tr in active if _task_group(tr) == "model_scored_deterring")
                ),
            }
        )
    return pd.DataFrame(rows)


def _task_row_from_task(task_row: dict, accepted_t: float) -> dict:
    return {
        "task_id": int(task_row.get("id", -1)),
        "task_group": _task_group(task_row),
        # Use the frame timebase for lifecycle metrics; task rows may carry an internal
        # absolute assignment time that does not match the emitted frame timeline.
        "accepted_t": float(accepted_t),
        "x": float(task_row.get("x", 0.0)),
        "y": float(task_row.get("y", 0.0)),
        "assigned_primary": str(task_row.get("assigned_primary", "")),
        "assigned_secondary": str(task_row.get("assigned_secondary", "")),
        "origin": str(task_row.get("origin", "")),
        "mode": (None if task_row.get("mode") in (None, "", "none") else str(task_row.get("mode"))),
        "score": float(task_row.get("score", 0.0)),
        "utility": float(task_row.get("utility", 0.0)),
        "predicted_deltaJ": float(task_row.get("predicted_deltaJ", 0.0)),
        "p_event": float(task_row.get("p_event", 0.0)),
        "deltaJ_per_cost": float(task_row.get("deltaJ_per_cost", 0.0)),
        "llr": float(task_row.get("llr", 0.0)),
        "selection_weight": float(task_row.get("selection_weight", 1.0)),
        "posterior_h1": float(task_row.get("posterior_h1", np.nan)),
        "count_excess_ratio": float(task_row.get("count_excess_ratio", np.nan)),
        "support": int(task_row.get("support", 0)),
        "risk_conf": float(task_row.get("risk_conf", 0.0)),
        "eta_s": float(task_row.get("eta_s", 0.0)),
        "assigned_eta_s": float(task_row.get("assigned_eta_s", task_row.get("eta_s", 0.0))),
        "persistence": int(task_row.get("persistence", 0)),
        "completed": 0,
        "t_done": float("nan"),
        "time_to_complete_s": float("nan"),
        "dropped_without_completion": 0,
        "t_dropped": float("nan"),
        "status": "active_or_pending",
        "accepted_with_preempt_command": 0,
        "dropped_patrol_same_robot_at_accept": 0,
        "dropped_direct_detection_same_robot_at_accept": 0,
        "dropped_model_scored_same_robot_at_accept": 0,
    }

def _analyze_proposed_run(
    frames: list[dict],
    truth_events: list[dict],
    detection_events: list[dict],
    eval_horizon_s: float,
    spatial_radius_m: float,
    recent_window_s: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    accepted_rows: list[dict] = []
    row_index_by_task_id: Dict[int, int] = {}
    step_rows: list[dict] = []

    prev_active: Dict[int, dict] = {}
    prev_done_ids: set[int] = set()

    for snap in frames:
        now_t = float(snap["t"])
        metrics = snap.get("metrics", {})
        active_now = {
            int(tr.get("id", -1)): tr
            for tr in snap.get("tasks_active", [])
            if str(tr.get("state", "")).strip().lower() == "active"
        }
        done_now = {int(tr.get("id", -1)): tr for tr in snap.get("tasks_done", [])}

        new_active_ids = set(active_now) - set(prev_active)
        new_done_ids = set(done_now) - set(prev_done_ids)
        dropped_ids = set(prev_active) - set(active_now) - set(done_now)
        dropped_rows = [prev_active[tid] for tid in dropped_ids]

        dropped_counts_by_robot = defaultdict(lambda: {"patrolling": 0, "direct_detection_deterring": 0, "model_scored_deterring": 0})
        for tr in dropped_rows:
            rid = str(tr.get("assigned_primary", ""))
            grp = _task_group(tr)
            if grp in dropped_counts_by_robot[rid]:
                dropped_counts_by_robot[rid][grp] += 1

        commands = snap.get("motion_commands", [])
        preempt_by_robot = defaultdict(int)
        for cmd in commands:
            if str(cmd.get("source", "")) == "deterring_preempt":
                preempt_by_robot[str(cmd.get("robot_id", ""))] += 1

        new_model_scored_accepted = 0
        new_model_scored_completed = 0
        new_model_scored_dropped = 0
        dropped_patrol_for_model_scored = 0
        dropped_direct_for_model_scored = 0
        model_preempt_commands = 0

        for tid in sorted(new_active_ids):
            tr = active_now[tid]
            grp = _task_group(tr)
            if grp not in {"model_scored_deterring", "patrolling", "direct_detection_deterring"}:
                continue
            row = _task_row_from_task(tr, accepted_t=now_t)
            rid = str(row["assigned_primary"])
            if grp == "model_scored_deterring":
                row["accepted_with_preempt_command"] = int(preempt_by_robot.get(rid, 0) > 0)
                row["dropped_patrol_same_robot_at_accept"] = int(dropped_counts_by_robot[rid]["patrolling"])
                row["dropped_direct_detection_same_robot_at_accept"] = int(
                    dropped_counts_by_robot[rid]["direct_detection_deterring"]
                )
                row["dropped_model_scored_same_robot_at_accept"] = int(
                    dropped_counts_by_robot[rid]["model_scored_deterring"]
                )
                new_model_scored_accepted += 1
                dropped_patrol_for_model_scored += int(row["dropped_patrol_same_robot_at_accept"])
                dropped_direct_for_model_scored += int(row["dropped_direct_detection_same_robot_at_accept"])
                model_preempt_commands += int(row["accepted_with_preempt_command"])
            accepted_rows.append(row)
            row_index_by_task_id[tid] = len(accepted_rows) - 1

        for tid in sorted(new_done_ids):
            tr = done_now[tid]
            grp = _task_group(tr)
            if tid not in row_index_by_task_id and grp in {"model_scored_deterring", "patrolling", "direct_detection_deterring"}:
                accepted_rows.append(_task_row_from_task(tr, accepted_t=now_t))
                row_index_by_task_id[tid] = len(accepted_rows) - 1
                if grp == "model_scored_deterring":
                    new_model_scored_accepted += 1
            idx = row_index_by_task_id.get(tid)
            if idx is None:
                continue
            accepted_rows[idx]["completed"] = 1
            accepted_rows[idx]["t_done"] = float(now_t)
            accepted_rows[idx]["time_to_complete_s"] = float(accepted_rows[idx]["t_done"] - accepted_rows[idx]["accepted_t"])
            accepted_rows[idx]["status"] = "completed"
            if accepted_rows[idx]["task_group"] == "model_scored_deterring":
                new_model_scored_completed += 1

        for tid in sorted(dropped_ids):
            idx = row_index_by_task_id.get(tid)
            if idx is None:
                continue
            if int(accepted_rows[idx]["completed"]) == 1:
                continue
            accepted_rows[idx]["dropped_without_completion"] = 1
            accepted_rows[idx]["t_dropped"] = now_t
            accepted_rows[idx]["status"] = "dropped"
            if accepted_rows[idx]["task_group"] == "model_scored_deterring":
                new_model_scored_dropped += 1

        active_model_scored = int(
            sum(1 for tr in active_now.values() if _task_group(tr) == "model_scored_deterring")
        )
        active_patrolling = int(
            sum(1 for tr in active_now.values() if _task_group(tr) == "patrolling")
        )
        step_rows.append(
            {
                "t": now_t,
                "value_weighted_exposure": float(metrics.get("value_weighted_exposure", np.nan)),
                "mean_response_time_s": float(metrics.get("mean_response_time_s", np.nan)),
                "boundary_message_count": float(metrics.get("boundary_message_count", np.nan)),
                "active_model_scored_deterring": active_model_scored,
                "active_patrolling": active_patrolling,
                "new_model_scored_accepted": int(new_model_scored_accepted),
                "new_model_scored_completed": int(new_model_scored_completed),
                "new_model_scored_dropped": int(new_model_scored_dropped),
                "dropped_patrol_for_model_scored": int(dropped_patrol_for_model_scored),
                "dropped_direct_for_model_scored": int(dropped_direct_for_model_scored),
                "model_scored_preempt_commands": int(model_preempt_commands),
            }
        )

        prev_active = active_now
        prev_done_ids = set(done_now)

    task_df = pd.DataFrame(accepted_rows)
    if task_df.empty:
        return task_df, pd.DataFrame(step_rows), {}

    for idx in task_df.index:
        x = float(task_df.at[idx, "x"])
        y = float(task_df.at[idx, "y"])
        accepted_t = float(task_df.at[idx, "accepted_t"])
        recent_truth = _recent_event_count(x, y, accepted_t, truth_events, recent_window_s, spatial_radius_m)
        recent_det = _recent_event_count(x, y, accepted_t, detection_events, recent_window_s, spatial_radius_m)
        future_truth_count, future_truth_min_dt, future_truth_min_dist = _future_event_stats(
            x, y, accepted_t, truth_events, eval_horizon_s, spatial_radius_m
        )
        future_det_count, _, _ = _future_event_stats(
            x, y, accepted_t, detection_events, eval_horizon_s, spatial_radius_m
        )
        task_df.at[idx, "recent_truth_count"] = int(recent_truth)
        task_df.at[idx, "recent_detection_count"] = int(recent_det)
        task_df.at[idx, "future_truth_count"] = int(future_truth_count)
        task_df.at[idx, "future_truth_hit"] = int(future_truth_count > 0)
        task_df.at[idx, "future_truth_min_dt_s"] = float(future_truth_min_dt)
        task_df.at[idx, "future_truth_min_dist_m"] = float(future_truth_min_dist)
        task_df.at[idx, "future_detection_count"] = int(future_det_count)

    for idx in task_df.index:
        if str(task_df.at[idx, "status"]) == "active_or_pending":
            task_df.at[idx, "status"] = "still_active"

    step_df = pd.DataFrame(step_rows)
    summary = {
        "accepted_task_count_total": int(len(task_df)),
        "model_scored_task_count": int((task_df["task_group"] == "model_scored_deterring").sum()),
        "patrolling_task_count": int((task_df["task_group"] == "patrolling").sum()),
        "direct_detection_task_count": int((task_df["task_group"] == "direct_detection_deterring").sum()),
    }
    return task_df, step_df, summary


def _summarize_group(task_df: pd.DataFrame, group_name: str) -> dict:
    sub = task_df[task_df["task_group"] == group_name].copy()
    if sub.empty:
        return {
            "accepted_count": 0,
            "completed_count": 0,
            "dropped_count": 0,
            "completion_rate": float("nan"),
            "future_truth_hit_rate": float("nan"),
            "future_truth_count_mean": float("nan"),
            "recent_truth_count_mean": float("nan"),
            "p_event_mean": float("nan"),
            "p_event_hit_mean": float("nan"),
            "p_event_miss_mean": float("nan"),
            "predicted_deltaJ_mean": float("nan"),
            "deltaJ_per_cost_mean": float("nan"),
            "selection_weight_mean": float("nan"),
            "posterior_h1_mean": float("nan"),
            "count_excess_ratio_mean": float("nan"),
            "accept_with_preempt_rate": float("nan"),
            "dropped_patrol_same_robot_at_accept_mean": float("nan"),
            "dropped_direct_detection_same_robot_at_accept_mean": float("nan"),
            "time_to_complete_mean_s": float("nan"),
        }
    hit_mask = sub["future_truth_hit"] == 1
    miss_mask = sub["future_truth_hit"] == 0
    return {
        "accepted_count": int(len(sub)),
        "completed_count": int(sub["completed"].sum()),
        "dropped_count": int(sub["dropped_without_completion"].sum()),
        "completion_rate": float(sub["completed"].mean()),
        "future_truth_hit_rate": float(sub["future_truth_hit"].mean()),
        "future_truth_count_mean": float(sub["future_truth_count"].mean()),
        "recent_truth_count_mean": float(sub["recent_truth_count"].mean()),
        "p_event_mean": _safe_mean(sub["p_event"]),
        "p_event_hit_mean": _safe_mean(sub.loc[hit_mask, "p_event"]),
        "p_event_miss_mean": _safe_mean(sub.loc[miss_mask, "p_event"]),
        "predicted_deltaJ_mean": _safe_mean(sub["predicted_deltaJ"]),
        "deltaJ_per_cost_mean": _safe_mean(sub["deltaJ_per_cost"]),
        "selection_weight_mean": _safe_mean(sub["selection_weight"]),
        "posterior_h1_mean": _safe_mean(sub["posterior_h1"]),
        "count_excess_ratio_mean": _safe_mean(sub["count_excess_ratio"]),
        "accept_with_preempt_rate": _safe_mean(sub["accepted_with_preempt_command"]),
        "dropped_patrol_same_robot_at_accept_mean": _safe_mean(sub["dropped_patrol_same_robot_at_accept"]),
        "dropped_direct_detection_same_robot_at_accept_mean": _safe_mean(
            sub["dropped_direct_detection_same_robot_at_accept"]
        ),
        "time_to_complete_mean_s": _safe_mean(sub["time_to_complete_s"]),
    }

def _build_recommendations(summary: dict) -> list[str]:
    out: list[str] = []
    model_stats = summary.get("model_scored_deterring", {})
    patrol_stats = summary.get("patrolling", {})
    exposure_delta = float(summary.get("comparison", {}).get("exposure_improve_pct", float("nan")))
    response_delta = float(summary.get("comparison", {}).get("response_improve_pct", float("nan")))

    if int(model_stats.get("accepted_count", 0)) == 0:
        out.append("No model-scored preventive tasks were accepted; the bottleneck is still admission, not task quality.")
        return out

    model_hit = float(model_stats.get("future_truth_hit_rate", float("nan")))
    patrol_hit = float(patrol_stats.get("future_truth_hit_rate", float("nan")))
    if np.isfinite(model_hit) and np.isfinite(patrol_hit) and model_hit + 1e-9 < patrol_hit:
        out.append("Accepted model-scored tasks are landing in weaker locations than patrol tasks; tighten admission or re-rank preventive tasks by stronger future-event evidence.")
    if float(model_stats.get("completion_rate", float("nan"))) < 0.6:
        out.append("Many accepted model-scored tasks do not complete; reduce ETA allowance or admit fewer preventive tasks so execution can keep up.")
    if float(model_stats.get("accept_with_preempt_rate", float("nan"))) > 0.2 and np.isfinite(response_delta) and response_delta < 0.0:
        out.append("Preventive tasks are frequently taking over robot goals while response worsens; limit model-scored preemption or raise its score threshold.")
    if (
        np.isfinite(float(model_stats.get("p_event_hit_mean", float("nan"))))
        and np.isfinite(float(model_stats.get("p_event_miss_mean", float("nan"))))
        and float(model_stats.get("p_event_hit_mean")) <= float(model_stats.get("p_event_miss_mean")) + 1e-9
    ):
        out.append("The accepted-task chance score is not separating hits from misses; recalibrate the chance mapping or gate on a stronger local truth proxy.")
    if np.isfinite(exposure_delta) and exposure_delta < 0.0:
        out.append("Closed-loop exposure is still worse than prediction-only; the current preventive policy is too disruptive or is placing tasks in low-yield regions.")
    if not out:
        out.append("Accepted preventive tasks show reasonable spatial quality; next step is multi-seed confirmation of the current policy setting.")
    return out


def _plot_policy_map(last_snap: dict, truth_events: list[dict], task_df: pd.DataFrame, out_png: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharex=True, sharey=True)
    panels = [
        ("model_scored_deterring", "Accepted Model-Scored Deterring"),
        ("patrolling", "Accepted Patrol Tasks"),
    ]
    truth_x = [float(ev["x"]) for ev in truth_events]
    truth_y = [float(ev["y"]) for ev in truth_events]
    for ax, (group_name, title) in zip(axes, panels):
        ax.set_title(title)
        ax.set_xlim(0.0, float(last_snap["W"]))
        ax.set_ylim(0.0, float(last_snap["H"]))
        ax.set_aspect("equal", adjustable="box")
        bx, by = zip(*(last_snap["boundary"] + [last_snap["boundary"][0]]))
        ax.plot(bx, by, "k-", lw=1.0)
        for cell in last_snap["cells"]:
            if not cell:
                continue
            xs = [p[0] for p in cell] + [cell[0][0]]
            ys = [p[1] for p in cell] + [cell[0][1]]
            ax.plot(xs, ys, "-", color="#999999", lw=0.7, alpha=0.6)
        if truth_x:
            ax.scatter(truth_x, truth_y, s=8, c="#bbbbbb", alpha=0.35, label="truth events")
        sub = task_df[task_df["task_group"] == group_name]
        hits = sub[sub["future_truth_hit"] == 1]
        misses = sub[sub["future_truth_hit"] == 0]
        if not hits.empty:
            ax.scatter(hits["x"], hits["y"], s=42, c="#2ca02c", label="future-hit")
        if not misses.empty:
            ax.scatter(misses["x"], misses["y"], s=42, c="#d62728", label="future-miss")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
    handles, labels = axes[1].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="upper center", ncol=4, fontsize=8)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _plot_policy_timeseries(pred_df: pd.DataFrame, prop_step_df: pd.DataFrame, out_png: Path) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    axes[0].plot(pred_df["t"], pred_df["value_weighted_exposure"], label="prediction_only", lw=1.4)
    axes[0].plot(prop_step_df["t"], prop_step_df["value_weighted_exposure"], label="proposed", lw=1.4)
    axes[0].set_title("Exposure Over Time")
    axes[0].grid(alpha=0.25)
    axes[0].legend(loc="best", fontsize=8)

    axes[1].plot(prop_step_df["t"], prop_step_df["active_model_scored_deterring"], label="active model-scored")
    axes[1].plot(prop_step_df["t"], prop_step_df["new_model_scored_accepted"], label="new accepts")
    axes[1].plot(prop_step_df["t"], prop_step_df["new_model_scored_completed"], label="new completes")
    axes[1].set_title("Preventive Task Flow")
    axes[1].grid(alpha=0.25)
    axes[1].legend(loc="best", fontsize=8)

    axes[2].plot(prop_step_df["t"], prop_step_df["dropped_patrol_for_model_scored"], label="patrol dropped")
    axes[2].plot(prop_step_df["t"], prop_step_df["dropped_direct_for_model_scored"], label="direct deterring dropped")
    axes[2].plot(prop_step_df["t"], prop_step_df["model_scored_preempt_commands"], label="preempt commands")
    axes[2].set_title("Preemption / Displacement Effects")
    axes[2].grid(alpha=0.25)
    axes[2].legend(loc="best", fontsize=8)
    axes[2].set_xlabel("time (s)")

    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _plot_quality_scatter(task_df: pd.DataFrame, out_png: Path) -> None:
    sub = task_df[task_df["task_group"] == "model_scored_deterring"].copy()
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    if sub.empty:
        for ax in axes:
            ax.text(0.5, 0.5, "No accepted model-scored tasks", ha="center", va="center")
            ax.set_axis_off()
    else:
        colors = np.where(sub["future_truth_hit"] == 1, "#2ca02c", "#d62728")
        axes[0].scatter(sub["p_event"], sub["future_truth_count"], c=colors, alpha=0.8)
        axes[0].set_title("Accepted Model-Scored Tasks: p_event vs Future Truth Count")
        axes[0].set_xlabel("p_event")
        axes[0].set_ylabel("future truth count")
        axes[0].grid(alpha=0.25)

        axes[1].scatter(sub["predicted_deltaJ"], sub["future_truth_count"], c=colors, alpha=0.8)
        axes[1].set_title("Accepted Model-Scored Tasks: predicted_deltaJ vs Future Truth Count")
        axes[1].set_xlabel("predicted_deltaJ")
        axes[1].set_ylabel("future truth count")
        axes[1].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)

def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose preventive task quality, placement, and preemption effects.")
    parser.add_argument("--T-end", type=float, default=3 * 3600.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--sample-every-s", type=float, default=30.0)
    parser.add_argument("--eval-horizon-s", type=float, default=300.0)
    parser.add_argument("--spatial-radius-m", type=float, default=25.0)
    parser.add_argument("--recent-window-s", type=float, default=180.0)
    parser.add_argument("--outdir", type=str, default="results/diagnostic_preventive_policy")
    parser.add_argument("--task-replan-period-s", type=float, default=60.0)
    parser.add_argument("--model-deterring-gate-policy", type=str, default="sprt_capacity")
    parser.add_argument("--model-deterring-sprt-alpha", type=float, default=0.25)
    parser.add_argument("--model-deterring-sprt-beta", type=float, default=0.40)
    parser.add_argument("--model-deterring-sprt-patch-radius-m", type=float, default=30.0)
    parser.add_argument("--model-deterring-min-sprt-margin", type=float, default=0.0)
    parser.add_argument("--model-deterring-chance-threshold", type=float, default=0.25)
    parser.add_argument("--model-deterring-min-deltaj-per-cost", type=float, default=100000.0)
    parser.add_argument("--model-deterring-min-selection-weight", type=float, default=0.0)
    parser.add_argument("--model-deterring-capacity-rho-max", type=float, default=0.85)
    parser.add_argument("--model-deterring-score-margin", type=float, default=0.10)
    parser.add_argument("--model-deterring-global-admission-cap-per-cycle", type=int, default=1)
    parser.add_argument("--model-deterring-require-idle-robot-for-admission", type=int, default=0)
    parser.add_argument("--model-deterring-prefer-idle-robots-for-assignment", type=int, default=1)
    parser.add_argument("--model-deterring-busy-fallback-p-event-min", type=float, default=0.95)
    parser.add_argument("--model-deterring-busy-fallback-deltaj-per-cost-min", type=float, default=2000000.0)
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

    pred_frames = list(ds.run_simulation_frames_persistent(simulation_mode="prediction_only", **run_params))
    prop_frames = list(ds.run_simulation_frames_persistent(simulation_mode="proposed", **run_params))

    pred_df = _baseline_step_metrics(pred_frames, sample_every_s=float(args.sample_every_s))
    prop_baseline_df = _baseline_step_metrics(prop_frames, sample_every_s=float(args.sample_every_s))
    truth_events = _extract_event_stream(prop_frames, "truth_pts")
    detection_events = _extract_event_stream(prop_frames, "det_pts")
    task_df, prop_step_df, analysis_meta = _analyze_proposed_run(
        prop_frames,
        truth_events=truth_events,
        detection_events=detection_events,
        eval_horizon_s=float(args.eval_horizon_s),
        spatial_radius_m=float(args.spatial_radius_m),
        recent_window_s=float(args.recent_window_s),
    )

    pred_final = _final_metrics(pred_frames[-1])
    prop_final = _final_metrics(prop_frames[-1])
    exposure_improve_pct = 100.0 * (
        float(pred_final["value_weighted_exposure"]) - float(prop_final["value_weighted_exposure"])
    ) / max(abs(float(pred_final["value_weighted_exposure"])), 1e-9)
    response_improve_pct = 100.0 * (
        float(pred_final["mean_response_time_s"]) - float(prop_final["mean_response_time_s"])
    ) / max(abs(float(pred_final["mean_response_time_s"])), 1e-9)

    summary = {
        "parameters": run_params,
        "comparison": {
            "prediction_only_final_metrics": pred_final,
            "proposed_final_metrics": prop_final,
            "exposure_improve_pct": float(exposure_improve_pct),
            "response_improve_pct": float(response_improve_pct),
        },
        "analysis_meta": analysis_meta,
        "model_scored_deterring": _summarize_group(task_df, "model_scored_deterring"),
        "patrolling": _summarize_group(task_df, "patrolling"),
        "direct_detection_deterring": _summarize_group(task_df, "direct_detection_deterring"),
    }
    summary["comparative_quality"] = {
        "model_scored_minus_patrolling_future_truth_hit_rate": (
            float(summary["model_scored_deterring"]["future_truth_hit_rate"])
            - float(summary["patrolling"]["future_truth_hit_rate"])
            if np.isfinite(float(summary["model_scored_deterring"]["future_truth_hit_rate"]))
            and np.isfinite(float(summary["patrolling"]["future_truth_hit_rate"]))
            else float("nan")
        ),
        "model_scored_minus_patrolling_future_truth_count_mean": (
            float(summary["model_scored_deterring"]["future_truth_count_mean"])
            - float(summary["patrolling"]["future_truth_count_mean"])
            if np.isfinite(float(summary["model_scored_deterring"]["future_truth_count_mean"]))
            and np.isfinite(float(summary["patrolling"]["future_truth_count_mean"]))
            else float("nan")
        ),
    }
    summary["critical_recommendations"] = _build_recommendations(summary)

    task_df.to_csv(outdir / "preventive_policy_tasks.csv", index=False)
    pred_df.to_csv(outdir / "preventive_policy_prediction_only_timeseries.csv", index=False)
    prop_baseline_df.to_csv(outdir / "preventive_policy_proposed_baseline_timeseries.csv", index=False)
    prop_step_df.to_csv(outdir / "preventive_policy_proposed_step_analysis.csv", index=False)
    with open(outdir / "preventive_policy_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    _plot_policy_map(prop_frames[-1], truth_events, task_df, outdir / "preventive_policy_map.png")
    _plot_policy_timeseries(pred_df, prop_step_df, outdir / "preventive_policy_timeseries.png")
    _plot_quality_scatter(task_df, outdir / "preventive_policy_quality.png")

    with open(outdir / "preventive_policy_report.md", "w", encoding="utf-8") as f:
        f.write("# Preventive Policy Diagnostic Report\n\n")
        f.write("## Parameters\n\n")
        for key, value in run_params.items():
            f.write(f"- `{key}`: `{value}`\n")
        f.write("\n## Final Comparison\n\n")
        f.write(
            f"- Exposure improvement vs `prediction_only`: `{summary['comparison']['exposure_improve_pct']:.3f}%`\n"
        )
        f.write(
            f"- Response improvement vs `prediction_only`: `{summary['comparison']['response_improve_pct']:.3f}%`\n"
        )
        f.write("\n## Preventive Task Quality\n\n")
        for group_name in ["model_scored_deterring", "patrolling", "direct_detection_deterring"]:
            stats = summary[group_name]
            f.write(f"### {group_name}\n\n")
            for key, value in stats.items():
                f.write(f"- `{key}`: `{value}`\n")
            f.write("\n")
        f.write("## Comparative Quality\n\n")
        for key, value in summary["comparative_quality"].items():
            f.write(f"- `{key}`: `{value}`\n")
        f.write("\n## Critical Recommendations\n\n")
        for rec in summary["critical_recommendations"]:
            f.write(f"- {rec}\n")


if __name__ == "__main__":
    main()
