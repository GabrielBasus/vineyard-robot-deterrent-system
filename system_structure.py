from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from action_schema import task_action_kind, task_action_name, task_action_public_dict


PRODUCTION_CONFIG_SECTIONS: Dict[str, tuple[str, ...]] = {
    "field_timing": ("W", "H", "seed", "dt", "T_end", "fps"),
    "fleet": ("Nrobots", "uav_fraction"),
    "zone_partitioning": (
        "mode",
        "scale",
        "gamma",
        "health_threshold",
        "health_retire_threshold",
        "health_recharge_time_s",
        "health_recovered_value",
        "debug_zone_areas",
    ),
    "model": (
        "NX",
        "NY",
        "sigma",
        "omega",
        "omega_inhib",
        "alpha_in",
        "alpha_cross",
        "alpha_inhib",
        "mu_base",
        "bg_ema",
        "model_feedback_sigma_scale",
        "model_feedback_omega_scale",
    ),
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
        "tau_service_s",
        "enable_predictive_patrol_tasks",
        "predictive_planning_topology",
        "enable_predictive_lead_time",
        "predictive_timing_mode",
        "predictive_lead_time_min_s",
        "predictive_lead_time_max_eta_s",
        "predictive_lead_time_buffer_s",
        "predictive_lead_time_risk_power",
        "predictive_expiry_grace_s",
        "deterring_suppress_radius_m",
        "deterring_suppress_window_s",
        "task_refresh_min_score",
        "task_max_age_s",
        "enable_direct_detection_task_clustering",
        "enable_direct_detection_tasks",
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
        "patrol_scoring_mode",
        "patrol_shared_detection_range_m",
        "patrol_shared_detection_prob_per_step",
        "patrol_shared_detection_dwell_s",
        "patrol_shared_followup_success_prob",
        "patrol_shared_response_eta_decay_s",
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
        "use_split_task_extraction_selection_pipeline",
        "preassignment_selection_policy",
        "preassignment_selection_limit",
        "dispatch_policy",
        "reservation_fraction",
        "reservation_window_s",
        "reactive_override_slack_s",
        "reservation_softening_alpha",
        "reservation_age_softening_beta",
        "reservation_age_gate",
        "predictive_slack_min_s",
        "reactive_pressure_max_for_predictive",
        "predictive_confidence_min",
        "predictive_deadline_weight",
        "predictive_eta_penalty_weight",
        "predictive_utility_mode",
        "predictive_fixed_deterring_mode",
        "predictive_confidence_source",
        "predictive_confidence_power",
        "predictive_time_score_deadline_scale_s",
        "predictive_time_score_reactive_pressure_weight",
        "predictive_time_score_infeasible_penalty",
        "predictive_utility_min",
        "predictive_cost_ratio_min",
        "predictive_opportunity_cost_weight",
        "predictive_eta_cost_weight",
        "predictive_service_cost_weight",
        "risk_adjusted_reservation_alpha",
        "risk_adjusted_reservation_beta",
        "predictive_selection_policy",
        "defer_predictive_action_selection",
        "assignment_switch_penalty",
        "zone_assignment_mode",
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
    "habituation": (
        "enable_habituation",
        "habituation_T_rec_s",
        "habituation_kappa",
        "habituation_gamma",
        "truth_habituation_T_rec_s",
        "truth_habituation_kappa",
        "truth_habituation_gamma",
        "truth_habituation_update_model",
        "planner_habituation_T_rec_s",
        "planner_habituation_kappa",
        "planner_habituation_gamma",
        "planner_habituation_update_model",
        "direct_detection_habituation_mode",
    ),
    "stl": (
        "stl_E_star",
        "stl_T_cov_s",
        "stl_T_react_s",
        "stl_W_s",
        "stl_eta_min",
        "stl_horizon_s",
        "stl_monitor_dt_s",
        "stl_theta",
        "stl_smooth",
        "stl_active_clauses",
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
        "motion_planning_mode",
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
        "graph_row_node_spacing_m",
        "graph_headland_node_spacing_m",
        "graph_passing_bay_spacing_m",
        "graph_anchor_snap_radius_m",
        "graph_replan_period_s",
        "graph_reservation_horizon_s",
        "graph_max_detour_ratio",
        "graph_wait_retry_period_s",
        "debug_movement",
    ),
    "idle_behavior": ("idle_roam_enabled", "idle_roam_interval_s", "idle_roam_jitter_m"),
    "tracking": ("emit_tracking_state", "tracking_include_arrays", "tracking_preview_limit", "tracking_capture_frame_locals"),
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
    habituation: Dict[str, Any]
    stl: Dict[str, Any]
    forecast: Dict[str, Any]
    metrics: Dict[str, Any]
    motion: Dict[str, Any]
    idle_behavior: Dict[str, Any]
    tracking: Dict[str, Any]
    deterring_modes: Dict[str, Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable structured snapshot payload."""
        return asdict(self)


@dataclass(frozen=True)
class ProductionRuntimeSnapshot:
    sim_time_s: float
    fleet: Dict[str, Any]
    tasks: Dict[str, Any]
    perception: Dict[str, Any]
    communication: Dict[str, Any]
    outputs: Dict[str, Any]
    tracking: Dict[str, Any] | None = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable structured snapshot payload."""
        return asdict(self)


@dataclass
class TaskGenerationStageResult:
    now_t: float
    patrolling_enabled: bool
    busy_deterring_robots: list[str]
    candidate_tasks: list[dict]
    candidate_stream_counts: Dict[str, int]
    extracted_candidate_count: int
    selected_candidate_count: int
    selection_policy: str
    selection_rejected_counts: Dict[str, int]
    source_buffer_size: int
    seen_task_key_count: int
    active_load_before_dispatch: Dict[str, int]
    active_patrol_load_before_dispatch: Dict[str, int]
    active_model_det_load_before_dispatch: Dict[str, int]
    diag_counts: Dict[str, Any]

    def to_public_dict(self, preview_limit: int = 25) -> Dict[str, Any]:
        """Return a JSON-serializable public stage payload for diagnostics and exports."""
        preview = []
        for task in self.candidate_tasks[: max(int(preview_limit), 0)]:
            preview.append(
                {
                    "stream": (
                        "reactive"
                        if (
                            task_action_kind(task) == "deterring"
                            and task_action_name(task) == "direct_detection"
                        ) else "predictive"
                    ),
                    "type": task.get("type"),
                    "origin": task.get("origin"),
                    "mode": task.get("mode"),
                    "action": task_action_public_dict(task),
                    "robot_id": task.get("robot_id"),
                    "x": task.get("x"),
                    "y": task.get("y"),
                    "time": task.get("time"),
                    "score": task.get("score"),
                    "utility": task.get("utility"),
                    "predicted_deltaJ": task.get("predicted_deltaJ"),
                    "predictive_stl_U": task.get("predictive_stl_U"),
                    "habituation_eta_at_plan": task.get("habituation_eta_at_plan"),
                    "p_event": task.get("p_event"),
                    "predictive_utility_mode": task.get("predictive_utility_mode"),
                    "predictive_confidence_source": task.get("predictive_confidence_source"),
                    "predictive_confidence_power": task.get("predictive_confidence_power"),
                    "predictive_confidence": task.get("predictive_confidence", task.get("confidence")),
                    "confidence": task.get("confidence", task.get("predictive_confidence")),
                    "confidence_components": task.get("confidence_components"),
                    "predictive_raw_deltaJ": task.get("predictive_raw_deltaJ"),
                    "bernoulli_expected_deltaJ": task.get("bernoulli_expected_deltaJ"),
                    "predictive_expected_deltaJ": task.get("predictive_expected_deltaJ"),
                    "deltaJ_per_cost": task.get("deltaJ_per_cost"),
                    "llr": task.get("llr"),
                    "selection_weight": task.get("selection_weight"),
                    "lead_time_s": task.get("lead_time_s"),
                    "predictive_timing_mode": task.get("predictive_timing_mode"),
                    "forecast_event_time": task.get("forecast_event_time"),
                    "release_time": task.get("release_time"),
                    "event_time": task.get("event_time"),
                    "required_arrival_by_t": task.get("required_arrival_by_t"),
                    "predictive_deadline_slack_s": task.get("predictive_deadline_slack_s"),
                    "predictive_event_offset_s": task.get("predictive_event_offset_s"),
                    "predictive_offset_margin_s": task.get("predictive_offset_margin_s"),
                    "predictive_offset_cap_s": task.get("predictive_offset_cap_s"),
                    "predictive_mode_variant_count": task.get("predictive_mode_variant_count"),
                    "predictive_generation_best_mode": task.get("predictive_generation_best_mode"),
                    "predictive_fixed_deterring_mode": task.get("predictive_fixed_deterring_mode"),
                    "predictive_dispatch_resolved_mode": task.get("predictive_dispatch_resolved_mode"),
                    "predictive_dispatch_eta_basis": task.get("predictive_dispatch_eta_basis"),
                }
            )
        return {
            "now_t": float(self.now_t),
            "patrolling_enabled": bool(self.patrolling_enabled),
            "busy_deterring_robots": list(self.busy_deterring_robots),
            "extracted_candidate_count": int(self.extracted_candidate_count),
            "selected_candidate_count": int(self.selected_candidate_count),
            "selection_policy": str(self.selection_policy),
            "selection_rejected_counts": dict(self.selection_rejected_counts),
            "candidate_count": int(len(self.candidate_tasks)),
            "candidate_stream_counts": dict(self.candidate_stream_counts),
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
    dispatch_policy: str
    reservation_fraction: float
    reservation_window_s: float
    reactive_override_slack_s: float
    reservation_softening_alpha: float
    reservation_age_softening_beta: float
    reservation_age_gate: float
    predictive_slack_min_s: float
    reactive_pressure_max_for_predictive: float
    predictive_confidence_min: float
    predictive_deadline_weight: float
    predictive_eta_penalty_weight: float
    predictive_utility_mode: str
    predictive_confidence_source: str
    predictive_confidence_power: float
    predictive_time_score_deadline_scale_s: float
    predictive_time_score_reactive_pressure_weight: float
    predictive_time_score_infeasible_penalty: float
    predictive_utility_min: float
    predictive_cost_ratio_min: float
    predictive_opportunity_cost_weight: float
    predictive_eta_cost_weight: float
    predictive_service_cost_weight: float
    risk_adjusted_reservation_alpha: float
    risk_adjusted_reservation_beta: float
    predictive_timing_mode: str
    predictive_expiry_grace_s: float
    predictive_selection_policy: str
    candidate_count: int
    candidate_stream_counts: Dict[str, int]
    accepted_tasks: list[dict]
    accepted_stream_counts: Dict[str, int]
    rejected_counts: Dict[str, int]
    rejected_model_det_tasks: list[dict]
    ordering_policy: str
    ordered_candidate_preview: list[dict]
    replaced_patrol_count: int
    urgent_reactive_override_count: int
    robot_predictive_share_snapshot: Dict[str, float]
    active_load_after_dispatch: Dict[str, int]
    active_patrol_load_after_dispatch: Dict[str, int]
    active_model_det_load_after_dispatch: Dict[str, int]
    model_deterring_accepted_total: int
    model_deterring_rejected_budget_total: int
    risk_adjusted_diagnostics: Dict[str, Any]

    def to_public_dict(self, preview_limit: int = 25) -> Dict[str, Any]:
        """Return a JSON-serializable public stage payload for diagnostics and exports."""
        preview = []
        for task in self.accepted_tasks[: max(int(preview_limit), 0)]:
            preview.append(
                {
                    "id": task.get("id"),
                    "stream": (
                        "reactive"
                        if (
                            task_action_kind(task) == "deterring"
                            and task_action_name(task) == "direct_detection"
                        ) else "predictive"
                    ),
                    "type": task.get("type"),
                    "origin": task.get("origin"),
                    "mode": task.get("mode"),
                    "action": task_action_public_dict(task),
                    "assigned_primary": task.get("assigned_primary"),
                    "assigned_secondary": task.get("assigned_secondary"),
                    "robot_id": task.get("robot_id"),
                    "x": task.get("x"),
                    "y": task.get("y"),
                    "time": task.get("time"),
                    "score": task.get("score"),
                    "utility": task.get("utility"),
                    "support": task.get("support"),
                    "eta_s": task.get("eta_s"),
                    "assigned_eta_s": task.get("assigned_eta_s"),
                    "cluster_key": task.get("cluster_key"),
                    "candidate_key": task.get("candidate_key"),
                    "predictive_opportunity_key": task.get("predictive_opportunity_key"),
                    "predicted_deltaJ": task.get("predicted_deltaJ"),
                    "predictive_stl_U": task.get("predictive_stl_U"),
                    "habituation_eta_at_plan": task.get("habituation_eta_at_plan"),
                    "p_event": task.get("p_event"),
                    "predictive_utility_mode": task.get("predictive_utility_mode"),
                    "predictive_confidence_source": task.get("predictive_confidence_source"),
                    "predictive_confidence_power": task.get("predictive_confidence_power"),
                    "confidence": task.get("confidence", task.get("predictive_confidence")),
                    "confidence_components": task.get("confidence_components"),
                    "predictive_raw_deltaJ": task.get("predictive_raw_deltaJ"),
                    "bernoulli_expected_deltaJ": task.get("bernoulli_expected_deltaJ"),
                    "predictive_expected_deltaJ": task.get("predictive_expected_deltaJ"),
                    "lead_time_s": task.get("lead_time_s"),
                    "predictive_timing_mode": task.get("predictive_timing_mode"),
                    "forecast_event_time": task.get("forecast_event_time"),
                    "release_time": task.get("release_time"),
                    "event_time": task.get("event_time"),
                    "required_arrival_by_t": task.get("required_arrival_by_t"),
                    "predictive_deadline_slack_s": task.get("predictive_deadline_slack_s"),
                    "predictive_event_offset_s": task.get("predictive_event_offset_s"),
                    "predictive_offset_margin_s": task.get("predictive_offset_margin_s"),
                    "predictive_offset_cap_s": task.get("predictive_offset_cap_s"),
                    "predictive_mode_variant_count": task.get("predictive_mode_variant_count"),
                    "predictive_generation_best_mode": task.get("predictive_generation_best_mode"),
                    "predictive_fixed_deterring_mode": task.get("predictive_fixed_deterring_mode"),
                    "predictive_dispatch_resolved_mode": task.get("predictive_dispatch_resolved_mode"),
                    "predictive_dispatch_eta_basis": task.get("predictive_dispatch_eta_basis"),
                    "predictive_confidence": task.get("predictive_confidence"),
                    "predictive_expected_reduction": task.get("predictive_expected_reduction"),
                    "predictive_cost": task.get("predictive_cost"),
                    "predictive_opportunity_cost": task.get("predictive_opportunity_cost"),
                    "predictive_risk_adjusted_utility": task.get("predictive_risk_adjusted_utility"),
                    "predictive_cost_ratio": task.get("predictive_cost_ratio"),
                }
            )
        return {
            "now_t": float(self.now_t),
            "dispatch_policy": str(self.dispatch_policy),
            "reservation_fraction": float(self.reservation_fraction),
            "reservation_window_s": float(self.reservation_window_s),
            "reactive_override_slack_s": float(self.reactive_override_slack_s),
            "reservation_softening_alpha": float(self.reservation_softening_alpha),
            "reservation_age_softening_beta": float(self.reservation_age_softening_beta),
            "reservation_age_gate": float(self.reservation_age_gate),
            "predictive_slack_min_s": float(self.predictive_slack_min_s),
            "reactive_pressure_max_for_predictive": float(self.reactive_pressure_max_for_predictive),
            "predictive_confidence_min": float(self.predictive_confidence_min),
            "predictive_deadline_weight": float(self.predictive_deadline_weight),
            "predictive_eta_penalty_weight": float(self.predictive_eta_penalty_weight),
            "predictive_utility_mode": str(self.predictive_utility_mode),
            "predictive_confidence_source": str(self.predictive_confidence_source),
            "predictive_confidence_power": float(self.predictive_confidence_power),
            "predictive_time_score_deadline_scale_s": float(self.predictive_time_score_deadline_scale_s),
            "predictive_time_score_reactive_pressure_weight": float(self.predictive_time_score_reactive_pressure_weight),
            "predictive_time_score_infeasible_penalty": float(self.predictive_time_score_infeasible_penalty),
            "predictive_utility_min": float(self.predictive_utility_min),
            "predictive_cost_ratio_min": float(self.predictive_cost_ratio_min),
            "predictive_opportunity_cost_weight": float(self.predictive_opportunity_cost_weight),
            "predictive_eta_cost_weight": float(self.predictive_eta_cost_weight),
            "predictive_service_cost_weight": float(self.predictive_service_cost_weight),
            "risk_adjusted_reservation_alpha": float(self.risk_adjusted_reservation_alpha),
            "risk_adjusted_reservation_beta": float(self.risk_adjusted_reservation_beta),
            "predictive_timing_mode": str(self.predictive_timing_mode),
            "predictive_expiry_grace_s": float(self.predictive_expiry_grace_s),
            "predictive_selection_policy": str(self.predictive_selection_policy),
            "candidate_count": int(self.candidate_count),
            "candidate_stream_counts": dict(self.candidate_stream_counts),
            "accepted_count": int(len(self.accepted_tasks)),
            "accepted_stream_counts": dict(self.accepted_stream_counts),
            "accepted_preview": preview,
            "rejected_counts": dict(self.rejected_counts),
            "rejected_model_det_count": int(len(self.rejected_model_det_tasks)),
            "rejected_model_det_tasks": list(self.rejected_model_det_tasks),
            "ordering_policy": str(self.ordering_policy),
            "ordered_candidate_preview": list(self.ordered_candidate_preview),
            "replaced_patrol_count": int(self.replaced_patrol_count),
            "urgent_reactive_override_count": int(self.urgent_reactive_override_count),
            "robot_predictive_share_snapshot": dict(self.robot_predictive_share_snapshot),
            "active_load_after_dispatch": dict(self.active_load_after_dispatch),
            "active_patrol_load_after_dispatch": dict(self.active_patrol_load_after_dispatch),
            "active_model_det_load_after_dispatch": dict(self.active_model_det_load_after_dispatch),
            "model_deterring_accepted_total": int(self.model_deterring_accepted_total),
            "model_deterring_rejected_budget_total": int(self.model_deterring_rejected_budget_total),
            "risk_adjusted_diagnostics": dict(self.risk_adjusted_diagnostics),
        }


@dataclass
class MotionCommand:
    robot_id: str
    command_type: str
    source: str
    assigned_task_id: Optional[int]
    assigned_task_type: Optional[str]
    assigned_task_mode: Optional[str]
    assigned_task_stream: Optional[str]
    assigned_action_kind: Optional[str]
    assigned_action_name: Optional[str]
    assigned_action_service_time_s: Optional[float]
    goal: Optional[Tuple[float, float]]
    effective_goal: Optional[Tuple[float, float]]
    current_pose: Tuple[float, float]
    planner_mode: str = "lane_projection"
    route_node_ids: list[str] | None = None
    route_waypoints: list[Tuple[float, float]] | None = None
    active_waypoint_index: int = 0
    blocked: bool = False
    wait_reason: Optional[str] = None

    def to_public_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable public stage payload for diagnostics and exports."""
        return {
            "robot_id": str(self.robot_id),
            "command_type": str(self.command_type),
            "source": str(self.source),
            "assigned_task_id": (None if self.assigned_task_id is None else int(self.assigned_task_id)),
            "assigned_task_type": (None if self.assigned_task_type is None else str(self.assigned_task_type)),
            "assigned_task_mode": (None if self.assigned_task_mode is None else str(self.assigned_task_mode)),
            "assigned_task_stream": (None if self.assigned_task_stream is None else str(self.assigned_task_stream)),
            "assigned_action_kind": (
                None if self.assigned_action_kind is None else str(self.assigned_action_kind)
            ),
            "assigned_action_name": (
                None if self.assigned_action_name is None else str(self.assigned_action_name)
            ),
            "assigned_action_service_time_s": (
                None
                if self.assigned_action_service_time_s is None
                else float(self.assigned_action_service_time_s)
            ),
            "goal": (None if self.goal is None else (float(self.goal[0]), float(self.goal[1]))),
            "effective_goal": (
                None if self.effective_goal is None else (float(self.effective_goal[0]), float(self.effective_goal[1]))
            ),
            "current_pose": (float(self.current_pose[0]), float(self.current_pose[1])),
            "planner_mode": str(self.planner_mode),
            "route_node_ids": ([] if self.route_node_ids is None else [str(node_id) for node_id in self.route_node_ids]),
            "route_waypoints": (
                []
                if self.route_waypoints is None
                else [(float(point[0]), float(point[1])) for point in self.route_waypoints]
            ),
            "active_waypoint_index": int(self.active_waypoint_index),
            "blocked": bool(self.blocked),
            "wait_reason": (None if self.wait_reason is None else str(self.wait_reason)),
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
    dispatched_stream_counts_this_step: Dict[str, int]
    completed_stream_counts_this_step: Dict[str, int]
    completed_patrolling_this_step: int
    completed_deterring_this_step: int
    stale_goal_clears_this_step: int
    holding_robot_count: int
    moving_robot_count: int
    idle_robot_count: int

    def to_public_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable public stage payload for diagnostics and exports."""
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
            "dispatched_stream_counts_this_step": dict(self.dispatched_stream_counts_this_step),
            "completed_stream_counts_this_step": dict(self.completed_stream_counts_this_step),
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
        """Return a JSON-serializable public stage payload for diagnostics and exports."""
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
    dispatch_policy: str
    reservation_fraction: float
    reservation_softening_alpha: float
    reservation_age_softening_beta: float
    reservation_age_gate: float
    predictive_slack_min_s: float
    reactive_pressure_max_for_predictive: float
    predictive_confidence_min: float
    predictive_deadline_weight: float
    predictive_eta_penalty_weight: float
    predictive_utility_mode: str
    predictive_confidence_source: str
    predictive_confidence_power: float
    predictive_time_score_deadline_scale_s: float
    predictive_time_score_reactive_pressure_weight: float
    predictive_time_score_infeasible_penalty: float
    predictive_utility_min: float
    predictive_cost_ratio_min: float
    predictive_opportunity_cost_weight: float
    predictive_eta_cost_weight: float
    predictive_service_cost_weight: float
    risk_adjusted_reservation_alpha: float
    risk_adjusted_reservation_beta: float
    predictive_timing_mode: str
    predictive_expiry_grace_s: float
    predictive_selection_policy: str
    zone_repartition_total: int
    health_retirement_total: int
    health_return_total: int
    active_robot_count: int
    retired_robot_count: int
    habituation_eta_mean: float
    habituation_eta_min: float
    habituation_eta_at_apply_mean: float
    habituation_variety_index: float
    stl_robustness_global_mean: float
    stl_robustness_global_min: float
    stl_robustness_exp: float
    stl_robustness_cov: float
    stl_robustness_hab: float
    predictive_planning_topology: str
    zone_assignment_mode: str
    defer_predictive_action_selection: int
    assignment_switch_penalty: float
    value_weighted_exposure: float
    mean_response_time_s: float
    completed_tasks_total: int
    reactive_generated_total: int
    predictive_generated_total: int
    predictive_distinct_generated_total: int
    reactive_admitted_total: int
    predictive_admitted_total: int
    predictive_distinct_admitted_total: int
    reactive_dispatched_total: int
    predictive_dispatched_total: int
    reactive_completed_total: int
    predictive_completed_total: int
    predictive_distinct_completed_total: int
    reactive_completed_fraction: float
    predictive_completed_fraction: float
    predictive_expired_total: int
    predictive_expired_fraction: float
    predictive_confidence_mean: float
    predictive_confidence_completed_mean: float
    predictive_expected_deltaJ_total: float
    predictive_raw_deltaJ_total: float
    predictive_completion_ratio: float
    predictive_success_ratio: float
    predictive_false_positive_ratio: float
    predictive_success_proxy_evaluated_total: int
    predictive_success_proxy_total: int
    predictive_false_positive_proxy_total: int
    centralized_global_opportunity_count_total: int
    cross_zone_assignment_total: int
    predictive_zone_bonus_mean: float
    reactive_load_factor_estimate: float
    robot_idle_fraction_mean: float
    robot_reactive_fraction_mean: float
    robot_predictive_fraction_mean: float
    urgent_reactive_override_total: int
    predictive_deadline_feasible_total: int
    predictive_deadline_checked_total: int
    predictive_deadline_feasible_fraction: float
    boundary_message_count: int
    boundary_bytes_sent: int
    fleet_task_engagement_fraction_so_far: float
    fleet_moving_fraction_so_far: float
    fleet_idle_no_task_fraction_so_far: float
    truth_suppression_rate: float
    birds_deterred_pct: float
    truth_suppression_rate_last_hour: float
    birds_deterred_pct_last_hour: float
    forecast_recall_at_k: float
    forecast_precision_at_k: float

    def to_public_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable public stage payload for diagnostics and exports."""
        return {
            "now_t": float(self.now_t),
            "dispatch_policy": str(self.dispatch_policy),
            "reservation_fraction": float(self.reservation_fraction),
            "reservation_softening_alpha": float(self.reservation_softening_alpha),
            "reservation_age_softening_beta": float(self.reservation_age_softening_beta),
            "reservation_age_gate": float(self.reservation_age_gate),
            "predictive_slack_min_s": float(self.predictive_slack_min_s),
            "reactive_pressure_max_for_predictive": float(self.reactive_pressure_max_for_predictive),
            "predictive_confidence_min": float(self.predictive_confidence_min),
            "predictive_deadline_weight": float(self.predictive_deadline_weight),
            "predictive_eta_penalty_weight": float(self.predictive_eta_penalty_weight),
            "predictive_utility_mode": str(self.predictive_utility_mode),
            "predictive_confidence_source": str(self.predictive_confidence_source),
            "predictive_confidence_power": float(self.predictive_confidence_power),
            "predictive_time_score_deadline_scale_s": float(self.predictive_time_score_deadline_scale_s),
            "predictive_time_score_reactive_pressure_weight": float(self.predictive_time_score_reactive_pressure_weight),
            "predictive_time_score_infeasible_penalty": float(self.predictive_time_score_infeasible_penalty),
            "predictive_utility_min": float(self.predictive_utility_min),
            "predictive_cost_ratio_min": float(self.predictive_cost_ratio_min),
            "predictive_opportunity_cost_weight": float(self.predictive_opportunity_cost_weight),
            "predictive_eta_cost_weight": float(self.predictive_eta_cost_weight),
            "predictive_service_cost_weight": float(self.predictive_service_cost_weight),
            "risk_adjusted_reservation_alpha": float(self.risk_adjusted_reservation_alpha),
            "risk_adjusted_reservation_beta": float(self.risk_adjusted_reservation_beta),
            "predictive_timing_mode": str(self.predictive_timing_mode),
            "predictive_expiry_grace_s": float(self.predictive_expiry_grace_s),
            "predictive_selection_policy": str(self.predictive_selection_policy),
            "zone_repartition_total": int(self.zone_repartition_total),
            "health_retirement_total": int(self.health_retirement_total),
            "health_return_total": int(self.health_return_total),
            "active_robot_count": int(self.active_robot_count),
            "retired_robot_count": int(self.retired_robot_count),
            "habituation_eta_mean": float(self.habituation_eta_mean),
            "habituation_eta_min": float(self.habituation_eta_min),
            "habituation_eta_at_apply_mean": float(self.habituation_eta_at_apply_mean),
            "habituation_variety_index": float(self.habituation_variety_index),
            "stl_robustness_global_mean": float(self.stl_robustness_global_mean),
            "stl_robustness_global_min": float(self.stl_robustness_global_min),
            "stl_robustness_exp": float(self.stl_robustness_exp),
            "stl_robustness_cov": float(self.stl_robustness_cov),
            "stl_robustness_hab": float(self.stl_robustness_hab),
            "predictive_planning_topology": str(self.predictive_planning_topology),
            "zone_assignment_mode": str(self.zone_assignment_mode),
            "defer_predictive_action_selection": int(self.defer_predictive_action_selection),
            "assignment_switch_penalty": float(self.assignment_switch_penalty),
            "value_weighted_exposure": float(self.value_weighted_exposure),
            "mean_response_time_s": float(self.mean_response_time_s),
            "completed_tasks_total": int(self.completed_tasks_total),
            "reactive_generated_total": int(self.reactive_generated_total),
            "predictive_generated_total": int(self.predictive_generated_total),
            "predictive_distinct_generated_total": int(self.predictive_distinct_generated_total),
            "reactive_admitted_total": int(self.reactive_admitted_total),
            "predictive_admitted_total": int(self.predictive_admitted_total),
            "predictive_distinct_admitted_total": int(self.predictive_distinct_admitted_total),
            "reactive_dispatched_total": int(self.reactive_dispatched_total),
            "predictive_dispatched_total": int(self.predictive_dispatched_total),
            "reactive_completed_total": int(self.reactive_completed_total),
            "predictive_completed_total": int(self.predictive_completed_total),
            "predictive_distinct_completed_total": int(self.predictive_distinct_completed_total),
            "reactive_completed_fraction": float(self.reactive_completed_fraction),
            "predictive_completed_fraction": float(self.predictive_completed_fraction),
            "predictive_expired_total": int(self.predictive_expired_total),
            "predictive_expired_fraction": float(self.predictive_expired_fraction),
            "predictive_confidence_mean": float(self.predictive_confidence_mean),
            "predictive_confidence_completed_mean": float(self.predictive_confidence_completed_mean),
            "predictive_expected_deltaJ_total": float(self.predictive_expected_deltaJ_total),
            "predictive_raw_deltaJ_total": float(self.predictive_raw_deltaJ_total),
            "predictive_completion_ratio": float(self.predictive_completion_ratio),
            "predictive_success_ratio": float(self.predictive_success_ratio),
            "predictive_false_positive_ratio": float(self.predictive_false_positive_ratio),
            "predictive_success_proxy_evaluated_total": int(self.predictive_success_proxy_evaluated_total),
            "predictive_success_proxy_total": int(self.predictive_success_proxy_total),
            "predictive_false_positive_proxy_total": int(self.predictive_false_positive_proxy_total),
            "centralized_global_opportunity_count_total": int(self.centralized_global_opportunity_count_total),
            "cross_zone_assignment_total": int(self.cross_zone_assignment_total),
            "predictive_zone_bonus_mean": float(self.predictive_zone_bonus_mean),
            "reactive_load_factor_estimate": float(self.reactive_load_factor_estimate),
            "robot_idle_fraction_mean": float(self.robot_idle_fraction_mean),
            "robot_reactive_fraction_mean": float(self.robot_reactive_fraction_mean),
            "robot_predictive_fraction_mean": float(self.robot_predictive_fraction_mean),
            "urgent_reactive_override_total": int(self.urgent_reactive_override_total),
            "predictive_deadline_feasible_total": int(self.predictive_deadline_feasible_total),
            "predictive_deadline_checked_total": int(self.predictive_deadline_checked_total),
            "predictive_deadline_feasible_fraction": float(self.predictive_deadline_feasible_fraction),
            "boundary_message_count": int(self.boundary_message_count),
            "boundary_bytes_sent": int(self.boundary_bytes_sent),
            "fleet_task_engagement_fraction_so_far": float(self.fleet_task_engagement_fraction_so_far),
            "fleet_moving_fraction_so_far": float(self.fleet_moving_fraction_so_far),
            "fleet_idle_no_task_fraction_so_far": float(self.fleet_idle_no_task_fraction_so_far),
            "truth_suppression_rate": float(self.truth_suppression_rate),
            "birds_deterred_pct": float(self.birds_deterred_pct),
            "truth_suppression_rate_last_hour": float(self.truth_suppression_rate_last_hour),
            "birds_deterred_pct_last_hour": float(self.birds_deterred_pct_last_hour),
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
        """Return a JSON-serializable public stage payload for diagnostics and exports."""
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
        """Return a JSON-serializable public stage payload for diagnostics and exports."""
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
        """Return a JSON-serializable public stage payload for diagnostics and exports."""
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
    """Collect production configuration values belonging to one export section."""
    return {name: params.get(name) for name in names}


def build_production_system_config(
    resolved_params: Mapping[str, Any],
    *,
    deterring_modes: Mapping[str, Mapping[str, Any]],
) -> ProductionSystemConfig:
    """Build the structured production configuration snapshot emitted at run start."""
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
        habituation=sections["habituation"],
        stl=sections["stl"],
        forecast=sections["forecast"],
        metrics=sections["metrics"],
        motion=sections["motion"],
        idle_behavior=sections["idle_behavior"],
        tracking=sections["tracking"],
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
    tracking: Mapping[str, Any] | None = None,
) -> ProductionRuntimeSnapshot:
    """Build the structured runtime snapshot emitted for each production frame."""
    active_patrolling = 0
    active_reactive = 0
    active_predictive = 0
    active_deterring_direct = 0
    active_deterring_model_scored = 0
    for task in active_tasks:
        if str(task.get("state", "")).strip().lower() != "active":
            continue
        task_kind = task_action_kind(task)
        action_name = task_action_name(task)
        if task_kind == "patrolling":
            active_patrolling += 1
            active_predictive += 1
        elif task_kind == "deterring":
            if action_name == "direct_detection":
                active_deterring_direct += 1
                active_reactive += 1
            else:
                active_deterring_model_scored += 1
                active_predictive += 1

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
            "active_reactive": int(active_reactive),
            "active_predictive": int(active_predictive),
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
        tracking=(None if tracking is None else dict(tracking)),
    )
