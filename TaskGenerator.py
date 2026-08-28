from typing import Any, Callable, Dict, List, Mapping
from Robot import Robot
from ZonePartitioner import polygon_area, polygon_centroid, point_in_polygon, point_to_poly_distance
from Robot import RobotProfile
import math
import numpy as np
from planner_task_estimation import (
    _time_integral_factor,
    _robot_pose_guess,
    cluster_points,
    estimate_counterfactual_reduction,
    estimate_patrol_response_reduction,
    estimate_stl_counterfactual_value,
)
from tracking_export import export_tracking_value
from action_schema import (
    task_action,
    task_action_kind,
    task_action_name,
    task_action_public_dict,
    task_action_service_time_s,
)

class TaskGenerator:
    def __init__(self, merge_radius_m: float = 20.0, dedupe_xy_decimals: int = 1, dedupe_t_decimals: int = 0,
                 patrol_cooldown_s: float = 20.0):
        """Initialize task generator state, deduplication caches, and patrol fallback bookkeeping."""
        self.merge_radius_m = float(merge_radius_m)
        self._rows = []
        self._keys = set()  # (robot_id,type,round(x,d),round(y,d),round(t,d))

        self._dx = dedupe_xy_decimals
        self._dt = dedupe_t_decimals
        self._cooldown = float(patrol_cooldown_s)
        self._next_allowed: dict[str,float] = {}  # per-robot next allowed time for patrolling
        self._fallback_patrol_state: dict[str, dict] = {}
        # Per-robot cluster memory for preventive model-scored deterring gates.
        self._deterring_cluster_state: dict[tuple[str, int, int], dict] = {}
        self._deterring_forecast_state: dict[tuple[str, str, int, int], dict] = {}
        self._last_model_deterring_fire: dict[tuple, dict] = {}
        self._diag_model_deterring_llr_values: list[float] = []
        self._diag_deduped_task_preview: list[dict[str, Any]] = []
        self.travel_time_fn: Callable[[str, float, float], float] | None = None
        self._deterring_modes: dict[str, dict[str, Any]] = {}
        self._default_tau_service_s = 0.0
        self._enable_predictive_lead_time = False
        self._predictive_lead_time_min_s = 0.0
        self._predictive_lead_time_max_eta_s = 120.0
        self._predictive_lead_time_buffer_s = 0.0
        self._predictive_lead_time_risk_power = 1.0
        self._predictive_timing_mode = "synthetic"
        self.diag_counts = {
            "model_deterring_candidates_total": 0,
            "model_deterring_rejected_cooldown": 0,
            "model_deterring_rejected_field": 0,
            "model_deterring_pass_field": 0,
            "model_deterring_rejected_predicted_deltaJ": 0,
            "model_deterring_pass_predicted_deltaJ": 0,
            "model_deterring_rejected_risk": 0,
            "model_deterring_pass_risk": 0,
            "model_deterring_rejected_support": 0,
            "model_deterring_pass_support": 0,
            "model_deterring_rejected_persistence": 0,
            "model_deterring_rejected_repeat_no_new_support": 0,
            "model_deterring_rejected_eta": 0,
            "model_deterring_rejected_busy": 0,
            "model_deterring_rejected_margin": 0,
            "model_deterring_not_selected": 0,
            "model_deterring_generated": 0,
            "model_deterring_pass_sprt": 0,
            "model_deterring_rejected_sprt_pending": 0,
            "model_deterring_rejected_sprt_negative": 0,
            "model_deterring_rejected_sprt_margin": 0,
            "model_deterring_pass_chance": 0,
            "model_deterring_rejected_chance": 0,
            "model_deterring_pass_utility_ratio": 0,
            "model_deterring_rejected_utility_ratio": 0,
            "model_deterring_pass_selection_weight": 0,
            "model_deterring_rejected_selection_weight": 0,
            "model_deterring_pass_capacity": 0,
            "model_deterring_capacity_pending": 0,
            "model_deterring_rejected_capacity": 0,
            "model_deterring_cluster_key_total": 0,
            "model_deterring_cluster_key_reused": 0,
            "model_deterring_cluster_key_churn": 0,
            "model_deterring_cluster_key_new": 0,
            "model_deterring_llr_sum": 0.0,
            "model_deterring_llr_samples": 0,
            "model_deterring_llr_max": float("-inf"),
            "model_deterring_p_event_sum": 0.0,
            "model_deterring_p_event_samples": 0,
            "model_deterring_deltaJ_per_cost_sum": 0.0,
            "model_deterring_deltaJ_per_cost_samples": 0,
            "deduped_task_total": 0,
        }

    def _diag_increment(self, key: str, amount=1):
        """Increment an internal task-generation diagnostic counter."""
        self.diag_counts[key] = self.diag_counts.get(key, 0) + amount

    def _diag_increment_source(self, prefix: str, origin: str, amount: int = 1):
        """Increment a diagnostic counter keyed by candidate source."""
        origin_key = (
            str(origin).strip().lower().replace("-", "_").replace(" ", "_")
            or "unknown"
        )
        self._diag_increment(f"{prefix}_{origin_key}", int(amount))

    def _record_deduped_task(self, task: Dict, key: tuple):
        """Track a task that was dropped during generation-time deduplication."""
        self._diag_increment("deduped_task_total")
        self._diag_increment_source("deduped_task", str(task.get("origin", "unknown")))
        action_value = task.get("action")
        if action_value is None:
            action_value = task_action(
                task,
                deterring_modes=self._deterring_modes,
                default_service_time_s=float(self._default_tau_service_s),
            )
        row = {
            "dedupe_key": repr(key),
            "robot_id": task.get("robot_id"),
            "type": task.get("type"),
            "origin": task.get("origin", "unknown"),
            "mode": task.get("mode"),
            "action": task_action_public_dict({"action": action_value}),
            "x": float(task.get("x", float("nan"))),
            "y": float(task.get("y", float("nan"))),
            "time": float(task.get("time", float("nan"))),
            "score": float(task.get("score", 0.0)),
            "utility": float(task.get("utility", task.get("score", 0.0))),
            "p_event": float(task.get("p_event", float("nan"))),
            "predicted_deltaJ": float(task.get("predicted_deltaJ", float("nan"))),
            "predictive_opportunity_key": str(self._predictive_opportunity_key(task) or ""),
        }
        self._diag_deduped_task_preview.append(row)
        if len(self._diag_deduped_task_preview) > 200:
            del self._diag_deduped_task_preview[:-200]
        self.diag_counts["deduped_task_preview"] = list(self._diag_deduped_task_preview[-50:])

    def to_tracking_dict(self, *, include_arrays: bool = False, max_items: int = 50):
        """Return a compact tracking snapshot for task generation or assignment state."""
        preview_limit = max(int(max_items), 0)
        return {
            "merge_radius_m": float(self.merge_radius_m),
            "pending_rows_total": int(len(self._rows)),
            "pending_rows_preview": export_tracking_value(
                self._rows[-preview_limit:],
                include_arrays=include_arrays,
                max_items=max_items,
            ),
            "dedupe_key_total": int(len(self._keys)),
            "dedupe_key_preview": export_tracking_value(
                list(self._keys)[:preview_limit],
                include_arrays=include_arrays,
                max_items=max_items,
            ),
            "dedupe_xy_decimals": int(self._dx),
            "dedupe_t_decimals": int(self._dt),
            "deduped_task_total": int(self.diag_counts.get("deduped_task_total", 0)),
            "deduped_task_preview": export_tracking_value(
                self._diag_deduped_task_preview[-preview_limit:],
                include_arrays=include_arrays,
                max_items=max_items,
            ),
            "patrol_cooldown_s": float(self._cooldown),
            "next_allowed": dict(self._next_allowed),
            "fallback_patrol_state": export_tracking_value(
                self._fallback_patrol_state,
                include_arrays=include_arrays,
                max_items=max_items,
            ),
            "deterring_cluster_state": export_tracking_value(
                self._deterring_cluster_state,
                include_arrays=include_arrays,
                max_items=max_items,
            ),
            "deterring_forecast_state": export_tracking_value(
                self._deterring_forecast_state,
                include_arrays=include_arrays,
                max_items=max_items,
            ),
            "last_model_deterring_fire": export_tracking_value(
                self._last_model_deterring_fire,
                include_arrays=include_arrays,
                max_items=max_items,
            ),
            "diag_model_deterring_llr_values": export_tracking_value(
                self._diag_model_deterring_llr_values[-preview_limit:],
                include_arrays=include_arrays,
                max_items=max_items,
            ),
            "diag_counts": dict(self.diag_counts),
        }

    def configure_actions(
        self,
        *,
        deterring_modes: Mapping[str, Mapping[str, Any]] | None = None,
        tau_service_s: float | None = None,
    ):
        """Install the deterrence action catalog used for generated task rows."""
        if deterring_modes is not None:
            self._deterring_modes = {
                str(mode): dict(params)
                for mode, params in dict(deterring_modes).items()
            }
        if tau_service_s is not None:
            self._default_tau_service_s = max(float(tau_service_s), 0.0)

    def configure_predictive_lead_time(
        self,
        *,
        enable_predictive_lead_time: bool | None = None,
        predictive_lead_time_min_s: float | None = None,
        predictive_lead_time_max_eta_s: float | None = None,
        predictive_lead_time_buffer_s: float | None = None,
        predictive_lead_time_risk_power: float | None = None,
        predictive_timing_mode: str | None = None,
    ):
        """Configure forecast lead-time offsets applied to predictive tasks."""
        if enable_predictive_lead_time is not None:
            self._enable_predictive_lead_time = bool(enable_predictive_lead_time)
        if predictive_lead_time_min_s is not None:
            self._predictive_lead_time_min_s = max(float(predictive_lead_time_min_s), 0.0)
        if predictive_lead_time_max_eta_s is not None:
            self._predictive_lead_time_max_eta_s = max(float(predictive_lead_time_max_eta_s), 0.0)
        if predictive_lead_time_buffer_s is not None:
            self._predictive_lead_time_buffer_s = max(float(predictive_lead_time_buffer_s), 0.0)
        if predictive_lead_time_risk_power is not None:
            self._predictive_lead_time_risk_power = max(float(predictive_lead_time_risk_power), 1.0e-6)
        if predictive_timing_mode is not None:
            mode = str(predictive_timing_mode or "synthetic").strip().lower().replace("-", "_")
            if mode not in {"synthetic", "forecast_horizon", "arrival_offset"}:
                raise ValueError(
                    "predictive_timing_mode must be one of ['synthetic', 'forecast_horizon', 'arrival_offset'], "
                    f"got: {predictive_timing_mode!r}"
                )
            self._predictive_timing_mode = mode

    @staticmethod
    def _clip01(value: float) -> float:
        """Clamp a numeric value to the inclusive probability range [0, 1]."""
        return float(min(max(float(value), 0.0), 1.0))

    def _predictive_lead_time_confidence(self, task: Mapping[str, Any]) -> float:
        """Estimate confidence used to schedule a predictive task ahead of an event."""
        confidence_terms: list[float] = []
        for key in ("p_event", "risk_conf", "selection_weight"):
            try:
                value = float(task.get(key, float("nan")))
            except Exception:
                value = float("nan")
            if math.isfinite(value):
                confidence_terms.append(self._clip01(value))
        if str(task.get("type", "")).strip().lower() == "patrolling" and not confidence_terms:
            confidence_terms.append(0.5)
        if not confidence_terms:
            return 0.0
        return float(max(confidence_terms))

    def _apply_predictive_lead_time_fields(
        self,
        task: Dict[str, Any],
        *,
        replan_interval_s: float,
        forecast_horizon_s: float | None = None,
    ) -> Dict[str, Any]:
        """Attach timing fields that describe when a predictive task should be released and completed."""
        task_with_timing = dict(task)
        if not bool(self._enable_predictive_lead_time):
            return task_with_timing
        if task_action_kind(task_with_timing) != "patrolling" and task_action_name(task_with_timing) == "direct_detection":
            return task_with_timing
        if task_action_kind(task_with_timing) == "deterring" and task_action_name(task_with_timing) == "direct_detection":
            return task_with_timing

        base_time = float(task_with_timing.get("time", 0.0))
        eta_s = max(float(task_with_timing.get("eta_s", 0.0)), 0.0)
        tau_service_s = max(
            float(
                task_action(
                    task_with_timing,
                    deterring_modes=self._deterring_modes,
                    default_service_time_s=float(self._default_tau_service_s),
                ).service_time_s
            ),
            0.0,
        )
        min_lead_s = max(float(self._predictive_lead_time_min_s), 0.0)
        worst_case_eta_s = max(float(self._predictive_lead_time_max_eta_s), eta_s)
        buffer_s = max(float(self._predictive_lead_time_buffer_s), 0.0)
        replan_s = max(float(replan_interval_s), 0.0)

        required_lead_s = replan_s + eta_s + tau_service_s + buffer_s
        max_lead_s = max(min_lead_s, replan_s + worst_case_eta_s + tau_service_s + buffer_s)
        confidence = self._predictive_lead_time_confidence(task_with_timing)
        confidence = confidence ** max(float(self._predictive_lead_time_risk_power), 1.0e-6)
        raw_lead_s = min_lead_s + confidence * max(max_lead_s - min_lead_s, 0.0)
        synthetic_lead_time_s = min(max(raw_lead_s, required_lead_s), max_lead_s)

        timing_mode = str(self._predictive_timing_mode or "synthetic")
        forecast_horizon_value_s = max(
            float(forecast_horizon_s if forecast_horizon_s is not None else 0.0),
            0.0,
        )
        useful_margin_cap_s = min(
            max(max_lead_s - required_lead_s, 0.0),
            max(buffer_s + 0.5 * tau_service_s, 0.0),
        )
        if timing_mode == "forecast_horizon":
            forecast_event_offset_s = max(forecast_horizon_value_s, required_lead_s)
            forecast_event_time = base_time + forecast_event_offset_s
            release_time = base_time
            lead_time_s = float(forecast_event_time - release_time)
            predictive_event_offset_s = float(forecast_event_offset_s)
            predictive_offset_margin_s = float(max(predictive_event_offset_s - required_lead_s, 0.0))
            predictive_offset_cap_s = float(max(forecast_event_offset_s - required_lead_s, 0.0))
        elif timing_mode == "arrival_offset":
            offset_cap_s = max(
                required_lead_s,
                min(max_lead_s, max(forecast_horizon_value_s, required_lead_s)),
            )
            offset_margin_s = confidence * min(
                max(offset_cap_s - required_lead_s, 0.0),
                useful_margin_cap_s,
            )
            predictive_event_offset_s = float(required_lead_s + offset_margin_s)
            forecast_event_time = base_time + predictive_event_offset_s
            release_time = base_time
            lead_time_s = float(forecast_event_time - release_time)
            predictive_offset_margin_s = float(offset_margin_s)
            predictive_offset_cap_s = float(max(offset_cap_s - required_lead_s, 0.0))
        else:
            forecast_event_time = base_time + synthetic_lead_time_s
            release_time = base_time
            lead_time_s = synthetic_lead_time_s
            predictive_event_offset_s = float(synthetic_lead_time_s)
            predictive_offset_margin_s = float(max(synthetic_lead_time_s - required_lead_s, 0.0))
            predictive_offset_cap_s = float(max(max_lead_s - required_lead_s, 0.0))

        predictive_deadline_slack_s = forecast_event_time - release_time - eta_s - tau_service_s

        task_with_timing["lead_time_s"] = float(lead_time_s)
        task_with_timing["predictive_timing_mode"] = str(timing_mode)
        task_with_timing["forecast_event_time"] = float(forecast_event_time)
        task_with_timing["release_time"] = float(release_time)
        task_with_timing["event_time"] = float(forecast_event_time)
        task_with_timing["required_arrival_by_t"] = float(forecast_event_time)
        task_with_timing["predictive_deadline_slack_s"] = float(predictive_deadline_slack_s)
        task_with_timing["predictive_required_lead_time_s"] = float(required_lead_s)
        task_with_timing["predictive_event_offset_s"] = float(predictive_event_offset_s)
        task_with_timing["predictive_offset_margin_s"] = float(predictive_offset_margin_s)
        task_with_timing["predictive_offset_cap_s"] = float(predictive_offset_cap_s)
        return task_with_timing

    def _predictive_opportunity_key(self, task: Mapping[str, Any]) -> str:
        """Return the stable opportunity key used to deduplicate predictive tasks."""
        if task_action_kind(task) == "deterring" and task_action_name(task) == "direct_detection":
            return ""
        task_type = str(task.get("type", "")).strip().lower()
        if task_type not in {"patrolling", "deterring"}:
            return ""
        origin = str(task.get("origin", "") or "").strip().lower() or "unknown"
        cluster_key = task.get("cluster_key")
        candidate_key = task.get("candidate_key")
        if cluster_key not in (None, "", ()):
            identity = f"cluster:{repr(cluster_key)}"
        elif candidate_key not in (None, "", ()):
            identity = f"candidate:{repr(candidate_key)}"
        else:
            identity = (
                f"xy:{round(float(task.get('x', 0.0)), self._dx)}:"
                f"{round(float(task.get('y', 0.0)), self._dx)}"
            )
        try:
            event_anchor = float(
                task.get(
                    "forecast_event_time",
                    task.get("required_arrival_by_t", task.get("event_time", task.get("time", 0.0))),
                )
            )
        except Exception:
            event_anchor = float(task.get("time", 0.0))
        if not math.isfinite(event_anchor):
            event_anchor = float(task.get("time", 0.0))
        time_bucket = round(float(event_anchor), self._dt)
        return f"predictive:{task_type}:{origin}:{identity}:t{time_bucket}"

    def _fallback_zone_key(self, zone_polygon) -> tuple:
        """Return a stable zone identifier used for fallback patrol bookkeeping."""
        if not zone_polygon:
            return ()
        return tuple(
            (round(float(x), 3), round(float(y), 3))
            for (x, y) in zone_polygon
        )

    def _fallback_waypoints(self, zone_polygon) -> list[tuple[float, float]]:
        """Generate deterministic fallback patrol waypoints inside a robot zone."""
        if not zone_polygon:
            return []

        # Use a coarse boustrophedon lattice so fallback patrol still covers the zone.
        xs = [float(x) for (x, _y) in zone_polygon]
        ys = [float(y) for (_x, y) in zone_polygon]
        xmin = min(xs)
        xmax = max(xs)
        ymin = min(ys)
        ymax = max(ys)
        width = max(xmax - xmin, 1e-6)
        height = max(ymax - ymin, 1e-6)
        base_spacing = max(float(self.merge_radius_m), 1.0)
        base_cols = max(2, min(4, int(math.ceil(width / base_spacing)) + 1))
        base_rows = max(2, min(4, int(math.ceil(height / base_spacing)) + 1))

        waypoints: list[tuple[float, float]] = []
        for extra_density in (0, 2):
            cols = min(6, base_cols + extra_density)
            rows = min(6, base_rows + extra_density)
            trial: list[tuple[float, float]] = []
            seen = set()
            x_positions = np.linspace(xmin, xmax, num=cols + 2, dtype=float)[1:-1]
            y_positions = np.linspace(ymin, ymax, num=rows + 2, dtype=float)[1:-1]
            for row_idx, y in enumerate(y_positions):
                x_iter = x_positions if (row_idx % 2 == 0) else x_positions[::-1]
                for x in x_iter:
                    xf = float(x)
                    yf = float(y)
                    if not point_in_polygon(xf, yf, zone_polygon):
                        continue
                    key = (round(xf, 4), round(yf, 4))
                    if key in seen:
                        continue
                    seen.add(key)
                    trial.append((xf, yf))
            if trial:
                waypoints = trial
            if len(trial) >= 2:
                break

        if waypoints:
            return waypoints

        cx, cy = polygon_centroid(zone_polygon)
        return [(float(cx), float(cy))]

    def _select_fallback_patrol_point(self, rid: str, rob: "Robot") -> tuple[float, float]:
        """Choose the next fallback patrol point for an idle robot."""
        waypoints = self._fallback_waypoints(rob.zone_polygon)
        if not waypoints:
            return _robot_pose_guess(rob)

        # Select the least-recently-used waypoint to avoid collapsing onto one anchor point.
        zone_key = self._fallback_zone_key(rob.zone_polygon)
        state = self._fallback_patrol_state.get(rid)
        if (
            state is None
            or state.get("zone_key") != zone_key
            or len(state.get("last_visit_step", [])) != len(waypoints)
        ):
            state = {
                "zone_key": zone_key,
                "last_visit_step": [-1] * len(waypoints),
                "visit_counter": 0,
            }

        last_visit_step = list(state["last_visit_step"])
        best_idx = min(range(len(waypoints)), key=lambda idx: (int(last_visit_step[idx]), idx))
        visit_counter = int(state.get("visit_counter", 0)) + 1
        last_visit_step[best_idx] = visit_counter
        state["last_visit_step"] = last_visit_step
        state["visit_counter"] = visit_counter
        self._fallback_patrol_state[rid] = state
        return waypoints[best_idx]

    # -------- immediate tasks (called right when detections arrive) --------
    def on_detection(self, robot_id: str, x: float, y: float, t: float):
        """Create or update a reactive direct-detection task from an observed event."""
        self._add({
            'robot_id': robot_id,
            'type': 'deterring',
            'x': float(x), 'y': float(y),
            'time': float(t),
            'origin': 'detection',
            'score': 0.0,
        })

    # -------- periodic tasks (hotspots + optional fallback) --------
    def periodic_patrolling(self,
                             robots: Dict[str, "Robot"],
                             now_t: float,
                             hotspot_top_k: int = 6,
                             enable_predictive_patrol_tasks: bool = True,
                             include_fallback_patrol: bool = False,
                             enable_model_scored_deterring: bool = True,
                             deterring_window_s: float = 0.0,
                             deterring_risk_threshold: float = 0.35,
                             deterring_risk_scale: float = 1e-4,
                             deterring_min_recent_points: int = 1,
                             deterring_field_threshold: float | None = None,
                             deterring_min_persistence_replans: int = 2,
                             deterring_persistence_max_gap_s: float = 120.0,
                             deterring_score_margin: float = 0.05,
                             deterring_repeat_block_window_s: float = 120.0,
                             deterring_repeat_block_radius_m: float = 25.0,
                             deterring_max_eta_s: float = 120.0,
                             deterring_busy_min_support_override: int = 1,
                             deterring_busy_risk_override: float = 0.20,
                             enable_predicted_deltaJ_gate: bool = False,
                             min_predicted_deltaJ_for_model_deterring: float = 0.0,
                             model_deterring_gate_policy: str = "heuristic",
                             model_deterring_sprt_alpha: float = 0.05,
                             model_deterring_sprt_beta: float = 0.20,
                             model_deterring_sprt_patch_radius_m: float | None = None,
                             model_deterring_min_sprt_margin: float = 0.0,
                             model_deterring_chance_threshold: float = 0.20,
                             model_deterring_min_deltaJ_per_cost: float = 0.15,
                             model_deterring_min_selection_weight: float = 0.0,
                             preventive_capacity_remaining_by_robot: Dict[str, float] | None = None,
                             preventive_capacity_ready_by_robot: Dict[str, bool] | None = None,
                             replan_interval_s: float | None = None,
                             busy_deterring_robots=None,
                             recent_deterrence_events: List[dict] | None = None,
                             min_hotspot_score: float = 1e-4,
                             patrol_hotspot_filter_mode: str = "percentile",
                             patrol_hotspot_score_percentile: float = 97.0,
                             patrol_hotspot_keep_top_k: int | None = None,
                             patrol_feedback_inhibition_retention: float = 1.0,
                             patrol_scoring_mode: str = "shared_response_reduction",
                             patrol_shared_detection_range_m: float | None = None,
                             patrol_shared_detection_prob_per_step: float = 0.10,
                             patrol_shared_detection_dwell_s: float = 20.0,
                             patrol_shared_followup_success_prob: float = 0.75,
                             patrol_shared_response_eta_decay_s: float | None = None,
                             hotspot_spacing_m: float = 25.0,
                             jitter_m: float = 4.0,
                             horizon_s: float = 300.0,
                             weight_fn=None,
                             profiles: Dict[str, RobotProfile] | None = None,
                             robot_poses: Mapping[str, tuple[float, float]] | None = None,
                             rng=None,
                             cost_w_eta: float = 1.0,
                             spinup_by_type: Dict[str, float] | None = None,
                             deterring_modes: Dict[str, Dict] | None = None,
                             value_edge_gain: float = 0.5,
                             value_edge_scale: float = 30.0,
                             value_block_gain: float = 0.3,
                             value_block_size: float = 80.0,
                             travel_time_fn: Callable[[str, float, float], float] | None = None,
                             enable_predictive_lead_time: bool | None = None,
                             predictive_lead_time_min_s: float | None = None,
                             predictive_lead_time_max_eta_s: float | None = None,
                             predictive_lead_time_buffer_s: float | None = None,
                             predictive_lead_time_risk_power: float | None = None,
                             predictive_timing_mode: str | None = None,
                             predictive_utility_mode: str = "legacy",
                             predictive_fixed_deterring_mode: str | None = None,
                             stl_hab=None,
                             stl_spec_params=None,
                             stl_dynamics=None,
                             stl_cell_polys=None,
                             stl_local_cell_ids_by_robot: Mapping[str, list[int]] | None = None,
                             stl_last_service_t_by_cell: Mapping[int, float] | None = None,
                             stl_mode_to_id: Mapping[str, int] | None = None,
                             stl_cell_id_for_xy_fn: Callable[[float, float], int | None] | None = None):
        """
        Build patrolling-from-hotspots tasks for each robot at 'now_t'.
        Optionally keep a small deterring window if you also want clustered deterring here.
        By default deterring_window_s=0 to avoid duplicating immediate tasks.
        """
        if busy_deterring_robots is None:
            busy_deterring_robots = set()
        if preventive_capacity_remaining_by_robot is None:
            preventive_capacity_remaining_by_robot = {}
        if preventive_capacity_ready_by_robot is None:
            preventive_capacity_ready_by_robot = {}
        if deterring_modes is not None:
            self.configure_actions(deterring_modes=deterring_modes)
        self.configure_predictive_lead_time(
            enable_predictive_lead_time=enable_predictive_lead_time,
            predictive_lead_time_min_s=predictive_lead_time_min_s,
            predictive_lead_time_max_eta_s=predictive_lead_time_max_eta_s,
            predictive_lead_time_buffer_s=predictive_lead_time_buffer_s,
            predictive_lead_time_risk_power=predictive_lead_time_risk_power,
            predictive_timing_mode=predictive_timing_mode,
        )
        repeat_radius = max(1e-6, float(deterring_repeat_block_radius_m))
        repeat_radius2 = repeat_radius ** 2
        persist_gap_s = max(float(deterring_persistence_max_gap_s), 1e-6)
        persist_min = max(1, int(deterring_min_persistence_replans))
        score_margin = float(deterring_score_margin)
        max_eta_s = max(1e-6, float(deterring_max_eta_s))
        busy_support_override = max(1, int(deterring_busy_min_support_override))
        busy_risk_override = float(deterring_busy_risk_override)
        repeat_block_window = max(0.0, float(deterring_repeat_block_window_s))
        cluster_quant = max(1.0, 0.5 * float(self.merge_radius_m))
        preventive_quant = max(cluster_quant, 0.5 * max(float(self.merge_radius_m), float(hotspot_spacing_m)))
        preventive_overlap_radius = max(float(self.merge_radius_m), 0.5 * float(hotspot_spacing_m))
        preventive_overlap_radius2 = preventive_overlap_radius ** 2
        # Restore the pre-selective preventive gate: all callers now execute the
        # legacy heuristic admission path even if older configs still pass the
        # selective `sprt_capacity` token.
        gate_policy = "heuristic"
        enable_predicted_deltaJ_gate = False
        sprt_alpha = min(max(float(model_deterring_sprt_alpha), 1e-6), 1.0 - 1e-6)
        sprt_beta = min(max(float(model_deterring_sprt_beta), 1e-6), 1.0 - 1e-6)
        sprt_accept = math.log((1.0 - sprt_beta) / sprt_alpha)
        sprt_reject = math.log(sprt_beta / (1.0 - sprt_alpha))
        sprt_margin = max(0.0, float(model_deterring_min_sprt_margin))
        patch_radius = float(model_deterring_sprt_patch_radius_m) if model_deterring_sprt_patch_radius_m is not None else float(self.merge_radius_m)
        patch_radius = max(patch_radius, 1e-6)
        chance_threshold = min(max(float(model_deterring_chance_threshold), 0.0), 1.0)
        min_deltaJ_per_cost = float(model_deterring_min_deltaJ_per_cost)
        min_selection_weight = min(max(float(model_deterring_min_selection_weight), 0.0), 1.0)
        count_window_s = float(replan_interval_s) if replan_interval_s is not None else float(deterring_window_s)
        count_window_s = max(count_window_s, 1e-6)
        filter_mode = str(patrol_hotspot_filter_mode).strip().lower()
        if filter_mode not in ("absolute", "percentile", "top_k"):
            filter_mode = "absolute"
        percentile = float(patrol_hotspot_score_percentile)
        if percentile <= 1.0:
            percentile *= 100.0
        percentile = min(max(percentile, 0.0), 100.0)
        keep_top_k = hotspot_top_k if patrol_hotspot_keep_top_k is None else max(1, int(patrol_hotspot_keep_top_k))
        patrol_inhib_retention = min(max(float(patrol_feedback_inhibition_retention), 0.0), 1.0)
        patrol_scoring_mode = str(patrol_scoring_mode).strip().lower()
        if patrol_scoring_mode not in ("legacy_field_benefit", "shared_response_reduction"):
            patrol_scoring_mode = "shared_response_reduction"
        predictive_utility_mode_key = str(predictive_utility_mode or "legacy").strip().lower().replace("-", "_")
        use_stl_robustness_value = predictive_utility_mode_key in {
            "stl",
            "stl_robustness",
            "robustness",
            "counterfactual_robustness",
        }
        use_habituation_aware_legacy_value = predictive_utility_mode_key in {
            "legacy_habituation",
            "habituation_legacy",
            "habituation_aware",
            "habituation_aware_legacy",
            "eta_scaled_legacy",
            "eta_scaled_deltaj",
            "eta_scaled_delta_j",
        }

        for rid, rob in robots.items():
            # ----------------------------------------------------------------
            # Algorithm Block: Robot-local field preparation and hotspot search
            # ----------------------------------------------------------------
            # keep model time consistent
            rob.m.advance_time(now_t - rob.m.t_now)

            # recent detections (for optional clustered deterring here)
            recent_pts = [(x,y) for (x,y,t) in rob.recent_events if (now_t - t) <= deterring_window_s]
            count_pts = [(x,y) for (x,y,t) in rob.recent_events if (now_t - t) <= count_window_s]
            deterring_points = (
                cluster_points(recent_pts, self.merge_radius_m)
                if (enable_model_scored_deterring and deterring_window_s > 0)
                else []
            )

            patrol_field_cache = {"excess": None}

            def _patrol_field_grid():
                """Sample a robot forecast field over candidate patrol points in its zone."""
                if patrol_field_cache["excess"] is None:
                    if abs(patrol_inhib_retention - 1.0) <= 1e-12:
                        patrol_field_cache["excess"] = (rob.m.lam - rob.m.mu).copy()
                    else:
                        base_lam = rob.m.mu * rob.m.time_multiplier(rob.m.t_now) + rob.m.trigger_mass
                        patrol_lam = np.clip(base_lam - patrol_inhib_retention * rob.m.inhib_mass, 0.0, None)
                        patrol_field_cache["excess"] = patrol_lam - rob.m.mu
                return patrol_field_cache["excess"]

            def _patrol_field_score(x, y):
                """Score a patrol point from the forecast field and configured value weighting."""
                if abs(patrol_inhib_retention - 1.0) <= 1e-12:
                    return _field_score(x, y)
                iy, ix = rob.m.world_to_idx(x, y)
                return float(_patrol_field_grid()[iy, ix])

            def _patrol_hotspots(top_k, merge_radius, mask_poly):
                """Return filtered forecast hotspots eligible for patrol task generation."""
                if abs(patrol_inhib_retention - 1.0) <= 1e-12:
                    return rob.m.hotspots(
                        top_k=top_k,
                        merge_radius=merge_radius,
                        use_excess=True,
                        mask_poly=mask_poly,
                    )
                field = _patrol_field_grid()
                k_short = min(field.size, max(5 * int(top_k), int(top_k)))
                flat_idx = np.argpartition(field.ravel(), -k_short)[-k_short:]
                flat_sorted = flat_idx[np.argsort(field.ravel()[flat_idx])[::-1]]
                picks = []
                coords = []
                for idx in flat_sorted:
                    iy, ix = divmod(idx, rob.m.nx)
                    x = float(rob.m.xs[ix])
                    y = float(rob.m.ys[iy])
                    if mask_poly and (not point_in_polygon(x, y, mask_poly)):
                        continue
                    if any((x - px) ** 2 + (y - py) ** 2 <= merge_radius ** 2 for (px, py) in coords):
                        continue
                    coords.append((x, y))
                    picks.append({"x": x, "y": y, "score": float(field[iy, ix])})
                    if len(picks) >= int(top_k):
                        break
                return picks

            # hotspots from SESTPP excess lambda-mu
            # Get more candidates than we'll keep, then thin for spacing
            mask = rob.zone_polygon if rob.zone_polygon else None
            raw = _patrol_hotspots(
                top_k=max(hotspot_top_k * 3, hotspot_top_k),
                merge_radius=max(self.merge_radius_m, hotspot_spacing_m * 0.5),
                mask_poly=mask,
            )
            def _quantile(sorted_vals, pct):
                """Compute a robust quantile threshold for candidate filtering."""
                if not sorted_vals:
                    return float("nan")
                if len(sorted_vals) == 1:
                    return float(sorted_vals[0])
                pos = (len(sorted_vals) - 1) * (float(pct) / 100.0)
                lo = int(math.floor(pos))
                hi = int(math.ceil(pos))
                if lo == hi:
                    return float(sorted_vals[lo])
                frac = pos - lo
                return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)

            raw_scores = sorted(float(h.get("score", 0.0)) for h in raw)
            if filter_mode == "absolute":
                threshold_applied = float(min_hotspot_score)
                filtered_hotspots = [h for h in raw if float(h.get("score", 0.0)) >= threshold_applied]
            elif filter_mode == "percentile":
                threshold_applied = _quantile(raw_scores, percentile)
                filtered_hotspots = (
                    [h for h in raw if float(h.get("score", 0.0)) >= threshold_applied]
                    if math.isfinite(threshold_applied)
                    else []
                )
            else:
                ranked_hotspots = sorted(raw, key=lambda h: float(h.get("score", 0.0)), reverse=True)
                filtered_hotspots = ranked_hotspots[: int(keep_top_k)]
            # Score filter + Poisson-disk style thinning
            cand = [(h['x'], h['y'], h['score']) for h in filtered_hotspots]
            picks = []
            for (hx, hy, hs) in cand:
                if any((hx-px)**2 + (hy-py)**2 <= hotspot_spacing_m**2 for (px,py,_) in picks):
                    continue
                picks.append((hx, hy, hs))

            # avoid hotspots that coincide with deterring clusters
            # Add a tiny deterministic jitter to decorrelate grid alignment.
            if deterring_modes is None:
                deterring_modes = {
                    "formation": {"beta": 0.30, "omega": 800.0, "sigma": 18.0, "w_eta": 1.0, "fixed_cost": 0.0},
                    "laser":     {"beta": 0.45, "omega": 400.0, "sigma": 10.0, "w_eta": 1.5, "fixed_cost": 0.0},
                    "biosonic":  {"beta": 0.25, "omega": 600.0, "sigma": 20.0, "w_eta": 1.2, "fixed_cost": 0.0},
                }
            fixed_deterring_mode = str(predictive_fixed_deterring_mode or "").strip()
            if fixed_deterring_mode.lower() in {"", "none", "auto", "best", "multi", "multicue"}:
                fixed_deterring_mode = ""
            if fixed_deterring_mode and fixed_deterring_mode not in deterring_modes:
                raise ValueError(
                    "predictive_fixed_deterring_mode must be empty/auto or one of "
                    f"{list(deterring_modes.keys())!r}, got: {predictive_fixed_deterring_mode!r}"
                )
            candidate_deterring_modes = (
                [fixed_deterring_mode]
                if fixed_deterring_mode
                else list(deterring_modes.keys())
            )

            def _weight_at(x, y):
                """Evaluate the optional spatial value weight at a candidate point."""
                if weight_fn is not None:
                    return float(weight_fn(x, y))
                # Static value map: edges + coarse blocks (default).
                dist_edge = point_to_poly_distance((x, y), rob.zone_polygon) if rob.zone_polygon else 0.0
                edge_w = value_edge_gain * math.exp(-dist_edge / max(value_edge_scale, 1e-9))
                bx = math.sin(2.0 * math.pi * x / max(value_block_size, 1e-9))
                by = math.sin(2.0 * math.pi * y / max(value_block_size, 1e-9))
                block_w = value_block_gain * (0.5 + 0.5 * bx * by)
                return 1.0 + edge_w + block_w

            def _field_score(x, y):
                """Read the forecast field score around a candidate point."""
                iy, ix = rob.m.world_to_idx(x, y)
                return float(rob.m.lam[iy, ix] - rob.m.mu[iy, ix])

            baseline_grid = rob.m.mu * rob.m.time_multiplier(rob.m.t_now)
            available_excess_integral_grid = (
                np.clip(rob.m.lam - baseline_grid, 0.0, None)
                * _time_integral_factor(rob.m.omega, horizon_s)
            )

            def _risk_confidence(x, y):
                # Map local excess intensity to [0,1) confidence.
                """Convert a model risk score into a bounded predictive confidence value."""
                fs = max(0.0, _field_score(x, y))
                scale = max(float(deterring_risk_scale), 1e-12)
                return 1.0 - math.exp(-fs / scale)

            def _patch_expectation_horizon(x, y, sigma_u, field_name):
                """Estimate expected event mass in a patch over a prediction horizon."""
                rad = int(math.ceil(3.0 * sigma_u / max(rob.m.dx, rob.m.dy)))
                iy, ix = rob.m.world_to_idx(x, y)
                y0 = max(0, iy - rad); y1 = min(rob.m.ny, iy + rad + 1)
                x0 = max(0, ix - rad); x1 = min(rob.m.nx, ix + rad + 1)
                field = rob.m.mu if str(field_name).strip().lower() == "mu" else rob.m.lam
                time_factor = float(rob.m.omega) * (1.0 - math.exp(-horizon_s / max(float(rob.m.omega), 1e-9)))
                delta_a = float(rob.m.dx * rob.m.dy)
                acc = 0.0
                patch_r2 = patch_radius ** 2
                for yy in range(y0, y1):
                    wy = rob.m.ys[yy]
                    for xx in range(x0, x1):
                        wx = rob.m.xs[xx]
                        dxw = wx - x
                        dyw = wy - y
                        if (dxw * dxw + dyw * dyw) > patch_r2:
                            continue
                        k = math.exp(-0.5 * (dxw * dxw + dyw * dyw) / max(sigma_u ** 2, 1e-9))
                        acc += float(field[yy, xx]) * k
                return max(delta_a * time_factor * acc, 1e-9)

            def _patch_expectation_count_window(x, y, sigma_u, field_name):
                # SPRT compares a hard count of detections inside the patch window,
                # so the expected count must use the same hard patch footprint.
                """Estimate recent event support around a candidate patch."""
                rad = int(math.ceil(patch_radius / max(rob.m.dx, rob.m.dy)))
                iy, ix = rob.m.world_to_idx(x, y)
                y0 = max(0, iy - rad); y1 = min(rob.m.ny, iy + rad + 1)
                x0 = max(0, ix - rad); x1 = min(rob.m.nx, ix + rad + 1)
                field = rob.m.mu if str(field_name).strip().lower() == "mu" else rob.m.lam
                time_factor = max(float(count_window_s), 1e-9)
                delta_a = float(rob.m.dx * rob.m.dy)
                acc = 0.0
                patch_r2 = patch_radius ** 2
                for yy in range(y0, y1):
                    wy = rob.m.ys[yy]
                    for xx in range(x0, x1):
                        wx = rob.m.xs[xx]
                        dxw = wx - x
                        dyw = wy - y
                        if (dxw * dxw + dyw * dyw) > patch_r2:
                            continue
                        acc += float(field[yy, xx])
                return max(delta_a * time_factor * acc, 1e-9)

            def _patch_area_in_zone(x, y):
                """Estimate how much of a candidate patch lies inside the robot zone."""
                rad = int(math.ceil(patch_radius / max(rob.m.dx, rob.m.dy)))
                iy, ix = rob.m.world_to_idx(x, y)
                y0 = max(0, iy - rad); y1 = min(rob.m.ny, iy + rad + 1)
                x0 = max(0, ix - rad); x1 = min(rob.m.nx, ix + rad + 1)
                delta_a = float(rob.m.dx * rob.m.dy)
                acc = 0.0
                patch_r2 = patch_radius ** 2
                for yy in range(y0, y1):
                    wy = rob.m.ys[yy]
                    for xx in range(x0, x1):
                        wx = rob.m.xs[xx]
                        dxw = wx - x
                        dyw = wy - y
                        if (dxw * dxw + dyw * dyw) > patch_r2:
                            continue
                        if (mask is not None) and (not point_in_polygon(wx, wy, mask)):
                            continue
                        acc += delta_a
                return max(acc, delta_a)

            def _cost_eta(x, y, w_eta_override=None, fixed_cost=0.0):
                """Estimate travel and service cost for a candidate task."""
                eta_s = None
                if callable(travel_time_fn):
                    try:
                        eta_s = float(travel_time_fn(str(rid), float(x), float(y)))
                    except Exception:
                        eta_s = None
                if eta_s is None or not math.isfinite(float(eta_s)):
                    rx, ry = _robot_pose_guess(rob, robot_pose=(robot_poses or {}).get(rid))
                    dist = math.hypot(x - rx, y - ry)
                    speed = 1.0
                    spin = 0.0
                    if profiles is not None and rid in profiles:
                        prof = profiles[rid]
                        speed = max(float(prof.speed_mps), 1e-6)
                        if spinup_by_type is not None:
                            spin = float(spinup_by_type.get(prof.type, 0.0))
                    eta_s = float(dist / max(speed, 1e-6) + spin)
                w_eta = cost_w_eta if w_eta_override is None else float(w_eta_override)
                return w_eta * float(eta_s) + float(fixed_cost)

            def _eta_seconds(x, y):
                """Estimate travel time between a robot and candidate task location."""
                if callable(travel_time_fn):
                    try:
                        eta_s = float(travel_time_fn(str(rid), float(x), float(y)))
                        if math.isfinite(eta_s):
                            return float(eta_s)
                    except Exception:
                        pass
                rx, ry = _robot_pose_guess(rob, robot_pose=(robot_poses or {}).get(rid))
                dist = math.hypot(x - rx, y - ry)
                speed = 1.0
                spin = 0.0
                if profiles is not None and rid in profiles:
                    prof = profiles[rid]
                    speed = max(float(prof.speed_mps), 1e-6)
                    if spinup_by_type is not None:
                        spin = float(spinup_by_type.get(prof.type, 0.0))
                return float(dist / max(speed, 1e-6) + spin)

            def _patrol_candidate_metrics(x, y):
                """Compute value, confidence, and timing metrics for a patrol candidate."""
                time_factor = _time_integral_factor(rob.m.omega, horizon_s)
                cost_eta = _cost_eta(x, y)
                if patrol_scoring_mode == "shared_response_reduction":
                    shared_detect_range = (
                        max(float(patrol_shared_detection_range_m), 1.0e-6)
                        if patrol_shared_detection_range_m is not None
                        else max(float(self.merge_radius_m), 1.5 * max(float(rob.m.sigma), 1.0e-6))
                    )
                    shared_detection_dwell_s = max(float(patrol_shared_detection_dwell_s), 1.0e-6)
                    shared_response_eta_decay_s = (
                        max(float(patrol_shared_response_eta_decay_s), 1.0e-6)
                        if patrol_shared_response_eta_decay_s is not None
                        else max(shared_detection_dwell_s, 0.10 * float(horizon_s), 1.0)
                    )
                    followup_speed_mps = 1.0
                    if profiles is not None and rid in profiles:
                        followup_speed_mps = max(float(profiles[rid].speed_mps), 1.0e-6)
                    patrol_available_integral_grid = np.clip(_patrol_field_grid(), 0.0, None) * time_factor
                    patrol_summary = estimate_patrol_response_reduction(
                        rob.m,
                        x,
                        y,
                        horizon_s=horizon_s,
                        detect_range_m=shared_detect_range,
                        detect_prob_per_step=float(patrol_shared_detection_prob_per_step),
                        detection_dwell_s=shared_detection_dwell_s,
                        followup_success_prob=float(patrol_shared_followup_success_prob),
                        response_eta_decay_s=shared_response_eta_decay_s,
                        followup_speed_mps=followup_speed_mps,
                        mask_poly=mask,
                        weight_fn=weight_fn,
                        value_edge_gain=value_edge_gain,
                        value_edge_scale=value_edge_scale,
                        value_block_gain=value_block_gain,
                        value_block_size=value_block_size,
                        available_integral_grid=patrol_available_integral_grid,
                    )
                    predicted_delta_j = float(patrol_summary["predicted_reduction_raw"])
                    utility = predicted_delta_j - cost_eta
                    return {
                        "benefit": float(predicted_delta_j),
                        "cost_eta": float(cost_eta),
                        "utility": float(utility),
                        "score": float(utility),
                        "predicted_deltaJ": float(predicted_delta_j),
                        "deltaJ_per_cost": float(predicted_delta_j / max(cost_eta, 1.0e-6)),
                    }

                delta_a = float(rob.m.dx * rob.m.dy)
                benefit = max(0.0, _patrol_field_score(x, y)) * max(_weight_at(x, y), 0.0) * time_factor * delta_a
                utility = benefit - cost_eta
                return {
                    "benefit": float(benefit),
                    "cost_eta": float(cost_eta),
                    "utility": float(utility),
                    "score": float(utility),
                    "predicted_deltaJ": 0.0,
                    "deltaJ_per_cost": 0.0,
                }

            def _event_probability(x, y, sigma_u):
                """Estimate event probability for a predictive deterrence candidate."""
                lam_patch = _patch_expectation_horizon(x, y, sigma_u, "lam")
                lam_patch = max(lam_patch, 0.0)
                return float(1.0 - math.exp(-lam_patch))

            def _habituation_eta_for_candidate(x, y, mode):
                """Return current cue effectiveness for non-STL habituation-aware scoring."""
                if stl_hab is None:
                    return 1.0
                target_cell_id = None
                if callable(stl_cell_id_for_xy_fn):
                    target_cell_id = stl_cell_id_for_xy_fn(float(x), float(y))
                if target_cell_id is None:
                    return 1.0
                mode_id = None
                if stl_mode_to_id is not None:
                    mode_id = dict(stl_mode_to_id).get(str(mode))
                    if mode_id is None:
                        mode_id = dict(stl_mode_to_id).get(mode)
                if mode_id is None:
                    return 1.0
                try:
                    return float(stl_hab.effectiveness(int(target_cell_id), int(mode_id)))
                except Exception:
                    return 1.0

            def _deterrence_candidate_metrics(x, y, mode):
                """Compute predictive deterrence value, cost, confidence, and STL fields."""
                params = deterring_modes.get(mode, {})
                beta = float(params.get("beta", rob.m.alpha_inhib))
                omega_u = float(params.get("omega", rob.m.omega_inhib))
                sigma_u = float(params.get("sigma", rob.m.sigma))
                w_eta = float(params.get("w_eta", cost_w_eta))
                fixed_cost = float(params.get("fixed_cost", 0.0))
                cost_eta = _cost_eta(x, y, w_eta_override=w_eta, fixed_cost=fixed_cost)
                if use_stl_robustness_value:
                    task_stub = {
                        "type": "deterring",
                        "origin": "model_scored",
                        "mode": mode,
                    }
                    completion_lead_s = _eta_seconds(x, y) + max(
                        float(
                            task_action_service_time_s(
                                task_stub,
                                deterring_modes=deterring_modes,
                                default_service_time_s=float(self._default_tau_service_s),
                            )
                        ),
                        0.0,
                    )
                    target_cell_id = None
                    if callable(stl_cell_id_for_xy_fn):
                        target_cell_id = stl_cell_id_for_xy_fn(float(x), float(y))
                    stl_summary = estimate_stl_counterfactual_value(
                        rob.m,
                        x,
                        y,
                        mode=mode,
                        mode_to_id=dict(stl_mode_to_id or {}),
                        hab=stl_hab,
                        spec_params=stl_spec_params,
                        dynamics=stl_dynamics,
                        cell_polys=list(stl_cell_polys or []),
                        local_cell_ids=(
                            (stl_local_cell_ids_by_robot or {}).get(str(rid), [])
                            if stl_local_cell_ids_by_robot is not None
                            else []
                        ),
                        last_service_t_by_cell=dict(stl_last_service_t_by_cell or {}),
                        now_t=float(now_t),
                        completion_lead_s=float(completion_lead_s),
                        weight_fn=weight_fn,
                        target_cell_id=target_cell_id,
                    )
                    stl_u = float(stl_summary.get("predictive_stl_U", 0.0))
                    return {
                        "predicted_reduction_raw": float(stl_u),
                        "predicted_deltaJ": float(stl_u),
                        "cost_eta": float(cost_eta),
                        "utility": float(stl_u),
                        "score": float(stl_u),
                        "deltaJ_per_cost": float(stl_u / max(cost_eta, 1e-6)),
                        "beta": float(beta),
                        "omega_u": float(omega_u),
                        "sigma_u": float(sigma_u),
                        "predictive_stl_U": float(stl_u),
                        "stl_summary": stl_summary,
                    }
                reduction_summary = estimate_counterfactual_reduction(
                    rob.m,
                    x,
                    y,
                    beta_u=beta,
                    sigma_u=sigma_u,
                    omega_u=omega_u,
                    horizon_s=horizon_s,
                    mask_poly=mask,
                    weight_fn=weight_fn,
                    value_edge_gain=value_edge_gain,
                    value_edge_scale=value_edge_scale,
                    value_block_gain=value_block_gain,
                    value_block_size=value_block_size,
                    baseline_grid=baseline_grid,
                    available_integral_grid=available_excess_integral_grid,
                )
                predicted_reduction_raw = float(reduction_summary["predicted_reduction_raw"])
                eta_at_plan = (
                    _habituation_eta_for_candidate(x, y, mode)
                    if use_habituation_aware_legacy_value
                    else 1.0
                )
                predicted_delta_j = float(predicted_reduction_raw) * float(eta_at_plan)
                utility = predicted_delta_j - cost_eta
                return {
                    "predicted_reduction_raw": float(predicted_reduction_raw),
                    "predicted_deltaJ": float(predicted_delta_j),
                    "cost_eta": float(cost_eta),
                    "utility": float(utility),
                    "score": float(utility),
                    "deltaJ_per_cost": float(predicted_delta_j / max(cost_eta, 1e-6)),
                    "beta": float(beta),
                    "omega_u": float(omega_u),
                    "sigma_u": float(sigma_u),
                    "habituation_eta_at_plan": float(eta_at_plan),
                    "reduction_summary": reduction_summary,
                }

            def _deterring_selection_weight(cand):
                """Compute the selection weight used to prioritize model-scored deterrence candidates."""
                llr_val = float(cand.get("llr", 0.0))
                llr_clip = max(min(llr_val, 20.0), -20.0)
                posterior_h1 = 1.0 / (1.0 + math.exp(-llr_clip))
                evidence_margin = max(llr_val - sprt_accept, 0.0)
                margin_conf = evidence_margin / (1.0 + evidence_margin)
                recent_count = max(0.0, float(cand.get("recent_detection_count", 0.0)))
                patch_mu0 = max(float(cand.get("patch_mu0", 1e-6)), 1e-6)
                count_excess_ratio = recent_count / patch_mu0
                excess_conf = 1.0 - math.exp(-max(count_excess_ratio - 1.0, 0.0))
                selection_weight = posterior_h1 * max(margin_conf, excess_conf)
                return (
                    float(selection_weight),
                    float(posterior_h1),
                    float(count_excess_ratio),
                )

            def _cluster_key(x, y):
                """Return the spatial-temporal cluster key for a generated candidate."""
                return (
                    rid,
                    int(round(float(x) / cluster_quant)),
                    int(round(float(y) / cluster_quant)),
                )

            def _candidate_key(origin, x, y):
                """Return the deduplication key for a generated task candidate."""
                return (
                    rid,
                    str(origin).strip().lower(),
                    int(round(float(x) / preventive_quant)),
                    int(round(float(y) / preventive_quant)),
                )

            def _origin_is_detection_cluster(origin):
                """Return whether a candidate originated from clustered detections."""
                return str(origin).strip().lower() == "model_detection_cluster"

            def _origin_is_forecast_hotspot(origin):
                """Return whether a candidate originated from forecast hotspot generation."""
                return str(origin).strip().lower() in ("model_hotspot", "model_border_hotspot")

            def _near_any(x, y, pts, radius2):
                """Return whether a point lies near any recent candidate point."""
                return any(((x - px) ** 2 + (y - py) ** 2) <= radius2 for (px, py) in pts)

            def _collect_border_hotspots(top_k):
                """Collect forecast hotspots near robot-zone borders for shared planning."""
                if top_k <= 0 or mask is None:
                    return []
                field = np.clip(rob.m.lam - rob.m.mu, 0.0, None)
                if field.size <= 0:
                    return []
                shortlist = min(field.size, max(8 * int(top_k), int(top_k)))
                flat_idx = np.argpartition(field.ravel(), -shortlist)[-shortlist:]
                flat_sorted = flat_idx[np.argsort(field.ravel()[flat_idx])[::-1]]
                border_band_m = max(float(self.merge_radius_m), float(hotspot_spacing_m))
                border_min_score = max(float(min_hotspot_score), 0.0)
                border_coords = []
                border_picks = []
                for idx in flat_sorted:
                    iy, ix = divmod(int(idx), rob.m.nx)
                    x = float(rob.m.xs[ix])
                    y = float(rob.m.ys[iy])
                    score = float(field[iy, ix])
                    if score < border_min_score:
                        if border_picks:
                            break
                        continue
                    if (mask is not None) and (not point_in_polygon(x, y, mask)):
                        continue
                    if point_to_poly_distance((x, y), mask) > border_band_m:
                        continue
                    if _near_any(x, y, border_coords, preventive_overlap_radius2):
                        continue
                    border_coords.append((x, y))
                    border_picks.append({"x": x, "y": y, "score": score})
                    if len(border_picks) >= int(top_k):
                        break
                return border_picks

            # ----------------------------------------------------------------
            # Algorithm Block: Task-location seed generation
            # Sources:
            # - clustered recent detections
            # - forecast hotspots
            # - border hotspots
            # ----------------------------------------------------------------
            patrol_candidates = []
            preventive_candidate_seeds = []
            preventive_seed_points = []

            def _register_preventive_seed(x, y, origin, forecast_score=0.0):
                """Record a seed point used to generate preventive deterrence candidates."""
                if _near_any(x, y, preventive_seed_points, preventive_overlap_radius2):
                    return False
                preventive_seed_points.append((float(x), float(y)))
                preventive_candidate_seeds.append(
                    {
                        "x": float(x),
                        "y": float(y),
                        "origin": str(origin),
                        "forecast_score": float(forecast_score),
                    }
                )
                return True

            if enable_model_scored_deterring:
                for (dx, dy) in deterring_points:
                    _register_preventive_seed(dx, dy, "model_detection_cluster", _field_score(dx, dy))
                for (hx, hy, hs) in picks:
                    if float(hs) <= 0.0:
                        continue
                    _register_preventive_seed(hx, hy, "model_hotspot", hs)
                for border_pick in _collect_border_hotspots(max(1, int(math.ceil(keep_top_k / 2.0)))):
                    _register_preventive_seed(
                        border_pick["x"],
                        border_pick["y"],
                        "model_border_hotspot",
                        border_pick["score"],
                    )

            if enable_predictive_patrol_tasks:
                for (hx, hy, hs) in picks:
                    patrol_candidates.append({
                        "type": "patrolling",
                        "x": float(hx),
                        "y": float(hy),
                        "origin": "hotspot",
                        "mode": None,
                        "support": 0,
                        "persistence": 0,
                        "risk_conf": 0.0,
                        "eta_s": _eta_seconds(hx, hy),
                        "cluster_key": None,
                        "candidate_key": None,
                        "forecast_score": float(hs),
                    })

            # ----------------------------------------------------------------
            # Algorithm Block: Preventive candidate scoring and persistence
            # ----------------------------------------------------------------
            preventive_candidates = []
            current_cluster_keys = set()
            current_forecast_keys = set()
            if enable_model_scored_deterring:
                zone_area = float(polygon_area(mask)) if mask else float(
                    (max(rob.m.xs) - min(rob.m.xs) + float(rob.m.dx))
                    * (max(rob.m.ys) - min(rob.m.ys) + float(rob.m.dy))
                )
                zone_area = max(zone_area, float(rob.m.dx * rob.m.dy))
                zone_detection_count = float(len(count_pts))
                prev_robot_states = {
                    key: st
                    for key, st in self._deterring_cluster_state.items()
                    if (key[0] == rid) and ((float(now_t) - float(st.get("last_t", -1e9))) <= persist_gap_s)
                }
                prev_robot_centers = [
                    (
                        key,
                        float(st.get("x", float("nan"))),
                        float(st.get("y", float("nan"))),
                    )
                    for key, st in prev_robot_states.items()
                ]

                for seed in preventive_candidate_seeds:
                    dx = float(seed["x"])
                    dy = float(seed["y"])
                    origin = str(seed.get("origin", "unknown"))
                    support = sum(
                        1 for (rx, ry) in recent_pts
                        if ((rx - dx) ** 2 + (ry - dy) ** 2) <= (self.merge_radius_m ** 2)
                    )
                    recent_detection_count = sum(
                        1 for (rx, ry) in count_pts
                        if ((rx - dx) ** 2 + (ry - dy) ** 2) <= (patch_radius ** 2)
                    )
                    patch_area = _patch_area_in_zone(dx, dy)
                    patch_mu0 = max(zone_detection_count * (patch_area / zone_area), 1e-6)
                    patch_mu1 = float("nan")
                    llr = float("nan")
                    persistence = 1
                    candidate_key = None
                    cluster_key = None
                    obs_count_sum = float("nan")
                    obs_count_windows = float("nan")
                    obs_count_mean = float("nan")

                    if _origin_is_detection_cluster(origin):
                        cluster_key = _cluster_key(dx, dy)
                        candidate_key = cluster_key
                        current_cluster_keys.add(cluster_key)
                        self._diag_increment("model_deterring_cluster_key_total")
                        if cluster_key in prev_robot_states:
                            self._diag_increment("model_deterring_cluster_key_reused")
                        else:
                            churn_match = any(
                                math.isfinite(px)
                                and math.isfinite(py)
                                and ((px - dx) ** 2 + (py - dy) ** 2) <= (self.merge_radius_m ** 2)
                                for _, px, py in prev_robot_centers
                            )
                            if churn_match:
                                self._diag_increment("model_deterring_cluster_key_churn")
                            else:
                                self._diag_increment("model_deterring_cluster_key_new")
                        prev_state = self._deterring_cluster_state.get(cluster_key)
                        if prev_state and (float(now_t) - float(prev_state.get("last_t", -1e9)) <= persist_gap_s):
                            persistence = int(prev_state.get("count", 0)) + 1
                            prev_obs_sum = float(prev_state.get("obs_count_sum", 0.0))
                            prev_obs_windows = float(prev_state.get("obs_count_windows", 0.0))
                        else:
                            persistence = 1
                            prev_obs_sum = 0.0
                            prev_obs_windows = 0.0
                        obs_count_sum = prev_obs_sum + float(recent_detection_count)
                        obs_count_windows = prev_obs_windows + 1.0
                        obs_count_mean = obs_count_sum / max(obs_count_windows, 1.0)
                        patch_mu1 = max(patch_mu0 * 1.25, obs_count_mean)
                        llr_prev = float(prev_state.get("llr", 0.0)) if prev_state else 0.0
                        llr_incr = (
                            float(recent_detection_count)
                            * math.log(max(patch_mu1, 1e-9) / max(patch_mu0, 1e-9))
                            - (patch_mu1 - patch_mu0)
                        )
                        llr = llr_prev + llr_incr
                    else:
                        candidate_key = _candidate_key(origin, dx, dy)
                        current_forecast_keys.add(candidate_key)
                        prev_state = self._deterring_forecast_state.get(candidate_key)
                        if prev_state and (float(now_t) - float(prev_state.get("last_t", -1e9)) <= persist_gap_s):
                            persistence = int(prev_state.get("count", 0)) + 1

                    best_mode = None
                    best_mode_utility = None
                    best_mode_cost = None
                    best_mode_event_prob = None
                    best_mode_deltaJ_per_cost = None
                    best_mode_predicted_deltaJ = None
                    best_mode_score = None
                    best_mode_habituation_eta_at_plan = None
                    mode_variants: list[dict[str, Any]] = []
                    for mode in candidate_deterring_modes:
                        mode_metrics = _deterrence_candidate_metrics(dx, dy, mode)
                        params = deterring_modes.get(mode, {})
                        mode_cost = float(mode_metrics["cost_eta"])
                        sigma_u = float(params.get("sigma", rob.m.sigma))
                        mode_p_event = _event_probability(dx, dy, sigma_u)
                        mode_predicted_deltaJ = float(mode_metrics["predicted_deltaJ"])
                        mode_utility = float(mode_metrics["utility"])
                        mode_score = float(mode_metrics["score"])
                        mode_deltaJ_per_cost = float(mode_metrics["deltaJ_per_cost"])
                        mode_variants.append({
                            "mode": str(mode),
                            "score": float(mode_score),
                            "utility": float(mode_utility),
                            "predicted_deltaJ": float(mode_predicted_deltaJ),
                            "predictive_stl_U": mode_metrics.get("predictive_stl_U"),
                            "habituation_eta_at_plan": mode_metrics.get("habituation_eta_at_plan"),
                            "stl_summary": mode_metrics.get("stl_summary"),
                            "deltaJ_per_cost": float(mode_deltaJ_per_cost),
                            "cost_eta": float(mode_cost),
                            "p_event": float(mode_p_event),
                            "action": task_action_public_dict(
                                {
                                    "type": "deterring",
                                    "origin": origin,
                                    "mode": str(mode),
                                },
                                deterring_modes=deterring_modes,
                                default_service_time_s=float(self._default_tau_service_s),
                            ),
                        })
                        if best_mode is None or mode_utility > best_mode_utility:
                            best_mode = mode
                            best_mode_utility = mode_utility
                            best_mode_score = mode_score
                            best_mode_cost = mode_cost
                            best_mode_event_prob = mode_p_event
                            best_mode_deltaJ_per_cost = mode_deltaJ_per_cost
                            best_mode_predicted_deltaJ = mode_predicted_deltaJ
                            best_mode_habituation_eta_at_plan = mode_metrics.get("habituation_eta_at_plan")

                    if _origin_is_detection_cluster(origin):
                        self._deterring_cluster_state[cluster_key] = {
                            "count": int(persistence),
                            "last_t": float(now_t),
                            "x": float(dx),
                            "y": float(dy),
                            "support": int(support),
                            "llr": float(llr),
                            "last_count_window_start_t": float(now_t - count_window_s),
                            "recent_detection_count": int(recent_detection_count),
                            "patch_area": float(patch_area),
                            "obs_count_sum": float(obs_count_sum),
                            "obs_count_windows": float(obs_count_windows),
                            "obs_count_mean": float(obs_count_mean),
                            "patch_mu0": float(patch_mu0),
                            "patch_mu1": float(patch_mu1),
                            "p_event": float(best_mode_event_prob or 0.0),
                            "deltaJ_per_cost": float(best_mode_deltaJ_per_cost or 0.0),
                        }
                        self._diag_increment("model_deterring_llr_sum", float(llr))
                        self._diag_increment("model_deterring_llr_samples")
                        self.diag_counts["model_deterring_llr_max"] = max(
                            float(self.diag_counts.get("model_deterring_llr_max", float("-inf"))),
                            float(llr),
                        )
                        self._diag_model_deterring_llr_values.append(float(llr))
                    elif _origin_is_forecast_hotspot(origin):
                        self._deterring_forecast_state[candidate_key] = {
                            "count": int(persistence),
                            "last_t": float(now_t),
                            "x": float(dx),
                            "y": float(dy),
                            "support": int(support),
                            "forecast_score": float(seed.get("forecast_score", _field_score(dx, dy))),
                            "recent_detection_count": int(recent_detection_count),
                            "p_event": float(best_mode_event_prob or 0.0),
                            "deltaJ_per_cost": float(best_mode_deltaJ_per_cost or 0.0),
                        }

                    self._diag_increment("model_deterring_p_event_sum", float(best_mode_event_prob or 0.0))
                    self._diag_increment("model_deterring_p_event_samples")
                    self._diag_increment("model_deterring_deltaJ_per_cost_sum", float(best_mode_deltaJ_per_cost or 0.0))
                    self._diag_increment("model_deterring_deltaJ_per_cost_samples")

                    if best_mode is not None:
                        preventive_candidates.append({
                            "type": "deterring",
                            "x": float(dx),
                            "y": float(dy),
                            "origin": origin,
                            "mode": best_mode,
                            "support": int(support),
                            "persistence": int(persistence),
                            "risk_conf": float(_risk_confidence(dx, dy)),
                            "eta_s": _eta_seconds(dx, dy),
                            "cluster_key": cluster_key,
                            "candidate_key": candidate_key,
                            "score": float(best_mode_score or 0.0),
                            "utility": float(best_mode_utility or 0.0),
                            "predicted_deltaJ": float(best_mode_predicted_deltaJ or 0.0),
                            "predictive_stl_U": (
                                float(best_mode_utility or 0.0)
                                if use_stl_robustness_value
                                else None
                            ),
                            "habituation_eta_at_plan": (
                                None if best_mode is None else best_mode_habituation_eta_at_plan
                            ),
                            "llr": float(llr),
                            "recent_detection_count": int(recent_detection_count),
                            "patch_area": float(patch_area),
                            "patch_mu0": float(patch_mu0),
                            "patch_mu1": float(patch_mu1),
                            "p_event": float(best_mode_event_prob or 0.0),
                            "deltaJ_per_cost": float(best_mode_deltaJ_per_cost or 0.0),
                            "cost_eta": float(best_mode_cost or 0.0),
                            "forecast_score": float(seed.get("forecast_score", 0.0)),
                            "predictive_action_variants": list(mode_variants),
                            "predictive_mode_variant_count": int(len(mode_variants)),
                            "predictive_generation_best_mode": best_mode,
                            "predictive_fixed_deterring_mode": fixed_deterring_mode or None,
                        })

                stale_cluster = [
                    key for key, st in self._deterring_cluster_state.items()
                    if (key[0] == rid) and ((float(now_t) - float(st.get("last_t", -1e9))) > 3.0 * persist_gap_s)
                ]
                for key in stale_cluster:
                    self._deterring_cluster_state.pop(key, None)
                    self._last_model_deterring_fire.pop(key, None)

                stale_forecast = [
                    key for key, st in self._deterring_forecast_state.items()
                    if (key[0] == rid) and ((float(now_t) - float(st.get("last_t", -1e9))) > 3.0 * persist_gap_s)
                ]
                for key in stale_forecast:
                    self._deterring_forecast_state.pop(key, None)
                    self._last_model_deterring_fire.pop(key, None)

            # ----------------------------------------------------------------
            # Algorithm Block: Preventive gating and patrol/preventive arbitration
            # ----------------------------------------------------------------
            next_ok = self._next_allowed.get(rid, -1e9)
            if now_t < next_ok and enable_model_scored_deterring:
                self._diag_increment("model_deterring_rejected_cooldown", int(len(preventive_candidates)))
            if now_t >= next_ok and (preventive_candidates or patrol_candidates):
                eligible_deterring_candidates = []
                best_deterring = None
                for cand in preventive_candidates:
                    origin = str(cand.get("origin", "unknown"))
                    origin_is_detection_cluster = _origin_is_detection_cluster(origin)
                    self._diag_increment("model_deterring_candidates_total")
                    self._diag_increment_source("model_deterring_candidates", origin)

                    x = float(cand["x"])
                    y = float(cand["y"])
                    det_metrics = None
                    pred_dj = float(cand.get("predicted_deltaJ", 0.0))
                    if pred_dj <= 0.0:
                        det_metrics = _deterrence_candidate_metrics(x, y, cand.get("mode"))
                        pred_dj = float(det_metrics["predicted_deltaJ"])

                    if gate_policy == "sprt_capacity":
                        if origin_is_detection_cluster:
                            ck = cand.get("cluster_key")
                            if ck is not None:
                                cluster_state = self._deterring_cluster_state.get(ck, {})
                                llr_val = float(cluster_state.get("llr", cand.get("llr", 0.0)))
                            else:
                                llr_val = float(cand.get("llr", 0.0))
                            if llr_val <= sprt_reject:
                                self._diag_increment("model_deterring_rejected_sprt_negative")
                                if ck is not None and ck in self._deterring_cluster_state:
                                    self._deterring_cluster_state[ck]["llr"] = 0.0
                                continue
                            if llr_val < sprt_accept:
                                self._diag_increment("model_deterring_rejected_sprt_pending")
                                continue
                            if llr_val < (sprt_accept + sprt_margin):
                                self._diag_increment("model_deterring_rejected_sprt_margin")
                                continue
                            self._diag_increment("model_deterring_pass_sprt")
                        else:
                            if int(cand.get("persistence", 0)) < persist_min:
                                self._diag_increment("model_deterring_rejected_persistence")
                                continue

                        p_event = float(cand.get("p_event", 0.0))
                        if p_event < chance_threshold:
                            self._diag_increment("model_deterring_rejected_chance")
                            continue
                        self._diag_increment("model_deterring_pass_chance")

                        if pred_dj <= 0.0 or pred_dj < float(min_predicted_deltaJ_for_model_deterring):
                            self._diag_increment("model_deterring_rejected_predicted_deltaJ")
                            continue
                        self._diag_increment("model_deterring_pass_predicted_deltaJ")

                        dj_per_cost = float(cand.get("deltaJ_per_cost", 0.0))
                        if (dj_per_cost <= 0.0) and (det_metrics is not None):
                            dj_per_cost = float(det_metrics["deltaJ_per_cost"])
                        if dj_per_cost < min_deltaJ_per_cost:
                            self._diag_increment("model_deterring_rejected_utility_ratio")
                            continue
                        self._diag_increment("model_deterring_pass_utility_ratio")

                        cap_ready = bool(preventive_capacity_ready_by_robot.get(rid, False))
                        if cap_ready:
                            remaining = float(preventive_capacity_remaining_by_robot.get(rid, 0.0))
                            if remaining < 1.0:
                                self._diag_increment("model_deterring_rejected_capacity")
                                continue
                            self._diag_increment("model_deterring_pass_capacity")
                        else:
                            self._diag_increment("model_deterring_capacity_pending")
                    elif bool(enable_predicted_deltaJ_gate):
                        if pred_dj < float(min_predicted_deltaJ_for_model_deterring):
                            self._diag_increment("model_deterring_rejected_predicted_deltaJ")
                            continue
                        self._diag_increment("model_deterring_pass_predicted_deltaJ")

                    if rid in busy_deterring_robots:
                        cand_support = int(cand.get("support", 0))
                        cand_conf = float(cand.get("risk_conf", 0.0))
                        if (cand_support < busy_support_override) and (cand_conf < busy_risk_override):
                            self._diag_increment("model_deterring_rejected_busy")
                            continue
                    if float(cand.get("eta_s", float("inf"))) > max_eta_s:
                        self._diag_increment("model_deterring_rejected_eta")
                        continue

                    field_val = _field_score(x, y)
                    if (deterring_field_threshold is not None) and (field_val < float(deterring_field_threshold)):
                        self._diag_increment("model_deterring_rejected_field")
                        continue
                    self._diag_increment("model_deterring_pass_field")

                    if gate_policy == "heuristic":
                        conf = float(cand.get("risk_conf", _risk_confidence(x, y)))
                        if conf < float(deterring_risk_threshold):
                            self._diag_increment("model_deterring_rejected_risk")
                            continue
                        self._diag_increment("model_deterring_pass_risk")
                        if int(cand.get("persistence", 0)) < persist_min:
                            self._diag_increment("model_deterring_rejected_persistence")
                            continue
                        if origin_is_detection_cluster:
                            if int(cand.get("support", 0)) < int(deterring_min_recent_points):
                                self._diag_increment("model_deterring_rejected_support")
                                continue
                            self._diag_increment("model_deterring_pass_support")

                    candidate_key = cand.get("candidate_key", cand.get("cluster_key"))
                    if repeat_block_window > 0.0 and origin_is_detection_cluster:
                        has_recent_det = False
                        if recent_deterrence_events:
                            for ev in recent_deterrence_events:
                                dt_ev = float(now_t) - float(ev.get("t", -1e9))
                                if dt_ev < 0.0 or dt_ev > repeat_block_window:
                                    continue
                                dx_ev = x - float(ev.get("x", 0.0))
                                dy_ev = y - float(ev.get("y", 0.0))
                                if (dx_ev * dx_ev + dy_ev * dy_ev) <= repeat_radius2:
                                    has_recent_det = True
                                    break
                        last_fire = self._last_model_deterring_fire.get(candidate_key, None) if candidate_key is not None else None
                        if (not has_recent_det) and (last_fire is not None):
                            has_recent_det = (float(now_t) - float(last_fire.get("t", -1e9))) <= repeat_block_window
                        if has_recent_det:
                            prev_support = int(last_fire.get("support", 0)) if last_fire is not None else 0
                            if int(cand.get("support", 0)) <= prev_support:
                                self._diag_increment("model_deterring_rejected_repeat_no_new_support")
                                continue

                    if det_metrics is None:
                        det_metrics = _deterrence_candidate_metrics(x, y, cand["mode"])
                    utility = float(cand.get("utility", det_metrics["utility"]))
                    cost_eta = float(cand.get("cost_eta", det_metrics["cost_eta"]))
                    score = float(cand.get("score", utility))
                    selection_weight = 1.0
                    posterior_h1 = float("nan")
                    count_excess_ratio = float("nan")
                    if gate_policy == "sprt_capacity" and origin_is_detection_cluster:
                        selection_weight, posterior_h1, count_excess_ratio = _deterring_selection_weight(cand)
                        if selection_weight < min_selection_weight:
                            self._diag_increment("model_deterring_rejected_selection_weight")
                            continue
                        self._diag_increment("model_deterring_pass_selection_weight")
                        score = selection_weight * pred_dj - cost_eta

                    cand_scored = dict(cand)
                    cand_scored["score"] = float(score)
                    cand_scored["utility"] = float(utility)
                    cand_scored["cost_eta"] = float(cost_eta)
                    cand_scored["predicted_deltaJ"] = float(pred_dj)
                    if "predictive_stl_U" in cand:
                        cand_scored["predictive_stl_U"] = cand.get("predictive_stl_U")
                    elif det_metrics is not None and "predictive_stl_U" in det_metrics:
                        cand_scored["predictive_stl_U"] = det_metrics.get("predictive_stl_U")
                    cand_scored["deltaJ_per_cost"] = float(cand.get("deltaJ_per_cost", det_metrics["deltaJ_per_cost"]))
                    cand_scored["selection_weight"] = float(selection_weight)
                    cand_scored["posterior_h1"] = float(posterior_h1)
                    cand_scored["count_excess_ratio"] = float(count_excess_ratio)
                    eligible_deterring_candidates.append(cand_scored)
                    if best_deterring is None or float(score) > float(best_deterring["score"]):
                        best_deterring = cand_scored

                best_patrol = None
                for cand in patrol_candidates:
                    x = float(cand["x"])
                    y = float(cand["y"])
                    field_val = _field_score(x, y)
                    if field_val < min_hotspot_score:
                        continue
                    if any(
                        ((x - float(det_cand.get("x", 0.0))) ** 2 + (y - float(det_cand.get("y", 0.0))) ** 2)
                        <= preventive_overlap_radius2
                        for det_cand in eligible_deterring_candidates
                    ):
                        continue
                    patrol_metrics = _patrol_candidate_metrics(x, y)
                    utility = float(patrol_metrics["utility"])
                    cost_eta = float(patrol_metrics["cost_eta"])
                    score = float(patrol_metrics["score"])
                    cand_scored = dict(cand)
                    cand_scored["score"] = float(score)
                    cand_scored["utility"] = float(utility)
                    cand_scored["cost_eta"] = float(cost_eta)
                    cand_scored["predicted_deltaJ"] = float(patrol_metrics["predicted_deltaJ"])
                    cand_scored["deltaJ_per_cost"] = float(patrol_metrics["deltaJ_per_cost"])
                    cand_scored["selection_weight"] = 1.0
                    cand_scored["posterior_h1"] = float("nan")
                    cand_scored["count_excess_ratio"] = float("nan")
                    if best_patrol is None or float(score) > float(best_patrol["score"]):
                        best_patrol = cand_scored

                best = best_deterring
                det_eligible = int(len(eligible_deterring_candidates))

                if best is not None and best_patrol is not None:
                    if gate_policy == "sprt_capacity":
                        patrol_ref = max(0.0, float(best_patrol["score"]))
                        if float(best["score"]) <= patrol_ref * (1.0 + score_margin):
                            self._diag_increment("model_deterring_rejected_margin")
                            best = best_patrol
                    else:
                        if float(best["score"]) <= float(best_patrol["score"]) + score_margin:
                            self._diag_increment("model_deterring_rejected_margin")
                            best = best_patrol
                elif best is None:
                    best = best_patrol

                if best is not None:
                    _score = float(best["score"])
                    ttype = str(best["type"]).strip().lower()
                    x = float(best["x"])
                    y = float(best["y"])
                    origin = str(best.get("origin", "unknown"))
                    mode = best.get("mode")
                    support = int(best.get("support", 0))
                    if ttype == "patrolling":
                        if rng is not None:
                            jx = float(rng.uniform(-1.0, 1.0)) * jitter_m
                            jy = float(rng.uniform(-1.0, 1.0)) * jitter_m
                        else:
                            import random
                            jx = random.uniform(-1, 1) * jitter_m
                            jy = random.uniform(-1, 1) * jitter_m
                    else:
                        jx = 0.0
                        jy = 0.0
                    task_added = self._add(self._apply_predictive_lead_time_fields({
                        'robot_id': rid,
                        'type': ttype,
                        'x': float(x + jx), 'y': float(y + jy),
                        'time': float(now_t),
                        'origin': origin,
                        'mode': mode,
                        'score': float(_score),
                        'utility': float(best.get("utility", _score)),
                        'support': int(support),
                        'risk_conf': float(best.get("risk_conf", 0.0)),
                        'eta_s': float(best.get("eta_s", 0.0)),
                        'cost_eta': float(best.get("cost_eta", 0.0)),
                        'persistence': int(best.get("persistence", 0)),
                        'predicted_deltaJ': float(best.get("predicted_deltaJ", 0.0)),
                        'predictive_stl_U': best.get("predictive_stl_U"),
                        'habituation_eta_at_plan': best.get("habituation_eta_at_plan"),
                        'stl_summary': best.get("stl_summary"),
                        'p_event': float(best.get("p_event", 0.0)),
                        'deltaJ_per_cost': float(best.get("deltaJ_per_cost", 0.0)),
                        'llr': float(best.get("llr", 0.0)),
                        'selection_weight': float(best.get("selection_weight", 1.0)),
                        'posterior_h1': float(best.get("posterior_h1", float("nan"))),
                        'count_excess_ratio': float(best.get("count_excess_ratio", float("nan"))),
                        'predictive_action_variants': list(best.get("predictive_action_variants", []) or []),
                        'predictive_mode_variant_count': int(best.get("predictive_mode_variant_count", 0)),
                        'predictive_generation_best_mode': best.get("predictive_generation_best_mode"),
                    }, replan_interval_s=float(replan_interval_s or 0.0), forecast_horizon_s=float(horizon_s)))
                    if ttype == "deterring" and task_added:
                        self._diag_increment("model_deterring_generated")
                        self._diag_increment_source("model_deterring_generated", origin)
                        candidate_key = best.get("candidate_key", best.get("cluster_key"))
                        if candidate_key is not None:
                            self._last_model_deterring_fire[candidate_key] = {
                                "t": float(now_t),
                                "support": int(support),
                            }
                    elif ttype == "patrolling" and det_eligible > 0:
                        self._diag_increment("model_deterring_not_selected", int(det_eligible))
                        for det_cand in eligible_deterring_candidates:
                            self._diag_increment_source(
                                "model_deterring_not_selected",
                                str(det_cand.get("origin", "unknown")),
                            )
                    self._next_allowed[rid] = now_t + self._cooldown

            # ----------------------------------------------------------------
            # Algorithm Block: Fallback patrol generation
            # ----------------------------------------------------------------
            if enable_predictive_patrol_tasks and include_fallback_patrol and not self._has_robot_at_time(rid, now_t):
                cx, cy = self._select_fallback_patrol_point(rid, rob)
                self._add(self._apply_predictive_lead_time_fields({
                    'robot_id': rid,
                    'type': 'patrolling',
                    'x': float(cx), 'y': float(cy),
                    'time': float(now_t),
                    'origin': 'fallback',
                    'score': 0.0
                }, replan_interval_s=float(replan_interval_s or 0.0), forecast_horizon_s=float(horizon_s)))

    # -------- utilities --------
    def rows(self):
        """Return the current generated task table."""
        return list(self._rows)

    def clear(self):
        """Remove all generated task rows and reset generator bookkeeping."""
        self._rows.clear()
        self._keys.clear()

    def _has_robot_at_time(self, rid: str, t: float) -> bool:
        # quick presence check by scanning keys (rounded time)
        """Return whether a robot is available for assignment at a candidate time."""
        rt = round(float(t), self._dt)
        for (krid, _kt, _kx, _ky, kt) in self._keys:
            if krid == rid and kt == rt:
                return True
        return False

    def _add(self, task: Dict):
        """Add a task to the assignment queue for an eligible robot."""
        action_value = task.get("action")
        if action_value is None:
            action_value = task_action(
                task,
                deterring_modes=self._deterring_modes,
                default_service_time_s=float(self._default_tau_service_s),
            )
        key = (
            task['robot_id'],
            task['type'],
            round(float(task['x']), self._dx),
            round(float(task['y']), self._dx),
            round(float(task['time']), self._dt),
        )
        if key in self._keys:
            self._record_deduped_task(task, key)
            return False
        self._keys.add(key)
        self._rows.append({
            'robot_id': task['robot_id'],
            'type': task['type'],                         # 'deterring' or 'patrolling'
            'x': float(task['x']),
            'y': float(task['y']),
            'time': float(task['time']),
            'origin': task.get('origin', 'unknown'),      # 'detection'|'hotspot'|'fallback'|'model_*'
            'mode': task.get('mode'),
            'action': action_value,
            'score': float(task.get('score', 0.0)),
            'utility': float(task.get('utility', task.get('score', 0.0))),
            'support': int(task.get('support', 0)),
            'risk_conf': float(task.get('risk_conf', 0.0)),
            'eta_s': float(task.get('eta_s', 0.0)),
            'cost_eta': float(task.get('cost_eta', 0.0)),
            'persistence': int(task.get('persistence', 0)),
            'cluster_key': task.get('cluster_key'),
            'candidate_key': task.get('candidate_key'),
            'predictive_opportunity_key': str(self._predictive_opportunity_key(task) or ""),
            'predicted_deltaJ': float(task.get('predicted_deltaJ', 0.0)),
            'predictive_stl_U': (
                None
                if task.get('predictive_stl_U') is None
                else float(task.get('predictive_stl_U', 0.0))
            ),
            'habituation_eta_at_plan': (
                None
                if task.get('habituation_eta_at_plan') is None
                else float(task.get('habituation_eta_at_plan', 1.0))
            ),
            'stl_summary': task.get('stl_summary'),
            'p_event': float(task.get('p_event', 0.0)),
            'deltaJ_per_cost': float(task.get('deltaJ_per_cost', 0.0)),
            'llr': float(task.get('llr', 0.0)),
            'selection_weight': float(task.get('selection_weight', 1.0)),
            'posterior_h1': float(task.get('posterior_h1', float("nan"))),
            'count_excess_ratio': float(task.get('count_excess_ratio', float("nan"))),
            'lead_time_s': float(task.get('lead_time_s', float("nan"))),
            'predictive_timing_mode': str(task.get('predictive_timing_mode', "")),
            'forecast_event_time': float(task.get('forecast_event_time', float("nan"))),
            'release_time': float(task.get('release_time', float("nan"))),
            'event_time': float(task.get('event_time', float("nan"))),
            'required_arrival_by_t': float(task.get('required_arrival_by_t', float("nan"))),
            'predictive_deadline_slack_s': float(task.get('predictive_deadline_slack_s', float("nan"))),
            'predictive_required_lead_time_s': float(task.get('predictive_required_lead_time_s', float("nan"))),
            'predictive_event_offset_s': float(task.get('predictive_event_offset_s', float("nan"))),
            'predictive_offset_margin_s': float(task.get('predictive_offset_margin_s', float("nan"))),
            'predictive_offset_cap_s': float(task.get('predictive_offset_cap_s', float("nan"))),
            'predictive_action_variants': list(task.get('predictive_action_variants', []) or []),
            'predictive_mode_variant_count': int(task.get('predictive_mode_variant_count', 0)),
            'predictive_generation_best_mode': task.get('predictive_generation_best_mode'),
            'predictive_fixed_deterring_mode': task.get('predictive_fixed_deterring_mode'),
            'predictive_dispatch_resolved_mode': task.get('predictive_dispatch_resolved_mode'),
            'predictive_dispatch_eta_basis': str(task.get('predictive_dispatch_eta_basis', "")),
        })
        return True

class TaskAssigner:
    def __init__(self, robots_state: dict[str, "Robot"], profiles: dict[str, RobotProfile], params: dict | None = None):
        """
        robots_state: your SESTPP Robot objects {id -> Robot}, for zone polygon & current pose.
        profiles:     capability/kinematics {id -> RobotProfile}
        """
        self.R = robots_state
        self.P = profiles
        self.w = {
            "w_cap":   3.0,   # capability / deterrent efficacy weight
            "w_eta":   1.0,   # ETA penalty weight
            "w_stay":  0.5,   # endurance bonus
            "w_zone":  0.3,   # zone ownership bonus
            "w_health":0.2,   # robot health bonus
            "w_prio":  2.0,   # task-priority weight
            "w_load":  0.8,   # active task load penalty
            "w_task_value": 0.0,  # optional task-value term (off by default)
            # task-type priorities
            "prio_deterring": 1.0,
            "prio_patrolling": 0.5,
            # spin-up times
            "uav_spinup_s": 20.0,
            "ugv_spinup_s": 0.0,
            # minimum battery thresholds
            "min_batt_deterring": 0.25,
            "min_batt_patrolling": 0.15,
        }
        if params: self.w.update(params)
        self.load_by_robot: dict[str, int] = {}
        self.robot_poses: dict[str, tuple[float, float]] = {}
        self.travel_time_fn: Callable[[str, float, float], float] | None = None
        self.disabled_robot_ids: set[str] = set()

    def set_load(self, load_by_robot: dict[str, int]):
        """Update the per-robot active task load used by assignment scoring."""
        self.load_by_robot = {str(k): int(v) for k, v in (load_by_robot or {}).items()}

    def set_robot_poses(self, robot_poses: Mapping[str, tuple[float, float]] | None):
        """Update robot poses used by assignment scoring."""
        self.robot_poses = {
            str(k): (float(v[0]), float(v[1]))
            for k, v in (robot_poses or {}).items()
            if v is not None
        }

    def set_travel_time_fn(self, travel_time_fn: Callable[[str, float, float], float] | None):
        """Install an optional travel-time callback for assignment scoring."""
        self.travel_time_fn = travel_time_fn

    def set_disabled_robot_ids(self, robot_ids):
        """Exclude robots that are temporarily out of service from assignment."""
        self.disabled_robot_ids = {str(rid) for rid in (robot_ids or [])}

    # ---------- public API ----------
    def assign_task(self, task: dict, eligible_ids: list[str] | None = None) -> dict | None:
        """
        Returns an assignment dict:
          {task: <task>, primary: <robot_id>, secondary: <robot_id or None>, details: {...}}
        or None if no eligible robot.
        """
        if eligible_ids is not None:
            eligible = [rid for rid in eligible_ids if rid in self.P and self._eligible(self.P[rid], task)]
            scope = "filtered"
        else:
            owner = task.get("robot_id")
            if task_action_kind(task) == "deterring":
                # Deterring response is time-critical: rank all eligible robots globally.
                eligible = [rid for rid in self.P if self._eligible(self.P[rid], task)]
                scope = "global_deterring"
            else:
                local_pool = []
                if owner in self.R:
                    local_pool.append(owner)
                    local_pool.extend([rid for rid in self.R[owner].neighbors if rid not in local_pool])

                # Patrol stays locality-first, then falls back globally.
                eligible = [rid for rid in local_pool if rid in self.P and self._eligible(self.P[rid], task)]
                scope = "local"
                if not eligible:
                    eligible = [rid for rid in self.P if self._eligible(self.P[rid], task)]
                    scope = "global_fallback"
        if not eligible:
            return None

        scored = [(self._score(self.P[rid], task), rid) for rid in eligible]
        scored.sort(reverse=True, key=lambda x: x[0])
        primary = scored[0][1]

        secondary = None
        if task_action_kind(task) == "deterring" and len(scored) > 1:
            # pick a second unit for handoff/sustain (prefer UGV if primary is UAV)
            for _, rid in scored[1:]:
                if self.P[primary].type == "UAV" and self.P[rid].type == "UGV":
                    secondary = rid; break
            if secondary is None:
                secondary = scored[1][1]

        return {
            "task": task,
            "primary": primary,
            "secondary": secondary,
            "details": {"scores": scored[:3], "scope": scope}
        }

    # ---------- helpers ----------
    def _eligible(self, prof: RobotProfile, task: dict) -> bool:
        # battery thresholds by task type
        """Return whether a robot can serve a task under capability and timing constraints."""
        if str(prof.id) in self.disabled_robot_ids:
            return False
        action_kind = task_action_kind(task)
        min_batt = self.w["min_batt_deterring"] if action_kind == "deterring" else self.w["min_batt_patrolling"]
        if prof.battery < min_batt or prof.health < 0.15:
            return False
        if action_kind == "deterring" and not prof.has_deterrent:
            return False
        # (extend here with airspace/terrain checks as needed)
        return True

    def _score(self, prof: RobotProfile, task: dict) -> float:
        """Compute the assignment score for a robot-task pair."""
        w = self.w
        action_kind = task_action_kind(task)
        prio = w["prio_deterring"] if action_kind == "deterring" else w["prio_patrolling"]

        # Distance from robot to task. Use robot anchor or zone centroid as current pose.
        rob = self.R[prof.id]
        eta = None
        if callable(self.travel_time_fn):
            try:
                eta = float(self.travel_time_fn(str(prof.id), float(task["x"]), float(task["y"])))
            except Exception:
                eta = None
        if eta is None or not math.isfinite(float(eta)):
            rx, ry = _robot_pose_guess(rob, robot_pose=self.robot_poses.get(prof.id))
            dist = math.hypot(task["x"] - rx, task["y"] - ry)
            spin = w["uav_spinup_s"] if prof.type == "UAV" else w["ugv_spinup_s"]
            eta = dist / max(prof.speed_mps, 1e-6) + spin

        cap = prof.deterrent_eff if action_kind == "deterring" else 1.0
        zone_bonus = 1.0 if point_in_polygon(task["x"], task["y"], rob.zone_polygon) else 0.0
        load = float(self.load_by_robot.get(prof.id, 0))
        task_value = float(task.get("utility", task.get("score", 0.0)))

        return (w["w_cap"]   * cap
              - w["w_eta"]   * eta
              + w["w_stay"]  * prof.endurance_min
              + w["w_zone"]  * zone_bonus
              + w["w_health"]* prof.health
              + w["w_prio"]  * prio
              + w["w_task_value"] * task_value
              - w["w_load"]  * load)

    def to_tracking_dict(self, *, include_arrays: bool = False, max_items: int = 50):
        """Return a compact tracking snapshot for task generation or assignment state."""
        return {
            "weights": dict(self.w),
            "load_by_robot": dict(self.load_by_robot),
            "robot_poses": dict(self.robot_poses),
            "robot_ids": [str(rid) for rid in self.R.keys()],
            "profile_ids": [str(rid) for rid in self.P.keys()],
            "robots_state": export_tracking_value(
                self.R,
                include_arrays=include_arrays,
                max_items=max_items,
            ),
            "profiles": export_tracking_value(
                self.P,
                include_arrays=include_arrays,
                max_items=max_items,
            ),
        }
