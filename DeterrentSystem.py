import bisect
import math
import random
from collections import deque
from typing import Any, Dict, List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.animation import FuncAnimation
from matplotlib.collections import LineCollection
from matplotlib.patches import Polygon as MplPolygon

from habituation_stl.habituation import HabituationField
from habituation_stl.mission_spec import SpecParams
from habituation_stl.signals import RobotMonitor
from habituation_stl.task_value import Dynamics

try:
    from telemetry_sim import TelemetrySim
    mon: 'TelemetrySim|None' = TelemetrySim(enabled=True)
except Exception:
    mon = None  # telemetry disabled if import fails

from ZonePartitioner import (
    ZonePartitioner,
    build_neighbors,
    health_to_weight,
    point_in_polygon,
    point_to_poly_distance,
    power_cells,
)
from SESTPP import OnlineSESTPP
from Robot import Robot, RobotProfile
from TaskGenerator import TaskGenerator, TaskAssigner
from graph_motion import (
    GraphReservationTable,
    GraphRobotState,
    VineyardMotionGraph,
    infer_active_waypoint_index,
    snap_point_to_graph,
)
from system_structure import (
    DispatchStageResult,
    FeedbackCommunicationStageResult,
    ForecastModelStageResult,
    MetricsStageResult,
    MotionCommand,
    MotionExecutionStageResult,
    TelemetryStageResult,
    TaskGenerationStageResult,
    TruthEventStageResult,
    build_production_runtime_snapshot,
    build_production_system_config,
)
from system_stage_helpers import (
    build_motion_command,
    build_forecast_model_stage_result,
    build_telemetry_stage_result,
    build_truth_generation_stage_result,
    apply_external_motion_feedback,
    publish_motion_commands,
    run_forecast_evaluation_stage,
    run_telemetry_stage,
    run_truth_generation_stage,
)
from planner_profiles import canonicalize_planner_profile_name, get_planner_profile_values
from planner_dispatch import (
    evaluate_model_deterring_dispatch_gating,
    has_direct_detection_conflict,
    passes_busy_fallback_quality,
    select_assignment,
)
from planner_task_extraction import (
    annotate_predictive_utility_fields,
    build_task_dispatch_candidate_buffer,
    canonical_predictive_confidence_source,
    canonical_predictive_utility_mode,
    compute_predictive_confidence,
    extract_task_candidates_from_sestpp,
    run_task_location_estimation,
)
from planner_task_generation import (
    compute_preventive_capacity_state,
    current_busy_deterring_robots,
    prune_preventive_histories,
)
from planner_task_estimation import cell_exposure_rate
from planner_task_selection import select_preassignment_task_candidates
from calibration_config import load_frozen_sestpp_calibration
from action_schema import (
    task_action,
    task_action_kind,
    task_action_name,
    task_action_public_dict,
    task_action_service_time_s,
)
from tracking_export import export_named_tracking_state


# ============================================================================
# Communication and shared dispatch utilities
# ============================================================================

class EventBus:
    def __init__(self, robots: Dict[str, Robot], bytes_per_boundary_msg: int = 64, bytes_per_intervention_msg: int = 72):
        """Initialize the helper object state used by the production simulator."""
        self.robots = robots
        self.bytes_per_boundary_msg = int(bytes_per_boundary_msg)
        self.bytes_per_intervention_msg = int(bytes_per_intervention_msg)
        self.boundary_msg_count = 0
        self.intervention_msg_count = 0
        self.boundary_bytes = 0
        self.intervention_bytes = 0
        self.intervention_msg_dropped_debounce = 0
        self.intervention_msg_dropped_low_weight = 0
        self._last_intervention_key_t = {}
    
    def send_boundary_events(self, events: List[Dict], source_id: str):
        """Publish boundary-sharing events to neighboring robot models."""
        for ev in events:
            rid = ev['target_robot']
            if rid in self.robots and rid != source_id:
                self.boundary_msg_count += 1
                self.boundary_bytes += self.bytes_per_boundary_msg
                self.robots[rid].ingest_boundary_event(
                    x=ev['x'], y=ev['y'], t=ev['t'],
                    weight=ev.get('weight', 0.35), sigma=ev.get('sigma'), omega=ev.get('omega')
                )
    
    def send_intervention_events(
        self,
        events: List[Dict],
        source_id: str,
        min_interval_s: float = 0.0,
        spatial_quant_m: float = 0.0,
        min_weight: float = 0.0,
    ):
        """Publish intervention feedback events to neighboring robot models."""
        min_interval_s = max(0.0, float(min_interval_s))
        spatial_quant_m = float(spatial_quant_m)
        min_weight = float(min_weight)
        for ev in events:
            rid = ev['target_robot']
            if rid in self.robots and rid != source_id:
                w = float(ev.get('weight', 1.0))
                if w < min_weight:
                    self.intervention_msg_dropped_low_weight += 1
                    continue
                if min_interval_s > 0.0:
                    x = float(ev.get('x', 0.0))
                    y = float(ev.get('y', 0.0))
                    t = float(ev.get('t', 0.0))
                    if spatial_quant_m > 1e-9:
                        qx = int(round(x / spatial_quant_m))
                        qy = int(round(y / spatial_quant_m))
                    else:
                        qx = int(round(x))
                        qy = int(round(y))
                    k = (
                        str(source_id),
                        str(rid),
                        qx,
                        qy,
                        None if ev.get('mode') is None else str(ev.get('mode')),
                        ev.get('action_id'),
                    )
                    t_last = float(self._last_intervention_key_t.get(k, -1e18))
                    if (t - t_last) < min_interval_s:
                        self.intervention_msg_dropped_debounce += 1
                        continue
                    self._last_intervention_key_t[k] = t
                self.intervention_msg_count += 1
                self.intervention_bytes += self.bytes_per_intervention_msg
                self.robots[rid].ingest_intervention_event(
                    x=ev['x'], y=ev['y'], t=ev['t'],
                    weight=w,
                    sigma=ev.get('sigma'),
                    omega_inhib=ev.get('omega_inhib'),
                    mode=ev.get('mode'),
                    beta=ev.get('beta'),
                    action_id=ev.get('action_id'),
                )

    def to_tracking_dict(self, *, include_arrays: bool = False, max_items: int = 50):
        """Return a compact tracking snapshot for structured runtime exports."""
        return {
            "robot_ids": [str(rid) for rid in self.robots.keys()],
            "bytes_per_boundary_msg": int(self.bytes_per_boundary_msg),
            "bytes_per_intervention_msg": int(self.bytes_per_intervention_msg),
            "boundary_msg_count": int(self.boundary_msg_count),
            "intervention_msg_count": int(self.intervention_msg_count),
            "boundary_bytes": int(self.boundary_bytes),
            "intervention_bytes": int(self.intervention_bytes),
            "intervention_msg_dropped_debounce": int(self.intervention_msg_dropped_debounce),
            "intervention_msg_dropped_low_weight": int(self.intervention_msg_dropped_low_weight),
            "last_intervention_key_count": int(len(self._last_intervention_key_t)),
            "last_intervention_key_preview": list(self._last_intervention_key_t.items())[: max(int(max_items), 0)],
        }


# ============================================================================
# Task ordering and policy resolution helpers
# ============================================================================

def _is_model_deterring_candidate(task_row: dict) -> bool:
    """Return whether a task row represents a predictive model-scored deterrence action."""
    return (
        task_action_kind(task_row) == "deterring"
        and task_action_name(task_row) != "direct_detection"
    )


def _is_direct_detection_task_row(task_row: dict) -> bool:
    """Return whether a task row represents a reactive direct-detection action."""
    return (
        task_action_kind(task_row) == "deterring"
        and task_action_name(task_row) == "direct_detection"
    )


def _task_stream(task_row: dict) -> str:
    """Classify a task row as reactive or predictive for metrics and dispatch accounting."""
    if _is_direct_detection_task_row(task_row):
        return "reactive"
    return "predictive"


def _predictive_opportunity_key(task_row: dict) -> str:
    """Return the stable opportunity key used to deduplicate predictive work."""
    raw = task_row.get("predictive_opportunity_key")
    if raw is None:
        return ""
    key = str(raw).strip()
    return key


def _count_tasks_by_stream(tasks: list[dict]) -> dict[str, int]:
    """Count reactive and predictive task rows in a task collection."""
    counts = {"reactive": 0, "predictive": 0}
    for task_row in tasks:
        counts[_task_stream(task_row)] = int(counts.get(_task_stream(task_row), 0) + 1)
    return counts


def _finite_task_metric(task_row: dict, key: str, default: float = 0.0) -> float:
    """Read a finite numeric task metric with a safe default fallback."""
    try:
        value = float(task_row.get(key, default))
    except Exception:
        value = float(default)
    if not math.isfinite(value):
        return float(default)
    return float(value)


def _task_has_finite_metric(task_row: dict, key: str) -> bool:
    """Return whether a task row has a finite numeric metric."""
    if key not in task_row:
        return False
    try:
        value = float(task_row.get(key))
    except Exception:
        return False
    return bool(math.isfinite(value))


def _resolve_truth_deterrence_event_params(
    action_spec,
    *,
    use_mode_dependent_truth_suppression: bool,
    beta_true: float,
    sigma_true: float,
    omega_true: float,
) -> tuple[str, float, float, float]:
    """Resolve the mode identity and suppression parameters used by truth events."""
    params = dict(getattr(action_spec, "params", {}) or {})
    mode_label = str(getattr(action_spec, "name", None) or "direct_detection")
    if bool(use_mode_dependent_truth_suppression) and mode_label != "direct_detection" and params:
        return (
            mode_label,
            float(params.get("beta", beta_true)),
            float(params.get("sigma", sigma_true)),
            float(params.get("omega", omega_true)),
        )
    return mode_label, float(beta_true), float(sigma_true), float(omega_true)


def _dispatch_task_value(task_row: dict) -> float:
    """Task-level value used for admission ordering across patrol and preventive tasks."""
    utility = _finite_task_metric(task_row, "utility", float("nan"))
    if math.isfinite(utility):
        return float(utility)
    score = _finite_task_metric(task_row, "score", float("nan"))
    if math.isfinite(score):
        return float(score)
    if _is_model_deterring_candidate(task_row):
        return _finite_task_metric(task_row, "predicted_deltaJ", 0.0)
    return 0.0


def _predictive_deadline_slack_s(task_row: dict, *, now_t: float | None = None) -> float:
    """Compute remaining slack before a predictive task misses its required arrival time."""
    if _task_stream(task_row) != "predictive":
        return float("nan")
    deadline_s = _finite_task_metric(task_row, "required_arrival_by_t", float("nan"))
    if not math.isfinite(deadline_s):
        deadline_s = _finite_task_metric(task_row, "event_time", float("nan"))
    if not math.isfinite(deadline_s):
        existing_slack_s = _finite_task_metric(task_row, "predictive_deadline_slack_s", float("nan"))
        if math.isfinite(existing_slack_s):
            return float(existing_slack_s)
        return float("nan")
    eta_s = max(
        _finite_task_metric(
            task_row,
            "assigned_eta_s",
            _finite_task_metric(task_row, "eta_s", 0.0),
        ),
        0.0,
    )
    service_time_s = max(float(task_action_service_time_s(task_row)), 0.0)
    reference_time_s = (
        float(now_t)
        if now_t is not None and math.isfinite(float(now_t))
        else _finite_task_metric(task_row, "time", 0.0)
    )
    return float(deadline_s - reference_time_s - eta_s - service_time_s)


def _predictive_deadline_slack_with_eta_s(
    task_row: dict,
    *,
    now_t: float | None = None,
    eta_s_override: float | None = None,
) -> float:
    """Compute predictive deadline slack using an explicit travel-time override."""
    if _task_stream(task_row) != "predictive":
        return float("nan")
    deadline_s = _finite_task_metric(task_row, "required_arrival_by_t", float("nan"))
    if not math.isfinite(deadline_s):
        deadline_s = _finite_task_metric(task_row, "event_time", float("nan"))
    if not math.isfinite(deadline_s):
        existing_slack_s = _finite_task_metric(task_row, "predictive_deadline_slack_s", float("nan"))
        if math.isfinite(existing_slack_s):
            return float(existing_slack_s)
        return float("nan")
    eta_s = max(
        float(eta_s_override)
        if eta_s_override is not None and math.isfinite(float(eta_s_override))
        else _finite_task_metric(
            task_row,
            "assigned_eta_s",
            _finite_task_metric(task_row, "eta_s", 0.0),
        ),
        0.0,
    )
    service_time_s = max(float(task_action_service_time_s(task_row)), 0.0)
    reference_time_s = (
        float(now_t)
        if now_t is not None and math.isfinite(float(now_t))
        else _finite_task_metric(task_row, "time", 0.0)
    )
    return float(deadline_s - reference_time_s - eta_s - service_time_s)


def _predictive_deadline_urgency(task_row: dict, *, now_t: float | None = None) -> float:
    """Convert predictive deadline slack into an urgency score."""
    slack_s = _predictive_deadline_slack_s(task_row, now_t=now_t)
    if not math.isfinite(slack_s):
        return 0.0
    if slack_s >= 0.0:
        return float(1.0 / (1.0 + slack_s))
    return float(-1.0 - abs(slack_s))


def _predictive_task_has_expired(
    task_row: dict,
    *,
    now_t: float,
    eta_s: float | None = None,
    predictive_expiry_grace_s: float = 0.0,
) -> bool:
    """Return whether a predictive task is no longer feasible within its deadline grace."""
    slack_s = _predictive_deadline_slack_with_eta_s(
        task_row,
        now_t=float(now_t),
        eta_s_override=eta_s,
    )
    if not math.isfinite(slack_s):
        return False
    return bool(float(slack_s) < -max(float(predictive_expiry_grace_s), 0.0))


def _resolve_dispatch_policy_settings(
    *,
    dispatch_policy: str,
    reservation_fraction: float,
    reservation_window_s: float,
    reactive_override_slack_s: float,
    reservation_softening_alpha: float,
    reservation_age_softening_beta: float = 0.0,
    reservation_age_gate: float = 1.0,
    predictive_selection_policy: str = "utility",
) -> dict[str, float | str]:
    """Validate and normalize dispatch policy settings for the production run."""
    policy = str(dispatch_policy or "unc").strip().lower().replace("_", "-")
    selection = str(predictive_selection_policy or "utility").strip().lower().replace("_", "-")
    if policy in {"res-rand", "resrand"}:
        policy = "res"
        selection = "random"
    if policy in {"res-soft-rand", "ressoft-rand", "ressoftrand"}:
        policy = "res-soft"
        selection = "random"
    if policy in {"res-adaptive-rand", "resadaptive-rand", "resadaptiverand"}:
        policy = "res-adaptive"
        selection = "random"
    if policy in {
        "res-opportunity-cost",
        "resopportunitycost",
        "res-risk-adjusted",
        "resriskadjusted",
    }:
        policy = "res-risk-adjusted"
        if selection == "utility":
            selection = "risk-adjusted"
    if selection not in {"utility", "random", "confidence-weighted", "time-aware", "time-aware-v2", "risk-adjusted"}:
        raise ValueError(
            "predictive_selection_policy must be one of ['utility', 'random', 'confidence-weighted', 'time-aware', 'time-aware-v2', 'risk-adjusted'], "
            f"got: {predictive_selection_policy!r}"
        )
    if policy not in {
        "react",
        "reactive-first",
        "unc",
        "res",
        "res-soft",
        "res-adaptive",
        "res-feasible",
        "res-idle-feasible",
        "res-confidence",
        "res-idle-feasible-confidence",
        "res-risk-adjusted",
    }:
        raise ValueError(
            "dispatch_policy must be one of ['react', 'reactive-first', 'unc', 'res', 'res-soft', 'res-adaptive', "
            "'res-feasible', 'res-idle-feasible', 'res-confidence', 'res-idle-feasible-confidence', 'res-risk-adjusted'], "
            f"got: {dispatch_policy!r}"
        )
    rho = float(reservation_fraction)
    if (not math.isfinite(rho)) or rho < 0.0 or rho > 1.0:
        raise ValueError(
            "reservation_fraction must be finite and lie in [0, 1], "
            f"got: {reservation_fraction!r}"
        )
    window_s = float(reservation_window_s)
    if (not math.isfinite(window_s)) or window_s <= 0.0:
        raise ValueError(
            "reservation_window_s must be finite and > 0, "
            f"got: {reservation_window_s!r}"
        )
    slack_s = float(reactive_override_slack_s)
    if not math.isfinite(slack_s):
        raise ValueError(
            "reactive_override_slack_s must be finite, "
            f"got: {reactive_override_slack_s!r}"
        )
    soft_alpha = float(reservation_softening_alpha)
    if (not math.isfinite(soft_alpha)) or soft_alpha < 0.0:
        raise ValueError(
            "reservation_softening_alpha must be finite and >= 0, "
            f"got: {reservation_softening_alpha!r}"
        )
    age_beta = float(reservation_age_softening_beta)
    if (not math.isfinite(age_beta)) or age_beta < 0.0:
        raise ValueError(
            "reservation_age_softening_beta must be finite and >= 0, "
            f"got: {reservation_age_softening_beta!r}"
        )
    age_gate = float(reservation_age_gate)
    if (not math.isfinite(age_gate)) or age_gate < 0.0:
        raise ValueError(
            "reservation_age_gate must be finite and >= 0, "
            f"got: {reservation_age_gate!r}"
        )
    return {
        "dispatch_policy": str(policy),
        "reservation_fraction": float(rho),
        "reservation_window_s": float(window_s),
        "reactive_override_slack_s": float(slack_s),
        "reservation_softening_alpha": float(soft_alpha),
        "reservation_age_softening_beta": float(age_beta),
        "reservation_age_gate": float(age_gate),
        "predictive_selection_policy": str(selection),
    }

def _mixed_greedy_sort_key(task_row: dict, *, now_t: float | None = None) -> tuple:
    """Unified greedy ordering across reactive and predictive tasks.

    This is intended for the true 'unc' baseline. It does not reserve capacity;
    it simply chooses the currently best task across both streams.
    """
    comp = _dispatch_priority_components(task_row, now_t=now_t)
    stream = _task_stream(task_row)

    if stream == "reactive":
        age_s = 0.0
        if now_t is not None and math.isfinite(float(now_t)):
            age_s = max(0.0, float(now_t) - comp["time"])

        merged_detection_count = max(1, int(task_row.get("merged_detection_count", 1)))
        refresh_count = max(0, int(task_row.get("cluster_refresh_count", 0)))

        # Reactive value is based on task score, age/urgency, support, and ETA.
        # Keep this tuple comparable but not automatically dominant.
        return (
            comp["utility"],
            age_s,
            merged_detection_count,
            refresh_count,
            -comp["eta_s"],
            -comp["time"],
        )

    # Predictive value is based on predicted benefit, efficiency, confidence, and ETA.
    return (
        comp["utility"],
        comp["predicted_deltaJ"],
        comp["deltaJ_per_cost"],
        comp["predictive_deadline_urgency"],
        comp["p_event"],
        comp["selection_weight"],
        comp["support"],
        -comp["eta_s"],
        -comp["time"],
    )

def _reactive_override_slack_seconds(
    task_row: dict,
    *,
    now_t: float,
    reactive_override_slack_s: float,
    eta_s: float,
) -> float:
    """Compute remaining slack before a reactive task should override reserved capacity."""
    age_s = max(0.0, float(now_t) - _finite_task_metric(task_row, "time", float(now_t)))
    return float(reactive_override_slack_s) - float(age_s) - max(float(eta_s), 0.0)


def _reactive_task_priority_key(task_row: dict, *, eta_s: float) -> tuple:
    """Build the priority tuple used to rank reactive direct-detection tasks."""
    merged_detection_count = max(1, int(task_row.get("merged_detection_count", 1)))
    refresh_count = max(0, int(task_row.get("cluster_refresh_count", 0)))
    return (
        merged_detection_count,
        refresh_count,
        -max(float(eta_s), 0.0),
        -_finite_task_metric(task_row, "time", 0.0),
    )


def _select_predictive_task_for_policy(
    predictive_tasks: list[dict],
    *,
    predictive_selection_policy: str,
    rng,
    now_t: float | None = None,
    reactive_pressure: float = 0.0,
    predictive_confidence_source: str = "p_event_times_selection_weight",
    predictive_confidence_power: float = 1.0,
    predictive_deadline_weight: float = 2.0,
    predictive_eta_penalty_weight: float = 0.1,
    predictive_time_score_deadline_scale_s: float = 120.0,
    predictive_time_score_reactive_pressure_weight: float = 5.0,
    predictive_time_score_infeasible_penalty: float = 25.0,
) -> dict | None:
    """Select the best predictive task under the configured predictive selection policy."""
    if not predictive_tasks:
        return None
    policy = str(predictive_selection_policy).strip().lower().replace("_", "-")
    if policy == "random":
        index = int(rng.integers(0, len(predictive_tasks)))
        return predictive_tasks[index]
    if policy == "confidence-weighted":
        return max(
            predictive_tasks,
            key=lambda task_row: _predictive_dispatch_score(
                task_row,
                now_t=now_t,
                reactive_pressure=reactive_pressure,
                predictive_confidence_source=predictive_confidence_source,
                predictive_confidence_power=float(predictive_confidence_power),
                predictive_deadline_weight=predictive_deadline_weight,
                predictive_eta_penalty_weight=predictive_eta_penalty_weight,
                predictive_time_score_deadline_scale_s=predictive_time_score_deadline_scale_s,
                predictive_time_score_reactive_pressure_weight=predictive_time_score_reactive_pressure_weight,
                predictive_time_score_infeasible_penalty=predictive_time_score_infeasible_penalty,
            ),
        )
    if policy == "time-aware":
        return max(
            predictive_tasks,
            key=lambda task_row: _predictive_dispatch_score(
                task_row,
                now_t=now_t,
                reactive_pressure=reactive_pressure,
                predictive_confidence_source=predictive_confidence_source,
                predictive_confidence_power=float(predictive_confidence_power),
                predictive_deadline_weight=predictive_deadline_weight,
                predictive_eta_penalty_weight=predictive_eta_penalty_weight,
                predictive_time_score_deadline_scale_s=predictive_time_score_deadline_scale_s,
                predictive_time_score_reactive_pressure_weight=predictive_time_score_reactive_pressure_weight,
                predictive_time_score_infeasible_penalty=predictive_time_score_infeasible_penalty,
                use_time_aware_score=True,
            ),
        )
    if policy == "time-aware-v2":
        return max(
            predictive_tasks,
            key=lambda task_row: _predictive_dispatch_score(
                task_row,
                now_t=now_t,
                reactive_pressure=reactive_pressure,
                predictive_confidence_source=predictive_confidence_source,
                predictive_confidence_power=float(predictive_confidence_power),
                predictive_deadline_weight=predictive_deadline_weight,
                predictive_eta_penalty_weight=predictive_eta_penalty_weight,
                predictive_time_score_deadline_scale_s=predictive_time_score_deadline_scale_s,
                predictive_time_score_reactive_pressure_weight=predictive_time_score_reactive_pressure_weight,
                predictive_time_score_infeasible_penalty=predictive_time_score_infeasible_penalty,
                use_time_aware_score_v2=True,
            ),
        )
    if policy == "risk-adjusted":
        return max(
            predictive_tasks,
            key=lambda task_row: (
                _finite_task_metric(task_row, "predictive_risk_adjusted_utility", float("-inf")),
                _dispatch_priority_sort_key(task_row, now_t=now_t),
            ),
        )
    return max(
        predictive_tasks,
        key=lambda task_row: _dispatch_priority_sort_key(task_row, now_t=now_t),
    )


def _effective_reservation_fraction(
    *,
    dispatch_policy: str,
    reservation_fraction: float,
    reservation_softening_alpha: float,
    reactive_task_count: int,
    predictive_task_count: int,
    reservation_age_softening_beta: float = 0.0,
    reactive_age_norm: float = 0.0,
) -> float:
    """Compute the reservation fraction after softening or adaptive pressure adjustments."""
    rho = float(max(0.0, min(1.0, float(reservation_fraction))))
    if str(dispatch_policy) not in {"res-soft", "res-adaptive"}:
        return rho
    alpha = float(max(float(reservation_softening_alpha), 0.0))
    age_beta = float(max(float(reservation_age_softening_beta), 0.0))
    total_competing = int(max(0, int(reactive_task_count)) + max(0, int(predictive_task_count)))
    if alpha <= 0.0 and age_beta <= 0.0:
        return rho
    reactive_pressure = (
        float(max(0, int(reactive_task_count))) / float(total_competing)
        if total_competing > 0 else 0.0
    )
    age_norm = max(float(reactive_age_norm), 0.0)
    softened = rho / (1.0 + alpha * reactive_pressure + age_beta * age_norm)
    return float(max(0.0, min(rho, softened)))


def _reactive_age_norm(
    reactive_tasks: list[dict],
    *,
    now_t: float,
    reactive_override_slack_s: float,
    eta_seconds_fn=None,
) -> float:
    """Estimate normalized reactive task age pressure for adaptive dispatch policies."""
    if not reactive_tasks:
        return 0.0
    denom = max(abs(float(reactive_override_slack_s)), 1.0)
    max_age_s = max(
        max(0.0, float(now_t) - _finite_task_metric(task, "time", float(now_t)))
        + (
            max(float(eta_seconds_fn(task)), 0.0)
            if eta_seconds_fn is not None
            else 0.0
        )
        for task in reactive_tasks
    )
    return float(max(0.0, max_age_s / denom))


def _clip01(value: float) -> float:
    """Clamp a numeric value to the inclusive probability range [0, 1]."""
    try:
        value_f = float(value)
    except Exception:
        return 0.0
    if not math.isfinite(value_f):
        return 0.0
    return float(min(max(value_f, 0.0), 1.0))


def _reactive_pressure(reactive_tasks: list[dict]) -> float:
    """Estimate the current reactive workload pressure seen by dispatch."""
    reactive_count = max(0, int(len(reactive_tasks)))
    return float(reactive_count / float(reactive_count + 1))


def _predictive_confidence(
    task_row: dict,
    *,
    predictive_confidence_source: str = "p_event_times_selection_weight",
    predictive_confidence_power: float = 1.0,
) -> float:
    """Read the predictive confidence value used by dispatch ranking."""
    return float(
        compute_predictive_confidence(
            task_row,
            predictive_confidence_source=str(predictive_confidence_source),
            predictive_confidence_power=float(predictive_confidence_power),
        )
    )


def _predictive_delta_j(task_row: dict) -> float:
    """Read the predictive benefit value used by dispatch ranking."""
    for key in ("predicted_deltaJ", "predicted_delta_j", "deltaJ", "delta_j"):
        value = _finite_task_metric(task_row, key, float("nan"))
        if math.isfinite(value):
            return float(max(value, 0.0))
    return float(max(_dispatch_task_value(task_row), 0.0))


def _predictive_task_cost(
    task_row: dict,
    *,
    eta_s: float | None = None,
    predictive_eta_cost_weight: float = 0.1,
    predictive_service_cost_weight: float = 0.05,
) -> float:
    """Estimate the service and opportunity cost of a predictive task."""
    eta_value_s = (
        float(eta_s)
        if eta_s is not None and math.isfinite(float(eta_s))
        else _finite_task_metric(
            task_row,
            "assigned_eta_s",
            _finite_task_metric(task_row, "eta_s", 0.0),
        )
    )
    eta_value_s = max(float(eta_value_s), 0.0)
    service_time_s = max(float(task_action_service_time_s(task_row)), 0.0)
    w_eta = max(float(predictive_eta_cost_weight), 0.0)
    w_service = max(float(predictive_service_cost_weight), 0.0)
    cost = w_eta * eta_value_s + w_service * service_time_s

    for key in ("energy_cost", "cost_energy", "battery_cost", "fixed_cost"):
        extra = _finite_task_metric(task_row, key, float("nan"))
        if math.isfinite(extra) and extra > 0.0:
            cost += float(extra)
            break
    try:
        action_params = dict(task_action(task_row).params)
    except Exception:
        action_params = {}
    fixed_cost = _finite_task_metric(action_params, "fixed_cost", float("nan"))
    if math.isfinite(fixed_cost) and fixed_cost > 0.0:
        cost += float(fixed_cost)

    if cost <= 0.0:
        cost_eta = _finite_task_metric(task_row, "cost_eta", float("nan"))
        if math.isfinite(cost_eta) and cost_eta > 0.0:
            cost = float(cost_eta)
    return float(max(cost, 0.0))


def _reactive_opportunity_cost(
    *,
    reactive_pressure: float,
    reactive_age_norm: float,
    eta_s: float,
    tau_service_s: float,
    predictive_opportunity_cost_weight: float = 0.1,
) -> float:
    """Estimate the opportunity cost imposed by reactive workload."""
    pressure = max(float(reactive_pressure), 0.0)
    age_norm = max(float(reactive_age_norm), 0.0)
    occupation_s = max(float(eta_s), 0.0) + max(float(tau_service_s), 0.0)
    weight = max(float(predictive_opportunity_cost_weight), 0.0)
    return float(weight * pressure * age_norm * occupation_s)


def _predictive_risk_adjusted_utility(
    task_row: dict,
    *,
    now_t: float,
    eta_s: float | None,
    reactive_pressure: float,
    reactive_age_norm: float,
    predictive_confidence_source: str = "p_event_times_selection_weight",
    predictive_confidence_power: float = 1.0,
    predictive_opportunity_cost_weight: float = 0.1,
    predictive_eta_cost_weight: float = 0.1,
    predictive_service_cost_weight: float = 0.05,
) -> dict[str, float]:
    """Compute risk-adjusted utility for predictive dispatch admission."""
    eta_value_s = (
        float(eta_s)
        if eta_s is not None and math.isfinite(float(eta_s))
        else _finite_task_metric(
            task_row,
            "assigned_eta_s",
            _finite_task_metric(task_row, "eta_s", 0.0),
        )
    )
    eta_value_s = max(float(eta_value_s), 0.0)
    service_time_s = max(float(task_action_service_time_s(task_row)), 0.0)
    confidence = _predictive_confidence(
        task_row,
        predictive_confidence_source=str(predictive_confidence_source),
        predictive_confidence_power=float(predictive_confidence_power),
    )
    delta_j = _predictive_delta_j(task_row)
    cost = _predictive_task_cost(
        task_row,
        eta_s=float(eta_value_s),
        predictive_eta_cost_weight=float(predictive_eta_cost_weight),
        predictive_service_cost_weight=float(predictive_service_cost_weight),
    )
    opportunity = _reactive_opportunity_cost(
        reactive_pressure=float(reactive_pressure),
        reactive_age_norm=float(reactive_age_norm),
        eta_s=float(eta_value_s),
        tau_service_s=float(service_time_s),
        predictive_opportunity_cost_weight=float(predictive_opportunity_cost_weight),
    )
    expected_reduction = float(confidence * delta_j)
    utility = float(expected_reduction - cost - opportunity)
    ratio = float(expected_reduction / max(cost, 1.0e-9))
    slack_s = _predictive_deadline_slack_with_eta_s(
        task_row,
        now_t=float(now_t),
        eta_s_override=float(eta_value_s),
    )
    return {
        "confidence": float(confidence),
        "deltaJ": float(delta_j),
        "expected_reduction": float(expected_reduction),
        "eta_s": float(eta_value_s),
        "tau_service_s": float(service_time_s),
        "cost": float(cost),
        "opportunity_cost": float(opportunity),
        "utility": float(utility),
        "cost_ratio": float(ratio),
        "slack_s": float(slack_s),
        "reactive_pressure": float(max(float(reactive_pressure), 0.0)),
        "reactive_age_norm": float(max(float(reactive_age_norm), 0.0)),
    }


def _predictive_feasibility_gates(
    task_row: dict,
    *,
    now_t: float,
    eta_s: float | None,
    reactive_tasks: list[dict],
    reactive_override_slack_s: float,
    eta_seconds_fn=None,
    predictive_confidence_min: float = 0.25,
    predictive_utility_min: float = 0.0,
    predictive_cost_ratio_min: float = 1.0,
    predictive_slack_min_s: float = 15.0,
    predictive_confidence_source: str = "p_event_times_selection_weight",
    predictive_confidence_power: float = 1.0,
    predictive_opportunity_cost_weight: float = 0.1,
    predictive_eta_cost_weight: float = 0.1,
    predictive_service_cost_weight: float = 0.05,
) -> dict[str, float | bool | str]:
    """Evaluate confidence, timing, utility, and cost-ratio gates for predictive tasks."""
    reactive_pressure = _reactive_pressure(reactive_tasks)
    reactive_age_norm = _reactive_age_norm(
        reactive_tasks,
        now_t=float(now_t),
        reactive_override_slack_s=float(reactive_override_slack_s),
        eta_seconds_fn=eta_seconds_fn,
    )
    metrics = _predictive_risk_adjusted_utility(
        task_row,
        now_t=float(now_t),
        eta_s=eta_s,
        reactive_pressure=float(reactive_pressure),
        reactive_age_norm=float(reactive_age_norm),
        predictive_confidence_source=str(predictive_confidence_source),
        predictive_confidence_power=float(predictive_confidence_power),
        predictive_opportunity_cost_weight=float(predictive_opportunity_cost_weight),
        predictive_eta_cost_weight=float(predictive_eta_cost_weight),
        predictive_service_cost_weight=float(predictive_service_cost_weight),
    )
    reason = ""
    if float(metrics["confidence"]) < float(predictive_confidence_min):
        reason = "confidence"
    elif (not math.isfinite(float(metrics["slack_s"]))) or float(metrics["slack_s"]) < float(predictive_slack_min_s):
        reason = "slack"
    elif float(metrics["utility"]) <= float(predictive_utility_min):
        reason = "utility"
    elif float(metrics["cost_ratio"]) < float(predictive_cost_ratio_min):
        reason = "cost_ratio"

    return {
        **metrics,
        "accepted": not bool(reason),
        "reject_reason": str(reason),
    }


def _effective_risk_adjusted_reservation_fraction(
    *,
    reservation_fraction: float,
    mean_predictive_confidence: float,
    reactive_pressure: float,
    reactive_age_norm: float,
    risk_adjusted_reservation_alpha: float = 2.0,
    risk_adjusted_reservation_beta: float = 2.0,
) -> float:
    """Compute the reservation fraction for the risk-adjusted policy."""
    rho0 = float(max(0.0, min(1.0, float(reservation_fraction))))
    c_bar = _clip01(mean_predictive_confidence)
    if c_bar <= 0.0:
        return 0.0
    alpha = max(float(risk_adjusted_reservation_alpha), 0.0)
    beta = max(float(risk_adjusted_reservation_beta), 0.0)
    denom = 1.0 + alpha * max(float(reactive_pressure), 0.0) + beta * max(float(reactive_age_norm), 0.0)
    if denom <= 0.0 or not math.isfinite(denom):
        return 0.0
    return float(max(0.0, min(rho0, rho0 * c_bar / denom)))


def _risk_adjusted_dispatch_diagnostics(
    gate_results: list[dict],
    *,
    rho_eff: float,
    reactive_pressure: float,
    reactive_age_norm: float,
) -> dict[str, float | int]:
    """Summarize risk-adjusted dispatch state for metrics and debugging."""
    rejected_by_reason = {"confidence": 0, "slack": 0, "utility": 0, "cost_ratio": 0}
    confidence_values = []
    utility_values = []
    feasible_confidence_values = []
    for result in gate_results:
        confidence_values.append(float(result.get("confidence", 0.0)))
        utility_values.append(float(result.get("utility", 0.0)))
        if bool(result.get("accepted", False)):
            feasible_confidence_values.append(float(result.get("confidence", 0.0)))
            continue
        reason = str(result.get("reject_reason", ""))
        if reason in rejected_by_reason:
            rejected_by_reason[reason] += 1
    return {
        "predictive_candidates": int(len(gate_results)),
        "rejected_by_confidence": int(rejected_by_reason["confidence"]),
        "rejected_by_slack": int(rejected_by_reason["slack"]),
        "rejected_by_utility": int(rejected_by_reason["utility"]),
        "rejected_by_cost_ratio": int(rejected_by_reason["cost_ratio"]),
        "mean_predictive_confidence": (
            float(np.mean(confidence_values)) if confidence_values else float("nan")
        ),
        "mean_feasible_predictive_confidence": (
            float(np.mean(feasible_confidence_values)) if feasible_confidence_values else 0.0
        ),
        "mean_risk_adjusted_utility": (
            float(np.mean(utility_values)) if utility_values else float("nan")
        ),
        "rho_eff": float(rho_eff),
        "reactive_pressure": float(reactive_pressure),
        "reactive_age_norm": float(reactive_age_norm),
    }


def _predictive_dispatch_score(
    task_row: dict,
    *,
    now_t: float | None = None,
    reactive_pressure: float = 0.0,
    predictive_confidence_source: str = "p_event_times_selection_weight",
    predictive_confidence_power: float = 1.0,
    predictive_deadline_weight: float = 2.0,
    predictive_eta_penalty_weight: float = 0.1,
    predictive_time_score_deadline_scale_s: float = 120.0,
    predictive_time_score_reactive_pressure_weight: float = 5.0,
    predictive_time_score_infeasible_penalty: float = 25.0,
    use_time_aware_score: bool = False,
    use_time_aware_score_v2: bool = False,
) -> float:
    """Compute the scalar score used by confidence-weighted and time-aware dispatch."""
    predicted_delta_j = max(_finite_task_metric(task_row, "predicted_deltaJ", 0.0), 0.0)
    base_value = max(_dispatch_task_value(task_row), predicted_delta_j, 0.0)
    confidence = (
        _predictive_confidence(
            task_row,
            predictive_confidence_source=predictive_confidence_source,
            predictive_confidence_power=float(predictive_confidence_power),
        )
        if _is_model_deterring_candidate(task_row)
        else 1.0
    )
    deadline_urgency = _predictive_deadline_urgency(task_row, now_t=now_t)
    deadline_slack_s = _predictive_deadline_slack_s(task_row, now_t=now_t)
    eta_s = max(
        _finite_task_metric(
            task_row,
            "assigned_eta_s",
            _finite_task_metric(task_row, "eta_s", 0.0),
        ),
        0.0,
    )
    if not use_time_aware_score and not use_time_aware_score_v2:
        return float(
            predicted_delta_j * confidence
            + float(predictive_deadline_weight) * float(deadline_urgency)
            - float(predictive_eta_penalty_weight) * float(eta_s)
        )

    deadline_scale_s = max(float(predictive_time_score_deadline_scale_s), 1.0)
    if not math.isfinite(deadline_slack_s):
        time_factor = 1.0
    elif deadline_slack_s >= 0.0:
        time_factor = deadline_scale_s / (deadline_scale_s + float(deadline_slack_s))
    else:
        miss_ratio = abs(float(deadline_slack_s)) / deadline_scale_s
        time_factor = -float(predictive_time_score_infeasible_penalty) * (1.0 + miss_ratio)

    if use_time_aware_score_v2:
        return float(
            predicted_delta_j * confidence * time_factor
            + float(predictive_deadline_weight) * float(deadline_urgency)
            - float(predictive_eta_penalty_weight) * float(eta_s)
            - float(predictive_time_score_reactive_pressure_weight) * max(float(reactive_pressure), 0.0)
        )

    return float(
        base_value * confidence * time_factor
        + float(predictive_deadline_weight) * float(deadline_urgency)
        - float(predictive_eta_penalty_weight) * float(eta_s)
        - float(predictive_time_score_reactive_pressure_weight) * max(float(reactive_pressure), 0.0)
    )


def _predictive_task_is_feasible(
    task_row: dict,
    *,
    now_t: float,
    predictive_slack_min_s: float,
) -> bool:
    """Return whether a predictive task satisfies dispatch feasibility constraints."""
    slack_s = _predictive_deadline_slack_s(task_row, now_t=now_t)
    return bool(math.isfinite(slack_s) and slack_s >= float(predictive_slack_min_s))


def _select_dispatch_policy_task(
    active_tasks: list[dict],
    *,
    dispatch_policy: str,
    predictive_share: float,
    reservation_fraction: float,
    reactive_override_slack_s: float,
    reservation_softening_alpha: float,
    predictive_selection_policy: str,
    now_t: float,
    eta_seconds_fn,
    rng,
    reservation_age_softening_beta: float = 0.0,
    reservation_age_gate: float = 1.0,
    predictive_slack_min_s: float = 15.0,
    reactive_pressure_max_for_predictive: float = 0.5,
    predictive_confidence_min: float = 0.25,
    predictive_deadline_weight: float = 2.0,
    predictive_eta_penalty_weight: float = 0.1,
    predictive_utility_mode: str = "legacy",
    predictive_confidence_source: str = "p_event_times_selection_weight",
    predictive_confidence_power: float = 1.0,
    predictive_time_score_deadline_scale_s: float = 120.0,
    predictive_time_score_reactive_pressure_weight: float = 5.0,
    predictive_time_score_infeasible_penalty: float = 25.0,
    predictive_utility_min: float = 0.0,
    predictive_cost_ratio_min: float = 1.0,
    predictive_opportunity_cost_weight: float = 0.1,
    predictive_eta_cost_weight: float = 0.1,
    predictive_service_cost_weight: float = 0.05,
    risk_adjusted_reservation_alpha: float = 2.0,
    risk_adjusted_reservation_beta: float = 2.0,
    robot_is_idle: bool = False,
) -> tuple[dict | None, bool]:
    """Select one task from the candidate pool under the configured dispatch policy."""
    reactive_tasks = [task for task in active_tasks if _task_stream(task) == "reactive"]
    predictive_tasks = [task for task in active_tasks if _task_stream(task) == "predictive"]
    reactive_age_norm = _reactive_age_norm(
        reactive_tasks,
        now_t=float(now_t),
        reactive_override_slack_s=float(reactive_override_slack_s),
        eta_seconds_fn=eta_seconds_fn,
    )
    urgent_reactive: list[tuple[float, dict]] = []
    for task in reactive_tasks:
        eta_s = float(eta_seconds_fn(task))
        slack_s = _reactive_override_slack_seconds(
            task,
            now_t=float(now_t),
            reactive_override_slack_s=float(reactive_override_slack_s),
            eta_s=float(eta_s),
        )
        if slack_s <= 0.0:
            urgent_reactive.append((float(slack_s), task))
    if urgent_reactive:
        _slack, urgent_task = min(
            urgent_reactive,
            key=lambda item: (
                item[0],
                -int(item[1].get("merged_detection_count", 1)),
                float(eta_seconds_fn(item[1])),
                _finite_task_metric(item[1], "time", 0.0),
            ),
        )
        return urgent_task, True

    if dispatch_policy == "react":
        if not reactive_tasks:
            return None, False
        return max(
            reactive_tasks,
            key=lambda task: _reactive_task_priority_key(task, eta_s=float(eta_seconds_fn(task))),
        ), False

    if dispatch_policy == "unc":
        if not active_tasks:
            return None, False
        return max(
            active_tasks,
            key=lambda task: _mixed_greedy_sort_key(task, now_t=float(now_t)),
        ), False

    if dispatch_policy == "reactive-first":
        if reactive_tasks:
            return max(
                reactive_tasks,
                key=lambda task: _reactive_task_priority_key(
                    task,
                    eta_s=float(eta_seconds_fn(task)),
                ),
            ), False

        selected_predictive = _select_predictive_task_for_policy(
            predictive_tasks,
            predictive_selection_policy=predictive_selection_policy,
            rng=rng,
            now_t=float(now_t),
            reactive_pressure=0.0,
            predictive_confidence_source=predictive_confidence_source,
            predictive_confidence_power=float(predictive_confidence_power),
            predictive_deadline_weight=float(predictive_deadline_weight),
            predictive_eta_penalty_weight=float(predictive_eta_penalty_weight),
            predictive_time_score_deadline_scale_s=float(predictive_time_score_deadline_scale_s),
            predictive_time_score_reactive_pressure_weight=float(predictive_time_score_reactive_pressure_weight),
            predictive_time_score_infeasible_penalty=float(predictive_time_score_infeasible_penalty),
        )
        return selected_predictive, False

    reactive_pressure = _reactive_pressure(reactive_tasks)

    if dispatch_policy == "res-risk-adjusted":
        gate_results = []
        feasible_predictive_tasks = []
        for task in predictive_tasks:
            eta_s = float(eta_seconds_fn(task))
            gate = _predictive_feasibility_gates(
                task,
                now_t=float(now_t),
                eta_s=float(eta_s),
                reactive_tasks=reactive_tasks,
                reactive_override_slack_s=float(reactive_override_slack_s),
                eta_seconds_fn=eta_seconds_fn,
                predictive_confidence_min=float(predictive_confidence_min),
                predictive_utility_min=float(predictive_utility_min),
                predictive_cost_ratio_min=float(predictive_cost_ratio_min),
                predictive_slack_min_s=float(predictive_slack_min_s),
                predictive_confidence_source=str(predictive_confidence_source),
                predictive_confidence_power=float(predictive_confidence_power),
                predictive_opportunity_cost_weight=float(predictive_opportunity_cost_weight),
                predictive_eta_cost_weight=float(predictive_eta_cost_weight),
                predictive_service_cost_weight=float(predictive_service_cost_weight),
            )
            gate_results.append(gate)
            if bool(gate.get("accepted", False)):
                annotated = dict(task)
                annotated["predictive_confidence"] = float(gate["confidence"])
                annotated["predictive_risk_adjusted_utility"] = float(gate["utility"])
                annotated["predictive_expected_reduction"] = float(gate["expected_reduction"])
                annotated["predictive_cost"] = float(gate["cost"])
                annotated["predictive_opportunity_cost"] = float(gate["opportunity_cost"])
                annotated["predictive_cost_ratio"] = float(gate["cost_ratio"])
                annotated["predictive_deadline_slack_s"] = float(gate["slack_s"])
                feasible_predictive_tasks.append(annotated)

        mean_feasible_confidence = (
            float(np.mean([float(task["predictive_confidence"]) for task in feasible_predictive_tasks]))
            if feasible_predictive_tasks else 0.0
        )
        effective_reservation_fraction = _effective_risk_adjusted_reservation_fraction(
            reservation_fraction=float(reservation_fraction),
            mean_predictive_confidence=float(mean_feasible_confidence),
            reactive_pressure=float(reactive_pressure),
            reactive_age_norm=float(reactive_age_norm),
            risk_adjusted_reservation_alpha=float(risk_adjusted_reservation_alpha),
            risk_adjusted_reservation_beta=float(risk_adjusted_reservation_beta),
        )
        if (
            feasible_predictive_tasks
            and float(predictive_share) < float(effective_reservation_fraction)
            and float(reactive_age_norm) < float(max(float(reservation_age_gate), 0.0))
        ):
            return _select_predictive_task_for_policy(
                feasible_predictive_tasks,
                predictive_selection_policy="risk-adjusted",
                rng=rng,
                now_t=float(now_t),
                reactive_pressure=float(reactive_pressure),
                predictive_confidence_source=predictive_confidence_source,
                predictive_confidence_power=float(predictive_confidence_power),
                predictive_deadline_weight=float(predictive_deadline_weight),
                predictive_eta_penalty_weight=float(predictive_eta_penalty_weight),
                predictive_time_score_deadline_scale_s=float(predictive_time_score_deadline_scale_s),
                predictive_time_score_reactive_pressure_weight=float(predictive_time_score_reactive_pressure_weight),
                predictive_time_score_infeasible_penalty=float(predictive_time_score_infeasible_penalty),
            ), False
        if reactive_tasks:
            return max(
                reactive_tasks,
                key=lambda task: _reactive_task_priority_key(task, eta_s=float(eta_seconds_fn(task))),
            ), False
        return None, False

    effective_reservation_fraction = _effective_reservation_fraction(
        dispatch_policy=str(dispatch_policy),
        reservation_fraction=float(reservation_fraction),
        reservation_softening_alpha=float(reservation_softening_alpha),
        reservation_age_softening_beta=float(reservation_age_softening_beta),
        reactive_task_count=len(reactive_tasks),
        predictive_task_count=len(predictive_tasks),
        reactive_age_norm=float(reactive_age_norm),
    )

    predictive_claim_tasks = list(predictive_tasks)
    if dispatch_policy in {"res-feasible", "res-idle-feasible", "res-idle-feasible-confidence"}:
        predictive_claim_tasks = [
            task for task in predictive_claim_tasks
            if _predictive_task_is_feasible(
                task,
                now_t=float(now_t),
                predictive_slack_min_s=float(predictive_slack_min_s),
            )
        ]
    if dispatch_policy == "res-idle-feasible-confidence":
        predictive_claim_tasks = [
            task for task in predictive_claim_tasks
            if _predictive_confidence(
                task,
                predictive_confidence_source=predictive_confidence_source,
                predictive_confidence_power=float(predictive_confidence_power),
            ) >= float(predictive_confidence_min)
        ]

    if (
        dispatch_policy in {
            "res",
            "res-soft",
            "res-adaptive",
            "res-feasible",
            "res-idle-feasible",
            "res-confidence",
            "res-idle-feasible-confidence",
        }
        and float(predictive_share) < float(effective_reservation_fraction)
        and (
            dispatch_policy != "res-adaptive"
            or float(reactive_age_norm) < float(max(float(reservation_age_gate), 0.0))
        )
        and (
            dispatch_policy not in {"res-idle-feasible", "res-idle-feasible-confidence"}
            or (
                bool(robot_is_idle)
                and float(reactive_pressure) <= float(reactive_pressure_max_for_predictive)
            )
        )
        and predictive_claim_tasks
    ):
        return _select_predictive_task_for_policy(
            predictive_claim_tasks,
            predictive_selection_policy=predictive_selection_policy,
            rng=rng,
            now_t=float(now_t),
            reactive_pressure=float(reactive_pressure),
            predictive_confidence_source=predictive_confidence_source,
            predictive_confidence_power=float(predictive_confidence_power),
            predictive_deadline_weight=float(predictive_deadline_weight),
            predictive_eta_penalty_weight=float(predictive_eta_penalty_weight),
            predictive_time_score_deadline_scale_s=float(predictive_time_score_deadline_scale_s),
            predictive_time_score_reactive_pressure_weight=float(predictive_time_score_reactive_pressure_weight),
            predictive_time_score_infeasible_penalty=float(predictive_time_score_infeasible_penalty),
        ), False

    if reactive_tasks:
        return max(
            reactive_tasks,
            key=lambda task: _reactive_task_priority_key(task, eta_s=float(eta_seconds_fn(task))),
        ), False

    fallback_predictive_tasks = list(predictive_tasks)
    if dispatch_policy in {"res-feasible", "res-idle-feasible", "res-idle-feasible-confidence"}:
        fallback_predictive_tasks = list(predictive_claim_tasks)
    if dispatch_policy in {"res-idle-feasible", "res-idle-feasible-confidence"} and not bool(robot_is_idle):
        fallback_predictive_tasks = []

    selected_predictive = _select_predictive_task_for_policy(
        fallback_predictive_tasks,
        predictive_selection_policy=predictive_selection_policy,
        rng=rng,
        now_t=float(now_t),
        reactive_pressure=float(reactive_pressure),
        predictive_confidence_source=predictive_confidence_source,
        predictive_confidence_power=float(predictive_confidence_power),
        predictive_deadline_weight=float(predictive_deadline_weight),
        predictive_eta_penalty_weight=float(predictive_eta_penalty_weight),
        predictive_time_score_deadline_scale_s=float(predictive_time_score_deadline_scale_s),
        predictive_time_score_reactive_pressure_weight=float(predictive_time_score_reactive_pressure_weight),
        predictive_time_score_infeasible_penalty=float(predictive_time_score_infeasible_penalty),
    )
    return selected_predictive, False


def _dispatch_priority_components(task_row: dict, *, now_t: float | None = None) -> dict:
    """Shared task ordering components for thesis-facing dispatch reporting.

    Direct-detection deterring tasks are handled in a separate absolute-priority
    tier. Within the regular competition tier, both patrol and model-scored
    preventive tasks use the same lexicographic ordering:

    1. task-level utility/score
    2. predicted_deltaJ
    3. deltaJ_per_cost
    4. lower ETA

    Additional existing safety and feasibility protections are still enforced in
    the dispatch admission loop after ordering.
    """
    eta_s = _finite_task_metric(task_row, "eta_s", float("inf"))
    if eta_s < 0.0:
        eta_s = 0.0
    return {
        "utility": float(_dispatch_task_value(task_row)),
        "predicted_deltaJ": float(_finite_task_metric(task_row, "predicted_deltaJ", 0.0)),
        "deltaJ_per_cost": float(_finite_task_metric(task_row, "deltaJ_per_cost", 0.0)),
        "predictive_deadline_urgency": float(_predictive_deadline_urgency(task_row, now_t=now_t)),
        "predictive_deadline_slack_s": float(_predictive_deadline_slack_s(task_row, now_t=now_t)),
        "eta_s": float(eta_s),
        "p_event": float(_finite_task_metric(task_row, "p_event", 0.0)),
        "selection_weight": float(_finite_task_metric(task_row, "selection_weight", 1.0)),
        "support": int(max(0, int(task_row.get("support", 0)))),
        "time": float(_finite_task_metric(task_row, "time", 0.0)),
    }


def _dispatch_priority_sort_key(task_row: dict, *, now_t: float | None = None) -> tuple:
    """Build the default priority tuple used to order dispatch candidates."""
    comp = _dispatch_priority_components(task_row, now_t=now_t)
    return (
        comp["utility"],
        comp["predicted_deltaJ"],
        comp["deltaJ_per_cost"],
        comp["predictive_deadline_urgency"],
        -comp["eta_s"],
        comp["p_event"],
        comp["selection_weight"],
        comp["support"],
        -comp["time"],
    )


def _dispatch_ordering_bucket(task_row: dict) -> str:
    """Assign a dispatch ordering bucket for mixed reactive/predictive ranking."""
    if _is_direct_detection_task_row(task_row):
        return "direct_detection"
    return "regular_competition"


def _ordered_dispatch_candidates(candidate_tasks: list[dict]) -> list[dict]:
    """Return dispatch candidates sorted under the configured ordering policy."""
    direct_candidates = [dict(task) for task in candidate_tasks if _is_direct_detection_task_row(task)]
    regular_candidates = [dict(task) for task in candidate_tasks if not _is_direct_detection_task_row(task)]
    regular_candidates.sort(key=_dispatch_priority_sort_key, reverse=True)
    return direct_candidates + regular_candidates


def _build_dispatch_order_preview(candidate_tasks: list[dict], preview_limit: int = 25) -> list[dict]:
    """Build a compact preview of candidate ordering for structured diagnostics."""
    ordered = _ordered_dispatch_candidates(candidate_tasks)
    preview = []
    for rank, task_row in enumerate(ordered[: max(int(preview_limit), 0)], start=1):
        comp = _dispatch_priority_components(task_row)
        preview.append(
            {
                "rank": int(rank),
                "ordering_bucket": _dispatch_ordering_bucket(task_row),
                "stream": _task_stream(task_row),
                "type": task_row.get("type"),
                "origin": task_row.get("origin"),
                "mode": task_row.get("mode"),
                "action": task_action_public_dict(task_row),
                "score": float(_finite_task_metric(task_row, "score", 0.0)),
                "utility": float(comp["utility"]),
                "predicted_deltaJ": float(comp["predicted_deltaJ"]),
                "predictive_stl_U": task_row.get("predictive_stl_U"),
                "deltaJ_per_cost": float(comp["deltaJ_per_cost"]),
                "predictive_deadline_urgency": float(comp["predictive_deadline_urgency"]),
                "predictive_deadline_slack_s": float(comp["predictive_deadline_slack_s"]),
                "eta_s": float(comp["eta_s"]),
                "p_event": float(comp["p_event"]),
                "selection_weight": float(comp["selection_weight"]),
                "support": int(comp["support"]),
            }
        )
    return preview


def _select_patrol_replacement_task(active_tasks: list[dict], assigned_primary: str, incoming_task: dict) -> dict | None:
    """Choose an active patrol task that may be replaced by higher-value work."""
    patrol_active = [
        tr for tr in active_tasks
        if (
            tr.get("assigned_primary") == assigned_primary
            and str(tr.get("state", "")).strip().lower() == "active"
            and task_action_kind(tr) == "patrolling"
        )
    ]
    if not patrol_active:
        return None
    worst_patrol = min(patrol_active, key=_dispatch_priority_sort_key)
    if _dispatch_priority_sort_key(incoming_task) <= _dispatch_priority_sort_key(worst_patrol):
        return None
    return worst_patrol


# ============================================================================
# Runtime configuration helpers
# ============================================================================

def _resolve_preventive_policy_settings(
    *,
    simulation_mode: str,
    preventive_policy: str | None,
    planner_profile: str,
    planner_profile_values: dict | None,
    enable_model_scored_deterring: bool,
    enable_predicted_deltaJ_gate: bool,
    model_deterring_gate_policy: str,
) -> dict:
    """Normalize preventive planning policy settings and compatibility aliases."""
    profile_values = dict(planner_profile_values or {})
    explicit_policy = str(preventive_policy).strip().lower() if preventive_policy not in (None, "") else ""
    profile_policy = str(profile_values.get("preventive_policy", "")).strip().lower()

    if explicit_policy:
        selected_policy = explicit_policy
        source = "argument"
    elif str(simulation_mode).strip().lower() == "proposed" and profile_policy:
        selected_policy = profile_policy
        source = f"profile:{planner_profile}" if planner_profile else "profile"
    else:
        selected_policy = (
            "off"
            if not bool(enable_model_scored_deterring)
            else str(model_deterring_gate_policy).strip().lower()
        )
        source = "legacy"

    if selected_policy not in {"off", "heuristic", "sprt_capacity"}:
        raise ValueError(
            "preventive_policy must be one of ['off', 'heuristic', 'sprt_capacity'], "
            f"got: {selected_policy!r}"
        )

    # Legacy compatibility: keep accepting the selective policy token in configs/CLI,
    # but route execution back through the older heuristic preventive gate.
    if selected_policy == "sprt_capacity":
        selected_policy = "heuristic"

    resolved = {
        "preventive_policy": str(selected_policy),
        "preventive_policy_source": str(source),
        "enable_model_scored_deterring": bool(enable_model_scored_deterring),
        "enable_predicted_deltaJ_gate": False,
        "model_deterring_gate_policy": "heuristic",
        "selective_preventive_enabled": False,
    }
    if selected_policy == "off":
        resolved["enable_model_scored_deterring"] = False
        resolved["enable_predicted_deltaJ_gate"] = False
    elif selected_policy == "heuristic":
        resolved["enable_model_scored_deterring"] = True
        resolved["model_deterring_gate_policy"] = "heuristic"
    return resolved


def _resolve_calibration_runtime_overrides(
    *,
    simulation_mode: str,
    use_frozen_calibration: bool,
    calibration_ranking_path: str | None,
    calibration_manifest_path: str | None,
    calibration_config_id: str | None,
    planner_profile: str,
    planner_profile_values: dict | None,
    prediction_only_model_overrides: dict | None,
    proposed_model_overrides: dict | None,
    sigma: float,
    omega: float,
    alpha_in: float | None,
    alpha_cross: float | None,
    alpha_inhib: float,
    omega_inhib: float,
    mu_base: float,
    bg_ema: float,
    model_feedback_sigma_scale: float,
    model_feedback_omega_scale: float,
) -> dict:
    """Resolve frozen-calibration parameters for the selected runtime profile."""
    def _normalized_overrides(raw: dict | None) -> dict[str, float]:
        """Return only finite calibration override values for runtime application."""
        if not isinstance(raw, dict):
            return {}
        out: dict[str, float] = {}
        for key in (
            "sigma",
            "omega",
            "alpha_in",
            "alpha_cross",
            "alpha_inhib",
            "omega_inhib",
            "mu_base",
            "bg_ema",
            "model_feedback_sigma_scale",
            "model_feedback_omega_scale",
        ):
            value = raw.get(key)
            if value in (None, ""):
                continue
            try:
                out[key] = float(value)
            except Exception:
                continue
        return out

    mode_key = str(simulation_mode).strip().lower()
    profile_values = dict(planner_profile_values or {})
    profile_requested = bool(profile_values.get("use_frozen_calibration", False)) and (
        mode_key == "proposed"
    )
    requested = bool(use_frozen_calibration) or profile_requested
    resolved_ranking = calibration_ranking_path or profile_values.get("calibration_ranking_path")
    resolved_manifest = calibration_manifest_path or profile_values.get("calibration_manifest_path")
    resolved_config_id = calibration_config_id or profile_values.get("calibration_config_id")
    source = "disabled"
    selected_config = None

    if requested:
        selected_config = load_frozen_sestpp_calibration(
            ranking_path=resolved_ranking,
            manifest_path=resolved_manifest,
            config_id=resolved_config_id,
        )
        selected_model_params = selected_config.params_for_mode(mode_key)
        runtime_overrides = selected_model_params.to_runtime_overrides()
        if "sigma" in runtime_overrides:
            sigma = float(runtime_overrides["sigma"])
        if "omega" in runtime_overrides:
            omega = float(runtime_overrides["omega"])
        if "alpha_in" in runtime_overrides:
            alpha_in = float(runtime_overrides["alpha_in"])
        if "alpha_cross" in runtime_overrides:
            alpha_cross = float(runtime_overrides["alpha_cross"])
        alpha_inhib = float(runtime_overrides["alpha_inhib"])
        omega_inhib = float(runtime_overrides["omega_inhib"])
        mu_base = float(runtime_overrides["mu_base"])
        bg_ema = float(runtime_overrides["bg_ema"])
        model_feedback_sigma_scale = float(runtime_overrides["model_feedback_sigma_scale"])
        model_feedback_omega_scale = float(runtime_overrides["model_feedback_omega_scale"])
        source = "argument" if bool(use_frozen_calibration) else (
            f"profile:{planner_profile}" if planner_profile else "profile"
        )

    mode_overrides = _normalized_overrides(
        proposed_model_overrides if mode_key == "proposed" else prediction_only_model_overrides
    )
    if "sigma" in mode_overrides:
        sigma = float(mode_overrides["sigma"])
    if "omega" in mode_overrides:
        omega = float(mode_overrides["omega"])
    if "alpha_in" in mode_overrides:
        alpha_in = float(mode_overrides["alpha_in"])
    if "alpha_cross" in mode_overrides:
        alpha_cross = float(mode_overrides["alpha_cross"])
    if "alpha_inhib" in mode_overrides:
        alpha_inhib = float(mode_overrides["alpha_inhib"])
    if "omega_inhib" in mode_overrides:
        omega_inhib = float(mode_overrides["omega_inhib"])
    if "mu_base" in mode_overrides:
        mu_base = float(mode_overrides["mu_base"])
    if "bg_ema" in mode_overrides:
        bg_ema = float(mode_overrides["bg_ema"])
    if "model_feedback_sigma_scale" in mode_overrides:
        model_feedback_sigma_scale = float(mode_overrides["model_feedback_sigma_scale"])
    if "model_feedback_omega_scale" in mode_overrides:
        model_feedback_omega_scale = float(mode_overrides["model_feedback_omega_scale"])

    return {
        "use_frozen_calibration": bool(requested),
        "selected_calibration_config_id": (
            str(selected_config.config_id) if selected_config is not None else ""
        ),
        "selected_calibration_source": str(source),
        "selected_calibration_summary_metrics": (
            dict(selected_config.summary_metrics) if selected_config is not None else {}
        ),
        "calibration_ranking_path": (None if resolved_ranking in (None, "") else str(resolved_ranking)),
        "calibration_manifest_path": (None if resolved_manifest in (None, "") else str(resolved_manifest)),
        "calibration_config_id": (None if resolved_config_id in (None, "") else str(resolved_config_id)),
        "sigma": float(sigma),
        "omega": float(omega),
        "alpha_in": (None if alpha_in is None else float(alpha_in)),
        "alpha_cross": (None if alpha_cross is None else float(alpha_cross)),
        "alpha_inhib": float(alpha_inhib),
        "omega_inhib": float(omega_inhib),
        "mu_base": float(mu_base),
        "bg_ema": float(bg_ema),
        "model_feedback_sigma_scale": float(model_feedback_sigma_scale),
        "model_feedback_omega_scale": float(model_feedback_omega_scale),
    }


# ============================================================================
# Fleet and zone construction helpers
# ============================================================================

def make_robot_profiles(robots_def, rng, uav_fraction=0.4):
    """
    robots_def: [{'id','anchor','health'}, ...]
    Returns profiles: {id -> RobotProfile}
    """
    profiles = {}
    for r in robots_def:
        rid = r['id']
        health = float(r['health'])
        battery = float(rng.uniform(0.5, 0.95))   # demo range; replace with real metrics

        # Assign a type (demo: mix UAV/UGV)
        is_uav = rng.uniform() < uav_fraction
        if is_uav:
            prof = RobotProfile(
                id=rid, type='UAV',
                speed_mps=12.0,           # demo; set from your spec
                endurance_min=12,         # demo
                battery=battery,
                health=health,
                has_deterrent=True,
                deterrent_eff=1.0
            )
        else:
            prof = RobotProfile(
                id=rid, type='UGV',
                speed_mps=2.5,            # demo ground speed
                endurance_min=120,        # demo
                battery=battery,
                health=health,
                has_deterrent=True,       # flip to False if some UGVs lack deterrents
                deterrent_eff=0.7
            )
        profiles[rid] = prof
    return profiles


def build_fleet_and_zones(W, H, rng, Nrobots=None,
                          mode="direct", scale=800.0, gamma=1.0,
                          NX=100, NY=80,
                          sigma=15.0, omega=600.0,
                          omega_inhib=900.0,
                          alpha_in=0.25, alpha_cross=0.10,
                          alpha_inhib=0.45,
                          mu_base=5e-5, bg_ema=1e-6,
                          border_radius_m=None):
    """
    Returns:
      robots_def: list of seed dicts [{'id','anchor','health'}]
      profiles:   {id -> RobotProfile}
      robots:     {id -> Robot}  (SESTPP wrappers)
      cells:      list[polygon] per robot (power diagram zones)
      nbrs:       neighbor index graph
    """
    # --- random anchors + health (replace with your real inputs) ---
    if Nrobots is None:
        Nrobots = rng.integers(4, 8)
    robots_def = []
    for i in range(Nrobots):
        x = float(rng.uniform(0.1*W, 0.9*W))
        y = float(rng.uniform(0.1*H, 0.9*H))
        health = float(rng.uniform(0.2, 1.0))
        robots_def.append({"id": f"r{i+1}", "anchor": (x,y), "health": health})

    # --- profiles (types/capabilities/kinematics) ---
    profiles = make_robot_profiles(robots_def, rng, uav_fraction=0.4)

    # --- power (Laguerre) diagram from anchors + healthâ†’weights ---
    boundary = [(0,0),(W,0),(W,H),(0,H)]
    anchors  = [r["anchor"] for r in robots_def]
    healths  = [r["health"] for r in robots_def]

    # If you have the auto-scaling helper, use it; otherwise keep scale as-is:
    # scale = auto_weight_scale(anchors, healths, mode=mode, gamma=gamma, desired_shift_m=30.0)
    weights  = [health_to_weight(h, mode=mode, scale=scale, gamma=gamma) for h in healths]

    cells = power_cells(anchors, weights, boundary)
    nbrs  = build_neighbors(cells)

    # --- build SESTPP models + Robot wrappers ---
    X_MIN, X_MAX = 0.0, W
    Y_MIN, Y_MAX = 0.0, H
    robots = {}
    for i, r in enumerate(robots_def):
        model = OnlineSESTPP(X_MIN, X_MAX, Y_MIN, Y_MAX, NX, NY,
                             sigma=sigma, omega=omega, omega_inhib=omega_inhib,
                             alpha_in=alpha_in, alpha_cross=alpha_cross, alpha_inhib=alpha_inhib,
                             mu_base=mu_base, bg_ema=bg_ema)
        neighbors = [robots_def[j]['id'] for j in nbrs[i]]

        # border relay radius: sensible default from sigma if not passed
        br = border_radius_m if border_radius_m is not None else max(10.0, 1.5*sigma)

        robots[r['id']] = Robot(r['id'], model, cells[i], neighbors, border_radius_m=br)

    return robots_def, profiles, robots, cells, nbrs

"""
Method to simulate a test scenario for the deterrent system with multiple robots,
including health-based zone partitioning, detection ingestion, and task generation.
Inputs:
- W, H: Dimensions of the area.
- Nrobots: Number of robots (if None, randomly chosen between 4 and 7).
- seed: Random seed for reproducibility.
- mode, scale, gamma: Parameters for health-to-weight conversion.
- NX, NY: Grid dimensions for the SESTPP model.
- T_end: End time of the simulation.
- base_rate: Base detection rate per unit area per time.
- burst_prob: Probability of a flock burst event at each time step.
- health_drop_time, health_drop_factor: Parameters for simulating health drops (not implemented in this snippet).
Outputs:
- Visualization of the zone partitioning, robot anchors, detections, and predictive hotspots.
"""

# A very light recent-tasks buffer for the plot.

# ============================================================================
# Lightweight runtime buffers and the core simulation entrypoint
# ============================================================================

class RecentTasks:
    def __init__(self, maxlen=60):
        """Initialize the helper object state used by the production simulator."""
        self.buf = deque(maxlen=maxlen)
    def extend(self, tasks):
        """Append a sequence of timestamped items to the bounded time list."""
        self.buf.extend(tasks)
    def list(self):
        """Return the current items from the bounded time list as a standard list."""
        return list(self.buf)


def _build_demo_tracking_links(active_tasks: list[dict], motion_commands: list[MotionCommand]) -> dict[str, Any]:
    """Build robot-to-task link summaries used by tracking exports."""
    active_task_ids_by_robot: dict[str, list[int]] = {}
    for task in active_tasks:
        if str(task.get("state", "")).strip().lower() != "active":
            continue
        rid = task.get("assigned_primary")
        task_id = task.get("id")
        if rid in (None, "") or task_id is None:
            continue
        active_task_ids_by_robot.setdefault(str(rid), []).append(int(task_id))

    current_task_ids_by_robot: dict[str, int] = {}
    for command in motion_commands:
        if command.assigned_task_id is None:
            continue
        if str(command.command_type).strip().lower() not in {"move", "hold"}:
            continue
        current_task_ids_by_robot[str(command.robot_id)] = int(command.assigned_task_id)

    queued_task_ids_by_robot: dict[str, list[int]] = {}
    for rid, task_ids in active_task_ids_by_robot.items():
        current_id = current_task_ids_by_robot.get(rid)
        queued_task_ids_by_robot[rid] = [task_id for task_id in task_ids if task_id != current_id]

    return {
        "active_task_ids_by_robot": active_task_ids_by_robot,
        "current_task_ids_by_robot": current_task_ids_by_robot,
        "queued_task_ids_by_robot": queued_task_ids_by_robot,
    }

def run_simulation_frames_persistent(
    # Field / timing
    W=220.0, H=140.0, seed=123, dt=1.0, T_end=240.0, fps=10,
    # Fleet
    Nrobots=6, uav_fraction=0.0,
    # Zones (health â†’ weight), anchored to **initial positions**
    mode="direct", scale=1500.0, gamma=1.0,
    health_threshold=0.25,   # trigger-only partitioning (optional)
    debug_zone_areas=False,
    # SESTPP grid / calibration-managed model fallback
    NX=120, NY=96, sigma=16.0, omega=700.0, omega_inhib=900.0, mu_base=5e-5, bg_ema=1e-6,
    alpha_in=None, alpha_cross=None,
    alpha_inhib=0.45,
    model_feedback_sigma_scale=1.0,
    model_feedback_omega_scale=1.0,
    # Detections near robots
    detect_rate_per_robot=0.01, detect_sigma_m=10.0,

    bird_stay_mean_s=20.0,       # how long a bird lingers near a robot (exp. mean)
    bird_detection_prob=0.10,    # truth-event observation probability within range; per-step while present in fallback mode
    per_robot_cooldown_s=10.0,   # minimum time between detections for each robot
    max_detections_per_step=2,   # safety cap per step per robot
    
    # Tasks / motion
    task_replan_period_s=10.0, arrival_radius_m=3.0, hold_time_s=20.0, tau_service_s=None,
    predictive_planning_topology="mixed",
    enable_predictive_lead_time=False,
    predictive_timing_mode="synthetic",
    predictive_lead_time_min_s=30.0,
    predictive_lead_time_max_eta_s=120.0,
    predictive_lead_time_buffer_s=15.0,
    predictive_lead_time_risk_power=1.0,
    predictive_expiry_grace_s=0.0,
    # Dynamic task suppression near deterrence
    deterring_suppress_radius_m=20.0,
    deterring_suppress_window_s=60.0,
    # Task refresh pruning
    task_refresh_min_score=1e-4,
    task_max_age_s=120.0,
    enable_direct_detection_task_clustering=True,
    enable_direct_detection_tasks=True,
    direct_detection_task_cluster_radius_m=20.0,
    direct_detection_task_cluster_window_s=60.0,
    direct_detection_task_active_refresh_radius_m=None,
    direct_detection_task_active_refresh_window_s=None,
    direct_detection_task_active_refresh_require_assigned=True,
    direct_detection_task_active_refresh_max_eta_s=45.0,
    direct_detection_task_queued_cluster_radius_m=None,
    direct_detection_task_queued_cluster_window_s=None,
    # Task priority tuning
    w_prio=3.0,
    prio_deterring=2.0,
    prio_patrolling=0.2,
    assigner_w_load=0.8,
    # Optional assignment term to prioritize high-value tasks (off by default).
    enable_assignment_task_value_term=False,
    assigner_w_task_value=0.0,
    planner_profile="",
    preventive_policy=None,
    # Frozen calibration owns the effective model parameters for calibrated modes.
    use_frozen_calibration=False,
    calibration_ranking_path=None,
    calibration_manifest_path=None,
    calibration_config_id=None,
    prediction_only_model_overrides=None,
    proposed_model_overrides=None,
    # Model-scored deterrence gating/budget (realism controls)
    model_deterring_window_s=0.0,
    model_deterring_risk_threshold=0.35,
    model_deterring_risk_scale=1e-4,
    model_deterring_min_recent_points=1,
    model_deterring_field_threshold=None,
    model_deterring_min_persistence_replans=2,
    model_deterring_persistence_max_gap_s=120.0,
    model_deterring_score_margin=0.05,
    model_deterring_repeat_block_window_s=120.0,
    model_deterring_repeat_block_radius_m=25.0,
    model_deterring_max_eta_s=120.0,
    model_deterring_busy_min_support_override=1,
    model_deterring_busy_risk_override=0.20,
    model_deterring_budget_per_robot_per_hr=4,
    # Optional lab-to-prod migration controls (all disabled by default).
    enable_predicted_deltaJ_gate=False,
    min_predicted_deltaJ_for_model_deterring=0.0,
    model_deterring_gate_policy="heuristic",
    model_deterring_sprt_alpha=0.05,
    model_deterring_sprt_beta=0.20,
    model_deterring_sprt_patch_radius_m=None,
    model_deterring_min_sprt_margin=0.0,
    model_deterring_chance_threshold=0.20,
    model_deterring_min_deltaJ_per_cost=0.15,
    model_deterring_min_selection_weight=0.0,
    model_deterring_capacity_rho_max=0.85,
    model_deterring_capacity_history_window_s=3600.0,
    model_deterring_capacity_min_completed_tasks=3,
    model_deterring_capacity_fallback_budget_per_hr=None,
    model_deterring_budget_mode="count_per_hour",
    model_deterring_budget_utility_per_robot_per_hr=5.0,
    auto_enable_proposed_preventive_window=True,
    default_proposed_model_deterring_window_s=120.0,
    # Winner profile toggle: explicit opt-in only.
    enable_winner_profile=False,
    # Planner/dispatch admission controls
    use_split_task_extraction_selection_pipeline=False,
    preassignment_selection_policy="pass_through",
    preassignment_selection_limit=0,
    dispatch_policy="unc",
    reservation_fraction=0.0,
    reservation_window_s=600.0,
    reactive_load_factor_window_s=None,
    reactive_override_slack_s=90.0,
    reservation_softening_alpha=1.0,
    reservation_age_softening_beta=0.0,
    reservation_age_gate=1.0,
    predictive_slack_min_s=15.0,
    reactive_pressure_max_for_predictive=0.5,
    predictive_confidence_min=0.25,
    predictive_deadline_weight=2.0,
    predictive_eta_penalty_weight=0.1,
    predictive_utility_mode="legacy",
    predictive_confidence_source="p_event_times_selection_weight",
    predictive_confidence_power=1.0,
    confidence_source=None,
    confidence_power=None,
    predictive_time_score_deadline_scale_s=120.0,
    predictive_time_score_reactive_pressure_weight=5.0,
    predictive_time_score_infeasible_penalty=25.0,
    predictive_utility_min=0.0,
    predictive_cost_ratio_min=1.0,
    predictive_opportunity_cost_weight=0.1,
    predictive_eta_cost_weight=0.1,
    predictive_service_cost_weight=0.05,
    risk_adjusted_reservation_alpha=2.0,
    risk_adjusted_reservation_beta=2.0,
    predictive_selection_policy="utility",
    defer_predictive_action_selection=False,
    assignment_switch_penalty=1.0,
    zone_assignment_mode="soft",
    max_active_tasks_per_robot=4,
    max_active_patrolling_per_robot=2,
    max_active_model_deterring_per_robot=1,
    preempt_deterring_goals=True,
    preempt_direct_detection_goals=True,
    preempt_model_scored_goals=False,
    use_live_robot_pose_for_task_planning=True,
    model_deterring_global_admission_cap_per_cycle=1,
    model_deterring_require_idle_robot_for_admission=False,
    model_deterring_prefer_idle_robots_for_assignment=True,
    model_deterring_busy_fallback_p_event_min=0.95,
    model_deterring_busy_fallback_deltaJ_per_cost_min=2000000.0,
    model_deterring_busy_fallback_eta_s_max=1.25,
    protect_direct_detection_from_model_deterring=True,
    model_deterring_direct_conflict_radius_m=35.0,
    model_deterring_direct_conflict_window_s=120.0,
    protect_active_model_deterring_persistence=True,
    model_deterring_min_persistence_lifetime_s=180.0,
    model_deterring_persistence_eta_multiplier=2.0,
    model_deterring_persistence_buffer_s=60.0,
    model_deterring_max_persistence_lifetime_s=420.0,
    model_deterring_lock_near_goal_radius_m=10.0,
    protect_active_model_deterring_goal_preemption=True,
    protect_locked_model_deterring_from_patrol_assignment=True,
    # Simulation mode selector
    simulation_mode="proposed",
    # Baseline toggles
    enable_patrolling=None,
    enable_predictive_patrol_tasks=True,
    enable_intervention_feedback=None,
    include_fallback_patrol=None,
    enable_model_scored_deterring=None,
    patrol_hotspot_filter_mode="percentile",
    patrol_hotspot_score_percentile=97.0,
    patrol_hotspot_keep_top_k=None,
    patrol_feedback_inhibition_retention=1.0,
    patrol_scoring_mode="shared_response_reduction",
    patrol_shared_detection_range_m=None,
    patrol_shared_detection_prob_per_step=None,
    patrol_shared_detection_dwell_s=None,
    patrol_shared_followup_success_prob=0.75,
    patrol_shared_response_eta_decay_s=None,
    # Deterring action modes (benefit/cost params)
    deterring_modes=None,
    # Ground-truth event process (event-driven)
    use_ground_truth=True,
    mu_true=1e-6,            # base rate per m^2 per s (scaled by w(x))
    alpha_true=0.3,          # offspring mean per event
    omega_true=600.0,        # temporal decay for offspring + suppression
    sigma_true=12.0,         # spatial spread for offspring + suppression
    beta_true=0.25,          # suppression strength
    use_mode_dependent_truth_suppression=True,
    detect_range_m=30.0,     # detections only within range of robot
    warmup_s=0.0,            # pre-run ground-truth warmup horizon (seeds SESTPP state)
    # Habituation
    habituation_T_rec_s = 1800.0,
    habituation_kappa=0.35,
    habituation_gamma=0.0,
    direct_detection_habituation_mode="laser",
    enable_habituation=True,
    stl_E_star=5.0,
    stl_T_cov_s=1200.0,
    stl_T_react_s=None,
    stl_W_s=600.0,
    stl_eta_min=0.4,
    stl_horizon_s=None,
    stl_monitor_dt_s=30.0,
    stl_theta=12.0,
    stl_smooth=True,
    stl_active_clauses=("exp", "cov", "hab"),
    # Forecast quality metrics
    forecast_horizon_s=300.0,
    forecast_match_radius_m=20.0,
    forecast_top_k=5,
    forecast_eval_period_s=30.0,
    event_viz_window_s=20.0, # seconds of events to keep in plot
    telemetry_dir="telemetry_live",
    telemetry_clear_on_start=True,
    telemetry_prompt_save=True,
    # Metrics
    response_match_radius_m=25.0,
    deterring_eval_radius_m=25.0,
    deterring_eval_window_s=180.0,
    ugv_energy_per_m=1.0,
    uav_energy_per_m=1.0,
    bytes_per_boundary_msg=64,
    bytes_per_intervention_msg=72,
    intervention_boundary_min_interval_s=60.0,
    intervention_boundary_spatial_quant_m=20.0,
    intervention_boundary_min_weight=0.35,
    report_metrics_end=True,
    emit_rejected_model_det_debug=False,
    emit_planning_diagnostics=False,
    planning_hotspot_top_k=5,
    planning_candidate_limit=200,
    # Debug
    debug_movement=False,
    # Vineyard rows (meters)
    row_spacing_m=4.8,
    row_width_m=3.2,
    row_gain=1.5,
    edge_gain=0.6,
    edge_scale_m=40.0,
    # Lane/headland motion params
    headland_m=20.0,
    lane_eps_m=0.5,
    headland_space_m=10.0,
    turn_space_m=8.0,
    row_block_len_m=60.0,
    row_block_gap_m=12.0,
    # Demo motion helper: keep idle robots roaming when no tasks are available.
    idle_roam_enabled=False,
    idle_roam_interval_s=45.0,
    idle_roam_jitter_m=25.0,
    # Motion integration seam: another system may consume commands and own execution.
    motion_orchestration_mode="local",
    motion_planning_mode="lane_projection",
    graph_row_node_spacing_m=12.0,
    graph_headland_node_spacing_m=8.0,
    graph_passing_bay_spacing_m=36.0,
    graph_anchor_snap_radius_m=18.0,
    graph_replan_period_s=10.0,
    graph_reservation_horizon_s=180.0,
    graph_max_detour_ratio=1.75,
    graph_wait_retry_period_s=10.0,
    motion_command_callback=None,
    motion_state_callback=None,
    emit_tracking_state=False,
    tracking_include_arrays=False,
    tracking_preview_limit=50,
    tracking_capture_frame_locals=False,
):
    """Run the reference simulation and emit per-frame runtime snapshots."""

    # ------------------------------------------------------------------------
    # Runtime configuration resolution and validation
    # ------------------------------------------------------------------------
    rng = np.random.default_rng(seed)
    boundary = [(0,0),(W,0),(W,H),(0,H)]
    motion_orchestration_mode = str(motion_orchestration_mode).strip().lower()
    if motion_orchestration_mode not in {"local", "command_only"}:
        raise ValueError(
            "motion_orchestration_mode must be one of ['local', 'command_only'], "
            f"got: {motion_orchestration_mode!r}"
        )
    motion_planning_mode = str(motion_planning_mode).strip().lower()
    if motion_planning_mode not in {"lane_projection", "graph"}:
        raise ValueError(
            "motion_planning_mode must be one of ['lane_projection', 'graph'], "
            f"got: {motion_planning_mode!r}"
        )

    mode_key = str(simulation_mode).lower().strip()
    mode_defaults = {
        "reactive": {
            "enable_patrolling": False,
            "enable_intervention_feedback": False,
            "include_fallback_patrol": False,
            "enable_model_scored_deterring": False,
        },
        "prediction_only": {
            "enable_patrolling": True,
            "enable_intervention_feedback": False,
            "include_fallback_patrol": True,
            "enable_model_scored_deterring": False,
        },
        "proposed": {
            "enable_patrolling": True,
            "enable_intervention_feedback": True,
            "include_fallback_patrol": True,
            "enable_model_scored_deterring": True,
        },
    }
    if mode_key not in mode_defaults:
        raise ValueError(
            f"simulation_mode must be one of {list(mode_defaults.keys())}, got: {simulation_mode!r}"
        )
    if enable_patrolling is None:
        enable_patrolling = mode_defaults[mode_key]["enable_patrolling"]
    if enable_intervention_feedback is None:
        enable_intervention_feedback = mode_defaults[mode_key]["enable_intervention_feedback"]
    if include_fallback_patrol is None:
        include_fallback_patrol = mode_defaults[mode_key]["include_fallback_patrol"]
    if enable_model_scored_deterring is None:
        enable_model_scored_deterring = mode_defaults[mode_key]["enable_model_scored_deterring"]

    # Explicit opt-in winner profile from lab finals (kept off by default).
    if bool(enable_winner_profile):
        enable_assignment_task_value_term = True
        assigner_w_task_value = 0.3
        model_deterring_window_s = 120.0
        model_deterring_risk_threshold = 0.4
        model_deterring_min_persistence_replans = 3
        model_deterring_max_eta_s = 90.0
        model_deterring_score_margin = 0.2
        model_deterring_budget_per_robot_per_hr = 3
        model_deterring_budget_mode = "count_per_hour"
        model_deterring_budget_utility_per_robot_per_hr = 6.0
    planner_profile = canonicalize_planner_profile_name(planner_profile)
    planner_profile_values = {}
    if planner_profile:
        planner_profile_values = get_planner_profile_values(planner_profile)
        enable_assignment_task_value_term = bool(
            planner_profile_values.get("enable_assignment_task_value_term", enable_assignment_task_value_term)
        )
        assigner_w_task_value = float(planner_profile_values.get("assigner_w_task_value", assigner_w_task_value))
        model_deterring_window_s = float(
            planner_profile_values.get("model_deterring_window_s", model_deterring_window_s)
        )
        model_deterring_min_persistence_replans = int(
            planner_profile_values.get(
                "model_deterring_min_persistence_replans",
                model_deterring_min_persistence_replans,
            )
        )
        model_deterring_max_eta_s = float(
            planner_profile_values.get("model_deterring_max_eta_s", model_deterring_max_eta_s)
        )
        model_deterring_score_margin = float(
            planner_profile_values.get("model_deterring_score_margin", model_deterring_score_margin)
        )
        model_deterring_budget_per_robot_per_hr = int(
            planner_profile_values.get(
                "model_deterring_budget_per_robot_per_hr",
                model_deterring_budget_per_robot_per_hr,
            )
        )
        model_deterring_budget_mode = str(
            planner_profile_values.get("model_deterring_budget_mode", model_deterring_budget_mode)
        )
        model_deterring_budget_utility_per_robot_per_hr = float(
            planner_profile_values.get(
                "model_deterring_budget_utility_per_robot_per_hr",
                model_deterring_budget_utility_per_robot_per_hr,
            )
        )
        enable_predicted_deltaJ_gate = bool(
            planner_profile_values.get("enable_predicted_deltaJ_gate", enable_predicted_deltaJ_gate)
        )
        min_predicted_deltaJ_for_model_deterring = float(
            planner_profile_values.get(
                "min_predicted_deltaJ_for_model_deterring",
                min_predicted_deltaJ_for_model_deterring,
            )
        )
        model_deterring_gate_policy = str(
            planner_profile_values.get("model_deterring_gate_policy", model_deterring_gate_policy)
        )
        model_deterring_sprt_alpha = float(
            planner_profile_values.get("model_deterring_sprt_alpha", model_deterring_sprt_alpha)
        )
        model_deterring_sprt_beta = float(
            planner_profile_values.get("model_deterring_sprt_beta", model_deterring_sprt_beta)
        )
        model_deterring_sprt_patch_radius_m = planner_profile_values.get(
            "model_deterring_sprt_patch_radius_m",
            model_deterring_sprt_patch_radius_m,
        )
        model_deterring_min_sprt_margin = float(
            planner_profile_values.get("model_deterring_min_sprt_margin", model_deterring_min_sprt_margin)
        )
        model_deterring_chance_threshold = float(
            planner_profile_values.get("model_deterring_chance_threshold", model_deterring_chance_threshold)
        )
        model_deterring_min_deltaJ_per_cost = float(
            planner_profile_values.get(
                "model_deterring_min_deltaJ_per_cost",
                model_deterring_min_deltaJ_per_cost,
            )
        )
        model_deterring_min_selection_weight = float(
            planner_profile_values.get(
                "model_deterring_min_selection_weight",
                model_deterring_min_selection_weight,
            )
        )
        model_deterring_capacity_rho_max = float(
            planner_profile_values.get("model_deterring_capacity_rho_max", model_deterring_capacity_rho_max)
        )
        model_deterring_capacity_history_window_s = float(
            planner_profile_values.get(
                "model_deterring_capacity_history_window_s",
                model_deterring_capacity_history_window_s,
            )
        )
        model_deterring_capacity_min_completed_tasks = int(
            planner_profile_values.get(
                "model_deterring_capacity_min_completed_tasks",
                model_deterring_capacity_min_completed_tasks,
            )
        )
        model_deterring_capacity_fallback_budget_per_hr = planner_profile_values.get(
            "model_deterring_capacity_fallback_budget_per_hr",
            model_deterring_capacity_fallback_budget_per_hr,
        )
        model_deterring_global_admission_cap_per_cycle = int(
            planner_profile_values.get(
                "model_deterring_global_admission_cap_per_cycle",
                model_deterring_global_admission_cap_per_cycle,
            )
        )
        model_deterring_require_idle_robot_for_admission = bool(
            planner_profile_values.get(
                "model_deterring_require_idle_robot_for_admission",
                model_deterring_require_idle_robot_for_admission,
            )
        )
        model_deterring_prefer_idle_robots_for_assignment = bool(
            planner_profile_values.get(
                "model_deterring_prefer_idle_robots_for_assignment",
                model_deterring_prefer_idle_robots_for_assignment,
            )
        )
        model_deterring_busy_fallback_p_event_min = float(
            planner_profile_values.get(
                "model_deterring_busy_fallback_p_event_min",
                model_deterring_busy_fallback_p_event_min,
            )
        )
        model_deterring_busy_fallback_deltaJ_per_cost_min = float(
            planner_profile_values.get(
                "model_deterring_busy_fallback_deltaJ_per_cost_min",
                model_deterring_busy_fallback_deltaJ_per_cost_min,
            )
        )
        model_deterring_busy_fallback_eta_s_max = float(
            planner_profile_values.get(
                "model_deterring_busy_fallback_eta_s_max",
                model_deterring_busy_fallback_eta_s_max,
            )
        )
        protect_direct_detection_from_model_deterring = bool(
            planner_profile_values.get(
                "protect_direct_detection_from_model_deterring",
                protect_direct_detection_from_model_deterring,
            )
        )
        model_deterring_direct_conflict_radius_m = float(
            planner_profile_values.get(
                "model_deterring_direct_conflict_radius_m",
                model_deterring_direct_conflict_radius_m,
            )
        )
        model_deterring_direct_conflict_window_s = float(
            planner_profile_values.get(
                "model_deterring_direct_conflict_window_s",
                model_deterring_direct_conflict_window_s,
            )
        )
        protect_active_model_deterring_persistence = bool(
            planner_profile_values.get(
                "protect_active_model_deterring_persistence",
                protect_active_model_deterring_persistence,
            )
        )
        model_deterring_min_persistence_lifetime_s = float(
            planner_profile_values.get(
                "model_deterring_min_persistence_lifetime_s",
                model_deterring_min_persistence_lifetime_s,
            )
        )
        model_deterring_persistence_eta_multiplier = float(
            planner_profile_values.get(
                "model_deterring_persistence_eta_multiplier",
                model_deterring_persistence_eta_multiplier,
            )
        )
        model_deterring_persistence_buffer_s = float(
            planner_profile_values.get(
                "model_deterring_persistence_buffer_s",
                model_deterring_persistence_buffer_s,
            )
        )
        model_deterring_max_persistence_lifetime_s = float(
            planner_profile_values.get(
                "model_deterring_max_persistence_lifetime_s",
                model_deterring_max_persistence_lifetime_s,
            )
        )
        model_deterring_lock_near_goal_radius_m = float(
            planner_profile_values.get(
                "model_deterring_lock_near_goal_radius_m",
                model_deterring_lock_near_goal_radius_m,
            )
        )
        protect_active_model_deterring_goal_preemption = bool(
            planner_profile_values.get(
                "protect_active_model_deterring_goal_preemption",
                protect_active_model_deterring_goal_preemption,
            )
        )
        protect_locked_model_deterring_from_patrol_assignment = bool(
            planner_profile_values.get(
                "protect_locked_model_deterring_from_patrol_assignment",
                protect_locked_model_deterring_from_patrol_assignment,
            )
        )
        dispatch_policy = str(planner_profile_values.get("dispatch_policy", dispatch_policy))
        reservation_fraction = float(planner_profile_values.get("reservation_fraction", reservation_fraction))
        reservation_window_s = float(planner_profile_values.get("reservation_window_s", reservation_window_s))
        reactive_override_slack_s = float(
            planner_profile_values.get("reactive_override_slack_s", reactive_override_slack_s)
        )
        reservation_softening_alpha = float(
            planner_profile_values.get("reservation_softening_alpha", reservation_softening_alpha)
        )
        reservation_age_softening_beta = float(
            planner_profile_values.get("reservation_age_softening_beta", reservation_age_softening_beta)
        )
        reservation_age_gate = float(
            planner_profile_values.get("reservation_age_gate", reservation_age_gate)
        )
        predictive_slack_min_s = float(
            planner_profile_values.get("predictive_slack_min_s", predictive_slack_min_s)
        )
        reactive_pressure_max_for_predictive = float(
            planner_profile_values.get(
                "reactive_pressure_max_for_predictive",
                reactive_pressure_max_for_predictive,
            )
        )
        predictive_confidence_min = float(
            planner_profile_values.get("predictive_confidence_min", predictive_confidence_min)
        )
        predictive_deadline_weight = float(
            planner_profile_values.get("predictive_deadline_weight", predictive_deadline_weight)
        )
        predictive_eta_penalty_weight = float(
            planner_profile_values.get(
                "predictive_eta_penalty_weight",
                predictive_eta_penalty_weight,
            )
        )
        predictive_utility_mode = str(
            planner_profile_values.get("predictive_utility_mode", predictive_utility_mode)
        )
        predictive_confidence_source = str(
            planner_profile_values.get("predictive_confidence_source", predictive_confidence_source)
        )
        predictive_confidence_power = float(
            planner_profile_values.get("predictive_confidence_power", predictive_confidence_power)
        )
        predictive_time_score_deadline_scale_s = float(
            planner_profile_values.get(
                "predictive_time_score_deadline_scale_s",
                predictive_time_score_deadline_scale_s,
            )
        )
        predictive_time_score_reactive_pressure_weight = float(
            planner_profile_values.get(
                "predictive_time_score_reactive_pressure_weight",
                predictive_time_score_reactive_pressure_weight,
            )
        )
        predictive_time_score_infeasible_penalty = float(
            planner_profile_values.get(
                "predictive_time_score_infeasible_penalty",
                predictive_time_score_infeasible_penalty,
            )
        )
        predictive_utility_min = float(
            planner_profile_values.get("predictive_utility_min", predictive_utility_min)
        )
        predictive_cost_ratio_min = float(
            planner_profile_values.get("predictive_cost_ratio_min", predictive_cost_ratio_min)
        )
        predictive_opportunity_cost_weight = float(
            planner_profile_values.get(
                "predictive_opportunity_cost_weight",
                predictive_opportunity_cost_weight,
            )
        )
        predictive_eta_cost_weight = float(
            planner_profile_values.get("predictive_eta_cost_weight", predictive_eta_cost_weight)
        )
        predictive_service_cost_weight = float(
            planner_profile_values.get(
                "predictive_service_cost_weight",
                predictive_service_cost_weight,
            )
        )
        risk_adjusted_reservation_alpha = float(
            planner_profile_values.get(
                "risk_adjusted_reservation_alpha",
                risk_adjusted_reservation_alpha,
            )
        )
        risk_adjusted_reservation_beta = float(
            planner_profile_values.get(
                "risk_adjusted_reservation_beta",
                risk_adjusted_reservation_beta,
            )
        )
        predictive_selection_policy = str(
            planner_profile_values.get("predictive_selection_policy", predictive_selection_policy)
        )
        defer_predictive_action_selection = bool(
            planner_profile_values.get(
                "defer_predictive_action_selection",
                defer_predictive_action_selection,
            )
        )
        assignment_switch_penalty = float(
            planner_profile_values.get("assignment_switch_penalty", assignment_switch_penalty)
        )
        predictive_planning_topology = str(
            planner_profile_values.get("predictive_planning_topology", predictive_planning_topology)
        )
        zone_assignment_mode = str(
            planner_profile_values.get("zone_assignment_mode", zone_assignment_mode)
        )
        predictive_timing_mode = str(
            planner_profile_values.get("predictive_timing_mode", predictive_timing_mode)
        )
        predictive_expiry_grace_s = float(
            planner_profile_values.get("predictive_expiry_grace_s", predictive_expiry_grace_s)
        )

    dispatch_policy_settings = _resolve_dispatch_policy_settings(
        dispatch_policy=str(dispatch_policy),
        reservation_fraction=float(reservation_fraction),
        reservation_window_s=float(reservation_window_s),
        reactive_override_slack_s=float(reactive_override_slack_s),
        reservation_softening_alpha=float(reservation_softening_alpha),
        reservation_age_softening_beta=float(reservation_age_softening_beta),
        reservation_age_gate=float(reservation_age_gate),
        predictive_selection_policy=str(predictive_selection_policy),
    )
    dispatch_policy = str(dispatch_policy_settings["dispatch_policy"])
    reservation_fraction = float(dispatch_policy_settings["reservation_fraction"])
    reservation_window_s = float(dispatch_policy_settings["reservation_window_s"])
    reactive_override_slack_s = float(dispatch_policy_settings["reactive_override_slack_s"])
    reservation_softening_alpha = float(dispatch_policy_settings["reservation_softening_alpha"])
    reservation_age_softening_beta = float(dispatch_policy_settings["reservation_age_softening_beta"])
    reservation_age_gate = float(dispatch_policy_settings["reservation_age_gate"])
    if reactive_load_factor_window_s in (None, ""):
        effective_reactive_load_factor_window_s = float(reservation_window_s)
    else:
        effective_reactive_load_factor_window_s = float(reactive_load_factor_window_s)
        if (not math.isfinite(effective_reactive_load_factor_window_s)) or effective_reactive_load_factor_window_s <= 0.0:
            raise ValueError(
                "reactive_load_factor_window_s must be finite and > 0 when provided, "
                f"got: {reactive_load_factor_window_s!r}"
            )
    predictive_slack_min_s = float(predictive_slack_min_s)
    reactive_pressure_max_for_predictive = float(reactive_pressure_max_for_predictive)
    predictive_confidence_min = float(predictive_confidence_min)
    predictive_deadline_weight = float(predictive_deadline_weight)
    predictive_eta_penalty_weight = float(predictive_eta_penalty_weight)
    if confidence_source is not None:
        predictive_confidence_source = confidence_source
    if confidence_power is not None:
        predictive_confidence_power = confidence_power
    predictive_utility_mode = canonical_predictive_utility_mode(predictive_utility_mode)
    direct_detection_habituation_mode = str(direct_detection_habituation_mode or "direct_detection").strip()
    predictive_confidence_source = canonical_predictive_confidence_source(predictive_confidence_source)
    predictive_confidence_power = float(predictive_confidence_power)
    predictive_time_score_deadline_scale_s = float(predictive_time_score_deadline_scale_s)
    predictive_time_score_reactive_pressure_weight = float(predictive_time_score_reactive_pressure_weight)
    predictive_time_score_infeasible_penalty = float(predictive_time_score_infeasible_penalty)
    predictive_utility_min = float(predictive_utility_min)
    predictive_cost_ratio_min = float(predictive_cost_ratio_min)
    predictive_opportunity_cost_weight = float(predictive_opportunity_cost_weight)
    predictive_eta_cost_weight = float(predictive_eta_cost_weight)
    predictive_service_cost_weight = float(predictive_service_cost_weight)
    stl_E_star = max(float(stl_E_star), 1.0e-9)
    stl_T_cov_s = max(float(stl_T_cov_s), 1.0e-9)
    stl_T_react_s = float(reactive_override_slack_s if stl_T_react_s in (None, "") else stl_T_react_s)
    stl_W_s = max(float(stl_W_s), 0.0)
    stl_eta_min = min(max(float(stl_eta_min), 0.0), 0.999999)
    stl_horizon_s = float(forecast_horizon_s if stl_horizon_s in (None, "") else stl_horizon_s)
    stl_horizon_s = max(float(stl_horizon_s), 1.0e-9)
    stl_monitor_dt_s = max(float(stl_monitor_dt_s), 1.0e-9)
    stl_theta = max(float(stl_theta), 1.0e-9)
    stl_smooth = bool(stl_smooth)
    if isinstance(stl_active_clauses, str):
        stl_active_clauses = tuple(
            clause.strip()
            for clause in stl_active_clauses.replace(";", ",").split(",")
            if clause.strip()
        )
    else:
        stl_active_clauses = tuple(str(clause).strip() for clause in stl_active_clauses if str(clause).strip())
    if not stl_active_clauses:
        stl_active_clauses = ("exp", "cov", "hab")
    if direct_detection_habituation_mode not in {"", "direct_detection"} and deterring_modes is not None:
        if str(direct_detection_habituation_mode) not in {str(mode) for mode in deterring_modes.keys()}:
            raise ValueError(
                "direct_detection_habituation_mode must be direct_detection or one of deterring_modes, "
                f"got: {direct_detection_habituation_mode!r}"
            )
    risk_adjusted_reservation_alpha = float(risk_adjusted_reservation_alpha)
    risk_adjusted_reservation_beta = float(risk_adjusted_reservation_beta)
    predictive_planning_topology = str(predictive_planning_topology or "mixed").strip().lower().replace("-", "_")
    zone_assignment_mode = str(zone_assignment_mode or "soft").strip().lower().replace("-", "_")
    defer_predictive_action_selection = bool(defer_predictive_action_selection)
    assignment_switch_penalty = float(assignment_switch_penalty)
    predictive_timing_mode = str(predictive_timing_mode or "synthetic").strip().lower().replace("-", "_")
    predictive_expiry_grace_s = float(predictive_expiry_grace_s)
    if (not math.isfinite(predictive_slack_min_s)) or predictive_slack_min_s < 0.0:
        raise ValueError(
            f"predictive_slack_min_s must be finite and >= 0, got: {predictive_slack_min_s!r}"
        )
    if (not math.isfinite(reactive_pressure_max_for_predictive)) or reactive_pressure_max_for_predictive < 0.0:
        raise ValueError(
            "reactive_pressure_max_for_predictive must be finite and >= 0, "
            f"got: {reactive_pressure_max_for_predictive!r}"
        )
    if (not math.isfinite(predictive_confidence_min)) or predictive_confidence_min < 0.0 or predictive_confidence_min > 1.0:
        raise ValueError(
            "predictive_confidence_min must be finite and lie in [0, 1], "
            f"got: {predictive_confidence_min!r}"
        )
    if (not math.isfinite(predictive_deadline_weight)) or predictive_deadline_weight < 0.0:
        raise ValueError(
            f"predictive_deadline_weight must be finite and >= 0, got: {predictive_deadline_weight!r}"
        )
    if (not math.isfinite(predictive_eta_penalty_weight)) or predictive_eta_penalty_weight < 0.0:
        raise ValueError(
            "predictive_eta_penalty_weight must be finite and >= 0, "
            f"got: {predictive_eta_penalty_weight!r}"
        )
    if (not math.isfinite(predictive_confidence_power)) or predictive_confidence_power <= 0.0:
        raise ValueError(
            "predictive_confidence_power must be finite and > 0, "
            f"got: {predictive_confidence_power!r}"
        )
    if (not math.isfinite(predictive_time_score_deadline_scale_s)) or predictive_time_score_deadline_scale_s <= 0.0:
        raise ValueError(
            "predictive_time_score_deadline_scale_s must be finite and > 0, "
            f"got: {predictive_time_score_deadline_scale_s!r}"
        )
    if (not math.isfinite(predictive_time_score_reactive_pressure_weight)) or predictive_time_score_reactive_pressure_weight < 0.0:
        raise ValueError(
            "predictive_time_score_reactive_pressure_weight must be finite and >= 0, "
            f"got: {predictive_time_score_reactive_pressure_weight!r}"
        )
    if (not math.isfinite(predictive_time_score_infeasible_penalty)) or predictive_time_score_infeasible_penalty < 0.0:
        raise ValueError(
            "predictive_time_score_infeasible_penalty must be finite and >= 0, "
            f"got: {predictive_time_score_infeasible_penalty!r}"
        )
    if not math.isfinite(predictive_utility_min):
        raise ValueError(
            "predictive_utility_min must be finite, "
            f"got: {predictive_utility_min!r}"
        )
    if (not math.isfinite(predictive_cost_ratio_min)) or predictive_cost_ratio_min < 0.0:
        raise ValueError(
            "predictive_cost_ratio_min must be finite and >= 0, "
            f"got: {predictive_cost_ratio_min!r}"
        )
    if (not math.isfinite(predictive_opportunity_cost_weight)) or predictive_opportunity_cost_weight < 0.0:
        raise ValueError(
            "predictive_opportunity_cost_weight must be finite and >= 0, "
            f"got: {predictive_opportunity_cost_weight!r}"
        )
    if (not math.isfinite(predictive_eta_cost_weight)) or predictive_eta_cost_weight < 0.0:
        raise ValueError(
            "predictive_eta_cost_weight must be finite and >= 0, "
            f"got: {predictive_eta_cost_weight!r}"
        )
    if (not math.isfinite(predictive_service_cost_weight)) or predictive_service_cost_weight < 0.0:
        raise ValueError(
            "predictive_service_cost_weight must be finite and >= 0, "
            f"got: {predictive_service_cost_weight!r}"
        )
    if (not math.isfinite(risk_adjusted_reservation_alpha)) or risk_adjusted_reservation_alpha < 0.0:
        raise ValueError(
            "risk_adjusted_reservation_alpha must be finite and >= 0, "
            f"got: {risk_adjusted_reservation_alpha!r}"
        )
    if (not math.isfinite(risk_adjusted_reservation_beta)) or risk_adjusted_reservation_beta < 0.0:
        raise ValueError(
            "risk_adjusted_reservation_beta must be finite and >= 0, "
            f"got: {risk_adjusted_reservation_beta!r}"
        )
    if predictive_timing_mode not in {"synthetic", "forecast_horizon", "arrival_offset"}:
        raise ValueError(
            "predictive_timing_mode must be one of ['synthetic', 'forecast_horizon', 'arrival_offset'], "
            f"got: {predictive_timing_mode!r}"
        )
    if predictive_planning_topology not in {"mixed", "centralized_global"}:
        raise ValueError(
            "predictive_planning_topology must be one of ['mixed', 'centralized_global'], "
            f"got: {predictive_planning_topology!r}"
        )
    if zone_assignment_mode not in {"soft"}:
        raise ValueError(
            "zone_assignment_mode must be one of ['soft'], "
            f"got: {zone_assignment_mode!r}"
        )
    if (not math.isfinite(predictive_expiry_grace_s)) or predictive_expiry_grace_s < 0.0:
        raise ValueError(
            f"predictive_expiry_grace_s must be finite and >= 0, got: {predictive_expiry_grace_s!r}"
        )
    if (not math.isfinite(assignment_switch_penalty)) or assignment_switch_penalty < 0.0:
        raise ValueError(
            f"assignment_switch_penalty must be finite and >= 0, got: {assignment_switch_penalty!r}"
        )
    predictive_selection_policy = str(dispatch_policy_settings["predictive_selection_policy"])
    effective_tau_service_s = float(hold_time_s) if tau_service_s in (None, "") else float(tau_service_s)
    if (not math.isfinite(float(hold_time_s))) or float(hold_time_s) < 0.0:
        raise ValueError(f"hold_time_s must be finite and >= 0, got: {hold_time_s!r}")
    if (not math.isfinite(effective_tau_service_s)) or effective_tau_service_s < 0.0:
        raise ValueError(f"tau_service_s must be finite and >= 0 when provided, got: {tau_service_s!r}")
    tau_service_s = float(effective_tau_service_s)
    predictive_lead_time_min_s = float(predictive_lead_time_min_s)
    predictive_lead_time_max_eta_s = float(predictive_lead_time_max_eta_s)
    predictive_lead_time_buffer_s = float(predictive_lead_time_buffer_s)
    predictive_lead_time_risk_power = float(predictive_lead_time_risk_power)
    if (not math.isfinite(predictive_lead_time_min_s)) or predictive_lead_time_min_s < 0.0:
        raise ValueError(
            f"predictive_lead_time_min_s must be finite and >= 0, got: {predictive_lead_time_min_s!r}"
        )
    if (not math.isfinite(predictive_lead_time_max_eta_s)) or predictive_lead_time_max_eta_s < 0.0:
        raise ValueError(
            "predictive_lead_time_max_eta_s must be finite and >= 0, "
            f"got: {predictive_lead_time_max_eta_s!r}"
        )
    if (not math.isfinite(predictive_lead_time_buffer_s)) or predictive_lead_time_buffer_s < 0.0:
        raise ValueError(
            "predictive_lead_time_buffer_s must be finite and >= 0, "
            f"got: {predictive_lead_time_buffer_s!r}"
        )
    if (not math.isfinite(predictive_lead_time_risk_power)) or predictive_lead_time_risk_power <= 0.0:
        raise ValueError(
            "predictive_lead_time_risk_power must be finite and > 0, "
            f"got: {predictive_lead_time_risk_power!r}"
        )

    preventive_policy_settings = _resolve_preventive_policy_settings(
        simulation_mode=mode_key,
        preventive_policy=preventive_policy,
        planner_profile=planner_profile,
        planner_profile_values=planner_profile_values,
        enable_model_scored_deterring=bool(enable_model_scored_deterring),
        enable_predicted_deltaJ_gate=bool(enable_predicted_deltaJ_gate),
        model_deterring_gate_policy=str(model_deterring_gate_policy),
    )
    preventive_policy = str(preventive_policy_settings["preventive_policy"])
    preventive_policy_source = str(preventive_policy_settings["preventive_policy_source"])
    selective_preventive_enabled = bool(preventive_policy_settings["selective_preventive_enabled"])
    enable_model_scored_deterring = bool(preventive_policy_settings["enable_model_scored_deterring"])
    enable_predicted_deltaJ_gate = bool(preventive_policy_settings["enable_predicted_deltaJ_gate"])
    model_deterring_gate_policy = str(preventive_policy_settings["model_deterring_gate_policy"])

    if (
        bool(auto_enable_proposed_preventive_window)
        and mode_key == "proposed"
        and bool(enable_model_scored_deterring)
        and float(model_deterring_window_s) <= 0.0
    ):
        model_deterring_window_s = float(default_proposed_model_deterring_window_s)
    elif (
        mode_key == "proposed"
        and bool(enable_model_scored_deterring)
        and float(model_deterring_window_s) <= 0.0
    ):
        print(
            "[warn] proposed mode has model-scored deterring enabled but "
            "model_deterring_window_s<=0, so preventive task generation is disabled."
        )

    calibration_resolution = _resolve_calibration_runtime_overrides(
        simulation_mode=mode_key,
        use_frozen_calibration=bool(use_frozen_calibration),
        calibration_ranking_path=calibration_ranking_path,
        calibration_manifest_path=calibration_manifest_path,
        calibration_config_id=calibration_config_id,
        planner_profile=planner_profile,
        planner_profile_values=planner_profile_values,
        prediction_only_model_overrides=prediction_only_model_overrides,
        proposed_model_overrides=proposed_model_overrides,
        sigma=float(sigma),
        omega=float(omega),
        alpha_in=(None if alpha_in is None else float(alpha_in)),
        alpha_cross=(None if alpha_cross is None else float(alpha_cross)),
        alpha_inhib=float(alpha_inhib),
        omega_inhib=float(omega_inhib),
        mu_base=float(mu_base),
        bg_ema=float(bg_ema),
        model_feedback_sigma_scale=float(model_feedback_sigma_scale),
        model_feedback_omega_scale=float(model_feedback_omega_scale),
    )
    use_frozen_calibration = bool(calibration_resolution["use_frozen_calibration"])
    calibration_ranking_path = calibration_resolution.get("calibration_ranking_path")
    calibration_manifest_path = calibration_resolution.get("calibration_manifest_path")
    calibration_config_id = calibration_resolution.get("calibration_config_id")
    selected_calibration_config_id = str(calibration_resolution["selected_calibration_config_id"])
    selected_calibration_source = str(calibration_resolution["selected_calibration_source"])
    selected_calibration_summary_metrics = dict(calibration_resolution["selected_calibration_summary_metrics"])
    sigma = float(calibration_resolution["sigma"])
    omega = float(calibration_resolution["omega"])
    alpha_in = calibration_resolution["alpha_in"]
    alpha_cross = calibration_resolution["alpha_cross"]
    alpha_inhib = float(calibration_resolution["alpha_inhib"])
    omega_inhib = float(calibration_resolution["omega_inhib"])
    mu_base = float(calibration_resolution["mu_base"])
    bg_ema = float(calibration_resolution["bg_ema"])
    model_feedback_sigma_scale = float(calibration_resolution["model_feedback_sigma_scale"])
    model_feedback_omega_scale = float(calibration_resolution["model_feedback_omega_scale"])
    if alpha_in is None:
        alpha_in = 0.6 / max(float(omega), 1e-9)
    else:
        alpha_in = float(alpha_in)
    if alpha_cross is None:
        alpha_cross = 0.4 * float(alpha_in)
    else:
        alpha_cross = float(alpha_cross)
    calibrated_model_sigma = float(sigma)
    calibrated_model_omega = float(omega)
    calibrated_model_alpha_in = float(alpha_in)
    calibrated_model_alpha_cross = float(alpha_cross)
    calibrated_model_alpha_inhib = float(alpha_inhib)
    calibrated_model_omega_inhib = float(omega_inhib)
    calibrated_model_mu_base = float(mu_base)
    calibrated_model_bg_ema = float(bg_ema)
    calibrated_model_feedback_sigma_scale = float(model_feedback_sigma_scale)
    calibrated_model_feedback_omega_scale = float(model_feedback_omega_scale)

    model_deterring_gate_policy = str(model_deterring_gate_policy).strip().lower()
    if model_deterring_gate_policy not in {"heuristic", "sprt_capacity"}:
        raise ValueError(
            "model_deterring_gate_policy must be one of ['heuristic', 'sprt_capacity'], "
            f"got: {model_deterring_gate_policy!r}"
        )
    if model_deterring_capacity_fallback_budget_per_hr is None:
        model_deterring_capacity_fallback_budget_per_hr = model_deterring_budget_per_robot_per_hr
    use_split_task_extraction_selection_pipeline = bool(use_split_task_extraction_selection_pipeline)
    preassignment_selection_policy = str(preassignment_selection_policy).strip().lower()
    if preassignment_selection_policy not in {"pass_through", "priority_top_k", "capacity_aware_greedy"}:
        raise ValueError(
            "preassignment_selection_policy must be one of ['pass_through', 'priority_top_k', 'capacity_aware_greedy'], "
            f"got: {preassignment_selection_policy!r}"
        )
    preassignment_selection_limit = max(0, int(preassignment_selection_limit))
    model_deterring_global_admission_cap_per_cycle = max(0, int(model_deterring_global_admission_cap_per_cycle))
    model_deterring_prefer_idle_robots_for_assignment = bool(model_deterring_prefer_idle_robots_for_assignment)
    model_deterring_busy_fallback_p_event_min = min(1.0, max(0.0, float(model_deterring_busy_fallback_p_event_min)))
    model_deterring_busy_fallback_deltaJ_per_cost_min = max(0.0, float(model_deterring_busy_fallback_deltaJ_per_cost_min))
    model_deterring_busy_fallback_eta_s_max = max(0.0, float(model_deterring_busy_fallback_eta_s_max))
    model_deterring_min_sprt_margin = max(0.0, float(model_deterring_min_sprt_margin))
    model_deterring_min_selection_weight = min(1.0, max(0.0, float(model_deterring_min_selection_weight)))
    model_deterring_direct_conflict_radius_m = max(0.0, float(model_deterring_direct_conflict_radius_m))
    model_deterring_direct_conflict_window_s = max(0.0, float(model_deterring_direct_conflict_window_s))
    protect_active_model_deterring_persistence = bool(protect_active_model_deterring_persistence)
    model_deterring_min_persistence_lifetime_s = max(0.0, float(model_deterring_min_persistence_lifetime_s))
    model_deterring_persistence_eta_multiplier = max(0.0, float(model_deterring_persistence_eta_multiplier))
    model_deterring_persistence_buffer_s = max(0.0, float(model_deterring_persistence_buffer_s))
    model_deterring_max_persistence_lifetime_s = max(
        float(model_deterring_min_persistence_lifetime_s),
        float(model_deterring_max_persistence_lifetime_s),
    )
    model_deterring_lock_near_goal_radius_m = max(0.0, float(model_deterring_lock_near_goal_radius_m))
    protect_active_model_deterring_goal_preemption = bool(protect_active_model_deterring_goal_preemption)
    protect_locked_model_deterring_from_patrol_assignment = bool(protect_locked_model_deterring_from_patrol_assignment)

    # ------------------------------------------------------------------------
    # Runtime state initialization: fleet, zones, models, and metrics
    # ------------------------------------------------------------------------
    # --- Seed robots & profiles (types/kinematics) ---
    robots_def = []
    if Nrobots is None:
        Nrobots = rng.integers(5, 8)
    for i in range(Nrobots):
        x = float(rng.uniform(0.15*W, 0.85*W))
        y = float(rng.uniform(0.15*H, 0.85*H))
        health = float(rng.uniform(0.3, 1.0))
        robots_def.append({"id": f"r{i+1}", "anchor": (x,y), "health": health})

    profiles = {}
    for r in robots_def:
        rid = r['id']
        if rng.uniform() < uav_fraction:
            profiles[rid] = RobotProfile(rid,'UAV',12.0,12, float(rng.uniform(0.6,0.95)), r['health'], True, 1.0)
        else:
            profiles[rid] = RobotProfile(rid,'UGV',2.6,150, float(rng.uniform(0.6,0.95)), r['health'], True, 0.7)

    # --- ZonePartitioner with **home anchors = initial positions** ---
    partitioner = ZonePartitioner(W, H, robots_def, profiles, mode=mode, scale=scale, gamma=gamma)
    for r in robots_def:
        partitioner.update_anchor(r['id'], r['anchor'])   # homes = initial anchors
    partitioner.recompute(force=True)
    cells = partitioner.cells_for_ids()
    id_to_cell = {rid: cells[i] for i, rid in enumerate(partitioner.ids)}  # only UGVs are in partitioner.ids
    if debug_zone_areas:
        def _poly_area(poly):
            """Compute polygon area using the shoelace formula for diagnostics and partition checks."""
            if not poly:
                return 0.0
            s = 0.0
            n = len(poly)
            for k in range(n):
                x1, y1 = poly[k]
                x2, y2 = poly[(k + 1) % n]
                s += x1 * y2 - x2 * y1
            return abs(0.5 * s)
        for rid in [r["id"] for r in robots_def]:
            area = _poly_area(id_to_cell.get(rid, []))
            print(f"[zone] {rid} area={area:.2f}")

    #  --- SESTPP models + Robot wrappers ---
    X_MIN, X_MAX = 0.0, W; Y_MIN, Y_MAX = 0.0, H
    robots = {}

    for r in robots_def:
        rid = r['id']
        m = OnlineSESTPP(X_MIN, X_MAX, Y_MIN, Y_MAX, NX, NY,
            sigma=sigma, omega=omega, omega_inhib=omega_inhib,
            alpha_in=alpha_in, alpha_cross=alpha_cross, alpha_inhib=alpha_inhib,
            mu_base=mu_base, bg_ema=bg_ema)

        neighbors = partitioner.neighbors_for_id(rid)  # returns [] for UAVs if you applied the ZonePartitioner fix
        zone = id_to_cell.get(rid, [])                 # UAVs get an empty zone
        robots[rid] = Robot(rid, m, zone, neighbors, border_radius_m=max(10.0, 1.5*sigma))
        robots[rid].configure_dispatch_time_tracker(float(reservation_window_s), now_t=0.0)

    # --- Live kinematics (start at initial positions; no dock logic) ---
    pose = {r['id']: tuple(r['anchor']) for r in robots_def}
    goal = {r['id']: None for r in robots_def}
    next_idle_retarget = {r['id']: -1.0 for r in robots_def}
    loiter_until = {r['id']: -1.0 for r in robots_def}
    bird_present_until = {r['id']: -1.0 for r in robots_def}
    last_detection_time = {r['id']: -1.0 for r in robots_def}
    bus = EventBus(robots, bytes_per_boundary_msg=bytes_per_boundary_msg,
                   bytes_per_intervention_msg=bytes_per_intervention_msg)
    global_predictive_model = None
    global_predictive_recent_events = deque(maxlen=5000)
    centralized_planning_robots = None
    centralized_predictive_topology_enabled = (
        str(predictive_planning_topology).strip().lower() == "centralized_global"
    )
    if centralized_predictive_topology_enabled:
        global_predictive_model = OnlineSESTPP(
            X_MIN,
            X_MAX,
            Y_MIN,
            Y_MAX,
            NX,
            NY,
            sigma=sigma,
            omega=omega,
            omega_inhib=omega_inhib,
            alpha_in=alpha_in,
            alpha_cross=alpha_cross,
            alpha_inhib=alpha_inhib,
            mu_base=mu_base,
            bg_ema=bg_ema,
        )
        centralized_planning_robots = {}
        for rid in robots:
            planning_robot = Robot(
                rid,
                global_predictive_model,
                boundary,
                [],
                border_radius_m=max(10.0, 1.5 * sigma),
            )
            planning_robot.recent_events = global_predictive_recent_events
            centralized_planning_robots[rid] = planning_robot

    # --- Metrics accumulators ---
    pending_event_onsets = deque(maxlen=5000)  # dicts: {x,y,t,responded}
    response_times = []
    reactive_response_times = []
    direct_detection_task_refresh_active = 0
    direct_detection_task_refresh_skipped_unassigned = 0
    direct_detection_task_refresh_skipped_eta = 0
    direct_detection_task_cluster_groups = 0
    direct_detection_task_cluster_merged = 0
    direct_detection_task_response_matches = 0

    direct_detection_cluster_radius_m = max(float(direct_detection_task_cluster_radius_m), 0.0)
    direct_detection_cluster_window_s = max(float(direct_detection_task_cluster_window_s), 0.0)
    direct_detection_active_refresh_radius_m = (
        direct_detection_cluster_radius_m
        if direct_detection_task_active_refresh_radius_m is None
        else max(float(direct_detection_task_active_refresh_radius_m), 0.0)
    )
    direct_detection_active_refresh_window_s = (
        direct_detection_cluster_window_s
        if direct_detection_task_active_refresh_window_s is None
        else max(float(direct_detection_task_active_refresh_window_s), 0.0)
    )
    direct_detection_queued_cluster_radius_m = (
        direct_detection_cluster_radius_m
        if direct_detection_task_queued_cluster_radius_m is None
        else max(float(direct_detection_task_queued_cluster_radius_m), 0.0)
    )
    direct_detection_queued_cluster_window_s = (
        direct_detection_cluster_window_s
        if direct_detection_task_queued_cluster_window_s is None
        else max(float(direct_detection_task_queued_cluster_window_s), 0.0)
    )
    direct_detection_active_refresh_max_eta_s = float(direct_detection_task_active_refresh_max_eta_s)
    travel_distance_by_robot = {rid: 0.0 for rid in pose}
    energy_by_robot = {rid: 0.0 for rid in pose}
    completed_count_by_type = {"deterring": 0, "patrolling": 0}
    completed_task_scores = []
    value_weighted_exposure = 0.0
    # Robot duty-cycle diagnostics
    robot_time_total = {rid: 0.0 for rid in pose}
    robot_time_with_task = {rid: 0.0 for rid in pose}
    robot_time_moving = {rid: 0.0 for rid in pose}
    robot_time_holding = {rid: 0.0 for rid in pose}
    robot_time_idle = {rid: 0.0 for rid in pose}
    robot_time_moving_with_task = {rid: 0.0 for rid in pose}
    robot_idle_streak = {rid: 0.0 for rid in pose}
    robot_idle_streak_max = {rid: 0.0 for rid in pose}
    fleet_task_engagement_time = 0.0
    fleet_moving_time = 0.0
    fleet_idle_no_task_time = 0.0

    # ------------------------------------------------------------------------
    # Local helper closures: value map, truth generation, and perception
    # ------------------------------------------------------------------------
    # --- Vineyard value map: rows + edges (static w(x)) ---
    def value_weight(x, y):
        # Rows run along x-axis, so row centers are spaced along y.
        """Evaluate the static vineyard value map used by exposure metrics and planning."""
        if row_spacing_m <= 0:
            row_w = 0.0
        else:
            y_mod = y % row_spacing_m
            dist_row = min(y_mod, row_spacing_m - y_mod)
            row_w = row_gain if dist_row <= (row_width_m * 0.5) else 0.0

        dist_edge = point_to_poly_distance((x, y), boundary)
        edge_w = edge_gain * math.exp(-dist_edge / max(edge_scale_m, 1e-9))
        return 1.0 + row_w + edge_w

    # --- Ground-truth event process (event-driven with value map bias) ---
    truth_events = []     # list of (x,y,t)
    truth_event_times = []  # monotonic-ish times for fast horizon slicing
    recent_truth = deque(maxlen=5000)      # (x,y,t) for plotting
    recent_detections = deque(maxlen=5000) # (x,y,t) for plotting
    truth_queue = []      # scheduled offspring events (x,y,t)
    # Ground-truth suppression diagnostics
    truth_candidate_events = 0
    truth_accepted_events = 0
    truth_suppressed_events = 0
    truth_detection_opportunities = 0
    truth_detections_observed = 0
    truth_detections_missed_range = 0
    truth_detections_missed_false_negative = 0
    suppression_effect_sum = 0.0
    suppression_effect_by_mode = {}
    suppression_effect_by_source = {"direct_detection": 0.0, "model_scored": 0.0}
    truth_metrics_window_s = 3600.0
    truth_candidate_event_times_last_hour = deque()
    truth_suppressed_event_times_last_hour = deque()
    truth_candidate_event_times_load = deque()
    truth_suppressed_event_times_load = deque()
    truth_accepted_event_times_load = deque()
    truth_detection_opportunity_times_load = deque()
    truth_detection_in_range_times_load = deque()
    truth_detection_observed_times_load = deque()
    truth_event_detection_prob = min(max(float(bird_detection_prob), 0.0), 1.0)
    w_cdf = None
    w_shape = None
    dx = W / max(NX - 1, 1)
    dy = H / max(NY - 1, 1)

    if use_ground_truth:
        xs = np.linspace(0.0, W, NX)
        ys = np.linspace(0.0, H, NY)
        W_grid = np.zeros((NY, NX), float)
        for iy, yy in enumerate(ys):
            for ix, xx in enumerate(xs):
                W_grid[iy, ix] = max(0.0, value_weight(xx, yy))
        w_flat = W_grid.ravel()
        w_sum = float(w_flat.sum()) if w_flat.size else 1.0
        w_cdf = np.cumsum(w_flat) / (w_sum if w_sum > 0 else 1.0)
        w_shape = (NY, NX, xs, ys, W_grid)

    def _sample_from_value_map(rng):
        """Sample a ground-truth event location from the value-weighted spatial distribution."""
        if w_cdf is None or w_shape is None:
            return float(rng.uniform(0.0, W)), float(rng.uniform(0.0, H))
        r = float(rng.random())
        idx = int(np.searchsorted(w_cdf, r, side="right"))
        ny, nx, xs, ys, _ = w_shape
        iy, ix = divmod(min(idx, ny * nx - 1), nx)
        # jitter within cell
        x = float(xs[ix] + rng.uniform(-0.5 * dx, 0.5 * dx))
        y = float(ys[iy] + rng.uniform(-0.5 * dy, 0.5 * dy))
        return float(np.clip(x, 0.0, W)), float(np.clip(y, 0.0, H))

    def _suppression_eval(x, y, t_now):
        """
        Returns:
          p_keep: probability a truth event survives suppression.
          p_suppress: probability mass removed by suppression at this sample.
          suppress_by_mode: mode-attributed share of p_suppress (sums to p_suppress).
          suppress_by_source: source-attributed share of p_suppress.
        """
        if not recent_deterrences:
            return 1.0, 0.0, {}, {}
        s = 0.0
        contrib_by_mode = {}
        contrib_by_source = {}
        for ev in recent_deterrences:
            zx = float(ev.get("x", 0.0))
            zy = float(ev.get("y", 0.0))
            tz = float(ev.get("t", 0.0))
            dt = t_now - tz
            if dt < 0:
                continue
            beta_u = float(ev.get("beta", beta_true))
            sigma_u = float(ev.get("sigma", sigma_true))
            omega_u = float(ev.get("omega", omega_true))
            mode_u = str(ev.get("mode", "unknown"))
            source_u = str(ev.get("source", "direct_detection"))
            k = math.exp(-0.5 * ((x - zx)**2 + (y - zy)**2) / max(sigma_u**2, 1e-9))
            eta_u = float(ev.get("eta", 1.0))
            c = eta_u * beta_u * k * math.exp(-dt / max(omega_u, 1e-9))
            if c <= 0.0:
                continue
            s += c
            contrib_by_mode[mode_u] = float(contrib_by_mode.get(mode_u, 0.0) + c)
            contrib_by_source[source_u] = float(contrib_by_source.get(source_u, 0.0) + c)
        if s <= 0.0:
            return 1.0, 0.0, {}, {}
        p_keep = float(math.exp(-s))
        p_suppress = float(1.0 - p_keep)
        suppress_by_mode = {
            mode: float(p_suppress * (c / s))
            for mode, c in contrib_by_mode.items()
        }
        suppress_by_source = {
            src: float(p_suppress * (c / s))
            for src, c in contrib_by_source.items()
        }
        return p_keep, p_suppress, suppress_by_mode, suppress_by_source

    def _prune_truth_event_window(now_t):
        """Prune truth suppression counters to the configured metrics window."""
        cutoff_t = float(now_t) - float(truth_metrics_window_s)
        while truth_candidate_event_times_last_hour and truth_candidate_event_times_last_hour[0] < cutoff_t:
            truth_candidate_event_times_last_hour.popleft()
        while truth_suppressed_event_times_last_hour and truth_suppressed_event_times_last_hour[0] < cutoff_t:
            truth_suppressed_event_times_last_hour.popleft()

    def _prune_reactive_load_window(now_t):
        """Prune reactive load counters to the configured workload-estimation window."""
        cutoff_t = float(now_t) - float(effective_reactive_load_factor_window_s)
        for event_times in (
            truth_candidate_event_times_load,
            truth_suppressed_event_times_load,
            truth_accepted_event_times_load,
            truth_detection_opportunity_times_load,
            truth_detection_in_range_times_load,
            truth_detection_observed_times_load,
        ):
            while event_times and float(event_times[0]) < cutoff_t:
                event_times.popleft()

    def _record_truth_window_event(event_t, suppressed):
        """Record whether a truth candidate survived or was suppressed for windowed metrics."""
        event_t = float(event_t)
        truth_candidate_event_times_last_hour.append(event_t)
        truth_candidate_event_times_load.append(event_t)
        if suppressed:
            truth_suppressed_event_times_last_hour.append(event_t)
            truth_suppressed_event_times_load.append(event_t)
        _prune_truth_event_window(event_t)
        _prune_reactive_load_window(event_t)

    def _current_truth_window_metrics(now_t):
        """Return current truth suppression metrics over the rolling metrics window."""
        _prune_truth_event_window(now_t)
        candidate_last_hour = int(len(truth_candidate_event_times_last_hour))
        suppressed_last_hour = int(len(truth_suppressed_event_times_last_hour))
        suppression_rate_last_hour = (
            float(suppressed_last_hour) / float(candidate_last_hour) if candidate_last_hour > 0 else float("nan")
        )
        birds_deterred_pct_last_hour = (
            100.0 * float(suppressed_last_hour) / float(candidate_last_hour) if candidate_last_hour > 0 else float("nan")
        )
        return {
            "truth_candidate_events_last_hour": candidate_last_hour,
            "truth_suppressed_events_last_hour": suppressed_last_hour,
            "truth_suppression_rate_last_hour": suppression_rate_last_hour,
            "birds_deterred_pct_last_hour": birds_deterred_pct_last_hour,
        }

    def _current_reactive_load_factor_metrics(now_t):
        """Return current reactive workload metrics over the rolling load window."""
        _prune_reactive_load_window(now_t)
        window_s = max(float(effective_reactive_load_factor_window_s), 1.0)
        service_s = max(float(tau_service_s), 0.0)
        fleet_n = max(float(len(robots)), 1.0)

        def _load_factor(count):
            """Convert an event count in the load window into a nominal service load factor."""
            return float((float(count) / window_s) * service_s / fleet_n)

        truth_candidate_count = int(len(truth_candidate_event_times_load))
        truth_accepted_count = int(len(truth_accepted_event_times_load))
        detection_opportunity_count = int(len(truth_detection_opportunity_times_load))
        detection_in_range_count = int(len(truth_detection_in_range_times_load))
        detection_observed_count = int(len(truth_detection_observed_times_load))
        return {
            "reactive_load_factor_window_s": float(window_s),
            "reactive_load_factor_nominal_service_s": float(service_s),
            "reactive_load_factor_truth_candidate": _load_factor(truth_candidate_count),
            "reactive_load_factor_truth": _load_factor(truth_accepted_count),
            "reactive_load_factor_observable": _load_factor(detection_in_range_count),
            "reactive_load_factor_observed": _load_factor(detection_observed_count),
            "reactive_load_window_truth_candidate_events": int(truth_candidate_count),
            "reactive_load_window_truth_accepted_events": int(truth_accepted_count),
            "reactive_load_window_detection_opportunities": int(detection_opportunity_count),
            "reactive_load_window_detections_in_range": int(detection_in_range_count),
            "reactive_load_window_detections_observed": int(detection_observed_count),
        }

    def _active_modes_by_cell():
        """Return active deterrence modes by partition cell for STL monitoring."""
        active_modes = {}
        for task_row in active_tasks:
            if str(task_row.get("state", "")).strip().lower() != "active":
                continue
            if task_action_kind(task_row, deterring_modes, float(tau_service_s)) != "deterring":
                continue
            cell_id = _cell_id_for_xy(task_row.get("x", 0.0), task_row.get("y", 0.0))
            if cell_id is None:
                continue
            mode_label = task_action_name(task_row, deterring_modes, float(tau_service_s))
            mode_idx = _mode_id_for_label(_habituation_mode_label(mode_label))
            if mode_idx is not None:
                active_modes[int(cell_id)] = int(mode_idx)
        return active_modes

    def _habituation_variety_index():
        """Compute a mode-use entropy summary for habituation diagnostics."""
        entropies = []
        denom = math.log(max(len(mode_labels), 2))
        for counts_by_mode in mode_use_by_cell.values():
            counts = np.array(list(counts_by_mode.values()), dtype=float)
            if counts.size <= 0 or float(np.sum(counts)) <= 0.0:
                continue
            if np.count_nonzero(counts) <= 1:
                entropies.append(0.0)
                continue
            p = counts / float(np.sum(counts))
            entropies.append(float(-np.sum(p * np.log(p + 1e-12)) / denom))
        return float(np.mean(entropies)) if entropies else float("nan")

    def _stl_and_habituation_metrics(now_t):
        """Compute per-frame habituation and STL robustness metrics for production exports."""
        active_modes = _active_modes_by_cell()
        robustness_by_robot = {}
        for rid, rob in robots.items():
            rid_key = str(rid)
            monitor = stl_monitors_by_robot.get(rid_key)
            if monitor is None:
                monitor = RobotMonitor(_local_cell_ids_for_robot(rid_key), stl_spec_params)
                stl_monitors_by_robot[rid_key] = monitor
            exposures = {
                int(cell_id): cell_exposure_rate(rob.m, cells[int(cell_id)], weight_fn=value_weight)
                for cell_id in monitor.cells
                if 0 <= int(cell_id) < len(cells)
            }
            coverage_ages = {
                int(cell_id): max(0.0, float(now_t) - float(last_service_t_by_cell.get(int(cell_id), 0.0)))
                for cell_id in monitor.cells
                if 0 <= int(cell_id) < len(cells)
            }
            monitor.record(float(now_t), exposures, coverage_ages, active_modes, hab)
            robustness_by_robot[rid_key] = monitor.robustness()
        last_stl_robustness_by_robot.clear()
        last_stl_robustness_by_robot.update(robustness_by_robot)

        global_values = [
            float(payload.get("global"))
            for payload in robustness_by_robot.values()
            if math.isfinite(float(payload.get("global", float("nan"))))
        ]

        def _clause_mean(name):
            """Compute the mean robustness for one STL clause across robot monitors."""
            values = [
                float(payload.get(name))
                for payload in robustness_by_robot.values()
                if math.isfinite(float(payload.get(name, float("nan"))))
            ]
            return float(np.mean(values)) if values else float("nan")

        eta_arr = np.asarray(hab.eta, dtype=float)
        return {
            "habituation_enabled": int(bool(enable_habituation)),
            "habituation_T_rec_s": float(habituation_T_rec_s),
            "habituation_kappa": float(habituation_kappa),
            "habituation_gamma": float(habituation_gamma),
            "direct_detection_habituation_mode": str(direct_detection_habituation_mode),
            "habituation_eta_mean": float(np.mean(eta_arr)) if eta_arr.size else float("nan"),
            "habituation_eta_min": float(np.min(eta_arr)) if eta_arr.size else float("nan"),
            "habituation_eta_at_apply_mean": (
                float(np.mean(eta_at_apply_samples)) if eta_at_apply_samples else float("nan")
            ),
            "habituation_variety_index": _habituation_variety_index(),
            "stl_E_star": float(stl_E_star),
            "stl_T_cov_s": float(stl_T_cov_s),
            "stl_T_react_s": float(stl_T_react_s),
            "stl_W_s": float(stl_W_s),
            "stl_eta_min": float(stl_eta_min),
            "stl_horizon_s": float(stl_horizon_s),
            "stl_monitor_dt_s": float(stl_monitor_dt_s),
            "stl_theta": float(stl_theta),
            "stl_smooth": int(bool(stl_smooth)),
            "stl_active_clauses": tuple(stl_active_clauses),
            "stl_robustness_global_mean": float(np.mean(global_values)) if global_values else float("nan"),
            "stl_robustness_global_min": float(np.min(global_values)) if global_values else float("nan"),
            "stl_robustness_exp": _clause_mean("exp"),
            "stl_robustness_cov": _clause_mean("cov"),
            "stl_robustness_hab": _clause_mean("hab"),
            "stl_robustness_by_robot": robustness_by_robot,
        }

    def _process_truth_event(x, y, t_now, enqueue_tasks=True, record_metrics=True):
        """Accept a truth event into exposure metrics, detection ingestion, and reactive task generation."""
        nonlocal value_weighted_exposure
        nonlocal truth_detection_opportunities, truth_detections_observed
        nonlocal truth_detections_missed_range, truth_detections_missed_false_negative
        truth_events.append((x, y, t_now))
        truth_event_times.append(float(t_now))
        recent_truth.append((x, y, t_now))
        if record_metrics:
            truth_accepted_event_times_load.append(float(t_now))
            _prune_reactive_load_window(float(t_now))
            value_weighted_exposure += float(value_weight(x, y))
        owner = None
        for rr in robots_def:
            zid = rr['id']
            zone_rr = id_to_cell.get(zid, [])
            if zone_rr and point_in_polygon(x, y, zone_rr):
                owner = zid; break
        if owner is not None:
            truth_detection_opportunities += 1
            if record_metrics:
                truth_detection_opportunity_times_load.append(float(t_now))
                _prune_reactive_load_window(float(t_now))
            # Only detect if within range of the owning robot
            ox, oy = pose[owner]
            if math.hypot(x - ox, y - oy) > detect_range_m:
                truth_detections_missed_range += 1
                return
            if record_metrics:
                truth_detection_in_range_times_load.append(float(t_now))
                _prune_reactive_load_window(float(t_now))
            if rng.random() > truth_event_detection_prob:
                truth_detections_missed_false_negative += 1
                return
            truth_detections_observed += 1
            if record_metrics:
                truth_detection_observed_times_load.append(float(t_now))
                _prune_reactive_load_window(float(t_now))
            if centralized_predictive_topology_enabled and global_predictive_model is not None:
                global_predictive_model.advance_time(float(t_now) - float(global_predictive_model.t_now))
                global_predictive_model.add_local_event(float(x), float(y))
                global_predictive_recent_events.append((float(x), float(y), float(t_now)))
            b = robots[owner].ingest_detection(x, y, t_now)
            bus.send_boundary_events(b, source_id=owner)
            if enqueue_tasks:
                if bool(enable_direct_detection_tasks):
                    refresh_task = _find_refreshable_direct_detection_task(x, y, t_now)
                    if refresh_task is None:
                        taskgen.on_detection(owner, x, y, t_now)
                    else:
                        _refresh_direct_detection_task(refresh_task, t_now)
                    pending_event_onsets.append({"x": float(x), "y": float(y), "t": float(t_now), "responded": False})
            recent_detections.append((x, y, t_now))
            if mon is not None and getattr(mon, 'enabled', False):
                mon.message(t_now, kind='detection', source=owner, target=owner,
                            data={'x': x, 'y': y})

    def _deterring_source(task_row):
        """Classify a completed deterring task by the source stream that generated it."""
        action_kind = task_action_kind(task_row, deterring_modes, float(tau_service_s))
        action_name = task_action_name(task_row, deterring_modes, float(tau_service_s))
        origin = str(task_row.get("origin", "")).strip().lower()
        if action_kind == "deterring" and action_name != "direct_detection":
            return "model_scored"
        if origin == "detection" or action_name == "direct_detection":
            return "direct_detection"
        # Conservative fallback: tasks with no explicit mode are treated as direct.
        return "direct_detection"

    def _is_direct_detection_task(task_row):
        """Return whether a task is a reactive direct-detection deterrence task."""
        return (
            task_action_kind(task_row, deterring_modes, float(tau_service_s)) == "deterring"
            and _deterring_source(task_row) == "direct_detection"
        )

    def _task_buffer_key(task):
        """Return the stable buffer key used to deduplicate active and candidate tasks."""
        return (
            task_action_kind(task, deterring_modes, float(tau_service_s)),
            task_action_name(task, deterring_modes, float(tau_service_s)),
            round(float(task.get("x", float("nan"))), 2),
            round(float(task.get("y", float("nan"))), 2),
            round(float(task.get("time", float("nan"))), 0),
        )

    def _direct_detection_refresh_status(task_row):
        """Return whether an active direct-detection task can absorb a new detection."""
        rid = str(task_row.get("assigned_primary", "")).strip()
        if bool(direct_detection_task_active_refresh_require_assigned) and not rid:
            return False, "unassigned"
        if task_row.get("started_hold") is not None:
            return True, None
        if math.isfinite(direct_detection_active_refresh_max_eta_s) and direct_detection_active_refresh_max_eta_s >= 0.0:
            eta_s = float("inf")
            if rid:
                eta_s = _assigned_robot_eta_seconds(
                    rid,
                    (float(task_row.get("x", 0.0)), float(task_row.get("y", 0.0))),
                )
            if not math.isfinite(eta_s):
                eta_s = float(task_row.get("eta_s", float("inf")))
            if eta_s > float(direct_detection_active_refresh_max_eta_s):
                return False, "eta"
        return True, None

    def _find_refreshable_direct_detection_task(x, y, t_now):
        """Find an active direct-detection task eligible for refresh by a new detection."""
        nonlocal direct_detection_task_refresh_skipped_unassigned, direct_detection_task_refresh_skipped_eta
        if not bool(enable_direct_detection_task_clustering):
            return None
        radius2 = float(direct_detection_active_refresh_radius_m) ** 2
        window_s = float(direct_detection_active_refresh_window_s)
        nearby = []
        for tr in active_tasks:
            if str(tr.get("state", "")).strip().lower() != "active":
                continue
            if not _is_direct_detection_task(tr):
                continue
            t_ref = float(tr.get("last_detection_t", tr.get("time", -1e18)))
            if (float(t_now) - t_ref) > window_s:
                continue
            dx = float(x) - float(tr.get("x", 0.0))
            dy = float(y) - float(tr.get("y", 0.0))
            d2 = dx * dx + dy * dy
            if d2 > radius2:
                continue
            nearby.append((d2, tr))
        if not nearby:
            return None
        nearby.sort(key=lambda item: item[0])
        first_reason = None
        for _, tr in nearby:
            allowed, reason = _direct_detection_refresh_status(tr)
            if allowed:
                return tr
            if first_reason is None:
                first_reason = reason
        if first_reason == "unassigned":
            direct_detection_task_refresh_skipped_unassigned += 1
        elif first_reason == "eta":
            direct_detection_task_refresh_skipped_eta += 1
        return None

    def _refresh_direct_detection_task(task_row, t_now):
        """Refresh an existing direct-detection task with a new detection timestamp."""
        nonlocal direct_detection_task_refresh_active
        task_row["last_detection_t"] = float(t_now)
        task_row["merged_detection_count"] = int(task_row.get("merged_detection_count", 1)) + 1
        task_row["cluster_refresh_count"] = int(task_row.get("cluster_refresh_count", 0)) + 1
        direct_detection_task_refresh_active += 1

    def _cluster_direct_detection_candidate_tasks(tasks):
        """Cluster direct-detection candidates before dispatch admission."""
        nonlocal direct_detection_task_cluster_groups, direct_detection_task_cluster_merged
        if not bool(enable_direct_detection_task_clustering):
            return list(tasks)
        direct_indices = [i for i, tr in enumerate(tasks) if _is_direct_detection_task(tr)]
        if len(direct_indices) <= 1:
            return list(tasks)

        direct_rows = [dict(tasks[i]) for i in direct_indices]
        radius2 = float(direct_detection_queued_cluster_radius_m) ** 2
        window_s = float(direct_detection_queued_cluster_window_s)
        visited = [False] * len(direct_rows)
        clustered_rows = []

        def _neighbor(a, b):
            """Return the adjacent vineyard lane center for local motion projection."""
            if abs(float(a.get("time", 0.0)) - float(b.get("time", 0.0))) > window_s:
                return False
            dx = float(a.get("x", 0.0)) - float(b.get("x", 0.0))
            dy = float(a.get("y", 0.0)) - float(b.get("y", 0.0))
            return (dx * dx + dy * dy) <= radius2

        for i in range(len(direct_rows)):
            if visited[i]:
                continue
            queue = [i]
            visited[i] = True
            component = []
            while queue:
                cur = queue.pop()
                component.append(cur)
                for j in range(len(direct_rows)):
                    if visited[j]:
                        continue
                    if _neighbor(direct_rows[cur], direct_rows[j]):
                        visited[j] = True
                        queue.append(j)

            members = [direct_rows[j] for j in component]
            members.sort(key=lambda tr: float(tr.get("time", 0.0)))
            rep = dict(members[0])
            rep["_member_task_keys"] = [_task_buffer_key(m) for m in members]
            rep["merged_detection_count"] = int(sum(int(m.get("merged_detection_count", 1)) for m in members))
            rep["cluster_refresh_count"] = int(sum(int(m.get("cluster_refresh_count", 0)) for m in members))
            rep["last_detection_t"] = float(max(float(m.get("last_detection_t", m.get("time", 0.0))) for m in members))
            if len(members) > 1:
                direct_detection_task_cluster_groups += 1
                direct_detection_task_cluster_merged += int(len(members) - 1)
            clustered_rows.append(rep)

        out = []
        inserted = False
        direct_index_set = set(direct_indices)
        for i, tr in enumerate(tasks):
            if i in direct_index_set:
                if not inserted:
                    out.extend(clustered_rows)
                    inserted = True
                continue
            out.append(tr)
        if not inserted:
            out.extend(clustered_rows)
        return out

    def _spawn_offspring(x, y, t_now):
        """Schedule Hawkes offspring events from an accepted ground-truth event."""
        n = rng.poisson(alpha_true)
        for _ in range(int(n)):
            dt_off = rng.exponential(omega_true)
            xo = float(np.clip(x + rng.normal(0.0, sigma_true), 0.0, W))
            yo = float(np.clip(y + rng.normal(0.0, sigma_true), 0.0, H))
            truth_queue.append((xo, yo, t_now + dt_off))

    def _future_truth_events(t0, horizon_s):
        """Return truth events in (t0, t0 + horizon_s]."""
        if not truth_events:
            return []
        i0 = bisect.bisect_right(truth_event_times, float(t0))
        i1 = bisect.bisect_right(truth_event_times, float(t0 + horizon_s))
        return truth_events[i0:i1]

    def _annotate_predictive_task_for_runtime(task_row):
        """Attach runtime confidence and utility annotations to a predictive task."""
        return annotate_predictive_utility_fields(
            task_row,
            predictive_utility_mode=str(predictive_utility_mode),
            predictive_confidence_source=str(predictive_confidence_source),
            predictive_confidence_power=float(predictive_confidence_power),
            is_direct_detection_task_fn=_is_direct_detection_task,
        )

    def _record_predictive_success_label_task(task_row):
        """Record whether a completed predictive task matched a later event label."""
        if _task_stream(task_row) != "predictive":
            return
        if bool(task_row.get("_predictive_success_proxy_recorded", False)):
            return
        task_row["_predictive_success_proxy_recorded"] = True
        predictive_success_label_tasks.append(dict(task_row))

    def _predictive_label_window(task_row):
        """Return the time window used for predictive success labeling."""
        start_t = _finite_task_metric(
            task_row,
            "t_assigned",
            _finite_task_metric(task_row, "time", 0.0),
        )
        deadline_candidates = [
            _finite_task_metric(task_row, "required_arrival_by_t", float("nan")),
            _finite_task_metric(task_row, "event_time", float("nan")),
            _finite_task_metric(task_row, "forecast_event_time", float("nan")),
        ]
        end_t = next((float(v) for v in deadline_candidates if math.isfinite(float(v))), float("nan"))
        if not math.isfinite(end_t):
            end_t = float(start_t) + float(forecast_horizon_s)
        if end_t < start_t:
            end_t = float(start_t)
        return float(start_t), float(end_t)

    def _predictive_success_proxy(task_row, *, now_t):
        """Estimate whether a predictive task was successful using nearby truth events."""
        if _task_stream(task_row) != "predictive":
            return None
        start_t, end_t = _predictive_label_window(task_row)
        if float(now_t) + 1.0e-9 < float(end_t):
            return None
        radius_m = max(float(forecast_match_radius_m), float(response_match_radius_m))
        radius2 = float(radius_m) ** 2
        i0 = bisect.bisect_left(truth_event_times, float(start_t))
        i1 = bisect.bisect_right(truth_event_times, float(end_t))
        tx = float(task_row.get("x", 0.0))
        ty = float(task_row.get("y", 0.0))
        for x_ev, y_ev, _t_ev in truth_events[i0:i1]:
            dx = float(x_ev) - tx
            dy = float(y_ev) - ty
            if dx * dx + dy * dy <= radius2:
                return True
        return False

    def _predictive_success_proxy_counts(now_t):
        """Aggregate predictive success proxy counts for completed tasks."""
        evaluated = 0
        success = 0
        for task_row in predictive_success_label_tasks:
            label = _predictive_success_proxy(task_row, now_t=float(now_t))
            if label is None:
                continue
            evaluated += 1
            if bool(label):
                success += 1
        false_positive = max(0, int(evaluated) - int(success))
        return int(evaluated), int(success), int(false_positive)

    def _global_hotspots(top_k):
        """Collect top hotspots across robots by score."""
        if centralized_predictive_topology_enabled and global_predictive_model is not None:
            try:
                hs = global_predictive_model.hotspots(
                    top_k=max(2 * int(top_k), int(top_k)),
                    merge_radius=max(8.0, 0.5 * sigma),
                    use_excess=True,
                    mask_poly=boundary,
                )
                return [
                    (float(h["x"]), float(h["y"]), float(h.get("score", 0.0)))
                    for h in hs[: int(top_k)]
                ]
            except Exception:
                pass
        hs_all = []
        for rid, rob in robots.items():
            try:
                hs = rob.m.hotspots(
                    top_k=max(2 * int(top_k), int(top_k)),
                    merge_radius=max(8.0, 0.5 * sigma),
                    use_excess=True,
                    mask_poly=rob.zone_polygon,
                )
                for h in hs:
                    hs_all.append((float(h["x"]), float(h["y"]), float(h.get("score", 0.0))))
            except Exception:
                pass
        hs_all.sort(key=lambda z: z[2], reverse=True)
        return hs_all[: int(top_k)]

    def _compact_action_variant_rows(row):
        """Build compact per-mode variant rows for planning diagnostics."""
        variants = row.get("predictive_action_variants") or []
        if not isinstance(variants, list):
            return []
        compact_variants = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            compact_variants.append(
                {
                    "mode": variant.get("mode"),
                    "action": task_action_public_dict(variant),
                    "score": float(variant.get("score", 0.0)),
                    "utility": float(variant.get("utility", 0.0)),
                    "predicted_deltaJ": float(variant.get("predicted_deltaJ", 0.0)),
                    "predictive_stl_U": variant.get("predictive_stl_U"),
                    "deltaJ_per_cost": float(variant.get("deltaJ_per_cost", 0.0)),
                    "cost_eta": float(variant.get("cost_eta", 0.0)),
                    "p_event": float(variant.get("p_event", float("nan"))),
                    "risk_conf": variant.get("risk_conf"),
                    "selection_weight": variant.get("selection_weight"),
                    "predictive_utility_mode": variant.get("predictive_utility_mode"),
                    "predictive_confidence_source": variant.get("predictive_confidence_source"),
                    "predictive_confidence_power": variant.get("predictive_confidence_power"),
                    "predictive_confidence": variant.get("predictive_confidence", variant.get("confidence")),
                    "confidence": variant.get("confidence", variant.get("predictive_confidence")),
                    "confidence_components": variant.get("confidence_components"),
                    "predictive_raw_deltaJ": variant.get("predictive_raw_deltaJ"),
                    "bernoulli_expected_deltaJ": variant.get("bernoulli_expected_deltaJ"),
                    "predictive_expected_deltaJ": variant.get("predictive_expected_deltaJ"),
                    "stl_summary": variant.get("stl_summary"),
                }
            )
        return compact_variants
    def _compact_task_rows(rows, task_type=None, limit=None):
        """Build compact task rows for planning diagnostics."""
        out = []
        limit_n = None if limit is None else max(int(limit), 0)
        for row in rows:
            if task_type is not None and str(row.get("type", "")).strip().lower() != str(task_type).strip().lower():
                continue
            out.append(
                {
                    "id": row.get("id"),
                    "stream": _task_stream(row),
                    "type": row.get("type"),
                    "origin": row.get("origin"),
                    "mode": row.get("mode"),
                    "action": task_action_public_dict(row),
                    "robot_id": row.get("robot_id"),
                    "assigned_primary": row.get("assigned_primary"),
                    "assigned_secondary": row.get("assigned_secondary"),
                    "x": float(row.get("x", 0.0)),
                    "y": float(row.get("y", 0.0)),
                    "score": float(row.get("score", 0.0)),
                    "utility": float(row.get("utility", 0.0)),
                    "eta_s": float(row.get("eta_s", float("nan"))),
                    "p_event": float(row.get("p_event", float("nan"))),
                    "predicted_deltaJ": float(row.get("predicted_deltaJ", 0.0)),
                    "predictive_stl_U": row.get("predictive_stl_U"),
                    "predictive_utility_mode": row.get("predictive_utility_mode"),
                    "predictive_confidence_source": row.get("predictive_confidence_source"),
                    "predictive_confidence_power": row.get("predictive_confidence_power"),
                    "predictive_confidence": row.get("predictive_confidence", row.get("confidence")),
                    "confidence": row.get("confidence", row.get("predictive_confidence")),
                    "confidence_components": row.get("confidence_components"),
                    "predictive_raw_deltaJ": row.get("predictive_raw_deltaJ"),
                    "bernoulli_expected_deltaJ": row.get("bernoulli_expected_deltaJ"),
                    "predictive_expected_deltaJ": row.get("predictive_expected_deltaJ"),
                    "predictive_mode_variant_count": int(row.get("predictive_mode_variant_count", 0)),
                    "predictive_generation_best_mode": row.get("predictive_generation_best_mode"),
                    "predictive_dispatch_resolved_mode": row.get("predictive_dispatch_resolved_mode"),
                    "predictive_dispatch_eta_basis": row.get("predictive_dispatch_eta_basis"),
                    "predictive_action_variants": _compact_action_variant_rows(row),
                }
            )
            if limit_n is not None and len(out) >= limit_n:
                break
        return out

    def _count_task_rows_by_origin(rows, task_type=None):
        """Count compact task rows by origin for planning diagnostics."""
        counts = {}
        for row in rows:
            if task_type is not None and str(row.get("type", "")).strip().lower() != str(task_type).strip().lower():
                continue
            origin = str(row.get("origin", "unknown")).strip().lower() or "unknown"
            counts[origin] = int(counts.get(origin, 0) + 1)
        return counts

    # ------------------------------------------------------------------------
    # Local helper closures: task generation, dispatch, and planner bookkeeping
    # ------------------------------------------------------------------------
    # --- Task system: persistent tasks (active + completed) ---
    taskgen  = TaskGenerator(merge_radius_m=max(8.0, 0.5*sigma))
    assigner = TaskAssigner(
        robots_state=robots,
        profiles=profiles,
        params={
            "uav_spinup_s": 8.0,
            "w_prio": w_prio,
            "prio_deterring": prio_deterring,
            "prio_patrolling": prio_patrolling,
            "w_load": float(assigner_w_load),
            "w_task_value": float(assigner_w_task_value) if bool(enable_assignment_task_value_term) else 0.0,
        },
    )
    graph_motion_graph = None
    graph_motion_states: dict[str, GraphRobotState] = {}
    graph_reservations_snapshot = GraphReservationTable()
    graph_robot_ids = [
        str(rid)
        for rid, profile in profiles.items()
        if str(getattr(profile, "type", "")).upper() == "UGV"
    ]
    if motion_planning_mode == "graph" and graph_robot_ids:
        graph_motion_graph = VineyardMotionGraph(
            W=float(W),
            H=float(H),
            row_spacing_m=float(row_spacing_m),
            row_width_m=float(row_width_m),
            headland_space_m=float(headland_space_m),
            graph_row_node_spacing_m=float(graph_row_node_spacing_m),
            graph_headland_node_spacing_m=float(graph_headland_node_spacing_m),
            graph_passing_bay_spacing_m=float(graph_passing_bay_spacing_m),
        )
        graph_motion_states = {
            str(rid): GraphRobotState()
            for rid in graph_robot_ids
        }

    def _graph_enabled_for_robot(rid: str) -> bool:
        """Return whether graph-based motion planning is active for one robot."""
        return (
            motion_planning_mode == "graph"
            and graph_motion_graph is not None
            and str(rid) in graph_motion_states
        )

    def _graph_eta_seconds(robot_id: str, target_xy: tuple[float, float]) -> float:
        """Estimate graph-route travel time between two world points."""
        rid = str(robot_id)
        if not _graph_enabled_for_robot(rid):
            return float("nan")
        if rid not in pose or rid not in profiles:
            return float("nan")
        try:
            start_node_id = snap_point_to_graph(
                graph_motion_graph,
                (float(pose[rid][0]), float(pose[rid][1])),
                anchor_snap_radius_m=float(graph_anchor_snap_radius_m),
            )
            goal_node_id = snap_point_to_graph(
                graph_motion_graph,
                (float(target_xy[0]), float(target_xy[1])),
                anchor_snap_radius_m=float(graph_anchor_snap_radius_m),
            )
        except Exception:
            return float("nan")
        if str(start_node_id) == str(goal_node_id):
            return 0.0
        _nodes, distance_m = graph_motion_graph.shortest_path(str(start_node_id), str(goal_node_id))
        if not math.isfinite(float(distance_m)):
            return float("inf")
        speed_mps = max(float(profiles[rid].speed_mps), 1.0e-6)
        return float(distance_m / speed_mps)

    assigner.set_travel_time_fn(_graph_eta_seconds if graph_motion_graph is not None else None)
    next_tid = 1
    active_tasks = []     # list of dicts: {id, type, x,y,time,origin,assigned_primary,assigned_secondary,state,started_hold}
    completed_tasks = []  # same schema + state='done'
    consumed_task_keys = set()
    recent_deterrences = deque(maxlen=200)  # {"x","y","t","mode","beta","sigma","omega"}
    model_deterring_accepted = 0
    model_deterring_accepted_by_source = {}
    model_deterring_rejected_budget = 0
    model_deterring_rejected_budget_count_mode = 0
    model_deterring_rejected_budget_utility_mode = 0
    model_deterring_by_robot = {rid: deque() for rid in robots}  # stores (t_s, utility)
    service_history_by_robot = {rid: deque() for rid in robots}  # stores (t_done_s, service_time_s)
    reactive_service_history_by_robot = {rid: deque() for rid in robots}  # stores (t_done_s, service_time_s)
    direct_deterring_arrivals_by_robot = {rid: deque() for rid in robots}  # stores t_assigned
    model_deterring_admissions_by_robot = {rid: deque() for rid in robots}  # stores t_assigned
    reactive_generated_total = 0
    predictive_generated_total = 0
    predictive_distinct_generated_keys = set()
    reactive_admitted_total = 0
    predictive_admitted_total = 0
    predictive_distinct_admitted_keys = set()
    predictive_expired_total = 0
    centralized_global_opportunity_count_total = 0
    cross_zone_assignment_total = 0
    predictive_zone_bonus_sum = 0.0
    predictive_zone_bonus_count = 0
    reactive_completed_total = 0
    predictive_completed_total = 0
    predictive_distinct_completed_keys = set()
    reactive_dispatched_task_ids = set()
    predictive_dispatched_task_ids = set()
    urgent_reactive_override_total = 0
    predictive_deadline_feasible_total = 0
    predictive_deadline_checked_total = 0
    predictive_confidence_sum = 0.0
    predictive_confidence_sample_count = 0
    predictive_confidence_completed_sum = 0.0
    predictive_confidence_completed_count = 0
    predictive_expected_deltaJ_total = 0.0
    predictive_raw_deltaJ_total = 0.0
    predictive_success_label_tasks = []
    predictive_risk_adjusted_candidates_total = 0
    predictive_risk_adjusted_rejected_confidence_total = 0
    predictive_risk_adjusted_rejected_slack_total = 0
    predictive_risk_adjusted_rejected_utility_total = 0
    predictive_risk_adjusted_rejected_cost_ratio_total = 0
    predictive_risk_adjusted_confidence_sum = 0.0
    predictive_risk_adjusted_utility_sum = 0.0
    predictive_risk_adjusted_candidate_sample_count = 0
    predictive_risk_adjusted_rho_eff_sum = 0.0
    predictive_risk_adjusted_reactive_pressure_sum = 0.0
    predictive_risk_adjusted_reactive_age_norm_sum = 0.0
    predictive_risk_adjusted_dispatch_sample_count = 0
    preventive_service_rate_snapshot = {rid: float("nan") for rid in robots}
    preventive_direct_arrival_rate_snapshot = {rid: float("nan") for rid in robots}
    preventive_capacity_remaining_snapshot = {rid: float("nan") for rid in robots}
    preventive_capacity_ready_snapshot = {rid: False for rid in robots}
    preventive_service_rate_mean_accum = 0.0
    preventive_direct_arrival_rate_mean_accum = 0.0
    preventive_capacity_remaining_mean_accum = 0.0
    preventive_capacity_sample_count = 0
    planner_rejected_unassigned = 0
    planner_rejected_task_cap = 0
    planner_rejected_patrol_cap = 0
    planner_rejected_patrol_locked_model_det = 0
    planner_rejected_model_det_cap = 0
    planner_rejected_model_det_cycle_cap = 0
    planner_rejected_model_det_busy_primary = 0
    planner_rejected_model_det_busy_fallback_quality = 0
    planner_rejected_model_det_direct_conflict = 0
    planner_accepted_model_det_idle_primary = 0
    planner_accepted_model_det_busy_primary = 0
    planner_replaced_patrol = 0
    forecast_last_eval_t = -1e9
    forecast_recall_vals = []
    forecast_precision_vals = []
    forecast_lead_times = []
    forecast_hit_flags = []
    stale_goal_clears = 0

    # --- Telemetry: initial zones and poses ---
    if mon is not None and getattr(mon, 'enabled', False):
        try:
            mon.prepare_live_dir(
                telemetry_dir,
                clear_existing=telemetry_clear_on_start,
                prompt_save_existing=telemetry_prompt_save,
                backup_on_save=True,
            )
        except Exception:
            pass
        for r in robots_def:
            rid = r['id']
            mon.set_zone(rid, id_to_cell.get(rid, []), t=0.0)
            x0, y0 = pose[rid]
            mon.pose(t=0.0, rid=rid, x=x0, y=y0)


    if deterring_modes is None:
        deterring_modes = {
            "formation": {"beta": 0.30, "omega": 800.0, "sigma": 18.0, "w_eta": 1.0, "fixed_cost": 0.0},
            "laser":     {"beta": 0.45, "omega": 400.0, "sigma": 10.0, "w_eta": 1.5, "fixed_cost": 0.0},
            "biosonic":  {"beta": 0.25, "omega": 600.0, "sigma": 20.0, "w_eta": 1.2, "fixed_cost": 0.0},
        }

    mode_labels = tuple(
        dict.fromkeys(("direct_detection", *(str(mode) for mode in deterring_modes.keys())))
    )
    mode_to_id = {mode: idx for idx, mode in enumerate(mode_labels)}

    def _habituation_mode_label(mode_label):
        """Map a task action name to the physical cue mode used by habituation."""
        label = str(mode_label or "direct_detection")
        if label == "direct_detection":
            mapped = str(direct_detection_habituation_mode or "direct_detection")
            return mapped if mapped else "direct_detection"
        return label
    hab = HabituationField(
        n_cells=len(cells),
        n_modes=len(mode_labels),
        T_rec=float(habituation_T_rec_s),
        kappa=float(habituation_kappa),
        gamma=float(habituation_gamma),
    )
    stl_spec_params = SpecParams(
        E_star=float(stl_E_star),
        T_cov=float(stl_T_cov_s),
        T_react=float(stl_T_react_s),
        W=float(stl_W_s),
        eta_min=float(stl_eta_min),
        horizon=float(stl_horizon_s),
        monitor_dt=float(stl_monitor_dt_s),
        theta=float(stl_theta),
        smooth=bool(stl_smooth),
        active_clauses=tuple(stl_active_clauses),
    )
    stl_dynamics = Dynamics(
        omega_e=float(omega),
        omega_u=float(omega_inhib),
        beta=tuple(
            float(deterring_modes.get(mode, {}).get("beta", beta_true))
            for mode in mode_labels
        ),
    )
    last_service_t_by_cell = {cell_id: 0.0 for cell_id in range(len(cells))}
    eta_at_apply_samples = []
    mode_use_by_cell = {}
    last_stl_robustness_by_robot = {}

    def _mode_id_for_label(mode_label):
        """Map a cue-mode label into the habituation/STL mode index."""
        return mode_to_id.get(str(mode_label))

    def _cell_id_for_xy(x, y):
        """Map a world point into a partition cell id."""
        for cell_id, poly in enumerate(cells):
            if poly and point_in_polygon(float(x), float(y), poly):
                return int(cell_id)
        return None

    def _rid_to_cell_id_map():
        """Map robot identifiers to their current partition cell ids."""
        return {
            str(rid): int(idx)
            for idx, rid in enumerate(getattr(partitioner, "ids", []))
            if idx < len(cells)
        }

    def _local_cell_ids_for_robot(rid):
        """Return the local STL cell ids monitored by one robot."""
        if centralized_predictive_topology_enabled:
            return list(range(len(cells)))
        rid_key = str(rid)
        rid_to_cell = _rid_to_cell_id_map()
        local_ids = []
        own_cell = rid_to_cell.get(rid_key)
        if own_cell is not None:
            local_ids.append(int(own_cell))
        robot_obj = robots.get(rid_key)
        if robot_obj is not None:
            for nbr in robot_obj.neighbors:
                nbr_cell = rid_to_cell.get(str(nbr))
                if nbr_cell is not None:
                    local_ids.append(int(nbr_cell))
        if not local_ids:
            local_ids = list(range(len(cells)))
        return sorted({int(cell_id) for cell_id in local_ids if 0 <= int(cell_id) < len(cells)})

    def _local_cell_ids_by_robot(robot_ids=None):
        """Return the local STL cell ids monitored by each robot."""
        ids = list(robots.keys()) if robot_ids is None else list(robot_ids)
        return {str(rid): _local_cell_ids_for_robot(str(rid)) for rid in ids}

    stl_monitors_by_robot = {
        str(rid): RobotMonitor(_local_cell_ids_for_robot(str(rid)), stl_spec_params)
        for rid in robots
    }

    taskgen.configure_actions(
        deterring_modes=deterring_modes,
        tau_service_s=float(tau_service_s),
    )
    taskgen.configure_predictive_lead_time(
        enable_predictive_lead_time=bool(enable_predictive_lead_time),
        predictive_timing_mode=str(predictive_timing_mode),
        predictive_lead_time_min_s=float(predictive_lead_time_min_s),
        predictive_lead_time_max_eta_s=float(predictive_lead_time_max_eta_s),
        predictive_lead_time_buffer_s=float(predictive_lead_time_buffer_s),
        predictive_lead_time_risk_power=float(predictive_lead_time_risk_power),
    )
    system_config_structured = build_production_system_config(
        dict(locals()),
        deterring_modes=deterring_modes,
    )
    emit_structured_config_once = True
    last_task_generation_structured = TaskGenerationStageResult(
        now_t=0.0,
        patrolling_enabled=bool(enable_patrolling),
        busy_deterring_robots=[],
        candidate_tasks=[],
        candidate_stream_counts={"reactive": 0, "predictive": 0},
        extracted_candidate_count=0,
        selected_candidate_count=0,
        selection_policy="",
        selection_rejected_counts={},
        source_buffer_size=0,
        seen_task_key_count=0,
        active_load_before_dispatch={rid: 0 for rid in robots},
        active_patrol_load_before_dispatch={rid: 0 for rid in robots},
        active_model_det_load_before_dispatch={rid: 0 for rid in robots},
        diag_counts={},
    )
    last_dispatch_structured = DispatchStageResult(
        now_t=0.0,
        dispatch_policy=str(dispatch_policy),
        reservation_fraction=float(reservation_fraction),
        reservation_window_s=float(reservation_window_s),
        reactive_override_slack_s=float(reactive_override_slack_s),
        reservation_softening_alpha=float(reservation_softening_alpha),
        reservation_age_softening_beta=float(reservation_age_softening_beta),
        reservation_age_gate=float(reservation_age_gate),
        predictive_slack_min_s=float(predictive_slack_min_s),
        reactive_pressure_max_for_predictive=float(reactive_pressure_max_for_predictive),
        predictive_confidence_min=float(predictive_confidence_min),
        predictive_deadline_weight=float(predictive_deadline_weight),
        predictive_eta_penalty_weight=float(predictive_eta_penalty_weight),
        predictive_utility_mode=str(predictive_utility_mode),
        predictive_confidence_source=str(predictive_confidence_source),
        predictive_confidence_power=float(predictive_confidence_power),
        predictive_time_score_deadline_scale_s=float(predictive_time_score_deadline_scale_s),
        predictive_time_score_reactive_pressure_weight=float(predictive_time_score_reactive_pressure_weight),
        predictive_time_score_infeasible_penalty=float(predictive_time_score_infeasible_penalty),
        predictive_utility_min=float(predictive_utility_min),
        predictive_cost_ratio_min=float(predictive_cost_ratio_min),
        predictive_opportunity_cost_weight=float(predictive_opportunity_cost_weight),
        predictive_eta_cost_weight=float(predictive_eta_cost_weight),
        predictive_service_cost_weight=float(predictive_service_cost_weight),
        risk_adjusted_reservation_alpha=float(risk_adjusted_reservation_alpha),
        risk_adjusted_reservation_beta=float(risk_adjusted_reservation_beta),
        predictive_timing_mode=str(predictive_timing_mode),
        predictive_expiry_grace_s=float(predictive_expiry_grace_s),
        predictive_selection_policy=str(predictive_selection_policy),
        candidate_count=0,
        candidate_stream_counts={"reactive": 0, "predictive": 0},
        accepted_tasks=[],
        accepted_stream_counts={"reactive": 0, "predictive": 0},
        rejected_counts={
            "unassigned": 0,
            "task_cap": 0,
            "patrol_cap": 0,
            "model_det_cap": 0,
            "model_det_cycle_cap": 0,
            "model_det_busy_primary": 0,
            "model_det_busy_fallback_quality": 0,
            "model_det_direct_conflict": 0,
            "budget": 0,
            "policy_blocked_predictive": 0,
        },
        rejected_model_det_tasks=[],
        ordering_policy="",
        ordered_candidate_preview=[],
        replaced_patrol_count=0,
        urgent_reactive_override_count=0,
        robot_predictive_share_snapshot={rid: 0.0 for rid in robots},
        active_load_after_dispatch={rid: 0 for rid in robots},
        active_patrol_load_after_dispatch={rid: 0 for rid in robots},
        active_model_det_load_after_dispatch={rid: 0 for rid in robots},
        model_deterring_accepted_total=0,
        model_deterring_rejected_budget_total=0,
        risk_adjusted_diagnostics=_risk_adjusted_dispatch_diagnostics(
            [],
            rho_eff=0.0,
            reactive_pressure=0.0,
            reactive_age_norm=0.0,
        ),
    )
    last_motion_execution_structured = MotionExecutionStageResult(
        now_t=0.0,
        motion_orchestration_mode=str(motion_orchestration_mode),
        motion_execution_backend="internal_sim" if motion_orchestration_mode == "local" else "external_command_only",
        external_feedback_applied=False,
        external_pose_updates_this_step=0,
        robot_states={rid: "idle" for rid in robots},
        commands=[],
        moving_distance_by_robot_step={rid: 0.0 for rid in robots},
        goals_active_count=0,
        dispatched_stream_counts_this_step={"reactive": 0, "predictive": 0},
        completed_stream_counts_this_step={"reactive": 0, "predictive": 0},
        completed_patrolling_this_step=0,
        completed_deterring_this_step=0,
        stale_goal_clears_this_step=0,
        holding_robot_count=0,
        moving_robot_count=0,
        idle_robot_count=int(len(robots)),
    )
    last_feedback_structured = FeedbackCommunicationStageResult(
        now_t=0.0,
        recent_deterrence_events_added_this_step=0,
        intervention_feedback_applied_this_step=0,
        boundary_messages_sent_this_step=0,
        intervention_messages_sent_this_step=0,
        boundary_bytes_sent_this_step=0,
        intervention_bytes_sent_this_step=0,
        intervention_msg_dropped_debounce_this_step=0,
        intervention_msg_dropped_low_weight_this_step=0,
        truth_suppressed_events_total=0,
        truth_accepted_events_total=0,
    )
    last_metrics_structured = MetricsStageResult(
        now_t=0.0,
        dispatch_policy=str(dispatch_policy),
        reservation_fraction=float(reservation_fraction),
        reservation_softening_alpha=float(reservation_softening_alpha),
        reservation_age_softening_beta=float(reservation_age_softening_beta),
        reservation_age_gate=float(reservation_age_gate),
        predictive_slack_min_s=float(predictive_slack_min_s),
        reactive_pressure_max_for_predictive=float(reactive_pressure_max_for_predictive),
        predictive_confidence_min=float(predictive_confidence_min),
        predictive_deadline_weight=float(predictive_deadline_weight),
        predictive_eta_penalty_weight=float(predictive_eta_penalty_weight),
        predictive_utility_mode=str(predictive_utility_mode),
        predictive_confidence_source=str(predictive_confidence_source),
        predictive_confidence_power=float(predictive_confidence_power),
        predictive_time_score_deadline_scale_s=float(predictive_time_score_deadline_scale_s),
        predictive_time_score_reactive_pressure_weight=float(predictive_time_score_reactive_pressure_weight),
        predictive_time_score_infeasible_penalty=float(predictive_time_score_infeasible_penalty),
        predictive_utility_min=float(predictive_utility_min),
        predictive_cost_ratio_min=float(predictive_cost_ratio_min),
        predictive_opportunity_cost_weight=float(predictive_opportunity_cost_weight),
        predictive_eta_cost_weight=float(predictive_eta_cost_weight),
        predictive_service_cost_weight=float(predictive_service_cost_weight),
        risk_adjusted_reservation_alpha=float(risk_adjusted_reservation_alpha),
        risk_adjusted_reservation_beta=float(risk_adjusted_reservation_beta),
        predictive_timing_mode=str(predictive_timing_mode),
        predictive_expiry_grace_s=float(predictive_expiry_grace_s),
        predictive_selection_policy=str(predictive_selection_policy),
        habituation_eta_mean=float("nan"),
        habituation_eta_min=float("nan"),
        habituation_eta_at_apply_mean=float("nan"),
        habituation_variety_index=float("nan"),
        stl_robustness_global_mean=float("nan"),
        stl_robustness_global_min=float("nan"),
        stl_robustness_exp=float("nan"),
        stl_robustness_cov=float("nan"),
        stl_robustness_hab=float("nan"),
        predictive_planning_topology=str(predictive_planning_topology),
        zone_assignment_mode=str(zone_assignment_mode),
        defer_predictive_action_selection=int(bool(defer_predictive_action_selection)),
        assignment_switch_penalty=float(assignment_switch_penalty),
        value_weighted_exposure=0.0,
        mean_response_time_s=float("nan"),
        completed_tasks_total=0,
        reactive_generated_total=0,
        predictive_generated_total=0,
        predictive_distinct_generated_total=0,
        reactive_admitted_total=0,
        predictive_admitted_total=0,
        predictive_distinct_admitted_total=0,
        reactive_dispatched_total=0,
        predictive_dispatched_total=0,
        reactive_completed_total=0,
        predictive_completed_total=0,
        predictive_distinct_completed_total=0,
        reactive_completed_fraction=float("nan"),
        predictive_completed_fraction=float("nan"),
        predictive_expired_total=0,
        predictive_expired_fraction=float("nan"),
        predictive_confidence_mean=float("nan"),
        predictive_confidence_completed_mean=float("nan"),
        predictive_expected_deltaJ_total=0.0,
        predictive_raw_deltaJ_total=0.0,
        predictive_completion_ratio=float("nan"),
        predictive_success_ratio=float("nan"),
        predictive_false_positive_ratio=float("nan"),
        predictive_success_proxy_evaluated_total=0,
        predictive_success_proxy_total=0,
        predictive_false_positive_proxy_total=0,
        centralized_global_opportunity_count_total=0,
        cross_zone_assignment_total=0,
        predictive_zone_bonus_mean=float("nan"),
        reactive_load_factor_estimate=float("nan"),
        robot_idle_fraction_mean=0.0,
        robot_reactive_fraction_mean=0.0,
        robot_predictive_fraction_mean=0.0,
        urgent_reactive_override_total=0,
        predictive_deadline_feasible_total=0,
        predictive_deadline_checked_total=0,
        predictive_deadline_feasible_fraction=float("nan"),
        boundary_message_count=0,
        boundary_bytes_sent=0,
        fleet_task_engagement_fraction_so_far=0.0,
        fleet_moving_fraction_so_far=0.0,
        fleet_idle_no_task_fraction_so_far=0.0,
        truth_suppression_rate=float("nan"),
        birds_deterred_pct=float("nan"),
        truth_suppression_rate_last_hour=float("nan"),
        birds_deterred_pct_last_hour=float("nan"),
        forecast_recall_at_k=float("nan"),
        forecast_precision_at_k=float("nan"),
    )
    last_truth_generation_structured = TruthEventStageResult(
        now_t=0.0,
        use_ground_truth=bool(use_ground_truth),
        truth_events_added_this_step=0,
        detections_added_this_step=0,
        truth_candidate_events_this_step=0,
        truth_accepted_events_this_step=0,
        truth_suppressed_events_this_step=0,
        truth_candidate_events_total=0,
        truth_accepted_events_total=0,
        truth_suppressed_events_total=0,
        suppression_effect_sum_total=0.0,
    )
    last_forecast_model_structured = ForecastModelStageResult(
        now_t=0.0,
        model_advance_dt_s=0.0,
        lam_mean_mean=float("nan"),
        lam_max_max=float("nan"),
        trigger_sum_total=float("nan"),
        inhib_sum_total=float("nan"),
        forecast_eval_ran_this_step=False,
        forecast_future_event_count=0,
        forecast_hotspot_count=0,
        forecast_hit_count=0,
        forecast_covered_event_count=0,
        forecast_recall_latest=float("nan"),
        forecast_precision_latest=float("nan"),
        forecast_samples_total=0,
    )
    last_telemetry_structured = TelemetryStageResult(
        now_t=0.0,
        telemetry_enabled=bool(mon is not None and getattr(mon, "enabled", False)),
        robot_pose_updates_this_step=0,
        robot_diag_updates_this_step=0,
        hotspot_exports_this_step=0,
        flush_called_this_step=False,
        telemetry_dir=str(telemetry_dir),
    )

    def _run_zone_partitioning_algorithm(now_t):
        """Health-aware zone partitioning and neighbor refresh."""
        nonlocal cells, id_to_cell, stl_monitors_by_robot
        if not any(profiles[rid].health <= health_threshold for rid in profiles):
            return False

        partitioner.recompute(force=True)
        cells = partitioner.cells_for_ids()
        id_to_cell = {rid: cells[i] for i, rid in enumerate(partitioner.ids)}
        if debug_zone_areas:
            def _poly_area(poly):
                """Compute polygon area using the shoelace formula for diagnostics and partition checks."""
                if not poly:
                    return 0.0
                s = 0.0
                n = len(poly)
                for k in range(n):
                    x1, y1 = poly[k]
                    x2, y2 = poly[(k + 1) % n]
                    s += x1 * y2 - x2 * y1
                return abs(0.5 * s)

            for rid0 in [rr["id"] for rr in robots_def]:
                area = _poly_area(id_to_cell.get(rid0, []))
                print(f"[zone@t={now_t:.1f}] {rid0} area={area:.2f}")
        for r in robots_def:
            rid = r["id"]
            robots[rid].update_zone(id_to_cell.get(rid, []))   # UAVs: []
            robots[rid].update_neighbors(partitioner.neighbors_for_id(rid))
            if mon is not None and getattr(mon, "enabled", False):
                mon.set_zone(rid, id_to_cell.get(rid, []), t=now_t)
        for cell_id in range(len(cells)):
            last_service_t_by_cell.setdefault(int(cell_id), 0.0)
        stl_monitors_by_robot = {
            str(rid): RobotMonitor(_local_cell_ids_for_robot(str(rid)), stl_spec_params)
            for rid in robots
        }
        return True

    def _run_truth_generation_algorithm(now_t):
        """Ground-truth event generation and local/boundary detection ingestion."""
        nonlocal truth_candidate_events, truth_accepted_events, truth_suppressed_events
        nonlocal suppression_effect_sum

        if bool(enable_habituation):
            hab.recover(dt)

        truth_step = run_truth_generation_stage(
            use_ground_truth=use_ground_truth,
            now_t=now_t,
            dt=dt,
            rng=rng,
            W=W,
            H=H,
            w_cdf=w_cdf,
            w_shape=w_shape,
            mu_true=mu_true,
            sample_from_value_map_fn=_sample_from_value_map,
            suppression_eval_fn=_suppression_eval,
            process_truth_event_fn=_process_truth_event,
            spawn_offspring_fn=_spawn_offspring,
            truth_queue=truth_queue,
            suppression_effect_by_mode=suppression_effect_by_mode,
            suppression_effect_by_source=suppression_effect_by_source,
            truth_candidate_events=truth_candidate_events,
            truth_accepted_events=truth_accepted_events,
            truth_suppressed_events=truth_suppressed_events,
            suppression_effect_sum=suppression_effect_sum,
            robots_def=robots_def,
            pose=pose,
            bird_present_until=bird_present_until,
            last_detection_time=last_detection_time,
            detect_rate_per_robot=detect_rate_per_robot,
            bird_stay_mean_s=bird_stay_mean_s,
            bird_detection_prob=bird_detection_prob,
            per_robot_cooldown_s=per_robot_cooldown_s,
            max_detections_per_step=max_detections_per_step,
            detect_sigma_m=detect_sigma_m,
            id_to_cell=id_to_cell,
            point_in_polygon_fn=point_in_polygon,
            robots=robots,
            bus=bus,
            taskgen=taskgen,
            pending_event_onsets=pending_event_onsets,
            mon=mon,
            record_truth_window_event_fn=_record_truth_window_event,
        )
        truth_candidate_events = int(truth_step.truth_candidate_events)
        truth_accepted_events = int(truth_step.truth_accepted_events)
        truth_suppressed_events = int(truth_step.truth_suppressed_events)
        suppression_effect_sum = float(truth_step.suppression_effect_sum)
        return truth_step

    def _prune_preventive_histories(now_t):
        """Prune rolling histories used for preventive capacity estimation."""
        prune_preventive_histories(
            now_t=now_t,
            robot_ids=robots.keys(),
            history_window_s=float(model_deterring_capacity_history_window_s),
            model_deterring_by_robot=model_deterring_by_robot,
            service_history_by_robot=service_history_by_robot,
            direct_deterring_arrivals_by_robot=direct_deterring_arrivals_by_robot,
            model_deterring_admissions_by_robot=model_deterring_admissions_by_robot,
        )

    def _preventive_capacity_state(now_t):
        """Compute preventive capacity availability and service-rate estimates by robot."""
        nonlocal preventive_service_rate_mean_accum, preventive_direct_arrival_rate_mean_accum
        nonlocal preventive_capacity_remaining_mean_accum, preventive_capacity_sample_count
        result = compute_preventive_capacity_state(
            now_t=now_t,
            robot_ids=robots.keys(),
            history_window_s=float(model_deterring_capacity_history_window_s),
            rho_max=float(model_deterring_capacity_rho_max),
            min_completed=int(model_deterring_capacity_min_completed_tasks),
            budget_mode=str(model_deterring_budget_mode),
            fallback_budget_per_hr=float(model_deterring_capacity_fallback_budget_per_hr),
            model_deterring_by_robot=model_deterring_by_robot,
            service_history_by_robot=service_history_by_robot,
            direct_deterring_arrivals_by_robot=direct_deterring_arrivals_by_robot,
            model_deterring_admissions_by_robot=model_deterring_admissions_by_robot,
            preventive_service_rate_snapshot=preventive_service_rate_snapshot,
            preventive_direct_arrival_rate_snapshot=preventive_direct_arrival_rate_snapshot,
            preventive_capacity_remaining_snapshot=preventive_capacity_remaining_snapshot,
            preventive_capacity_ready_snapshot=preventive_capacity_ready_snapshot,
        )
        remaining = result["remaining"]
        ready = result["ready"]
        remain_vals = result["remain_vals"]
        service_vals = result["service_vals"]
        direct_vals = result["direct_vals"]
        if remain_vals or service_vals or direct_vals:
            preventive_capacity_sample_count += 1
            preventive_capacity_remaining_mean_accum += float(np.mean(remain_vals)) if remain_vals else 0.0
            preventive_service_rate_mean_accum += float(np.mean(service_vals)) if service_vals else 0.0
            preventive_direct_arrival_rate_mean_accum += float(np.mean(direct_vals)) if direct_vals else 0.0
        return remaining, ready

    def _reactive_load_factor_estimate(now_t):
        """Estimate current reactive load for dispatch pressure and metrics."""
        window_s = max(float(effective_reactive_load_factor_window_s), 1.0)
        cutoff_t = float(now_t) - window_s
        arrival_count = 0
        reactive_service_samples = []
        for rid in robots:
            arrivals = direct_deterring_arrivals_by_robot.get(rid, deque())
            arrival_count += int(sum(1 for ts in arrivals if float(ts) >= cutoff_t))
            service_hist = reactive_service_history_by_robot.get(rid, deque())
            reactive_service_samples.extend(
                float(duration_s)
                for done_t, duration_s in service_hist
                if float(done_t) >= cutoff_t
            )
        if not reactive_service_samples:
            return float("nan")
        fleet_arrival_rate = float(arrival_count) / window_s
        mean_service_s = float(np.mean(reactive_service_samples))
        if len(robots) <= 0:
            return float("nan")
        return float(fleet_arrival_rate * mean_service_s / float(len(robots)))

    def _current_busy_deterring_robots_algorithm():
        """Robots currently occupied by active deterring tasks."""
        return current_busy_deterring_robots(active_tasks)

    def _run_preventive_capacity_gating_algorithm(now_t):
        """Preventive-capacity estimate used to gate model-scored deterring generation."""
        if not enable_patrolling:
            return {rid: float("nan") for rid in robots}, {rid: False for rid in robots}
        return _preventive_capacity_state(now_t)

    def _run_task_location_estimation_algorithm(
        now_t,
        *,
        busy_deterring_robots,
        preventive_capacity_remaining,
        preventive_capacity_ready,
    ):
        """Estimate patrol and preventive task locations from the field and recent events."""
        planning_robots = (
            centralized_planning_robots
            if centralized_predictive_topology_enabled and centralized_planning_robots is not None
            else robots
        )
        run_task_location_estimation(
            taskgen=taskgen,
            robots=planning_robots,
            now_t=now_t,
            enable_patrolling=bool(enable_patrolling),
            enable_predictive_patrol_tasks=bool(enable_predictive_patrol_tasks),
            include_fallback_patrol=bool(include_fallback_patrol),
            enable_model_scored_deterring=bool(enable_model_scored_deterring),
            model_deterring_window_s=float(model_deterring_window_s),
            model_deterring_risk_threshold=float(model_deterring_risk_threshold),
            model_deterring_risk_scale=float(model_deterring_risk_scale),
            model_deterring_min_recent_points=int(model_deterring_min_recent_points),
            model_deterring_field_threshold=model_deterring_field_threshold,
            model_deterring_min_persistence_replans=int(model_deterring_min_persistence_replans),
            model_deterring_persistence_max_gap_s=float(model_deterring_persistence_max_gap_s),
            model_deterring_score_margin=float(model_deterring_score_margin),
            model_deterring_repeat_block_window_s=float(model_deterring_repeat_block_window_s),
            model_deterring_repeat_block_radius_m=float(model_deterring_repeat_block_radius_m),
            model_deterring_max_eta_s=float(model_deterring_max_eta_s),
            model_deterring_busy_min_support_override=int(model_deterring_busy_min_support_override),
            model_deterring_busy_risk_override=float(model_deterring_busy_risk_override),
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
            preventive_capacity_remaining_by_robot=preventive_capacity_remaining,
            preventive_capacity_ready_by_robot=preventive_capacity_ready,
            task_replan_period_s=float(task_replan_period_s),
            busy_deterring_robots=busy_deterring_robots,
            recent_deterrences=list(recent_deterrences),
            profiles=profiles,
            use_live_robot_pose_for_task_planning=bool(use_live_robot_pose_for_task_planning),
            pose=pose,
            rng=rng,
            patrol_hotspot_filter_mode=patrol_hotspot_filter_mode,
            patrol_hotspot_score_percentile=float(patrol_hotspot_score_percentile),
            patrol_hotspot_keep_top_k=patrol_hotspot_keep_top_k,
            patrol_feedback_inhibition_retention=float(patrol_feedback_inhibition_retention),
            patrol_scoring_mode=str(patrol_scoring_mode),
            patrol_shared_detection_range_m=(
                float(detect_range_m)
                if patrol_shared_detection_range_m is None
                else float(patrol_shared_detection_range_m)
            ),
            patrol_shared_detection_prob_per_step=(
                float(bird_detection_prob)
                if patrol_shared_detection_prob_per_step is None
                else float(patrol_shared_detection_prob_per_step)
            ),
            patrol_shared_detection_dwell_s=(
                float(bird_stay_mean_s)
                if patrol_shared_detection_dwell_s is None
                else float(patrol_shared_detection_dwell_s)
            ),
            patrol_shared_followup_success_prob=float(patrol_shared_followup_success_prob),
            patrol_shared_response_eta_decay_s=(
                max(float(bird_stay_mean_s), float(task_replan_period_s), 1.0)
                if patrol_shared_response_eta_decay_s is None
                else float(patrol_shared_response_eta_decay_s)
            ),
            enable_predictive_lead_time=bool(enable_predictive_lead_time),
            predictive_timing_mode=str(predictive_timing_mode),
            predictive_lead_time_min_s=float(predictive_lead_time_min_s),
            predictive_lead_time_max_eta_s=float(predictive_lead_time_max_eta_s),
            predictive_lead_time_buffer_s=float(predictive_lead_time_buffer_s),
            predictive_lead_time_risk_power=float(predictive_lead_time_risk_power),
            forecast_horizon_s=float(forecast_horizon_s),
            value_weight_fn=value_weight,
            deterring_modes=deterring_modes,
            travel_time_fn=(_graph_eta_seconds if graph_motion_graph is not None else None),
            predictive_utility_mode=str(predictive_utility_mode),
            stl_hab=hab,
            stl_spec_params=stl_spec_params,
            stl_dynamics=stl_dynamics,
            stl_cell_polys=cells,
            stl_local_cell_ids_by_robot=_local_cell_ids_by_robot(planning_robots.keys()),
            stl_last_service_t_by_cell=last_service_t_by_cell,
            stl_mode_to_id=mode_to_id,
            stl_cell_id_for_xy_fn=_cell_id_for_xy,
        )

    def _build_task_dispatch_candidate_buffer_algorithm(now_t):
        """Assemble the candidate task buffer passed from estimation into dispatch."""
        return build_task_dispatch_candidate_buffer(
            now_t=now_t,
            active_tasks=active_tasks,
            completed_tasks=completed_tasks,
            consumed_task_keys=consumed_task_keys,
            taskgen=taskgen,
            robot_ids=robots.keys(),
            task_buffer_key_fn=_task_buffer_key,
            is_direct_detection_task_fn=_is_direct_detection_task,
            cluster_direct_detection_candidate_tasks_fn=_cluster_direct_detection_candidate_tasks,
            predictive_utility_mode=str(predictive_utility_mode),
            predictive_confidence_source=str(predictive_confidence_source),
            predictive_confidence_power=float(predictive_confidence_power),
            predictive_owner_override_id=(
                "global"
                if centralized_predictive_topology_enabled
                else None
            ),
        )

    def _run_task_extraction_algorithm(
        now_t,
        *,
        busy_deterring_robots,
        preventive_capacity_remaining,
        preventive_capacity_ready,
    ):
        """SESTPP-driven task extraction before any pre-assignment selection."""
        if not bool(use_split_task_extraction_selection_pipeline):
            _run_task_location_estimation_algorithm(
                now_t,
                busy_deterring_robots=busy_deterring_robots,
                preventive_capacity_remaining=preventive_capacity_remaining,
                preventive_capacity_ready=preventive_capacity_ready,
            )
            return _build_task_dispatch_candidate_buffer_algorithm(now_t)

        return extract_task_candidates_from_sestpp(
            estimation_kwargs={
                "taskgen": taskgen,
                "robots": robots,
                "now_t": now_t,
                "enable_patrolling": bool(enable_patrolling),
                "enable_predictive_patrol_tasks": bool(enable_predictive_patrol_tasks),
                "include_fallback_patrol": bool(include_fallback_patrol),
                "enable_model_scored_deterring": bool(enable_model_scored_deterring),
                "model_deterring_window_s": float(model_deterring_window_s),
                "model_deterring_risk_threshold": float(model_deterring_risk_threshold),
                "model_deterring_risk_scale": float(model_deterring_risk_scale),
                "model_deterring_min_recent_points": int(model_deterring_min_recent_points),
                "model_deterring_field_threshold": model_deterring_field_threshold,
                "model_deterring_min_persistence_replans": int(model_deterring_min_persistence_replans),
                "model_deterring_persistence_max_gap_s": float(model_deterring_persistence_max_gap_s),
                "model_deterring_score_margin": float(model_deterring_score_margin),
                "model_deterring_repeat_block_window_s": float(model_deterring_repeat_block_window_s),
                "model_deterring_repeat_block_radius_m": float(model_deterring_repeat_block_radius_m),
                "model_deterring_max_eta_s": float(model_deterring_max_eta_s),
                "model_deterring_busy_min_support_override": int(model_deterring_busy_min_support_override),
                "model_deterring_busy_risk_override": float(model_deterring_busy_risk_override),
                "enable_predicted_deltaJ_gate": bool(enable_predicted_deltaJ_gate),
                "min_predicted_deltaJ_for_model_deterring": float(min_predicted_deltaJ_for_model_deterring),
                "model_deterring_gate_policy": str(model_deterring_gate_policy),
                "model_deterring_sprt_alpha": float(model_deterring_sprt_alpha),
                "model_deterring_sprt_beta": float(model_deterring_sprt_beta),
                "model_deterring_sprt_patch_radius_m": model_deterring_sprt_patch_radius_m,
                "model_deterring_min_sprt_margin": float(model_deterring_min_sprt_margin),
                "model_deterring_chance_threshold": float(model_deterring_chance_threshold),
                "model_deterring_min_deltaJ_per_cost": float(model_deterring_min_deltaJ_per_cost),
                "model_deterring_min_selection_weight": float(model_deterring_min_selection_weight),
                "preventive_capacity_remaining_by_robot": preventive_capacity_remaining,
                "preventive_capacity_ready_by_robot": preventive_capacity_ready,
                "task_replan_period_s": float(task_replan_period_s),
                "busy_deterring_robots": busy_deterring_robots,
                "recent_deterrences": list(recent_deterrences),
                "profiles": profiles,
                "use_live_robot_pose_for_task_planning": bool(use_live_robot_pose_for_task_planning),
                "pose": pose,
                "rng": rng,
                "patrol_hotspot_filter_mode": patrol_hotspot_filter_mode,
                "patrol_hotspot_score_percentile": float(patrol_hotspot_score_percentile),
                "patrol_hotspot_keep_top_k": patrol_hotspot_keep_top_k,
                "patrol_feedback_inhibition_retention": float(patrol_feedback_inhibition_retention),
                "patrol_scoring_mode": str(patrol_scoring_mode),
                "patrol_shared_detection_range_m": (
                    float(detect_range_m)
                    if patrol_shared_detection_range_m is None
                    else float(patrol_shared_detection_range_m)
                ),
                "patrol_shared_detection_prob_per_step": (
                    float(bird_detection_prob)
                    if patrol_shared_detection_prob_per_step is None
                    else float(patrol_shared_detection_prob_per_step)
                ),
                "patrol_shared_detection_dwell_s": (
                    float(bird_stay_mean_s)
                    if patrol_shared_detection_dwell_s is None
                    else float(patrol_shared_detection_dwell_s)
                ),
                "patrol_shared_followup_success_prob": float(patrol_shared_followup_success_prob),
                "patrol_shared_response_eta_decay_s": (
                    max(float(bird_stay_mean_s), float(task_replan_period_s), 1.0)
                    if patrol_shared_response_eta_decay_s is None
                    else float(patrol_shared_response_eta_decay_s)
                ),
                "enable_predictive_lead_time": bool(enable_predictive_lead_time),
                "predictive_timing_mode": str(predictive_timing_mode),
                "predictive_lead_time_min_s": float(predictive_lead_time_min_s),
                "predictive_lead_time_max_eta_s": float(predictive_lead_time_max_eta_s),
                "predictive_lead_time_buffer_s": float(predictive_lead_time_buffer_s),
                "predictive_lead_time_risk_power": float(predictive_lead_time_risk_power),
                "forecast_horizon_s": float(forecast_horizon_s),
                "value_weight_fn": value_weight,
                "deterring_modes": deterring_modes,
                "travel_time_fn": (_graph_eta_seconds if graph_motion_graph is not None else None),
                "predictive_utility_mode": str(predictive_utility_mode),
                "stl_hab": hab,
                "stl_spec_params": stl_spec_params,
                "stl_dynamics": stl_dynamics,
                "stl_cell_polys": cells,
                "stl_local_cell_ids_by_robot": _local_cell_ids_by_robot(robots.keys()),
                "stl_last_service_t_by_cell": last_service_t_by_cell,
                "stl_mode_to_id": mode_to_id,
                "stl_cell_id_for_xy_fn": _cell_id_for_xy,
            },
            buffer_kwargs={
                "now_t": now_t,
                "active_tasks": active_tasks,
                "completed_tasks": completed_tasks,
                "consumed_task_keys": consumed_task_keys,
                "taskgen": taskgen,
                "robot_ids": robots.keys(),
                "task_buffer_key_fn": _task_buffer_key,
                "is_direct_detection_task_fn": _is_direct_detection_task,
                "cluster_direct_detection_candidate_tasks_fn": _cluster_direct_detection_candidate_tasks,
                "predictive_utility_mode": str(predictive_utility_mode),
                "predictive_confidence_source": str(predictive_confidence_source),
                "predictive_confidence_power": float(predictive_confidence_power),
            },
        )

    def _run_task_selection_algorithm(now_t, extraction_buffer):
        """Pre-assignment gating/selection over extracted task candidates."""
        if not bool(use_split_task_extraction_selection_pipeline):
            candidate_tasks = [dict(task) for task in extraction_buffer["candidate_tasks"]]
            return {
                "selection_policy": "legacy_inline_dispatch",
                "selected_candidate_tasks": candidate_tasks,
                "rejected_candidate_tasks": [],
                "rejected_counts": {},
                "extracted_candidate_count": int(len(candidate_tasks)),
                "selected_candidate_count": int(len(candidate_tasks)),
            }

        return select_preassignment_task_candidates(
            candidate_tasks=extraction_buffer["candidate_tasks"],
            selection_policy=str(preassignment_selection_policy),
            selection_limit=int(preassignment_selection_limit),
            is_direct_detection_task_fn=_is_direct_detection_task_row,
            priority_sort_key_fn=_dispatch_priority_sort_key,
            now_t=float(now_t),
            active_load_by_robot=extraction_buffer["active_load"],
            active_patrol_load_by_robot=extraction_buffer["active_patrol_load"],
            active_model_det_load_by_robot=extraction_buffer["active_model_det_load"],
            max_active_tasks_per_robot=int(max_active_tasks_per_robot),
            max_active_patrolling_per_robot=int(max_active_patrolling_per_robot),
            max_active_model_deterring_per_robot=int(max_active_model_deterring_per_robot),
            preserve_direct_detection_priority=True,
        )

    def _run_task_generation_stage(now_t, patrolling_only=False):
        """Run task generation and return the structured generation-stage result."""
        nonlocal reactive_generated_total, predictive_generated_total, predictive_distinct_generated_keys
        nonlocal centralized_global_opportunity_count_total
        if not patrolling_only:
            pass  # direct-detection deterring tasks are still enqueued elsewhere
        busy_deterring_robots = _current_busy_deterring_robots_algorithm()
        preventive_capacity_remaining, preventive_capacity_ready = _run_preventive_capacity_gating_algorithm(now_t)
        extraction_buffer = _run_task_extraction_algorithm(
            now_t,
            busy_deterring_robots=busy_deterring_robots,
            preventive_capacity_remaining=preventive_capacity_remaining,
            preventive_capacity_ready=preventive_capacity_ready,
        )
        selection_buffer = _run_task_selection_algorithm(now_t, extraction_buffer)
        candidate_tasks = list(selection_buffer["selected_candidate_tasks"])
        candidate_stream_counts = _count_tasks_by_stream(candidate_tasks)
        reactive_generated_total += int(candidate_stream_counts.get("reactive", 0))
        predictive_generated_total += int(candidate_stream_counts.get("predictive", 0))
        for task_row in candidate_tasks:
            if _task_stream(task_row) != "predictive":
                continue
            opportunity_key = _predictive_opportunity_key(task_row)
            if opportunity_key:
                predictive_distinct_generated_keys.add(opportunity_key)
        if centralized_predictive_topology_enabled:
            centralized_global_opportunity_count_total += int(
                len({_predictive_opportunity_key(task_row) for task_row in candidate_tasks if _predictive_opportunity_key(task_row)})
            )

        return TaskGenerationStageResult(
            now_t=float(now_t),
            patrolling_enabled=bool(enable_patrolling),
            busy_deterring_robots=sorted(str(rid) for rid in busy_deterring_robots),
            candidate_tasks=candidate_tasks,
            candidate_stream_counts=dict(candidate_stream_counts),
            extracted_candidate_count=int(selection_buffer["extracted_candidate_count"]),
            selected_candidate_count=int(selection_buffer["selected_candidate_count"]),
            selection_policy=str(selection_buffer["selection_policy"]),
            selection_rejected_counts=dict(selection_buffer["rejected_counts"]),
            source_buffer_size=int(len(extraction_buffer["recent_rows"])),
            seen_task_key_count=int(len(extraction_buffer["seen_keys"])),
            active_load_before_dispatch=dict(extraction_buffer["active_load"]),
            active_patrol_load_before_dispatch=dict(extraction_buffer["active_patrol_load"]),
            active_model_det_load_before_dispatch=dict(extraction_buffer["active_model_det_load"]),
            diag_counts=dict(getattr(taskgen, "diag_counts", {})),
        )

    def _run_dispatch_stage(now_t, task_stage):
        """Run dispatch admission/assignment and return the structured dispatch-stage result."""
        nonlocal next_tid, model_deterring_accepted, model_deterring_accepted_by_source, model_deterring_rejected_budget, consumed_task_keys
        nonlocal model_deterring_rejected_budget_count_mode, model_deterring_rejected_budget_utility_mode
        nonlocal planner_rejected_unassigned, planner_rejected_task_cap
        nonlocal planner_rejected_patrol_cap, planner_rejected_patrol_locked_model_det, planner_rejected_model_det_cap
        nonlocal planner_rejected_model_det_cycle_cap, planner_rejected_model_det_busy_primary
        nonlocal planner_rejected_model_det_busy_fallback_quality, planner_rejected_model_det_direct_conflict
        nonlocal planner_accepted_model_det_idle_primary, planner_accepted_model_det_busy_primary
        nonlocal planner_replaced_patrol
        nonlocal reactive_admitted_total, predictive_admitted_total
        nonlocal predictive_distinct_admitted_keys
        nonlocal predictive_deadline_feasible_total, predictive_deadline_checked_total
        nonlocal predictive_confidence_sum, predictive_confidence_sample_count
        nonlocal predictive_expected_deltaJ_total, predictive_raw_deltaJ_total
        nonlocal predictive_risk_adjusted_candidates_total
        nonlocal predictive_risk_adjusted_rejected_confidence_total, predictive_risk_adjusted_rejected_slack_total
        nonlocal predictive_risk_adjusted_rejected_utility_total, predictive_risk_adjusted_rejected_cost_ratio_total
        nonlocal predictive_risk_adjusted_confidence_sum, predictive_risk_adjusted_utility_sum
        nonlocal predictive_risk_adjusted_candidate_sample_count
        nonlocal predictive_risk_adjusted_rho_eff_sum, predictive_risk_adjusted_reactive_pressure_sum
        nonlocal predictive_risk_adjusted_reactive_age_norm_sum, predictive_risk_adjusted_dispatch_sample_count
        nonlocal cross_zone_assignment_total, predictive_zone_bonus_sum, predictive_zone_bonus_count

        active_load = dict(task_stage.active_load_before_dispatch)
        active_patrol_load = dict(task_stage.active_patrol_load_before_dispatch)
        active_model_det_load = dict(task_stage.active_model_det_load_before_dispatch)
        accepted_tasks = []
        accepted_stream_counts = {"reactive": 0, "predictive": 0}
        rejected_counts = {
            "unassigned": 0,
            "task_cap": 0,
            "patrol_cap": 0,
            "patrol_locked_model_det": 0,
            "model_det_cap": 0,
            "model_det_cycle_cap": 0,
            "model_det_busy_primary": 0,
            "model_det_busy_fallback_quality": 0,
            "model_det_direct_conflict": 0,
            "budget": 0,
            "policy_blocked_predictive": 0,
        }
        replaced_patrol_count = 0
        rejected_model_det_tasks = []
        assigner.set_robot_poses(pose if bool(use_live_robot_pose_for_task_planning) else None)
        model_deterring_accepted_this_cycle = 0
        candidate_stream_counts = dict(task_stage.candidate_stream_counts)
        robot_predictive_share_snapshot = {
            str(rid): float(robots[rid].predictive_share(now_t))
            for rid in robots
        }
        ordering_policy = (
            "direct-detection deterring tasks keep absolute priority; remaining patrol and "
            "model-scored preventive tasks share one lexicographic ordering by utility/score, "
            "predicted_deltaJ, deltaJ_per_cost, and lower ETA; admission constraints still "
            "apply afterward."
        )
        ordered_candidates = _ordered_dispatch_candidates(task_stage.candidate_tasks)
        ordered_candidate_preview = _build_dispatch_order_preview(task_stage.candidate_tasks)
        risk_adjusted_gate_results = []
        risk_adjusted_stage_rho_eff = 0.0
        risk_adjusted_stage_reactive_pressure = 0.0
        risk_adjusted_stage_reactive_age_norm = 0.0

        def _has_direct_detection_conflict(task_row, assigned_primary):
            """Return whether a candidate conflicts with protected direct-detection work."""
            return has_direct_detection_conflict(
                task_row=task_row,
                assigned_primary=assigned_primary,
                active_tasks=active_tasks,
                completed_tasks=completed_tasks,
                now_t=now_t,
                protect_direct_detection_from_model_deterring=bool(protect_direct_detection_from_model_deterring),
                direct_conflict_radius_m=float(model_deterring_direct_conflict_radius_m),
                direct_conflict_window_s=float(model_deterring_direct_conflict_window_s),
                deterring_source_fn=_deterring_source,
            )

        def _record_model_det_rejection(reason, task_row, assigned_primary=None, assigned_secondary=None):
            """Record a model-scored deterrence rejection reason for diagnostics."""
            if (not bool(emit_rejected_model_det_debug)) or (not _is_model_deterring_candidate(task_row)):
                return
            rejected_model_det_tasks.append(
                {
                    "reason": str(reason),
                    "x": float(task_row.get("x", 0.0)),
                    "y": float(task_row.get("y", 0.0)),
                    "time": float(task_row.get("time", now_t)),
                    "assigned_primary": assigned_primary,
                    "assigned_secondary": assigned_secondary,
                    "mode": task_row.get("mode"),
                    "origin": task_row.get("origin"),
                    "score": float(task_row.get("score", 0.0)),
                    "utility": float(task_row.get("utility", task_row.get("score", 0.0))),
                    "predicted_deltaJ": float(task_row.get("predicted_deltaJ", 0.0)),
                    "predictive_stl_U": task_row.get("predictive_stl_U"),
                    "p_event": float(task_row.get("p_event", 0.0)),
                    "deltaJ_per_cost": float(task_row.get("deltaJ_per_cost", 0.0)),
                    "llr": float(task_row.get("llr", 0.0)),
                    "eta_s": float(task_row.get("eta_s", 0.0)),
                    "support": int(task_row.get("support", 0)),
                    "risk_conf": float(task_row.get("risk_conf", 0.0)),
                    "persistence": int(task_row.get("persistence", 0)),
                }
            )

        def _passes_busy_fallback_quality(task_row):
            """Return whether a busy robot may accept a high-quality fallback candidate."""
            return passes_busy_fallback_quality(
                task_row=task_row,
                p_event_min=float(model_deterring_busy_fallback_p_event_min),
                deltaJ_per_cost_min=float(model_deterring_busy_fallback_deltaJ_per_cost_min),
                eta_s_max=float(model_deterring_busy_fallback_eta_s_max),
            )

        def _evict_active_patrol_task(evict_tr):
            """Remove an active patrol task so higher-priority work can use the robot."""
            nonlocal planner_replaced_patrol
            rid_e = evict_tr.get("assigned_primary")
            active_tasks[:] = [tr for tr in active_tasks if tr.get("id") != evict_tr.get("id")]
            if rid_e in active_load:
                active_load[rid_e] = max(0, active_load.get(rid_e, 0) - 1)
                active_patrol_load[rid_e] = max(0, active_patrol_load.get(rid_e, 0) - 1)
            if rid_e in goal and goal.get(rid_e) is not None:
                gx, gy = goal[rid_e]
                if math.hypot(float(evict_tr.get("x", 0.0)) - gx, float(evict_tr.get("y", 0.0)) - gy) <= arrival_radius_m:
                    goal[rid_e] = None
            planner_replaced_patrol += 1

        def _task_has_predictive_action_variants(task_row):
            """Return whether a task carries deferred predictive action variants."""
            if not bool(defer_predictive_action_selection):
                return False
            if _task_stream(task_row) != "predictive":
                return False
            variants = task_row.get("predictive_action_variants", [])
            return isinstance(variants, list) and len(variants) > 0

        def _eta_seconds_between_positions(rid, start_xy, tgt_xy, *, include_spin=False):
            """Estimate travel time between two positions using the active motion model."""
            if rid not in profiles:
                return float("nan")
            sx, sy = float(start_xy[0]), float(start_xy[1])
            tx, ty = float(tgt_xy[0]), float(tgt_xy[1])
            speed = max(float(profiles[rid].speed_mps), 1.0e-6)
            spin = 0.0
            if include_spin:
                spin = 8.0 if str(profiles[rid].type).upper() == "UAV" else 0.0
            return float(math.hypot(tx - sx, ty - sy) / speed + spin)

        def _zone_bonus_for_robot_task(rid, task_row):
            """Compute assignment preference for tasks inside the robot local zone."""
            if str(zone_assignment_mode).strip().lower() != "soft":
                return 0.0
            if rid not in robots:
                return 0.0
            rob = robots[rid]
            if not rob.zone_polygon:
                return 0.0
            return 1.0 if point_in_polygon(float(task_row["x"]), float(task_row["y"]), rob.zone_polygon) else 0.0

        def _hybrid_eta_seconds_for_robot(rid, task_row):
            """Estimate robot travel time with graph routing when available and lane projection otherwise."""
            tgt_xy = (float(task_row.get("x", 0.0)), float(task_row.get("y", 0.0)))
            if rid not in pose:
                return float("nan"), "unknown"
            current_goal_xy = goal.get(rid)
            busy = active_load.get(rid, 0) > 0 or current_goal_xy is not None
            if not busy or current_goal_xy is None:
                return _assigned_robot_eta_seconds(rid, tgt_xy), "live_pose"
            if math.hypot(
                float(current_goal_xy[0]) - float(tgt_xy[0]),
                float(current_goal_xy[1]) - float(tgt_xy[1]),
            ) <= float(arrival_radius_m):
                return _assigned_robot_eta_seconds(rid, tgt_xy), "committed_goal"
            current_goal_eta_s = _assigned_robot_eta_seconds(rid, current_goal_xy)
            if not math.isfinite(current_goal_eta_s):
                return _assigned_robot_eta_seconds(rid, tgt_xy), "live_pose"
            follow_eta_s = _eta_seconds_between_positions(
                rid,
                current_goal_xy,
                tgt_xy,
                include_spin=False,
            )
            return (
                float(current_goal_eta_s)
                + max(float(assignment_switch_penalty), 0.0)
                + max(float(follow_eta_s), 0.0),
                "switch_cost_adjusted",
            )

        def _deferred_assignment_score(rid, task_row, eta_s):
            """Score a deferred predictive action variant for one robot assignment."""
            prof = profiles[rid]
            rob = robots[rid]
            weights = assigner.w
            action_kind = task_action_kind(task_row)
            prio = (
                float(weights["prio_deterring"])
                if action_kind == "deterring"
                else float(weights["prio_patrolling"])
            )
            cap = float(prof.deterrent_eff) if action_kind == "deterring" else 1.0
            zone_bonus = _zone_bonus_for_robot_task(rid, task_row)
            load = float(active_load.get(rid, 0))
            task_value = float(task_row.get("utility", task_row.get("score", 0.0)))
            return (
                float(weights["w_cap"]) * cap
                - float(weights["w_eta"]) * max(float(eta_s), 0.0)
                + float(weights["w_stay"]) * float(prof.endurance_min)
                + float(weights["w_zone"]) * float(zone_bonus)
                + float(weights["w_health"]) * float(prof.health)
                + float(weights["w_prio"]) * float(prio)
                + float(weights["w_task_value"]) * float(task_value)
                - float(weights["w_load"]) * float(load)
            )

        def _resolve_predictive_task_for_robot(task_row, rid):
            """Resolve deferred predictive action variants once a concrete robot is considered."""
            variants = list(task_row.get("predictive_action_variants", []) or [])
            if not variants:
                return None
            reactive_pressure_local = _reactive_pressure(
                [task for task in active_tasks if _task_stream(task) == "reactive"]
            )
            resolved_variants = []
            for variant in variants:
                candidate = dict(task_row)
                candidate["mode"] = variant.get("mode")
                candidate["action"] = variant.get("action")
                for metric_key in (
                    "score",
                    "utility",
                    "predicted_deltaJ",
                    "deltaJ_per_cost",
                    "cost_eta",
                    "p_event",
                    "risk_conf",
                    "selection_weight",
                    "predictive_utility_mode",
                    "predictive_confidence_source",
                    "predictive_confidence_power",
                    "predictive_confidence_raw",
                    "predictive_confidence",
                    "confidence",
                    "confidence_components",
                    "predictive_raw_deltaJ",
                    "bernoulli_expected_deltaJ",
                    "predictive_expected_deltaJ",
                    "predictive_stl_U",
                    "stl_summary",
                ):
                    if metric_key in variant:
                        candidate[metric_key] = variant.get(metric_key)
                candidate = annotate_predictive_utility_fields(
                    candidate,
                    predictive_utility_mode=str(predictive_utility_mode),
                    predictive_confidence_source=str(predictive_confidence_source),
                    predictive_confidence_power=float(predictive_confidence_power),
                    is_direct_detection_task_fn=_is_direct_detection_task,
                )
                eta_s, eta_basis = _hybrid_eta_seconds_for_robot(rid, candidate)
                candidate["eta_s"] = float(eta_s)
                candidate["assigned_eta_s"] = float(eta_s)
                candidate["predictive_dispatch_eta_basis"] = str(eta_basis)
                candidate["predictive_dispatch_resolved_mode"] = candidate.get("mode")
                candidate["predictive_mode_variant_count"] = int(len(variants))
                if not assigner._eligible(profiles[rid], candidate):
                    continue
                resolved_variants.append(candidate)
            if not resolved_variants:
                return None
            selected = _select_predictive_task_for_policy(
                resolved_variants,
                predictive_selection_policy=predictive_selection_policy,
                rng=rng,
                now_t=float(now_t),
                reactive_pressure=float(reactive_pressure_local),
                predictive_confidence_source=predictive_confidence_source,
                predictive_confidence_power=float(predictive_confidence_power),
                predictive_deadline_weight=float(predictive_deadline_weight),
                predictive_eta_penalty_weight=float(predictive_eta_penalty_weight),
                predictive_time_score_deadline_scale_s=float(predictive_time_score_deadline_scale_s),
                predictive_time_score_reactive_pressure_weight=float(predictive_time_score_reactive_pressure_weight),
                predictive_time_score_infeasible_penalty=float(predictive_time_score_infeasible_penalty),
            )
            return None if selected is None else dict(selected)

        def _select_assignment_algorithm(task_row):
            """Assignment scoring and robot selection before dispatch admission gates."""
            if _task_has_predictive_action_variants(task_row):
                candidate_robot_ids = [
                    str(rid)
                    for rid in profiles
                    if assigner._eligible(profiles[str(rid)], task_row)
                ]
                if _is_model_deterring_candidate(task_row) and bool(model_deterring_prefer_idle_robots_for_assignment):
                    idle_robot_ids = [
                        rid for rid in candidate_robot_ids
                        if int(active_load.get(rid, 0)) <= 0
                    ]
                    if idle_robot_ids:
                        candidate_robot_ids = idle_robot_ids
                ranked = []
                for rid in candidate_robot_ids:
                    resolved_task = _resolve_predictive_task_for_robot(task_row, str(rid))
                    if resolved_task is None:
                        continue
                    eta_s = max(
                        _finite_task_metric(
                            resolved_task,
                            "assigned_eta_s",
                            _finite_task_metric(resolved_task, "eta_s", float("inf")),
                        ),
                        0.0,
                    )
                    ranked.append(
                        (
                            _deferred_assignment_score(str(rid), resolved_task, eta_s),
                            str(rid),
                            resolved_task,
                        )
                    )
                if not ranked:
                    return {
                        "task_type": str(task_row.get("type", "")).strip().lower(),
                        "is_model_det": bool(_is_model_deterring_candidate(task_row)),
                        "assigned_primary": None,
                        "assigned_secondary": None,
                        "resolved_task": None,
                    }
                ranked.sort(reverse=True, key=lambda item: item[0])
                primary = ranked[0][1]
                resolved_task = ranked[0][2]
                secondary = None
                if task_action_kind(resolved_task) == "deterring" and len(ranked) > 1:
                    for _score, rid, _resolved in ranked[1:]:
                        if str(profiles[primary].type).upper() == "UAV" and str(profiles[rid].type).upper() == "UGV":
                            secondary = rid
                            break
                    if secondary is None:
                        secondary = ranked[1][1]
                return {
                    "task_type": str(resolved_task.get("type", task_row.get("type", ""))).strip().lower(),
                    "is_model_det": bool(_is_model_deterring_candidate(resolved_task)),
                    "assigned_primary": primary,
                    "assigned_secondary": secondary,
                    "resolved_task": resolved_task,
                }
            selection = select_assignment(
                task_row=task_row,
                active_load=active_load,
                assigner=assigner,
                prefer_idle_for_model_deterring=bool(model_deterring_prefer_idle_robots_for_assignment),
                is_model_deterring_candidate_fn=_is_model_deterring_candidate,
            )
            return {
                "task_type": str(selection.task_type),
                "is_model_det": bool(selection.is_model_det),
                "assigned_primary": selection.assigned_primary,
                "assigned_secondary": selection.assigned_secondary,
                "resolved_task": None,
            }

        def _apply_patrol_lock_gating_algorithm(task_type, assigned_primary, now_t):
            """Protect robots already committed to locked preventive deterring work."""
            nonlocal planner_rejected_patrol_locked_model_det
            if (
                task_type == "patrolling"
                and bool(protect_locked_model_deterring_from_patrol_assignment)
                and _has_locked_model_deterring_on_robot(assigned_primary, now_t)
            ):
                planner_rejected_patrol_locked_model_det += 1
                rejected_counts["patrol_locked_model_det"] += 1
                return False
            return True

        def _evaluate_model_deterring_dispatch_gating_algorithm(
            task_row,
            assigned_primary,
            assigned_primary_busy,
            accepted_this_cycle,
            active_model_det_load_map,
            now_t,
        ):
            """Admission gates for model-scored deterring after assignment selection."""
            result = evaluate_model_deterring_dispatch_gating(
                task_row=task_row,
                assigned_primary=assigned_primary,
                assigned_primary_busy=bool(assigned_primary_busy),
                accepted_this_cycle=int(accepted_this_cycle),
                active_model_det_load_map=active_model_det_load_map,
                now_t=now_t,
                model_deterring_global_admission_cap_per_cycle=int(model_deterring_global_admission_cap_per_cycle),
                model_deterring_require_idle_robot_for_admission=bool(model_deterring_require_idle_robot_for_admission),
                model_deterring_budget_mode=str(model_deterring_budget_mode),
                model_deterring_budget_per_robot_per_hr=int(model_deterring_budget_per_robot_per_hr),
                model_deterring_budget_utility_per_robot_per_hr=float(model_deterring_budget_utility_per_robot_per_hr),
                max_active_model_deterring_per_robot=int(max_active_model_deterring_per_robot),
                model_deterring_by_robot=model_deterring_by_robot,
                dispatch_task_value_fn=_dispatch_task_value,
                is_model_deterring_candidate_fn=_is_model_deterring_candidate,
                direct_conflict_fn=_has_direct_detection_conflict,
                busy_fallback_quality_fn=_passes_busy_fallback_quality,
            )
            return {
                "reason": result.reason,
                "task_utility": float(result.task_utility),
                "budget_mode": str(result.budget_mode),
                "budget_queue": result.budget_queue,
            }

        def _apply_model_deterring_dispatch_rejection_accounting(reason):
            """Central accounting for preventive dispatch rejections."""
            nonlocal model_deterring_rejected_budget
            nonlocal model_deterring_rejected_budget_count_mode, model_deterring_rejected_budget_utility_mode
            nonlocal planner_rejected_model_det_cycle_cap, planner_rejected_model_det_busy_primary
            nonlocal planner_rejected_model_det_busy_fallback_quality, planner_rejected_model_det_direct_conflict
            nonlocal planner_rejected_model_det_cap

            if reason == "cycle_cap":
                planner_rejected_model_det_cycle_cap += 1
                rejected_counts["model_det_cycle_cap"] += 1
            elif reason == "busy_primary":
                planner_rejected_model_det_busy_primary += 1
                rejected_counts["model_det_busy_primary"] += 1
            elif reason == "busy_fallback_quality":
                planner_rejected_model_det_busy_fallback_quality += 1
                rejected_counts["model_det_busy_fallback_quality"] += 1
            elif reason == "direct_conflict":
                planner_rejected_model_det_direct_conflict += 1
                rejected_counts["model_det_direct_conflict"] += 1
            elif reason == "model_det_cap":
                planner_rejected_model_det_cap += 1
                rejected_counts["model_det_cap"] += 1
            elif reason == "budget":
                model_deterring_rejected_budget += 1
                rejected_counts["budget"] += 1
            else:
                return

        def _risk_adjusted_predictive_admission_gate(task_row, assigned_primary):
            """Apply risk-adjusted predictive admission gates and record rejection diagnostics."""
            nonlocal risk_adjusted_stage_rho_eff, risk_adjusted_stage_reactive_pressure
            nonlocal risk_adjusted_stage_reactive_age_norm
            if dispatch_policy != "res-risk-adjusted" or _task_stream(task_row) != "predictive":
                return True, None
            rid = str(assigned_primary)
            eta_s = _finite_task_metric(
                task_row,
                "assigned_eta_s",
                _assigned_robot_eta_seconds(
                    rid,
                    (float(task_row.get("x", 0.0)), float(task_row.get("y", 0.0))),
                ),
            )
            task_row["assigned_eta_s"] = float(max(eta_s, 0.0))
            local_reactive_tasks = [
                tr for tr in active_tasks
                if str(tr.get("assigned_primary", "")) == rid
                and str(tr.get("state", "")).strip().lower() == "active"
                and _task_stream(tr) == "reactive"
            ]
            gate = _predictive_feasibility_gates(
                task_row,
                now_t=float(now_t),
                eta_s=float(task_row["assigned_eta_s"]),
                reactive_tasks=local_reactive_tasks,
                reactive_override_slack_s=float(reactive_override_slack_s),
                eta_seconds_fn=lambda row: _assigned_robot_eta_seconds(
                    rid,
                    (float(row.get("x", 0.0)), float(row.get("y", 0.0))),
                ),
                predictive_confidence_min=float(predictive_confidence_min),
                predictive_utility_min=float(predictive_utility_min),
                predictive_cost_ratio_min=float(predictive_cost_ratio_min),
                predictive_slack_min_s=float(predictive_slack_min_s),
                predictive_confidence_source=str(predictive_confidence_source),
                predictive_confidence_power=float(predictive_confidence_power),
                predictive_opportunity_cost_weight=float(predictive_opportunity_cost_weight),
                predictive_eta_cost_weight=float(predictive_eta_cost_weight),
                predictive_service_cost_weight=float(predictive_service_cost_weight),
            )
            mean_feasible_confidence = float(gate["confidence"]) if bool(gate.get("accepted", False)) else 0.0
            rho_eff = _effective_risk_adjusted_reservation_fraction(
                reservation_fraction=float(reservation_fraction),
                mean_predictive_confidence=float(mean_feasible_confidence),
                reactive_pressure=float(gate["reactive_pressure"]),
                reactive_age_norm=float(gate["reactive_age_norm"]),
                risk_adjusted_reservation_alpha=float(risk_adjusted_reservation_alpha),
                risk_adjusted_reservation_beta=float(risk_adjusted_reservation_beta),
            )
            gate["rho_eff"] = float(rho_eff)
            gate["predictive_share"] = float(robot_predictive_share_snapshot.get(rid, 0.0))
            risk_adjusted_gate_results.append(gate)
            risk_adjusted_stage_rho_eff = float(rho_eff)
            risk_adjusted_stage_reactive_pressure = float(gate["reactive_pressure"])
            risk_adjusted_stage_reactive_age_norm = float(gate["reactive_age_norm"])

            for key, value in (
                ("predictive_confidence", gate["confidence"]),
                ("predictive_expected_reduction", gate["expected_reduction"]),
                ("predictive_cost", gate["cost"]),
                ("predictive_opportunity_cost", gate["opportunity_cost"]),
                ("predictive_risk_adjusted_utility", gate["utility"]),
                ("predictive_cost_ratio", gate["cost_ratio"]),
                ("predictive_deadline_slack_s", gate["slack_s"]),
                ("predictive_rho_eff", gate["rho_eff"]),
            ):
                task_row[key] = float(value)

            if not bool(gate.get("accepted", False)):
                return False, str(gate.get("reject_reason", "risk_gate"))
            if float(robot_predictive_share_snapshot.get(rid, 0.0)) >= float(rho_eff):
                gate["accepted"] = False
                gate["reject_reason"] = "reservation_share"
                return False, "reservation_share"
            if float(gate["reactive_age_norm"]) >= float(max(float(reservation_age_gate), 0.0)):
                gate["accepted"] = False
                gate["reject_reason"] = "age_gate"
                return False, "age_gate"
            return True, None

        for t in ordered_candidates:
            if dispatch_policy == "react" and _task_stream(t) == "predictive":
                rejected_counts["policy_blocked_predictive"] += 1
                continue
            assignment = _select_assignment_algorithm(t)
            candidate_task = assignment.get("resolved_task") or t
            if _task_stream(candidate_task) == "predictive":
                candidate_task = _annotate_predictive_task_for_runtime(candidate_task)
            ttype = assignment["task_type"]
            is_model_det = bool(assignment["is_model_det"])
            assigned_primary = assignment["assigned_primary"]
            assigned_secondary = assignment["assigned_secondary"]
            if assigned_primary is None:
                _record_model_det_rejection("unassigned", candidate_task, assigned_primary, assigned_secondary)
                planner_rejected_unassigned += 1
                rejected_counts["unassigned"] += 1
                continue

            risk_gate_passed, risk_reject_reason = _risk_adjusted_predictive_admission_gate(
                candidate_task,
                assigned_primary,
            )
            if not risk_gate_passed:
                _record_model_det_rejection(risk_reject_reason or "risk_adjusted", candidate_task, assigned_primary, assigned_secondary)
                rejected_counts["policy_blocked_predictive"] += 1
                continue

            assigned_primary_busy = active_load.get(assigned_primary, 0) > 0

            if not _apply_patrol_lock_gating_algorithm(ttype, assigned_primary, now_t):
                continue

            gating = _evaluate_model_deterring_dispatch_gating_algorithm(
                candidate_task,
                assigned_primary,
                assigned_primary_busy,
                model_deterring_accepted_this_cycle,
                active_model_det_load,
                now_t,
            )
            budget_queue = gating["budget_queue"]
            budget_mode = gating["budget_mode"]
            t_utility = float(gating["task_utility"])
            if gating["reason"] is not None:
                _record_model_det_rejection(gating["reason"], candidate_task, assigned_primary, assigned_secondary)
                _apply_model_deterring_dispatch_rejection_accounting(gating["reason"])
                if gating["reason"] == "budget":
                    if budget_mode == "utility_per_hour":
                        model_deterring_rejected_budget_utility_mode += 1
                    else:
                        model_deterring_rejected_budget_count_mode += 1
                continue

            if active_load.get(assigned_primary, 0) >= int(max_active_tasks_per_robot):
                if (ttype == "patrolling") or is_model_det:
                    worst_patrol = _select_patrol_replacement_task(active_tasks, assigned_primary, candidate_task)
                    if worst_patrol is None:
                        _record_model_det_rejection("task_cap", candidate_task, assigned_primary, assigned_secondary)
                        planner_rejected_task_cap += 1
                        rejected_counts["task_cap"] += 1
                        continue
                    _evict_active_patrol_task(worst_patrol)
                    replaced_patrol_count += 1

            if ttype == "patrolling" and active_patrol_load.get(assigned_primary, 0) >= int(max_active_patrolling_per_robot):
                worst_patrol = _select_patrol_replacement_task(active_tasks, assigned_primary, candidate_task)
                if worst_patrol is None:
                    planner_rejected_patrol_cap += 1
                    rejected_counts["patrol_cap"] += 1
                    continue
                _evict_active_patrol_task(worst_patrol)
                replaced_patrol_count += 1

            if is_model_det:
                budget_queue.append((float(now_t), t_utility))
                model_deterring_by_robot[assigned_primary] = budget_queue
                model_deterring_admissions_by_robot[assigned_primary].append(float(now_t))
                model_deterring_accepted += 1
                accepted_origin = str(candidate_task.get("origin", "unknown")).strip().lower() or "unknown"
                model_deterring_accepted_by_source[accepted_origin] = int(
                    model_deterring_accepted_by_source.get(accepted_origin, 0) + 1
                )
                model_deterring_accepted_this_cycle += 1
                if assigned_primary_busy:
                    planner_accepted_model_det_busy_primary += 1
                else:
                    planner_accepted_model_det_idle_primary += 1
            elif ttype == "deterring":
                direct_deterring_arrivals_by_robot[assigned_primary].append(float(now_t))

            accepted_task = {
                "id": next_tid,
                **candidate_task,
                "assigned_primary": assigned_primary,
                "assigned_secondary": assigned_secondary,
                "state": "active",
                "started_hold": None,
                "t_assigned": float(now_t),
            }
            accepted_stream = _task_stream(accepted_task)
            if accepted_stream == "predictive":
                accepted_task = _annotate_predictive_task_for_runtime(accepted_task)
                assigned_eta_s = _finite_task_metric(
                    accepted_task,
                    "assigned_eta_s",
                    _assigned_robot_eta_seconds(
                        assigned_primary,
                        (float(candidate_task.get("x", 0.0)), float(candidate_task.get("y", 0.0))),
                    ),
                )
                accepted_task["assigned_eta_s"] = float(assigned_eta_s)
                predictive_deadline_slack_s = _predictive_deadline_slack_s(accepted_task)
                if math.isfinite(predictive_deadline_slack_s):
                    predictive_deadline_checked_total += 1
                    accepted_task["predictive_deadline_slack_s"] = float(
                        predictive_deadline_slack_s
                    )
                    if predictive_deadline_slack_s >= 0.0:
                        predictive_deadline_feasible_total += 1
                confidence = _finite_task_metric(accepted_task, "predictive_confidence", float("nan"))
                if math.isfinite(confidence):
                    predictive_confidence_sum += float(confidence)
                    predictive_confidence_sample_count += 1
                predictive_expected_deltaJ_total += max(
                    _finite_task_metric(accepted_task, "bernoulli_expected_deltaJ", 0.0),
                    0.0,
                )
                predictive_raw_deltaJ_total += max(
                    _finite_task_metric(accepted_task, "predictive_raw_deltaJ", 0.0),
                    0.0,
                )
            if is_model_det:
                accepted_task["persist_lock_until_t"] = _model_deterring_lock_until_t(accepted_task, now_t)
            active_tasks.append(accepted_task)
            accepted_tasks.append(dict(accepted_task))
            accepted_stream_counts[accepted_stream] = int(accepted_stream_counts.get(accepted_stream, 0) + 1)
            if accepted_stream == "reactive":
                reactive_admitted_total += 1
            else:
                predictive_admitted_total += 1
                opportunity_key = _predictive_opportunity_key(accepted_task)
                if opportunity_key:
                    predictive_distinct_admitted_keys.add(opportunity_key)
                zone_bonus_value = _zone_bonus_for_robot_task(assigned_primary, accepted_task)
                predictive_zone_bonus_sum += float(zone_bonus_value)
                predictive_zone_bonus_count += 1
                if zone_bonus_value <= 0.0:
                    cross_zone_assignment_total += 1
            member_keys = t.get("_member_task_keys")
            if isinstance(member_keys, list) and member_keys:
                for mk in member_keys:
                    try:
                        consumed_task_keys.add(tuple(mk))
                    except Exception:
                        pass
            consumed_task_keys.add(_task_buffer_key(t))
            active_load[assigned_primary] = active_load.get(assigned_primary, 0) + 1
            if ttype == "patrolling":
                active_patrol_load[assigned_primary] = active_patrol_load.get(assigned_primary, 0) + 1
            if is_model_det:
                active_model_det_load[assigned_primary] = active_model_det_load.get(assigned_primary, 0) + 1

            if mon is not None and getattr(mon, "enabled", False):
                mon.event_task("spawn", active_tasks[-1])
                if assigned_primary is not None:
                    mon.event_task("assign", active_tasks[-1])

            if assigned_primary and goal[assigned_primary] is None:
                goal[assigned_primary] = (candidate_task["x"], candidate_task["y"])
                if debug_movement:
                    print(
                        f"[goal] {assigned_primary} -> ({candidate_task['x']:.1f},{candidate_task['y']:.1f}) "
                        f"type={candidate_task['type']}"
                    )
            next_tid += 1

        risk_adjusted_diagnostics = _risk_adjusted_dispatch_diagnostics(
            risk_adjusted_gate_results,
            rho_eff=float(risk_adjusted_stage_rho_eff),
            reactive_pressure=float(risk_adjusted_stage_reactive_pressure),
            reactive_age_norm=float(risk_adjusted_stage_reactive_age_norm),
        )
        predictive_risk_adjusted_candidates_total += int(
            risk_adjusted_diagnostics["predictive_candidates"]
        )
        predictive_risk_adjusted_rejected_confidence_total += int(
            risk_adjusted_diagnostics["rejected_by_confidence"]
        )
        predictive_risk_adjusted_rejected_slack_total += int(
            risk_adjusted_diagnostics["rejected_by_slack"]
        )
        predictive_risk_adjusted_rejected_utility_total += int(
            risk_adjusted_diagnostics["rejected_by_utility"]
        )
        predictive_risk_adjusted_rejected_cost_ratio_total += int(
            risk_adjusted_diagnostics["rejected_by_cost_ratio"]
        )
        for gate in risk_adjusted_gate_results:
            predictive_risk_adjusted_confidence_sum += float(gate.get("confidence", 0.0))
            predictive_risk_adjusted_utility_sum += float(gate.get("utility", 0.0))
            predictive_risk_adjusted_candidate_sample_count += 1
        if risk_adjusted_gate_results:
            predictive_risk_adjusted_rho_eff_sum += float(risk_adjusted_diagnostics["rho_eff"])
            predictive_risk_adjusted_reactive_pressure_sum += float(
                risk_adjusted_diagnostics["reactive_pressure"]
            )
            predictive_risk_adjusted_reactive_age_norm_sum += float(
                risk_adjusted_diagnostics["reactive_age_norm"]
            )
            predictive_risk_adjusted_dispatch_sample_count += 1

        return DispatchStageResult(
            now_t=float(now_t),
            dispatch_policy=str(dispatch_policy),
            reservation_fraction=float(reservation_fraction),
            reservation_window_s=float(reservation_window_s),
            reactive_override_slack_s=float(reactive_override_slack_s),
            reservation_softening_alpha=float(reservation_softening_alpha),
            reservation_age_softening_beta=float(reservation_age_softening_beta),
            reservation_age_gate=float(reservation_age_gate),
            predictive_slack_min_s=float(predictive_slack_min_s),
            reactive_pressure_max_for_predictive=float(reactive_pressure_max_for_predictive),
            predictive_confidence_min=float(predictive_confidence_min),
            predictive_deadline_weight=float(predictive_deadline_weight),
            predictive_eta_penalty_weight=float(predictive_eta_penalty_weight),
            predictive_utility_mode=str(predictive_utility_mode),
            predictive_confidence_source=str(predictive_confidence_source),
            predictive_confidence_power=float(predictive_confidence_power),
            predictive_time_score_deadline_scale_s=float(predictive_time_score_deadline_scale_s),
            predictive_time_score_reactive_pressure_weight=float(predictive_time_score_reactive_pressure_weight),
            predictive_time_score_infeasible_penalty=float(predictive_time_score_infeasible_penalty),
            predictive_utility_min=float(predictive_utility_min),
            predictive_cost_ratio_min=float(predictive_cost_ratio_min),
            predictive_opportunity_cost_weight=float(predictive_opportunity_cost_weight),
            predictive_eta_cost_weight=float(predictive_eta_cost_weight),
            predictive_service_cost_weight=float(predictive_service_cost_weight),
            risk_adjusted_reservation_alpha=float(risk_adjusted_reservation_alpha),
            risk_adjusted_reservation_beta=float(risk_adjusted_reservation_beta),
            predictive_timing_mode=str(predictive_timing_mode),
            predictive_expiry_grace_s=float(predictive_expiry_grace_s),
            predictive_selection_policy=str(predictive_selection_policy),
            candidate_count=int(len(task_stage.candidate_tasks)),
            candidate_stream_counts=dict(candidate_stream_counts),
            accepted_tasks=accepted_tasks,
            accepted_stream_counts=dict(accepted_stream_counts),
            rejected_counts=rejected_counts,
            rejected_model_det_tasks=rejected_model_det_tasks,
            ordering_policy=str(ordering_policy),
            ordered_candidate_preview=ordered_candidate_preview,
            replaced_patrol_count=int(replaced_patrol_count),
            urgent_reactive_override_count=0,
            robot_predictive_share_snapshot=dict(robot_predictive_share_snapshot),
            active_load_after_dispatch=dict(active_load),
            active_patrol_load_after_dispatch=dict(active_patrol_load),
            active_model_det_load_after_dispatch=dict(active_model_det_load),
            model_deterring_accepted_total=int(model_deterring_accepted),
            model_deterring_rejected_budget_total=int(model_deterring_rejected_budget),
            risk_adjusted_diagnostics=dict(risk_adjusted_diagnostics),
        )

    def _spawn_and_assign_new_tasks(now_t, patrolling_only=False):
        """Run the explicit task-generation and dispatch stages."""
        nonlocal last_task_generation_structured, last_dispatch_structured
        last_task_generation_structured = _run_task_generation_stage(now_t, patrolling_only=patrolling_only)
        last_dispatch_structured = _run_dispatch_stage(now_t, last_task_generation_structured)

    # ------------------------------------------------------------------------
    # Local helper closures: motion projection and task lifecycle completion
    # ------------------------------------------------------------------------
    # Motion helpers (row-constrained movement with headland lane switching)
    def _row_bands():
        """Build vineyard row bands used by lane-projection motion planning."""
        if row_spacing_m <= 0:
            return []
        bands = []
        k = 0
        while True:
            y = headland_space_m + k * row_spacing_m
            if y - 0.5 * row_width_m > (H - headland_space_m):
                break
            bands.append((y - 0.5 * row_width_m, y + 0.5 * row_width_m))
            k += 1
        return bands

    row_bands = _row_bands()

    def _nearest_free_lane_y(y):
        """Find the nearest traversable row-lane center for a y coordinate."""
        if not row_bands:
            return float(y)
        # If already in a free band, keep that band center.
        prev = 0.0
        for (a, b) in row_bands:
            if prev <= y <= a:
                return 0.5 * (prev + a)
            prev = b
        if y >= prev:
            return 0.5 * (prev + H)
        # If inside a row, snap to nearest adjacent free band center.
        # Find nearest row band and pick closer free band.
        for i, (a, b) in enumerate(row_bands):
            if a <= y <= b:
                lower = 0.0 if i == 0 else row_bands[i-1][1]
                upper = row_bands[i+1][0] if i+1 < len(row_bands) else H
                lower_c = 0.5 * (lower + a)
                upper_c = 0.5 * (b + upper)
                return lower_c if abs(y - lower_c) <= abs(y - upper_c) else upper_c
        return float(y)

    def _lane_center_for(y):
        """Return the lane center associated with a y coordinate."""
        return _nearest_free_lane_y(y)

    def _is_at_headland(x):
        """Return whether an x coordinate lies in a vineyard headland."""
        return x <= (0.0 + headland_m) or x >= (W - headland_m)

    def _nearest_headland_x(x):
        """Return the nearest headland x coordinate for row transitions."""
        left = max(0.0, headland_space_m)
        right = min(float(W), W - headland_space_m)
        return left if x <= W * 0.5 else float(right)

    def _project_to_lane(rid, tgt):
        """Project a target point onto a traversable vineyard lane or headland route."""
        x, y = pose[rid]
        tx, ty = tgt
        cur_lane = _lane_center_for(y)
        tgt_lane = _lane_center_for(ty)
        # If already on target lane, just move along it.
        if abs(cur_lane - tgt_lane) <= lane_eps_m:
            return (tx, cur_lane)
        # If not at headland, go to nearest headland along current lane.
        if not _is_at_headland(x):
            hx = _nearest_headland_x(x)
            return (hx, cur_lane)
        # At headland: slide laterally to target lane first.
        if abs(y - tgt_lane) > lane_eps_m:
            hx = _nearest_headland_x(x)
            return (hx, tgt_lane)
        # Now at target lane on headland: proceed along lane to target x.
        return (tx, tgt_lane)

    def _move_directly_to_point(rid, tgt_xy, dt_local):
        """Move a robot toward a target point by the distance allowed this step."""
        x, y = pose[rid]
        tx, ty = float(tgt_xy[0]), float(tgt_xy[1])
        dx, dy = tx - x, ty - y
        dist = math.hypot(dx, dy)
        if dist < 1.0e-6:
            return
        speed = max(float(profiles[rid].speed_mps), 1.0e-6)
        step = speed * float(dt_local)
        nx, ny = (tx, ty) if step >= dist else (x + dx * (step / dist), y + dy * (step / dist))
        clamped_x = min(max(nx, 0.0), float(W))
        clamped_y = min(max(ny, 0.0), float(H))
        step_dist = math.hypot(clamped_x - x, clamped_y - y)
        travel_distance_by_robot[rid] += step_dist
        e_per_m = uav_energy_per_m if profiles[rid].type == "UAV" else ugv_energy_per_m
        energy_by_robot[rid] += step_dist * float(e_per_m)
        pose[rid] = (clamped_x, clamped_y)

    def _graph_goal_node_id(rid, tgt_xy, allowed_node_ids=None):
        """Return the graph node id closest to a robot goal point."""
        if not _graph_enabled_for_robot(rid):
            return None
        return snap_point_to_graph(
            graph_motion_graph,
            (float(tgt_xy[0]), float(tgt_xy[1])),
            anchor_snap_radius_m=float(graph_anchor_snap_radius_m),
            allowed_node_ids=allowed_node_ids,
        )

    def _graph_effective_goal(rid, tgt_xy):
        """Return the currently active graph waypoint for a robot goal."""
        goal_node_id = _graph_goal_node_id(rid, tgt_xy)
        if goal_node_id is None:
            return (float(tgt_xy[0]), float(tgt_xy[1]))
        return graph_motion_graph.node_point(goal_node_id)

    def _graph_sync_progress(rid):
        """Synchronize graph-route progress with the robot current pose."""
        if not _graph_enabled_for_robot(rid):
            return
        state = graph_motion_states[str(rid)]
        plan = state.plan
        if not plan.route_waypoints:
            return
        next_index = infer_active_waypoint_index(
            pose[str(rid)],
            plan,
            reach_tol_m=max(float(arrival_radius_m), 0.5 * float(graph_anchor_snap_radius_m)),
        )
        plan.active_waypoint_index = int(next_index)
        if next_index <= 0 and plan.route_node_ids:
            plan.current_node_id = None
        elif plan.route_node_ids:
            plan.current_node_id = str(plan.route_node_ids[min(next_index - 1, len(plan.route_node_ids) - 1)])
        if next_index < len(plan.route_node_ids):
            plan.next_node_id = str(plan.route_node_ids[next_index])
        else:
            plan.next_node_id = None
        if next_index >= len(plan.route_waypoints):
            plan.route_status = "complete" if not plan.blocked else "waiting"
        elif plan.blocked and plan.next_node_id is None:
            plan.route_status = "waiting"

    def _graph_plan_for_robot(rid, tgt_xy, now_t, reservations):
        """Plan or refresh a graph route for a robot assigned to a goal."""
        if not _graph_enabled_for_robot(rid):
            return None
        rid_s = str(rid)
        start_node_id = snap_point_to_graph(
            graph_motion_graph,
            (float(pose[rid_s][0]), float(pose[rid_s][1])),
            anchor_snap_radius_m=float(graph_anchor_snap_radius_m),
        )
        goal_node_id = _graph_goal_node_id(rid_s, tgt_xy)
        if goal_node_id is None:
            return None
        plan = graph_motion_graph.plan_route(
            start_node_id=str(start_node_id),
            goal_node_id=str(goal_node_id),
            start_time_s=float(now_t),
            speed_mps=max(float(profiles[rid_s].speed_mps), 1.0e-6),
            reservations=reservations,
            reservation_horizon_s=float(graph_reservation_horizon_s),
            max_detour_ratio=float(graph_max_detour_ratio),
            wait_retry_period_s=float(graph_wait_retry_period_s),
            node_hold_s=float(max(arrival_radius_m, 0.5 * graph_anchor_snap_radius_m)),
            ignore_robot_id=str(rid_s),
        )
        if plan.route_waypoints:
            start_point = plan.route_waypoints[0]
            if math.hypot(float(start_point[0]) - float(pose[rid_s][0]), float(start_point[1]) - float(pose[rid_s][1])) > float(arrival_radius_m):
                plan.active_waypoint_index = 0
                plan.current_node_id = None
                plan.next_node_id = str(plan.route_node_ids[0])
            elif len(plan.route_waypoints) > 1:
                plan.active_waypoint_index = max(int(plan.active_waypoint_index), 1)
                plan.current_node_id = str(plan.route_node_ids[0])
                plan.next_node_id = str(plan.route_node_ids[plan.active_waypoint_index])
        state = graph_motion_states[rid_s]
        state.goal_node_id = str(goal_node_id)
        state.goal_xy = (float(tgt_xy[0]), float(tgt_xy[1]))
        state.last_plan_t = float(now_t)
        state.plan = plan
        return plan

    def _graph_route_waypoint(rid):
        """Return the next waypoint a robot should follow on its graph route."""
        if not _graph_enabled_for_robot(rid):
            return None
        plan = graph_motion_states[str(rid)].plan
        if not plan.route_waypoints:
            return None
        index = int(plan.active_waypoint_index)
        if index < 0 or index >= len(plan.route_waypoints):
            return None
        return plan.route_waypoints[index]

    def _effective_goal(rid, tgt):
        """Return the immediate motion target after lane or graph projection."""
        if _graph_enabled_for_robot(rid):
            return _graph_effective_goal(rid, tgt)
        return _project_to_lane(rid, tgt)

    def _step_to(rid, tgt, dt):
        """Advance one robot pose toward its effective goal for this frame."""
        if _graph_enabled_for_robot(rid):
            waypoint = _graph_route_waypoint(rid)
            if waypoint is None:
                return
            _move_directly_to_point(rid, waypoint, dt)
            return
        _move_directly_to_point(rid, _project_to_lane(rid, tgt), dt)

    def _match_active_task_for_robot_goal(rid, tgt):
        """Find the active task whose goal currently drives a robot."""
        if tgt is None:
            return None
        tx_goal, ty_goal = _effective_goal(rid, tgt)
        for tr in active_tasks:
            if tr.get("assigned_primary") != rid or tr.get("state") != "active":
                continue
            tx_task, ty_task = _effective_goal(rid, (tr["x"], tr["y"]))
            if math.hypot(tx_task - tx_goal, ty_task - ty_goal) <= arrival_radius_m:
                return tr
        return None

    def _task_age_anchor_t(task_row):
        """Return the timestamp used for task age and persistence calculations."""
        t_assigned = task_row.get("t_assigned", None)
        if t_assigned is not None:
            try:
                return float(t_assigned)
            except Exception:
                pass
        return float(task_row.get("time", t))

    def _is_active_model_deterring(task_row):
        """Return whether a task is an active predictive model-scored deterrence action."""
        return (
            str(task_row.get("state", "")).strip().lower() == "active"
            and task_action_kind(task_row, deterring_modes, float(tau_service_s)) == "deterring"
            and _deterring_source(task_row) == "model_scored"
        )

    def _is_model_deterring_persist_locked(task_row, now_t):
        """Return whether a model-scored deterrence task is still protected by persistence rules."""
        if not bool(protect_active_model_deterring_persistence):
            return False
        if not _is_active_model_deterring(task_row):
            return False
        if task_row.get("started_hold") is not None:
            return True
        lock_until_t = task_row.get("persist_lock_until_t", None)
        if lock_until_t is not None:
            try:
                if float(now_t) < float(lock_until_t):
                    return True
            except Exception:
                pass
        age_s = float(now_t) - _task_age_anchor_t(task_row)
        if age_s < float(model_deterring_min_persistence_lifetime_s):
            return True
        if _is_model_deterring_arrival_imminent(task_row):
            return True
        rid = str(task_row.get("assigned_primary", ""))
        if rid in pose:
            tx, ty = _effective_goal(rid, (float(task_row.get("x", 0.0)), float(task_row.get("y", 0.0))))
            dist = math.hypot(float(pose[rid][0]) - tx, float(pose[rid][1]) - ty)
            if dist <= float(model_deterring_lock_near_goal_radius_m):
                return True
        return False

    def _has_locked_model_deterring_on_robot(rid, now_t):
        """Return whether a robot currently owns a locked model-scored deterrence task."""
        for tr in active_tasks:
            if str(tr.get("assigned_primary", "")) != str(rid):
                continue
            if _is_model_deterring_persist_locked(tr, now_t):
                return True
        return False

    def _assigned_robot_eta_seconds(rid, tgt_xy):
        """Estimate travel time for the robot currently assigned to a task."""
        if rid not in pose:
            return float("nan")
        if _graph_enabled_for_robot(rid):
            eta_s = _graph_eta_seconds(rid, tgt_xy)
            if math.isfinite(eta_s):
                return float(eta_s)
        tx, ty = _effective_goal(rid, tgt_xy)
        px, py = pose[rid]
        dist = math.hypot(float(tx) - float(px), float(ty) - float(py))
        speed = 1.0
        spin = 0.0
        spinup_lookup = {"UAV": 8.0, "UGV": 0.0}
        if profiles is not None and rid in profiles:
            prof = profiles[rid]
            speed = max(float(prof.speed_mps), 1e-6)
            spin = float(spinup_lookup.get(prof.type, 0.0))
        return float(dist / max(speed, 1e-6) + spin)

    def _is_model_deterring_arrival_imminent(task_row):
        """Return whether a model-scored deterrence task is close enough to preserve."""
        if motion_orchestration_mode != "local":
            return False
        if not _is_active_model_deterring(task_row):
            return False
        rid = str(task_row.get("assigned_primary", ""))
        if rid not in pose or rid not in profiles:
            return False
        tx, ty = _effective_goal(rid, (float(task_row.get("x", 0.0)), float(task_row.get("y", 0.0))))
        px, py = pose[rid]
        dist = math.hypot(float(px) - tx, float(py) - ty)
        step_reach_m = max(0.0, float(profiles[rid].speed_mps) * float(dt))
        eta_s = _assigned_robot_eta_seconds(
            rid,
            (float(task_row.get("x", 0.0)), float(task_row.get("y", 0.0))),
        )
        return (
            dist <= float(arrival_radius_m) + float(step_reach_m)
            or (math.isfinite(eta_s) and eta_s <= float(dt))
        )

    def _model_deterring_lock_until_t(task_row, now_t):
        """Compute the time until which a model-scored deterrence task remains locked."""
        rid = str(task_row.get("assigned_primary", ""))
        eta_s = _assigned_robot_eta_seconds(
            rid,
            (float(task_row.get("x", 0.0)), float(task_row.get("y", 0.0))),
        )
        if not math.isfinite(eta_s):
            eta_s = max(0.0, float(task_row.get("eta_s", 0.0)))
        service_time_s = task_action_service_time_s(
            task_row,
            deterring_modes=deterring_modes,
            default_service_time_s=float(tau_service_s),
        )
        lock_duration_s = max(
            float(model_deterring_min_persistence_lifetime_s),
            float(model_deterring_persistence_buffer_s)
            + float(service_time_s)
            + float(model_deterring_persistence_eta_multiplier) * eta_s,
        )
        lock_duration_s = min(lock_duration_s, float(model_deterring_max_persistence_lifetime_s))
        return float(now_t) + float(lock_duration_s)

    def _active_tasks_for_robot(rid):
        """Return active tasks assigned to a specific robot."""
        return [
            tr for tr in active_tasks
            if (
                str(tr.get("assigned_primary", "")) == str(rid)
                and str(tr.get("state", "")).strip().lower() == "active"
            )
        ]

    def _task_goal_xy(task_row):
        """Return the goal coordinates for a task row."""
        return (float(task_row.get("x", 0.0)), float(task_row.get("y", 0.0)))

    def _task_eta_seconds_for_robot(rid, task_row):
        """Estimate travel time from a robot to a task goal."""
        return _assigned_robot_eta_seconds(rid, _task_goal_xy(task_row))

    def _expire_infeasible_predictive_tasks(now_t):
        """Expire predictive tasks that can no longer meet their timing constraints."""
        nonlocal predictive_expired_total
        if not active_tasks:
            return 0
        expired_ids = set()
        expired_count = 0
        for task_row in list(active_tasks):
            if str(task_row.get("state", "")).strip().lower() != "active":
                continue
            if _task_stream(task_row) != "predictive":
                continue
            if task_row.get("started_hold") is not None:
                continue
            rid = str(task_row.get("assigned_primary", "")).strip()
            eta_s = None
            if rid:
                eta_candidate_s = _assigned_robot_eta_seconds(rid, _task_goal_xy(task_row))
                if math.isfinite(float(eta_candidate_s)):
                    eta_s = float(eta_candidate_s)
            if _predictive_task_has_expired(
                task_row,
                now_t=float(now_t),
                eta_s=eta_s,
                predictive_expiry_grace_s=float(predictive_expiry_grace_s),
            ):
                task_row.update(_annotate_predictive_task_for_runtime(task_row))
                expired_ids.add(task_row.get("id"))
                task_row["state"] = "expired"
                task_row["t_expired"] = float(now_t)
                task_row["predictive_deadline_slack_s"] = float(
                    _predictive_deadline_slack_with_eta_s(
                        task_row,
                        now_t=float(now_t),
                        eta_s_override=eta_s,
                    )
                )
                if rid and goal.get(rid) is not None:
                    gx, gy = goal[rid]
                    tx, ty = _task_goal_xy(task_row)
                    if math.hypot(float(tx) - float(gx), float(ty) - float(gy)) <= float(arrival_radius_m):
                        goal[rid] = None
                        if rid in graph_motion_states:
                            graph_motion_states[rid].clear()
                if mon is not None and getattr(mon, "enabled", False):
                    mon.event_task("expire", task_row)
                _record_predictive_success_label_task(task_row)
                expired_count += 1
        if expired_ids:
            active_tasks[:] = [tr for tr in active_tasks if tr.get("id") not in expired_ids]
            predictive_expired_total += int(expired_count)
        return int(expired_count)

    def _select_policy_task_for_robot(rid, now_t):
        """Select the best dispatch candidate for one robot under the active policy."""
        assigned_tasks = _active_tasks_for_robot(rid)
        if not assigned_tasks:
            return None, False
        robot_is_idle = bool(goal.get(rid) is None) and float(loiter_until.get(rid, 0.0)) <= float(now_t)
        return _select_dispatch_policy_task(
            assigned_tasks,
            dispatch_policy=str(dispatch_policy),
            predictive_share=float(robots[rid].predictive_share(now_t)),
            reservation_fraction=float(reservation_fraction),
            reactive_override_slack_s=float(reactive_override_slack_s),
            reservation_softening_alpha=float(reservation_softening_alpha),
            reservation_age_softening_beta=float(reservation_age_softening_beta),
            reservation_age_gate=float(reservation_age_gate),
            predictive_selection_policy=str(predictive_selection_policy),
            now_t=float(now_t),
            eta_seconds_fn=lambda task_row: _task_eta_seconds_for_robot(rid, task_row),
            rng=rng,
            predictive_slack_min_s=float(predictive_slack_min_s),
            reactive_pressure_max_for_predictive=float(reactive_pressure_max_for_predictive),
            predictive_confidence_min=float(predictive_confidence_min),
            predictive_deadline_weight=float(predictive_deadline_weight),
            predictive_eta_penalty_weight=float(predictive_eta_penalty_weight),
            predictive_utility_mode=str(predictive_utility_mode),
            predictive_confidence_source=str(predictive_confidence_source),
            predictive_confidence_power=float(predictive_confidence_power),
            predictive_time_score_deadline_scale_s=float(predictive_time_score_deadline_scale_s),
            predictive_time_score_reactive_pressure_weight=float(predictive_time_score_reactive_pressure_weight),
            predictive_time_score_infeasible_penalty=float(predictive_time_score_infeasible_penalty),
            predictive_utility_min=float(predictive_utility_min),
            predictive_cost_ratio_min=float(predictive_cost_ratio_min),
            predictive_opportunity_cost_weight=float(predictive_opportunity_cost_weight),
            predictive_eta_cost_weight=float(predictive_eta_cost_weight),
            predictive_service_cost_weight=float(predictive_service_cost_weight),
            risk_adjusted_reservation_alpha=float(risk_adjusted_reservation_alpha),
            risk_adjusted_reservation_beta=float(risk_adjusted_reservation_beta),
            robot_is_idle=bool(robot_is_idle),
        )

    def _start_deterring_hold(rid, task_row, now_t):
        """Start the service hold interval for a deterring task."""
        task_row["started_hold"] = float(now_t)
        loiter_until[rid] = float(now_t) + float(
            task_action_service_time_s(
                task_row,
                deterring_modes=deterring_modes,
                default_service_time_s=float(tau_service_s),
            )
        )

    def _complete_deterring_task(rid, task_row, now_t):
        """Complete a deterring task, update habituation, and append its truth-suppression event."""
        nonlocal direct_detection_task_response_matches, reactive_completed_total, predictive_completed_total
        nonlocal predictive_distinct_completed_keys
        nonlocal predictive_confidence_completed_sum, predictive_confidence_completed_count
        task_row["state"] = "done"
        task_row["t_done"] = float(now_t)
        if _task_stream(task_row) == "predictive":
            task_row.update(_annotate_predictive_task_for_runtime(task_row))
        completed_tasks.append(task_row)
        t_assigned = float(task_row.get("t_assigned", task_row.get("time", now_t)))
        service_duration_s = max(0.0, float(now_t) - t_assigned)
        service_history_by_robot[rid].append((float(now_t), service_duration_s))
        stream_key = _task_stream(task_row)
        if stream_key == "reactive":
            reactive_service_history_by_robot[rid].append((float(now_t), service_duration_s))
            reactive_completed_total += 1
        else:
            predictive_completed_total += 1
            confidence = _finite_task_metric(task_row, "predictive_confidence", float("nan"))
            if math.isfinite(confidence):
                predictive_confidence_completed_sum += float(confidence)
                predictive_confidence_completed_count += 1
            opportunity_key = _predictive_opportunity_key(task_row)
            if opportunity_key:
                predictive_distinct_completed_keys.add(opportunity_key)
            _record_predictive_success_label_task(task_row)
        completed_count_by_type["deterring"] += 1
        completed_task_scores.append(float(task_row.get("score", 0.0)))
        action_spec = task_action(
            task_row,
            deterring_modes=deterring_modes,
            default_service_time_s=float(tau_service_s),
        )
        mode_label, beta_u, sigma_u, omega_u = _resolve_truth_deterrence_event_params(
            action_spec,
            use_mode_dependent_truth_suppression=bool(use_mode_dependent_truth_suppression),
            beta_true=float(beta_true),
            sigma_true=float(sigma_true),
            omega_true=float(omega_true),
        )
        params = dict(action_spec.params)

        eta_at_apply = 1.0
        cell_id = _cell_id_for_xy(task_row["x"], task_row["y"])
        habituation_mode_label = _habituation_mode_label(mode_label)
        mode_idx = _mode_id_for_label(habituation_mode_label)

        if bool(enable_habituation) and cell_id is not None and mode_idx is not None:
            eta_at_apply = hab.effectiveness(cell_id, mode_idx)
            hab.apply(cell_id, mode_idx)
        if cell_id is not None:
            last_service_t_by_cell[int(cell_id)] = float(now_t)
            if mode_idx is not None:
                eta_at_apply_samples.append(float(eta_at_apply))
                mode_counts = mode_use_by_cell.setdefault(int(cell_id), {})
                mode_counts[int(mode_idx)] = int(mode_counts.get(int(mode_idx), 0)) + 1

        action_id = int(task_row.get("id", -1))
        recent_deterrences.append({
            "x": float(task_row["x"]),
            "y": float(task_row["y"]),
            "t": float(now_t),
            "mode": mode_label,
            "source": _deterring_source(task_row),
            "action_id": action_id,
            "beta": beta_u,
            "sigma": sigma_u,
            "omega": omega_u,
            "eta": eta_at_apply,
            "habituation_mode": habituation_mode_label
        })
        feedback_beta = float(params.get("beta", 1.0))
        feedback_omega = float(params.get("omega", robots[rid].m.omega_inhib)) * float(model_feedback_omega_scale)
        feedback_sigma = float(params.get("sigma", robots[rid].m.sigma)) * float(model_feedback_sigma_scale)
        if enable_intervention_feedback:
            nonlocal step_intervention_feedback_applied
            step_intervention_feedback_applied += 1
            if centralized_predictive_topology_enabled and global_predictive_model is not None:
                global_predictive_model.advance_time(float(now_t) - float(global_predictive_model.t_now))
                global_predictive_model.add_intervention_event(
                    task_row["x"],
                    task_row["y"],
                    weight=feedback_beta,
                    sigma=feedback_sigma,
                    omega_inhib=feedback_omega,
                    mode=mode_label,
                )
            robots[rid].ingest_intervention_event(
                task_row["x"],
                task_row["y"],
                now_t,
                weight=feedback_beta,
                sigma=feedback_sigma,
                omega_inhib=feedback_omega,
                mode=mode_label,
                beta=feedback_beta,
                action_id=action_id,
            )
            b = robots[rid].intervention_boundary_events(
                task_row["x"],
                task_row["y"],
                now_t,
                weight=feedback_beta,
                mode=mode_label,
                sigma=feedback_sigma,
                omega_inhib=feedback_omega,
                beta=feedback_beta,
                action_id=action_id,
            )
            bus.send_intervention_events(
                b,
                source_id=rid,
                min_interval_s=float(intervention_boundary_min_interval_s),
                spatial_quant_m=float(intervention_boundary_spatial_quant_m),
                min_weight=float(intervention_boundary_min_weight),
            )
        matched_count = 0
        if _is_direct_detection_task(task_row) and bool(enable_direct_detection_task_clustering):
            cluster_t0 = float(task_row.get("time", now_t))
            cluster_t1 = float(task_row.get("last_detection_t", cluster_t0))
            match_radius = max(
                float(response_match_radius_m),
                float(direct_detection_active_refresh_radius_m),
                float(direct_detection_queued_cluster_radius_m),
            )
            for i, ev in enumerate(pending_event_onsets):
                if ev["responded"] or ev["t"] > now_t:
                    continue
                if float(ev["t"]) < cluster_t0 or float(ev["t"]) > cluster_t1:
                    continue
                d_ev = math.hypot(float(task_row["x"]) - float(ev["x"]), float(task_row["y"]) - float(ev["y"]))
                if d_ev <= match_radius:
                    pending_event_onsets[i]["responded"] = True
                    latency_s = float(now_t - ev["t"])
                    response_times.append(latency_s)
                    if _is_direct_detection_task(task_row):
                        reactive_response_times.append(latency_s)
                    matched_count += 1
        if matched_count <= 0:
            best_idx = None
            best_dist = float("inf")
            for i, ev in enumerate(pending_event_onsets):
                if ev["responded"] or ev["t"] > now_t:
                    continue
                d_ev = math.hypot(task_row["x"] - ev["x"], task_row["y"] - ev["y"])
                if d_ev <= response_match_radius_m and d_ev < best_dist:
                    best_dist = d_ev
                    best_idx = i
            if best_idx is not None:
                ev = pending_event_onsets[best_idx]
                pending_event_onsets[best_idx]["responded"] = True
                latency_s = float(now_t - ev["t"])
                response_times.append(latency_s)
                if _is_direct_detection_task(task_row):
                    reactive_response_times.append(latency_s)
                matched_count = 1
        direct_detection_task_response_matches += int(matched_count)
        if mon is not None and getattr(mon, "enabled", False):
            mon.event_task("complete", task_row)
        active_tasks[:] = [x for x in active_tasks if x["id"] != task_row["id"]]
        goal[rid] = None
        if rid in graph_motion_states:
            graph_motion_states[rid].clear()
        loiter_until[rid] = -1.0

    def _complete_patrolling_task(rid, task_row, now_t):
        """Complete a patrol task and record its service metrics."""
        nonlocal predictive_completed_total, predictive_distinct_completed_keys
        nonlocal predictive_confidence_completed_sum, predictive_confidence_completed_count
        task_row["state"] = "done"
        task_row["t_done"] = float(now_t)
        task_row.update(_annotate_predictive_task_for_runtime(task_row))
        completed_tasks.append(task_row)
        t_assigned = float(task_row.get("t_assigned", task_row.get("time", now_t)))
        service_history_by_robot[rid].append((float(now_t), max(0.0, float(now_t) - t_assigned)))
        completed_count_by_type["patrolling"] += 1
        predictive_completed_total += 1
        confidence = _finite_task_metric(task_row, "predictive_confidence", float("nan"))
        if math.isfinite(confidence):
            predictive_confidence_completed_sum += float(confidence)
            predictive_confidence_completed_count += 1
        opportunity_key = _predictive_opportunity_key(task_row)
        if opportunity_key:
            predictive_distinct_completed_keys.add(opportunity_key)
        _record_predictive_success_label_task(task_row)
        completed_task_scores.append(float(task_row.get("score", 0.0)))
        if mon is not None and getattr(mon, "enabled", False):
            mon.event_task("complete", task_row)
        active_tasks[:] = [x for x in active_tasks if x["id"] != task_row["id"]]
        goal[rid] = None
        if rid in graph_motion_states:
            graph_motion_states[rid].clear()

    def _process_near_goal_model_deterring_before_replan(now_t):
        """Complete imminent model-scored deterrence work before replanning can preempt it."""
        if motion_orchestration_mode != "local":
            return 0
        protected_count = 0
        for rid in pose:
            for tr in list(active_tasks):
                if not _is_active_model_deterring(tr):
                    continue
                if str(tr.get("assigned_primary", "")) != str(rid):
                    continue
                tx, ty = _effective_goal(rid, (float(tr.get("x", 0.0)), float(tr.get("y", 0.0))))
                dist = math.hypot(float(pose[rid][0]) - tx, float(pose[rid][1]) - ty)
                if dist > float(arrival_radius_m):
                    continue
                protected_count += 1
                if tr.get("started_hold") is None:
                    _start_deterring_hold(rid, tr, now_t)
                    if goal[rid] is None:
                        goal[rid] = (float(tr.get("x", tx)), float(tr.get("y", ty)))
                elif float(now_t) >= float(tr["started_hold"]) + float(
                    task_action_service_time_s(
                        tr,
                        deterring_modes=deterring_modes,
                        default_service_time_s=float(tau_service_s),
                    )
                ):
                    _complete_deterring_task(rid, tr, now_t)
                break
        return int(protected_count)

    # ------------------------------------------------------------------------
    # Simulation clocking, warmup, and end-of-run summaries
    # ------------------------------------------------------------------------
    # Sim clocks / cadence
    warmup_s = max(0.0, float(warmup_s))
    t_start = 0.0
    if warmup_s > 0.0 and use_ground_truth:
        # Burn in the ground-truth process to seed robot models before active tasking.
        t_w = 0.0
        while t_w < warmup_s:
            if w_shape is not None:
                area = float(W * H)
                w_mean = float(np.mean(w_shape[4]))
                lam_base = mu_true * w_mean * area
                n0 = rng.poisson(max(lam_base * dt, 0.0))
                for _ in range(int(n0)):
                    x, y = _sample_from_value_map(rng)
                    p_keep, p_suppress, p_by_mode, p_by_source = _suppression_eval(x, y, t_w)
                    truth_candidate_events += 1
                    suppression_effect_sum += float(p_suppress)
                    for mk, mv in p_by_mode.items():
                        suppression_effect_by_mode[mk] = float(suppression_effect_by_mode.get(mk, 0.0) + mv)
                    for sk, sv in p_by_source.items():
                        suppression_effect_by_source[sk] = float(suppression_effect_by_source.get(sk, 0.0) + sv)
                    if rng.random() <= p_keep:
                        truth_accepted_events += 1
                        _record_truth_window_event(t_w, False)
                        _process_truth_event(x, y, t_w, enqueue_tasks=False, record_metrics=False)
                        _spawn_offspring(x, y, t_w)
                    else:
                        truth_suppressed_events += 1
                        _record_truth_window_event(t_w, True)

                truth_queue.sort(key=lambda z: z[2])
                due = []
                while truth_queue and truth_queue[0][2] <= (t_w + dt):
                    due.append(truth_queue.pop(0))
                for (x, y, te) in due:
                    p_keep, p_suppress, p_by_mode, p_by_source = _suppression_eval(x, y, te)
                    truth_candidate_events += 1
                    suppression_effect_sum += float(p_suppress)
                    for mk, mv in p_by_mode.items():
                        suppression_effect_by_mode[mk] = float(suppression_effect_by_mode.get(mk, 0.0) + mv)
                    for sk, sv in p_by_source.items():
                        suppression_effect_by_source[sk] = float(suppression_effect_by_source.get(sk, 0.0) + sv)
                    if rng.random() <= p_keep:
                        truth_accepted_events += 1
                        _record_truth_window_event(te, False)
                        _process_truth_event(x, y, te, enqueue_tasks=False, record_metrics=False)
                        _spawn_offspring(x, y, te)
                    else:
                        truth_suppressed_events += 1
                        _record_truth_window_event(te, True)
            t_w += dt

        # Reset public-facing/metrics buffers so the scored run starts clean at t=0.
        truth_events.clear()
        truth_event_times.clear()
        recent_truth.clear()
        recent_detections.clear()
        pending_event_onsets.clear()
        response_times.clear()
        value_weighted_exposure = 0.0
        truth_candidate_events = 0
        truth_accepted_events = 0
        truth_suppressed_events = 0
        truth_detection_opportunities = 0
        truth_detections_observed = 0
        truth_detections_missed_range = 0
        truth_detections_missed_false_negative = 0
        truth_candidate_event_times_last_hour.clear()
        truth_suppressed_event_times_last_hour.clear()
        truth_candidate_event_times_load.clear()
        truth_suppressed_event_times_load.clear()
        truth_accepted_event_times_load.clear()
        truth_detection_opportunity_times_load.clear()
        truth_detection_in_range_times_load.clear()
        truth_detection_observed_times_load.clear()
        suppression_effect_sum = 0.0
        suppression_effect_by_mode.clear()
        suppression_effect_by_source = {"direct_detection": 0.0, "model_scored": 0.0}
        t_start = warmup_s

    t = t_start
    t_report_offset = t_start
    t_end = t_start + float(T_end)
    last_replan = -1e9

    def _task_intensity_score(tr):
        """Estimate local forecast intensity at a task location."""
        x = tr.get("x", float("nan"))
        y = tr.get("y", float("nan"))
        if not np.isfinite(x) or not np.isfinite(y):
            return float("-inf")
        rid = tr.get("robot_id")
        if rid not in robots:
            return 0.0
        rob = robots[rid]
        iy, ix = rob.m.world_to_idx(float(x), float(y))
        return float(rob.m.lam[iy, ix] - rob.m.mu[iy, ix])

    deterring_quality_cache = {
        "deterring_actions_completed_total": 0,
        "deterring_actions_completed_direct_detection": 0,
        "deterring_actions_completed_model_scored": 0,
        "deterring_action_precision": float("nan"),
        "deterring_action_precision_direct_detection": float("nan"),
        "deterring_action_precision_model_scored": float("nan"),
        "suppression_per_deterring_action": float("nan"),
        "suppression_per_direct_deterring_action": float("nan"),
        "suppression_per_model_deterring_action": float("nan"),
        "model_vs_direct_suppression_yield_ratio": float("nan"),
    }

    def _compute_deterring_quality():
        """Compute field, support, and persistence quality for a deterring task."""
        out = dict(deterring_quality_cache)
        det_done = [
            tr
            for tr in completed_tasks
            if task_action_kind(tr, deterring_modes, float(tau_service_s)) == "deterring"
        ]
        if not det_done:
            return out

        def _safe_div(a, b):
            """Divide two values while returning NaN when the denominator is not usable."""
            return float(a) / float(b) if float(b) > 0 else float("nan")

        total = len(det_done)
        by_source = {"direct_detection": [], "model_scored": []}
        for tr in det_done:
            by_source[_deterring_source(tr)].append(tr)

        # Precision: a deterring action is a "hit" if at least one truth event appears
        # near its location shortly after completion.
        ts_sorted = sorted(
            [(float(tt), float(xx), float(yy)) for ((xx, yy, tt)) in truth_events],
            key=lambda z: z[0],
        )
        times = [tt for (tt, _x, _y) in ts_sorted]
        r2 = float(deterring_eval_radius_m) ** 2
        w = float(deterring_eval_window_s)

        hit_total = 0
        hit_src = {"direct_detection": 0, "model_scored": 0}
        for tr in det_done:
            t_done = float(tr.get("t_done", tr.get("time", 0.0)))
            i0 = bisect.bisect_left(times, t_done)
            i1 = bisect.bisect_right(times, t_done + w)
            tx = float(tr.get("x", 0.0)); ty = float(tr.get("y", 0.0))
            hit = False
            for i in range(i0, i1):
                _tt, ex, ey = ts_sorted[i]
                if ((ex - tx) ** 2 + (ey - ty) ** 2) <= r2:
                    hit = True
                    break
            if hit:
                hit_total += 1
                hit_src[_deterring_source(tr)] += 1

        sup_total = float(suppression_effect_sum)
        sup_by_source = {
            "direct_detection": float(suppression_effect_by_source.get("direct_detection", 0.0)),
            "model_scored": float(suppression_effect_by_source.get("model_scored", 0.0)),
        }
        y_direct = _safe_div(sup_by_source["direct_detection"], len(by_source["direct_detection"]))
        y_model = _safe_div(sup_by_source["model_scored"], len(by_source["model_scored"]))

        out.update({
            "deterring_actions_completed_total": int(total),
            "deterring_actions_completed_direct_detection": int(len(by_source["direct_detection"])),
            "deterring_actions_completed_model_scored": int(len(by_source["model_scored"])),
            "deterring_action_precision": _safe_div(hit_total, total),
            "deterring_action_precision_direct_detection": _safe_div(hit_src["direct_detection"], len(by_source["direct_detection"])),
            "deterring_action_precision_model_scored": _safe_div(hit_src["model_scored"], len(by_source["model_scored"])),
            "suppression_per_deterring_action": _safe_div(sup_total, total),
            "suppression_per_direct_deterring_action": y_direct,
            "suppression_per_model_deterring_action": y_model,
            "model_vs_direct_suppression_yield_ratio": (y_model / y_direct) if (np.isfinite(y_model) and np.isfinite(y_direct) and y_direct > 0) else float("nan"),
        })
        return out

    # ------------------------------------------------------------------------
    # Main simulation loop
    # ------------------------------------------------------------------------
    while t <= t_end:
        step_pose_before = {rid: tuple(pose[rid]) for rid in pose}
        step_motion_feedback = apply_external_motion_feedback(
            now_t=t,
            dt=dt,
            motion_orchestration_mode=motion_orchestration_mode,
            motion_state_callback=motion_state_callback,
            pose=pose,
            goal=goal,
            active_tasks=active_tasks,
            W=W,
            H=H,
        )
        if graph_motion_graph is not None:
            for robot_id, route_info in (step_motion_feedback.route_progress_by_robot or {}).items():
                if robot_id not in graph_motion_states:
                    continue
                plan = graph_motion_states[robot_id].plan
                if route_info.get("active_waypoint_index") is not None:
                    plan.active_waypoint_index = max(0, int(route_info["active_waypoint_index"]))
                if route_info.get("route_status") is not None:
                    plan.route_status = str(route_info["route_status"])
                if route_info.get("blocked") is not None:
                    plan.blocked = bool(route_info["blocked"])
                if route_info.get("wait_reason") is not None:
                    plan.wait_reason = str(route_info["wait_reason"])
                _graph_sync_progress(robot_id)
            for robot_id in graph_motion_states:
                _graph_sync_progress(robot_id)
        step_completed_before = int(len(completed_tasks))
        step_recent_deterrences_before = int(len(recent_deterrences))
        step_recent_truth_before = int(len(recent_truth))
        step_recent_detections_before = int(len(recent_detections))
        step_truth_candidate_before = int(truth_candidate_events)
        step_truth_accepted_before = int(truth_accepted_events)
        step_truth_suppressed_before = int(truth_suppressed_events)
        step_suppression_effect_before = float(suppression_effect_sum)
        step_stale_goal_clears_before = int(stale_goal_clears)
        step_boundary_msg_before = int(bus.boundary_msg_count)
        step_intervention_msg_before = int(bus.intervention_msg_count)
        step_boundary_bytes_before = int(bus.boundary_bytes)
        step_intervention_bytes_before = int(bus.intervention_bytes)
        step_drop_debounce_before = int(bus.intervention_msg_dropped_debounce)
        step_drop_low_weight_before = int(bus.intervention_msg_dropped_low_weight)
        step_intervention_feedback_applied = 0

        # --------------------------------------------------------------------
        # Stage 1: Optional trigger-only repartition on health threshold
        # --------------------------------------------------------------------
        _run_zone_partitioning_algorithm(t)

        # --------------------------------------------------------------------
        # Stage 2: Ground-truth event generation or legacy local detections
        # --------------------------------------------------------------------
        truth_step = _run_truth_generation_algorithm(t)
        _expire_infeasible_predictive_tasks(t)

        # --------------------------------------------------------------------
        # Stage 3: Periodic planning, task generation, and dispatch
        # --------------------------------------------------------------------
        if (t - last_replan) >= task_replan_period_s:
            _process_near_goal_model_deterring_before_replan(t)
            # Drop patrolling tasks that are close to recent deterrences.
            # Keep active deterring tasks so dispatched actions can complete.
            if recent_deterrences:
                active_tasks[:] = [
                    tr for tr in active_tasks
                    if (
                        task_action_kind(tr, deterring_modes, float(tau_service_s)) == "deterring"
                        or not any(
                            (float(ev.get("t", -1e9)) >= t - deterring_suppress_window_s) and
                            ((tr["x"] - float(ev.get("x", 0.0)))**2 + (tr["y"] - float(ev.get("y", 0.0)))**2 <= deterring_suppress_radius_m**2)
                            for ev in recent_deterrences
                        )
                    )
                ]
            # Prune tasks that are stale or no longer supported by intensity
            active_tasks[:] = [
                tr for tr in active_tasks
                if (
                    _is_model_deterring_persist_locked(tr, t)
                    or (t - _task_age_anchor_t(tr) <= task_max_age_s)
                ) and
                   (
                       task_action_kind(tr, deterring_modes, float(tau_service_s)) != "patrolling"
                       or (_task_intensity_score(tr) >= task_refresh_min_score)
                   )
            ]
            _spawn_and_assign_new_tasks(now_t=t, patrolling_only=False)
            last_replan = t

        # --------------------------------------------------------------------
        # Stage 4: Motion execution and task completion checks
        # --------------------------------------------------------------------
        motion_commands = []
        current_task_by_robot = {}
        step_urgent_reactive_override_count = 0
        graph_reservations_step = GraphReservationTable()
        for r in robots_def:
            rid = r['id']
            command_source = "holding"
            command_type = "hold"
            graph_plan_for_command = (graph_motion_states[str(rid)].plan if str(rid) in graph_motion_states else None)
            # If holding at a deterring site, keep holding
            if loiter_until[rid] > t:
                pass
            else:
                command_source = "existing_goal" if goal[rid] is not None else "idle"
                command_type = "move" if goal[rid] is not None else "idle"
                assigned_candidates = []
                if dispatch_policy == "unc":
                    if preempt_deterring_goals:
                        # If an active deterring task exists for this robot, prioritize it over patrol goals.
                        det_candidates = [
                            tr for tr in active_tasks
                            if (
                                tr.get("assigned_primary") == rid
                                and str(tr.get("state", "")).strip().lower() == "active"
                                and task_action_kind(tr, deterring_modes, float(tau_service_s)) == "deterring"
                                and (
                                    (
                                        _deterring_source(tr) == "direct_detection"
                                        and bool(preempt_direct_detection_goals)
                                    )
                                    or (
                                        _deterring_source(tr) == "model_scored"
                                        and (
                                            bool(preempt_model_scored_goals)
                                            or (
                                                bool(protect_active_model_deterring_goal_preemption)
                                                and _is_model_deterring_persist_locked(tr, t)
                                            )
                                        )
                                    )
                                )
                            )
                        ]
                        if det_candidates:
                            px, py = pose[rid]
                            best_det = min(
                                det_candidates,
                                key=lambda tr: _assigned_robot_eta_seconds(
                                    rid,
                                    (float(tr.get("x", px)), float(tr.get("y", py))),
                                ),
                            )
                            det_goal = (float(best_det.get("x", px)), float(best_det.get("y", py)))
                            cur_is_det_goal = False
                            if goal[rid] is not None:
                                gx, gy = goal[rid]
                                for tr in det_candidates:
                                    if math.hypot(float(tr.get("x", 0.0)) - gx, float(tr.get("y", 0.0)) - gy) <= arrival_radius_m:
                                        cur_is_det_goal = True
                                        break
                            if (goal[rid] is None) or (not cur_is_det_goal):
                                goal[rid] = det_goal
                            command_source = "deterring_preempt"
                            command_type = "move"
                    if goal[rid] is None:
                        assigned_candidates = [tr for tr in active_tasks if tr["assigned_primary"] == rid and tr["state"] == "active"]
                        if assigned_candidates:
                            px, py = pose[rid]
                            _tid, gx, gy = min(
                                ((tr["id"], tr["x"], tr["y"]) for tr in assigned_candidates),
                                key=lambda z: _assigned_robot_eta_seconds(rid, (float(z[1]), float(z[2]))),
                            )
                            goal[rid] = (gx, gy)
                            command_source = "assigned_task"
                            command_type = "move"
                else:
                    current_goal_task = _match_active_task_for_robot_goal(rid, goal[rid])
                    policy_task = None
                    urgent_override = False
                    if preempt_deterring_goals or goal[rid] is None:
                        policy_task, urgent_override = _select_policy_task_for_robot(rid, t)
                    if urgent_override and policy_task is not None:
                        current_task_id = None if current_goal_task is None else current_goal_task.get("id")
                        if current_task_id != policy_task.get("id"):
                            goal[rid] = _task_goal_xy(policy_task)
                            step_urgent_reactive_override_count += 1
                        command_source = "reactive_override"
                        command_type = "move"
                    elif goal[rid] is None and policy_task is not None:
                        goal[rid] = _task_goal_xy(policy_task)
                        command_source = "policy_task"
                        command_type = "move"

                if goal[rid] is None:
                    if idle_roam_enabled and (t >= next_idle_retarget[rid]):
                        # No assigned work: keep robot moving with a local roam goal.
                        px, py = pose[rid]
                        if _graph_enabled_for_robot(rid):
                            allowed_node_ids = graph_motion_graph.nodes_in_polygon(
                                robots[rid].zone_polygon,
                                point_in_polygon_fn=point_in_polygon,
                            )
                            if allowed_node_ids:
                                target_node_id = max(
                                    allowed_node_ids,
                                    key=lambda node_id: math.hypot(
                                        float(graph_motion_graph.nodes[node_id].x) - float(px),
                                        float(graph_motion_graph.nodes[node_id].y) - float(py),
                                    ) + 0.05 * float(rng.random()),
                                )
                                gx, gy = graph_motion_graph.node_point(target_node_id)
                            else:
                                gx, gy = px, py
                        else:
                            gx = float(np.clip(px + rng.normal(0.0, idle_roam_jitter_m), 0.0, W))
                            gy = float(np.clip(py + rng.normal(0.0, idle_roam_jitter_m), 0.0, H))
                            zpoly = robots[rid].zone_polygon
                            if zpoly:
                                if not point_in_polygon(gx, gy, zpoly):
                                    # Try sampling a point inside zone bounds.
                                    xs = [p[0] for p in zpoly]
                                    ys = [p[1] for p in zpoly]
                                    xmin, xmax = min(xs), max(xs)
                                    ymin, ymax = min(ys), max(ys)
                                    found = False
                                    for _ in range(30):
                                        tx = float(rng.uniform(xmin, xmax))
                                        ty = float(rng.uniform(ymin, ymax))
                                        if point_in_polygon(tx, ty, zpoly):
                                            gx, gy = tx, ty
                                            found = True
                                            break
                                    if not found:
                                        gx = float(sum(xs) / max(len(xs), 1))
                                        gy = float(sum(ys) / max(len(ys), 1))
                        goal[rid] = (gx, gy)
                        next_idle_retarget[rid] = t + float(idle_roam_interval_s)
                        command_source = "idle_roam"
                        command_type = "move"
                # step
                command_pose = tuple(pose[rid])
                graph_plan_for_command = None
                if goal[rid] is None and rid in graph_motion_states:
                    graph_motion_states[rid].clear()
                    graph_plan_for_command = graph_motion_states[rid].plan
                if goal[rid] is not None and _graph_enabled_for_robot(rid):
                    state = graph_motion_states[str(rid)]
                    target_node_id = _graph_goal_node_id(rid, goal[rid])
                    goal_changed = (
                        state.goal_node_id != target_node_id
                        or state.goal_xy != (float(goal[rid][0]), float(goal[rid][1]))
                    )
                    plan_finished = (
                        bool(state.plan.route_waypoints)
                        and int(state.plan.active_waypoint_index) >= len(state.plan.route_waypoints)
                    )
                    replan_needed = (
                        goal_changed
                        or state.plan.blocked
                        or (not state.plan.route_waypoints)
                        or plan_finished
                        or ((float(t) - float(state.last_plan_t)) >= float(graph_replan_period_s))
                    )
                    graph_plan_for_command = (
                        _graph_plan_for_robot(rid, goal[rid], t, graph_reservations_step)
                        if replan_needed
                        else state.plan
                    )
                    if graph_plan_for_command is not None:
                        graph_reservations_step.reserve_plan(
                            robot_id=str(rid),
                            plan=graph_plan_for_command,
                            node_hold_s=float(max(arrival_radius_m, 0.5 * graph_anchor_snap_radius_m)),
                            final_hold_s=float(max(graph_wait_retry_period_s, tau_service_s)),
                        )
                        if graph_plan_for_command.blocked:
                            command_source = "graph_wait"
                            command_type = "hold" if graph_plan_for_command.next_node_id is None else "move"
                    if motion_orchestration_mode == "local":
                        _step_to(rid, goal[rid], dt)
                        _graph_sync_progress(rid)
                elif goal[rid] is not None:
                    if motion_orchestration_mode == "local":
                        _step_to(rid, goal[rid], dt)
            if loiter_until[rid] > t:
                command_pose = tuple(pose[rid])

            assigned_task_for_command = _match_active_task_for_robot_goal(rid, goal[rid])
            current_task_by_robot[rid] = assigned_task_for_command
            effective_goal_for_command = None if goal[rid] is None else _effective_goal(rid, goal[rid])
            motion_commands.append(
                build_motion_command(
                    robot_id=rid,
                    pose=command_pose,
                    goal=goal[rid],
                    effective_goal=effective_goal_for_command,
                    command_type=command_type,
                    source=command_source,
                    assigned_task=assigned_task_for_command,
                    planner_mode=("graph" if _graph_enabled_for_robot(rid) else "lane_projection"),
                    route_node_ids=(None if graph_plan_for_command is None else graph_plan_for_command.route_node_ids),
                    route_waypoints=(None if graph_plan_for_command is None else graph_plan_for_command.route_waypoints),
                    active_waypoint_index=(0 if graph_plan_for_command is None else graph_plan_for_command.active_waypoint_index),
                    blocked=(False if graph_plan_for_command is None else graph_plan_for_command.blocked),
                    wait_reason=(None if graph_plan_for_command is None else graph_plan_for_command.wait_reason),
                )
            )

            # Arrival / completion checks
            if motion_orchestration_mode == "local" and goal[rid] is not None:
                gx, gy = _effective_goal(rid, goal[rid])
                if math.hypot(pose[rid][0]-gx, pose[rid][1]-gy) <= arrival_radius_m:
                    # Find the active task at this location assigned to rid
                    matched = False
                    for tr in active_tasks:
                        if tr["assigned_primary"] != rid or tr["state"] != "active":
                            continue
                        tx, ty = _effective_goal(rid, (tr["x"], tr["y"]))
                        if math.hypot(pose[rid][0]-tx, pose[rid][1]-ty) > arrival_radius_m:
                            continue
                        matched = True
                        if task_action_kind(tr, deterring_modes, float(tau_service_s)) == "deterring":
                            # Start hold if not started; else complete when time passed
                            if tr["started_hold"] is None:
                                _start_deterring_hold(rid, tr, t)
                            elif t >= tr["started_hold"] + task_action_service_time_s(
                                tr,
                                deterring_modes=deterring_modes,
                                default_service_time_s=float(tau_service_s),
                            ):
                                _complete_deterring_task(rid, tr, t)
                            break
                        else:  # patrolling completes on proximity
                            _complete_patrolling_task(rid, tr, t)
                            break
                    if debug_movement and not matched:
                        print(f"[stall] {rid} at ({pose[rid][0]:.1f},{pose[rid][1]:.1f}) no matching task")
                    if not matched:
                        # Task may have been pruned/reassigned while robot was en route.
                        # Clear stale goal so the robot can pick a fresh assignment next step.
                        goal[rid] = None
                        if rid in graph_motion_states:
                            graph_motion_states[rid].clear()
                        stale_goal_clears += 1

        graph_reservations_snapshot = graph_reservations_step
        step_dispatched_stream_counts = {"reactive": 0, "predictive": 0}
        for rid, task_row in current_task_by_robot.items():
            if task_row is None:
                robots[rid].record_dispatch_time(t, t + dt, "idle")
                continue
            stream_key = _task_stream(task_row)
            robots[rid].record_dispatch_time(t, t + dt, stream_key)
            task_id = task_row.get("id")
            if task_id is None:
                continue
            if stream_key == "reactive":
                if task_id not in reactive_dispatched_task_ids:
                    reactive_dispatched_task_ids.add(task_id)
                    step_dispatched_stream_counts["reactive"] += 1
            else:
                if task_id not in predictive_dispatched_task_ids:
                    predictive_dispatched_task_ids.add(task_id)
                    step_dispatched_stream_counts["predictive"] += 1

        motion_execution_backend = publish_motion_commands(
            now_t=t,
            dt=dt,
            motion_orchestration_mode=motion_orchestration_mode,
            motion_command_callback=motion_command_callback,
            commands=motion_commands,
            pose=pose,
            goal=goal,
        )
        urgent_reactive_override_total += int(step_urgent_reactive_override_count)

        # --------------------------------------------------------------------
        # Stage 5: Telemetry, model advance, and forecast evaluation
        # --------------------------------------------------------------------
        # Telemetry: per-step poses + hotspots + periodic flush
        step_telemetry = run_telemetry_stage(
            mon=mon,
            telemetry_dir=telemetry_dir,
            now_t=t,
            robots=robots,
            active_tasks=active_tasks,
            pose=pose,
            loiter_until=loiter_until,
            goal=goal,
            profiles=profiles,
            sigma=sigma,
            effective_goal_fn=_effective_goal,
            lane_center_for_fn=_lane_center_for,
            is_at_headland_fn=_is_at_headland,
        )

        # 5) Advance SESTPP time
        for rob in robots.values():
            rob.advance_time(dt)

        # 5b) Forecast quality metrics (per scenario/per baseline run)
        forecast_last_eval_t, step_forecast = run_forecast_evaluation_stage(
            use_ground_truth=use_ground_truth,
            now_t=t,
            forecast_last_eval_t=forecast_last_eval_t,
            forecast_eval_period_s=forecast_eval_period_s,
            forecast_horizon_s=forecast_horizon_s,
            forecast_top_k=forecast_top_k,
            forecast_match_radius_m=forecast_match_radius_m,
            future_truth_events_fn=_future_truth_events,
            global_hotspots_fn=_global_hotspots,
            forecast_recall_vals=forecast_recall_vals,
            forecast_precision_vals=forecast_precision_vals,
            forecast_hit_flags=forecast_hit_flags,
            forecast_lead_times=forecast_lead_times,
        )

        # --------------------------------------------------------------------
        # Stage 6: Build and emit the frame snapshot
        # --------------------------------------------------------------------
        # Event visualization buffers (recent window)
        t_min = t - event_viz_window_s
        truth_pts = [(x, y) for (x, y, tt) in recent_truth if tt >= t_min]
        det_pts = [(x, y) for (x, y, tt) in recent_detections if tt >= t_min]
        total_distance = float(sum(travel_distance_by_robot.values()))
        total_completed = int(completed_count_by_type["deterring"] + completed_count_by_type["patrolling"])
        total_boundary_msgs = int(bus.boundary_msg_count + bus.intervention_msg_count)
        total_boundary_bytes = int(bus.boundary_bytes + bus.intervention_bytes)
        distance_by_type = {
            "UGV": float(sum(travel_distance_by_robot[rid] for rid in travel_distance_by_robot if profiles[rid].type == "UGV")),
            "UAV": float(sum(travel_distance_by_robot[rid] for rid in travel_distance_by_robot if profiles[rid].type == "UAV")),
        }
        energy_by_type = {
            "UGV": float(sum(energy_by_robot[rid] for rid in energy_by_robot if profiles[rid].type == "UGV")),
            "UAV": float(sum(energy_by_robot[rid] for rid in energy_by_robot if profiles[rid].type == "UAV")),
        }
        model_diag = {}
        for rid, rob in robots.items():
            try:
                model_diag[rid] = {
                    "lam_mean": float(np.mean(rob.m.lam)),
                    "lam_max": float(np.max(rob.m.lam)),
                    "trigger_sum": float(np.sum(rob.m.trigger_mass)),
                    "inhib_sum": float(np.sum(rob.m.inhib_mass)),
                }
            except Exception:
                model_diag[rid] = {
                    "lam_mean": float("nan"),
                    "lam_max": float("nan"),
                    "trigger_sum": float("nan"),
                    "inhib_sum": float("nan"),
                }
        robot_states_now = {
            rid: ("holding" if loiter_until[rid] > t else ("moving" if goal[rid] is not None else "idle"))
            for rid in pose
        }
        active_assigned_counts = {rid: 0 for rid in pose}
        for tr in active_tasks:
            if tr.get("state") != "active":
                continue
            rp = tr.get("assigned_primary")
            if rp in active_assigned_counts:
                active_assigned_counts[rp] += 1
        robot_has_task = {rid: (active_assigned_counts[rid] > 0) for rid in pose}
        if pose:
            n_robots = float(len(pose))
            cur_task_fraction = float(sum(1 for rid in pose if robot_has_task[rid])) / n_robots
            cur_moving_fraction = float(sum(1 for rid in pose if robot_states_now[rid] == "moving")) / n_robots
            cur_idle_fraction = float(sum(1 for rid in pose if robot_states_now[rid] == "idle")) / n_robots
            cur_idle_no_task_fraction = float(sum(1 for rid in pose if (robot_states_now[rid] == "idle" and not robot_has_task[rid]))) / n_robots
            cur_idle_with_task_fraction = float(sum(1 for rid in pose if (robot_states_now[rid] == "idle" and robot_has_task[rid]))) / n_robots
        else:
            cur_task_fraction = 0.0
            cur_moving_fraction = 0.0
            cur_idle_fraction = 0.0
            cur_idle_no_task_fraction = 0.0
            cur_idle_with_task_fraction = 0.0

        for rid in pose:
            robot_time_total[rid] += float(dt)
            st = robot_states_now[rid]
            has_task = robot_has_task[rid]
            if has_task:
                robot_time_with_task[rid] += float(dt)
            if st == "moving":
                robot_time_moving[rid] += float(dt)
                robot_idle_streak[rid] = 0.0
                if has_task:
                    robot_time_moving_with_task[rid] += float(dt)
            elif st == "holding":
                robot_time_holding[rid] += float(dt)
                robot_idle_streak[rid] = 0.0
            else:
                robot_time_idle[rid] += float(dt)
                robot_idle_streak[rid] += float(dt)
                if robot_idle_streak[rid] > robot_idle_streak_max[rid]:
                    robot_idle_streak_max[rid] = robot_idle_streak[rid]
        fleet_task_engagement_time += float(dt) * cur_task_fraction
        fleet_moving_time += float(dt) * cur_moving_fraction
        fleet_idle_no_task_time += float(dt) * cur_idle_no_task_fraction

        robot_utilization_by_robot = {
            rid: (robot_time_with_task[rid] / robot_time_total[rid]) if robot_time_total[rid] > 1e-9 else float("nan")
            for rid in pose
        }
        robot_idle_fraction_by_robot = {
            rid: (robot_time_idle[rid] / robot_time_total[rid]) if robot_time_total[rid] > 1e-9 else float("nan")
            for rid in pose
        }
        robot_moving_with_task_fraction_by_robot = {
            rid: (robot_time_moving_with_task[rid] / robot_time_total[rid]) if robot_time_total[rid] > 1e-9 else float("nan")
            for rid in pose
        }
        sim_elapsed_s = max([float(v) for v in robot_time_total.values()] + [1e-9])
        dispatch_time_query_t = float(t) + float(dt)
        robot_dispatch_time_allocation_by_robot = {
            rid: robots[rid].dispatch_time_allocation(dispatch_time_query_t)
            for rid in robots
        }
        robot_reactive_fraction_by_robot = {
            rid: float(robot_dispatch_time_allocation_by_robot[rid].get("reactive", 0.0))
            for rid in robots
        }
        robot_predictive_fraction_by_robot = {
            rid: float(robot_dispatch_time_allocation_by_robot[rid].get("predictive", 0.0))
            for rid in robots
        }
        robot_idle_allocation_fraction_by_robot = {
            rid: float(robot_dispatch_time_allocation_by_robot[rid].get("idle", 0.0))
            for rid in robots
        }
        final_step = (t + dt > t_end)
        if final_step:
            deterring_quality_cache = _compute_deterring_quality()
        diag_counts = getattr(taskgen, "diag_counts", {})
        def _diag_source_counts(prefix):
            """Return diagnostic task counts by source stream."""
            prefix_text = f"{prefix}_"
            out = {}
            for key, value in diag_counts.items():
                if key.startswith(prefix_text):
                    out[key[len(prefix_text):]] = int(value)
            return out

        model_deterring_candidate_source_counts = _diag_source_counts("model_deterring_candidates")
        model_deterring_generated_source_counts = _diag_source_counts("model_deterring_generated")
        model_deterring_not_selected_source_counts = _diag_source_counts("model_deterring_not_selected")
        model_deterring_accepted_source_counts = {
            str(k): int(v) for k, v in model_deterring_accepted_by_source.items()
        }
        llr_values = np.asarray(getattr(taskgen, "_diag_model_deterring_llr_values", []), dtype=float)
        llr_samples = int(diag_counts.get("model_deterring_llr_samples", 0))
        p_event_samples = int(diag_counts.get("model_deterring_p_event_samples", 0))
        deltaj_ratio_samples = int(diag_counts.get("model_deterring_deltaJ_per_cost_samples", 0))
        llr_mean = (
            float(diag_counts.get("model_deterring_llr_sum", 0.0)) / float(llr_samples)
            if llr_samples > 0 else float("nan")
        )
        llr_max = float(diag_counts.get("model_deterring_llr_max", float("nan")))
        if not np.isfinite(llr_max):
            llr_max = float("nan")
        llr_p50 = float(np.percentile(llr_values, 50.0)) if llr_values.size > 0 else float("nan")
        llr_p75 = float(np.percentile(llr_values, 75.0)) if llr_values.size > 0 else float("nan")
        llr_p90 = float(np.percentile(llr_values, 90.0)) if llr_values.size > 0 else float("nan")
        p_event_mean = (
            float(diag_counts.get("model_deterring_p_event_sum", 0.0)) / float(p_event_samples)
            if p_event_samples > 0 else float("nan")
        )
        deltaJ_per_cost_mean = (
            float(diag_counts.get("model_deterring_deltaJ_per_cost_sum", 0.0)) / float(deltaj_ratio_samples)
            if deltaj_ratio_samples > 0 else float("nan")
        )
        preventive_service_rate_mean = (
            float(preventive_service_rate_mean_accum) / float(preventive_capacity_sample_count)
            if preventive_capacity_sample_count > 0 else float("nan")
        )
        preventive_direct_arrival_rate_mean = (
            float(preventive_direct_arrival_rate_mean_accum) / float(preventive_capacity_sample_count)
            if preventive_capacity_sample_count > 0 else float("nan")
        )
        preventive_capacity_remaining_mean = (
            float(preventive_capacity_remaining_mean_accum) / float(preventive_capacity_sample_count)
            if preventive_capacity_sample_count > 0 else float("nan")
        )
        selected_calibration_metrics_map = dict(selected_calibration_summary_metrics or {})

        def _selected_calibration_metric(name: str) -> float:
            """Read a selected calibration metric from the active calibration record."""
            try:
                value = float(selected_calibration_metrics_map.get(name, float("nan")))
            except Exception:
                return float("nan")
            return float(value) if np.isfinite(value) else float("nan")

        reactive_dispatched_total = int(len(reactive_dispatched_task_ids))
        predictive_dispatched_total = int(len(predictive_dispatched_task_ids))
        reactive_completed_fraction = (
            float(reactive_completed_total) / float(reactive_generated_total)
            if reactive_generated_total > 0 else float("nan")
        )
        predictive_completed_fraction = (
            float(predictive_completed_total) / float(predictive_generated_total)
            if predictive_generated_total > 0 else float("nan")
        )
        predictive_expired_fraction = (
            float(predictive_expired_total) / float(predictive_admitted_total)
            if predictive_admitted_total > 0 else float("nan")
        )
        predictive_confidence_mean = (
            float(predictive_confidence_sum) / float(predictive_confidence_sample_count)
            if predictive_confidence_sample_count > 0 else float("nan")
        )
        predictive_confidence_completed_mean = (
            float(predictive_confidence_completed_sum) / float(predictive_confidence_completed_count)
            if predictive_confidence_completed_count > 0 else float("nan")
        )
        predictive_completion_ratio = (
            float(predictive_completed_total) / float(predictive_admitted_total)
            if predictive_admitted_total > 0 else float("nan")
        )
        (
            predictive_success_proxy_evaluated_total,
            predictive_success_proxy_total,
            predictive_false_positive_proxy_total,
        ) = _predictive_success_proxy_counts(t)
        predictive_success_ratio = (
            float(predictive_success_proxy_total) / float(predictive_success_proxy_evaluated_total)
            if predictive_success_proxy_evaluated_total > 0 else float("nan")
        )
        predictive_false_positive_ratio = (
            float(predictive_false_positive_proxy_total) / float(predictive_success_proxy_evaluated_total)
            if predictive_success_proxy_evaluated_total > 0 else float("nan")
        )
        reactive_load_factor_estimate = float(_reactive_load_factor_estimate(dispatch_time_query_t))
        predictive_risk_adjusted_mean_confidence = (
            float(predictive_risk_adjusted_confidence_sum)
            / float(predictive_risk_adjusted_candidate_sample_count)
            if predictive_risk_adjusted_candidate_sample_count > 0 else float("nan")
        )
        predictive_risk_adjusted_mean_utility = (
            float(predictive_risk_adjusted_utility_sum)
            / float(predictive_risk_adjusted_candidate_sample_count)
            if predictive_risk_adjusted_candidate_sample_count > 0 else float("nan")
        )
        predictive_risk_adjusted_rho_eff_mean = (
            float(predictive_risk_adjusted_rho_eff_sum)
            / float(predictive_risk_adjusted_dispatch_sample_count)
            if predictive_risk_adjusted_dispatch_sample_count > 0 else float("nan")
        )
        predictive_risk_adjusted_reactive_pressure_mean = (
            float(predictive_risk_adjusted_reactive_pressure_sum)
            / float(predictive_risk_adjusted_dispatch_sample_count)
            if predictive_risk_adjusted_dispatch_sample_count > 0 else float("nan")
        )
        predictive_risk_adjusted_reactive_age_norm_mean = (
            float(predictive_risk_adjusted_reactive_age_norm_sum)
            / float(predictive_risk_adjusted_dispatch_sample_count)
            if predictive_risk_adjusted_dispatch_sample_count > 0 else float("nan")
        )
        last_risk_diag = dict(getattr(last_dispatch_structured, "risk_adjusted_diagnostics", {}) or {})
        stl_hab_metrics = _stl_and_habituation_metrics(t)

        metrics = {
            "dispatch_policy": str(dispatch_policy),
            "reservation_fraction": float(reservation_fraction),
            "reservation_window_s": float(reservation_window_s),
            "reactive_override_slack_s": float(reactive_override_slack_s),
            "reservation_softening_alpha": float(reservation_softening_alpha),
            "reservation_age_softening_beta": float(reservation_age_softening_beta),
            "reservation_age_gate": float(reservation_age_gate),
            "predictive_slack_min_s": float(predictive_slack_min_s),
            "reactive_pressure_max_for_predictive": float(reactive_pressure_max_for_predictive),
            "predictive_confidence_min": float(predictive_confidence_min),
            "predictive_deadline_weight": float(predictive_deadline_weight),
            "predictive_eta_penalty_weight": float(predictive_eta_penalty_weight),
            "predictive_utility_mode": str(predictive_utility_mode),
            "predictive_confidence_source": str(predictive_confidence_source),
            "predictive_confidence_power": float(predictive_confidence_power),
            "predictive_time_score_deadline_scale_s": float(predictive_time_score_deadline_scale_s),
            "predictive_time_score_reactive_pressure_weight": float(predictive_time_score_reactive_pressure_weight),
            "predictive_time_score_infeasible_penalty": float(predictive_time_score_infeasible_penalty),
            "predictive_utility_min": float(predictive_utility_min),
            "predictive_cost_ratio_min": float(predictive_cost_ratio_min),
            "predictive_opportunity_cost_weight": float(predictive_opportunity_cost_weight),
            "predictive_eta_cost_weight": float(predictive_eta_cost_weight),
            "predictive_service_cost_weight": float(predictive_service_cost_weight),
            "risk_adjusted_reservation_alpha": float(risk_adjusted_reservation_alpha),
            "risk_adjusted_reservation_beta": float(risk_adjusted_reservation_beta),
            "tau_service_s": float(tau_service_s),
            "enable_predictive_lead_time": int(bool(enable_predictive_lead_time)),
            "predictive_planning_topology": str(predictive_planning_topology),
            "predictive_timing_mode": str(predictive_timing_mode),
            "predictive_lead_time_min_s": float(predictive_lead_time_min_s),
            "predictive_lead_time_max_eta_s": float(predictive_lead_time_max_eta_s),
            "predictive_lead_time_buffer_s": float(predictive_lead_time_buffer_s),
            "predictive_lead_time_risk_power": float(predictive_lead_time_risk_power),
            "predictive_expiry_grace_s": float(predictive_expiry_grace_s),
            "predictive_selection_policy": str(predictive_selection_policy),
            **stl_hab_metrics,
            "zone_assignment_mode": str(zone_assignment_mode),
            "defer_predictive_action_selection": int(bool(defer_predictive_action_selection)),
            "assignment_switch_penalty": float(assignment_switch_penalty),
            "value_weighted_exposure": float(value_weighted_exposure),
            "mean_response_time_s": float(np.mean(response_times)) if response_times else float("nan"),
            "reactive_mean_response_time_s": float(np.mean(reactive_response_times)) if reactive_response_times else float("nan"),
            "response_samples": int(len(response_times)),
            "reactive_response_samples": int(len(reactive_response_times)),
            "travel_distance_by_robot": {rid: float(v) for rid, v in travel_distance_by_robot.items()},
            "travel_distance_by_type": distance_by_type,
            "energy_by_robot": {rid: float(v) for rid, v in energy_by_robot.items()},
            "energy_by_type": energy_by_type,
            "completed_tasks_by_type": dict(completed_count_by_type),
            "completed_tasks_total": total_completed,
            "tasks_per_unit_distance": (float(total_completed) / total_distance) if total_distance > 1e-9 else float("nan"),
            "exposure_per_completed_task": (float(value_weighted_exposure) / float(total_completed)) if total_completed > 0 else float("nan"),
            "score_per_completed_task": (float(np.mean(completed_task_scores)) if completed_task_scores else float("nan")),
            "boundary_message_count": total_boundary_msgs,
            "boundary_bytes_sent": total_boundary_bytes,
            "boundary_message_count_by_type": {
                "detection": int(bus.boundary_msg_count),
                "intervention": int(bus.intervention_msg_count),
            },
            "boundary_bytes_by_type": {
                "detection": int(bus.boundary_bytes),
                "intervention": int(bus.intervention_bytes),
            },
            "intervention_msg_dropped_debounce": int(bus.intervention_msg_dropped_debounce),
            "intervention_msg_dropped_low_weight": int(bus.intervention_msg_dropped_low_weight),
            "fleet_task_assigned_fraction": float(cur_task_fraction),
            "fleet_moving_fraction": float(cur_moving_fraction),
            "fleet_idle_fraction": float(cur_idle_fraction),
            "fleet_idle_no_task_fraction": float(cur_idle_no_task_fraction),
            "fleet_idle_with_task_fraction": float(cur_idle_with_task_fraction),
            "fleet_task_engagement_fraction_so_far": float(fleet_task_engagement_time / sim_elapsed_s),
            "fleet_moving_fraction_so_far": float(fleet_moving_time / sim_elapsed_s),
            "fleet_idle_no_task_fraction_so_far": float(fleet_idle_no_task_time / sim_elapsed_s),
            "robot_task_utilization_by_robot": robot_utilization_by_robot,
            "robot_idle_fraction_by_robot": robot_idle_fraction_by_robot,
            "robot_moving_with_task_fraction_by_robot": robot_moving_with_task_fraction_by_robot,
            "robot_reactive_fraction_by_robot": robot_reactive_fraction_by_robot,
            "robot_predictive_fraction_by_robot": robot_predictive_fraction_by_robot,
            "robot_idle_allocation_fraction_by_robot": robot_idle_allocation_fraction_by_robot,
            "robot_longest_idle_s_by_robot": {rid: float(v) for rid, v in robot_idle_streak_max.items()},
            "robot_tail_idle_s_by_robot": {rid: float(v) for rid, v in robot_idle_streak.items()},
            "robot_task_utilization_mean": float(np.nanmean(list(robot_utilization_by_robot.values()))) if robot_utilization_by_robot else float("nan"),
            "robot_idle_fraction_mean": float(np.nanmean(list(robot_idle_fraction_by_robot.values()))) if robot_idle_fraction_by_robot else float("nan"),
            "robot_moving_with_task_fraction_mean": float(np.nanmean(list(robot_moving_with_task_fraction_by_robot.values()))) if robot_moving_with_task_fraction_by_robot else float("nan"),
            "robot_reactive_fraction_mean": float(np.nanmean(list(robot_reactive_fraction_by_robot.values()))) if robot_reactive_fraction_by_robot else float("nan"),
            "robot_predictive_fraction_mean": float(np.nanmean(list(robot_predictive_fraction_by_robot.values()))) if robot_predictive_fraction_by_robot else float("nan"),
            "robot_idle_allocation_fraction_mean": float(np.nanmean(list(robot_idle_allocation_fraction_by_robot.values()))) if robot_idle_allocation_fraction_by_robot else float("nan"),
            "robot_longest_idle_s_max": float(max(robot_idle_streak_max.values())) if robot_idle_streak_max else float("nan"),
            "robot_tail_idle_s_max": float(max(robot_idle_streak.values())) if robot_idle_streak else float("nan"),
            "robots_zero_distance_count": int(sum(1 for rid in travel_distance_by_robot if travel_distance_by_robot[rid] <= 1e-6)),
            "stale_goal_clears": int(stale_goal_clears),
            "urgent_reactive_override_total": int(urgent_reactive_override_total),
            "predictive_deadline_feasible_total": int(predictive_deadline_feasible_total),
            "predictive_deadline_checked_total": int(predictive_deadline_checked_total),
            "predictive_deadline_feasible_fraction": (
                float(predictive_deadline_feasible_total) / float(predictive_deadline_checked_total)
                if predictive_deadline_checked_total > 0 else float("nan")
            ),
            "predictive_risk_adjusted_candidates_total": int(predictive_risk_adjusted_candidates_total),
            "predictive_risk_adjusted_rejected_confidence_total": int(
                predictive_risk_adjusted_rejected_confidence_total
            ),
            "predictive_risk_adjusted_rejected_slack_total": int(
                predictive_risk_adjusted_rejected_slack_total
            ),
            "predictive_risk_adjusted_rejected_utility_total": int(
                predictive_risk_adjusted_rejected_utility_total
            ),
            "predictive_risk_adjusted_rejected_cost_ratio_total": int(
                predictive_risk_adjusted_rejected_cost_ratio_total
            ),
            "predictive_risk_adjusted_mean_confidence": float(predictive_risk_adjusted_mean_confidence),
            "predictive_risk_adjusted_mean_utility": float(predictive_risk_adjusted_mean_utility),
            "predictive_risk_adjusted_rho_eff": float(last_risk_diag.get("rho_eff", float("nan"))),
            "predictive_risk_adjusted_rho_eff_mean": float(predictive_risk_adjusted_rho_eff_mean),
            "predictive_risk_adjusted_reactive_pressure": float(
                last_risk_diag.get("reactive_pressure", float("nan"))
            ),
            "predictive_risk_adjusted_reactive_pressure_mean": float(
                predictive_risk_adjusted_reactive_pressure_mean
            ),
            "predictive_risk_adjusted_reactive_age_norm": float(
                last_risk_diag.get("reactive_age_norm", float("nan"))
            ),
            "predictive_risk_adjusted_reactive_age_norm_mean": float(
                predictive_risk_adjusted_reactive_age_norm_mean
            ),
            "direct_detection_task_refresh_active": int(direct_detection_task_refresh_active),
            "direct_detection_task_refresh_skipped_unassigned": int(direct_detection_task_refresh_skipped_unassigned),
            "direct_detection_task_refresh_skipped_eta": int(direct_detection_task_refresh_skipped_eta),
            "direct_detection_task_cluster_groups": int(direct_detection_task_cluster_groups),
            "direct_detection_task_cluster_merged": int(direct_detection_task_cluster_merged),
            "direct_detection_task_response_matches": int(direct_detection_task_response_matches),
            "reactive_generated_total": int(reactive_generated_total),
            "predictive_generated_total": int(predictive_generated_total),
            "predictive_distinct_generated_total": int(len(predictive_distinct_generated_keys)),
            "reactive_admitted_total": int(reactive_admitted_total),
            "predictive_admitted_total": int(predictive_admitted_total),
            "predictive_distinct_admitted_total": int(len(predictive_distinct_admitted_keys)),
            "reactive_dispatched_total": int(reactive_dispatched_total),
            "predictive_dispatched_total": int(predictive_dispatched_total),
            "reactive_completed_total": int(reactive_completed_total),
            "predictive_completed_total": int(predictive_completed_total),
            "predictive_distinct_completed_total": int(len(predictive_distinct_completed_keys)),
            "reactive_completed_fraction": float(reactive_completed_fraction),
            "predictive_completed_fraction": float(predictive_completed_fraction),
            "predictive_expired_total": int(predictive_expired_total),
            "predictive_expired_fraction": float(predictive_expired_fraction),
            "predictive_confidence_mean": float(predictive_confidence_mean),
            "predictive_confidence_completed_mean": float(predictive_confidence_completed_mean),
            "predictive_expected_deltaJ_total": float(predictive_expected_deltaJ_total),
            "predictive_raw_deltaJ_total": float(predictive_raw_deltaJ_total),
            "predictive_completion_ratio": float(predictive_completion_ratio),
            "predictive_success_ratio": float(predictive_success_ratio),
            "predictive_false_positive_ratio": float(predictive_false_positive_ratio),
            "predictive_success_proxy_evaluated_total": int(predictive_success_proxy_evaluated_total),
            "predictive_success_proxy_total": int(predictive_success_proxy_total),
            "predictive_false_positive_proxy_total": int(predictive_false_positive_proxy_total),
            "centralized_global_opportunity_count_total": int(centralized_global_opportunity_count_total),
            "cross_zone_assignment_total": int(cross_zone_assignment_total),
            "predictive_zone_bonus_mean": (
                float(predictive_zone_bonus_sum) / float(predictive_zone_bonus_count)
                if predictive_zone_bonus_count > 0 else float("nan")
            ),
            "reactive_load_factor_estimate": float(reactive_load_factor_estimate),
            **_current_reactive_load_factor_metrics(t),
            "preventive_policy": str(preventive_policy),
            "preventive_policy_source": str(preventive_policy_source),
            "selective_preventive_enabled": int(bool(selective_preventive_enabled)),
            "use_frozen_calibration": int(bool(use_frozen_calibration)),
            "selected_calibration_config_id": str(selected_calibration_config_id),
            "selected_calibration_source": str(selected_calibration_source),
            "calibrated_model_sigma": float(calibrated_model_sigma),
            "calibrated_model_omega": float(calibrated_model_omega),
            "calibrated_model_alpha_in": float(calibrated_model_alpha_in),
            "calibrated_model_alpha_cross": float(calibrated_model_alpha_cross),
            "calibrated_model_alpha_inhib": float(calibrated_model_alpha_inhib),
            "calibrated_model_omega_inhib": float(calibrated_model_omega_inhib),
            "calibrated_model_mu_base": float(calibrated_model_mu_base),
            "calibrated_model_bg_ema": float(calibrated_model_bg_ema),
            "calibrated_model_feedback_sigma_scale": float(calibrated_model_feedback_sigma_scale),
            "calibrated_model_feedback_omega_scale": float(calibrated_model_feedback_omega_scale),
            "selected_calibration_rank": _selected_calibration_metric("rank"),
            "selected_calibration_proposed_field_logloss_mean": _selected_calibration_metric("proposed_field_logloss_mean"),
            "selected_calibration_proposed_field_brier_mean": _selected_calibration_metric("proposed_field_brier_mean"),
            "selected_calibration_proposed_nll_mean": _selected_calibration_metric("proposed_nll_mean"),
            "selected_calibration_nll_improvement_pct_mean": _selected_calibration_metric("nll_improvement_pct_mean"),
            "model_deterring_gate_policy": str(model_deterring_gate_policy),
            "model_deterring_accepted": int(model_deterring_accepted),
            "model_deterring_rejected_budget": int(model_deterring_rejected_budget),
            "model_deterring_generated": int(diag_counts.get("model_deterring_generated", 0)),
            "model_deterring_candidates_total": int(diag_counts.get("model_deterring_candidates_total", 0)),
            "model_deterring_candidates_by_source": dict(model_deterring_candidate_source_counts),
            "model_deterring_generated_by_source": dict(model_deterring_generated_source_counts),
            "model_deterring_accepted_by_source": dict(model_deterring_accepted_source_counts),
            "model_deterring_rejected_cooldown": int(diag_counts.get("model_deterring_rejected_cooldown", 0)),
            "model_deterring_rejected_field": int(diag_counts.get("model_deterring_rejected_field", 0)),
            "model_deterring_pass_field": int(diag_counts.get("model_deterring_pass_field", 0)),
            "model_deterring_rejected_predicted_deltaJ": int(diag_counts.get("model_deterring_rejected_predicted_deltaJ", 0)),
            "model_deterring_pass_predicted_deltaJ": int(diag_counts.get("model_deterring_pass_predicted_deltaJ", 0)),
            "model_deterring_rejected_risk": int(diag_counts.get("model_deterring_rejected_risk", 0)),
            "model_deterring_pass_risk": int(diag_counts.get("model_deterring_pass_risk", 0)),
            "model_deterring_rejected_support": int(diag_counts.get("model_deterring_rejected_support", 0)),
            "model_deterring_rejected_persistence": int(diag_counts.get("model_deterring_rejected_persistence", 0)),
            "model_deterring_rejected_repeat_no_new_support": int(diag_counts.get("model_deterring_rejected_repeat_no_new_support", 0)),
            "model_deterring_rejected_eta": int(diag_counts.get("model_deterring_rejected_eta", 0)),
            "model_deterring_rejected_busy": int(diag_counts.get("model_deterring_rejected_busy", 0)),
            "model_deterring_rejected_margin": int(diag_counts.get("model_deterring_rejected_margin", 0)),
            "model_deterring_pass_support": int(diag_counts.get("model_deterring_pass_support", 0)),
            "model_deterring_pass_sprt": int(diag_counts.get("model_deterring_pass_sprt", 0)),
            "model_deterring_rejected_sprt_pending": int(diag_counts.get("model_deterring_rejected_sprt_pending", 0)),
            "model_deterring_rejected_sprt_negative": int(diag_counts.get("model_deterring_rejected_sprt_negative", 0)),
            "model_deterring_rejected_sprt_margin": int(diag_counts.get("model_deterring_rejected_sprt_margin", 0)),
            "model_deterring_pass_chance": int(diag_counts.get("model_deterring_pass_chance", 0)),
            "model_deterring_rejected_chance": int(diag_counts.get("model_deterring_rejected_chance", 0)),
            "model_deterring_pass_utility_ratio": int(diag_counts.get("model_deterring_pass_utility_ratio", 0)),
            "model_deterring_rejected_utility_ratio": int(diag_counts.get("model_deterring_rejected_utility_ratio", 0)),
            "model_deterring_pass_selection_weight": int(diag_counts.get("model_deterring_pass_selection_weight", 0)),
            "model_deterring_rejected_selection_weight": int(diag_counts.get("model_deterring_rejected_selection_weight", 0)),
            "model_deterring_pass_capacity": int(diag_counts.get("model_deterring_pass_capacity", 0)),
            "model_deterring_capacity_pending": int(diag_counts.get("model_deterring_capacity_pending", 0)),
            "model_deterring_rejected_capacity": int(diag_counts.get("model_deterring_rejected_capacity", 0)),
            "model_deterring_llr_mean": float(llr_mean),
            "model_deterring_llr_max": float(llr_max),
            "model_deterring_llr_p50": float(llr_p50),
            "model_deterring_llr_p75": float(llr_p75),
            "model_deterring_llr_p90": float(llr_p90),
            "model_deterring_p_event_mean": float(p_event_mean),
            "model_deterring_deltaJ_per_cost_mean": float(deltaJ_per_cost_mean),
            "model_deterring_cluster_key_total": int(diag_counts.get("model_deterring_cluster_key_total", 0)),
            "model_deterring_cluster_key_reused": int(diag_counts.get("model_deterring_cluster_key_reused", 0)),
            "model_deterring_cluster_key_churn": int(diag_counts.get("model_deterring_cluster_key_churn", 0)),
            "model_deterring_cluster_key_new": int(diag_counts.get("model_deterring_cluster_key_new", 0)),
            "model_deterring_not_selected": int(diag_counts.get("model_deterring_not_selected", 0)),
            "model_deterring_not_selected_by_source": dict(model_deterring_not_selected_source_counts),
            "model_deterring_rejected_budget_count_mode": int(model_deterring_rejected_budget_count_mode),
            "model_deterring_rejected_budget_utility_mode": int(model_deterring_rejected_budget_utility_mode),
            "model_deterring_budget_mode": str(model_deterring_budget_mode),
            "preventive_service_rate_per_robot_mean": float(preventive_service_rate_mean),
            "preventive_direct_arrival_rate_per_robot_mean": float(preventive_direct_arrival_rate_mean),
            "preventive_capacity_remaining_per_robot_mean": float(preventive_capacity_remaining_mean),
            "planner_rejected_unassigned": int(planner_rejected_unassigned),
            "planner_rejected_task_cap": int(planner_rejected_task_cap),
            "planner_rejected_patrol_cap": int(planner_rejected_patrol_cap),
            "planner_rejected_patrol_locked_model_det": int(planner_rejected_patrol_locked_model_det),
            "planner_rejected_model_det_cap": int(planner_rejected_model_det_cap),
            "planner_rejected_model_det_cycle_cap": int(planner_rejected_model_det_cycle_cap),
            "planner_rejected_model_det_busy_primary": int(planner_rejected_model_det_busy_primary),
            "planner_rejected_model_det_busy_fallback_quality": int(planner_rejected_model_det_busy_fallback_quality),
            "planner_rejected_model_det_direct_conflict": int(planner_rejected_model_det_direct_conflict),
            "planner_accepted_model_det_idle_primary": int(planner_accepted_model_det_idle_primary),
            "planner_accepted_model_det_busy_primary": int(planner_accepted_model_det_busy_primary),
            "planner_replaced_patrol": int(planner_replaced_patrol),
            "truth_candidate_events": int(truth_candidate_events),
            "truth_accepted_events": int(truth_accepted_events),
            "truth_suppressed_events": int(truth_suppressed_events),
            "truth_detection_opportunities": int(truth_detection_opportunities),
            "truth_detections_observed": int(truth_detections_observed),
            "truth_detections_missed_range": int(truth_detections_missed_range),
            "truth_detections_missed_false_negative": int(truth_detections_missed_false_negative),
            "truth_suppression_rate": (float(truth_suppressed_events) / float(truth_candidate_events)) if truth_candidate_events > 0 else float("nan"),
            "birds_deterred_pct": (100.0 * float(truth_suppressed_events) / float(truth_candidate_events)) if truth_candidate_events > 0 else float("nan"),
            **_current_truth_window_metrics(t),
            **_current_reactive_load_factor_metrics(t),
            "truth_suppression_effect_mean": (float(suppression_effect_sum) / float(truth_candidate_events)) if truth_candidate_events > 0 else float("nan"),
            "truth_suppression_effect_sum": float(suppression_effect_sum),
            "truth_suppression_effect_by_mode": dict(suppression_effect_by_mode),
            "truth_suppression_effect_by_source": dict(suppression_effect_by_source),
            **deterring_quality_cache,
            "forecast_recall_at_k": float(np.mean(forecast_recall_vals)) if forecast_recall_vals else float("nan"),
            "forecast_precision_at_k": float(np.mean(forecast_precision_vals)) if forecast_precision_vals else float("nan"),
            "forecast_hotspot_hit_rate": float(np.mean(forecast_hit_flags)) if forecast_hit_flags else float("nan"),
            "forecast_lead_time_s": float(np.mean(forecast_lead_times)) if forecast_lead_times else float("nan"),
            "forecast_samples": int(len(forecast_precision_vals)),
        }
        final_metrics = {
            "dispatch_policy": str(dispatch_policy),
            "reservation_fraction": float(reservation_fraction),
            "reservation_window_s": float(reservation_window_s),
            "reactive_override_slack_s": float(reactive_override_slack_s),
            "reservation_softening_alpha": float(reservation_softening_alpha),
            "reservation_age_softening_beta": float(reservation_age_softening_beta),
            "reservation_age_gate": float(reservation_age_gate),
            "predictive_slack_min_s": float(predictive_slack_min_s),
            "reactive_pressure_max_for_predictive": float(reactive_pressure_max_for_predictive),
            "predictive_confidence_min": float(predictive_confidence_min),
            "predictive_deadline_weight": float(predictive_deadline_weight),
            "predictive_eta_penalty_weight": float(predictive_eta_penalty_weight),
            "predictive_utility_mode": str(predictive_utility_mode),
            "predictive_confidence_source": str(predictive_confidence_source),
            "predictive_confidence_power": float(predictive_confidence_power),
            "predictive_time_score_deadline_scale_s": float(predictive_time_score_deadline_scale_s),
            "predictive_time_score_reactive_pressure_weight": float(predictive_time_score_reactive_pressure_weight),
            "predictive_time_score_infeasible_penalty": float(predictive_time_score_infeasible_penalty),
            "predictive_utility_min": float(predictive_utility_min),
            "predictive_cost_ratio_min": float(predictive_cost_ratio_min),
            "predictive_opportunity_cost_weight": float(predictive_opportunity_cost_weight),
            "predictive_eta_cost_weight": float(predictive_eta_cost_weight),
            "predictive_service_cost_weight": float(predictive_service_cost_weight),
            "risk_adjusted_reservation_alpha": float(risk_adjusted_reservation_alpha),
            "risk_adjusted_reservation_beta": float(risk_adjusted_reservation_beta),
            "tau_service_s": float(tau_service_s),
            "enable_predictive_lead_time": int(bool(enable_predictive_lead_time)),
            "predictive_planning_topology": str(predictive_planning_topology),
            "predictive_timing_mode": str(predictive_timing_mode),
            "predictive_lead_time_min_s": float(predictive_lead_time_min_s),
            "predictive_lead_time_max_eta_s": float(predictive_lead_time_max_eta_s),
            "predictive_lead_time_buffer_s": float(predictive_lead_time_buffer_s),
            "predictive_lead_time_risk_power": float(predictive_lead_time_risk_power),
            "predictive_expiry_grace_s": float(predictive_expiry_grace_s),
            "predictive_selection_policy": str(predictive_selection_policy),
            **stl_hab_metrics,
            "zone_assignment_mode": str(zone_assignment_mode),
            "defer_predictive_action_selection": int(bool(defer_predictive_action_selection)),
            "assignment_switch_penalty": float(assignment_switch_penalty),
            "value_weighted_exposure": float(value_weighted_exposure),
            "mean_response_time_s": float(np.mean(response_times)) if response_times else float("nan"),
            "reactive_mean_response_time_s": float(np.mean(reactive_response_times)) if reactive_response_times else float("nan"),
            "completed_tasks_total": int(total_completed),
            "travel_distance_total": float(total_distance),
            "reactive_generated_total": int(reactive_generated_total),
            "predictive_generated_total": int(predictive_generated_total),
            "predictive_distinct_generated_total": int(len(predictive_distinct_generated_keys)),
            "reactive_admitted_total": int(reactive_admitted_total),
            "predictive_admitted_total": int(predictive_admitted_total),
            "predictive_distinct_admitted_total": int(len(predictive_distinct_admitted_keys)),
            "reactive_dispatched_total": int(reactive_dispatched_total),
            "predictive_dispatched_total": int(predictive_dispatched_total),
            "reactive_completed_total": int(reactive_completed_total),
            "predictive_completed_total": int(predictive_completed_total),
            "predictive_distinct_completed_total": int(len(predictive_distinct_completed_keys)),
            "reactive_completed_fraction": float(reactive_completed_fraction),
            "predictive_completed_fraction": float(predictive_completed_fraction),
            "predictive_expired_total": int(predictive_expired_total),
            "predictive_expired_fraction": float(predictive_expired_fraction),
            "predictive_confidence_mean": float(predictive_confidence_mean),
            "predictive_confidence_completed_mean": float(predictive_confidence_completed_mean),
            "predictive_expected_deltaJ_total": float(predictive_expected_deltaJ_total),
            "predictive_raw_deltaJ_total": float(predictive_raw_deltaJ_total),
            "predictive_completion_ratio": float(predictive_completion_ratio),
            "predictive_success_ratio": float(predictive_success_ratio),
            "predictive_false_positive_ratio": float(predictive_false_positive_ratio),
            "predictive_success_proxy_evaluated_total": int(predictive_success_proxy_evaluated_total),
            "predictive_success_proxy_total": int(predictive_success_proxy_total),
            "predictive_false_positive_proxy_total": int(predictive_false_positive_proxy_total),
            "centralized_global_opportunity_count_total": int(centralized_global_opportunity_count_total),
            "cross_zone_assignment_total": int(cross_zone_assignment_total),
            "predictive_zone_bonus_mean": (
                float(predictive_zone_bonus_sum) / float(predictive_zone_bonus_count)
                if predictive_zone_bonus_count > 0 else float("nan")
            ),
            "reactive_load_factor_estimate": float(reactive_load_factor_estimate),
            **_current_reactive_load_factor_metrics(t),
            "urgent_reactive_override_total": int(urgent_reactive_override_total),
            "predictive_deadline_feasible_total": int(predictive_deadline_feasible_total),
            "predictive_deadline_checked_total": int(predictive_deadline_checked_total),
            "predictive_deadline_feasible_fraction": (
                float(predictive_deadline_feasible_total) / float(predictive_deadline_checked_total)
                if predictive_deadline_checked_total > 0 else float("nan")
            ),
            "predictive_risk_adjusted_candidates_total": int(predictive_risk_adjusted_candidates_total),
            "predictive_risk_adjusted_rejected_confidence_total": int(
                predictive_risk_adjusted_rejected_confidence_total
            ),
            "predictive_risk_adjusted_rejected_slack_total": int(
                predictive_risk_adjusted_rejected_slack_total
            ),
            "predictive_risk_adjusted_rejected_utility_total": int(
                predictive_risk_adjusted_rejected_utility_total
            ),
            "predictive_risk_adjusted_rejected_cost_ratio_total": int(
                predictive_risk_adjusted_rejected_cost_ratio_total
            ),
            "predictive_risk_adjusted_mean_confidence": float(predictive_risk_adjusted_mean_confidence),
            "predictive_risk_adjusted_mean_utility": float(predictive_risk_adjusted_mean_utility),
            "predictive_risk_adjusted_rho_eff": float(last_risk_diag.get("rho_eff", float("nan"))),
            "predictive_risk_adjusted_rho_eff_mean": float(predictive_risk_adjusted_rho_eff_mean),
            "predictive_risk_adjusted_reactive_pressure": float(
                last_risk_diag.get("reactive_pressure", float("nan"))
            ),
            "predictive_risk_adjusted_reactive_pressure_mean": float(
                predictive_risk_adjusted_reactive_pressure_mean
            ),
            "predictive_risk_adjusted_reactive_age_norm": float(
                last_risk_diag.get("reactive_age_norm", float("nan"))
            ),
            "predictive_risk_adjusted_reactive_age_norm_mean": float(
                predictive_risk_adjusted_reactive_age_norm_mean
            ),
            "boundary_message_count": int(total_boundary_msgs),
            "boundary_bytes_sent": int(total_boundary_bytes),
            "intervention_msg_dropped_debounce": int(bus.intervention_msg_dropped_debounce),
            "intervention_msg_dropped_low_weight": int(bus.intervention_msg_dropped_low_weight),
            "fleet_task_engagement_fraction_so_far": float(fleet_task_engagement_time / sim_elapsed_s),
            "fleet_moving_fraction_so_far": float(fleet_moving_time / sim_elapsed_s),
            "fleet_idle_no_task_fraction_so_far": float(fleet_idle_no_task_time / sim_elapsed_s),
            "robot_task_utilization_mean": float(np.nanmean(list(robot_utilization_by_robot.values()))) if robot_utilization_by_robot else float("nan"),
            "robot_idle_fraction_mean": float(np.nanmean(list(robot_idle_fraction_by_robot.values()))) if robot_idle_fraction_by_robot else float("nan"),
            "robot_moving_with_task_fraction_mean": float(np.nanmean(list(robot_moving_with_task_fraction_by_robot.values()))) if robot_moving_with_task_fraction_by_robot else float("nan"),
            "robot_reactive_fraction_mean": float(np.nanmean(list(robot_reactive_fraction_by_robot.values()))) if robot_reactive_fraction_by_robot else float("nan"),
            "robot_predictive_fraction_mean": float(np.nanmean(list(robot_predictive_fraction_by_robot.values()))) if robot_predictive_fraction_by_robot else float("nan"),
            "robot_longest_idle_s_max": float(max(robot_idle_streak_max.values())) if robot_idle_streak_max else float("nan"),
            "robot_tail_idle_s_max": float(max(robot_idle_streak.values())) if robot_idle_streak else float("nan"),
            "robots_zero_distance_count": int(sum(1 for rid in travel_distance_by_robot if travel_distance_by_robot[rid] <= 1e-6)),
            "stale_goal_clears": int(stale_goal_clears),
            "direct_detection_task_refresh_active": int(direct_detection_task_refresh_active),
            "direct_detection_task_refresh_skipped_unassigned": int(direct_detection_task_refresh_skipped_unassigned),
            "direct_detection_task_refresh_skipped_eta": int(direct_detection_task_refresh_skipped_eta),
            "direct_detection_task_cluster_groups": int(direct_detection_task_cluster_groups),
            "direct_detection_task_cluster_merged": int(direct_detection_task_cluster_merged),
            "direct_detection_task_response_matches": int(direct_detection_task_response_matches),
            "preventive_policy": str(preventive_policy),
            "preventive_policy_source": str(preventive_policy_source),
            "selective_preventive_enabled": int(bool(selective_preventive_enabled)),
            "use_frozen_calibration": int(bool(use_frozen_calibration)),
            "selected_calibration_config_id": str(selected_calibration_config_id),
            "selected_calibration_source": str(selected_calibration_source),
            "calibrated_model_sigma": float(calibrated_model_sigma),
            "calibrated_model_omega": float(calibrated_model_omega),
            "calibrated_model_alpha_in": float(calibrated_model_alpha_in),
            "calibrated_model_alpha_cross": float(calibrated_model_alpha_cross),
            "calibrated_model_alpha_inhib": float(calibrated_model_alpha_inhib),
            "calibrated_model_omega_inhib": float(calibrated_model_omega_inhib),
            "calibrated_model_mu_base": float(calibrated_model_mu_base),
            "calibrated_model_bg_ema": float(calibrated_model_bg_ema),
            "calibrated_model_feedback_sigma_scale": float(calibrated_model_feedback_sigma_scale),
            "calibrated_model_feedback_omega_scale": float(calibrated_model_feedback_omega_scale),
            "selected_calibration_rank": _selected_calibration_metric("rank"),
            "selected_calibration_proposed_field_logloss_mean": _selected_calibration_metric("proposed_field_logloss_mean"),
            "selected_calibration_proposed_field_brier_mean": _selected_calibration_metric("proposed_field_brier_mean"),
            "selected_calibration_proposed_nll_mean": _selected_calibration_metric("proposed_nll_mean"),
            "selected_calibration_nll_improvement_pct_mean": _selected_calibration_metric("nll_improvement_pct_mean"),
            "model_deterring_gate_policy": str(model_deterring_gate_policy),
            "model_deterring_accepted": int(model_deterring_accepted),
            "model_deterring_rejected_budget": int(model_deterring_rejected_budget),
            "model_deterring_generated": int(diag_counts.get("model_deterring_generated", 0)),
            "model_deterring_candidates_total": int(diag_counts.get("model_deterring_candidates_total", 0)),
            "model_deterring_candidates_by_source": dict(model_deterring_candidate_source_counts),
            "model_deterring_generated_by_source": dict(model_deterring_generated_source_counts),
            "model_deterring_accepted_by_source": dict(model_deterring_accepted_source_counts),
            "model_deterring_rejected_cooldown": int(diag_counts.get("model_deterring_rejected_cooldown", 0)),
            "model_deterring_rejected_field": int(diag_counts.get("model_deterring_rejected_field", 0)),
            "model_deterring_pass_field": int(diag_counts.get("model_deterring_pass_field", 0)),
            "model_deterring_rejected_predicted_deltaJ": int(diag_counts.get("model_deterring_rejected_predicted_deltaJ", 0)),
            "model_deterring_pass_predicted_deltaJ": int(diag_counts.get("model_deterring_pass_predicted_deltaJ", 0)),
            "model_deterring_rejected_risk": int(diag_counts.get("model_deterring_rejected_risk", 0)),
            "model_deterring_pass_risk": int(diag_counts.get("model_deterring_pass_risk", 0)),
            "model_deterring_rejected_support": int(diag_counts.get("model_deterring_rejected_support", 0)),
            "model_deterring_rejected_persistence": int(diag_counts.get("model_deterring_rejected_persistence", 0)),
            "model_deterring_rejected_repeat_no_new_support": int(diag_counts.get("model_deterring_rejected_repeat_no_new_support", 0)),
            "model_deterring_rejected_eta": int(diag_counts.get("model_deterring_rejected_eta", 0)),
            "model_deterring_rejected_busy": int(diag_counts.get("model_deterring_rejected_busy", 0)),
            "model_deterring_rejected_margin": int(diag_counts.get("model_deterring_rejected_margin", 0)),
            "model_deterring_pass_support": int(diag_counts.get("model_deterring_pass_support", 0)),
            "model_deterring_pass_sprt": int(diag_counts.get("model_deterring_pass_sprt", 0)),
            "model_deterring_rejected_sprt_pending": int(diag_counts.get("model_deterring_rejected_sprt_pending", 0)),
            "model_deterring_rejected_sprt_negative": int(diag_counts.get("model_deterring_rejected_sprt_negative", 0)),
            "model_deterring_rejected_sprt_margin": int(diag_counts.get("model_deterring_rejected_sprt_margin", 0)),
            "model_deterring_pass_chance": int(diag_counts.get("model_deterring_pass_chance", 0)),
            "model_deterring_rejected_chance": int(diag_counts.get("model_deterring_rejected_chance", 0)),
            "model_deterring_pass_utility_ratio": int(diag_counts.get("model_deterring_pass_utility_ratio", 0)),
            "model_deterring_rejected_utility_ratio": int(diag_counts.get("model_deterring_rejected_utility_ratio", 0)),
            "model_deterring_pass_selection_weight": int(diag_counts.get("model_deterring_pass_selection_weight", 0)),
            "model_deterring_rejected_selection_weight": int(diag_counts.get("model_deterring_rejected_selection_weight", 0)),
            "model_deterring_pass_capacity": int(diag_counts.get("model_deterring_pass_capacity", 0)),
            "model_deterring_capacity_pending": int(diag_counts.get("model_deterring_capacity_pending", 0)),
            "model_deterring_rejected_capacity": int(diag_counts.get("model_deterring_rejected_capacity", 0)),
            "model_deterring_llr_mean": float(llr_mean),
            "model_deterring_llr_max": float(llr_max),
            "model_deterring_llr_p50": float(llr_p50),
            "model_deterring_llr_p75": float(llr_p75),
            "model_deterring_llr_p90": float(llr_p90),
            "model_deterring_p_event_mean": float(p_event_mean),
            "model_deterring_deltaJ_per_cost_mean": float(deltaJ_per_cost_mean),
            "model_deterring_cluster_key_total": int(diag_counts.get("model_deterring_cluster_key_total", 0)),
            "model_deterring_cluster_key_reused": int(diag_counts.get("model_deterring_cluster_key_reused", 0)),
            "model_deterring_cluster_key_churn": int(diag_counts.get("model_deterring_cluster_key_churn", 0)),
            "model_deterring_cluster_key_new": int(diag_counts.get("model_deterring_cluster_key_new", 0)),
            "model_deterring_not_selected": int(diag_counts.get("model_deterring_not_selected", 0)),
            "model_deterring_not_selected_by_source": dict(model_deterring_not_selected_source_counts),
            "model_deterring_rejected_budget_count_mode": int(model_deterring_rejected_budget_count_mode),
            "model_deterring_rejected_budget_utility_mode": int(model_deterring_rejected_budget_utility_mode),
            "model_deterring_budget_mode": str(model_deterring_budget_mode),
            "preventive_service_rate_per_robot_mean": float(preventive_service_rate_mean),
            "preventive_direct_arrival_rate_per_robot_mean": float(preventive_direct_arrival_rate_mean),
            "preventive_capacity_remaining_per_robot_mean": float(preventive_capacity_remaining_mean),
            "planner_rejected_unassigned": int(planner_rejected_unassigned),
            "planner_rejected_task_cap": int(planner_rejected_task_cap),
            "planner_rejected_patrol_cap": int(planner_rejected_patrol_cap),
            "planner_rejected_patrol_locked_model_det": int(planner_rejected_patrol_locked_model_det),
            "planner_rejected_model_det_cap": int(planner_rejected_model_det_cap),
            "planner_rejected_model_det_cycle_cap": int(planner_rejected_model_det_cycle_cap),
            "planner_rejected_model_det_busy_primary": int(planner_rejected_model_det_busy_primary),
            "planner_rejected_model_det_busy_fallback_quality": int(planner_rejected_model_det_busy_fallback_quality),
            "planner_rejected_model_det_direct_conflict": int(planner_rejected_model_det_direct_conflict),
            "planner_accepted_model_det_idle_primary": int(planner_accepted_model_det_idle_primary),
            "planner_accepted_model_det_busy_primary": int(planner_accepted_model_det_busy_primary),
            "planner_replaced_patrol": int(planner_replaced_patrol),
            "truth_candidate_events": int(truth_candidate_events),
            "truth_accepted_events": int(truth_accepted_events),
            "truth_suppressed_events": int(truth_suppressed_events),
            "truth_detection_opportunities": int(truth_detection_opportunities),
            "truth_detections_observed": int(truth_detections_observed),
            "truth_detections_missed_range": int(truth_detections_missed_range),
            "truth_detections_missed_false_negative": int(truth_detections_missed_false_negative),
            "truth_suppression_rate": (float(truth_suppressed_events) / float(truth_candidate_events)) if truth_candidate_events > 0 else float("nan"),
            "birds_deterred_pct": (100.0 * float(truth_suppressed_events) / float(truth_candidate_events)) if truth_candidate_events > 0 else float("nan"),
            **_current_truth_window_metrics(t),
            **_current_reactive_load_factor_metrics(t),
            "truth_suppression_effect_mean": (float(suppression_effect_sum) / float(truth_candidate_events)) if truth_candidate_events > 0 else float("nan"),
            "truth_suppression_effect_sum": float(suppression_effect_sum),
            **deterring_quality_cache,
            "forecast_recall_at_k": float(np.mean(forecast_recall_vals)) if forecast_recall_vals else float("nan"),
            "forecast_precision_at_k": float(np.mean(forecast_precision_vals)) if forecast_precision_vals else float("nan"),
            "forecast_lead_time_s": float(np.mean(forecast_lead_times)) if forecast_lead_times else float("nan"),
        }
        completed_this_step = completed_tasks[step_completed_before:]
        completed_patrolling_this_step = int(
            sum(
                1
                for tr in completed_this_step
                if task_action_kind(tr, deterring_modes, float(tau_service_s)) == "patrolling"
            )
        )
        completed_deterring_this_step = int(
            sum(
                1
                for tr in completed_this_step
                if task_action_kind(tr, deterring_modes, float(tau_service_s)) == "deterring"
            )
        )
        completed_stream_counts_this_step = _count_tasks_by_stream(completed_this_step)
        moving_distance_by_robot_step = {
            rid: float(
                math.hypot(
                    float(pose[rid][0]) - float(step_pose_before[rid][0]),
                    float(pose[rid][1]) - float(step_pose_before[rid][1]),
                )
            )
            for rid in pose
        }
        last_motion_execution_structured = MotionExecutionStageResult(
            now_t=float(t - t_report_offset),
            motion_orchestration_mode=str(motion_orchestration_mode),
            motion_execution_backend=str(motion_execution_backend),
            external_feedback_applied=bool(step_motion_feedback.applied),
            external_pose_updates_this_step=int(step_motion_feedback.updated_robot_count),
            robot_states=dict(robot_states_now),
            commands=list(motion_commands),
            moving_distance_by_robot_step=moving_distance_by_robot_step,
            goals_active_count=int(sum(1 for rid in goal if goal[rid] is not None)),
            dispatched_stream_counts_this_step=dict(step_dispatched_stream_counts),
            completed_stream_counts_this_step=dict(completed_stream_counts_this_step),
            completed_patrolling_this_step=completed_patrolling_this_step,
            completed_deterring_this_step=completed_deterring_this_step,
            stale_goal_clears_this_step=int(stale_goal_clears - step_stale_goal_clears_before),
            holding_robot_count=int(sum(1 for state in robot_states_now.values() if state == "holding")),
            moving_robot_count=int(sum(1 for state in robot_states_now.values() if state == "moving")),
            idle_robot_count=int(sum(1 for state in robot_states_now.values() if state == "idle")),
        )
        last_dispatch_structured.urgent_reactive_override_count = int(step_urgent_reactive_override_count)
        last_feedback_structured = FeedbackCommunicationStageResult(
            now_t=float(t - t_report_offset),
            recent_deterrence_events_added_this_step=int(len(recent_deterrences) - step_recent_deterrences_before),
            intervention_feedback_applied_this_step=int(step_intervention_feedback_applied),
            boundary_messages_sent_this_step=int(bus.boundary_msg_count - step_boundary_msg_before),
            intervention_messages_sent_this_step=int(bus.intervention_msg_count - step_intervention_msg_before),
            boundary_bytes_sent_this_step=int(bus.boundary_bytes - step_boundary_bytes_before),
            intervention_bytes_sent_this_step=int(bus.intervention_bytes - step_intervention_bytes_before),
            intervention_msg_dropped_debounce_this_step=int(
                bus.intervention_msg_dropped_debounce - step_drop_debounce_before
            ),
            intervention_msg_dropped_low_weight_this_step=int(
                bus.intervention_msg_dropped_low_weight - step_drop_low_weight_before
            ),
            truth_suppressed_events_total=int(truth_suppressed_events),
            truth_accepted_events_total=int(truth_accepted_events),
        )
        last_metrics_structured = MetricsStageResult(
            now_t=float(t - t_report_offset),
            dispatch_policy=str(dispatch_policy),
            reservation_fraction=float(reservation_fraction),
            reservation_softening_alpha=float(reservation_softening_alpha),
            reservation_age_softening_beta=float(reservation_age_softening_beta),
            reservation_age_gate=float(reservation_age_gate),
            predictive_slack_min_s=float(predictive_slack_min_s),
            reactive_pressure_max_for_predictive=float(reactive_pressure_max_for_predictive),
            predictive_confidence_min=float(predictive_confidence_min),
            predictive_deadline_weight=float(predictive_deadline_weight),
            predictive_eta_penalty_weight=float(predictive_eta_penalty_weight),
            predictive_utility_mode=str(predictive_utility_mode),
            predictive_confidence_source=str(predictive_confidence_source),
            predictive_confidence_power=float(predictive_confidence_power),
            predictive_time_score_deadline_scale_s=float(predictive_time_score_deadline_scale_s),
            predictive_time_score_reactive_pressure_weight=float(predictive_time_score_reactive_pressure_weight),
            predictive_time_score_infeasible_penalty=float(predictive_time_score_infeasible_penalty),
            predictive_utility_min=float(predictive_utility_min),
            predictive_cost_ratio_min=float(predictive_cost_ratio_min),
            predictive_opportunity_cost_weight=float(predictive_opportunity_cost_weight),
            predictive_eta_cost_weight=float(predictive_eta_cost_weight),
            predictive_service_cost_weight=float(predictive_service_cost_weight),
            risk_adjusted_reservation_alpha=float(risk_adjusted_reservation_alpha),
            risk_adjusted_reservation_beta=float(risk_adjusted_reservation_beta),
            predictive_timing_mode=str(predictive_timing_mode),
            predictive_expiry_grace_s=float(predictive_expiry_grace_s),
            predictive_selection_policy=str(predictive_selection_policy),
            habituation_eta_mean=float(final_metrics.get("habituation_eta_mean", float("nan"))),
            habituation_eta_min=float(final_metrics.get("habituation_eta_min", float("nan"))),
            habituation_eta_at_apply_mean=float(
                final_metrics.get("habituation_eta_at_apply_mean", float("nan"))
            ),
            habituation_variety_index=float(final_metrics.get("habituation_variety_index", float("nan"))),
            stl_robustness_global_mean=float(final_metrics.get("stl_robustness_global_mean", float("nan"))),
            stl_robustness_global_min=float(final_metrics.get("stl_robustness_global_min", float("nan"))),
            stl_robustness_exp=float(final_metrics.get("stl_robustness_exp", float("nan"))),
            stl_robustness_cov=float(final_metrics.get("stl_robustness_cov", float("nan"))),
            stl_robustness_hab=float(final_metrics.get("stl_robustness_hab", float("nan"))),
            predictive_planning_topology=str(predictive_planning_topology),
            zone_assignment_mode=str(zone_assignment_mode),
            defer_predictive_action_selection=int(bool(defer_predictive_action_selection)),
            assignment_switch_penalty=float(assignment_switch_penalty),
            value_weighted_exposure=float(final_metrics.get("value_weighted_exposure", float("nan"))),
            mean_response_time_s=float(final_metrics.get("mean_response_time_s", float("nan"))),
            completed_tasks_total=int(final_metrics.get("completed_tasks_total", 0)),
            reactive_generated_total=int(final_metrics.get("reactive_generated_total", 0)),
            predictive_generated_total=int(final_metrics.get("predictive_generated_total", 0)),
            predictive_distinct_generated_total=int(final_metrics.get("predictive_distinct_generated_total", 0)),
            reactive_admitted_total=int(final_metrics.get("reactive_admitted_total", 0)),
            predictive_admitted_total=int(final_metrics.get("predictive_admitted_total", 0)),
            predictive_distinct_admitted_total=int(final_metrics.get("predictive_distinct_admitted_total", 0)),
            reactive_dispatched_total=int(final_metrics.get("reactive_dispatched_total", 0)),
            predictive_dispatched_total=int(final_metrics.get("predictive_dispatched_total", 0)),
            reactive_completed_total=int(final_metrics.get("reactive_completed_total", 0)),
            predictive_completed_total=int(final_metrics.get("predictive_completed_total", 0)),
            predictive_distinct_completed_total=int(final_metrics.get("predictive_distinct_completed_total", 0)),
            reactive_completed_fraction=float(final_metrics.get("reactive_completed_fraction", float("nan"))),
            predictive_completed_fraction=float(final_metrics.get("predictive_completed_fraction", float("nan"))),
            predictive_expired_total=int(final_metrics.get("predictive_expired_total", 0)),
            predictive_expired_fraction=float(final_metrics.get("predictive_expired_fraction", float("nan"))),
            predictive_confidence_mean=float(final_metrics.get("predictive_confidence_mean", float("nan"))),
            predictive_confidence_completed_mean=float(
                final_metrics.get("predictive_confidence_completed_mean", float("nan"))
            ),
            predictive_expected_deltaJ_total=float(final_metrics.get("predictive_expected_deltaJ_total", 0.0)),
            predictive_raw_deltaJ_total=float(final_metrics.get("predictive_raw_deltaJ_total", 0.0)),
            predictive_completion_ratio=float(final_metrics.get("predictive_completion_ratio", float("nan"))),
            predictive_success_ratio=float(final_metrics.get("predictive_success_ratio", float("nan"))),
            predictive_false_positive_ratio=float(
                final_metrics.get("predictive_false_positive_ratio", float("nan"))
            ),
            predictive_success_proxy_evaluated_total=int(
                final_metrics.get("predictive_success_proxy_evaluated_total", 0)
            ),
            predictive_success_proxy_total=int(final_metrics.get("predictive_success_proxy_total", 0)),
            predictive_false_positive_proxy_total=int(
                final_metrics.get("predictive_false_positive_proxy_total", 0)
            ),
            centralized_global_opportunity_count_total=int(
                final_metrics.get("centralized_global_opportunity_count_total", 0)
            ),
            cross_zone_assignment_total=int(final_metrics.get("cross_zone_assignment_total", 0)),
            predictive_zone_bonus_mean=float(final_metrics.get("predictive_zone_bonus_mean", float("nan"))),
            reactive_load_factor_estimate=float(final_metrics.get("reactive_load_factor_estimate", float("nan"))),
            robot_idle_fraction_mean=float(final_metrics.get("robot_idle_fraction_mean", float("nan"))),
            robot_reactive_fraction_mean=float(final_metrics.get("robot_reactive_fraction_mean", float("nan"))),
            robot_predictive_fraction_mean=float(final_metrics.get("robot_predictive_fraction_mean", float("nan"))),
            urgent_reactive_override_total=int(final_metrics.get("urgent_reactive_override_total", 0)),
            predictive_deadline_feasible_total=int(final_metrics.get("predictive_deadline_feasible_total", 0)),
            predictive_deadline_checked_total=int(final_metrics.get("predictive_deadline_checked_total", 0)),
            predictive_deadline_feasible_fraction=float(
                final_metrics.get("predictive_deadline_feasible_fraction", float("nan"))
            ),
            boundary_message_count=int(final_metrics.get("boundary_message_count", 0)),
            boundary_bytes_sent=int(final_metrics.get("boundary_bytes_sent", 0)),
            fleet_task_engagement_fraction_so_far=float(
                final_metrics.get("fleet_task_engagement_fraction_so_far", float("nan"))
            ),
            fleet_moving_fraction_so_far=float(final_metrics.get("fleet_moving_fraction_so_far", float("nan"))),
            fleet_idle_no_task_fraction_so_far=float(
                final_metrics.get("fleet_idle_no_task_fraction_so_far", float("nan"))
            ),
            truth_suppression_rate=float(final_metrics.get("truth_suppression_rate", float("nan"))),
            birds_deterred_pct=float(final_metrics.get("birds_deterred_pct", float("nan"))),
            truth_suppression_rate_last_hour=float(final_metrics.get("truth_suppression_rate_last_hour", float("nan"))),
            birds_deterred_pct_last_hour=float(final_metrics.get("birds_deterred_pct_last_hour", float("nan"))),
            forecast_recall_at_k=float(final_metrics.get("forecast_recall_at_k", float("nan"))),
            forecast_precision_at_k=float(final_metrics.get("forecast_precision_at_k", float("nan"))),
        )
        last_truth_generation_structured = build_truth_generation_stage_result(
            now_t=float(t - t_report_offset),
            use_ground_truth=use_ground_truth,
            recent_truth_count=len(recent_truth),
            recent_truth_before=step_recent_truth_before,
            recent_detections_count=len(recent_detections),
            recent_detections_before=step_recent_detections_before,
            truth_candidate_events=truth_candidate_events,
            truth_candidate_before=step_truth_candidate_before,
            truth_accepted_events=truth_accepted_events,
            truth_accepted_before=step_truth_accepted_before,
            truth_suppressed_events=truth_suppressed_events,
            truth_suppressed_before=step_truth_suppressed_before,
            suppression_effect_sum=suppression_effect_sum,
        )
        last_forecast_model_structured = build_forecast_model_stage_result(
            now_t=float(t - t_report_offset),
            model_advance_dt_s=dt,
            model_diag=model_diag,
            forecast_step=step_forecast,
            forecast_samples_total=len(forecast_precision_vals),
        )
        last_telemetry_structured = build_telemetry_stage_result(
            now_t=float(t - t_report_offset),
            telemetry_enabled=bool(mon is not None and getattr(mon, "enabled", False)),
            telemetry_step=step_telemetry,
            telemetry_dir=telemetry_dir,
        )
        demo_tracking_links = _build_demo_tracking_links(
            active_tasks=active_tasks,
            motion_commands=motion_commands,
        )
        tracking_state = None
        if bool(emit_tracking_state):
            tracking_runtime_state = {
                "robots": robots,
                "profiles": profiles,
                "pose": pose,
                "goal": goal,
                "cells": cells,
                "active_tasks": active_tasks,
                "completed_tasks": completed_tasks,
                "recent_truth": recent_truth,
                "recent_detections": recent_detections,
                "recent_deterrences": recent_deterrences,
                "truth_pts": truth_pts,
                "det_pts": det_pts,
                "taskgen": taskgen,
                "assigner": assigner,
                "bus": bus,
                "service_history_by_robot": service_history_by_robot,
                "preventive_service_rate_snapshot": preventive_service_rate_snapshot,
                "preventive_direct_arrival_rate_snapshot": preventive_direct_arrival_rate_snapshot,
                "preventive_capacity_remaining_snapshot": preventive_capacity_remaining_snapshot,
                "preventive_capacity_ready_snapshot": preventive_capacity_ready_snapshot,
                "travel_distance_by_robot": travel_distance_by_robot,
                "energy_by_robot": energy_by_robot,
                "robot_time_total": robot_time_total,
                "robot_time_with_task": robot_time_with_task,
                "robot_time_moving": robot_time_moving,
                "robot_time_holding": robot_time_holding,
                "robot_time_idle": robot_time_idle,
                "robot_idle_streak": robot_idle_streak,
                "robot_idle_streak_max": robot_idle_streak_max,
                "fleet_task_engagement_time": fleet_task_engagement_time,
                "fleet_moving_time": fleet_moving_time,
                "fleet_idle_no_task_time": fleet_idle_no_task_time,
                "completed_count_by_type": completed_count_by_type,
                "response_times": response_times,
                "truth_candidate_events": truth_candidate_events,
                "truth_accepted_events": truth_accepted_events,
                "truth_suppressed_events": truth_suppressed_events,
                "truth_detection_opportunities": truth_detection_opportunities,
                "truth_detections_observed": truth_detections_observed,
                "truth_detections_missed_range": truth_detections_missed_range,
                "truth_detections_missed_false_negative": truth_detections_missed_false_negative,
                "suppression_effect_sum": suppression_effect_sum,
                "forecast_recall_vals": forecast_recall_vals,
                "forecast_precision_vals": forecast_precision_vals,
                "forecast_lead_times": forecast_lead_times,
                "model_diag": model_diag,
                "motion_commands": motion_commands,
                "graph_motion_states": {
                    str(robot_id): state.to_public_dict()
                    for robot_id, state in graph_motion_states.items()
                },
                "graph_reservations": graph_reservations_snapshot.to_public_dict(),
                "metrics": metrics,
                "metrics_compact": final_metrics,
                "task_generation_structured": last_task_generation_structured,
                "dispatch_structured": last_dispatch_structured,
                "motion_execution_structured": last_motion_execution_structured,
                "feedback_structured": last_feedback_structured,
                "metrics_structured": last_metrics_structured,
                "truth_generation_structured": last_truth_generation_structured,
                "forecast_model_structured": last_forecast_model_structured,
                "telemetry_structured": last_telemetry_structured,
            }
            raw_tracking_locals = dict(locals())
            tracking_state = {
                "demo_links": demo_tracking_links,
                "runtime_state": export_named_tracking_state(
                    tracking_runtime_state,
                    include_arrays=bool(tracking_include_arrays),
                    max_items=int(tracking_preview_limit),
                ),
            }
            if bool(tracking_capture_frame_locals):
                tracking_state["frame_locals"] = export_named_tracking_state(
                    raw_tracking_locals,
                    include_arrays=bool(tracking_include_arrays),
                    max_items=int(tracking_preview_limit),
                    skip_names={
                        "raw_tracking_locals",
                        "tracking_state",
                        "tracking_runtime_state",
                    },
                )
        system_state_structured = build_production_runtime_snapshot(
            sim_time_s=(t - t_report_offset),
            poses={rid: tuple(pose[rid]) for rid in pose},
            goals={rid: (None if goal[rid] is None else tuple(goal[rid])) for rid in goal},
            robot_states=robot_states_now,
            active_tasks=active_tasks,
            completed_tasks=completed_tasks,
            truth_pts_count=len(truth_pts),
            det_pts_count=len(det_pts),
            boundary_message_count=total_boundary_msgs,
            boundary_bytes_sent=total_boundary_bytes,
            metrics_compact=final_metrics,
            tracking=tracking_state,
        )
        planning_diagnostics = None
        if bool(emit_planning_diagnostics):
            planning_diagnostics = {
                "global_hotspots": [
                    {"x": float(x), "y": float(y), "score": float(score)}
                    for x, y, score in _global_hotspots(int(planning_hotspot_top_k))
                ],
                "patrol_candidates": _compact_task_rows(
                    last_task_generation_structured.candidate_tasks,
                    task_type="patrolling",
                    limit=int(planning_candidate_limit),
                ),
                "model_deterring_candidates": _compact_task_rows(
                    last_task_generation_structured.candidate_tasks,
                    task_type="deterring",
                    limit=int(planning_candidate_limit),
                ),
                "model_deterring_candidate_counts_by_source": _count_task_rows_by_origin(
                    last_task_generation_structured.candidate_tasks,
                    task_type="deterring",
                ),
                "accepted_patrol_tasks": _compact_task_rows(
                    last_dispatch_structured.accepted_tasks,
                    task_type="patrolling",
                    limit=int(planning_candidate_limit),
                ),
                "accepted_deterring_tasks": _compact_task_rows(
                    last_dispatch_structured.accepted_tasks,
                    task_type="deterring",
                    limit=int(planning_candidate_limit),
                ),
                "accepted_deterring_counts_by_source": _count_task_rows_by_origin(
                    last_dispatch_structured.accepted_tasks,
                    task_type="deterring",
                ),
            }
        yield {
            "t": (t - t_report_offset),
            "W": W, "H": H, "boundary": boundary,
            "cells": list(cells),
            "poses": {rid: tuple(pose[rid]) for rid in pose},
            "robot_states": robot_states_now,
            "robot_goals": {rid: (None if goal[rid] is None else tuple(goal[rid])) for rid in goal},
            "profiles": profiles,
            "truth_pts": truth_pts,
            "det_pts": det_pts,
            "metrics": metrics,
            "metrics_compact": final_metrics,
            "model_diag": model_diag,
            "tasks_active": list(active_tasks),
            "tasks_done": list(completed_tasks),
            "motion_commands": [cmd.to_public_dict() for cmd in motion_commands],
            "motion_graph_states": {
                str(robot_id): state.to_public_dict()
                for robot_id, state in graph_motion_states.items()
            },
            "motion_graph_reservations": graph_reservations_snapshot.to_public_dict(),
            "system_config_structured": (
                system_config_structured.to_dict() if emit_structured_config_once else None
            ),
            "system_state_structured": system_state_structured.to_dict(),
            "task_generation_structured": last_task_generation_structured.to_public_dict(),
            "dispatch_structured": last_dispatch_structured.to_public_dict(),
            "motion_execution_structured": last_motion_execution_structured.to_public_dict(),
            "feedback_structured": last_feedback_structured.to_public_dict(),
            "metrics_structured": last_metrics_structured.to_public_dict(),
            "truth_generation_structured": last_truth_generation_structured.to_public_dict(),
            "forecast_model_structured": last_forecast_model_structured.to_public_dict(),
            "telemetry_structured": last_telemetry_structured.to_public_dict(),
            "tracking_state": tracking_state,
            "planning_diagnostics": planning_diagnostics,
        }
        emit_structured_config_once = False

        t += dt

    # ------------------------------------------------------------------------
    # End-of-run reporting
    # ------------------------------------------------------------------------
    if report_metrics_end:
        mrt = float(np.mean(response_times)) if response_times else float("nan")
        total_distance = float(sum(travel_distance_by_robot.values()))
        total_completed = int(completed_count_by_type["deterring"] + completed_count_by_type["patrolling"])
        total_boundary_msgs = int(bus.boundary_msg_count + bus.intervention_msg_count)
        total_boundary_bytes = int(bus.boundary_bytes + bus.intervention_bytes)
        sim_elapsed_s = max([float(v) for v in robot_time_total.values()] + [1e-9])
        print(
            "[run metrics] "
            f"Jexp={float(value_weighted_exposure):.3f} "
            f"resp_s={mrt:.3f} "
            f"tasks={total_completed} "
            f"dist={total_distance:.3f} "
            f"engage={float(fleet_task_engagement_time / max(sim_elapsed_s, 1e-9)):.3f} "
            f"idle_no_task={float(fleet_idle_no_task_time / max(sim_elapsed_s, 1e-9)):.3f} "
            f"truth_suppr={float(truth_suppressed_events) / float(max(truth_candidate_events, 1)):.3f} "
            f"birds_deterred_pct_last_hour={float(final_metrics.get('birds_deterred_pct_last_hour', float('nan'))):.2f} "
            f"msgs={total_boundary_msgs} "
            f"bytes={total_boundary_bytes}"
        )


# ============================================================================
# Experiment and reporting entrypoints
# ============================================================================

def run_metrics_experiments(
    num_runs=10,
    seed_start=123,
    report_each_run=True,
    progress_cb=None,
    collect_time_metrics=True,
    time_metrics_period_s=900.0,
    time_metrics_fields=None,
    **sim_kwargs,
):
    """
    Run multiple randomized simulations and report mean/variance metrics.
    """
    run_metrics = []
    run_time_series = []
    if time_metrics_fields is None:
        time_metrics_fields = [
            "reservation_fraction",
            "value_weighted_exposure",
            "completed_tasks_total",
            "boundary_message_count",
            "model_deterring_accepted",
            "model_deterring_generated",
            "model_deterring_rejected_budget",
            "reactive_generated_total",
            "predictive_generated_total",
            "reactive_admitted_total",
            "predictive_admitted_total",
            "reactive_dispatched_total",
            "predictive_dispatched_total",
            "reactive_completed_total",
            "predictive_completed_total",
            "reactive_completed_fraction",
            "predictive_completed_fraction",
            "predictive_confidence_mean",
            "predictive_confidence_completed_mean",
            "predictive_expected_deltaJ_total",
            "predictive_raw_deltaJ_total",
            "predictive_completion_ratio",
            "predictive_success_ratio",
            "predictive_false_positive_ratio",
            "predictive_deadline_feasible_fraction",
            "predictive_risk_adjusted_candidates_total",
            "predictive_risk_adjusted_rejected_confidence_total",
            "predictive_risk_adjusted_rejected_slack_total",
            "predictive_risk_adjusted_rejected_utility_total",
            "predictive_risk_adjusted_rejected_cost_ratio_total",
            "predictive_risk_adjusted_mean_confidence",
            "predictive_risk_adjusted_mean_utility",
            "predictive_risk_adjusted_rho_eff",
            "predictive_risk_adjusted_reactive_pressure",
            "predictive_risk_adjusted_reactive_age_norm",
            "reactive_load_factor_estimate",
            "reactive_load_factor_truth",
            "reactive_load_factor_observable",
            "reactive_load_factor_observed",
            "reactive_load_window_truth_accepted_events",
            "reactive_load_window_detections_observed",
            "urgent_reactive_override_total",
            "truth_candidate_events",
            "truth_suppressed_events",
            "truth_suppression_rate",
            "truth_suppression_rate_last_hour",
            "birds_deterred_pct",
            "birds_deterred_pct_last_hour",
            "truth_suppression_effect_mean",
            "fleet_task_assigned_fraction",
            "fleet_moving_fraction",
            "fleet_idle_no_task_fraction",
            "fleet_task_engagement_fraction_so_far",
            "robot_task_utilization_mean",
            "robot_idle_fraction_mean",
            "robot_reactive_fraction_mean",
            "robot_predictive_fraction_mean",
        ]

    def _sample_time_metrics(snap):
        """Extract the configured time-series metrics from a frame snapshot."""
        m = snap.get("metrics", {})
        t_s = float(snap.get("t", 0.0))
        row = {"t_s": t_s}
        for k in time_metrics_fields:
            value = m.get(k, np.nan)
            try:
                row[k] = float(value)
            except Exception:
                row[k] = value
        if t_s > 0.0:
            row["exposure_rate_per_hour_so_far"] = float(m.get("value_weighted_exposure", np.nan)) / (t_s / 3600.0)
            row["tasks_per_hour_so_far"] = float(m.get("completed_tasks_total", np.nan)) / (t_s / 3600.0)
        else:
            row["exposure_rate_per_hour_so_far"] = float("nan")
            row["tasks_per_hour_so_far"] = float("nan")
        return row
    for i in range(int(num_runs)):
        seed = int(seed_start) + i
        frames = run_simulation_frames_persistent(seed=seed, **sim_kwargs)
        last = None
        per_run_series = []
        next_time_sample_s = 0.0
        for snap in frames:
            last = snap
            if collect_time_metrics:
                t_s = float(snap.get("t", 0.0))
                if t_s + 1e-9 >= next_time_sample_s:
                    per_run_series.append(_sample_time_metrics(snap))
                    next_time_sample_s += float(time_metrics_period_s)
        if last is not None and "metrics" in last:
            m = last["metrics"]
            run_metrics.append(m)
            if collect_time_metrics:
                run_time_series.append(per_run_series)
            if report_each_run:
                mrt = m.get("mean_response_time_s", float("nan"))
                print(
                    f"[run {i+1}/{int(num_runs)} seed={seed}] "
                    f"Jexp={m.get('value_weighted_exposure', float('nan')):.3f} "
                    f"resp_s={mrt:.3f} "
                    f"tasks={m.get('completed_tasks_total', 0)} "
                    f"dist={sum(m.get('travel_distance_by_robot', {}).values()):.3f} "
                    f"msgs={m.get('boundary_message_count', 0)} "
                    f"bytes={m.get('boundary_bytes_sent', 0)}"
                )
            if progress_cb is not None:
                try:
                    progress_cb(i + 1, int(num_runs), seed, m)
                except Exception:
                    pass

    if not run_metrics:
        return {"num_runs": 0, "runs": [], "summary": {}, "time_summary": []}

    def _arr(key):
        """Convert a collected metric series into a finite numeric array."""
        return np.array([m.get(key, np.nan) for m in run_metrics], dtype=float)

    def _safe_stats(key):
        """Compute robust summary statistics for one collected metric series."""
        a = _arr(key)
        a = a[np.isfinite(a)]
        if a.size == 0:
            return {"mean": float("nan"), "var": float("nan")}
        return {"mean": float(np.mean(a)), "var": float(np.var(a))}

    summary = {
        "value_weighted_exposure": _safe_stats("value_weighted_exposure"),
        "mean_response_time_s": _safe_stats("mean_response_time_s"),
        "tasks_per_unit_distance": _safe_stats("tasks_per_unit_distance"),
        "exposure_per_completed_task": _safe_stats("exposure_per_completed_task"),
        "boundary_message_count": _safe_stats("boundary_message_count"),
        "boundary_bytes_sent": _safe_stats("boundary_bytes_sent"),
        "selective_preventive_enabled": _safe_stats("selective_preventive_enabled"),
        "use_frozen_calibration": _safe_stats("use_frozen_calibration"),
        "calibrated_model_sigma": _safe_stats("calibrated_model_sigma"),
        "calibrated_model_omega": _safe_stats("calibrated_model_omega"),
        "calibrated_model_alpha_in": _safe_stats("calibrated_model_alpha_in"),
        "calibrated_model_alpha_cross": _safe_stats("calibrated_model_alpha_cross"),
        "calibrated_model_alpha_inhib": _safe_stats("calibrated_model_alpha_inhib"),
        "calibrated_model_omega_inhib": _safe_stats("calibrated_model_omega_inhib"),
        "calibrated_model_mu_base": _safe_stats("calibrated_model_mu_base"),
        "calibrated_model_bg_ema": _safe_stats("calibrated_model_bg_ema"),
        "calibrated_model_feedback_sigma_scale": _safe_stats("calibrated_model_feedback_sigma_scale"),
        "calibrated_model_feedback_omega_scale": _safe_stats("calibrated_model_feedback_omega_scale"),
        "selected_calibration_rank": _safe_stats("selected_calibration_rank"),
        "selected_calibration_proposed_field_logloss_mean": _safe_stats("selected_calibration_proposed_field_logloss_mean"),
        "selected_calibration_proposed_field_brier_mean": _safe_stats("selected_calibration_proposed_field_brier_mean"),
        "selected_calibration_proposed_nll_mean": _safe_stats("selected_calibration_proposed_nll_mean"),
        "selected_calibration_nll_improvement_pct_mean": _safe_stats("selected_calibration_nll_improvement_pct_mean"),
        "intervention_msg_dropped_debounce": _safe_stats("intervention_msg_dropped_debounce"),
        "intervention_msg_dropped_low_weight": _safe_stats("intervention_msg_dropped_low_weight"),
        "forecast_recall_at_k": _safe_stats("forecast_recall_at_k"),
        "forecast_precision_at_k": _safe_stats("forecast_precision_at_k"),
        "forecast_lead_time_s": _safe_stats("forecast_lead_time_s"),
        "forecast_hotspot_hit_rate": _safe_stats("forecast_hotspot_hit_rate"),
        "model_deterring_accepted": _safe_stats("model_deterring_accepted"),
        "model_deterring_generated": _safe_stats("model_deterring_generated"),
        "reactive_generated_total": _safe_stats("reactive_generated_total"),
        "predictive_generated_total": _safe_stats("predictive_generated_total"),
        "predictive_distinct_generated_total": _safe_stats("predictive_distinct_generated_total"),
        "reactive_admitted_total": _safe_stats("reactive_admitted_total"),
        "predictive_admitted_total": _safe_stats("predictive_admitted_total"),
        "predictive_distinct_admitted_total": _safe_stats("predictive_distinct_admitted_total"),
        "reactive_dispatched_total": _safe_stats("reactive_dispatched_total"),
        "predictive_dispatched_total": _safe_stats("predictive_dispatched_total"),
        "reactive_completed_total": _safe_stats("reactive_completed_total"),
        "predictive_completed_total": _safe_stats("predictive_completed_total"),
        "predictive_distinct_completed_total": _safe_stats("predictive_distinct_completed_total"),
        "reactive_completed_fraction": _safe_stats("reactive_completed_fraction"),
        "predictive_completed_fraction": _safe_stats("predictive_completed_fraction"),
        "predictive_expired_total": _safe_stats("predictive_expired_total"),
        "predictive_expired_fraction": _safe_stats("predictive_expired_fraction"),
        "predictive_deadline_feasible_fraction": _safe_stats("predictive_deadline_feasible_fraction"),
        "reactive_load_factor_estimate": _safe_stats("reactive_load_factor_estimate"),
        "reactive_load_factor_window_s": _safe_stats("reactive_load_factor_window_s"),
        "reactive_load_factor_nominal_service_s": _safe_stats("reactive_load_factor_nominal_service_s"),
        "reactive_load_factor_truth_candidate": _safe_stats("reactive_load_factor_truth_candidate"),
        "reactive_load_factor_truth": _safe_stats("reactive_load_factor_truth"),
        "reactive_load_factor_observable": _safe_stats("reactive_load_factor_observable"),
        "reactive_load_factor_observed": _safe_stats("reactive_load_factor_observed"),
        "reactive_load_window_truth_candidate_events": _safe_stats("reactive_load_window_truth_candidate_events"),
            "reactive_load_window_truth_accepted_events": _safe_stats("reactive_load_window_truth_accepted_events"),
            "reactive_load_window_detection_opportunities": _safe_stats("reactive_load_window_detection_opportunities"),
            "reactive_load_window_detections_in_range": _safe_stats("reactive_load_window_detections_in_range"),
            "reactive_load_window_detections_observed": _safe_stats("reactive_load_window_detections_observed"),
        "urgent_reactive_override_total": _safe_stats("urgent_reactive_override_total"),
        "model_deterring_candidates_total": _safe_stats("model_deterring_candidates_total"),
        "model_deterring_rejected_cooldown": _safe_stats("model_deterring_rejected_cooldown"),
        "model_deterring_rejected_field": _safe_stats("model_deterring_rejected_field"),
        "model_deterring_pass_field": _safe_stats("model_deterring_pass_field"),
        "model_deterring_rejected_predicted_deltaJ": _safe_stats("model_deterring_rejected_predicted_deltaJ"),
        "model_deterring_pass_predicted_deltaJ": _safe_stats("model_deterring_pass_predicted_deltaJ"),
        "model_deterring_pass_risk": _safe_stats("model_deterring_pass_risk"),
        "model_deterring_pass_support": _safe_stats("model_deterring_pass_support"),
        "model_deterring_not_selected": _safe_stats("model_deterring_not_selected"),
        "model_deterring_rejected_budget": _safe_stats("model_deterring_rejected_budget"),
        "model_deterring_rejected_budget_count_mode": _safe_stats("model_deterring_rejected_budget_count_mode"),
        "model_deterring_rejected_budget_utility_mode": _safe_stats("model_deterring_rejected_budget_utility_mode"),
        "model_deterring_rejected_risk": _safe_stats("model_deterring_rejected_risk"),
        "model_deterring_rejected_support": _safe_stats("model_deterring_rejected_support"),
        "model_deterring_rejected_persistence": _safe_stats("model_deterring_rejected_persistence"),
        "model_deterring_rejected_repeat_no_new_support": _safe_stats("model_deterring_rejected_repeat_no_new_support"),
        "model_deterring_rejected_eta": _safe_stats("model_deterring_rejected_eta"),
        "model_deterring_rejected_busy": _safe_stats("model_deterring_rejected_busy"),
        "model_deterring_rejected_margin": _safe_stats("model_deterring_rejected_margin"),
        "model_deterring_rejected_sprt_margin": _safe_stats("model_deterring_rejected_sprt_margin"),
        "model_deterring_pass_selection_weight": _safe_stats("model_deterring_pass_selection_weight"),
        "model_deterring_rejected_selection_weight": _safe_stats("model_deterring_rejected_selection_weight"),
        "model_deterring_capacity_pending": _safe_stats("model_deterring_capacity_pending"),
        "planner_rejected_unassigned": _safe_stats("planner_rejected_unassigned"),
        "planner_rejected_task_cap": _safe_stats("planner_rejected_task_cap"),
        "planner_rejected_patrol_cap": _safe_stats("planner_rejected_patrol_cap"),
        "planner_rejected_patrol_locked_model_det": _safe_stats("planner_rejected_patrol_locked_model_det"),
        "planner_rejected_model_det_cap": _safe_stats("planner_rejected_model_det_cap"),
        "planner_rejected_model_det_cycle_cap": _safe_stats("planner_rejected_model_det_cycle_cap"),
        "planner_rejected_model_det_busy_primary": _safe_stats("planner_rejected_model_det_busy_primary"),
        "planner_rejected_model_det_busy_fallback_quality": _safe_stats("planner_rejected_model_det_busy_fallback_quality"),
        "planner_rejected_model_det_direct_conflict": _safe_stats("planner_rejected_model_det_direct_conflict"),
        "planner_accepted_model_det_idle_primary": _safe_stats("planner_accepted_model_det_idle_primary"),
        "planner_accepted_model_det_busy_primary": _safe_stats("planner_accepted_model_det_busy_primary"),
        "planner_replaced_patrol": _safe_stats("planner_replaced_patrol"),
        "truth_candidate_events": _safe_stats("truth_candidate_events"),
        "truth_accepted_events": _safe_stats("truth_accepted_events"),
        "truth_suppressed_events": _safe_stats("truth_suppressed_events"),
        "truth_detection_opportunities": _safe_stats("truth_detection_opportunities"),
        "truth_detections_observed": _safe_stats("truth_detections_observed"),
        "truth_detections_missed_range": _safe_stats("truth_detections_missed_range"),
        "truth_detections_missed_false_negative": _safe_stats("truth_detections_missed_false_negative"),
        "truth_suppression_rate": _safe_stats("truth_suppression_rate"),
        "truth_suppression_rate_last_hour": _safe_stats("truth_suppression_rate_last_hour"),
        "birds_deterred_pct": _safe_stats("birds_deterred_pct"),
        "birds_deterred_pct_last_hour": _safe_stats("birds_deterred_pct_last_hour"),
        "truth_suppression_effect_mean": _safe_stats("truth_suppression_effect_mean"),
        "truth_suppression_effect_sum": _safe_stats("truth_suppression_effect_sum"),
        "deterring_actions_completed_total": _safe_stats("deterring_actions_completed_total"),
        "deterring_actions_completed_direct_detection": _safe_stats("deterring_actions_completed_direct_detection"),
        "deterring_actions_completed_model_scored": _safe_stats("deterring_actions_completed_model_scored"),
        "deterring_action_precision": _safe_stats("deterring_action_precision"),
        "deterring_action_precision_direct_detection": _safe_stats("deterring_action_precision_direct_detection"),
        "deterring_action_precision_model_scored": _safe_stats("deterring_action_precision_model_scored"),
        "suppression_per_deterring_action": _safe_stats("suppression_per_deterring_action"),
        "suppression_per_direct_deterring_action": _safe_stats("suppression_per_direct_deterring_action"),
        "suppression_per_model_deterring_action": _safe_stats("suppression_per_model_deterring_action"),
        "model_vs_direct_suppression_yield_ratio": _safe_stats("model_vs_direct_suppression_yield_ratio"),
        "fleet_task_engagement_fraction_so_far": _safe_stats("fleet_task_engagement_fraction_so_far"),
        "fleet_moving_fraction_so_far": _safe_stats("fleet_moving_fraction_so_far"),
        "fleet_idle_no_task_fraction_so_far": _safe_stats("fleet_idle_no_task_fraction_so_far"),
        "robot_task_utilization_mean": _safe_stats("robot_task_utilization_mean"),
        "robot_idle_fraction_mean": _safe_stats("robot_idle_fraction_mean"),
        "robot_reactive_fraction_mean": _safe_stats("robot_reactive_fraction_mean"),
        "robot_predictive_fraction_mean": _safe_stats("robot_predictive_fraction_mean"),
        "robot_moving_with_task_fraction_mean": _safe_stats("robot_moving_with_task_fraction_mean"),
        "robot_longest_idle_s_max": _safe_stats("robot_longest_idle_s_max"),
        "robot_tail_idle_s_max": _safe_stats("robot_tail_idle_s_max"),
        "robots_zero_distance_count": _safe_stats("robots_zero_distance_count"),
        "stale_goal_clears": _safe_stats("stale_goal_clears"),
    }

    time_summary = []
    if collect_time_metrics and run_time_series:
        t_buckets = {}
        for series in run_time_series:
            for row in series:
                t_key = int(round(float(row.get("t_s", 0.0))))
                if t_key not in t_buckets:
                    t_buckets[t_key] = {}
                for k, v in row.items():
                    if k == "t_s":
                        continue
                    if np.isfinite(v):
                        t_buckets[t_key].setdefault(k, []).append(float(v))
        for t_key in sorted(t_buckets.keys()):
            out = {"t_s": float(t_key)}
            for k, vals in t_buckets[t_key].items():
                arr = np.array(vals, dtype=float)
                out[f"{k}_mean"] = float(np.mean(arr)) if arr.size else float("nan")
                out[f"{k}_var"] = float(np.var(arr)) if arr.size else float("nan")
            time_summary.append(out)

    def _uniform_run_value(key, default=""):
        """Return a configuration value only when it is uniform across all runs."""
        values = [m.get(key, default) for m in run_metrics if key in m]
        if not values:
            return default
        first = values[0]
        return first if all(v == first for v in values[1:]) else default

    return {
        "num_runs": len(run_metrics),
        "runs": run_metrics,
        "summary": summary,
        "time_summary": time_summary,
        "config_summary": {
            "dispatch_policy": str(_uniform_run_value("dispatch_policy", "")),
            "reservation_fraction": _uniform_run_value("reservation_fraction", float("nan")),
            "reservation_window_s": _uniform_run_value("reservation_window_s", float("nan")),
            "reactive_override_slack_s": _uniform_run_value("reactive_override_slack_s", float("nan")),
            "reservation_softening_alpha": _uniform_run_value("reservation_softening_alpha", float("nan")),
            "reservation_age_softening_beta": _uniform_run_value("reservation_age_softening_beta", float("nan")),
            "reservation_age_gate": _uniform_run_value("reservation_age_gate", float("nan")),
            "tau_service_s": _uniform_run_value("tau_service_s", float("nan")),
            "predictive_selection_policy": str(_uniform_run_value("predictive_selection_policy", "")),
            "preventive_policy": str(_uniform_run_value("preventive_policy", "")),
            "preventive_policy_source": str(_uniform_run_value("preventive_policy_source", "")),
            "selected_calibration_config_id": str(_uniform_run_value("selected_calibration_config_id", "")),
            "selected_calibration_source": str(_uniform_run_value("selected_calibration_source", "")),
        },
    }


# ============================================================================
# Baseline comparison entrypoint
# ============================================================================

def run_baseline_suite(
    num_runs=10,
    seed_start=123,
    report_each_run=True,
    csv_path=None,
    progress_cb=None,
    collect_time_metrics=True,
    time_metrics_period_s=900.0,
    proposed_enable_model_scored_deterring=None,
    proposed_enable_intervention_feedback=None,
    use_frozen_calibration=False,
    calibration_ranking_path=None,
    calibration_manifest_path=None,
    calibration_config_id=None,
    proposed_preventive_policy=None,
    **sim_kwargs,
):
    """
    Run and compare baseline families:
    - reactive: detections only, no predictive patrol, no intervention feedback
    - prediction_only: predictive patrol enabled, no intervention feedback, and no model-scored preventive deterring
    - proposed: predictive patrol + intervention feedback + model-scored preventive deterring
    Returns per-baseline full results plus a flattened comparison table.
    """
    baseline_cfgs = {
        "reactive": {
            "simulation_mode": "reactive",
            "enable_patrolling": False,
            "enable_intervention_feedback": False,
            "include_fallback_patrol": False,
            "enable_model_scored_deterring": False,
        },
        "prediction_only": {
            "simulation_mode": "prediction_only",
            "enable_patrolling": True,
            "enable_intervention_feedback": False,
            "include_fallback_patrol": True,
            "enable_model_scored_deterring": False,
        },
        "proposed": {
            "simulation_mode": "proposed",
            "enable_patrolling": True,
            "enable_intervention_feedback": True,
            "include_fallback_patrol": True,
            "enable_model_scored_deterring": True,
        },
    }
    if proposed_enable_model_scored_deterring is not None:
        baseline_cfgs["proposed"]["enable_model_scored_deterring"] = bool(
            proposed_enable_model_scored_deterring
        )
    if proposed_enable_intervention_feedback is not None:
        baseline_cfgs["proposed"]["enable_intervention_feedback"] = bool(
            proposed_enable_intervention_feedback
        )

    all_results = {}
    rows = []
    time_rows = []
    baseline_names = list(baseline_cfgs.keys())
    total_runs_all = int(num_runs) * len(baseline_names)
    runs_done_all = 0
    proposed_only_keys = {
        "preventive_policy",
        "use_frozen_calibration",
        "calibration_ranking_path",
        "calibration_manifest_path",
        "calibration_config_id",
    }
    shared_sim_kwargs = {k: v for k, v in sim_kwargs.items() if k not in proposed_only_keys}

    def _uniform_run_value(run_list, key, default=""):
        """Return a configuration value only when it is uniform across all runs."""
        values = [m.get(key, default) for m in run_list if key in m]
        if not values:
            return default
        first = values[0]
        return first if all(v == first for v in values[1:]) else default

    for bidx, name in enumerate(baseline_names, start=1):
        cfg = baseline_cfgs[name]
        if report_each_run:
            print(f"[baseline] {name}")
        run_kwargs = dict(shared_sim_kwargs)
        run_kwargs.update(cfg)
        if name == "proposed":
            if proposed_preventive_policy not in (None, ""):
                run_kwargs["preventive_policy"] = str(proposed_preventive_policy)
        if name in {"prediction_only", "proposed"} and bool(use_frozen_calibration):
            run_kwargs["use_frozen_calibration"] = True
            if calibration_ranking_path not in (None, ""):
                run_kwargs["calibration_ranking_path"] = calibration_ranking_path
            if calibration_manifest_path not in (None, ""):
                run_kwargs["calibration_manifest_path"] = calibration_manifest_path
            if calibration_config_id not in (None, ""):
                run_kwargs["calibration_config_id"] = calibration_config_id
        def _baseline_progress(run_idx, run_total, seed, metrics):
            """Report baseline-suite progress for a completed seed run."""
            nonlocal runs_done_all
            runs_done_all = (bidx - 1) * int(num_runs) + int(run_idx)
            pct = 100.0 * runs_done_all / max(total_runs_all, 1)
            bar_len = 30
            fill = int(round(bar_len * pct / 100.0))
            bar = "#" * fill + "-" * (bar_len - fill)
            if report_each_run:
                print(
                    f"[progress] [{bar}] {pct:6.2f}% "
                    f"({runs_done_all}/{total_runs_all}) "
                    f"baseline={name} run={run_idx}/{run_total}",
                    flush=True,
                )
            if progress_cb is not None:
                try:
                    progress_cb(runs_done_all, total_runs_all, name, run_idx, run_total, seed, metrics)
                except Exception:
                    pass
        result = run_metrics_experiments(
            num_runs=num_runs,
            seed_start=seed_start,
            report_each_run=report_each_run,
            progress_cb=_baseline_progress,
            collect_time_metrics=collect_time_metrics,
            time_metrics_period_s=time_metrics_period_s,
            **run_kwargs,
        )
        all_results[name] = result
        summary = result.get("summary", {})
        run_list = result.get("runs", [])
        row = {"baseline": name, "num_runs": int(result.get("num_runs", 0))}
        for metric_name, stats in summary.items():
            row[f"{metric_name}_mean"] = float(stats.get("mean", np.nan))
            row[f"{metric_name}_var"] = float(stats.get("var", np.nan))
        row["preventive_policy"] = str(_uniform_run_value(run_list, "preventive_policy", ""))
        row["preventive_policy_source"] = str(_uniform_run_value(run_list, "preventive_policy_source", ""))
        row["selected_calibration_config_id"] = str(
            _uniform_run_value(run_list, "selected_calibration_config_id", "")
        )
        row["selected_calibration_source"] = str(
            _uniform_run_value(run_list, "selected_calibration_source", "")
        )
        rows.append(row)
        for tr in result.get("time_summary", []):
            tr_out = {"baseline": name}
            tr_out.update(tr)
            time_rows.append(tr_out)

    comparison_df = pd.DataFrame(rows)
    comparison_over_time_df = pd.DataFrame(time_rows)
    if not comparison_over_time_df.empty:
        pivot_exposure = comparison_over_time_df.pivot_table(
            index="t_s", columns="baseline", values="value_weighted_exposure_mean", aggfunc="first"
        )
        for col in ["proposed", "prediction_only", "reactive"]:
            if col not in pivot_exposure.columns:
                pivot_exposure[col] = np.nan
        if "prediction_only" in pivot_exposure.columns:
            den = pivot_exposure["prediction_only"].replace(0.0, np.nan)
            improvement = 100.0 * (pivot_exposure["prediction_only"] - pivot_exposure["proposed"]) / den
            comparison_over_time_df = comparison_over_time_df.merge(
                improvement.rename("proposed_vs_prediction_only_exposure_improvement_pct"),
                left_on="t_s",
                right_index=True,
                how="left",
            )
        if "reactive" in pivot_exposure.columns:
            den = pivot_exposure["reactive"].replace(0.0, np.nan)
            improvement = 100.0 * (pivot_exposure["reactive"] - pivot_exposure["proposed"]) / den
            comparison_over_time_df = comparison_over_time_df.merge(
                improvement.rename("proposed_vs_reactive_exposure_improvement_pct"),
                left_on="t_s",
                right_index=True,
                how="left",
            )

    if csv_path:
        comparison_df.to_csv(csv_path, index=False)
        base, ext = csv_path.rsplit(".", 1) if "." in csv_path else (csv_path, "csv")
        time_csv = f"{base}_over_time.{ext}"
        comparison_over_time_df.to_csv(time_csv, index=False)
        if report_each_run:
            print(f"[baseline] comparison csv written: {csv_path}")
            print(f"[baseline] over-time csv written: {time_csv}")

    return {"baselines": all_results, "comparison": comparison_df, "comparison_over_time": comparison_over_time_df}


# ============================================================================
# Visualization and demo entrypoints
# ============================================================================

def animate_demo_persistent(save_path=None, fps=5, duration_s=120, **sim_kwargs):
    """Run the production simulator with Matplotlib animation for interactive inspection."""
    frames = run_simulation_frames_persistent(dt=1.0, T_end=duration_s, fps=fps, **sim_kwargs)

    first = next(frames)
    W, H = first["W"], first["H"]
    fig, ax = plt.subplots(figsize=(8,6))
    ax.set_aspect('equal', adjustable='box')
    turn_space_m = sim_kwargs.get("turn_space_m", 20.0)
    ax.set_xlim(-turn_space_m - 10, W + turn_space_m + 10)
    ax.set_ylim(-turn_space_m - 10, H + turn_space_m + 10)
    bx,by = zip(* (first["boundary"] + [first["boundary"][0]]) )
    (boundary_line,) = ax.plot(bx, by, 'k-', lw=1)

    # zone patches
    zone_patches = []
    for cell in first["cells"]:
        if not cell:
            zone_patches.append(None); continue
        p = MplPolygon(cell, closed=True, fill=True, alpha=0.10, edgecolor='k', facecolor='#bbbbff', zorder=1)
        ax.add_patch(p); zone_patches.append(p)

    # row bands (visualize vineyard rows)
    row_spacing_m = sim_kwargs.get("row_spacing_m", 8.0 * 0.3048)
    row_width_m = sim_kwargs.get("row_width_m", 8.0 * 0.3048)
    headland_space_m = sim_kwargs.get("headland_space_m", 20.0)
    row_patches = []
    row_lines = None
    if row_spacing_m > 0 and row_width_m > 0:
        k = 0
        while True:
            y = headland_space_m + k * row_spacing_m
            if y - 0.5 * row_width_m > (H - headland_space_m):
                break
            y0 = y - 0.5 * row_width_m
            y1 = y + 0.5 * row_width_m
            # Draw continuous row bands
            p = MplPolygon([(headland_space_m, y0), (W - headland_space_m, y0),
                            (W - headland_space_m, y1), (headland_space_m, y1)],
                           closed=True, fill=True, alpha=0.12,
                           edgecolor='none', facecolor='#7a8f5a', zorder=0.5)
            ax.add_patch(p)
            row_patches.append(p)
            k += 1
        # Optional faint centerlines inside vineyard bounds
        lines = [((headland_space_m, headland_space_m + i * row_spacing_m),
                  (W - headland_space_m, headland_space_m + i * row_spacing_m)) for i in range(k)]
        row_lines = LineCollection(lines, colors="#5f6f47", linewidths=0.4, alpha=0.3, zorder=0.6)
        ax.add_collection(row_lines)

    # robot scatters
    uav_sc = ax.scatter([], [], s=20, c='#ff7f0e', edgecolors='k', zorder=3, label='UAV')
    ugv_sc = ax.scatter([], [], s=20, c='#1f77b4', edgecolors='k', zorder=3, label='UGV')

    # event scatters (ground truth + detections)
    truth_sc = ax.scatter([], [], s=40, c='#2ca02c', marker='x', zorder=4, label='Truth')
    det_sc = ax.scatter([], [], s=40, c='red', marker='x', zorder=5, label='Detection')

    # task scatters: active & completed
    det_act = ax.scatter([], [], s=80, c='red', marker='x', zorder=4, label='Deterring (active)')
    pat_act = ax.scatter([], [], s=60, c='blue', marker='D', zorder=4, label='Patrolling (active)')
    done_sc = ax.scatter([], [], s=30, c='#888888', marker='o', alpha=0.6, zorder=2, label='Completed')

    title = ax.set_title("")
    ax.legend(loc='upper right')

    # numeric labels near robots + right-side state panel
    robot_ids = sorted(first["poses"].keys())
    def _rid_num(rid):
        """Extract the numeric suffix used to order robot identifiers in the demo view."""
        digits = "".join(ch for ch in str(rid) if ch.isdigit())
        return digits if digits else str(rid)
    label_artists = {}
    for rid in robot_ids:
        x, y = first["poses"][rid]
        label_artists[rid] = ax.text(
            x + 1.2, y + 1.2, _rid_num(rid),
            fontsize=8, color="black", zorder=6,
            bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.7)
        )
    state_text = ax.text(
        1.01, 0.98, "", transform=ax.transAxes,
        va="top", ha="left", fontsize=9,
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cccccc", alpha=0.9)
    )

    def _split_robot_points(poses, profiles):
        """Split robot positions by platform type for demo plotting."""
        xu,yu,xg,yg = [],[],[],[]
        for rid,(x,y) in poses.items():
            if profiles[rid].type == 'UAV':
                xu.append(x); yu.append(y)
            else:
                xg.append(x); yg.append(y)
        return xu,yu,xg,yg

    def _split_tasks(active, done):
        """Split active task coordinates by action type for demo plotting."""
        xd,yd,xp,yp = [],[],[],[]
        for tr in active:
            if task_action_kind(tr) == "deterring":
                xd.append(tr["x"]); yd.append(tr["y"])
            else:
                xp.append(tr["x"]); yp.append(tr["y"])
        xz,yz = [],[]
        for tr in done:
            xz.append(tr["x"]); yz.append(tr["y"])
        return xd,yd,xp,yp,xz,yz

    def init():
        # robots
        """Initialize Matplotlib artists for the production demo animation."""
        xu,yu,xg,yg = _split_robot_points(first["poses"], first["profiles"])
        uav_sc.set_offsets(np.c_[xu,yu] if xu else np.empty((0,2)))
        ugv_sc.set_offsets(np.c_[xg,yg] if xg else np.empty((0,2)))
        # events
        tp = first.get("truth_pts", [])
        dp = first.get("det_pts", [])
        truth_sc.set_offsets(np.array(tp) if tp else np.empty((0,2)))
        det_sc.set_offsets(np.array(dp) if dp else np.empty((0,2)))
        # tasks
        xd,yd,xp,yp,xz,yz = _split_tasks(first["tasks_active"], first["tasks_done"])
        det_act.set_offsets(np.c_[xd,yd] if xd else np.empty((0,2)))
        pat_act.set_offsets(np.c_[xp,yp] if xp else np.empty((0,2)))
        done_sc.set_offsets(np.c_[xz,yz] if xz else np.empty((0,2)))
        state_lines = []
        rs = first.get("robot_states", {})
        active = [tr for tr in first.get("tasks_active", []) if tr.get("state") == "active"]
        task_by_robot = {}
        for tr in active:
            rid = tr.get("assigned_primary")
            if rid and rid not in task_by_robot:
                action_kind = task_action_kind(tr)
                action_name = task_action_name(tr)
                task_by_robot[rid] = f"{action_kind}/{action_name}#{tr.get('id','?')}"
        for rid in robot_ids:
            st = rs.get(rid, "unknown")
            cur_task = task_by_robot.get(rid, "-")
            state_lines.append(f"{_rid_num(rid)}: {st} | task: {cur_task}")
        state_text.set_text("Robots\n" + "\n".join(state_lines))
        title.set_text(f"t = {int(first['t'])} s")
        return (*[p for p in zone_patches if p], *row_patches, *( [row_lines] if row_lines else [] ),
                uav_sc, ugv_sc, truth_sc, det_sc, det_act, pat_act, done_sc,
                *label_artists.values(), state_text, boundary_line, title)

    def update(_):
        """Advance the production demo animation by one simulator frame."""
        try:
            snap = next(frames)
        except StopIteration:
            return (*[p for p in zone_patches if p], *row_patches, *( [row_lines] if row_lines else [] ),
                    uav_sc, ugv_sc, truth_sc, det_sc, det_act, pat_act, done_sc, boundary_line, title)

        # zones
        for patch, cell in zip(zone_patches, snap["cells"]):
            if patch is None or not cell: continue
            patch.set_xy(cell)

        # robots
        xu,yu,xg,yg = _split_robot_points(snap["poses"], snap["profiles"])
        uav_sc.set_offsets(np.c_[xu,yu] if xu else np.empty((0,2)))
        ugv_sc.set_offsets(np.c_[xg,yg] if xg else np.empty((0,2)))
        for rid in robot_ids:
            if rid in snap["poses"]:
                x, y = snap["poses"][rid]
                label_artists[rid].set_position((x + 1.2, y + 1.2))
                label_artists[rid].set_text(_rid_num(rid))
        # events
        tp = snap.get("truth_pts", [])
        dp = snap.get("det_pts", [])
        truth_sc.set_offsets(np.array(tp) if tp else np.empty((0,2)))
        det_sc.set_offsets(np.array(dp) if dp else np.empty((0,2)))

        # tasks
        xd,yd,xp,yp,xz,yz = _split_tasks(snap["tasks_active"], snap["tasks_done"])
        det_act.set_offsets(np.c_[xd,yd] if xd else np.empty((0,2)))
        pat_act.set_offsets(np.c_[xp,yp] if xp else np.empty((0,2)))
        done_sc.set_offsets(np.c_[xz,yz] if xz else np.empty((0,2)))

        state_lines = []
        rs = snap.get("robot_states", {})
        active = [tr for tr in snap.get("tasks_active", []) if tr.get("state") == "active"]
        task_by_robot = {}
        for tr in active:
            rid = tr.get("assigned_primary")
            if rid and rid not in task_by_robot:
                action_kind = task_action_kind(tr)
                action_name = task_action_name(tr)
                task_by_robot[rid] = f"{action_kind}/{action_name}#{tr.get('id','?')}"
        for rid in robot_ids:
            st = rs.get(rid, "unknown")
            cur_task = task_by_robot.get(rid, "-")
            state_lines.append(f"{_rid_num(rid)}: {st} | task: {cur_task}")
        state_text.set_text("Robots\n" + "\n".join(state_lines))

        title.set_text(f"t = {int(snap['t'])} s")
        return (*[p for p in zone_patches if p], *row_patches, *( [row_lines] if row_lines else [] ),
                uav_sc, ugv_sc, truth_sc, det_sc, det_act, pat_act, done_sc,
                *label_artists.values(), state_text, boundary_line, title)

    anim = FuncAnimation(fig, update, init_func=init,
                         frames=int(fps * (sim_kwargs.get("T_end", duration_s)/dt if "T_end" in sim_kwargs else duration_s)),
                         interval=1000/fps, blit=False, repeat=False)

    if save_path:
        anim.save(save_path, fps=fps, dpi=130)
    plt.show()
    return anim


if __name__ == "__main__":  
    animate_demo_persistent()
