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
    build_task_dispatch_candidate_buffer,
    extract_task_candidates_from_sestpp,
    run_task_location_estimation,
)
from planner_task_generation import (
    compute_preventive_capacity_state,
    current_busy_deterring_robots,
    prune_preventive_histories,
)
from planner_task_selection import select_preassignment_task_candidates
from calibration_config import load_frozen_sestpp_calibration
from tracking_export import export_named_tracking_state


# ============================================================================
# Communication and shared dispatch utilities
# ============================================================================

class EventBus:
    def __init__(self, robots: Dict[str, Robot], bytes_per_boundary_msg: int = 64, bytes_per_intervention_msg: int = 72):
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
    return (
        str(task_row.get("type", "")).strip().lower() == "deterring"
        and task_row.get("mode") not in (None, "", "none")
    )


def _is_direct_detection_task_row(task_row: dict) -> bool:
    return (
        str(task_row.get("type", "")).strip().lower() == "deterring"
        and task_row.get("mode") in (None, "", "none")
    )


def _finite_task_metric(task_row: dict, key: str, default: float = 0.0) -> float:
    try:
        value = float(task_row.get(key, default))
    except Exception:
        value = float(default)
    if not math.isfinite(value):
        return float(default)
    return float(value)


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


def _dispatch_priority_components(task_row: dict) -> dict:
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
        "eta_s": float(eta_s),
        "p_event": float(_finite_task_metric(task_row, "p_event", 0.0)),
        "selection_weight": float(_finite_task_metric(task_row, "selection_weight", 1.0)),
        "support": int(max(0, int(task_row.get("support", 0)))),
        "time": float(_finite_task_metric(task_row, "time", 0.0)),
    }


def _dispatch_priority_sort_key(task_row: dict) -> tuple:
    comp = _dispatch_priority_components(task_row)
    return (
        comp["utility"],
        comp["predicted_deltaJ"],
        comp["deltaJ_per_cost"],
        -comp["eta_s"],
        comp["p_event"],
        comp["selection_weight"],
        comp["support"],
        -comp["time"],
    )


def _dispatch_ordering_bucket(task_row: dict) -> str:
    if _is_direct_detection_task_row(task_row):
        return "direct_detection"
    return "regular_competition"


def _ordered_dispatch_candidates(candidate_tasks: list[dict]) -> list[dict]:
    direct_candidates = [dict(task) for task in candidate_tasks if _is_direct_detection_task_row(task)]
    regular_candidates = [dict(task) for task in candidate_tasks if not _is_direct_detection_task_row(task)]
    regular_candidates.sort(key=_dispatch_priority_sort_key, reverse=True)
    return direct_candidates + regular_candidates


def _build_dispatch_order_preview(candidate_tasks: list[dict], preview_limit: int = 25) -> list[dict]:
    ordered = _ordered_dispatch_candidates(candidate_tasks)
    preview = []
    for rank, task_row in enumerate(ordered[: max(int(preview_limit), 0)], start=1):
        comp = _dispatch_priority_components(task_row)
        preview.append(
            {
                "rank": int(rank),
                "ordering_bucket": _dispatch_ordering_bucket(task_row),
                "type": task_row.get("type"),
                "origin": task_row.get("origin"),
                "mode": task_row.get("mode"),
                "score": float(_finite_task_metric(task_row, "score", 0.0)),
                "utility": float(comp["utility"]),
                "predicted_deltaJ": float(comp["predicted_deltaJ"]),
                "deltaJ_per_cost": float(comp["deltaJ_per_cost"]),
                "eta_s": float(comp["eta_s"]),
                "p_event": float(comp["p_event"]),
                "selection_weight": float(comp["selection_weight"]),
                "support": int(comp["support"]),
            }
        )
    return preview


def _select_patrol_replacement_task(active_tasks: list[dict], assigned_primary: str, incoming_task: dict) -> dict | None:
    patrol_active = [
        tr for tr in active_tasks
        if (
            tr.get("assigned_primary") == assigned_primary
            and str(tr.get("state", "")).strip().lower() == "active"
            and str(tr.get("type", "")).strip().lower() == "patrolling"
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
    alpha_inhib: float,
    omega_inhib: float,
    mu_base: float,
    bg_ema: float,
) -> dict:
    profile_values = dict(planner_profile_values or {})
    profile_requested = bool(profile_values.get("use_frozen_calibration", False)) and (
        str(simulation_mode).strip().lower() == "proposed"
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
        alpha_inhib = float(selected_config.model_alpha_inhib)
        omega_inhib = float(selected_config.model_omega_inhib)
        mu_base = float(selected_config.model_mu_base)
        bg_ema = float(selected_config.model_bg_ema)
        source = "argument" if bool(use_frozen_calibration) else (
            f"profile:{planner_profile}" if planner_profile else "profile"
        )

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
        "alpha_inhib": float(alpha_inhib),
        "omega_inhib": float(omega_inhib),
        "mu_base": float(mu_base),
        "bg_ema": float(bg_ema),
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

    # --- power (Laguerre) diagram from anchors + health→weights ---
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
        self.buf = deque(maxlen=maxlen)
    def extend(self, tasks):
        self.buf.extend(tasks)
    def list(self):
        return list(self.buf)


def _build_demo_tracking_links(active_tasks: list[dict], motion_commands: list[MotionCommand]) -> dict[str, Any]:
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
    # Zones (health → weight), anchored to **initial positions**
    mode="direct", scale=1500.0, gamma=1.0,
    health_threshold=0.25,   # trigger-only partitioning (optional)
    debug_zone_areas=False,
    # SESTPP
    NX=120, NY=96, sigma=16.0, omega=700.0, omega_inhib=900.0, mu_base=5e-5, bg_ema=1e-6,
    alpha_inhib=0.45,
    # Detections near robots
    detect_rate_per_robot=0.01, detect_sigma_m=10.0,

    bird_stay_mean_s=20.0,       # how long a bird lingers near a robot (exp. mean)
    bird_detection_prob=0.10,    # truth-event observation probability within range; per-step while present in fallback mode
    per_robot_cooldown_s=10.0,   # minimum time between detections for each robot
    max_detections_per_step=2,   # safety cap per step per robot
    
    # Tasks / motion
    task_replan_period_s=10.0, arrival_radius_m=3.0, hold_time_s=20.0,
    # Dynamic task suppression near deterrence
    deterring_suppress_radius_m=20.0,
    deterring_suppress_window_s=60.0,
    # Task refresh pruning
    task_refresh_min_score=1e-4,
    task_max_age_s=120.0,
    enable_direct_detection_task_clustering=True,
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
    use_frozen_calibration=False,
    calibration_ranking_path=None,
    calibration_manifest_path=None,
    calibration_config_id=None,
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
    enable_intervention_feedback=None,
    include_fallback_patrol=None,
    enable_model_scored_deterring=None,
    patrol_hotspot_filter_mode="percentile",
    patrol_hotspot_score_percentile=97.0,
    patrol_hotspot_keep_top_k=None,
    patrol_feedback_inhibition_retention=1.0,
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
        alpha_inhib=float(alpha_inhib),
        omega_inhib=float(omega_inhib),
        mu_base=float(mu_base),
        bg_ema=float(bg_ema),
    )
    use_frozen_calibration = bool(calibration_resolution["use_frozen_calibration"])
    calibration_ranking_path = calibration_resolution.get("calibration_ranking_path")
    calibration_manifest_path = calibration_resolution.get("calibration_manifest_path")
    calibration_config_id = calibration_resolution.get("calibration_config_id")
    selected_calibration_config_id = str(calibration_resolution["selected_calibration_config_id"])
    selected_calibration_source = str(calibration_resolution["selected_calibration_source"])
    selected_calibration_summary_metrics = dict(calibration_resolution["selected_calibration_summary_metrics"])
    alpha_inhib = float(calibration_resolution["alpha_inhib"])
    omega_inhib = float(calibration_resolution["omega_inhib"])
    mu_base = float(calibration_resolution["mu_base"])
    bg_ema = float(calibration_resolution["bg_ema"])
    calibrated_model_alpha_inhib = float(alpha_inhib)
    calibrated_model_omega_inhib = float(omega_inhib)
    calibrated_model_mu_base = float(mu_base)
    calibrated_model_bg_ema = float(bg_ema)

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
    alpha_in = 0.6 / omega
    alpha_cross = 0.4 * alpha_in
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

    # --- Live kinematics (start at initial positions; no dock logic) ---
    pose = {r['id']: tuple(r['anchor']) for r in robots_def}
    goal = {r['id']: None for r in robots_def}
    next_idle_retarget = {r['id']: -1.0 for r in robots_def}
    loiter_until = {r['id']: -1.0 for r in robots_def}
    bird_present_until = {r['id']: -1.0 for r in robots_def}
    last_detection_time = {r['id']: -1.0 for r in robots_def}
    bus = EventBus(robots, bytes_per_boundary_msg=bytes_per_boundary_msg,
                   bytes_per_intervention_msg=bytes_per_intervention_msg)

    # --- Metrics accumulators ---
    pending_event_onsets = deque(maxlen=5000)  # dicts: {x,y,t,responded}
    response_times = []
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
            c = beta_u * k * math.exp(-dt / max(omega_u, 1e-9))
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
        cutoff_t = float(now_t) - float(truth_metrics_window_s)
        while truth_candidate_event_times_last_hour and truth_candidate_event_times_last_hour[0] < cutoff_t:
            truth_candidate_event_times_last_hour.popleft()
        while truth_suppressed_event_times_last_hour and truth_suppressed_event_times_last_hour[0] < cutoff_t:
            truth_suppressed_event_times_last_hour.popleft()

    def _record_truth_window_event(event_t, suppressed):
        event_t = float(event_t)
        truth_candidate_event_times_last_hour.append(event_t)
        if suppressed:
            truth_suppressed_event_times_last_hour.append(event_t)
        _prune_truth_event_window(event_t)

    def _current_truth_window_metrics(now_t):
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

    def _process_truth_event(x, y, t_now, enqueue_tasks=True, record_metrics=True):
        nonlocal value_weighted_exposure
        nonlocal truth_detection_opportunities, truth_detections_observed
        nonlocal truth_detections_missed_range, truth_detections_missed_false_negative
        truth_events.append((x, y, t_now))
        truth_event_times.append(float(t_now))
        recent_truth.append((x, y, t_now))
        if record_metrics:
            value_weighted_exposure += float(value_weight(x, y))
        owner = None
        for rr in robots_def:
            zid = rr['id']
            zone_rr = id_to_cell.get(zid, [])
            if zone_rr and point_in_polygon(x, y, zone_rr):
                owner = zid; break
        if owner is not None:
            truth_detection_opportunities += 1
            # Only detect if within range of the owning robot
            ox, oy = pose[owner]
            if math.hypot(x - ox, y - oy) > detect_range_m:
                truth_detections_missed_range += 1
                return
            if rng.random() > truth_event_detection_prob:
                truth_detections_missed_false_negative += 1
                return
            truth_detections_observed += 1
            b = robots[owner].ingest_detection(x, y, t_now)
            bus.send_boundary_events(b, source_id=owner)
            if enqueue_tasks:
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
        mode = task_row.get("mode")
        origin = str(task_row.get("origin", "")).strip().lower()
        if mode not in (None, "", "none"):
            return "model_scored"
        if origin == "detection":
            return "direct_detection"
        # Conservative fallback: tasks with no explicit mode are treated as direct.
        return "direct_detection"

    def _is_direct_detection_task(task_row):
        return (
            str(task_row.get("type", "")).strip().lower() == "deterring"
            and _deterring_source(task_row) == "direct_detection"
        )

    def _task_buffer_key(task):
        return (
            str(task.get("type", "")).strip().lower(),
            round(float(task.get("x", float("nan"))), 2),
            round(float(task.get("y", float("nan"))), 2),
            round(float(task.get("time", float("nan"))), 0),
        )

    def _direct_detection_refresh_status(task_row):
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
        nonlocal direct_detection_task_refresh_active
        task_row["last_detection_t"] = float(t_now)
        task_row["merged_detection_count"] = int(task_row.get("merged_detection_count", 1)) + 1
        task_row["cluster_refresh_count"] = int(task_row.get("cluster_refresh_count", 0)) + 1
        direct_detection_task_refresh_active += 1

    def _cluster_direct_detection_candidate_tasks(tasks):
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

    def _global_hotspots(top_k):
        """Collect top hotspots across robots by score."""
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

    def _compact_task_rows(rows, task_type=None, limit=None):
        out = []
        limit_n = None if limit is None else max(int(limit), 0)
        for row in rows:
            if task_type is not None and str(row.get("type", "")).strip().lower() != str(task_type).strip().lower():
                continue
            out.append(
                {
                    "id": row.get("id"),
                    "type": row.get("type"),
                    "origin": row.get("origin"),
                    "mode": row.get("mode"),
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
                }
            )
            if limit_n is not None and len(out) >= limit_n:
                break
        return out

    def _count_task_rows_by_origin(rows, task_type=None):
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
    direct_deterring_arrivals_by_robot = {rid: deque() for rid in robots}  # stores t_assigned
    model_deterring_admissions_by_robot = {rid: deque() for rid in robots}  # stores t_assigned
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
        candidate_count=0,
        accepted_tasks=[],
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
        },
        rejected_model_det_tasks=[],
        ordering_policy="",
        ordered_candidate_preview=[],
        replaced_patrol_count=0,
        active_load_after_dispatch={rid: 0 for rid in robots},
        active_patrol_load_after_dispatch={rid: 0 for rid in robots},
        active_model_det_load_after_dispatch={rid: 0 for rid in robots},
        model_deterring_accepted_total=0,
        model_deterring_rejected_budget_total=0,
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
        value_weighted_exposure=0.0,
        mean_response_time_s=float("nan"),
        completed_tasks_total=0,
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
        nonlocal cells, id_to_cell
        if not any(profiles[rid].health <= health_threshold for rid in profiles):
            return False

        partitioner.recompute(force=True)
        cells = partitioner.cells_for_ids()
        id_to_cell = {rid: cells[i] for i, rid in enumerate(partitioner.ids)}
        if debug_zone_areas:
            def _poly_area(poly):
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
        return True

    def _run_truth_generation_algorithm(now_t):
        """Ground-truth event generation and local/boundary detection ingestion."""
        nonlocal truth_candidate_events, truth_accepted_events, truth_suppressed_events
        nonlocal suppression_effect_sum

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
        run_task_location_estimation(
            taskgen=taskgen,
            robots=robots,
            now_t=now_t,
            enable_patrolling=bool(enable_patrolling),
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
            value_weight_fn=value_weight,
            deterring_modes=deterring_modes,
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
                "value_weight_fn": value_weight,
                "deterring_modes": deterring_modes,
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

        return TaskGenerationStageResult(
            now_t=float(now_t),
            patrolling_enabled=bool(enable_patrolling),
            busy_deterring_robots=sorted(str(rid) for rid in busy_deterring_robots),
            candidate_tasks=list(selection_buffer["selected_candidate_tasks"]),
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
        nonlocal next_tid, model_deterring_accepted, model_deterring_accepted_by_source, model_deterring_rejected_budget, consumed_task_keys
        nonlocal model_deterring_rejected_budget_count_mode, model_deterring_rejected_budget_utility_mode
        nonlocal planner_rejected_unassigned, planner_rejected_task_cap
        nonlocal planner_rejected_patrol_cap, planner_rejected_patrol_locked_model_det, planner_rejected_model_det_cap
        nonlocal planner_rejected_model_det_cycle_cap, planner_rejected_model_det_busy_primary
        nonlocal planner_rejected_model_det_busy_fallback_quality, planner_rejected_model_det_direct_conflict
        nonlocal planner_accepted_model_det_idle_primary, planner_accepted_model_det_busy_primary
        nonlocal planner_replaced_patrol

        active_load = dict(task_stage.active_load_before_dispatch)
        active_patrol_load = dict(task_stage.active_patrol_load_before_dispatch)
        active_model_det_load = dict(task_stage.active_model_det_load_before_dispatch)
        accepted_tasks = []
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
        }
        replaced_patrol_count = 0
        rejected_model_det_tasks = []
        assigner.set_robot_poses(pose if bool(use_live_robot_pose_for_task_planning) else None)
        model_deterring_accepted_this_cycle = 0
        ordering_policy = (
            "direct-detection deterring tasks keep absolute priority; remaining patrol and "
            "model-scored preventive tasks share one lexicographic ordering by utility/score, "
            "predicted_deltaJ, deltaJ_per_cost, and lower ETA; admission constraints still "
            "apply afterward."
        )
        ordered_candidates = _ordered_dispatch_candidates(task_stage.candidate_tasks)
        ordered_candidate_preview = _build_dispatch_order_preview(task_stage.candidate_tasks)

        def _has_direct_detection_conflict(task_row, assigned_primary):
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
            return passes_busy_fallback_quality(
                task_row=task_row,
                p_event_min=float(model_deterring_busy_fallback_p_event_min),
                deltaJ_per_cost_min=float(model_deterring_busy_fallback_deltaJ_per_cost_min),
                eta_s_max=float(model_deterring_busy_fallback_eta_s_max),
            )

        def _evict_active_patrol_task(evict_tr):
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

        def _select_assignment_algorithm(task_row):
            """Assignment scoring and robot selection before dispatch admission gates."""
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

        for t in ordered_candidates:
            assignment = _select_assignment_algorithm(t)
            ttype = assignment["task_type"]
            is_model_det = bool(assignment["is_model_det"])
            assigned_primary = assignment["assigned_primary"]
            assigned_secondary = assignment["assigned_secondary"]
            if assigned_primary is None:
                _record_model_det_rejection("unassigned", t, assigned_primary, assigned_secondary)
                planner_rejected_unassigned += 1
                rejected_counts["unassigned"] += 1
                continue

            assigned_primary_busy = active_load.get(assigned_primary, 0) > 0

            if not _apply_patrol_lock_gating_algorithm(ttype, assigned_primary, now_t):
                continue

            gating = _evaluate_model_deterring_dispatch_gating_algorithm(
                t,
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
                _record_model_det_rejection(gating["reason"], t, assigned_primary, assigned_secondary)
                _apply_model_deterring_dispatch_rejection_accounting(gating["reason"])
                if gating["reason"] == "budget":
                    if budget_mode == "utility_per_hour":
                        model_deterring_rejected_budget_utility_mode += 1
                    else:
                        model_deterring_rejected_budget_count_mode += 1
                continue

            if active_load.get(assigned_primary, 0) >= int(max_active_tasks_per_robot):
                if (ttype == "patrolling") or is_model_det:
                    worst_patrol = _select_patrol_replacement_task(active_tasks, assigned_primary, t)
                    if worst_patrol is None:
                        _record_model_det_rejection("task_cap", t, assigned_primary, assigned_secondary)
                        planner_rejected_task_cap += 1
                        rejected_counts["task_cap"] += 1
                        continue
                    _evict_active_patrol_task(worst_patrol)
                    replaced_patrol_count += 1

            if ttype == "patrolling" and active_patrol_load.get(assigned_primary, 0) >= int(max_active_patrolling_per_robot):
                worst_patrol = _select_patrol_replacement_task(active_tasks, assigned_primary, t)
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
                accepted_origin = str(t.get("origin", "unknown")).strip().lower() or "unknown"
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
                **t,
                "assigned_primary": assigned_primary,
                "assigned_secondary": assigned_secondary,
                "state": "active",
                "started_hold": None,
                "t_assigned": float(now_t),
            }
            if is_model_det:
                accepted_task["assigned_eta_s"] = _assigned_robot_eta_seconds(
                    assigned_primary,
                    (float(t.get("x", 0.0)), float(t.get("y", 0.0))),
                )
                accepted_task["persist_lock_until_t"] = _model_deterring_lock_until_t(accepted_task, now_t)
            active_tasks.append(accepted_task)
            accepted_tasks.append(dict(accepted_task))
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
                goal[assigned_primary] = (t["x"], t["y"])
                if debug_movement:
                    print(f"[goal] {assigned_primary} -> ({t['x']:.1f},{t['y']:.1f}) type={t['type']}")
            next_tid += 1

        return DispatchStageResult(
            now_t=float(now_t),
            candidate_count=int(len(task_stage.candidate_tasks)),
            accepted_tasks=accepted_tasks,
            rejected_counts=rejected_counts,
            rejected_model_det_tasks=rejected_model_det_tasks,
            ordering_policy=str(ordering_policy),
            ordered_candidate_preview=ordered_candidate_preview,
            replaced_patrol_count=int(replaced_patrol_count),
            active_load_after_dispatch=dict(active_load),
            active_patrol_load_after_dispatch=dict(active_patrol_load),
            active_model_det_load_after_dispatch=dict(active_model_det_load),
            model_deterring_accepted_total=int(model_deterring_accepted),
            model_deterring_rejected_budget_total=int(model_deterring_rejected_budget),
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
        return _nearest_free_lane_y(y)

    def _is_at_headland(x):
        return x <= (0.0 + headland_m) or x >= (W - headland_m)

    def _nearest_headland_x(x):
        left = max(0.0, headland_space_m)
        right = min(float(W), W - headland_space_m)
        return left if x <= W * 0.5 else float(right)

    def _project_to_lane(rid, tgt):
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

    def _effective_goal(rid, tgt):
        return _project_to_lane(rid, tgt)

    def _step_to(rid, tgt, dt):
        x, y = pose[rid]
        tx, ty = _project_to_lane(rid, tgt)
        dx, dy = tx - x, ty - y
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return
        v = profiles[rid].speed_mps
        step = v * dt
        nx, ny = (tx, ty) if step >= d else (x + dx*(step/d), y + dy*(step/d))
        # Clamp to vineyard bounds so robots stay inside the map.
        min_x, max_x = 0.0, float(W)
        min_y, max_y = 0.0, float(H)
        clamped_x = min(max(nx, min_x), max_x)
        clamped_y = min(max(ny, min_y), max_y)
        step_dist = math.hypot(clamped_x - x, clamped_y - y)
        travel_distance_by_robot[rid] += step_dist
        e_per_m = uav_energy_per_m if profiles[rid].type == "UAV" else ugv_energy_per_m
        energy_by_robot[rid] += step_dist * float(e_per_m)
        pose[rid] = (clamped_x, clamped_y)

    def _match_active_task_for_robot_goal(rid, tgt):
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
        t_assigned = task_row.get("t_assigned", None)
        if t_assigned is not None:
            try:
                return float(t_assigned)
            except Exception:
                pass
        return float(task_row.get("time", t))

    def _is_active_model_deterring(task_row):
        return (
            str(task_row.get("state", "")).strip().lower() == "active"
            and str(task_row.get("type", "")).strip().lower() == "deterring"
            and _deterring_source(task_row) == "model_scored"
        )

    def _is_model_deterring_persist_locked(task_row, now_t):
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
        for tr in active_tasks:
            if str(tr.get("assigned_primary", "")) != str(rid):
                continue
            if _is_model_deterring_persist_locked(tr, now_t):
                return True
        return False

    def _assigned_robot_eta_seconds(rid, tgt_xy):
        if rid not in pose:
            return float("nan")
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
        rid = str(task_row.get("assigned_primary", ""))
        eta_s = _assigned_robot_eta_seconds(
            rid,
            (float(task_row.get("x", 0.0)), float(task_row.get("y", 0.0))),
        )
        if not math.isfinite(eta_s):
            eta_s = max(0.0, float(task_row.get("eta_s", 0.0)))
        lock_duration_s = max(
            float(model_deterring_min_persistence_lifetime_s),
            float(model_deterring_persistence_buffer_s)
            + float(hold_time_s)
            + float(model_deterring_persistence_eta_multiplier) * eta_s,
        )
        lock_duration_s = min(lock_duration_s, float(model_deterring_max_persistence_lifetime_s))
        return float(now_t) + float(lock_duration_s)

    def _start_deterring_hold(rid, task_row, now_t):
        task_row["started_hold"] = float(now_t)
        loiter_until[rid] = float(now_t) + float(hold_time_s)

    def _complete_deterring_task(rid, task_row, now_t):
        nonlocal direct_detection_task_response_matches
        task_row["state"] = "done"
        task_row["t_done"] = float(now_t)
        completed_tasks.append(task_row)
        t_assigned = float(task_row.get("t_assigned", task_row.get("time", now_t)))
        service_history_by_robot[rid].append((float(now_t), max(0.0, float(now_t) - t_assigned)))
        completed_count_by_type["deterring"] += 1
        completed_task_scores.append(float(task_row.get("score", 0.0)))
        mode = task_row.get("mode")
        params = deterring_modes.get(mode, {}) if mode else {}
        if bool(use_mode_dependent_truth_suppression) and params:
            beta_u = float(params.get("beta", beta_true))
            sigma_u = float(params.get("sigma", sigma_true))
            omega_u = float(params.get("omega", omega_true))
            mode_label = str(mode)
        else:
            beta_u = float(beta_true)
            sigma_u = float(sigma_true)
            omega_u = float(omega_true)
            mode_label = str(mode) if mode else "direct_detection"
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
        })
        feedback_beta = float(params.get("beta", 1.0))
        feedback_omega = float(params.get("omega", robots[rid].m.omega_inhib))
        feedback_sigma = float(params.get("sigma", robots[rid].m.sigma))
        if enable_intervention_feedback:
            nonlocal step_intervention_feedback_applied
            step_intervention_feedback_applied += 1
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
                    response_times.append(float(now_t - ev["t"]))
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
                response_times.append(float(now_t - ev["t"]))
                matched_count = 1
        direct_detection_task_response_matches += int(matched_count)
        if mon is not None and getattr(mon, "enabled", False):
            mon.event_task("complete", task_row)
        active_tasks[:] = [x for x in active_tasks if x["id"] != task_row["id"]]
        goal[rid] = None
        loiter_until[rid] = -1.0

    def _complete_patrolling_task(rid, task_row, now_t):
        task_row["state"] = "done"
        task_row["t_done"] = float(now_t)
        completed_tasks.append(task_row)
        t_assigned = float(task_row.get("t_assigned", task_row.get("time", now_t)))
        service_history_by_robot[rid].append((float(now_t), max(0.0, float(now_t) - t_assigned)))
        completed_count_by_type["patrolling"] += 1
        completed_task_scores.append(float(task_row.get("score", 0.0)))
        if mon is not None and getattr(mon, "enabled", False):
            mon.event_task("complete", task_row)
        active_tasks[:] = [x for x in active_tasks if x["id"] != task_row["id"]]
        goal[rid] = None

    def _process_near_goal_model_deterring_before_replan(now_t):
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
                elif float(now_t) >= float(tr["started_hold"]) + float(hold_time_s):
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
        truth_candidate_event_times_last_hour.clear()
        truth_suppressed_event_times_last_hour.clear()
        suppression_effect_sum = 0.0
        suppression_effect_by_mode.clear()
        suppression_effect_by_source = {"direct_detection": 0.0, "model_scored": 0.0}
        t_start = warmup_s

    t = t_start
    t_report_offset = t_start
    t_end = t_start + float(T_end)
    last_replan = -1e9

    def _task_intensity_score(tr):
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
        out = dict(deterring_quality_cache)
        det_done = [tr for tr in completed_tasks if str(tr.get("type", "")).strip().lower() == "deterring"]
        if not det_done:
            return out

        def _safe_div(a, b):
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
                        str(tr.get("type", "")).strip().lower() == "deterring"
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
                       str(tr.get("type", "")).strip().lower() != "patrolling"
                       or (_task_intensity_score(tr) >= task_refresh_min_score)
                   )
            ]
            _spawn_and_assign_new_tasks(now_t=t, patrolling_only=False)
            last_replan = t

        # --------------------------------------------------------------------
        # Stage 4: Motion execution and task completion checks
        # --------------------------------------------------------------------
        motion_commands = []
        for r in robots_def:
            rid = r['id']
            command_source = "holding"
            command_type = "hold"
            # If holding at a deterring site, keep holding
            if loiter_until[rid] > t:
                pass
            else:
                command_source = "existing_goal" if goal[rid] is not None else "idle"
                command_type = "move" if goal[rid] is not None else "idle"
                if preempt_deterring_goals:
                    # If an active deterring task exists for this robot, prioritize it over patrol goals.
                    det_candidates = [
                        tr for tr in active_tasks
                        if (
                            tr.get("assigned_primary") == rid
                            and str(tr.get("state", "")).strip().lower() == "active"
                            and str(tr.get("type", "")).strip().lower() == "deterring"
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
                            key=lambda tr: math.hypot(float(tr.get("x", 0.0)) - px, float(tr.get("y", 0.0)) - py),
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
                # If idle and there exists an active task assigned to this robot, pick nearest one
                if goal[rid] is None:
                    candidates = [tr for tr in active_tasks if tr["assigned_primary"] == rid and tr["state"]=="active"]
                    if candidates:
                        # pick nearest
                        px,py = pose[rid]
                        tid, gx, gy = min(((tr["id"], tr["x"], tr["y"]) for tr in candidates),
                                          key=lambda z: math.hypot(z[1]-px, z[2]-py))
                        goal[rid] = (gx, gy)
                        command_source = "assigned_task"
                        command_type = "move"
                    elif idle_roam_enabled and (t >= next_idle_retarget[rid]):
                        # No assigned work: keep robot moving with a local roam goal.
                        px, py = pose[rid]
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
                if goal[rid] is not None:
                    if motion_orchestration_mode == "local":
                        _step_to(rid, goal[rid], dt)
            if loiter_until[rid] > t:
                command_pose = tuple(pose[rid])

            assigned_task_for_command = _match_active_task_for_robot_goal(rid, goal[rid])
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
                        if tr["type"] == "deterring":
                            # Start hold if not started; else complete when time passed
                            if tr["started_hold"] is None:
                                _start_deterring_hold(rid, tr, t)
                            elif t >= tr["started_hold"] + hold_time_s:
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
                        stale_goal_clears += 1

        motion_execution_backend = publish_motion_commands(
            now_t=t,
            dt=dt,
            motion_orchestration_mode=motion_orchestration_mode,
            motion_command_callback=motion_command_callback,
            commands=motion_commands,
            pose=pose,
            goal=goal,
        )

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
        final_step = (t + dt > t_end)
        if final_step:
            deterring_quality_cache = _compute_deterring_quality()
        diag_counts = getattr(taskgen, "diag_counts", {})
        def _diag_source_counts(prefix):
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
            try:
                value = float(selected_calibration_metrics_map.get(name, float("nan")))
            except Exception:
                return float("nan")
            return float(value) if np.isfinite(value) else float("nan")

        metrics = {
            "value_weighted_exposure": float(value_weighted_exposure),
            "mean_response_time_s": float(np.mean(response_times)) if response_times else float("nan"),
            "response_samples": int(len(response_times)),
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
            "robot_longest_idle_s_by_robot": {rid: float(v) for rid, v in robot_idle_streak_max.items()},
            "robot_tail_idle_s_by_robot": {rid: float(v) for rid, v in robot_idle_streak.items()},
            "robot_task_utilization_mean": float(np.nanmean(list(robot_utilization_by_robot.values()))) if robot_utilization_by_robot else float("nan"),
            "robot_idle_fraction_mean": float(np.nanmean(list(robot_idle_fraction_by_robot.values()))) if robot_idle_fraction_by_robot else float("nan"),
            "robot_moving_with_task_fraction_mean": float(np.nanmean(list(robot_moving_with_task_fraction_by_robot.values()))) if robot_moving_with_task_fraction_by_robot else float("nan"),
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
            "calibrated_model_alpha_inhib": float(calibrated_model_alpha_inhib),
            "calibrated_model_omega_inhib": float(calibrated_model_omega_inhib),
            "calibrated_model_mu_base": float(calibrated_model_mu_base),
            "calibrated_model_bg_ema": float(calibrated_model_bg_ema),
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
            "value_weighted_exposure": float(value_weighted_exposure),
            "mean_response_time_s": float(np.mean(response_times)) if response_times else float("nan"),
            "completed_tasks_total": int(total_completed),
            "travel_distance_total": float(total_distance),
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
            "calibrated_model_alpha_inhib": float(calibrated_model_alpha_inhib),
            "calibrated_model_omega_inhib": float(calibrated_model_omega_inhib),
            "calibrated_model_mu_base": float(calibrated_model_mu_base),
            "calibrated_model_bg_ema": float(calibrated_model_bg_ema),
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
            **_current_truth_window_metrics(t_end),
            "truth_suppression_effect_mean": (float(suppression_effect_sum) / float(truth_candidate_events)) if truth_candidate_events > 0 else float("nan"),
            "truth_suppression_effect_sum": float(suppression_effect_sum),
            **deterring_quality_cache,
            "forecast_recall_at_k": float(np.mean(forecast_recall_vals)) if forecast_recall_vals else float("nan"),
            "forecast_precision_at_k": float(np.mean(forecast_precision_vals)) if forecast_precision_vals else float("nan"),
            "forecast_lead_time_s": float(np.mean(forecast_lead_times)) if forecast_lead_times else float("nan"),
        }
        completed_this_step = completed_tasks[step_completed_before:]
        completed_patrolling_this_step = int(
            sum(1 for tr in completed_this_step if str(tr.get("type", "")).strip().lower() == "patrolling")
        )
        completed_deterring_this_step = int(
            sum(1 for tr in completed_this_step if str(tr.get("type", "")).strip().lower() == "deterring")
        )
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
            completed_patrolling_this_step=completed_patrolling_this_step,
            completed_deterring_this_step=completed_deterring_this_step,
            stale_goal_clears_this_step=int(stale_goal_clears - step_stale_goal_clears_before),
            holding_robot_count=int(sum(1 for state in robot_states_now.values() if state == "holding")),
            moving_robot_count=int(sum(1 for state in robot_states_now.values() if state == "moving")),
            idle_robot_count=int(sum(1 for state in robot_states_now.values() if state == "idle")),
        )
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
            value_weighted_exposure=float(final_metrics.get("value_weighted_exposure", float("nan"))),
            mean_response_time_s=float(final_metrics.get("mean_response_time_s", float("nan"))),
            completed_tasks_total=int(final_metrics.get("completed_tasks_total", 0)),
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
            "value_weighted_exposure",
            "completed_tasks_total",
            "boundary_message_count",
            "model_deterring_accepted",
            "model_deterring_generated",
            "model_deterring_rejected_budget",
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
        ]

    def _sample_time_metrics(snap):
        m = snap.get("metrics", {})
        t_s = float(snap.get("t", 0.0))
        row = {"t_s": t_s}
        for k in time_metrics_fields:
            row[k] = float(m.get(k, np.nan))
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
        return np.array([m.get(key, np.nan) for m in run_metrics], dtype=float)

    def _safe_stats(key):
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
        "calibrated_model_alpha_inhib": _safe_stats("calibrated_model_alpha_inhib"),
        "calibrated_model_omega_inhib": _safe_stats("calibrated_model_omega_inhib"),
        "calibrated_model_mu_base": _safe_stats("calibrated_model_mu_base"),
        "calibrated_model_bg_ema": _safe_stats("calibrated_model_bg_ema"),
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
            if bool(use_frozen_calibration):
                run_kwargs["use_frozen_calibration"] = True
                if calibration_ranking_path not in (None, ""):
                    run_kwargs["calibration_ranking_path"] = calibration_ranking_path
                if calibration_manifest_path not in (None, ""):
                    run_kwargs["calibration_manifest_path"] = calibration_manifest_path
                if calibration_config_id not in (None, ""):
                    run_kwargs["calibration_config_id"] = calibration_config_id
        def _baseline_progress(run_idx, run_total, seed, metrics):
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
        xu,yu,xg,yg = [],[],[],[]
        for rid,(x,y) in poses.items():
            if profiles[rid].type == 'UAV':
                xu.append(x); yu.append(y)
            else:
                xg.append(x); yg.append(y)
        return xu,yu,xg,yg

    def _split_tasks(active, done):
        xd,yd,xp,yp = [],[],[],[]
        for tr in active:
            if tr["type"] == "deterring":
                xd.append(tr["x"]); yd.append(tr["y"])
            else:
                xp.append(tr["x"]); yp.append(tr["y"])
        xz,yz = [],[]
        for tr in done:
            xz.append(tr["x"]); yz.append(tr["y"])
        return xd,yd,xp,yp,xz,yz

    def init():
        # robots
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
                mode = tr.get("mode")
                mode_txt = f"/{mode}" if mode else ""
                task_by_robot[rid] = f"{tr.get('type','?')}{mode_txt}#{tr.get('id','?')}"
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
                mode = tr.get("mode")
                mode_txt = f"/{mode}" if mode else ""
                task_by_robot[rid] = f"{tr.get('type','?')}{mode_txt}#{tr.get('id','?')}"
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
