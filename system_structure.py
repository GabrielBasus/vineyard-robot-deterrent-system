from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional, Tuple


PRODUCTION_CONFIG_SECTIONS: Dict[str, tuple[str, ...]] = {
    "field_timing": ("W", "H", "seed", "dt", "T_end", "fps"),
    "fleet": ("Nrobots", "uav_fraction"),
    "zone_partitioning": ("mode", "scale", "gamma", "health_threshold", "debug_zone_areas"),
    "model": ("NX", "NY", "sigma", "omega", "omega_inhib", "alpha_inhib", "mu_base", "bg_ema"),
    "detection": (
        "detect_rate_per_robot",
        "detect_sigma_m",
        "bird_stay_mean_s",
        "bird_detection_prob",
        "per_robot_cooldown_s",
        "max_detections_per_step",
        "detect_range_m",
    ),
    "task_generation": (
        "task_replan_period_s",
        "arrival_radius_m",
        "hold_time_s",
        "deterring_suppress_radius_m",
        "deterring_suppress_window_s",
        "task_refresh_min_score",
        "task_max_age_s",
        "enable_direct_detection_task_clustering",
        "direct_detection_task_cluster_radius_m",
        "direct_detection_task_cluster_window_s",
        "direct_detection_task_active_refresh_radius_m",
        "direct_detection_task_active_refresh_window_s",
        "direct_detection_task_active_refresh_require_assigned",
        "direct_detection_task_active_refresh_max_eta_s",
        "direct_detection_task_queued_cluster_radius_m",
        "direct_detection_task_queued_cluster_window_s",
        "patrol_hotspot_filter_mode",
        "patrol_hotspot_score_percentile",
        "patrol_hotspot_keep_top_k",
        "patrol_feedback_inhibition_retention",
    ),
    "task_priority": (
        "w_prio",
        "prio_deterring",
        "prio_patrolling",
        "assigner_w_load",
        "enable_assignment_task_value_term",
        "assigner_w_task_value",
        "planner_profile",
    ),
    "calibration": (
        "use_frozen_calibration",
        "calibration_ranking_path",
        "calibration_manifest_path",
        "calibration_config_id",
        "selected_calibration_config_id",
        "selected_calibration_source",
        "selected_calibration_summary_metrics",
    ),
    "gating": (
        "preventive_policy",
        "preventive_policy_source",
        "selective_preventive_enabled",
        "model_deterring_window_s",
        "model_deterring_risk_threshold",
        "model_deterring_risk_scale",
        "model_deterring_min_recent_points",
        "model_deterring_field_threshold",
        "model_deterring_min_persistence_replans",
        "model_deterring_persistence_max_gap_s",
        "model_deterring_score_margin",
        "model_deterring_repeat_block_window_s",
        "model_deterring_repeat_block_radius_m",
        "model_deterring_max_eta_s",
        "model_deterring_busy_min_support_override",
        "model_deterring_busy_risk_override",
        "model_deterring_budget_per_robot_per_hr",
        "enable_predicted_deltaJ_gate",
        "min_predicted_deltaJ_for_model_deterring",
        "model_deterring_gate_policy",
        "model_deterring_sprt_alpha",
        "model_deterring_sprt_beta",
        "model_deterring_sprt_patch_radius_m",
        "model_deterring_min_sprt_margin",
        "model_deterring_chance_threshold",
        "model_deterring_min_deltaJ_per_cost",
        "model_deterring_min_selection_weight",
        "model_deterring_capacity_rho_max",
        "model_deterring_capacity_history_window_s",
        "model_deterring_capacity_min_completed_tasks",
        "model_deterring_capacity_fallback_budget_per_hr",
        "model_deterring_budget_mode",
        "model_deterring_budget_utility_per_robot_per_hr",
        "model_deterring_global_admission_cap_per_cycle",
        "model_deterring_require_idle_robot_for_admission",
        "model_deterring_prefer_idle_robots_for_assignment",
        "model_deterring_busy_fallback_p_event_min",
        "model_deterring_busy_fallback_deltaJ_per_cost_min",
        "model_deterring_busy_fallback_eta_s_max",
        "protect_direct_detection_from_model_deterring",
        "model_deterring_direct_conflict_radius_m",
        "model_deterring_direct_conflict_window_s",
        "protect_active_model_deterring_persistence",
        "model_deterring_min_persistence_lifetime_s",
        "model_deterring_persistence_eta_multiplier",
        "model_deterring_persistence_buffer_s",
        "model_deterring_max_persistence_lifetime_s",
        "model_deterring_lock_near_goal_radius_m",
        "protect_active_model_deterring_goal_preemption",
        "enable_model_scored_deterring",
        "auto_enable_proposed_preventive_window",
        "default_proposed_model_deterring_window_s",
    ),
    "planner": (
        "max_active_tasks_per_robot",
        "max_active_patrolling_per_robot",
        "max_active_model_deterring_per_robot",
        "preempt_deterring_goals",
        "preempt_direct_detection_goals",
        "preempt_model_scored_goals",
        "protect_locked_model_deterring_from_patrol_assignment",
        "use_live_robot_pose_for_task_planning",
    ),
    "baseline": (
        "simulation_mode",
        "enable_patrolling",
        "enable_intervention_feedback",
        "include_fallback_patrol",
        "enable_winner_profile",
    ),
    "ground_truth": (
        "use_ground_truth",
        "mu_true",
        "alpha_true",
        "omega_true",
        "sigma_true",
        "beta_true",
        "use_mode_dependent_truth_suppression",
        "warmup_s",
    ),
    "forecast": (
        "forecast_horizon_s",
        "forecast_match_radius_m",
        "forecast_top_k",
        "forecast_eval_period_s",
        "event_viz_window_s",
        "telemetry_dir",
        "telemetry_clear_on_start",
        "telemetry_prompt_save",
    ),
    "metrics": (
        "response_match_radius_m",
        "deterring_eval_radius_m",
        "deterring_eval_window_s",
        "ugv_energy_per_m",
        "uav_energy_per_m",
        "bytes_per_boundary_msg",
        "bytes_per_intervention_msg",
        "intervention_boundary_min_interval_s",
        "intervention_boundary_spatial_quant_m",
        "intervention_boundary_min_weight",
        "report_metrics_end",
        "emit_rejected_model_det_debug",
    ),
    "motion": (
        "motion_orchestration_mode",
        "row_spacing_m",
        "row_width_m",
        "row_gain",
        "edge_gain",
        "edge_scale_m",
        "headland_m",
        "lane_eps_m",
        "headland_space_m",
        "turn_space_m",
        "row_block_len_m",
        "row_block_gap_m",
        "debug_movement",
    ),
    "idle_behavior": ("idle_roam_enabled", "idle_roam_interval_s", "idle_roam_jitter_m"),
}


@dataclass(frozen=True)
class ProductionSystemConfig:
    field_timing: Dict[str, Any]
    fleet: Dict[str, Any]
    zone_partitioning: Dict[str, Any]
    model: Dict[str, Any]
    detection: Dict[str, Any]
    task_generation: Dict[str, Any]
    task_priority: Dict[str, Any]
    calibration: Dict[str, Any]
    gating: Dict[str, Any]
    planner: Dict[str, Any]
    baseline: Dict[str, Any]
    ground_truth: Dict[str, Any]
    forecast: Dict[str, Any]
    metrics: Dict[str, Any]
    motion: Dict[str, Any]
    idle_behavior: Dict[str, Any]
    deterring_modes: Dict[str, Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProductionRuntimeSnapshot:
    sim_time_s: float
    fleet: Dict[str, Any]
    tasks: Dict[str, Any]
    perception: Dict[str, Any]
    communication: Dict[str, Any]
    outputs: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TaskGenerationStageResult:
    now_t: float
    patrolling_enabled: bool
    busy_deterring_robots: list[str]
    candidate_tasks: list[dict]
    source_buffer_size: int
    seen_task_key_count: int
    active_load_before_dispatch: Dict[str, int]
    active_patrol_load_before_dispatch: Dict[str, int]
    active_model_det_load_before_dispatch: Dict[str, int]
    diag_counts: Dict[str, Any]

    def to_public_dict(self, preview_limit: int = 25) -> Dict[str, Any]:
        preview = []
        for task in self.candidate_tasks[: max(int(preview_limit), 0)]:
            preview.append(
                {
                    "type": task.get("type"),
                    "origin": task.get("origin"),
                    "mode": task.get("mode"),
                    "robot_id": task.get("robot_id"),
                    "x": task.get("x"),
                    "y": task.get("y"),
                    "time": task.get("time"),
                    "score": task.get("score"),
                    "utility": task.get("utility"),
                    "predicted_deltaJ": task.get("predicted_deltaJ"),
                    "p_event": task.get("p_event"),
                    "deltaJ_per_cost": task.get("deltaJ_per_cost"),
                    "llr": task.get("llr"),
                    "selection_weight": task.get("selection_weight"),
                }
            )
        return {
            "now_t": float(self.now_t),
            "patrolling_enabled": bool(self.patrolling_enabled),
            "busy_deterring_robots": list(self.busy_deterring_robots),
            "candidate_count": int(len(self.candidate_tasks)),
            "candidate_preview": preview,
            "source_buffer_size": int(self.source_buffer_size),
            "seen_task_key_count": int(self.seen_task_key_count),
            "active_load_before_dispatch": dict(self.active_load_before_dispatch),
            "active_patrol_load_before_dispatch": dict(self.active_patrol_load_before_dispatch),
            "active_model_det_load_before_dispatch": dict(self.active_model_det_load_before_dispatch),
            "diag_counts": dict(self.diag_counts),
        }


@dataclass
class DispatchStageResult:
    now_t: float
    candidate_count: int
    accepted_tasks: list[dict]
    rejected_counts: Dict[str, int]
    rejected_model_det_tasks: list[dict]
    ordering_policy: str
    ordered_candidate_preview: list[dict]
    replaced_patrol_count: int
    active_load_after_dispatch: Dict[str, int]
    active_patrol_load_after_dispatch: Dict[str, int]
    active_model_det_load_after_dispatch: Dict[str, int]
    model_deterring_accepted_total: int
    model_deterring_rejected_budget_total: int

    def to_public_dict(self, preview_limit: int = 25) -> Dict[str, Any]:
        preview = []
        for task in self.accepted_tasks[: max(int(preview_limit), 0)]:
            preview.append(
                {
                    "id": task.get("id"),
                    "type": task.get("type"),
                    "origin": task.get("origin"),
                    "mode": task.get("mode"),
                    "assigned_primary": task.get("assigned_primary"),
                    "assigned_secondary": task.get("assigned_secondary"),
                    "score": task.get("score"),
                    "utility": task.get("utility"),
                }
            )
        return {
            "now_t": float(self.now_t),
            "candidate_count": int(self.candidate_count),
            "accepted_count": int(len(self.accepted_tasks)),
            "accepted_preview": preview,
            "rejected_counts": dict(self.rejected_counts),
            "rejected_model_det_count": int(len(self.rejected_model_det_tasks)),
            "rejected_model_det_tasks": list(self.rejected_model_det_tasks),
            "ordering_policy": str(self.ordering_policy),
            "ordered_candidate_preview": list(self.ordered_candidate_preview),
            "replaced_patrol_count": int(self.replaced_patrol_count),
            "active_load_after_dispatch": dict(self.active_load_after_dispatch),
            "active_patrol_load_after_dispatch": dict(self.active_patrol_load_after_dispatch),
            "active_model_det_load_after_dispatch": dict(self.active_model_det_load_after_dispatch),
            "model_deterring_accepted_total": int(self.model_deterring_accepted_total),
            "model_deterring_rejected_budget_total": int(self.model_deterring_rejected_budget_total),
        }


@dataclass
class MotionCommand:
    robot_id: str
    command_type: str
    source: str
    assigned_task_id: Optional[int]
    assigned_task_type: Optional[str]
    assigned_task_mode: Optional[str]
    goal: Optional[Tuple[float, float]]
    effective_goal: Optional[Tuple[float, float]]
    current_pose: Tuple[float, float]

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "robot_id": str(self.robot_id),
            "command_type": str(self.command_type),
            "source": str(self.source),
            "assigned_task_id": (None if self.assigned_task_id is None else int(self.assigned_task_id)),
            "assigned_task_type": (None if self.assigned_task_type is None else str(self.assigned_task_type)),
            "assigned_task_mode": (None if self.assigned_task_mode is None else str(self.assigned_task_mode)),
            "goal": (None if self.goal is None else (float(self.goal[0]), float(self.goal[1]))),
            "effective_goal": (
                None if self.effective_goal is None else (float(self.effective_goal[0]), float(self.effective_goal[1]))
            ),
            "current_pose": (float(self.current_pose[0]), float(self.current_pose[1])),
        }


@dataclass
class MotionExecutionStageResult:
    now_t: float
    motion_orchestration_mode: str
    motion_execution_backend: str
    external_feedback_applied: bool
    external_pose_updates_this_step: int
    robot_states: Dict[str, str]
    commands: list[MotionCommand]
    moving_distance_by_robot_step: Dict[str, float]
    goals_active_count: int
    completed_patrolling_this_step: int
    completed_deterring_this_step: int
    stale_goal_clears_this_step: int
    holding_robot_count: int
    moving_robot_count: int
    idle_robot_count: int

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "now_t": float(self.now_t),
            "motion_orchestration_mode": str(self.motion_orchestration_mode),
            "motion_execution_backend": str(self.motion_execution_backend),
            "external_feedback_applied": bool(self.external_feedback_applied),
            "external_pose_updates_this_step": int(self.external_pose_updates_this_step),
            "robot_states": dict(self.robot_states),
            "command_count": int(len(self.commands)),
            "commands": [cmd.to_public_dict() for cmd in self.commands],
            "moving_distance_by_robot_step": dict(self.moving_distance_by_robot_step),
            "goals_active_count": int(self.goals_active_count),
            "completed_patrolling_this_step": int(self.completed_patrolling_this_step),
            "completed_deterring_this_step": int(self.completed_deterring_this_step),
            "stale_goal_clears_this_step": int(self.stale_goal_clears_this_step),
            "holding_robot_count": int(self.holding_robot_count),
            "moving_robot_count": int(self.moving_robot_count),
            "idle_robot_count": int(self.idle_robot_count),
        }


@dataclass
class FeedbackCommunicationStageResult:
    now_t: float
    recent_deterrence_events_added_this_step: int
    intervention_feedback_applied_this_step: int
    boundary_messages_sent_this_step: int
    intervention_messages_sent_this_step: int
    boundary_bytes_sent_this_step: int
    intervention_bytes_sent_this_step: int
    intervention_msg_dropped_debounce_this_step: int
    intervention_msg_dropped_low_weight_this_step: int
    truth_suppressed_events_total: int
    truth_accepted_events_total: int

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "now_t": float(self.now_t),
            "recent_deterrence_events_added_this_step": int(self.recent_deterrence_events_added_this_step),
            "intervention_feedback_applied_this_step": int(self.intervention_feedback_applied_this_step),
            "boundary_messages_sent_this_step": int(self.boundary_messages_sent_this_step),
            "intervention_messages_sent_this_step": int(self.intervention_messages_sent_this_step),
            "boundary_bytes_sent_this_step": int(self.boundary_bytes_sent_this_step),
            "intervention_bytes_sent_this_step": int(self.intervention_bytes_sent_this_step),
            "intervention_msg_dropped_debounce_this_step": int(self.intervention_msg_dropped_debounce_this_step),
            "intervention_msg_dropped_low_weight_this_step": int(self.intervention_msg_dropped_low_weight_this_step),
            "truth_suppressed_events_total": int(self.truth_suppressed_events_total),
            "truth_accepted_events_total": int(self.truth_accepted_events_total),
        }


@dataclass
class MetricsStageResult:
    now_t: float
    value_weighted_exposure: float
    mean_response_time_s: float
    completed_tasks_total: int
    boundary_message_count: int
    boundary_bytes_sent: int
    fleet_task_engagement_fraction_so_far: float
    fleet_moving_fraction_so_far: float
    fleet_idle_no_task_fraction_so_far: float
    truth_suppression_rate: float
    forecast_recall_at_k: float
    forecast_precision_at_k: float

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "now_t": float(self.now_t),
            "value_weighted_exposure": float(self.value_weighted_exposure),
            "mean_response_time_s": float(self.mean_response_time_s),
            "completed_tasks_total": int(self.completed_tasks_total),
            "boundary_message_count": int(self.boundary_message_count),
            "boundary_bytes_sent": int(self.boundary_bytes_sent),
            "fleet_task_engagement_fraction_so_far": float(self.fleet_task_engagement_fraction_so_far),
            "fleet_moving_fraction_so_far": float(self.fleet_moving_fraction_so_far),
            "fleet_idle_no_task_fraction_so_far": float(self.fleet_idle_no_task_fraction_so_far),
            "truth_suppression_rate": float(self.truth_suppression_rate),
            "forecast_recall_at_k": float(self.forecast_recall_at_k),
            "forecast_precision_at_k": float(self.forecast_precision_at_k),
        }


@dataclass
class TruthEventStageResult:
    now_t: float
    use_ground_truth: bool
    truth_events_added_this_step: int
    detections_added_this_step: int
    truth_candidate_events_this_step: int
    truth_accepted_events_this_step: int
    truth_suppressed_events_this_step: int
    truth_candidate_events_total: int
    truth_accepted_events_total: int
    truth_suppressed_events_total: int
    suppression_effect_sum_total: float

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "now_t": float(self.now_t),
            "use_ground_truth": bool(self.use_ground_truth),
            "truth_events_added_this_step": int(self.truth_events_added_this_step),
            "detections_added_this_step": int(self.detections_added_this_step),
            "truth_candidate_events_this_step": int(self.truth_candidate_events_this_step),
            "truth_accepted_events_this_step": int(self.truth_accepted_events_this_step),
            "truth_suppressed_events_this_step": int(self.truth_suppressed_events_this_step),
            "truth_candidate_events_total": int(self.truth_candidate_events_total),
            "truth_accepted_events_total": int(self.truth_accepted_events_total),
            "truth_suppressed_events_total": int(self.truth_suppressed_events_total),
            "suppression_effect_sum_total": float(self.suppression_effect_sum_total),
        }


@dataclass
class ForecastModelStageResult:
    now_t: float
    model_advance_dt_s: float
    lam_mean_mean: float
    lam_max_max: float
    trigger_sum_total: float
    inhib_sum_total: float
    forecast_eval_ran_this_step: bool
    forecast_future_event_count: int
    forecast_hotspot_count: int
    forecast_hit_count: int
    forecast_covered_event_count: int
    forecast_recall_latest: float
    forecast_precision_latest: float
    forecast_samples_total: int

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "now_t": float(self.now_t),
            "model_advance_dt_s": float(self.model_advance_dt_s),
            "lam_mean_mean": float(self.lam_mean_mean),
            "lam_max_max": float(self.lam_max_max),
            "trigger_sum_total": float(self.trigger_sum_total),
            "inhib_sum_total": float(self.inhib_sum_total),
            "forecast_eval_ran_this_step": bool(self.forecast_eval_ran_this_step),
            "forecast_future_event_count": int(self.forecast_future_event_count),
            "forecast_hotspot_count": int(self.forecast_hotspot_count),
            "forecast_hit_count": int(self.forecast_hit_count),
            "forecast_covered_event_count": int(self.forecast_covered_event_count),
            "forecast_recall_latest": float(self.forecast_recall_latest),
            "forecast_precision_latest": float(self.forecast_precision_latest),
            "forecast_samples_total": int(self.forecast_samples_total),
        }


@dataclass
class TelemetryStageResult:
    now_t: float
    telemetry_enabled: bool
    robot_pose_updates_this_step: int
    robot_diag_updates_this_step: int
    hotspot_exports_this_step: int
    flush_called_this_step: bool
    telemetry_dir: str

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "now_t": float(self.now_t),
            "telemetry_enabled": bool(self.telemetry_enabled),
            "robot_pose_updates_this_step": int(self.robot_pose_updates_this_step),
            "robot_diag_updates_this_step": int(self.robot_diag_updates_this_step),
            "hotspot_exports_this_step": int(self.hotspot_exports_this_step),
            "flush_called_this_step": bool(self.flush_called_this_step),
            "telemetry_dir": str(self.telemetry_dir),
        }


def _pick(params: Mapping[str, Any], names: tuple[str, ...]) -> Dict[str, Any]:
    return {name: params.get(name) for name in names}


def build_production_system_config(
    resolved_params: Mapping[str, Any],
    *,
    deterring_modes: Mapping[str, Mapping[str, Any]],
) -> ProductionSystemConfig:
    sections = {section: _pick(resolved_params, fields) for section, fields in PRODUCTION_CONFIG_SECTIONS.items()}
    return ProductionSystemConfig(
        field_timing=sections["field_timing"],
        fleet=sections["fleet"],
        zone_partitioning=sections["zone_partitioning"],
        model=sections["model"],
        detection=sections["detection"],
        task_generation=sections["task_generation"],
        task_priority=sections["task_priority"],
        calibration=sections["calibration"],
        gating=sections["gating"],
        planner=sections["planner"],
        baseline=sections["baseline"],
        ground_truth=sections["ground_truth"],
        forecast=sections["forecast"],
        metrics=sections["metrics"],
        motion=sections["motion"],
        idle_behavior=sections["idle_behavior"],
        deterring_modes={str(k): dict(v) for k, v in deterring_modes.items()},
    )


def build_production_runtime_snapshot(
    *,
    sim_time_s: float,
    poses: Mapping[str, Tuple[float, float]],
    goals: Mapping[str, Optional[Tuple[float, float]]],
    robot_states: Mapping[str, Any],
    active_tasks: list[dict],
    completed_tasks: list[dict],
    truth_pts_count: int,
    det_pts_count: int,
    boundary_message_count: int,
    boundary_bytes_sent: int,
    metrics_compact: Mapping[str, Any],
) -> ProductionRuntimeSnapshot:
    active_patrolling = 0
    active_deterring_direct = 0
    active_deterring_model_scored = 0
    for task in active_tasks:
        if str(task.get("state", "")).strip().lower() != "active":
            continue
        task_type = str(task.get("type", "")).strip().lower()
        if task_type == "patrolling":
            active_patrolling += 1
        elif task_type == "deterring":
            if task.get("mode") in (None, "", "none"):
                active_deterring_direct += 1
            else:
                active_deterring_model_scored += 1

    return ProductionRuntimeSnapshot(
        sim_time_s=float(sim_time_s),
        fleet={
            "robot_count": int(len(poses)),
            "poses": {str(rid): (float(x), float(y)) for rid, (x, y) in poses.items()},
            "goals": {
                str(rid): (None if goal is None else (float(goal[0]), float(goal[1])))
                for rid, goal in goals.items()
            },
            "robot_states": {str(rid): str(state) for rid, state in robot_states.items()},
        },
        tasks={
            "active_total": int(sum(1 for task in active_tasks if str(task.get("state", "")).strip().lower() == "active")),
            "active_patrolling": int(active_patrolling),
            "active_deterring_direct": int(active_deterring_direct),
            "active_deterring_model_scored": int(active_deterring_model_scored),
            "completed_total": int(len(completed_tasks)),
        },
        perception={
            "truth_event_count": int(truth_pts_count),
            "detection_event_count": int(det_pts_count),
        },
        communication={
            "boundary_message_count": int(boundary_message_count),
            "boundary_bytes_sent": int(boundary_bytes_sent),
        },
        outputs={
            "metrics_compact": dict(metrics_compact),
        },
    )
