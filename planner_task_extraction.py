from __future__ import annotations

from typing import Any, Callable, Iterable

import numpy as np


def run_task_location_estimation(
    *,
    taskgen: Any,
    robots: dict,
    now_t: float,
    enable_patrolling: bool,
    include_fallback_patrol: bool,
    enable_model_scored_deterring: bool,
    model_deterring_window_s: float,
    model_deterring_risk_threshold: float,
    model_deterring_risk_scale: float,
    model_deterring_min_recent_points: int,
    model_deterring_field_threshold: float | None,
    model_deterring_min_persistence_replans: int,
    model_deterring_persistence_max_gap_s: float,
    model_deterring_score_margin: float,
    model_deterring_repeat_block_window_s: float,
    model_deterring_repeat_block_radius_m: float,
    model_deterring_max_eta_s: float,
    model_deterring_busy_min_support_override: int,
    model_deterring_busy_risk_override: float,
    enable_predicted_deltaJ_gate: bool,
    min_predicted_deltaJ_for_model_deterring: float,
    model_deterring_gate_policy: str,
    model_deterring_sprt_alpha: float,
    model_deterring_sprt_beta: float,
    model_deterring_sprt_patch_radius_m,
    model_deterring_min_sprt_margin: float,
    model_deterring_chance_threshold: float,
    model_deterring_min_deltaJ_per_cost: float,
    model_deterring_min_selection_weight: float,
    preventive_capacity_remaining_by_robot: dict,
    preventive_capacity_ready_by_robot: dict,
    task_replan_period_s: float,
    busy_deterring_robots: set[str],
    recent_deterrences: list[dict],
    profiles: dict,
    use_live_robot_pose_for_task_planning: bool,
    pose: dict,
    rng: Any,
    patrol_hotspot_filter_mode: str,
    patrol_hotspot_score_percentile: float,
    patrol_hotspot_keep_top_k,
    patrol_feedback_inhibition_retention: float,
    value_weight_fn: Callable[[float, float], float],
    deterring_modes: dict,
) -> None:
    if not enable_patrolling:
        return
    taskgen.periodic_patrolling(
        robots=robots,
        now_t=now_t,
        hotspot_top_k=5,
        include_fallback_patrol=include_fallback_patrol,
        enable_model_scored_deterring=bool(enable_model_scored_deterring),
        deterring_window_s=float(model_deterring_window_s),
        deterring_risk_threshold=float(model_deterring_risk_threshold),
        deterring_risk_scale=float(model_deterring_risk_scale),
        deterring_min_recent_points=int(model_deterring_min_recent_points),
        deterring_field_threshold=model_deterring_field_threshold,
        deterring_min_persistence_replans=int(model_deterring_min_persistence_replans),
        deterring_persistence_max_gap_s=float(model_deterring_persistence_max_gap_s),
        deterring_score_margin=float(model_deterring_score_margin),
        deterring_repeat_block_window_s=float(model_deterring_repeat_block_window_s),
        deterring_repeat_block_radius_m=float(model_deterring_repeat_block_radius_m),
        deterring_max_eta_s=float(model_deterring_max_eta_s),
        deterring_busy_min_support_override=int(model_deterring_busy_min_support_override),
        deterring_busy_risk_override=float(model_deterring_busy_risk_override),
        enable_predicted_deltaJ_gate=bool(enable_predicted_deltaJ_gate),
        min_predicted_deltaJ_for_model_deterring=float(min_predicted_deltaJ_for_model_deterring),
        model_deterring_gate_policy=str(model_deterring_gate_policy),
        model_deterring_sprt_alpha=float(model_deterring_sprt_alpha),
        model_deterring_sprt_beta=float(model_deterring_sprt_beta),
        model_deterring_sprt_patch_radius_m=model_deterring_sprt_patch_radius_m,
        model_deterring_min_sprt_margin=float(model_deterring_min_sprt_margin),
        model_deterring_chance_threshold=float(model_deterring_chance_threshold),
        model_deterring_min_deltaJ_per_cost=float(model_deterring_min_deltaJ_per_cost),
        model_deterring_min_selection_weight=float(model_deterring_min_selection_weight),
        preventive_capacity_remaining_by_robot=preventive_capacity_remaining_by_robot,
        preventive_capacity_ready_by_robot=preventive_capacity_ready_by_robot,
        replan_interval_s=float(task_replan_period_s),
        busy_deterring_robots=busy_deterring_robots,
        recent_deterrence_events=list(recent_deterrences),
        profiles=profiles,
        robot_poses=(pose if bool(use_live_robot_pose_for_task_planning) else None),
        rng=rng,
        patrol_hotspot_filter_mode=patrol_hotspot_filter_mode,
        patrol_hotspot_score_percentile=float(patrol_hotspot_score_percentile),
        patrol_hotspot_keep_top_k=patrol_hotspot_keep_top_k,
        patrol_feedback_inhibition_retention=float(patrol_feedback_inhibition_retention),
        spinup_by_type={"UAV": 8.0, "UGV": 0.0},
        weight_fn=value_weight_fn,
        deterring_modes=deterring_modes,
    )


def build_task_dispatch_candidate_buffer(
    *,
    now_t: float,
    active_tasks: list[dict],
    completed_tasks: list[dict],
    consumed_task_keys: set,
    taskgen: Any,
    robot_ids: Iterable[str],
    task_buffer_key_fn: Callable[[dict], Any],
    is_direct_detection_task_fn: Callable[[dict], bool],
    cluster_direct_detection_candidate_tasks_fn: Callable[[list[dict]], list[dict]],
) -> dict:
    seen_keys = {task_buffer_key_fn(t) for t in active_tasks}
    seen_keys |= {task_buffer_key_fn(t) for t in completed_tasks}
    seen_keys |= set(consumed_task_keys)
    active_load = {rid: 0 for rid in robot_ids}
    active_patrol_load = {rid: 0 for rid in robot_ids}
    active_model_det_load = {rid: 0 for rid in robot_ids}
    for tr in active_tasks:
        if str(tr.get("state", "")).strip().lower() != "active":
            continue
        ridp = tr.get("assigned_primary")
        if ridp not in active_load:
            continue
        active_load[ridp] += 1
        if str(tr.get("type", "")).strip().lower() == "patrolling":
            active_patrol_load[ridp] += 1
        if (
            str(tr.get("type", "")).strip().lower() == "deterring"
            and tr.get("mode") not in (None, "", "none")
        ):
            active_model_det_load[ridp] += 1

    candidate_tasks = []
    recent_rows = taskgen.rows()[-200:]
    for task in recent_rows:
        if (not np.isfinite(task.get("x", float("nan")))) or (not np.isfinite(task.get("y", float("nan")))):
            continue
        key = task_buffer_key_fn(task)
        if key in seen_keys:
            continue
        row = dict(task)
        if is_direct_detection_task_fn(row):
            row["last_detection_t"] = float(row.get("last_detection_t", row.get("time", now_t)))
            row["merged_detection_count"] = int(row.get("merged_detection_count", 1))
            row["cluster_refresh_count"] = int(row.get("cluster_refresh_count", 0))
        candidate_tasks.append(row)
    candidate_tasks = cluster_direct_detection_candidate_tasks_fn(candidate_tasks)

    return {
        "candidate_tasks": candidate_tasks,
        "recent_rows": recent_rows,
        "seen_keys": seen_keys,
        "active_load": active_load,
        "active_patrol_load": active_patrol_load,
        "active_model_det_load": active_model_det_load,
    }


def extract_task_candidates_from_sestpp(
    *,
    estimation_kwargs: dict[str, Any],
    buffer_kwargs: dict[str, Any],
) -> dict:
    """Run SESTPP-driven task extraction, then materialize the extracted candidate buffer."""
    run_task_location_estimation(**dict(estimation_kwargs))
    return build_task_dispatch_candidate_buffer(**dict(buffer_kwargs))
