from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Mapping, MutableMapping, MutableSequence, Sequence

import numpy as np

from system_structure import ForecastModelStageResult, MotionCommand, TelemetryStageResult, TruthEventStageResult


@dataclass(frozen=True)
class ForecastEvaluationStep:
    forecast_last_eval_t: float
    forecast_eval_ran: bool
    future_event_count: int
    hotspot_count: int
    hit_count: int
    covered_event_count: int
    recall_latest: float
    precision_latest: float


@dataclass(frozen=True)
class TelemetryExecutionStep:
    robot_pose_updates: int
    robot_diag_updates: int
    hotspot_exports: int
    flush_called: bool


@dataclass(frozen=True)
class TruthGenerationCounters:
    truth_candidate_events: int
    truth_accepted_events: int
    truth_suppressed_events: int
    suppression_effect_sum: float


@dataclass(frozen=True)
class MotionFeedbackStep:
    applied: bool
    updated_robot_count: int


def build_motion_command(
    *,
    robot_id: str,
    pose: tuple[float, float],
    goal: tuple[float, float] | None,
    effective_goal: tuple[float, float] | None,
    command_type: str,
    source: str,
    assigned_task: Mapping[str, Any] | None,
) -> MotionCommand:
    return MotionCommand(
        robot_id=str(robot_id),
        command_type=str(command_type),
        source=str(source),
        assigned_task_id=(None if not assigned_task else int(assigned_task.get("id"))),
        assigned_task_type=(None if not assigned_task else str(assigned_task.get("type"))),
        assigned_task_mode=(None if not assigned_task or assigned_task.get("mode") in (None, "") else str(assigned_task.get("mode"))),
        goal=(None if goal is None else (float(goal[0]), float(goal[1]))),
        effective_goal=(None if effective_goal is None else (float(effective_goal[0]), float(effective_goal[1]))),
        current_pose=(float(pose[0]), float(pose[1])),
    )


def run_forecast_evaluation_stage(
    *,
    use_ground_truth: bool,
    now_t: float,
    forecast_last_eval_t: float,
    forecast_eval_period_s: float,
    forecast_horizon_s: float,
    forecast_top_k: int,
    forecast_match_radius_m: float,
    future_truth_events_fn: Callable[[float, float], Sequence[tuple[float, float, float]]],
    global_hotspots_fn: Callable[[int], Sequence[tuple[float, float, float]]],
    forecast_recall_vals: MutableSequence[float],
    forecast_precision_vals: MutableSequence[float],
    forecast_hit_flags: MutableSequence[float],
    forecast_lead_times: MutableSequence[float],
) -> tuple[float, ForecastEvaluationStep]:
    if not use_ground_truth or ((now_t - forecast_last_eval_t) < float(forecast_eval_period_s)):
        return float(forecast_last_eval_t), ForecastEvaluationStep(
            forecast_last_eval_t=float(forecast_last_eval_t),
            forecast_eval_ran=False,
            future_event_count=0,
            hotspot_count=0,
            hit_count=0,
            covered_event_count=0,
            recall_latest=float("nan"),
            precision_latest=float("nan"),
        )

    forecast_last_eval_t = float(now_t)
    fut = list(future_truth_events_fn(now_t, float(forecast_horizon_s)))
    hs = list(global_hotspots_fn(int(forecast_top_k)))
    future_event_count = int(len(fut))
    hotspot_count = int(len(hs))
    covered_event_count = 0
    hit_count = 0
    recall_latest = float("nan")
    precision_latest = float("nan")
    radius_sq = float(forecast_match_radius_m) ** 2

    if fut:
        covered = 0
        for ex, ey, _tt in fut:
            if hs and any(((ex - hx) ** 2 + (ey - hy) ** 2 <= radius_sq) for hx, hy, _s in hs):
                covered += 1
        covered_event_count = int(covered)
        recall_latest = float(covered) / float(max(len(fut), 1))
        forecast_recall_vals.append(recall_latest)

    if hs:
        horizon_end_t = float(now_t) + float(forecast_horizon_s)
        for hx, hy, _s in hs:
            hit_t = None
            for ex, ey, event_t in fut:
                if event_t <= now_t or event_t > horizon_end_t:
                    continue
                if ((ex - hx) ** 2 + (ey - hy) ** 2) <= radius_sq:
                    if hit_t is None or event_t < hit_t:
                        hit_t = event_t
            if hit_t is not None:
                hit_count += 1
                forecast_hit_flags.append(1.0)
                forecast_lead_times.append(float(hit_t - now_t))
            else:
                forecast_hit_flags.append(0.0)
        precision_latest = float(hit_count) / float(max(len(hs), 1))
        forecast_precision_vals.append(precision_latest)

    return forecast_last_eval_t, ForecastEvaluationStep(
        forecast_last_eval_t=float(forecast_last_eval_t),
        forecast_eval_ran=True,
        future_event_count=future_event_count,
        hotspot_count=hotspot_count,
        hit_count=int(hit_count),
        covered_event_count=covered_event_count,
        recall_latest=recall_latest,
        precision_latest=precision_latest,
    )


def run_truth_generation_stage(
    *,
    use_ground_truth: bool,
    now_t: float,
    dt: float,
    rng: Any,
    W: float,
    H: float,
    w_cdf: Any,
    w_shape: Any,
    mu_true: float,
    sample_from_value_map_fn: Callable[[Any], tuple[float, float]],
    suppression_eval_fn: Callable[[float, float, float], tuple[float, float, Mapping[str, float], Mapping[str, float]]],
    process_truth_event_fn: Callable[[float, float, float], None],
    spawn_offspring_fn: Callable[[float, float, float], None],
    truth_queue: MutableSequence[tuple[float, float, float]],
    suppression_effect_by_mode: dict[str, float],
    suppression_effect_by_source: dict[str, float],
    truth_candidate_events: int,
    truth_accepted_events: int,
    truth_suppressed_events: int,
    suppression_effect_sum: float,
    robots_def: Sequence[Mapping[str, Any]],
    pose: Mapping[str, tuple[float, float]],
    bird_present_until: MutableMapping[str, float],
    last_detection_time: MutableMapping[str, float],
    detect_rate_per_robot: float,
    bird_stay_mean_s: float,
    bird_detection_prob: float,
    per_robot_cooldown_s: float,
    max_detections_per_step: int,
    detect_sigma_m: float,
    id_to_cell: Mapping[str, Sequence[tuple[float, float]]],
    point_in_polygon_fn: Callable[[float, float, Sequence[tuple[float, float]]], bool],
    robots: Mapping[str, Any],
    bus: Any,
    taskgen: Any,
    pending_event_onsets: MutableSequence[dict],
    mon: Any,
) -> TruthGenerationCounters:
    if use_ground_truth:
        if w_cdf is not None:
            area = float(W * H)
            w_mean = float(w_shape[4].mean()) if w_shape is not None else 1.0
            lam_base = mu_true * w_mean * area
            n_base = rng.poisson(lam_base * dt)
            for _ in range(int(n_base)):
                x, y = sample_from_value_map_fn(rng)
                p_keep, p_suppress, p_by_mode, p_by_source = suppression_eval_fn(x, y, now_t)
                truth_candidate_events += 1
                suppression_effect_sum += float(p_suppress)
                for mode_key, mode_value in p_by_mode.items():
                    suppression_effect_by_mode[mode_key] = float(suppression_effect_by_mode.get(mode_key, 0.0) + mode_value)
                for source_key, source_value in p_by_source.items():
                    suppression_effect_by_source[source_key] = float(
                        suppression_effect_by_source.get(source_key, 0.0) + source_value
                    )
                if rng.random() <= p_keep:
                    truth_accepted_events += 1
                    process_truth_event_fn(x, y, now_t)
                    spawn_offspring_fn(x, y, now_t)
                else:
                    truth_suppressed_events += 1

        if truth_queue:
            due: list[tuple[float, float, float]] = []
            future: list[tuple[float, float, float]] = []
            for event in truth_queue:
                x, y, event_t = event
                if event_t <= now_t:
                    due.append((x, y, event_t))
                else:
                    future.append((x, y, event_t))
            truth_queue[:] = future
            for x, y, event_t in due:
                p_keep, p_suppress, p_by_mode, p_by_source = suppression_eval_fn(x, y, event_t)
                truth_candidate_events += 1
                suppression_effect_sum += float(p_suppress)
                for mode_key, mode_value in p_by_mode.items():
                    suppression_effect_by_mode[mode_key] = float(suppression_effect_by_mode.get(mode_key, 0.0) + mode_value)
                for source_key, source_value in p_by_source.items():
                    suppression_effect_by_source[source_key] = float(
                        suppression_effect_by_source.get(source_key, 0.0) + source_value
                    )
                if rng.random() <= p_keep:
                    truth_accepted_events += 1
                    process_truth_event_fn(x, y, event_t)
                    spawn_offspring_fn(x, y, event_t)
                else:
                    truth_suppressed_events += 1
    else:
        for robot in robots_def:
            robot_id = robot["id"]
            if now_t >= bird_present_until[robot_id]:
                if rng.random() < (1.0 - np.exp(-detect_rate_per_robot * dt)):
                    bird_present_until[robot_id] = now_t + rng.exponential(bird_stay_mean_s)

            generated = 0
            if now_t < bird_present_until[robot_id]:
                if rng.random() < bird_detection_prob:
                    if (now_t - last_detection_time[robot_id]) >= per_robot_cooldown_s and generated < max_detections_per_step:
                        cx, cy = pose[robot_id]
                        x = float(np.clip(cx + rng.normal(0.0, detect_sigma_m), 0.0, W))
                        y = float(np.clip(cy + rng.normal(0.0, detect_sigma_m), 0.0, H))

                        owner = None
                        for zone_robot in robots_def:
                            zone_robot_id = zone_robot["id"]
                            zone_polygon = id_to_cell.get(zone_robot_id, [])
                            if zone_polygon and point_in_polygon_fn(x, y, zone_polygon):
                                owner = zone_robot_id
                                break

                        if owner is not None:
                            boundary_events = robots[owner].ingest_detection(x, y, now_t)
                            bus.send_boundary_events(boundary_events, source_id=owner)
                            taskgen.on_detection(owner, x, y, now_t)
                            pending_event_onsets.append(
                                {"x": float(x), "y": float(y), "t": float(now_t), "responded": False}
                            )
                            if mon is not None and getattr(mon, "enabled", False):
                                mon.message(now_t, kind="detection", source=owner, target=owner, data={"x": x, "y": y})
                            last_detection_time[robot_id] = now_t
                            generated += 1

    return TruthGenerationCounters(
        truth_candidate_events=int(truth_candidate_events),
        truth_accepted_events=int(truth_accepted_events),
        truth_suppressed_events=int(truth_suppressed_events),
        suppression_effect_sum=float(suppression_effect_sum),
    )


def run_telemetry_stage(
    *,
    mon: Any,
    telemetry_dir: str,
    now_t: float,
    robots: Mapping[str, Any],
    active_tasks: Sequence[dict],
    pose: Mapping[str, tuple[float, float]],
    loiter_until: Mapping[str, float],
    goal: Mapping[str, Any],
    profiles: Mapping[str, Any],
    sigma: float,
    effective_goal_fn: Callable[[str, tuple[float, float]], tuple[float, float]],
    lane_center_for_fn: Callable[[float], float],
    is_at_headland_fn: Callable[[float], bool],
) -> TelemetryExecutionStep:
    if mon is None or not getattr(mon, "enabled", False):
        return TelemetryExecutionStep(
            robot_pose_updates=0,
            robot_diag_updates=0,
            hotspot_exports=0,
            flush_called=False,
        )

    pose_updates = 0
    diag_updates = 0
    hotspot_exports = 0
    active_by_robot: dict[str, str] = {}
    for task in active_tasks:
        if task.get("state") != "active":
            continue
        robot_id = task.get("assigned_primary")
        if robot_id and robot_id not in active_by_robot:
            mode = task.get("mode")
            mode_txt = f"/{mode}" if mode else ""
            active_by_robot[robot_id] = f"{task.get('type', '?')}{mode_txt}#{task.get('id', '?')}"

    for robot_id in robots:
        px, py = pose[robot_id]
        mon.pose(now_t, robot_id, px, py)
        pose_updates += 1
        state = "holding" if loiter_until[robot_id] > now_t else ("moving" if goal[robot_id] is not None else "idle")
        if goal[robot_id] is None:
            goal_x = goal_y = eff_goal_x = eff_goal_y = float("nan")
            dist_to_goal = float("nan")
            lane_target = float("nan")
        else:
            goal_x, goal_y = goal[robot_id]
            eff_goal_x, eff_goal_y = effective_goal_fn(robot_id, goal[robot_id])
            dist_to_goal = float(math.hypot(px - eff_goal_x, py - eff_goal_y))
            lane_target = float(lane_center_for_fn(goal_y))
        mon.robot_diag(
            t=now_t,
            rid=robot_id,
            battery=float(profiles[robot_id].battery),
            state=state,
            task=active_by_robot.get(robot_id, "-"),
            goal_x=goal_x,
            goal_y=goal_y,
            eff_goal_x=eff_goal_x,
            eff_goal_y=eff_goal_y,
            dist_to_goal=dist_to_goal,
            lane_cur=float(lane_center_for_fn(py)),
            lane_tgt=lane_target,
            at_headland=1 if is_at_headland_fn(px) else 0,
        )
        diag_updates += 1
        try:
            hotspots = robots[robot_id].m.hotspots(
                top_k=3,
                merge_radius=max(8.0, 0.5 * sigma),
                use_excess=True,
                mask_poly=robots[robot_id].zone_polygon,
            )
            mon.hotspots(now_t, robot_id, hotspots)
            hotspot_exports += 1
        except Exception:
            pass

    mon.flush_live(telemetry_dir, min_interval_s=0.5)
    return TelemetryExecutionStep(
        robot_pose_updates=pose_updates,
        robot_diag_updates=diag_updates,
        hotspot_exports=hotspot_exports,
        flush_called=True,
    )


def publish_motion_commands(
    *,
    now_t: float,
    dt: float,
    motion_orchestration_mode: str,
    motion_command_callback: Any,
    commands: Sequence[MotionCommand],
    pose: Mapping[str, tuple[float, float]],
    goal: Mapping[str, Any],
) -> str:
    mode = str(motion_orchestration_mode).strip().lower()
    if callable(motion_command_callback):
        motion_command_callback(
            {
                "t": float(now_t),
                "dt": float(dt),
                "mode": mode,
                "commands": [cmd.to_public_dict() for cmd in commands],
                "poses": {str(rid): (float(x), float(y)) for rid, (x, y) in pose.items()},
                "goals": {
                    str(rid): (None if goal.get(rid) is None else (float(goal[rid][0]), float(goal[rid][1])))
                    for rid in goal
                },
            }
        )
    if mode == "command_only":
        return "external_command_only"
    if callable(motion_command_callback):
        return "internal_sim_with_callback"
    return "internal_sim"


def apply_external_motion_feedback(
    *,
    now_t: float,
    dt: float,
    motion_orchestration_mode: str,
    motion_state_callback: Any,
    pose: MutableMapping[str, tuple[float, float]],
    goal: Mapping[str, Any],
    active_tasks: Sequence[Mapping[str, Any]],
    W: float,
    H: float,
) -> MotionFeedbackStep:
    if not callable(motion_state_callback):
        return MotionFeedbackStep(applied=False, updated_robot_count=0)

    payload = motion_state_callback(
        {
            "t": float(now_t),
            "dt": float(dt),
            "mode": str(motion_orchestration_mode),
            "poses": {str(rid): (float(x), float(y)) for rid, (x, y) in pose.items()},
            "goals": {
                str(rid): (None if goal.get(rid) is None else (float(goal[rid][0]), float(goal[rid][1])))
                for rid in goal
            },
            "active_tasks": [
                {
                    "id": task.get("id"),
                    "type": task.get("type"),
                    "mode": task.get("mode"),
                    "assigned_primary": task.get("assigned_primary"),
                    "state": task.get("state"),
                    "x": task.get("x"),
                    "y": task.get("y"),
                }
                for task in active_tasks
            ],
        }
    )
    if not isinstance(payload, Mapping):
        return MotionFeedbackStep(applied=False, updated_robot_count=0)

    pose_updates = payload.get("poses")
    if not isinstance(pose_updates, Mapping):
        return MotionFeedbackStep(applied=False, updated_robot_count=0)

    updated_robot_count = 0
    for robot_id, xy in pose_updates.items():
        if robot_id not in pose:
            continue
        if not isinstance(xy, Sequence) or len(xy) != 2:
            continue
        try:
            x = float(xy[0])
            y = float(xy[1])
        except Exception:
            continue
        pose[robot_id] = (min(max(x, 0.0), float(W)), min(max(y, 0.0), float(H)))
        updated_robot_count += 1

    return MotionFeedbackStep(
        applied=updated_robot_count > 0,
        updated_robot_count=int(updated_robot_count),
    )


def build_truth_generation_stage_result(
    *,
    now_t: float,
    use_ground_truth: bool,
    recent_truth_count: int,
    recent_truth_before: int,
    recent_detections_count: int,
    recent_detections_before: int,
    truth_candidate_events: int,
    truth_candidate_before: int,
    truth_accepted_events: int,
    truth_accepted_before: int,
    truth_suppressed_events: int,
    truth_suppressed_before: int,
    suppression_effect_sum: float,
) -> TruthEventStageResult:
    return TruthEventStageResult(
        now_t=float(now_t),
        use_ground_truth=bool(use_ground_truth),
        truth_events_added_this_step=int(recent_truth_count - recent_truth_before),
        detections_added_this_step=int(recent_detections_count - recent_detections_before),
        truth_candidate_events_this_step=int(truth_candidate_events - truth_candidate_before),
        truth_accepted_events_this_step=int(truth_accepted_events - truth_accepted_before),
        truth_suppressed_events_this_step=int(truth_suppressed_events - truth_suppressed_before),
        truth_candidate_events_total=int(truth_candidate_events),
        truth_accepted_events_total=int(truth_accepted_events),
        truth_suppressed_events_total=int(truth_suppressed_events),
        suppression_effect_sum_total=float(suppression_effect_sum),
    )


def build_forecast_model_stage_result(
    *,
    now_t: float,
    model_advance_dt_s: float,
    model_diag: Mapping[str, Mapping[str, Any]],
    forecast_step: ForecastEvaluationStep,
    forecast_samples_total: int,
) -> ForecastModelStageResult:
    lam_mean_vals = [float(v.get("lam_mean", float("nan"))) for v in model_diag.values()]
    lam_max_vals = [float(v.get("lam_max", float("nan"))) for v in model_diag.values()]
    trigger_sum_vals = [float(v.get("trigger_sum", float("nan"))) for v in model_diag.values()]
    inhib_sum_vals = [float(v.get("inhib_sum", float("nan"))) for v in model_diag.values()]
    return ForecastModelStageResult(
        now_t=float(now_t),
        model_advance_dt_s=float(model_advance_dt_s),
        lam_mean_mean=float(np.nanmean(lam_mean_vals)) if lam_mean_vals else float("nan"),
        lam_max_max=float(np.nanmax(lam_max_vals)) if lam_max_vals else float("nan"),
        trigger_sum_total=float(np.nansum(trigger_sum_vals)) if trigger_sum_vals else float("nan"),
        inhib_sum_total=float(np.nansum(inhib_sum_vals)) if inhib_sum_vals else float("nan"),
        forecast_eval_ran_this_step=bool(forecast_step.forecast_eval_ran),
        forecast_future_event_count=int(forecast_step.future_event_count),
        forecast_hotspot_count=int(forecast_step.hotspot_count),
        forecast_hit_count=int(forecast_step.hit_count),
        forecast_covered_event_count=int(forecast_step.covered_event_count),
        forecast_recall_latest=float(forecast_step.recall_latest),
        forecast_precision_latest=float(forecast_step.precision_latest),
        forecast_samples_total=int(forecast_samples_total),
    )


def build_telemetry_stage_result(
    *,
    now_t: float,
    telemetry_enabled: bool,
    telemetry_step: TelemetryExecutionStep,
    telemetry_dir: str,
) -> TelemetryStageResult:
    return TelemetryStageResult(
        now_t=float(now_t),
        telemetry_enabled=bool(telemetry_enabled),
        robot_pose_updates_this_step=int(telemetry_step.robot_pose_updates),
        robot_diag_updates_this_step=int(telemetry_step.robot_diag_updates),
        hotspot_exports_this_step=int(telemetry_step.hotspot_exports),
        flush_called_this_step=bool(telemetry_step.flush_called),
        telemetry_dir=str(telemetry_dir),
    )
